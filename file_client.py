"""Reliable encrypted file protocol over a peer-routed UDP callback.

Chunk ACKs mean accepted bytes; only a matching receiver FILE_RESULT means
verified, atomically published contents. FILE_QUERY recovers lost outcomes.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable

from protocol import Packet, MSG_DATA, STATUS_OK
from file_transfer import (OutgoingFile, FileReceiver, FileTransferError,
                           encode_secure_json, decode_secure_json,
                           FILE_META, FILE_CHUNK)
from config import WINDOW_SIZE, RETRY_TIMEOUT, MAX_RETRIES
from stream_transport import CubicWindow


class FileTransferHandler:
    MAX_ACTIVE = 8
    MAX_HISTORY = 256
    MAX_CONGESTION_WINDOW = 64

    def __init__(self, send_packet_fn: Callable[[Packet, str], None],
                 next_seq_fn: Callable[[], int], download_dir='downloads'):
        self.send_packet_fn, self.next_seq_fn = send_packet_fn, next_seq_fn
        self.receiver = FileReceiver(download_dir)
        self.transfers = []
        self._lock = threading.RLock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._active = {}
        self._workers = set()
        self._closed = threading.Event()

    def _trim(self):
        # Never evict active transfers to meet a history target.
        active_receive = set(self.receiver.incoming)
        while len(self.transfers) > self.MAX_HISTORY:
            index = next((i for i, r in enumerate(self.transfers)
                          if r['file_id'] not in self._active and r['file_id'] not in active_receive), None)
            if index is None:
                break
            self.transfers.pop(index)

    def send_file(self, filepath: str | Path, recipient: str,
                  all_recipients: list[str] | None = None) -> str:
        targets = list(dict.fromkeys(all_recipients or [])) if recipient == '*' else [recipient]
        if not targets or any(not isinstance(t, str) or not t or t == '*' for t in targets):
            raise FileTransferError('Missing valid file recipient')
        last_id = ''
        for target in targets:
            outgoing = OutgoingFile.from_path(filepath)
            with self._lock:
                if self._closed.is_set():
                    raise FileTransferError('Client closed')
                if len(self._active) >= self.MAX_ACTIVE:
                    raise FileTransferError('Too many active sending transfers')
                record = dict(direction='send', file_id=outgoing.file_id, filename=outgoing.filename,
                              peer=target, status='sending', progress=0, total_chunks=len(outgoing.chunks),
                              retransmissions=0)
                self.transfers.append(record)
                self._active[outgoing.file_id] = dict(peer=target, record=record, outgoing=outgoing,
                                                     event=threading.Event(), result=None)
                worker = threading.Thread(target=self._send_worker, args=(outgoing,target,record), daemon=True)
                self._workers.add(worker)
                self._trim()
                worker.start()
                last_id = outgoing.file_id
        return last_id

    def _packet(self, message):
        return Packet(MSG_DATA, STATUS_OK, self.next_seq_fn(), encode_secure_json(message))

    def _register_wait(self, fid, index):
        event = threading.Event()
        with self._pending_lock:
            self._pending[(fid,index)] = event
        return event

    def _unregister(self, fid, index):
        with self._pending_lock:
            self._pending.pop((fid,index),None)

    def _result(self, fid):
        with self._lock:
            active = self._active.get(fid)
            return active['result'] if active else None

    def _check_running(self):
        if self._closed.is_set():
            raise FileTransferError('Client closed; completion unconfirmed')

    def _send_reliable_one(self, message, recipient, file_id, index):
        event = self._register_wait(file_id,index)
        packet = self._packet(message)
        try:
            for _ in range(MAX_RETRIES):
                self._check_running()
                self.send_packet_fn(packet,recipient)
                deadline = time.monotonic()+RETRY_TIMEOUT
                while not event.is_set() and not self._result(file_id):
                    self._check_running()
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        break
                    event.wait(min(remaining,.01))
                if event.is_set() or self._result(file_id):
                    return
            raise TimeoutError(f'Timeout ACK file_id={file_id} index={index}')
        finally:
            self._unregister(file_id,index)

    def _send_worker(self, outgoing, recipient, record):
        fid = outgoing.file_id
        # WINDOW_SIZE is the initial slow-start threshold, not a fixed window.
        # A separate capacity permits CUBIC avoidance to grow after slow start.
        controller = CubicWindow(max_window=self.MAX_CONGESTION_WINDOW,
                                 initial_ssthresh=max(2,WINDOW_SIZE))
        flight = {}
        next_index = acknowledged = 0
        try:
            self._send_reliable_one(outgoing.metadata_message(recipient),recipient,fid,-1)
            total = len(outgoing.chunks)
            while acknowledged < total and not self._result(fid):
                self._check_running()
                now = time.monotonic()
                for index, entry in list(flight.items()):
                    if entry['event'].is_set():
                        controller.on_ack(rtt=max(.000001,now-entry['time']) if entry['retries']==0 else None)
                        self._unregister(fid,index)
                        del flight[index]
                        acknowledged += 1
                while next_index < total and len(flight) < controller.window and not self._result(fid):
                    index = next_index
                    entry = {'event': self._register_wait(fid,index), 'time': time.monotonic(),
                             'retries': 0, 'packet': self._packet(outgoing.chunk_message(index,recipient))}
                    flight[index] = entry
                    self.send_packet_fn(entry['packet'],recipient)
                    next_index += 1
                timed_out = [entry for entry in flight.values()
                             if not entry['event'].is_set() and time.monotonic()-entry['time'] >= RETRY_TIMEOUT]
                if timed_out:
                    controller.on_loss(timeout=True)
                    for entry in timed_out:
                        if entry['retries'] >= MAX_RETRIES:
                            raise TimeoutError('Timeout chunks; completion unconfirmed')
                        self.send_packet_fn(entry['packet'],recipient)
                        entry['retries'] += 1
                        entry['time'] = time.monotonic()
                        with self._lock:
                            record['retransmissions'] += 1
                with self._lock:
                    if record['status']=='sending':
                        record['progress'] = int(acknowledged*100/total)
                    record['congestion'] = controller.snapshot()
                if flight and not self._result(fid):
                    # An ACK wakes this worker, but never blocks other transfers.
                    with self._lock:
                        wake = self._active[fid]['event']
                    wake.wait(.01)
                    wake.clear()
            if not self._result(fid):
                with self._lock:
                    record['progress'] = 100
                for _ in range(MAX_RETRIES):
                    self._check_running()
                    self.send_packet_fn(self._packet({'kind':'FILE_QUERY','file_id':fid,'to':recipient}),recipient)
                    with self._lock:
                        wake = self._active[fid]['event']
                    if self._result(fid):
                        break
                    wake.wait(RETRY_TIMEOUT)
                    wake.clear()
                    if self._result(fid):
                        break
                if not self._result(fid):
                    raise TimeoutError('Receiver completion unconfirmed after result queries')
        except Exception as exc:
            with self._lock:
                # A receiver-confirmed outcome is immutable, including when its
                # final chunk ACK was lost while the result arrived successfully.
                if record['status']=='sending':
                    record['status'] = f'failed: {exc}'
        finally:
            with self._pending_lock:
                for key in list(self._pending):
                    if key[0] == fid:
                        self._pending.pop(key)
            with self._lock:
                record['congestion'] = controller.snapshot()
                self._active.pop(fid,None)
                self._workers.discard(threading.current_thread())
                self._trim()

    def handle_packet(self, packet, sender='?'):
        if packet.msg_type != MSG_DATA:
            return False
        try:
            message = decode_secure_json(packet.payload)
        except FileTransferError:
            return False
        kind = message.get('kind')
        if kind not in (FILE_META, FILE_CHUNK, 'ACK', 'FILE_RESULT', 'FILE_QUERY'):
            return False
        fid = message.get('file_id')
        if not isinstance(fid,str) or not re.fullmatch(r'[0-9a-f]{32}',fid):
            return True
        if kind == 'ACK':
            self._on_ack(message,sender)
        elif kind == 'FILE_RESULT':
            self._on_file_result(message,sender)
        elif kind == 'FILE_QUERY':
            self._reply_terminal(fid,sender)
        elif kind == FILE_META:
            terminal = self.receiver.terminal_result(fid,sender)
            if terminal:
                if self.receiver.metadata_matches(terminal,message):
                    self._send_file_result(fid,sender,terminal['status'],terminal['error'],terminal)
            else:
                self._on_meta(message,sender)
        else:
            if not self._reply_terminal(fid,sender):
                self._on_chunk(message,sender)
        return True

    def _send_control(self, message, peer):
        packet = self._packet(message)
        try:
            self.send_packet_fn(packet,peer)
        except (OSError, RuntimeError):
            # Discovery may remove a peer between receiving its datagram and
            # replying; the client callback then raises RuntimeError. Preserve
            # the receive loop and terminal state, just as for a lost datagram.
            # Valid retransmits/queries recover the reply if the peer returns.
            pass

    def _reply_ack(self, fid, index, peer):
        self._send_control({'kind':'ACK','file_id':fid,'chunk_index':index,'to':peer},peer)

    def _on_ack(self, message, sender='?'):
        fid, index = message.get('file_id'), message.get('chunk_index')
        if type(index) is not int:
            return
        with self._lock:
            active = self._active.get(fid)
            if not active or active['peer'] != sender:
                return
            with self._pending_lock:
                event = self._pending.get((fid,index))
            if event:
                event.set()
                active['event'].set()

    def _on_file_result(self, message, sender='?'):
        fid, status = message.get('file_id'), message.get('status')
        if status not in ('completed','failed','timeout'):
            return
        with self._lock:
            active = self._active.get(fid)
            if not active or active['peer'] != sender or active['result'] is not None:
                return
            if status=='completed':
                out = active['outgoing']
                if message.get('sha256') != out.sha256 or message.get('size') != out.size:
                    return
            active['result'] = dict(message)
            rec = active['record']
            if rec['status']=='sending':
                if status=='completed':
                    rec.update(status='done',progress=100)
                else:
                    rec['status'] = f"failed: {str(message.get('error') or status)[:500]}"
            active['event'].set()

    def _on_meta(self, message, sender):
        try:
            item = self.receiver.accept_metadata(message,sender)
            with self._lock:
                if not any(r['file_id']==item.file_id and r['direction']=='receive' for r in self.transfers):
                    self.transfers.append(dict(direction='receive',file_id=item.file_id,filename=item.filename,
                                               peer=sender,status='receiving',progress=0,total_chunks=item.total_chunks))
                    self._trim()
            self._reply_ack(item.file_id,-1,sender)
        except FileTransferError as exc:
            self._send_file_result(message['file_id'],sender,'failed',str(exc))

    def _on_chunk(self, message, sender):
        fid = message['file_id']
        try:
            result = self.receiver.accept_chunk(message,sender=sender)
            if result.get('ignored'):
                return
            self._reply_ack(fid,message['chunk_index'],sender)
            self._reply_terminal(fid,sender)
        except FileTransferError:
            self._reply_terminal(fid,sender)

    def _reply_terminal(self, fid, sender):
        terminal = self.receiver.terminal_result(fid,sender)
        if terminal is None:
            return False
        self._send_file_result(fid,sender,terminal['status'],terminal['error'],terminal)
        return True

    def _send_file_result(self, file_id, to_user, status, error='', result=None):
        result = result or {}
        self._send_control(dict(kind='FILE_RESULT',file_id=file_id,to=to_user,status=status,error=error,
                                size=result.get('size'),sha256=result.get('sha256')),to_user)

    def get_progress(self):
        with self._lock:
            records = [dict(r) for r in self.transfers[-40:]]
        for record in records:
            if record['direction']=='receive':
                progress = self.receiver.get_progress(record['file_id'])
                if progress:
                    record['status'], record['progress'] = progress['status'], progress['progress']
        return records

    def cleanup(self):
        self.receiver.cleanup_expired(max_age=120.0)
        with self._lock:
            self._trim()

    def close(self):
        self._closed.set()
        with self._lock:
            workers = list(self._workers)
            for active in self._active.values():
                active['event'].set()
        self.receiver.close()
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(RETRY_TIMEOUT+.2)
