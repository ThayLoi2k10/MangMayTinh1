MAGIC = b"NP"
VERSION = 1

FLAG_ENCRYPTED = 1
FLAG_END = 2

HEARTBEAT = 1
MSG = 2
FILE_META = 3
FILE_CHUNK = 4
ACK = 5
USER_LIST = 6


import json
import struct
import uuid
from dataclasses import dataclass
from cryptography.fernet import Fernet
from config import FERNET_KEY


cipher = Fernet(FERNET_KEY.encode())

# !  : Network Byte Order (Big-Endian)
# 2s : Magic (2 bytes)
# B  : Version (1 byte)
# B  : Packet Type (1 byte)
# B  : Flags (1 byte)
# I  : Sequence Number (4 bytes, uint32)
# 16s: Message ID (16 bytes UUID)
# H  : Chunk Index (2 bytes, uint16)
# H  : Total Chunks (2 bytes, uint16)
# I  : Payload Size (4 bytes, uint32)
HEADER = struct.Struct("!2sBBB I 16s H H I")


@dataclass
class Packet:
    ptype: int
    seq: int
    msg_id: uuid.UUID
    chunk: int = 0
    total: int = 1
    flags: int = 0
    payload: bytes = b""


def encode_packet(packet: Packet, encrypt: bool = True) -> bytes:
    payload = packet.payload
    flags = packet.flags

    if encrypt and payload:
        payload = cipher.encrypt(payload)
        flags |= FLAG_ENCRYPTED

    header = HEADER.pack(
        MAGIC,
        VERSION,
        packet.ptype,
        flags,
        packet.seq,
        packet.msg_id.bytes,
        packet.chunk,
        packet.total,
        len(payload),
    )
    return header + payload


def decode_packet(data: bytes) -> Packet:
    if len(data) < HEADER.size:
        raise ValueError("Gói tin quá ngắn (dưới 33 bytes)")

    magic, version, ptype, flags, seq, mid_bytes, chunk, total, size = HEADER.unpack(
        data[:HEADER.size]
    )

    if magic != MAGIC or version != VERSION:
        raise ValueError("Gói tin không hợp lệ: Sai MAGIC hoặc VERSION")

    payload = data[HEADER.size : HEADER.size + size]

    if (flags & FLAG_ENCRYPTED) and payload:
        payload = cipher.decrypt(payload)

    return Packet(
        ptype=ptype,
        seq=seq,
        msg_id=uuid.UUID(bytes=mid_bytes),
        chunk=chunk,
        total=total,
        flags=flags,
        payload=payload,
    )


def json_bytes(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


def json_obj(payload: bytes) -> dict:
    return json.loads(payload.decode("utf-8"))


def new_id() -> uuid.UUID:
    return uuid.uuid4()