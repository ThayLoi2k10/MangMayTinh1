from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from protocol import Packet, MSG_DATA, STATUS_OK
from file_transfer import (
    OutgoingFile,
    FileReceiver,
    FileTransferError,
    encode_secure_json,
    decode_secure_json,
    FILE_META,
    FILE_CHUNK,
    FILE_COMPLETE,
)
from config import WINDOW_SIZE, RETRY_TIMEOUT, MAX_RETRIES


class FileTransferHandler:
    """
    Application-layer reliable file transfer trên UDP.
    """

    def __init__(self, send_packet_fn: Callable[[Packet, str], None], next_seq_fn: Callable[[], int], download_dir: str = "downloads"):
        """
        send_packet_fn(packet, recipient_username): Gửi packet UDP tới đúng peer
        next_seq_fn(): Sequence number application-layer.
        """
        self.send_packet_fn = send_packet_fn
        self.next_seq_fn = next_seq_fn
        self.receiver = FileReceiver(download_dir=download_dir)

        """ Lịch sử gửi nhận cho UI """
        self.transfers: list[dict[str, Any]] = []
        self._lock = threading.Lock()

        # (file_id, chunk_index) -> Event , chunk_index = -1 cho META
        """ Khi nhận đúng ACK sẽ gọi đến event.set()"""
        self._pending: dict[tuple[str, int], threading.Event] = {}
        self._pending_lock = threading.Lock()

    def send_file(self, filepath: str | Path, recipient: str, all_recipients: list[str] | None = None) -> str:
        if recipient == "*":
            targets = [u for u in (all_recipients or []) if u]
            if not targets:
                raise FileTransferError("Không có ai online để gửi file broadcast")
        else:
            if not recipient:
                raise FileTransferError("Thiếu người nhận")
            targets = [recipient]
        last_id = ""
        for target in targets:
            outgoing = OutgoingFile.from_path(filepath) # file_id mới cho mỗi peer
            last_id = outgoing.file_id

            record = {
                "direction": "send",
                "file_id": outgoing.file_id,
                "filename": outgoing.filename,
                "peer": target,
                "status": "sending",
                "progress": 0,
                "total_chunks": len(outgoing.chunks),
            }
            with self._lock:
                self.transfers.append(record)

            threading.Thread(
                target=self._send_worker,
                args=(outgoing, target, record),
                daemon=True,
            ).start()

        return last_id

    """ Đăng ký và hủy chờ cho ACK """
    def _register_wait(self, file_id: str, index: int) -> threading.Event:
        key = (file_id, index)
        ev = threading.Event()
        with self._pending_lock:
            self._pending[key] = ev
        return ev

    def _unregister(self, file_id: str, index: int) -> None:
        with self._pending_lock:
            self._pending.pop((file_id, index), None)

    def _send_reliable_one(self, message: dict, recipient: str, file_id: str, index: int) -> None:
        """Gửi 1 gói (META hoặc 1 CHUNK), chờ ACK, retransmit nếu cần """
        ev = self._register_wait(file_id, index)
        payload = encode_secure_json(message)
        packet = Packet(
            msg_type=MSG_DATA,
            status=STATUS_OK,
            seq_no=self.next_seq_fn(),
            payload=payload,
        )
        try:
            for _ in range(MAX_RETRIES):
                self.send_packet_fn(packet, recipient)
                if ev.wait(RETRY_TIMEOUT):
                    return
            raise TimeoutError(f"Timeout ACK file_id={file_id} index={index}")
        finally:
            self._unregister(file_id, index)

    """ Điều phối quá trình truyền file """
    def _send_worker(self, outgoing: OutgoingFile, recipient: str, record: dict) -> None:
        try:
            """ FILE_META (index = -1) """
            meta = outgoing.metadata_message(recipient)
            self._send_reliable_one(meta, recipient, outgoing.file_id, -1)

            """ FILE_CHUNK theo sliding window """
            total = len(outgoing.chunks)
            i = 0
            while i < total:
                end = min(i + WINDOW_SIZE, total)
                events: dict[int, threading.Event] = {}

                for idx in range(i, end):
                    events[idx] = self._register_wait(outgoing.file_id, idx)

                """ Gửi cả cửa sổ """
                for idx in range(i, end):
                    msg = outgoing.chunk_message(idx, recipient)
                    payload = encode_secure_json(msg)
                    pkt = Packet(
                        msg_type=MSG_DATA,
                        status=STATUS_OK,
                        seq_no=self.next_seq_fn(),
                        payload=payload,
                    )
                    self.send_packet_fn(pkt, recipient)

                """Retransmit những chunk chưa ACK"""
                for _ in range(MAX_RETRIES):
                    pending = [idx for idx, ev in events.items() if not ev.is_set()]
                    if not pending:
                        break
                    deadline = time.time() + RETRY_TIMEOUT
                    while time.time() < deadline and any(not ev.is_set() for ev in events.values()):
                        time.sleep(0.01)
                    pending = [idx for idx, ev in events.items() if not ev.is_set()]
                    if not pending:
                        break
                    for idx in pending:
                        msg = outgoing.chunk_message(idx, recipient)
                        payload = encode_secure_json(msg)
                        pkt = Packet(
                            msg_type=MSG_DATA,
                            status=STATUS_OK,
                            seq_no=self.next_seq_fn(),
                            payload=payload,
                        )
                        self.send_packet_fn(pkt, recipient)
                else:
                    pending = [idx for idx, ev in events.items() if not ev.is_set()]
                    if pending:
                        raise TimeoutError(f"Timeout chunks {pending}")

                for idx in range(i, end):
                    self._unregister(outgoing.file_id, idx)

                i = end
                with self._lock:
                    record["progress"] = int(i * 100 / total)

            with self._lock:
                record["status"] = "done"
                record["progress"] = 100

        except Exception as exc:
            with self._lock:
                record["status"] = f"failed: {exc}"

    # ==================================================================
    # NHẬN (gọi từ UDP loop)
    # ==================================================================
    def handle_packet(self, packet: Packet, sender: str = "?") -> bool:
        """
        Xử lý packet UDP MSG_DATA.
        True = đây là packet file (đã xử lý)
        """
        if packet.msg_type != MSG_DATA:
            return False
        try:
            msg = decode_secure_json(packet.payload)
        except FileTransferError:
            return False

        kind = msg.get("kind")
        if kind == FILE_META:
            self._on_meta(msg, sender)
            self._reply_ack(msg.get("file_id"), -1, sender)
            return True
        if kind == FILE_CHUNK:
            self._on_chunk(msg, sender)
            return True
        if kind == "ACK":
            self._on_ack(msg)
            return True
        return False

    def _reply_ack(self, file_id: str, chunk_index: int, to_user: str) -> None:
        ack = {
            "kind": "ACK",
            "file_id": file_id,
            "chunk_index": chunk_index,
            "to": to_user,
        }
        payload = encode_secure_json(ack)
        pkt = Packet(
            msg_type=MSG_DATA,
            status=STATUS_OK,
            seq_no=self.next_seq_fn(),
            payload=payload,
        )
        self.send_packet_fn(pkt, to_user)

    def _on_ack(self, msg: dict) -> None:
        fid = msg.get("file_id")
        idx = msg.get("chunk_index", -1)
        if not isinstance(fid, str):
            return
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return
        with self._pending_lock:
            ev = self._pending.get((fid, idx))
        if ev:
            ev.set()

    def _on_meta(self, msg: dict, sender: str) -> None:
        try:
            item = self.receiver.accept_metadata(msg, sender=sender)
            with self._lock:
                # chỉ thêm record nếu chưa có file_id này phía receive
                exists = any(
                    r.get("file_id") == item.file_id and r.get("direction") == "receive"
                    for r in self.transfers
                )
                if not exists:
                    self.transfers.append({
                        "direction": "receive",
                        "file_id": item.file_id,
                        "filename": item.filename,
                        "peer": sender,
                        "status": "receiving",
                        "progress": 0,
                        "total_chunks": item.total_chunks,
                    })
        except FileTransferError as exc:
            print(f"[FILE] meta error: {exc}")

    def _on_chunk(self, msg: dict, sender: str) -> None:
        try:
            result = self.receiver.accept_chunk(msg)
            fid = msg.get("file_id")
            idx = int(msg.get("chunk_index", -1))

            if fid:
                self._reply_ack(fid, idx, sender)

            if result.get("ignored"):
                return
        
            with self._lock:
                for rec in self.transfers:
                    if rec.get("file_id") == fid and rec.get("direction") == "receive":
                        rec["progress"] = result.get(
                            "progress", rec.get("progress", 0)
                        )
                        if result.get("kind") == FILE_COMPLETE:
                            rec["status"] = "completed"
                            rec["progress"] = 100
                            print(
                                f"[FILE] OK: {result['filename']} "
                                f"({result['size']} bytes) -> {result['path']}"
                            )
                        break
        except FileTransferError as exc:
            fid = msg.get("file_id")
            with self._lock:
                for rec in self.transfers:
                    if (
                        rec.get("file_id") == fid
                        and rec.get("direction") == "receive"
                        and rec.get("status") == "receiving"
                    ):
                        # Lấy status chi tiết nếu receiver đã ghi
                        rp = self.receiver.get_progress(str(fid)) if fid else None
                        rec["status"] = (
                            rp.get("status") if rp and rp.get("status") else f"failed: {exc}"
                        )
                        break
            print(f"[FILE] chunk error: {exc}")

    def get_progress(self) -> list[dict]:
        with self._lock:
            out = [dict(r) for r in self.transfers[-40:]]

        for rec in out:
            if rec.get("direction") != "receive":
                continue
            fid = rec.get("file_id")
            if not fid:
                continue
            rp = self.receiver.get_progress(str(fid))
            if not rp:
                continue
            st = rp.get("status")
            # Chỉ ghi đè khi receiver đã kết thúc hoặc lỗi
            if st and st not in ("receiving",):
                rec["status"] = st
                if "progress" in rp:
                    rec["progress"] = rp["progress"]
        return out

    def cleanup(self) -> None:
        expired = self.receiver.cleanup_expired(max_age=120.0)
        if not expired:
            return
        with self._lock:
            for rec in self.transfers:
                if ( rec.get("direction") == "receive" and rec.get("file_id") in expired and rec.get("status") == "receiving"):
                    rec["status"] = "timeout"