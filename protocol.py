import json
import struct
from dataclasses import dataclass

MAGIC_NUMBER = 0xDCBA

# Message Types (Opcodes)
MSG_HELLO_REQ   = 0x01
MSG_HELLO_RESP  = 0x02
MSG_AUTH_REQ    = 0x03
MSG_AUTH_RESP   = 0x04
MSG_LOGOUT_REQ  = 0x05
MSG_LOGOUT_RESP = 0x06
MSG_HEARTBEAT   = 0x10
MSG_USER_LIST   = 0x11
MSG_EOF         = 0x12
MSG_DATA        = 0x20
MSG_ACK         = 0x21

# Status Codes
STATUS_NONE = 0x00
STATUS_OK   = 0x01
STATUS_ERR  = 0x02

# Header struct: Big-Endian (!), uint16, uint8, uint8, uint16, uint16 -> 8 bytes
HEADER_FORMAT = "!HBBHH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 8 bytes


@dataclass
class Packet:
    msg_type: int
    status: int = STATUS_NONE
    seq_no: int = 0
    payload: bytes = b""


def encode_packet(packet: Packet) -> bytes:
    payload_len = len(packet.payload)
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC_NUMBER,
        packet.msg_type,
        packet.status,
        packet.seq_no,
        payload_len,
    )
    return header + packet.payload


def decode_header(header_bytes: bytes):
    if len(header_bytes) < HEADER_SIZE:
        raise ValueError(f"Header quá ngắn ({len(header_bytes)}/{HEADER_SIZE} bytes)")
    
    magic, msg_type, status, seq_no, payload_len = struct.unpack(
        HEADER_FORMAT, header_bytes
    )
    
    if magic != MAGIC_NUMBER:
        raise ValueError(f"Magic number không hợp lệ: {hex(magic)}")
        
    return msg_type, status, seq_no, payload_len


def decode_packet(data: bytes) -> Packet:
    if len(data) < HEADER_SIZE:
        raise ValueError("Gói tin ngắn hơn kích thước header tối thiểu")
        
    msg_type, status, seq_no, payload_len = decode_header(data[:HEADER_SIZE])
    payload = data[HEADER_SIZE : HEADER_SIZE + payload_len]
    
    if len(payload) != payload_len:
        raise ValueError("Kích thước payload thực tế không khớp với độ dài trong header")
        
    return Packet(msg_type, status, seq_no, payload)


def recv_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("Kết nối bị đóng giữa chừng khi đang đọc dữ liệu")
        buf.extend(chunk)
    return bytes(buf)


def recv_tcp_packet(sock) -> Packet:
    header_bytes = recv_exact(sock, HEADER_SIZE)
    msg_type, status, seq_no, payload_len = decode_header(header_bytes)
    
    payload = b""
    if payload_len > 0:
        payload = recv_exact(sock, payload_len)
        
    return Packet(msg_type, status, seq_no, payload)


def dump_json(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


def load_json(payload: bytes) -> dict:
    if not payload:
        return {}
    return json.loads(payload.decode("utf-8"))