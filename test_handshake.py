import socket
from protocol import (
    Packet,
    MSG_HELLO_REQ,
    MSG_HELLO_RESP,
    STATUS_OK,
    encode_packet,
    recv_tcp_packet,
)

SERVER_IP = "127.0.0.1"
TCP_PORT = 9000


def test_handshake():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print(f"[*] Đang kết nối tới server {SERVER_IP}:{TCP_PORT}...")
    sock.connect((SERVER_IP, TCP_PORT))

    try:
        # Gửi HELLO_REQ (0x01)
        hello_pkt = Packet(msg_type=MSG_HELLO_REQ)
        sock.sendall(encode_packet(hello_pkt))
        print("[*] Đã gửi HELLO_REQ (0x01), đang chờ phản hồi...")

        # Nhận HELLO_RESP (0x02)
        resp = recv_tcp_packet(sock)
        if resp.msg_type == MSG_HELLO_RESP and resp.status == STATUS_OK:
            print("[SUCCESS] Nhận phản hồi HELLO_RESP hợp lệ. Bắt tay thành công!")
        else:
            print(f"[FAIL] Bắt tay thất bại. Type={hex(resp.msg_type)}, Status={resp.status}")
    finally:
        sock.close()


if __name__ == "__main__":
    test_handshake()