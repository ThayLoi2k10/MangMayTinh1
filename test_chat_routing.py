#!/usr/bin/env python3
"""
test_chat_routing.py
Kiểm thử Chat Routing (Broadcast / Unicast) trên Server.

Yêu cầu:
  - Server đã chạy (python server.py)
  - File protocol.py nằm cùng thư mục hoặc trong PYTHONPATH

Cách chạy:
  python test_chat_routing.py
"""

import socket
import threading
import time
import sys
from protocol import (
    Packet,
    MSG_HELLO_REQ,
    MSG_HELLO_RESP,
    MSG_AUTH_REQ,
    MSG_AUTH_RESP,
    MSG_LOGOUT_REQ,
    MSG_LOGOUT_RESP,
    MSG_DATA,
    STATUS_OK,
    STATUS_ERR,
    encode_packet,
    recv_tcp_packet,
    dump_json,
    load_json,
)

SERVER_HOST = "127.0.0.1"
TCP_PORT = 9000


class TestClient:
    """Client đơn giản dùng để kiểm thử routing."""

    def __init__(self, username: str, udp_port: int):
        self.username = username
        self.udp_port = udp_port
        self.sock = None
        self.session_id = None
        self.received_messages = []          # list of dict
        self._recv_thread = None
        self._running = False
        self._lock = threading.Lock()

    def connect_and_auth(self) -> bool:
        """Thực hiện Handshake + Authentication."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((SERVER_HOST, TCP_PORT))

            # 1. HELLO
            self.sock.sendall(encode_packet(Packet(msg_type=MSG_HELLO_REQ)))
            resp = recv_tcp_packet(self.sock)
            if resp.msg_type != MSG_HELLO_RESP or resp.status != STATUS_OK:
                print(f"  [FAIL] {self.username}: HELLO failed")
                return False

            # 2. AUTH
            auth_payload = dump_json({
                "username": self.username,
                "udp_port": self.udp_port,
            })
            self.sock.sendall(encode_packet(Packet(msg_type=MSG_AUTH_REQ, payload=auth_payload)))
            resp = recv_tcp_packet(self.sock)

            if resp.msg_type != MSG_AUTH_RESP or resp.status != STATUS_OK:
                body = load_json(resp.payload)
                print(f"  [FAIL] {self.username}: AUTH failed → {body}")
                return False

            body = load_json(resp.payload)
            self.session_id = body.get("session_id")
            print(f"  [OK]   {self.username} authenticated (session={self.session_id[:8]}...)")

            # Bắt đầu luồng nhận tin
            self._running = True
            self.sock.settimeout(1.0)  # timeout ngắn để có thể dừng thread
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            return True

        except Exception as e:
            print(f"  [FAIL] {self.username}: connect/auth error → {e}")
            return False

    def _recv_loop(self):
        """Luồng nhận packet liên tục."""
        while self._running:
            try:
                pkt = recv_tcp_packet(self.sock)
                if pkt.msg_type == MSG_DATA:
                    body = load_json(pkt.payload)
                    with self._lock:
                        self.received_messages.append(body)
                    sender = body.get("sender", "?")
                    mode = body.get("mode", "?")
                    msg = body.get("message", "")
                    err = body.get("error")
                    if err:
                        print(f"  [RECV] {self.username} ← ERROR from server: {body.get('message')}")
                    else:
                        print(f"  [RECV] {self.username} ← [{mode}] from {sender}: \"{msg}\"")
                elif pkt.msg_type == MSG_LOGOUT_RESP:
                    break
            except socket.timeout:
                continue
            except (ConnectionResetError, ConnectionError, ValueError, OSError):
                break

    def send_broadcast(self, message: str):
        """Gửi tin broadcast."""
        payload = dump_json({
            "mode": "broadcast",
            "message": message,
        })
        self.sock.sendall(encode_packet(Packet(msg_type=MSG_DATA, payload=payload)))
        print(f"  [SEND] {self.username} → BROADCAST: \"{message}\"")

    def send_unicast(self, recipient: str, message: str):
        """Gửi tin unicast."""
        payload = dump_json({
            "mode": "unicast",
            "recipient": recipient,
            "message": message,
        })
        self.sock.sendall(encode_packet(Packet(msg_type=MSG_DATA, payload=payload)))
        print(f"  [SEND] {self.username} → UNICAST to {recipient}: \"{message}\"")

    def logout(self):
        """Gửi logout và đóng kết nối."""
        if self.sock and self.session_id:
            try:
                payload = dump_json({"session_id": self.session_id})
                self.sock.sendall(encode_packet(Packet(msg_type=MSG_LOGOUT_REQ, payload=payload)))
                # Đợi một chút để nhận LOGOUT_RESP
                time.sleep(0.3)
            except Exception:
                pass
        self._running = False
        if self._recv_thread:
            self._recv_thread.join(timeout=1.0)
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        print(f"  [OK]   {self.username} logged out")

    def get_messages(self):
        with self._lock:
            return list(self.received_messages)

    def clear_messages(self):
        with self._lock:
            self.received_messages.clear()


def wait_for_messages(clients, timeout=1.5):
    """Chờ một khoảng thời gian để các client nhận tin."""
    time.sleep(timeout)


def print_separator(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main():
    print("=" * 60)
    print("  TEST CHAT ROUTING (Broadcast / Unicast)")
    print("  Đảm bảo server đang chạy trên TCP 9000")
    print("=" * 60)

    # Tạo 3 client với UDP port khác nhau
    alice = TestClient("alice", 19001)
    bob   = TestClient("bob",   19002)
    cara  = TestClient("cara",  19003)

    # ========== SETUP ==========
    print_separator("1. Kết nối & Xác thực 3 client")
    ok_a = alice.connect_and_auth()
    ok_b = bob.connect_and_auth()
    ok_c = cara.connect_and_auth()

    if not (ok_a and ok_b and ok_c):
        print("\n[ERROR] Không thể xác thực đủ 3 client. Dừng test.")
        for c in (alice, bob, cara):
            c.logout()
        sys.exit(1)

    time.sleep(0.5)  # cho server ổn định

    # ========== TEST 1: Broadcast ==========
    print_separator("2. TEST 1 – Alice Broadcast")
    alice.clear_messages()
    bob.clear_messages()
    cara.clear_messages()

    alice.send_broadcast("Xin chào mọi người từ Alice!")
    wait_for_messages([bob, cara])

    bob_msgs = bob.get_messages()
    cara_msgs = cara.get_messages()
    alice_msgs = alice.get_messages()

    print("\n  Kết quả:")
    print(f"    Bob nhận được  : {len(bob_msgs)} tin")
    print(f"    Cara nhận được : {len(cara_msgs)} tin")
    print(f"    Alice nhận lại : {len(alice_msgs)} tin (mong đợi 0)")

    test1_pass = (
        len(bob_msgs) == 1 and
        len(cara_msgs) == 1 and
        len(alice_msgs) == 0 and
        bob_msgs[0].get("sender") == "alice" and
        bob_msgs[0].get("mode") == "broadcast"
    )
    print(f"  → TEST 1: {'PASS' if test1_pass else 'FAIL'}")

    # ========== TEST 2: Unicast ==========
    print_separator("3. TEST 2 – Alice Unicast đến Bob")
    alice.clear_messages()
    bob.clear_messages()
    cara.clear_messages()

    alice.send_unicast("bob", "Tin nhắn riêng cho Bob")
    wait_for_messages([bob, cara])

    bob_msgs = bob.get_messages()
    cara_msgs = cara.get_messages()
    alice_msgs = alice.get_messages()

    print("\n  Kết quả:")
    print(f"    Bob nhận được  : {len(bob_msgs)} tin")
    print(f"    Cara nhận được : {len(cara_msgs)} tin (mong đợi 0)")
    print(f"    Alice nhận lại : {len(alice_msgs)} tin (mong đợi 0 hoặc lỗi)")

    test2_pass = (
        len(bob_msgs) == 1 and
        len(cara_msgs) == 0 and
        bob_msgs[0].get("sender") == "alice" and
        bob_msgs[0].get("mode") == "unicast" and
        bob_msgs[0].get("message") == "Tin nhắn riêng cho Bob"
    )
    print(f"  → TEST 2: {'PASS' if test2_pass else 'FAIL'}")

    # ========== TEST 3: Unicast đến user không tồn tại ==========
    print_separator("4. TEST 3 – Alice Unicast đến user không tồn tại")
    alice.clear_messages()
    bob.clear_messages()
    cara.clear_messages()

    alice.send_unicast("david_not_exist", "Tin này không đến ai")
    wait_for_messages([alice, bob, cara], timeout=1.0)

    alice_msgs = alice.get_messages()
    bob_msgs = bob.get_messages()
    cara_msgs = cara.get_messages()

    print("\n  Kết quả:")
    print(f"    Alice nhận được : {len(alice_msgs)} tin (có thể là thông báo lỗi)")
    print(f"    Bob nhận được   : {len(bob_msgs)} tin (mong đợi 0)")
    print(f"    Cara nhận được  : {len(cara_msgs)} tin (mong đợi 0)")

    # Server không crash + không gửi nhầm cho người khác là PASS
    test3_pass = (len(bob_msgs) == 0 and len(cara_msgs) == 0)
    # Nếu server gửi lỗi về cho alice thì càng tốt
    if alice_msgs:
        print(f"    Nội dung lỗi trả về Alice: {alice_msgs[0]}")
    print(f"  → TEST 3: {'PASS' if test3_pass else 'FAIL'} (server không crash + không gửi nhầm)")

    # ========== TEST 4: Bob disconnect, Alice broadcast ==========
    print_separator("5. TEST 4 – Bob ngắt kết nối, Alice Broadcast")
    print("  → Bob đang logout...")
    bob.logout()
    time.sleep(0.8)  # cho server cập nhật registry

    alice.clear_messages()
    cara.clear_messages()

    alice.send_broadcast("Bob đã rời, chỉ còn Alice và Cara")
    wait_for_messages([cara], timeout=1.5)

    cara_msgs = cara.get_messages()
    alice_msgs = alice.get_messages()

    print("\n  Kết quả:")
    print(f"    Cara nhận được : {len(cara_msgs)} tin")
    print(f"    Alice nhận lại : {len(alice_msgs)} tin (mong đợi 0)")

    test4_pass = (
        len(cara_msgs) == 1 and
        len(alice_msgs) == 0 and
        cara_msgs[0].get("sender") == "alice"
    )
    print(f"  → TEST 4: {'PASS' if test4_pass else 'FAIL'}")

    # ========== CLEANUP ==========
    print_separator("6. Dọn dẹp")
    alice.logout()
    cara.logout()
    # bob đã logout rồi

    # ========== TỔNG KẾT ==========
    print("\n" + "=" * 60)
    print("  TỔNG KẾT")
    print("=" * 60)
    results = [
        ("TEST 1 – Broadcast", test1_pass),
        ("TEST 2 – Unicast", test2_pass),
        ("TEST 3 – Unicast offline", test3_pass),
        ("TEST 4 – Sau khi disconnect", test4_pass),
    ]
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status:4} | {name}")

    all_pass = all(p for _, p in results)
    print("-" * 60)
    if all_pass:
        print("  TẤT CẢ TEST ĐỀU PASS – Chat Routing hoạt động tốt!")
    else:
        print("  CÓ TEST BỊ FAIL – Kiểm tra lại logic server.")
    print("=" * 60)


if __name__ == "__main__":
    main()
