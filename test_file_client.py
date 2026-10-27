
import hashlib
import itertools
import tempfile
import threading
import time
import unittest
from pathlib import Path

from protocol import Packet, MSG_DATA, MSG_ACK
from file_client import FileTransferHandler
from file_transfer import (
    FileTransferError,
    FILE_META,
    FILE_CHUNK,
    encode_secure_json,
    OutgoingFile,
)


class TestFileClientAdvanced(unittest.TestCase):

    def make_handler(self, download_dir, send_fn=None):
        """Tạo handler với callback giả lập."""
        if send_fn is None:
            send_fn = lambda packet: None

        counter = itertools.count(1)

        return FileTransferHandler(
            send_packet_fn=send_fn,
            next_seq_fn=lambda: next(counter),
            download_dir=download_dir,
        )

    def wait_for_record(self, handler, file_id, direction, timeout=3):
        """Đợi worker cập nhật trạng thái truyền file."""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            records = handler.get_progress()

            for record in records:
                if (
                    record.get("file_id") == file_id
                    and record.get("direction") == direction
                ):
                    status = record.get("status", "")

                    if status in ("sent", "completed") or str(status).startswith("failed"):
                        return record

            time.sleep(0.01)

        self.fail(
            f"Không nhận được trạng thái cuối cho file_id={file_id}"
        )

    # --------------------------------------------------
    # 1. Kiểm tra lỗi ở phía gửi
    # --------------------------------------------------

    def test_send_nonexistent_file(self):
        """Đường dẫn không tồn tại phải báo lỗi khi gọi send_file."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)
            missing_file = Path(tmp) / "missing.txt"

            with self.assertRaises(FileTransferError):
                handler.send_file(missing_file)

    def test_send_callback_failure_updates_status(self):
        """Nếu callback gửi packet lỗi, trạng thái phải là failed."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_bytes(b"some content")

            def fail_send(packet):
                raise OSError("simulated send failure")

            handler = self.make_handler(
                Path(tmp) / "downloads",
                send_fn=fail_send,
            )

            file_id = handler.send_file(source)
            record = self.wait_for_record(
                handler, file_id, "send"
            )

            self.assertTrue(
                record["status"].startswith("failed:")
            )
            self.assertIn(
                "simulated send failure",
                record["status"],
            )

    def test_empty_file_can_be_sent_and_received(self):
        """File rỗng vẫn phải truyền và nhận thành công."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "empty.txt"
            source.write_bytes(b"")

            receiver_dir = root / "downloads"
            receiver_dir.mkdir()

            receiver = self.make_handler(receiver_dir)

            sender = self.make_handler(
                root / "sender_downloads",
                send_fn=lambda packet: receiver.handle_packet(
                    packet, sender="Alice"
                ),
            )

            file_id = sender.send_file(source)

            sent = self.wait_for_record(
                sender, file_id, "send"
            )
            received = self.wait_for_record(
                receiver, file_id, "receive"
            )

            self.assertEqual(sent["status"], "sent")
            self.assertEqual(received["status"], "completed")
            self.assertEqual(received["progress"], 100)

            received_file = receiver_dir / "empty.txt"
            self.assertTrue(received_file.exists())
            self.assertEqual(received_file.read_bytes(), b"")

            self.assertEqual(
                hashlib.sha256(received_file.read_bytes()).hexdigest(),
                hashlib.sha256(b"").hexdigest(),
            )

    def test_packets_are_sent_in_order(self):
        """Metadata phải được gửi trước các chunk."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "multi.txt"
            source.write_bytes(b"A" * 1500)

            sent_packets = []
            lock = threading.Lock()

            def collect(packet):
                with lock:
                    sent_packets.append(packet)

            handler = self.make_handler(
                Path(tmp) / "downloads",
                send_fn=collect,
            )

            file_id = handler.send_file(source)
            record = self.wait_for_record(
                handler, file_id, "send"
            )

            self.assertEqual(record["status"], "sent")

            with lock:
                packets = list(sent_packets)

            messages = [
                # Giải mã để kiểm tra loại thông điệp.
                __import__("file_transfer").decode_secure_json(
                    packet.payload
                )
                for packet in packets
            ]

            self.assertEqual(packets[0].msg_type, MSG_DATA)
            self.assertEqual(messages[0]["kind"], FILE_META)

            chunk_messages = messages[1:]
            self.assertTrue(chunk_messages)
            self.assertTrue(
                all(msg["kind"] == FILE_CHUNK for msg in chunk_messages)
            )

            self.assertEqual(
                [msg["chunk_index"] for msg in chunk_messages],
                list(range(len(chunk_messages))),
            )

            self.assertTrue(
                all(packet.msg_type == MSG_DATA for packet in packets)
            )

            self.assertEqual(
                [packet.seq_no for packet in packets],
                list(range(1, len(packets) + 1)),
            )

    # --------------------------------------------------
    # 2. Kiểm tra dữ liệu nhận không hợp lệ
    # --------------------------------------------------

    def test_invalid_metadata_does_not_crash_handler(self):
        """Metadata sai được bắt lỗi, không tạo transfer nhận."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)

            invalid_meta = {
                "kind": FILE_META,
                "file_id": "invalid-id",
                "filename": "bad.txt",
                "size": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
                "chunk_size": 700,
                "total_chunks": 1,
            }

            packet = Packet(
                msg_type=MSG_DATA,
                payload=encode_secure_json(invalid_meta),
            )

            self.assertTrue(handler.handle_packet(packet, sender="Alice"))
            self.assertEqual(handler.get_progress(), [])

    def test_chunk_before_metadata_does_not_crash_handler(self):
        """Chunk đến trước metadata phải bị từ chối an toàn."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)

            outgoing = OutgoingFile.from_bytes(
                "sample.txt", b"hello"
            )
            chunk_message = outgoing.chunk_message(0, "Bob")

            packet = Packet(
                msg_type=MSG_DATA,
                payload=encode_secure_json(chunk_message),
            )

            self.assertTrue(handler.handle_packet(packet, sender="Alice"))
            self.assertEqual(handler.get_progress(), [])

    def test_unknown_message_kind_is_not_handled_as_file(self):
        """Thông điệp không thuộc loại file phải trả về False."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)

            packet = Packet(
                msg_type=MSG_DATA,
                payload=encode_secure_json({
                    "kind": "UNKNOWN_KIND",
                    "data": "test",
                }),
            )

            self.assertFalse(handler.handle_packet(packet))

    def test_ack_packet_is_ignored(self):
        """MSG_ACK không bị nhầm thành dữ liệu file."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)

            packet = Packet(
                msg_type=MSG_ACK,
                payload=b"",
            )

            self.assertFalse(handler.handle_packet(packet))
            self.assertEqual(handler.get_progress(), [])

    def test_duplicate_metadata_does_not_add_second_record(self):
        """Metadata trùng file_id không tạo thêm bản ghi nhận."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)

            outgoing = OutgoingFile.from_bytes(
                "duplicate.txt", b"hello"
            )
            metadata = outgoing.metadata_message("Bob")

            packet = Packet(
                msg_type=MSG_DATA,
                payload=encode_secure_json(metadata),
            )

            self.assertTrue(handler.handle_packet(packet, sender="Alice"))
            self.assertTrue(handler.handle_packet(packet, sender="Alice"))

            receive_records = [
                record for record in handler.get_progress()
                if record.get("direction") == "receive"
            ]

            self.assertEqual(len(receive_records), 1)

    def test_tampered_encrypted_payload_is_ignored(self):
        """Payload mã hóa giả mạo không được xử lý thành file."""
        with tempfile.TemporaryDirectory() as tmp:
            handler = self.make_handler(tmp)

            packet = Packet(
                msg_type=MSG_DATA,
                payload=b"not-a-valid-fernet-token",
            )

            self.assertFalse(handler.handle_packet(packet))
            self.assertEqual(handler.get_progress(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
