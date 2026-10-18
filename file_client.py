from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Optional

from protocol import ( Packet, MSG_DATA, MSG_ACK, STATUS_OK, encode_packet, decode_packet)
from file_transfer import ( OutgoingFile, FileReceiver, FileTransferError, encode_secure_json, decode_secure_json, FILE_META, FILE_CHUNK, FILE_COMPLETE)

class FileTransferHandler:
    """
    Xử lí việc nhận và gửi file 
    """

    def __init__(self, 
                 send_packet_fn: Callable[[Packet], None],
                 next_seq_fn: Callable[[] , int],
                 download_dir: str = "downloads"):
        """
        Gửi packet và lấy seq tiếp theo
        """
        self.send_packet_fn = send_packet_fn
        self.next_seq_fn = next_seq_fn
        self.receiver = FileReceiver(download_dir = download_dir)

        self.transfers: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def send_file(self, filepath: str | Path , recipient: str = "*") -> str:
        """ Gửi file tới recipient và trả về file_id để theo dõi"""
        outgoing = OutgoingFile.from_path(filepath)

        record = {
            "direction": "send",
            "file_id": outgoing.file_id,
            "filename": outgoing.filename,
            "peer": recipient,
            "status": "sending",
            "progress": 0
        }
        with self._lock:
            self.transfers.append(record)

        threading.Thread(
            target=self._send_worker,
            args=(outgoing, recipient, record),
            daemon=True,
        ).start()

        return outgoing.file_id

    def _send_worker(self, outgoing: OutgoingFile, recipient: str, record: dict):
        try:
            """Gửi metadata"""
            meta_payload = encode_secure_json(outgoing.metadata_message(recipient))
            meta_pkt = Packet(
                msg_type=MSG_DATA,
                status=STATUS_OK,
                seq_no=self.next_seq_fn(),
                payload=meta_payload,
            )
            self.send_packet_fn(meta_pkt)

            """ Gửi các chunk """
            total = len(outgoing.chunks)
            for idx in range(total):
                chunk_payload = encode_secure_json(outgoing.chunk_message(idx, recipient))
                chunk_pkt = Packet(
                    msg_type=MSG_DATA,
                    status=STATUS_OK,
                    seq_no=self.next_seq_fn(),
                    payload=chunk_payload,
                )
                self.send_packet_fn(chunk_pkt)

                with self._lock:
                    record["progress"] = int((idx + 1) * 100 / total)

            with self._lock:
                record["status"] = "sent"
                record["progress"] = 100

        except Exception as exc:
            with self._lock:
                record["status"] = f"failed: {exc}"

    def handle_packet(self, packet: Packet, sender: str = "?") -> bool:
        """
        Xử lý packet MSG_DATA.
        Trả về True nếu đây là packet file (đã xử lý),
        False nếu không phải file.
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
            return True
        if kind == FILE_CHUNK:
            self._on_chunk(msg)
            return True

        return False 

    """ Khởi tạo trạng thái nhận file """
    def _on_meta(self, msg: dict, sender: str):
        try:
            item = self.receiver.accept_metadata(msg, sender=sender)
            with self._lock:
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

    def _on_chunk(self, msg: dict):
        try:
            result = self.receiver.accept_chunk(msg)
            fid = result.get("file_id")

            with self._lock:
                for rec in self.transfers:
                    if rec.get("file_id") == fid and rec["direction"] == "receive":
                        rec["progress"] = result.get("progress", rec.get("progress", 0))
                        if result.get("kind") == FILE_COMPLETE:
                            rec["status"] = "completed"
                            rec["progress"] = 100
                        break

        except FileTransferError as exc:
            print(f"[FILE] chunk error: {exc}")

    def get_progress(self) -> list[dict]:
        with self._lock:
            return [rec.copy() for rec in self.transfers[-40:]]

    def cleanup(self):
        """Gọi định kỳ để xóa transfer bị timeout """
        self.receiver.cleanup_expired(max_age=120.0)