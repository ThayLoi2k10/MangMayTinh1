import socket
import sys
import threading
import time
from protocol import (
    Packet,
    MSG_HELLO_REQ,
    MSG_HELLO_RESP,
    MSG_AUTH_REQ,
    MSG_AUTH_RESP,
    MSG_HEARTBEAT,
    STATUS_OK,
    encode_packet,
    recv_tcp_packet,
    dump_json,
    load_json,
)

SERVER_IP = "127.0.0.1"
TCP_PORT = 9000
UDP_PORT = 9001


def run_heartbeat_sender(udp_sock, stop_event):
    """Gửi heartbeat định kỳ mỗi 5s (seqDiagram1)."""
    hb_pkt = Packet(msg_type=MSG_HEARTBEAT, seq_no=0)
    wire_data = encode_packet(hb_pkt)
    
    while not stop_event.is_set():
        try:
            udp_sock.sendto(wire_data, (SERVER_IP, UDP_PORT))
            print(f"[*] [UDP] Đã gửi HEARTBEAT (0x10) tới Server.")
        except OSError:
            break
        # Ngủ 5 giây hoặc thức nếu có tín hiệu dừng
        stop_event.wait(5.0)


def test_heartbeat_and_timeout(username: str, client_udp_port: int):
    # Khởi tạo UDP socket với port cố định đã đăng ký
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("0.0.0.0", client_udp_port))

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.connect((SERVER_IP, TCP_PORT))

    stop_hb = threading.Event()

    try:
        # 1. Handshake & Login
        tcp_sock.sendall(encode_packet(Packet(msg_type=MSG_HELLO_REQ)))
        assert recv_tcp_packet(tcp_sock).msg_type == MSG_HELLO_RESP

        auth_data = dump_json({"username": username, "udp_port": client_udp_port})
        tcp_sock.sendall(encode_packet(Packet(msg_type=MSG_AUTH_REQ, payload=auth_data)))
        resp_auth = recv_tcp_packet(tcp_sock)
        assert resp_auth.status == STATUS_OK

        session_id = load_json(resp_auth.payload).get("session_id")
        print(f"[{username}] Đã đăng nhập (Session: {session_id}). Bắt đầu luồng Heartbeat...")

        # 2. Khởi động luồng gửi heartbeat
        hb_thread = threading.Thread(target=run_heartbeat_sender, args=(udp_sock, stop_hb), daemon=True)
        hb_thread.start()

        # Cho client duy trì sống bình thường trong 11 giây (sẽ gửi 2-3 nhịp heartbeat)
        print(f"[{username}] Duy trì gửi heartbeat trong 11 giây...")
        time.sleep(11)

        # 3. Kịch bản client bị treo/đứt mạng: Dừng gửi heartbeat
        print(f"\n[!] Cố tình dừng Heartbeat để thử thách Watchdog của Server...")
        stop_hb.set()

        # Chờ socket TCP bị server watchdog đá (quá hạn 15s)
        print(f"[{username}] Đang lắng nghe kênh TCP chờ xem server có đá kết nối không...")
        data = tcp_sock.recv(1024)
        if not data:
            print(f"[SUCCESS] Phía Server đã tự động đóng kết nối TCP do quá hạn 15s không nhận được Heartbeat!")

    finally:
        stop_hb.set()
        tcp_sock.close()
        udp_sock.close()
        print(f"[{username}] Hoàn tất bài test.")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "alice"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9005
    test_heartbeat_and_timeout(name, port)