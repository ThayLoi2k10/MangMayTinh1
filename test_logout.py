import socket
import sys
import time
from protocol import (
    Packet,
    MSG_HELLO_REQ,
    MSG_HELLO_RESP,
    MSG_AUTH_REQ,
    MSG_AUTH_RESP,
    MSG_LOGOUT_REQ,
    MSG_LOGOUT_RESP,
    STATUS_OK,
    encode_packet,
    recv_tcp_packet,
    dump_json,
    load_json,
)

SERVER_IP = "127.0.0.1"
TCP_PORT = 9000


def test_login_and_logout(username: str, udp_port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, TCP_PORT))

    try:
        # 1. Handshake
        sock.sendall(encode_packet(Packet(msg_type=MSG_HELLO_REQ)))
        resp_hello = recv_tcp_packet(sock)
        assert resp_hello.msg_type == MSG_HELLO_RESP

        # 2. Login
        auth_data = dump_json({"username": username, "udp_port": udp_port})
        sock.sendall(encode_packet(Packet(msg_type=MSG_AUTH_REQ, payload=auth_data)))
        resp_auth = recv_tcp_packet(sock)
        assert resp_auth.status == STATUS_OK

        session_id = load_json(resp_auth.payload).get("session_id")
        print(f"[{username}] Đã online thành công (Session: {session_id}). Giữ kết nối 2 giây...")
        time.sleep(2)

        # 3. Gửi LOGOUT_REQ
        print(f"[{username}] Bắt đầu gửi yêu cầu LOGOUT_REQ (0x05)...")
        logout_data = dump_json({"username": username, "session_id": session_id})
        sock.sendall(encode_packet(Packet(msg_type=MSG_LOGOUT_REQ, payload=logout_data)))

        # 4. Nhận LOGOUT_RESP
        resp_logout = recv_tcp_packet(sock)
        if resp_logout.msg_type == MSG_LOGOUT_RESP and resp_logout.status == STATUS_OK:
            print(f"[{username}] [SUCCESS] Nhận LOGOUT_RESP (0x06) thành công. Server đã xóa phiên.")
        else:
            print(f"[{username}] [FAIL] Server từ chối logout.")

    finally:
        # 5. Graceful shutdown socket phía Client
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        print(f"[{username}] Đã đóng socket.")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "alice"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9005
    test_login_and_logout(name, port)