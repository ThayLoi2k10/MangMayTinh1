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


def run_handshake():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    
    print(f"[*] Đang kết nối TCP tới {SERVER_IP}:{TCP_PORT}...")
    sock.connect((SERVER_IP, TCP_PORT))
    print("[+] Đã thiết lập kết nối TCP (OS 3-way handshake thành công)")

    try:
        # Bước 1: Tạo và gửi gói HELLO_REQ (Type=0x01, Len=0)
        hello_req = Packet(msg_type=MSG_HELLO_REQ)
        wire_data = encode_packet(hello_req)
        sock.sendall(wire_data)
        print(f"[*] Đã gửi HELLO_REQ ({len(wire_data)} bytes). Đang đợi phản hồi...")

        # Bước 2: Chờ nhận phản hồi HELLO_RESP từ Server
        resp = recv_tcp_packet(sock)
        print(f"[*] Nhận gói phản hồi: Type={hex(resp.msg_type)}, Status={hex(resp.status)}")

        # Bước 3: Kiểm tra tính hợp lệ
        if resp.msg_type == MSG_HELLO_RESP and resp.status == STATUS_OK:
            print("[SUCCESS] Handshake thành công! Sẵn sàng cho bước Authentication.")
        else:
            print(f"[FAIL] Handshake bị từ chối hoặc sai định dạng. Status={hex(resp.status)}")

    except socket.timeout:
        print("[-] Lỗi: Timeout khi đợi phản hồi từ Server.")
    except Exception as err:
        print(f"[-] Lỗi kết nối: {err}")
    finally:
        sock.close()
        print("[*] Đã ngắt kết nối.")


if __name__ == "__main__":
    run_handshake()