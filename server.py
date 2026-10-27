#!/usr/bin/env python3
"""
server.py - Collaboration Server với Chat Routing (Broadcast / Unicast)
"""

import socket
import struct
import threading
import time
import uuid
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
    STATUS_OK,
    STATUS_ERR,
    encode_packet,
    decode_packet,
    recv_tcp_packet,
    dump_json,
    load_json,
)

SERVER_HOST = "0.0.0.0"
TCP_PORT = 9000
UDP_PORT = 9001
AUTH_TIMEOUT = 10.0
PEER_TIMEOUT = 15.0
WATCHDOG_INTERVAL = 3.0


class ServerRegistry:
    # Khởi tạo bảng lưu trữ thông tin peer có khóa đồng bộ đa luồng
    def __init__(self):
        self._lock = threading.Lock()
        self._peers = {}

    # Đăng ký thông tin peer mới và cấp session_id nếu username chưa tồn tại
    def register_peer(self, username: str, tcp_sock, client_ip: str, udp_port: int) -> str:
        with self._lock:
            if username in self._peers:
                return ""
            session_id = str(uuid.uuid4())
            self._peers[username] = {
                "tcp_sock": tcp_sock,
                "client_ip": client_ip,
                "udp_port": udp_port,
                "session_id": session_id,
                "last_seen": time.time(),
                "send_lock": threading.Lock(),
            }
            return session_id

    # Xóa peer khỏi danh bạ khi session_id khớp hoặc ngắt phiên kết nối
    def unregister_peer(self, username: str, session_id: str = "") -> bool:
        with self._lock:
            peer = self._peers.get(username)
            if not peer:
                return False
            if session_id and peer["session_id"] != session_id:
                return False
            del self._peers[username]
            return True
        
    # Cập nhật mốc thời gian sống last_seen dựa theo cặp IP và UDP port gửi tới 
    def touch_peer_by_addr(self, client_ip: str, udp_port: int) -> bool:
        with self._lock:
            for info in self._peers.values():
                if info["client_ip"] == client_ip and info["udp_port"] == udp_port:
                    info["last_seen"] = time.time()
                    return True
            return False
        
    # Lọc và gỡ bỏ các peer không gửi tín hiệu quá thời gian quy định
    def scan_dead_peers(self, timeout_sec: float):
        dead_peers = []
        now = time.time()
        with self._lock:
            for username, info in list(self._peers.items()):
                if now - info["last_seen"] > timeout_sec:
                    dead_peers.append((username, info["tcp_sock"]))
                    del self._peers[username]
        return dead_peers
    
    # Lấy danh sách tóm tắt tất cả người dùng đang trực tuyến
    def get_online_users(self):
        with self._lock:
            return [
                {
                    "username": name,
                    "ip": info["client_ip"],
                    "udp_port": info["udp_port"],
                }
                for name, info in self._peers.items()
            ]
        
    # Lấy danh sách địa chỉ (IP, port) UDP của toàn bộ client đang online
    def get_all_udp_targets(self):
        with self._lock:
            return [(info["client_ip"], info["udp_port"]) for info in self._peers.values()]

    # Lấy thông tin của một peer (client) dựa trên username.
    def get_peer(self, username: str):
        with self._lock:
            return self._peers.get(username)
        
    # Lấy danh sách tất cả peer đang online, trừ một username cụ thể.
    def get_all_peers_except(self, exclude_username: str = ""):
        with self._lock:
            return [
                (name, info)
                for name, info in self._peers.items()
                if name != exclude_username
            ]


class CollaborationServer:
     # Khởi tạo server, registry và socket UDP phục vụ heartbeat/broadcast
    def __init__(self):
        self.registry = ServerRegistry()
        self.user_list_seq = 0
        self.seq_lock = threading.Lock()
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.udp_sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        self.udp_sock.bind((SERVER_HOST, UDP_PORT))
        self.is_running = True

     # Khởi tạo server, registry và socket UDP phục vụ heartbeat/broadcast
    def broadcast_user_list(self, bump_seq: bool = True):
        with self.seq_lock:
            if bump_seq or self.user_list_seq == 0:
                self.user_list_seq = (self.user_list_seq + 1) & 0xFFFF
                if self.user_list_seq == 0:
                    self.user_list_seq = 1
            current_seq = self.user_list_seq

        payload = dump_json({"users": self.registry.get_online_users()})
        wire_data = encode_packet(
            Packet(msg_type=MSG_USER_LIST, status=STATUS_OK, seq_no=current_seq, payload=payload)
        )
        for target in self.registry.get_all_udp_targets():
            try:
                self.udp_sock.sendto(wire_data, target)
            except (ConnectionResetError, OSError):
                pass

    # Lắng nghe các gói UDP heartbeat từ client để duy trì trạng thái online
    def udp_listener_loop(self):
        while self.is_running:
            try:
                data, addr = self.udp_sock.recvfrom(2048)
                packet = decode_packet(data)
                if packet.msg_type == MSG_HEARTBEAT:
                    self.registry.touch_peer_by_addr(addr[0], addr[1])
            except (ConnectionResetError, OSError):
                continue
            except Exception:
                continue

    # Định kỳ quét danh bạ, đóng socket và broadcast cập nhật nếu có peer quá hạn
    def watchdog_loop(self):
        last_sync = time.time()
        while self.is_running:
            time.sleep(WATCHDOG_INTERVAL)
            dead_list = self.registry.scan_dead_peers(PEER_TIMEOUT)
            if dead_list:
                for username, tcp_sock in dead_list:
                    print(f"[-] [WATCHDOG] Ngắt kết nối peer quá hạn: {username}")
                    try:
                        tcp_sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        tcp_sock.close()
                    except OSError:
                        pass
                self.broadcast_user_list(bump_seq=True)
            elif time.time() - last_sync >= 10.0:
                self.broadcast_user_list(bump_seq=False)
                last_sync = time.time()

    # Gửi một packet an toàn tới một peer
    def _send_safely(self, peer_info, packet: Packet) -> bool:
        try:
            with peer_info["send_lock"]:
                peer_info["tcp_sock"].sendall(encode_packet(packet))
            return True
        except (OSError, ConnectionResetError, BrokenPipeError, struct.error):
            return False

    # Xử lý packet kiểu MSG_DATA (tin nhắn chat).
    def handle_msg_data(self, pkt: Packet, sender_username: str):
        """Xử lý MSG_DATA: broadcast hoặc unicast."""
        try:
            body = load_json(pkt.payload)
        except Exception:
            print(f"[!] [{sender_username}] Payload MSG_DATA không hợp lệ")
            return

        mode = body.get("mode", "").lower()
        message = body.get("message", "")

        if not message:
            print(f"[!] [{sender_username}] Tin nhắn rỗng, bỏ qua")
            return

        forward_body = {
            "mode": mode,
            "sender": sender_username,
            "message": message,
        }

        if mode == "unicast":
            recipient = body.get("recipient", "").strip()
            if not recipient:
                print(f"[!] [{sender_username}] Unicast thiếu recipient")
                return
            forward_body["recipient"] = recipient

        # Kiểm tra kích thước payload chuyển tiếp không vượt quá giới hạn 16-bit
        try:
            forward_payload = dump_json(forward_body)
        except Exception:
            return

        if len(forward_payload) > 65535:
            print(f"[!] [{sender_username}] Payload sau đóng gói vượt quá 65535 bytes")
            sender_peer = self.registry.get_peer(sender_username)
            if sender_peer:
                err_pkt = Packet(
                    msg_type=MSG_DATA,
                    status=STATUS_ERR,
                    seq_no=pkt.seq_no,
                    payload=dump_json(
                        {
                            "mode": mode,
                            "error": "payload_too_large",
                            "message": "Nội dung tin nhắn vượt quá kích thước cho phép",
                        }
                    ),
                )
                self._send_safely(sender_peer, err_pkt)
            return

        if mode == "broadcast":
            targets = self.registry.get_all_peers_except(exclude_username=sender_username)
            success_count = 0
            failed_users = []

            for uname, peer_info in targets:
                ok = self._send_safely(
                    peer_info,
                    Packet(
                        msg_type=MSG_DATA,
                        status=STATUS_OK,
                        seq_no=pkt.seq_no,
                        payload=forward_payload,
                    ),
                )
                if ok:
                    success_count += 1
                else:
                    failed_users.append(uname)

            print(
                f"[*] [BROADCAST] {sender_username} → {success_count} clients | msg=\"{message[:40]}\""
            )
            if failed_users:
                print(f"    [!] Gửi thất bại tới: {failed_users}")

        elif mode == "unicast":
            recipient = forward_body["recipient"]
            peer_info = self.registry.get_peer(recipient)

            if peer_info is None:
                print(f"[!] [UNICAST] {sender_username} → {recipient} (offline/không tồn tại)")
                # Gửi thông báo lỗi về cho người gửi
                err_pkt = Packet(
                    msg_type=MSG_DATA,
                    status=STATUS_ERR,
                    payload=dump_json(
                        {
                            "mode": "unicast",
                            "error": "recipient_offline",
                            "recipient": recipient,
                            "message": f"Người dùng '{recipient}' không online",
                        }
                    ),
                )
                sender_peer = self.registry.get_peer(sender_username)
                if sender_peer:
                    self._send_safely(sender_peer, err_pkt)
                return

            ok = self._send_safely(
                peer_info,
                Packet(
                    msg_type=MSG_DATA,
                    status=STATUS_OK,
                    seq_no=pkt.seq_no,
                    payload=forward_payload,
                ),
            )
            if ok:
                print(
                    f"[*] [UNICAST] {sender_username} → {recipient} | msg=\"{message[:40]}\""
                )
            else:
                print(f"[!] [UNICAST] Gửi thất bại tới {recipient}")

        else:
            print(f"[!] [{sender_username}] mode không hợp lệ: {mode}")

    # Xử lý vòng đời phiên TCP của một client từ handshake, auth đến logout
    def handle_client_session(self, conn, addr):
        conn.settimeout(AUTH_TIMEOUT)
        username = None
        session_id = None

        try:
            # 1. Bắt tay ban đầu
            pkt_hello = recv_tcp_packet(conn)
            if pkt_hello.msg_type != MSG_HELLO_REQ:
                return
            conn.sendall(encode_packet(Packet(msg_type=MSG_HELLO_RESP, status=STATUS_OK)))

            # 2. Xác thực tài khoản
            pkt_auth = recv_tcp_packet(conn)
            if pkt_auth.msg_type != MSG_AUTH_REQ:
                return

            body = load_json(pkt_auth.payload)
            if not isinstance(body, dict):
                err_payload = dump_json(
                    {"error_code": "ERR_INVALID_PAYLOAD", "message": "Payload xác thực không hợp lệ"}
                )
                conn.sendall(
                    encode_packet(
                        Packet(msg_type=MSG_AUTH_RESP, status=STATUS_ERR, payload=err_payload)
                    )
                )
                return

            req_username = str(body.get("username", "")).strip()
            raw_port = body.get("udp_port")
            try:
                if isinstance(raw_port, bool) or raw_port is None:
                    raise ValueError("Invalid port type")
                client_udp_port = int(raw_port)
            except (ValueError, TypeError):
                client_udp_port = 0

            if not req_username or not (1 <= client_udp_port <= 65535):
                err_payload = dump_json(
                    {"error_code": "ERR_INVALID_PORT", "message": "Thông số username hoặc udp_port không hợp lệ"}
                )
                conn.sendall(
                    encode_packet(
                        Packet(msg_type=MSG_AUTH_RESP, status=STATUS_ERR, payload=err_payload)
                    )
                )
                return

            session_id = self.registry.register_peer(
                username=req_username,
                tcp_sock=conn,
                client_ip=addr[0],
                udp_port=client_udp_port,
            )

            if not session_id:
                err_payload = dump_json(
                    {"error_code": "ERR_DUP", "message": "Username đã tồn tại"}
                )
                conn.sendall(
                    encode_packet(
                        Packet(
                            msg_type=MSG_AUTH_RESP,
                            status=STATUS_ERR,
                            payload=err_payload,
                        )
                    )
                )
                return

            username = req_username
            ok_payload = dump_json(
                {"session_id": session_id, "message": "Authentication successful"}
            )
            conn.sendall(
                encode_packet(
                    Packet(msg_type=MSG_AUTH_RESP, status=STATUS_OK, payload=ok_payload)
                )
            )
            print(f"[+] User '{username}' online ({addr[0]}:{client_udp_port})")
            self.broadcast_user_list()

            # 3. Duy trì phiên và chờ lệnh điều khiển tiếp theo
            conn.settimeout(None)
            while True:
                pkt = recv_tcp_packet(conn)

                if pkt.msg_type == MSG_LOGOUT_REQ:
                    logout_data = load_json(pkt.payload)
                    if logout_data.get("session_id") == session_id:
                        self.registry.unregister_peer(username, session_id)
                        conn.sendall(
                            encode_packet(
                                Packet(msg_type=MSG_LOGOUT_RESP, status=STATUS_OK)
                            )
                        )
                        try:
                            conn.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        username = None
                        self.broadcast_user_list()
                        break

                elif pkt.msg_type == MSG_DATA:
                    self.handle_msg_data(pkt, username)

                else:
                    print(
                        f"[!] [{username}] Nhận packet không hỗ trợ: 0x{pkt.msg_type:02X}"
                    )

        except (socket.timeout, ConnectionResetError, ValueError, ConnectionError):
            pass
        finally:
            if username:
                if session_id:
                    self.registry.unregister_peer(username, session_id)
                    self.broadcast_user_list()
                else:
                    pass
            try:
                conn.close()
            except OSError:
                pass

    # Khởi chạy các tiến trình nền và mở socket TCP tiếp nhận kết nối mới
    def start(self):
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind((SERVER_HOST, TCP_PORT))
        tcp_server.listen(16)
        print(
            f"[*] Server sẵn sàng: TCP {SERVER_HOST}:{TCP_PORT} | UDP {SERVER_HOST}:{UDP_PORT}"
        )

        threading.Thread(target=self.udp_listener_loop, daemon=True).start()
        threading.Thread(target=self.watchdog_loop, daemon=True).start()

        try:
            while True:
                conn, addr = tcp_server.accept()
                threading.Thread(
                    target=self.handle_client_session, args=(conn, addr), daemon=True
                ).start()
        except KeyboardInterrupt:
            self.is_running = False
            print("\n[*] Server đang tắt...")
        finally:
            tcp_server.close()
            self.udp_sock.close()


if __name__ == "__main__":
    CollaborationServer().start()