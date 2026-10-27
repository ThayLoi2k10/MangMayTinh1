from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from file_transfer import (
    FILE_CHUNK,
    FILE_COMPLETE,
    FILE_META,
    FileReceiver,
    FileTransferError,
    IncomingFile,
    OutgoingFile,
    decode_secure_json,
    encode_secure_json,
    safe_filename,
    split_file,
)


# =====================================================================
# 1. Encryption / Decryption
# =====================================================================

class TestEncryption:
    def test_roundtrip_simple(self):
        msg = {"kind": FILE_META, "file_id": "a" * 32, "filename": "a.txt"}
        token = encode_secure_json(msg)
        assert isinstance(token, bytes)
        assert token != b""  # đã được mã hóa, khác plain JSON

        restored = decode_secure_json(token)
        assert restored == msg

    def test_roundtrip_with_unicode(self):
        msg = {
            "kind": FILE_META,
            "filename": "báo cáo cuối kỳ.pdf",
            "note": "xin chào 👋",
        }
        restored = decode_secure_json(encode_secure_json(msg))
        assert restored["filename"] == "báo cáo cuối kỳ.pdf"
        assert restored["note"] == "xin chào 👋"

    def test_tampered_payload_raises(self):
        token = encode_secure_json({"kind": "TEST"})
        # sửa 1 byte → Fernet phải báo lỗi
        bad = token[:-5] + b"XXXXX"
        with pytest.raises(FileTransferError, match="decrypt"):
            decode_secure_json(bad)

    def test_empty_dict(self):
        restored = decode_secure_json(encode_secure_json({}))
        assert restored == {}


# =====================================================================
# 2. safe_filename
# =====================================================================

class TestSafeFilename:
    def test_normal_name(self):
        assert safe_filename("report.pdf") == "report.pdf"
        assert safe_filename("  hello.txt  ") == "hello.txt"

    def test_reject_path_traversal(self):
        for bad in ["../secret.txt", "..\\secret.txt", "a/b.txt", "a\\b.txt"]:
            with pytest.raises(FileTransferError):
                safe_filename(bad)

    def test_reject_dangerous_chars(self):
        for bad in ['file<1>.txt', 'file|name.txt', 'file?.txt', 'file*.txt']:
            with pytest.raises(FileTransferError):
                safe_filename(bad)

    def test_reject_empty_and_dots(self):
        for bad in ["", ".", "..", "   "]:
            with pytest.raises(FileTransferError):
                safe_filename(bad)

    def test_reject_control_chars(self):
        with pytest.raises(FileTransferError):
            safe_filename("file\x00name.txt")


# =====================================================================
# 3. split_file + OutgoingFile
# =====================================================================

class TestOutgoingFile:
    def test_split_empty_file(self):
        chunks = split_file(b"")
        assert chunks == [b""]

    def test_split_exact_chunks(self):
        data = b"A" * 1400  # đúng 2 chunk nếu CHUNK_SIZE=700
        chunks = split_file(data, chunk_size=700)
        assert len(chunks) == 2
        assert chunks[0] == b"A" * 700
        assert chunks[1] == b"A" * 700

    def test_split_remainder(self):
        data = b"B" * 750
        chunks = split_file(data, chunk_size=700)
        assert len(chunks) == 2
        assert len(chunks[0]) == 700
        assert len(chunks[1]) == 50

    def test_from_bytes_basic(self):
        data = b"Hello File Transfer Module"
        out = OutgoingFile.from_bytes("hello.txt", data)

        assert out.filename == "hello.txt"
        assert out.size == len(data)
        assert out.sha256 == hashlib.sha256(data).hexdigest()
        assert len(out.file_id) == 32
        assert len(out.chunks) >= 1

    def test_from_bytes_reject_bad_name(self):
        with pytest.raises(FileTransferError):
            OutgoingFile.from_bytes("../evil.txt", b"data")

    def test_metadata_message(self):
        out = OutgoingFile.from_bytes("a.txt", b"xyz")
        meta = out.metadata_message("bob")

        assert meta["kind"] == FILE_META
        assert meta["to"] == "bob"
        assert meta["filename"] == "a.txt"
        assert meta["size"] == 3
        assert meta["total_chunks"] == len(out.chunks)
        assert meta["sha256"] == out.sha256

    def test_chunk_message(self):
        out = OutgoingFile.from_bytes("a.txt", b"0123456789")
        msg = out.chunk_message(0, "bob")

        assert msg["kind"] == FILE_CHUNK
        assert msg["chunk_index"] == 0
        assert msg["to"] == "bob"
        assert "data" in msg  # base64

    def test_chunk_index_out_of_range(self):
        out = OutgoingFile.from_bytes("a.txt", b"data")
        with pytest.raises(FileTransferError):
            out.chunk_message(999, "bob")


# =====================================================================
# 4. FileReceiver – nhận metadata + chunk + ghép file
# =====================================================================

class TestFileReceiver:
    def setup_method(self):
        self.tmp = Path("test_downloads_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.receiver = FileReceiver(download_dir=self.tmp)

    def teardown_method(self):
        # dọn thư mục test
        for f in self.tmp.iterdir():
            f.unlink()
        self.tmp.rmdir()

    def _make_outgoing(self, name: str, data: bytes) -> OutgoingFile:
        return OutgoingFile.from_bytes(name, data)

    def test_accept_metadata_ok(self):
        out = self._make_outgoing("doc.txt", b"content")
        meta = out.metadata_message("alice")
        item = self.receiver.accept_metadata(meta, sender="bob")

        assert item.file_id == out.file_id
        assert item.filename == "doc.txt"
        assert item.total_chunks == len(out.chunks)
        assert item.sender == "bob"

    def test_accept_metadata_duplicate_id(self):
        out = self._make_outgoing("doc.txt", b"content")
        meta = out.metadata_message("alice")
        self.receiver.accept_metadata(meta, sender="bob")

        with pytest.raises(FileTransferError, match="đã tồn tại"):
            self.receiver.accept_metadata(meta, sender="bob")

    def test_accept_metadata_bad_kind(self):
        with pytest.raises(FileTransferError):
            self.receiver.accept_metadata({"kind": "WRONG"}, sender="x")

    def test_full_transfer_success(self):
        """Gửi đủ chunk → file được ghép + hash đúng + lưu thành công."""
        data = b"Complete file content for testing 12345"
        out = self._make_outgoing("final.txt", data)
        meta = out.metadata_message("alice")
        self.receiver.accept_metadata(meta, sender="bob")

        # gửi từng chunk
        result = None
        for idx in range(len(out.chunks)):
            chunk_msg = out.chunk_message(idx, "alice")
            result = self.receiver.accept_chunk(chunk_msg)

        assert result is not None
        assert result["kind"] == FILE_COMPLETE
        assert result["filename"] == "final.txt"
        assert result["sha256"] == out.sha256

        # file đã nằm trong thư mục download
        saved = self.tmp / "final.txt"
        assert saved.exists()
        assert saved.read_bytes() == data

    def test_hash_mismatch_detected(self):
        """Gửi đủ chunk hợp lệ nhưng hash trong metadata bị sai → phải báo SHA-256."""
        data = b"Original content"
        out = self._make_outgoing("bad.txt", data)
        meta = out.metadata_message("alice")
        self.receiver.accept_metadata(meta, sender="bob")

        # Cố ý sửa hash đã lưu thành giá trị sai (vẫn giữ nguyên chunk thật)
        self.receiver.incoming[out.file_id].sha256 = "0" * 64

        # Gửi toàn bộ chunk đúng nội dung + đúng độ dài
        for idx in range(len(out.chunks)):
            chunk_msg = out.chunk_message(idx, "alice")
            if idx == len(out.chunks) - 1:
                # chunk cuối cùng sẽ kích hoạt kiểm tra hash
                with pytest.raises(FileTransferError, match="SHA-256"):
                    self.receiver.accept_chunk(chunk_msg)
            else:
                self.receiver.accept_chunk(chunk_msg)

    def test_no_overwrite_existing_file(self):
        """Không ghi đè file đã tồn tại."""
        data = b"new content"
        out = self._make_outgoing("exist.txt", data)

        # tạo file sẵn
        existing = self.tmp / "exist.txt"
        existing.write_bytes(b"old content")

        meta = out.metadata_message("alice")
        self.receiver.accept_metadata(meta, sender="bob")

        for idx in range(len(out.chunks)):
            chunk_msg = out.chunk_message(idx, "alice")
            if idx == len(out.chunks) - 1:
                with pytest.raises(FileTransferError, match="đã tồn tại"):
                    self.receiver.accept_chunk(chunk_msg)
            else:
                self.receiver.accept_chunk(chunk_msg)

        # nội dung cũ không bị đè
        assert existing.read_bytes() == b"old content"

    def test_progress_updates(self):
        data = b"X" * 1500  # nhiều chunk
        out = self._make_outgoing("prog.txt", data)
        meta = out.metadata_message("alice")
        self.receiver.accept_metadata(meta, sender="bob")

        for idx in range(len(out.chunks)):
            result = self.receiver.accept_chunk(out.chunk_message(idx, "alice"))
            prog = self.receiver.get_progress(out.file_id)
            assert prog is not None
            assert 0 <= prog["progress"] <= 100

        assert result["kind"] == FILE_COMPLETE

    def test_cleanup_expired(self):
        out = self._make_outgoing("old.txt", b"data")
        meta = out.metadata_message("alice")
        item = self.receiver.accept_metadata(meta, sender="bob")

        # giả lập đã quá hạn
        item.last_activity = time.time() - 200

        expired = self.receiver.cleanup_expired(max_age=120.0)
        assert out.file_id in expired
        assert out.file_id not in self.receiver.incoming
        assert self.receiver.progress[out.file_id]["status"] == "timeout"


# =====================================================================
# Chạy trực tiếp (không cần pytest)
# =====================================================================

def _run_standalone():
    """Cho phép chạy: python test_file_transfer.py"""
    print("=== Test Encryption ===")
    t = TestEncryption()
    t.test_roundtrip_simple()
    t.test_roundtrip_with_unicode()
    t.test_tampered_payload_raises()
    t.test_empty_dict()
    print("  PASS")

    print("=== Test safe_filename ===")
    t = TestSafeFilename()
    t.test_normal_name()
    t.test_reject_path_traversal()
    t.test_reject_dangerous_chars()
    t.test_reject_empty_and_dots()
    t.test_reject_control_chars()
    print("  PASS")

    print("=== Test OutgoingFile ===")
    t = TestOutgoingFile()
    t.test_split_empty_file()
    t.test_split_exact_chunks()
    t.test_split_remainder()
    t.test_from_bytes_basic()
    t.test_from_bytes_reject_bad_name()
    t.test_metadata_message()
    t.test_chunk_message()
    t.test_chunk_index_out_of_range()
    print("  PASS")

    print("=== Test FileReceiver ===")
    t = TestFileReceiver()
    t.setup_method()
    try:
        t.test_accept_metadata_ok()
        t.test_accept_metadata_duplicate_id()
        t.test_accept_metadata_bad_kind()
        t.test_full_transfer_success()
        t.test_no_overwrite_existing_file()
        t.test_progress_updates()
        t.test_cleanup_expired()
        # hash mismatch test riêng vì thay đổi state
        t2 = TestFileReceiver()
        t2.setup_method()
        try:
            t2.test_hash_mismatch_detected()
        finally:
            t2.teardown_method()
        print("  PASS")
    finally:
        t.teardown_method()

    print("\n✅ Tất cả test đều PASS")


if __name__ == "__main__":
    _run_standalone()