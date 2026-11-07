""" Module xử lý các vấn đề:
- Chia file thành các chunk
- Kiểm tra các metadata và chunk nhận được
- Theo dõi tiến trình truyền file.
- Ghép file và xác minh SHA-256.
- Mã hóa/giải mã payload bằng Fernet.
- Lưu file an toàn, không ghi đè file có sẵn.
 """

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import uuid
import time
import threading
from collections import OrderedDict

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import CHUNK_SIZE, FERNET_KEY
from stream_transport import OrderedByteStream

MAX_FILE_SIZE = 100*1024*1024
MAX_FILENAME_SIZE = 255

FILE_META = "FILE_META"
FILE_CHUNK = "FILE_CHUNK"
FILE_COMPLETE = "FILE_COMPLETE"
FILE_ERROR = "FILE_ERROR"

class FileTransferError(Exception):
    """Lỗi giao thức hoặc xử lý file"""


""" Encryption / Decryption """

def _cipher() -> Fernet:
    """ Tạo Fernet cipher từ khóa cấu hình của bài """
    key = (FERNET_KEY.encode("ascii") if isinstance(FERNET_KEY , str) else FERNET_KEY)

    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise FileTransferError("FERNET_KEY không hợp lệ") from exc

def encrypt_payload(payload: bytes) -> bytes:
    """ Mã hóa payload bằng Fernet"""
    if not isinstance(payload , bytes):
        raise TypeError("Payload không phải là bytes")

    return _cipher().encrypt(payload)

def decrypt_payload(token: bytes) -> bytes:
    """ Giải mã và xác thực Fernet token"""
    if not isinstance(token , bytes):
        raise TypeError("Token không phải là bytes")

    try:
        return _cipher().decrypt(token)
    except InvalidToken as exc:
        raise FileTransferError("Payload không valid , không decrypt được") from exc

def encode_secure_json(message: dict[str, Any]) -> bytes:
    """ Chuyển json thành bytes rồi mã hóa"""
    try:
        raw = json.dumps(message, ensure_ascii=False , separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FileTransferError("Không thể chuyển qua json") from exc

    return encrypt_payload(raw)

def decode_secure_json(payload: bytes) -> dict[str, Any]:
    """ Giải mã payload rồi phân tích thành json obj"""
    raw = decrypt_payload(payload)

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileTransferError(
            "JSON sau giải mã không hợp lệ"
        ) from exc

    if not isinstance(value , dict):
        raise FileTransferError("Payload phải là json obj")

    return value

def seal_chat_text(text: str) -> str:
    """Mã hóa nội dung chat thành Fernet token dạng chuỗi."""
    if not isinstance(text, str):
        raise FileTransferError("Nội dung chat phải là chuỗi")

    return encrypt_payload(text.encode("utf-8")).decode("ascii")


def open_chat_text(token: str) -> str:
    """Giải mã Fernet token thành nội dung chat."""
    if not isinstance(token, str):
        raise FileTransferError("Token chat phải là chuỗi")

    try:
        raw = decrypt_payload(token.encode("ascii"))
        return raw.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError) as exc:
        raise FileTransferError("Token chat không hợp lệ") from exc
    
""" Kiểm tra tính hợp lệ """
def safe_filename(name: Any) -> str:
    if not isinstance(name , str):
        raise FileTransferError("Tên file phải là chuỗi")

    if any(ch in name for ch in '/\\<>:"|?*'):
        raise FileTransferError("Tên file chứa ký tự không hợp lệ")

    cleaned = name.strip()

    if cleaned in ("", "." , ".."):
        raise FileTransferError("Tên file không hợp lệ")

    if len(cleaned) > MAX_FILENAME_SIZE:
        raise FileTransferError("Tên file quá dài")

    if any(ord(ch) < 32 for ch in cleaned):
        raise FileTransferError("Tên file chứa kí tự điều khiển")

    return cleaned

def split_file(data: bytes , chunk_size: int = CHUNK_SIZE) -> list[bytes]:
    """ Chia file thành các Chunk. Nếu file rỗng thì chunk rỗng """
    if not isinstance(data, bytes):
        raise TypeError("Data phải là bytes")

    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("Chunk size không hợp lệ")

    chunks = [data[i: i + chunk_size] for i in range(0 , len(data) , chunk_size)]

    return chunks or [b""]

@dataclass
class OutgoingFile:
    file_id: str
    filename: str
    size: int
    sha256: str
    chunks: list[bytes]
    chunk_size: int = CHUNK_SIZE

    @classmethod
    def from_bytes(cls, filename: str, data: bytes) -> "OutgoingFile":
        """ Tạo đối tượng truyền file đã có sẵn ở trong bộ nhớ"""
        name = safe_filename(filename)

        if not isinstance(data , bytes):
            raise TypeError("Data phải là bytes")

        if len(data) > MAX_FILE_SIZE:
            raise FileTransferError(f"File vượt quá {MAX_FILE_SIZE}")

        chunks = split_file(data , CHUNK_SIZE)

        return cls(file_id = uuid.uuid4().hex,
                   filename = name,
                   size = len(data),
                   sha256 = hashlib.sha256(data).hexdigest(),
                   chunks = chunks,
                   chunk_size = CHUNK_SIZE
                   )

    @classmethod
    def from_path(cls, path: str | Path) -> "OutgoingFile":
        """ Đọc file từ đường dẫn ở phía gửi"""
        source = Path(path)

        if not source.is_file():
            raise FileTransferError("Đường dẫn không phải file hợp lệ")

        if source.stat().st_size > MAX_FILE_SIZE:
            raise FileTransferError(f"File vượt quá {MAX_FILE_SIZE}")

        return cls.from_bytes(source.name , source.read_bytes())

    def metadata_message(self , recipient: str) -> dict[str, Any]:
        """ Thông tin gửi trước chunks """
        return {
            "kind": FILE_META,
            "file_id": self.file_id,
            "to": recipient,
            "filename": self.filename,
            "size": self.size,
            "sha256": self.sha256,
            "chunk_size": self.chunk_size,
            "total_chunks": len(self.chunks),
        }

    def chunk_message(self , index: int , recipient: str) -> dict[str, Any]:
        """ Tạo thông điệp chứa 1 chunk"""
        if type(index) is not int:
            raise FileTransferError("Chỉ số chunks phải là nguyên")

        if not 0 <= index < len(self.chunks):
            raise FileTransferError("Index nằm ngoài phạm vi")

        return {
            "kind": FILE_CHUNK,
            "file_id": self.file_id,
            "to": recipient,
            "chunk_index": index,
            "total_chunks": len(self.chunks),
            "data": base64.b64encode(self.chunks[index]).decode("ascii"),
        }

@dataclass
class IncomingFile:
    file_id: str
    filename: str
    size: int
    sha256: str
    total_chunks: int
    chunk_size: int
    sender: str = "?"
    chunks: dict[int, bytes] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    stream: OrderedByteStream = field(default_factory=lambda: OrderedByteStream(max_buffer_bytes=MAX_FILE_SIZE))

    @property
    def progress(self) -> int:
        return int(len(self.chunks) * 100 / self.total_chunks)

    @property
    def missing_chunks(self) -> list[int]:
        return [i for i in range(self.total_chunks) if i not in self.chunks]

    
class FileReceiver:
    """Validate files and expose provisional ordered bytes before atomic commit.

    Receiver state is serialized independently of sender/UI locks. Terminal
    outcomes retain metadata, never file bytes, for a bounded replay horizon.
    """
    TERMINAL_TTL = 120.0
    MAX_HISTORY = 256
    MAX_ACTIVE = 8

    def __init__(self, download_dir: str | Path = "downloads"):
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.incoming: dict[str, IncomingFile] = {}
        self.progress: dict[str, dict[str, Any]] = {}
        self._terminal: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _identity(item: IncomingFile) -> tuple:
        return (item.filename, item.size, item.sha256, item.total_chunks, item.chunk_size)

    def _prune(self) -> None:
        now = time.monotonic()
        for fid, value in list(self._terminal.items()):
            if now - value["finished_at"] > self.TERMINAL_TTL:
                self._terminal.pop(fid)
        while len(self._terminal) > self.MAX_HISTORY:
            self._terminal.popitem(last=False)
        for fid in list(self.progress):
            if len(self.progress) <= self.MAX_HISTORY + self.MAX_ACTIVE:
                break
            if fid not in self.incoming:
                self.progress.pop(fid)

    def _finish(self, item: IncomingFile, status: str, error: str = "") -> dict:
        rec = self.progress[item.file_id]
        rec["status"] = status if status in ("completed", "timeout") else f"failed: {error}"
        if status == "completed":
            rec["progress"] = 100
            item.stream.finish(item.total_chunks)
        else:
            item.stream.fail(FileTransferError(error or status))
        result = {"file_id": item.file_id, "status": status, "error": error,
                  "size": item.size, "sha256": item.sha256,
                  "peer": item.sender, "identity": self._identity(item),
                  "finished_at": time.monotonic()}
        self._terminal[item.file_id] = result
        self.incoming.pop(item.file_id, None)
        self._prune()
        return dict(result)

    def terminal_result(self, file_id: str, sender: str) -> dict | None:
        with self._lock:
            self._prune()
            result = self._terminal.get(file_id)
            return dict(result) if result and result["peer"] == sender else None

    def metadata_matches(self, result: dict, message: dict) -> bool:
        return result["identity"] == (
            message.get("filename"), message.get("size"), message.get("sha256"),
            message.get("total_chunks"), message.get("chunk_size", CHUNK_SIZE))

    def get_stream(self, file_id: str) -> OrderedByteStream:
        """Subscribe while receiving; EOF means verified/committed, not just bytes."""
        with self._lock:
            return self.incoming[file_id].stream

    def abort(self, file_id: str, sender: str, error: str) -> dict | None:
        with self._lock:
            item = self.incoming.get(file_id)
            if item is None or item.sender != sender:
                return None
            return self._finish(item, "failed", error)

    def close(self) -> None:
        with self._lock:
            for item in list(self.incoming.values()):
                self._finish(item, "failed", "Client closed")

    def cleanup_expired(self, max_age: float = 120.0) -> list[str]:
        with self._lock:
            now = time.monotonic()
            expired = [fid for fid, item in self.incoming.items()
                       if now - item.last_activity > max_age]
            for fid in expired:
                self._finish(self.incoming[fid], "timeout", "Receiver inactivity timeout")
            self._prune()
            return expired

    def accept_metadata(self, message: dict[str, Any], sender: str = "?") -> IncomingFile:
        with self._lock:
            if not isinstance(message, dict) or message.get("kind") != FILE_META:
                raise FileTransferError("Thông điệp metadata không hợp lệ")
            fid = message.get("file_id")
            if not isinstance(fid, str) or not re.fullmatch(r"[0-9a-f]{32}", fid):
                raise FileTransferError("file_id không hợp lệ")
            name = safe_filename(message.get("filename"))
            size, total = message.get("size"), message.get("total_chunks")
            chunk_size, digest = message.get("chunk_size", CHUNK_SIZE), message.get("sha256")
            if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
                raise FileTransferError("Size không hợp lệ")
            if type(chunk_size) is not int or not 1 <= chunk_size <= CHUNK_SIZE:
                raise FileTransferError("Chunk_size không hợp lệ")
            expected_total = max(1, (size + chunk_size - 1) // chunk_size)
            if type(total) is not int or total != expected_total or total > 200000:
                raise FileTransferError("Total không hợp lệ")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise FileTransferError("SHA-256 không hợp lệ")
            identity = (name, size, digest, total, chunk_size)
            existing = self.incoming.get(fid)
            if existing:
                if existing.sender != sender or self._identity(existing) != identity:
                    raise FileTransferError("Metadata trùng không khớp hoặc khác người gửi")
                return existing
            self._prune()
            if fid in self._terminal:
                raise FileTransferError("Transfer đã kết thúc; không tạo lại")
            if len(self.incoming) >= self.MAX_ACTIVE:
                raise FileTransferError("Too many active receiving transfers")
            item = IncomingFile(fid, name, size, digest, total, chunk_size, sender=sender)
            self.incoming[fid] = item
            self.progress[fid] = {
                "file_id": fid, "filename": name, "sender": sender,
                "status": "receiving", "progress": 0, "received_chunks": 0,
                "total_chunks": total}
            self._prune()
            return item

    def accept_chunk(self, message: dict[str, Any], sender: str | None = None) -> dict[str, Any]:
        with self._lock:
            if not isinstance(message, dict) or message.get("kind") != FILE_CHUNK:
                raise FileTransferError("Thông điệp chunk không hợp lệ")
            fid = message.get("file_id")
            if not isinstance(fid, str):
                raise FileTransferError("file_id không hợp lệ")
            item = self.incoming.get(fid)
            if item is None or (sender is not None and item.sender != sender):
                return {"ignored": True, "file_id": fid, "complete": False}
            total, idx, encoded = message.get("total_chunks"), message.get("chunk_index"), message.get("data")
            try:
                if type(total) is not int or total != item.total_chunks:
                    raise FileTransferError("Total_chunks không khớp metadata")
                if type(idx) is not int or not 0 <= idx < item.total_chunks:
                    raise FileTransferError("Chunk_index nằm ngoài phạm vi")
                if not isinstance(encoded, str):
                    raise FileTransferError("Dữ liệu chunk phải là Base64 string")
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise FileTransferError("Dữ liệu Base64 không hợp lệ") from exc
                expected_len = item.chunk_size if idx < item.total_chunks - 1 else item.size - item.chunk_size * (item.total_chunks - 1)
                if len(chunk) != expected_len:
                    raise FileTransferError("Kích thước chunk không hợp lệ")
                previous = item.chunks.get(idx)
                if previous is not None and previous != chunk:
                    raise FileTransferError("Chunk trùng có nội dung khác nhau")
                if previous is None:
                    item.stream.feed(idx, chunk)
                    item.chunks[idx] = chunk
                item.last_activity = time.monotonic()
                rec = self.progress[fid]
                rec.update(received_chunks=len(item.chunks), progress=item.progress)
                if len(item.chunks) < item.total_chunks:
                    return {"kind": "ACK", "file_id": fid, "chunk_index": idx,
                            "complete": False, "progress": item.progress}
                # Streaming hash/write avoids a second whole-file concatenation.
                digest = hashlib.sha256()
                for index in range(item.total_chunks):
                    digest.update(item.chunks[index])
                if digest.hexdigest() != item.sha256:
                    raise FileTransferError("SHA-256 không khớp")
                target = self.download_dir / item.filename
                temporary = self.download_dir / f".{item.file_id}.part"
                owned_temp = False
                try:
                    with temporary.open("xb") as stream:
                        owned_temp = True
                        for index in range(item.total_chunks):
                            stream.write(item.chunks[index])
                        stream.flush()
                        os.fsync(stream.fileno())
                    # Same-filesystem hard link atomically publishes without replacing
                    # an existing file, including a destination created after metadata.
                    os.link(temporary, target)
                except FileExistsError as exc:
                    raise FileTransferError("File đích đã tồn tại; không ghi đè") from exc
                except OSError as exc:
                    raise FileTransferError("Không thể lưu file nhận được") from exc
                finally:
                    if owned_temp:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass  # Never turn a successfully published file into failure.
                self._finish(item, "completed")
                return {"kind": FILE_COMPLETE, "file_id": fid, "filename": item.filename,
                        "size": item.size, "sha256": item.sha256, "path": str(target),
                        "progress": 100}
            except (FileTransferError, BufferError) as exc:
                self._finish(item, "failed", str(exc))
                if isinstance(exc, FileTransferError):
                    raise
                raise FileTransferError(str(exc)) from exc

    def get_progress(self, file_id: str) -> dict[str, Any] | None:
        if not isinstance(file_id, str):
            return None
        with self._lock:
            record = self.progress.get(file_id)
            return dict(record) if record else None
