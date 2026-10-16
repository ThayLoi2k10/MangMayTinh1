import socket
import sys
from protocol import (
    Packet,
    MSG_HELLO_REQ,
    MSG_HELLO_RESP,
    MSG_AUTH_REQ,
    MSG_AUTH_RESP,
    STATUS_OK,
    STATUS_ERR,
    encode_packet,
    recv_tcp_packet,
    dump_json,
    load_json,
)

SERVER_IP = "127.0.0.1"
TCP_PORT = 9000


def run_auth_client(username: str, udp_port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, TCP_PORT))
    
    try:
        # Bước 1: Gửi HELLO_REQ
        sock.sendall(encode_packet(Packet(msg_type=MSG_HELLO_REQ)))
        resp_hello = recv_tcp_packet(sock)
        if resp_hello.msg_type != MSG_HELLO_RESP or resp_hello.status != STATUS_OK:
            print(f"[{username}] Bắt tay thất bại.")
            return

        # Bước 2: Gửi AUTH_REQ
        payload = dump_json({"username": username, "udp_port": udp_port})
        sock.sendall(encode_packet(Packet(msg_type=MSG_AUTH_REQ, payload=payload)))
        
        # Bước 3: Đợi AUTH_RESP
        resp_auth = recv_tcp_packet(sock)
        res_data = load_json(resp_auth.payload)

        if resp_auth.status == STATUS_OK:
            print(f"[{username}] [SUCCESS] Đăng nhập thành công! Session ID: {res_data.get('session_id')}")
            print(f"[{username}] Đang giữ kết nối TCP (nhấn Ctrl+C để thoát)...")
            while True:
                # Giữ kết nối
                try:
                    data = sock.recv(1024)
                    if not data:
                        break
                except KeyboardInterrupt:
                    break
        else:
            print(f"[{username}] [REJECTED] Đăng nhập bị từ chối: {res_data.get('message')} (Code: {res_data.get('error_code')})")

    finally:
        sock.close()
        print(f"[{username}] Đã đóng kết nối.")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "alice"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9005
    run_auth_client(name, port)