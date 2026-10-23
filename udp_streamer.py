import threading
import socket
import time
from typing import Tuple, Dict, Optional, List
from protocol import (
    Packet,
    MSG_HELLO_REQ,
    MSG_HELLO_RESP,
    MSG_AUTH_REQ,
    MSG_AUTH_RESP,
    MSG_LOGOUT_REQ,
    MSG_LOGOUT_RESP,
    MSG_HEARTBEAT,
    MSG_USER_LIST,
    MSG_DATA,
    MSG_ACK,
    STATUS_OK,
    STATUS_ERR,
    encode_packet,
    decode_packet,
    recv_tcp_packet,
    dump_json,
    load_json,
)

CHUNK_SIZE = 700
WINDOW_SIZE = 8
RETRY_TIMEOUT = 0.5
MAX_RETRIES = 5

END_FLAG = b"__END__"

class UDPStreamSender:
    def __init__(self, sock: socket.socket, receiver_addr: Tuple[str, int]):
        self.sock = sock
        self.receiver_addr = receiver_addr

        # Trạng thái cửa sổ
        self.base: int = 0              # seq nhỏ nhất chưa được ACK
        self.next_seq: int = 0          # seq sẽ gửi tiếp theo
        self.window: Dict[int, dict] = {}  # seq → {data, send_time, retries}

        self.is_finished = False
        self.success = False
        self._stop = False

        self.stats = {
            "sent": 0,
            "retransmitted": 0,
            "acked": 0,
            "timeouts": 0,
        }
        self._lock = threading.Lock()
        self._ack_event = threading.Event()

    def send_data(self, data: bytes, timeout: float = 30.0) -> bool:
        """
        Gửi toàn bộ dữ liệu một cách tin cậy.
        Trả về True nếu gửi thành công, False nếu thất bại (timeout / quá số lần retry).
        """
        if not data:
            return True

        # Chia thành các chunk
        chunks = self._split_chunks(data)
        total_chunks = len(chunks)

        # Reset trạng thái
        with self._lock:
            self.base = 0
            self.next_seq = 0
            self.window.clear()
            self.is_finished = False
            self.success = False
            self._stop = False
            self.stats = {"sent": 0, "retransmitted": 0, "acked": 0, "timeouts": 0}

        # Thread nhận ACK chạy song song
        ack_thread = threading.Thread(target=self._ack_listener, daemon=True)
        ack_thread.start()

        start_time = time.time()

        try:
            while not self._stop:
                # Hết thời gian tổng?
                if time.time() - start_time > timeout:
                    self._stop = True
                    break

                with self._lock:
                    # ----- 1. Gửi các gói mới nếu cửa sổ còn chỗ -----
                    while (
                        self.next_seq < total_chunks
                        and self.next_seq < self.base + WINDOW_SIZE
                    ):
                        chunk = chunks[self.next_seq]
                        self._send_chunk(self.next_seq, chunk, is_retry=False)
                        self.next_seq += 1

                    # ----- 2. Kiểm tra timeout & gửi lại -----
                    now = time.time()
                    to_retry: List[int] = []
                    failed = False

                    for seq, info in list(self.window.items()):
                        if now - info["send_time"] >= RETRY_TIMEOUT:
                            if info["retries"] < MAX_RETRIES:
                                to_retry.append(seq)
                            else:
                                # Quá số lần retry → thất bại
                                failed = True
                                break

                    if failed:
                        self._stop = True
                        self.success = False
                        break

                    for seq in to_retry:
                        info = self.window[seq]
                        self._send_chunk(seq, info["data"], is_retry=True)
                        self.stats["timeouts"] += 1

                    # ----- 3. Đã gửi hết chunk dữ liệu và cửa sổ trống? -----
                    if self.next_seq >= total_chunks and len(self.window) == 0:
                        # Gửi gói END
                        self._send_end(total_chunks)
                        self.is_finished = True
                        self.success = True
                        self._stop = True
                        break

                # Nhường CPU một chút, đồng thời chờ ACK
                self._ack_event.wait(timeout=0.05)
                self._ack_event.clear()

        finally:
            self._stop = True
            # Đợi thread ACK kết thúc
            ack_thread.join(timeout=1.0)

        return self.success

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self.stats)

    # ------------------------------------------------------------------
    # Nội bộ – gửi
    # ------------------------------------------------------------------
    def _split_chunks(self, data: bytes) -> List[bytes]:
        """Chia dữ liệu thành các chunk kích thước CHUNK_SIZE."""
        chunks = []
        for i in range(0, len(data), CHUNK_SIZE):
            chunks.append(data[i : i + CHUNK_SIZE])
        return chunks

    def _send_chunk(self, seq: int, chunk: bytes, is_retry: bool = False):
        """Gửi một chunk DATA và cập nhật window."""
        pkt = Packet(
            msg_type=MSG_DATA,
            status=STATUS_OK,
            seq_no=seq,
            payload=chunk,
        )
        try:
            self.sock.sendto(encode_packet(pkt), self.receiver_addr)
        except OSError:
            return

        now = time.time()
        if seq in self.window:
            # Gửi lại
            self.window[seq]["send_time"] = now
            self.window[seq]["retries"] += 1
            self.stats["retransmitted"] += 1
        else:
            # Gửi lần đầu
            self.window[seq] = {
                "data": chunk,
                "send_time": now,
                "retries": 0,
            }
            self.stats["sent"] += 1

    def _send_end(self, total_chunks: int):
        """Gửi gói báo kết thúc. seq_no = total_chunks, payload = END_FLAG."""
        pkt = Packet(
            msg_type=MSG_DATA,
            status=STATUS_OK,
            seq_no=total_chunks,
            payload=END_FLAG,
        )
        # Gửi vài lần để tăng độ tin cậy (END cũng có thể mất)
        for _ in range(3):
            try:
                self.sock.sendto(encode_packet(pkt), self.receiver_addr)
            except OSError:
                pass
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Nội bộ – nhận ACK
    # ------------------------------------------------------------------
    def _ack_listener(self):
        """Thread chạy nền: nhận ACK và trượt cửa sổ."""
        self.sock.settimeout(0.2)
        while not self._stop:
            try:
                raw, _ = self.sock.recvfrom(2048)
                packet = decode_packet(raw)
                if packet.msg_type == MSG_ACK:
                    self._handle_ack(packet.seq_no)
            except socket.timeout:
                continue
            except (ValueError, OSError, ConnectionError):
                if self._stop:
                    break
                continue

    def _handle_ack(self, seq: int):
        """Xử lý một ACK: xóa khỏi window và trượt base."""
        with self._lock:
            if seq in self.window:
                del self.window[seq]
                self.stats["acked"] += 1

            # Trượt cửa sổ: base tiến tới seq nhỏ nhất chưa ACK
            while self.base not in self.window and self.base < self.next_seq:
                self.base += 1

            # Đánh thức vòng lặp chính
            self._ack_event.set()


class UDPStreamReceiver:
    def __init__(self, sock):
        self.sock = sock
        self.buffer: Dict[int, bytes] = {}
        self.expected_seq = 0
        self.received_data = bytearray()
        self.total_chunks: Optional[int] = None
        self.is_finished = False
        self.sender_addr: Optional[Tuple[str, int]] =None
        self.stats = {
            "received": 0,
            "duplicate": 0,
            "out_of_order": 0,
            "acked": 0,
        }
        self._lock = threading.Lock()


    def _send_ack(self, seq_no: int, addr: Tuple[str, int]):
        ack_packet = Packet(
            msg_type = MSG_ACK,
            status=STATUS_OK,
            seq_no=seq_no,
            payload=b"",
        )
        try:
            self.sock.sendto(encode_packet(ack_packet), addr)
        except OSError:
            pass

    def _try_assemble(self):
        # Ghép các chunk liên tục từ expected_seq, nếu đã biết total_chunks và đã nhận đủ thì đánh dấu hoàn thành
        while self.expected_seq in self.buffer:
            data = self.buffer.pop(self.expected_seq)
            self.received_data.extend(data)
            self.expected_seq +=1

        if self.total_chunks is not None:
            if self.expected_seq >= self.total_chunks:
                self.is_finished = True
                # Dọn buffer còn thừa (nếu có)
                self.buffer.clear()

    def handle_raw(self, raw_data: bytes, sender_addr: Tuple[str, int]) -> bool:
        try:
            packet= decode_packet(raw_data)

        except(ValueError, Exception):
            return False
        return self.handle_packet(packet, sender_addr)

    def handle_packet(self, packet: Packet, sender_addr: Tuple[str, int]) -> bool:
        if packet.msg_type != MSG_DATA:
            return False

        with self._lock:
            if self.is_finished:
                self._send_ack(packet.seq_no, sender_addr)
                return True

            self.sender_addr = sender_addr
            seq = packet.seq_no
            payload = packet.payload

            self.stats["received"] +=1

            # 1. Luôn gửi ACK ngay (kể cả gói trùng hoặc sai thứ tự)
            self._send_ack(seq, sender_addr)
            self.stats["acked"] +=1

            # 2. Xử lý gói kết thúc (END)
            if payload == END_FLAG:
                if self.total_chunks is None:
                    self.total_chunks = seq
                self._try_assemble()
                return self.is_finished

             # 3. Phát hiện gói trùng
            if seq < self.expected_seq or seq in self.buffer:
                self.stats["duplicate"] += 1
                return False

             # 4. Gói mới, đưa vào buffer
            if seq > self.expected_seq:
                self.stats["out_of_order"] += 1

            self.buffer[seq] = payload

            # 5. Ghép các gói liên tục từ expected_seq
            self._try_assemble()

            return self.is_finished

    def get_data(self) -> bytes:
        with self._lock:
            return bytes(self.received_data)

    def is_complete(self) -> bool:
        with self._lock:
            return self.is_finished

    def reset(self):
        """Reset trạng thái để nhận transfer mới."""
        with self._lock:
            self.expected_seq = 0
            self.buffer.clear()
            self.received_data = bytearray()
            self.total_chunks = None
            self.is_finished = False
            self.sender_addr = None
            self.stats = {
                "received": 0,
                "duplicate": 0,
                "out_of_order": 0,
                "acked": 0,
            }

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self.stats)

def create_udp_socket(bind_port: int = 0) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", bind_port))
    return sock