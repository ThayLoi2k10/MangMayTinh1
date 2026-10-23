#!/usr/bin/env python3
"""
test_udp_streaming.py
Kiểm thử bộ truyền dữ liệu tin cậy UDP (Sender + Receiver)
với giả lập mất gói (packet loss).

Chạy:
    python test_udp_streaming.py
"""

import os
import sys
import time
import socket
import threading
import random
import hashlib
from typing import Tuple, Optional

# Đảm bảo import được protocol và udp_streamer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from protocol import encode_packet, decode_packet, Packet, MSG_DATA, MSG_ACK
from udp_streamer import (
    UDPStreamSender,
    UDPStreamReceiver,
    CHUNK_SIZE,
    WINDOW_SIZE,
    create_udp_socket,
)


# ======================== CÔNG CỤ GIẢ LẬP MẤT GÓI ========================
class LossySocket:
    """
    Wrapper quanh UDP socket để giả lập mất gói.
    drop_rate: xác suất bỏ gói (0.0 → 1.0)
    drop_data: có bỏ gói DATA không
    drop_ack:  có bỏ gói ACK không
    """

    def __init__(
        self,
        sock: socket.socket,
        drop_rate: float = 0.0,
        drop_data: bool = True,
        drop_ack: bool = True,
        name: str = "sock",
    ):
        self._sock = sock
        self.drop_rate = drop_rate
        self.drop_data = drop_data
        self.drop_ack = drop_ack
        self.name = name
        self.dropped_count = 0
        self.sent_count = 0
        self.recv_count = 0

    def sendto(self, data: bytes, addr):
        self.sent_count += 1
        should_drop = False
        try:
            pkt = decode_packet(data)
            if pkt.msg_type == MSG_DATA and self.drop_data:
                should_drop = random.random() < self.drop_rate
            elif pkt.msg_type == MSG_ACK and self.drop_ack:
                should_drop = random.random() < self.drop_rate
        except Exception:
            pass

        if should_drop:
            self.dropped_count += 1
            return  # giả lập mất gói – không gửi
        return self._sock.sendto(data, addr)

    def recvfrom(self, bufsize: int):
        data, addr = self._sock.recvfrom(bufsize)
        self.recv_count += 1
        return data, addr

    def settimeout(self, value):
        self._sock.settimeout(value)

    def getsockname(self):
        return self._sock.getsockname()

    def close(self):
        self._sock.close()

    def fileno(self):
        return self._sock.fileno()


# ======================== HÀM HỖ TRỢ ========================
def make_test_data(size: int, seed: int = 42) -> bytes:
    """Tạo dữ liệu giả lập có thể kiểm tra tính toàn vẹn."""
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(size))


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def run_transfer(
    data: bytes,
    drop_rate: float = 0.0,
    drop_data: bool = True,
    drop_ack: bool = True,
    timeout: float = 20.0,
    verbose: bool = True,
) -> Tuple[bool, dict]:
    """
    Thực hiện một lần truyền từ Sender → Receiver.
    Trả về (success, info_dict)
    """
    # Tạo socket thật
    real_sender_sock = create_udp_socket(0)
    real_receiver_sock = create_udp_socket(0)

    sender_port = real_sender_sock.getsockname()[1]
    receiver_port = real_receiver_sock.getsockname()[1]
    receiver_addr = ("127.0.0.1", receiver_port)

    # Bọc lossy
    sender_sock = LossySocket(
        real_sender_sock,
        drop_rate=drop_rate,
        drop_data=drop_data,
        drop_ack=False,          # phía gửi chủ yếu gửi DATA
        name="sender",
    )
    receiver_sock = LossySocket(
        real_receiver_sock,
        drop_rate=drop_rate,
        drop_data=False,         # phía nhận chủ yếu gửi ACK
        drop_ack=drop_ack,
        name="receiver",
    )

    receiver = UDPStreamReceiver(receiver_sock)
    sender = UDPStreamSender(sender_sock, receiver_addr)

    result = {
        "success": False,
        "received_ok": False,
        "original_md5": md5(data),
        "received_md5": None,
        "original_size": len(data),
        "received_size": 0,
        "sender_stats": {},
        "receiver_stats": {},
        "dropped_sender": 0,
        "dropped_receiver": 0,
        "elapsed": 0.0,
    }

    # Thread chạy Receiver
    recv_done = threading.Event()

    def receiver_loop():
        deadline = time.time() + timeout
        while time.time() < deadline and not receiver.is_complete():
            try:
                raw, addr = receiver_sock.recvfrom(2048)
                receiver.handle_raw(raw, addr)
            except socket.timeout:
                continue
            except Exception:
                break
        recv_done.set()

    t_recv = threading.Thread(target=receiver_loop, daemon=True)
    t_recv.start()

    # Cho receiver sẵn sàng
    time.sleep(0.05)

    # Gửi
    t0 = time.time()
    ok = sender.send_data(data, timeout=timeout)
    elapsed = time.time() - t0

    # Chờ receiver xử lý hết
    recv_done.wait(timeout=3.0)
    t_recv.join(timeout=1.0)

    received = receiver.get_data()

    result["success"] = ok
    result["received_ok"] = received == data
    result["received_md5"] = md5(received) if received else None
    result["received_size"] = len(received)
    result["sender_stats"] = sender.get_stats()
    result["receiver_stats"] = receiver.get_stats()
    result["dropped_sender"] = sender_sock.dropped_count
    result["dropped_receiver"] = receiver_sock.dropped_count
    result["elapsed"] = elapsed

    # Dọn
    try:
        real_sender_sock.close()
        real_receiver_sock.close()
    except Exception:
        pass

    if verbose:
        status = "PASS" if (ok and result["received_ok"]) else "FAIL"
        print(f"  [{status}] size={len(data):>7}  drop={drop_rate*100:.0f}%  "
              f"time={elapsed:.2f}s  "
              f"sent={result['sender_stats'].get('sent',0)}  "
              f"retrans={result['sender_stats'].get('retransmitted',0)}  "
              f"drop_data={result['dropped_sender']}  drop_ack={result['dropped_receiver']}")

    return ok and result["received_ok"], result


# ======================== CÁC TEST CASE ========================
def test_no_loss():
    print("\n=== TEST 1: Không mất gói ===")
    sizes = [100, 700, 1400, 5000, 50_000]
    all_ok = True
    for sz in sizes:
        data = make_test_data(sz)
        ok, _ = run_transfer(data, drop_rate=0.0)
        if not ok:
            all_ok = False
    return all_ok


def test_data_loss():
    print("\n=== TEST 2: Mất gói DATA (10% – 30%) ===")
    data = make_test_data(30_000)
    all_ok = True
    for rate in (0.10, 0.20, 0.30):
        ok, info = run_transfer(data, drop_rate=rate, drop_data=True, drop_ack=False)
        if not ok:
            all_ok = False
            print(f"    → MD5 gốc : {info['original_md5']}")
            print(f"    → MD5 nhận: {info['received_md5']}")
    return all_ok


def test_ack_loss():
    print("\n=== TEST 3: Mất gói ACK (10% – 20%) ===")
    data = make_test_data(20_000)
    all_ok = True
    for rate in (0.10, 0.20):
        ok, info = run_transfer(data, drop_rate=rate, drop_data=False, drop_ack=True)
        if not ok:
            all_ok = False
    return all_ok


def test_both_loss():
    print("\n=== TEST 4: Mất cả DATA + ACK (15%) ===")
    data = make_test_data(25_000)
    ok, info = run_transfer(data, drop_rate=0.15, drop_data=True, drop_ack=True)
    if not ok:
        print(f"    → MD5 gốc : {info['original_md5']}")
        print(f"    → MD5 nhận: {info['received_md5']}")
        print(f"    → Sender stats  : {info['sender_stats']}")
        print(f"    → Receiver stats: {info['receiver_stats']}")
    return ok


def test_large_file():
    print("\n=== TEST 5: File lớn (~200KB) với mất gói 10% ===")
    data = make_test_data(200_000)
    ok, info = run_transfer(
        data,
        drop_rate=0.10,
        drop_data=True,
        drop_ack=True,
        timeout=60.0,
    )
    if not ok:
        print(f"    → size nhận được: {info['received_size']} / {info['original_size']}")
        print(f"    → Sender stats: {info['sender_stats']}")
    return ok


def test_empty_and_small():
    print("\n=== TEST 6: File rỗng + file rất nhỏ ===")
    ok1, _ = run_transfer(b"", drop_rate=0.0)
    ok2, _ = run_transfer(b"hello", drop_rate=0.2)
    ok3, _ = run_transfer(make_test_data(1), drop_rate=0.0)
    return ok1 and ok2 and ok3


# ======================== MAIN ========================
def main():
    print("=" * 64)
    print("  TEST UDP RELIABLE STREAMING (Sliding Window ARQ)")
    print(f"  CHUNK_SIZE={CHUNK_SIZE}  WINDOW_SIZE={WINDOW_SIZE}")
    print("=" * 64)

    random.seed(12345)  # để kết quả tái lập được khi cần

    results = []
    results.append(("Không mất gói", test_no_loss()))
    results.append(("Mất DATA", test_data_loss()))
    results.append(("Mất ACK", test_ack_loss()))
    results.append(("Mất DATA + ACK", test_both_loss()))
    results.append(("File lớn + loss", test_large_file()))
    results.append(("File rỗng / nhỏ", test_empty_and_small()))

    print("\n" + "=" * 64)
    print("  TỔNG KẾT")
    print("=" * 64)
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  {status:4} | {name}")

    print("-" * 64)
    if all_pass:
        print("  TẤT CẢ TEST ĐỀU PASS – Bộ truyền tin cậy hoạt động tốt!")
    else:
        print("  CÓ TEST BỊ FAIL – Kiểm tra lại logic Sender/Receiver.")
    print("=" * 64)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
