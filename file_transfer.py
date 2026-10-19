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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import CHUNK_SIZE, FERNET_KEY

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
    created_at: float = field(default_factory=time.time)

    @property
    def progress(self) -> int:
        return int(len(self.chunks) * 100 / self.total_chunks)

    @property
    def missing_chunks(self) -> list[int]:
        return [i for i in range(self.total_chunks) if i not in self.chunks]

    
class FileReceiver:
    """ Quản lý metadata , chunk , tiến trình và lưu file nhận """
    def __init__(self, download_dir: str | Path = "downloads"):
        self.download_dir = Path(download_dir).resolve()

        self.download_dir.mkdir(parents=True , exist_ok=True)
        self.incoming: dict[str, IncomingFile] = {}
        self.progress: dict[str, dict[str, Any]] = {}

    def cleanup_expired(self, max_age: float = 120.0) -> list[str]:
        """Xóa các file nhận quá thời gian cho phép """
        now = time.time()
        expired = [
            fid for fid, item in self.incoming.items()
            if now - item.created_at > max_age
        ]
        for fid in expired:
            self.incoming.pop(fid, None)
            if fid in self.progress:
                self.progress[fid]["status"] = "timeout"
        return expired
    
    def accept_metadata(self, message: dict[str, Any] , sender: str = "?") -> IncomingFile:
        """ Kiểm tra metadata và khởi tạo trạng thái nhận file """
        if(not isinstance(message, dict) or message.get("kind") != FILE_META):
            raise FileTransferError("Thông điệp metadata không hợp lệ")

        fid = message.get("file_id")

        if (not isinstance(fid, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", fid)):
            raise FileTransferError("file_id không hợp lệ")

        fid = fid.lower()

        if fid in self.incoming:
            return self.incoming[fid]

        name = safe_filename(message.get("filename"))

        size = message.get("size")
        total = message.get("total_chunks")
        chunk_size = message.get("chunk_size", CHUNK_SIZE)
        digest = message.get("sha256")

        if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
            raise FileTransferError("Size không hợp lệ")

        if type(chunk_size) is not int or chunk_size <= 0:
            raise FileTransferError("Chunk_size không hợp lệ")

        expected_total = max(1, (size + chunk_size - 1) // chunk_size)

        if type(total) is not int or total != expected_total:
            raise FileTransferError("Total không hợp lệ")

        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}",digest)):
            raise FileTransferError("SHA-256 không hợp lệ")

        item = IncomingFile(
            file_id=fid,
            filename=name,
            size=size,
            sha256=digest.lower(),
            total_chunks=total,
            chunk_size=chunk_size,
            sender=sender,
        )

        self.incoming[fid] = item

        self.progress[fid] = {
            "file_id": fid,
            "filename": name,
            "sender": sender,
            "status": "receiving",
            "progress": 0,
            "received_chunks": 0,
            "total_chunks": total,
        }

        return item

    def accept_chunk(self, message: dict[str, Any],) -> dict[str, Any]:
        """Nhận một chunk, ghép và kiểm tra khi đã đủ chunk """
        if (not isinstance(message, dict) or message.get("kind") != FILE_CHUNK):
            raise FileTransferError("Thông điệp chunk không hợp lệ")

        fid = message.get("file_id")

        if not isinstance(fid, str):
            raise FileTransferError("file_id không hợp lệ")

        item = self.incoming.get(fid.lower())

        if item is None:
            # Retransmit / chunk muộn sau khi đã hoàn tất hoặc đã hủy
            return {
                "kind": "ACK",
                "file_id": fid.lower(),
                "chunk_index": message.get("chunk_index", -1),
                "complete": False,
                "ignored": True,
            }

        total = message.get("total_chunks")

        if type(total) is not int or total != item.total_chunks:
            raise FileTransferError("Total_chunks không khớp metadata")
        
        idx = message.get("chunk_index")

        if (type(idx) is not int or not 0 <= idx < item.total_chunks):
            raise FileTransferError("Chunk_index nằm ngoài phạm vi")

        encoded = message.get("data")

        if not isinstance(encoded, str):
            raise FileTransferError("Dữ liệu chunk phải là Base64 string")

        try:
            chunk = base64.b64decode(encoded,validate=True)
        except (binascii.Error, ValueError) as exc:
            raise FileTransferError("Dữ liệu Base64 không hợp lệ") from exc

        if idx < item.total_chunks - 1:
            expected_len = item.chunk_size
        else:
            expected_len = (item.size - item.chunk_size * (item.total_chunks - 1))

        if len(chunk) != expected_len:
            raise FileTransferError("Kích thước chunk không hợp lệ")

        """Chunk trùng không làm tăng tiến trình.
        Nếu cùng chỉ số nhưng nội dung khác thì từ chối"""
        previous = item.chunks.get(idx)

        if previous is not None and previous != chunk:
            raise FileTransferError("Chunk trùng có nội dung khác nhau")

        item.chunks.setdefault(idx, chunk)

        rec = self.progress[item.file_id]
        rec["received_chunks"] = len(item.chunks)
        rec["progress"] = item.progress

        if item.missing_chunks:
            return {
                "kind": "ACK",
                "file_id": item.file_id,
                "chunk_index": idx,
                "complete": False,
                "missing_chunks": item.missing_chunks,
                "progress": item.progress,
            }

        data = b"".join(item.chunks[i] for i in range(item.total_chunks))

        if len(data) != item.size:
            rec["status"] = "failed: size mismatch"
            raise FileTransferError("Kích thước file sau khi ghép không khớp")

        actual_digest = hashlib.sha256(data).hexdigest()

        if actual_digest != item.sha256:
            rec["status"] = "failed: hash mismatch"
            self.incoming.pop(item.file_id, None)
            raise FileTransferError("SHA-256 không khớp")

        target = self.download_dir / item.filename

        if target.exists():
            rec["status"] = "failed: destination exists"
            self.incoming.pop(item.file_id, None)
            raise FileTransferError("File đích đã tồn tại; không ghi đè")

        temp = self.download_dir / (f".{item.file_id}.part")

        try:
            with temp.open("wb") as stream:
                stream.write(data)

            os.replace(temp, target)

        except FileTransferError:
            temp.unlink(missing_ok=True)
            raise

        except OSError as exc:
            temp.unlink(missing_ok=True)
            rec["status"] = "failed: disk error"
            self.incoming.pop(item.file_id, None)
            raise FileTransferError("Không thể lưu file nhận được") from exc

        rec["status"] = "completed"
        rec["progress"] = 100

        self.incoming.pop(item.file_id, None)

        return {
            "kind": FILE_COMPLETE,
            "file_id": item.file_id,
            "filename": item.filename,
            "size": item.size,
            "sha256": actual_digest,
            "path": str(target),
        }

    def get_progress(self, file_id: str) -> dict[str, Any] | None:
        """Lấy bản sao trạng thái truyền file"""
        if not isinstance(file_id, str):
            return None

        record = self.progress.get(file_id.lower())

        return dict(record) if record else None
