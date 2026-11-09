"""Real UDP terminal recovery, peer binding and receiver publication invariants."""
import asyncio
import hashlib
import itertools
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from file_client import FileTransferHandler
from file_transfer import OutgoingFile, FileReceiver, FileTransferError, decode_secure_json, encode_secure_json
from protocol import Packet, MSG_DATA, decode_packet, encode_packet


def wait(predicate, timeout=8):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        value = predicate()
        if value:
            return value
        time.sleep(.005)
    raise AssertionError('condition did not complete before deadline')


class DatagramPair:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='release-file-')
        self.root = Path(self.temp.name)
        self.stop = threading.Event()
        self.sockets = {}
        self.handlers = {}
        self.threads = []
        self.errors = []
        self.drop = lambda sender, body: False
        for name in ('alice','bob'):
            sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1',0))
            sock.settimeout(.1)
            self.sockets[name] = sock
        for name in self.sockets:
            count = itertools.count(1)
            def send(packet, recipient, name=name):
                if not self.drop(name,decode_secure_json(packet.payload)):
                    self.sockets[name].sendto(encode_packet(packet),self.sockets[recipient].getsockname())
            self.handlers[name] = FileTransferHandler(send,lambda count=count: next(count)&65535,self.root/name)
        def receive(name):
            while not self.stop.is_set():
                try:
                    raw, addr = self.sockets[name].recvfrom(65535)
                    peer = next(n for n,s in self.sockets.items() if s.getsockname()==addr)
                    self.handlers[name].handle_packet(decode_packet(raw),sender=peer)
                except socket.timeout:
                    continue
                except OSError:
                    break
                except Exception as exc:
                    self.errors.append(repr(exc))
                    break
        for name in self.sockets:
            thread=threading.Thread(target=receive,args=(name,))
            self.threads.append(thread)
            thread.start()
        return self

    def send(self,data=b'x'*100,name='payload.bin'):
        source=self.root/name
        source.write_bytes(data)
        return self.handlers['alice'].send_file(source,'bob')

    def record(self,peer,fid):
        return next(r for r in self.handlers[peer].get_progress() if r['file_id']==fid)

    def finished(self,fid):
        return fid not in self.handlers['alice']._active

    def __exit__(self,*args):
        for handler in self.handlers.values():
            handler.close()
        self.stop.set()
        for sock in self.sockets.values():
            sock.close()
        for thread in self.threads:
            thread.join(2)
        self.temp.cleanup()
        if not args[0]:
            assert not self.errors,self.errors


class ReleaseFileTests(unittest.TestCase):
    def test_healthy_file_window_enters_congestion_avoidance(self):
        with DatagramPair() as pair:
            payload = bytes(range(256))*1024
            observed_windows = []
            def observe(sender, message):
                if sender == 'alice':
                    records = pair.handlers['alice'].get_progress()
                    observed_windows.extend(r.get('congestion', {}).get('cwnd', 0) for r in records)
                return False  # Observe only: every real datagram is sent.
            pair.drop = observe
            fid = pair.send(payload)
            wait(lambda: pair.finished(fid))
            record = pair.record('alice', fid)
            self.assertEqual(record['status'], 'done')
            # Entry into avoidance is a transition, not a terminal-state property.
            # A legitimate later loss can reduce final cwnd back below8.
            observed_windows.append(record['congestion']['cwnd'])
            self.assertGreater(max(observed_windows), 8)
            self.assertLessEqual(record['congestion']['cwnd'], 64)
            self.assertEqual((pair.root/'bob/payload.bin').read_bytes(), payload)

    def test_peer_disappears_while_replying_does_not_kill_receive_loop(self):
        with DatagramPair() as pair:
            receiver = pair.handlers['bob']
            send = receiver.send_packet_fn
            refused = []
            def reply(packet, recipient):
                if not refused:
                    refused.append(decode_secure_json(packet.payload)['kind'])
                    # The real CollaborationClient raises RuntimeError if its
                    # discovery snapshot loses the peer between receive/reply.
                    raise RuntimeError('Peer no longer in discovery snapshot')
                send(packet, recipient)
            receiver.send_packet_fn = reply
            fid = pair.send()
            wait(lambda: pair.finished(fid))
            self.assertEqual(refused, ['ACK'])
            self.assertEqual(pair.errors, [])
            self.assertEqual(pair.record('alice', fid)['status'], 'done')
            self.assertEqual(pair.record('bob', fid)['status'], 'completed')
            self.assertFalse(pair.handlers['alice']._pending)

    def test_lost_final_ack_and_result_together_recover(self):
        with DatagramPair() as pair:
            drops=[]
            def drop(sender,msg):
                kind=msg['kind']
                if sender=='bob' and ((kind=='ACK' and msg['chunk_index']==0) or kind=='FILE_RESULT') and kind not in drops:
                    drops.append(kind)
                    return True
                return False
            pair.drop=drop
            fid=pair.send()
            wait(lambda:pair.finished(fid))
            self.assertCountEqual(drops,['ACK','FILE_RESULT'])
            self.assertEqual(pair.record('alice',fid)['status'],'done')
            self.assertEqual(pair.record('bob',fid)['status'],'completed')
            self.assertEqual((pair.root/'bob/payload.bin').read_bytes(),b'x'*100)
            self.assertFalse(pair.handlers['alice']._pending)

    def test_all_results_lost_is_bounded_unconfirmed_not_false_done(self):
        with DatagramPair() as pair:
            dropped=[]
            def drop(sender,msg):
                if sender=='bob' and msg['kind']=='FILE_RESULT':
                    dropped.append(msg)
                    return True
                return False
            pair.drop=drop
            fid=pair.send()
            wait(lambda:pair.finished(fid))
            self.assertGreaterEqual(len(dropped),2)
            self.assertIn('completion unconfirmed',pair.record('alice',fid)['status'])
            self.assertEqual(pair.record('bob',fid)['status'],'completed')
            self.assertFalse(pair.handlers['alice']._pending)

    def test_wrong_peer_ack_and_result_cannot_complete_send(self):
        with DatagramPair() as pair:
            pair.drop=lambda sender,msg: sender=='bob'
            fid=pair.send()
            wait(lambda:any(record['file_id']==fid and record['status']=='receiving'
                            for record in pair.handlers['bob'].get_progress()))
            out=pair.handlers['alice']._active[fid]['outgoing']
            for msg in ({'kind':'ACK','file_id':fid,'chunk_index':-1},
                        {'kind':'FILE_RESULT','file_id':fid,'status':'completed','size':out.size,'sha256':out.sha256}):
                pair.handlers['alice'].handle_packet(Packet(MSG_DATA,payload=encode_secure_json(msg)),sender='mallory')
            self.assertIsNone(pair.handlers['alice']._result(fid))
            self.assertFalse(pair.handlers['alice']._pending[(fid,-1)].is_set())

    def test_destination_conflict_failure_recovers_lost_failure_result(self):
        with DatagramPair() as pair:
            target=pair.root/'bob/payload.bin'
            target.write_bytes(b'old')
            dropped=[]
            def drop(sender,msg):
                if sender=='bob' and msg['kind']=='FILE_RESULT' and not dropped:
                    dropped.append(msg)
                    return True
                return False
            pair.drop=drop
            fid=pair.send()
            wait(lambda:pair.finished(fid))
            self.assertTrue(pair.record('alice',fid)['status'].startswith('failed:'))
            self.assertTrue(pair.record('bob',fid)['status'].startswith('failed:'))
            self.assertEqual(target.read_bytes(),b'old')
            self.assertFalse(pair.handlers['alice']._pending)
            self.assertEqual(list(target.parent.glob('*.part')),[])

    def test_close_cancels_sender_without_pending_leak(self):
        with DatagramPair() as pair:
            pair.drop=lambda sender,msg: sender=='bob'
            fid=pair.send()
            pair.handlers['alice'].close()
            self.assertTrue(pair.finished(fid))
            self.assertFalse(pair.handlers['alice']._pending)
            self.assertTrue(pair.record('alice',fid)['status'].startswith('failed:'))

    def test_receiver_atomic_publish_does_not_replace_late_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            receiver=FileReceiver(folder)
            outgoing=OutgoingFile.from_bytes('target.bin',b'new')
            receiver.accept_metadata(outgoing.metadata_message('bob'),'alice')
            target=Path(folder)/'target.bin'
            target.write_bytes(b'created after metadata')
            with self.assertRaises(FileTransferError):
                receiver.accept_chunk(outgoing.chunk_message(0,'bob'),'alice')
            self.assertEqual(target.read_bytes(),b'created after metadata')
            self.assertIsNone(receiver.terminal_result(outgoing.file_id,'mallory'))
            self.assertEqual(receiver.terminal_result(outgoing.file_id,'alice')['status'],'failed')

    def test_async_bytes_before_finish_and_hash_failure_aborts_stream(self):
        async def scenario(folder):
            receiver=FileReceiver(folder)
            outgoing=OutgoingFile.from_bytes('bytes.bin',b'a'*700+b'b')
            metadata=outgoing.metadata_message('bob')
            metadata['sha256']='0'*64
            receiver.accept_metadata(metadata,'alice')
            stream=receiver.get_stream(outgoing.file_id)
            receiver.accept_chunk(outgoing.chunk_message(0,'bob'),'alice')
            self.assertEqual(await asyncio.wait_for(stream.read(),1),b'a'*700)
            with self.assertRaises(FileTransferError):
                receiver.accept_chunk(outgoing.chunk_message(1,'bob'),'alice')
            with self.assertRaises(FileTransferError):
                await asyncio.wait_for(stream.read(),1)
            self.assertFalse((Path(folder)/'bytes.bin').exists())
        with tempfile.TemporaryDirectory() as folder:
            asyncio.run(scenario(folder))

    def test_terminal_cache_bound_preserves_receiver_outcome(self):
        with tempfile.TemporaryDirectory() as folder:
            receiver=FileReceiver(folder)
            receiver.MAX_HISTORY=3
            ids=[]
            for index in range(7):
                outgoing=OutgoingFile.from_bytes(f'{index}.bin',b'')
                receiver.accept_metadata(outgoing.metadata_message('bob'),'alice')
                receiver.accept_chunk(outgoing.chunk_message(0,'bob'),'alice')
                ids.append(outgoing.file_id)
            self.assertLessEqual(len(receiver._terminal),3)
            self.assertIsNone(receiver.terminal_result(ids[0],'alice'))
            self.assertEqual(receiver.terminal_result(ids[-1],'alice')['status'],'completed')


if __name__=='__main__':
    unittest.main()
