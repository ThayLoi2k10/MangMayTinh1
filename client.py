from __future__ import annotations

import argparse
import base64
import json
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import (
    SERVER_HOST,
    TCP_PORT,
    UDP_PORT,
    HEARTBEAT_INTERVAL,
)
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
from file_client import FileTransferHandler
from file_transfer import FileTransferError


class CollaborationClient:
    def __init__(self, username: str, password: str, server_host: str):
        self.username = username
        self.server_host = server_host
        self.users: list = []
        self.messages: list = []
        self.peer_addrs: dict[str, tuple[str, int]] = {}  # username -> (ip, udp_port)
        self.session_id = ""
        self.latest_user_list_seq = 0
        self.stop_event = threading.Event()

        self.tcp_send_lock = threading.Lock()
        self.udp_send_lock = threading.Lock()
        self.seq_lock = threading.Lock()
        self.seq = 1

        # UDP socket (file + heartbeat + user list)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.udp.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        self.udp.bind(("0.0.0.0", 0))
        self.udp_port = self.udp.getsockname()[1]
        self.udp.settimeout(1.0)
        self.server_udp = (server_host, UDP_PORT)

        # File handler (UDP reliable)
        self.file_handler = FileTransferHandler(
            send_packet_fn=self._send_file_packet,
            next_seq_fn=self._next_seq,
            download_dir=f"downloads_{username}" # Tránh ghi đè file
        )

        # TCP: handshake + auth
        self.tcp = socket.create_connection((server_host, TCP_PORT), timeout=5)
        self.tcp.settimeout(None)

        self._send_tcp(Packet(MSG_HELLO_REQ))
        hello = recv_tcp_packet(self.tcp)
        if hello.msg_type != MSG_HELLO_RESP or hello.status != STATUS_OK:
            self.close()
            raise RuntimeError("Server handshake thất bại")

        auth_body = {"username": username, "udp_port": self.udp_port}
        if password:
            auth_body["password"] = password
        self._send_tcp(Packet(MSG_AUTH_REQ, payload=dump_json(auth_body)))
        reply = recv_tcp_packet(self.tcp)
        if reply.msg_type != MSG_AUTH_RESP or reply.status != STATUS_OK:
            detail = load_json(reply.payload) if reply.payload else {}
            self.close()
            raise RuntimeError(detail.get("message", "Xác thực thất bại"))

        try:
            self.session_id = load_json(reply.payload).get("session_id", "")
        except Exception:
            self.session_id = ""

        threading.Thread(target=self._tcp_receive_loop, daemon=True).start()
        threading.Thread(target=self._udp_receive_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._file_cleanup_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Sequence / send helpers
    # ------------------------------------------------------------------
    def _next_seq(self) -> int:
        with self.seq_lock:
            n = self.seq
            self.seq = (self.seq + 1) & 0xFFFF
            return n

    def _send_tcp(self, packet: Packet) -> None:
        raw = encode_packet(packet)
        with self.tcp_send_lock:
            self.tcp.sendall(raw)

    def _send_udp_to_server(self, packet: Packet) -> None:
        with self.udp_send_lock:
            try:
                self.udp.sendto(encode_packet(packet), self.server_udp)
            except (ConnectionResetError, OSError):
                pass

    def _send_file_packet(self, packet: Packet, recipient: str) -> None:
        """Gửi packet file UDP P2P tới peer."""
        if self.stop_event.is_set():
            raise RuntimeError("Client đang đóng, không thể gửi file.")

        addr = self.peer_addrs.get(recipient)
        if not addr:
            raise RuntimeError(
                f"Chưa có địa chỉ UDP của '{recipient}'. "
                "Đợi user list (cả hai client phải online)."
            )

        with self.udp_send_lock:
            # Kiểm tra lại sau khi lấy lock để tránh race với close().
            if self.stop_event.is_set():
                raise RuntimeError("Client đang đóng, không thể gửi file.")

            self.udp.sendto(encode_packet(packet), addr)

    def _username_from_addr(self, addr) -> str | None:
        ip, port = addr[0], addr[1]
        for name, (pip, pport) in self.peer_addrs.items():
            if pip == ip and pport == port:
                return name
        return None

    # ------------------------------------------------------------------
    # Chat (TCP)
    # ------------------------------------------------------------------
    def send_message(self, target: str, text: str) -> None:
        text = str(text).strip()
        if not text:
            raise ValueError("Tin nhắn không được để trống")
        if target == "*":
            body = {"mode": "broadcast", "message": text}
        else:
            body = {"mode": "unicast", "recipient": target, "message": text}
        self._send_tcp(
            Packet(
                MSG_DATA,
                status=STATUS_OK,
                seq_no=self._next_seq(),
                payload=dump_json(body),
            )
        )
        self.messages.append(
            {
                "from": self.username,
                "to": target,
                "text": text,
                "time": time.strftime("%H:%M:%S"),
            }
        )

    # ------------------------------------------------------------------
    # File 
    # ------------------------------------------------------------------
    def send_file(self, target: str, path: str | Path) -> str:
        if target == "*":
            others = [name for name in self.peer_addrs if name != self.username]
            if not others:
                raise RuntimeError("Không có peer online để gửi file broadcast.")
            return self.file_handler.send_file(
                path, recipient="*", all_recipients=others
            )

        if not target:
            raise FileTransferError("Thiếu người nhận")
        if target not in self.peer_addrs:
            raise RuntimeError(
                f"'{target}' chưa có trong user list / chưa online. "
                "Gõ /users rồi thử lại."
            )
        return self.file_handler.send_file(path, recipient=target)

    # ------------------------------------------------------------------
    # Receive loops
    # ------------------------------------------------------------------
    def _tcp_receive_loop(self) -> None:
        """Chỉ xử lý chat / lỗi unicast (không còn file trên TCP)"""
        while not self.stop_event.is_set():
            try:
                packet = recv_tcp_packet(self.tcp)
            except (OSError, ConnectionError, ValueError) as exc:
                if not self.stop_event.is_set():
                    print(f"[TCP] Kết nối đã đóng: {exc}")
                    self.stop_event.set()
                break

            if packet.msg_type != MSG_DATA:
                continue
            try:
                body = load_json(packet.payload)
            except (ValueError, UnicodeDecodeError):
                continue

            if body.get("mode") == "unicast" and body.get("error"):
                print(f"[CHAT] {body.get('message', body.get('error'))}")
                continue

            sender = body.get("sender", "?")
            message = body.get("message", "")
            self.messages.append(
                {
                    "from": sender,
                    "to": body.get("recipient", "*"),
                    "text": message,
                    "time": time.strftime("%H:%M:%S"),
                }
            )

    def _udp_receive_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                raw, addr = self.udp.recvfrom(65535)
                packet = decode_packet(raw)
            except socket.timeout:
                continue
            except (ConnectionResetError, OSError, ValueError):
                if self.stop_event.is_set():
                    break
                continue
            except Exception:
                if self.stop_event.is_set():
                    break
                continue

            if packet.msg_type == MSG_USER_LIST:
                # D04: verify source is from server
                try:
                    server_ip = socket.gethostbyname(self.server_udp[0])
                except OSError:
                    server_ip = self.server_udp[0]

                if addr[1] != self.server_udp[1]:
                    continue
                if addr[0] != server_ip and addr[0] != self.server_udp[0]:
                    is_local = (addr[0] in ("127.0.0.1", "::1", "localhost") and server_ip in ("127.0.0.1", "::1", "localhost"))
                    if not is_local:
                        continue

                # D05: sequence number checking for out-of-order/replayed snapshots
                if self.latest_user_list_seq != 0 and packet.seq_no != 0:
                    diff = (packet.seq_no - self.latest_user_list_seq) & 0xFFFF
                    if diff == 0 or diff >= 0x8000:
                        continue

                try:
                    payload_data = load_json(packet.payload)
                    if not isinstance(payload_data, dict):
                        continue
                    users = payload_data.get("users")
                    if not isinstance(users, list):
                        continue

                    addrs: dict[str, tuple[str, int]] = {}
                    valid_users = []
                    for u in users:
                        if not isinstance(u, dict):
                            continue
                        name = u.get("username")
                        ip = u.get("ip")
                        port = u.get("udp_port")
                        if (
                            name and isinstance(name, str)
                            and ip and isinstance(ip, str)
                            and port is not None and isinstance(port, int) and 1 <= port <= 65535
                        ):
                            addrs[str(name)] = (str(ip), int(port))
                            valid_users.append(u)

                    self.users = valid_users
                    self.peer_addrs = addrs
                    if packet.seq_no != 0:
                        self.latest_user_list_seq = packet.seq_no
                except Exception:
                    pass
                continue

            if packet.msg_type == MSG_DATA:
                sender = self._username_from_addr(addr) or "?"
                if self.file_handler.handle_packet(packet, sender=sender):
                    continue

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_INTERVAL):
            try:
                self._send_udp_to_server(
                    Packet(MSG_HEARTBEAT, status=STATUS_OK, seq_no=self._next_seq())
                )
            except (ConnectionResetError, OSError):
                if self.stop_event.is_set():
                    break
                continue

    def _file_cleanup_loop(self) -> None:
        while not self.stop_event.wait(30):
            self.file_handler.cleanup()

    # ------------------------------------------------------------------
    # State / close
    # ------------------------------------------------------------------
    def state(self) -> dict:
        return {
            "username": self.username,
            "users": self.users,
            "messages": self.messages[-100:],
            "transfers": self.file_handler.get_progress()[-50:],
        }

    def close(self) -> None:
        self.stop_event.set()

        try:
            if hasattr(self, "tcp") and self.tcp:
                payload = dump_json({"session_id": self.session_id})
                self._send_tcp(Packet(MSG_LOGOUT_REQ, payload=payload))
        except Exception:
            pass

        sock = getattr(self, "tcp", None)
        if sock:
            try:
                sock.close()
            except OSError:
                pass

        with self.udp_send_lock:
            sock = getattr(self, "udp", None)
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass


# ======================================================================
# HTTP UI 
# ======================================================================
class UIHandler(BaseHTTPRequestHandler):
    client_app: CollaborationClient | None = None
    index_file = Path(__file__).with_name("static") / "index.html"

    def reply(self, code, data, ctype="application/json; charset=utf-8"):
        raw = data if isinstance(data, bytes) else data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 110 * 1024 * 1024:
            raise ValueError("Request quá lớn")
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        if self.path == "/":
            if not self.index_file.is_file():
                self.reply(
                    404,
                    "Không tìm thấy static/index.html",
                    "text/plain; charset=utf-8",
                )
            else:
                self.reply(
                    200,
                    self.index_file.read_bytes(),
                    "text/html; charset=utf-8",
                )
        elif self.path == "/api/state":
            assert self.client_app is not None
            self.reply(
                200,
                json.dumps(self.client_app.state(), ensure_ascii=False),
            )
        else:
            self.reply(404, "{}")

    def do_POST(self):
        assert self.client_app is not None
        try:
            body = self.read_json()
            if self.path == "/api/send":
                threading.Thread(
                    target=self.client_app.send_message,
                    args=(body.get("to", "*"), body.get("text", "")),
                    daemon=True,
                ).start()
                self.reply(200, '{"ok":true}')
            elif self.path == "/api/file":
                data = base64.b64decode(body["data"], validate=True)
                name = body["name"]
                target = body.get("to", "*")
                if not target or target == "*":
                    raise ValueError("Truyền file cần chỉ định người nhận")
                temp = Path(".upload_temp")
                temp.mkdir(exist_ok=True)
                path = temp / Path(name).name
                path.write_bytes(data)
                threading.Thread(
                    target=self.client_app.send_file,
                    args=(target, path),
                    daemon=True,
                ).start()
                self.reply(200, '{"ok":true}')
            else:
                self.reply(404, "{}")
        except Exception as exc:
            self.reply(
                400,
                json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            )

    def log_message(self, fmt, *args):
        pass


# ======================================================================
# CLI
# ======================================================================
def run_cli(app: CollaborationClient) -> None:
    import shlex

    print("\nChế độ CLI — lệnh:")
    print("  /help")
    print("  /users")
    print('  /send <username> "<duong_dan_file>"')
    print("  /status")
    print("  /quit")
    print("  Nội dung khác → broadcast chat\n")

    while not app.stop_event.is_set():
        try:
            line = input(f"{app.username}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/help":
            print('Ví dụ: /send bob "C:/Users/Asus/Documents/test.pdf"')
            continue
        if line == "/users":
            print("Users:", app.users)
            print("UDP peers:", app.peer_addrs)
            continue
        if line == "/status":
            items = app.file_handler.get_progress()
            if not items:
                print("Chưa có giao dịch file.")
            for item in items[-20:]:
                print(item)
            continue
        if line.startswith("/send "):
            try:
                parts = shlex.split(line, posix=False)
                if len(parts) < 3:
                    raise ValueError('Cú pháp: /send <username> "<path>"')
                target = parts[1]
                file_path = " ".join(parts[2:]).strip()
                if (
                    len(file_path) >= 2
                    and file_path[0] == file_path[-1]
                    and file_path[0] in "\"'"
                ):
                    file_path = file_path[1:-1]
                print(f"[FILE] Gửi {file_path} → {target} ...")
                app.send_file(target, file_path)
                print("[FILE] Worker đã chạy; xem /status hoặc log phía nhận.")
            except Exception as exc:
                print(f"[FILE] Lỗi: {exc}")
            continue
        try:
            app.send_message("*", line)
            print("[CHAT] Đã gửi broadcast.")
        except Exception as exc:
            print(f"[CHAT] Lỗi: {exc}")


def main():
    parser = argparse.ArgumentParser(
        description="Client collaboration (TCP chat + UDP reliable file)"
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default="")
    parser.add_argument("--host", "--server", dest="server", default=SERVER_HOST)
    parser.add_argument("--ui-port", type=int, default=8000)
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Chạy terminal, không mở web UI",
    )
    args = parser.parse_args()

    app = CollaborationClient(args.username, args.password, args.server)
    print(f"Đăng nhập: {args.username}")
    print(f"UDP local port: {app.udp_port}")

    try:
        if args.cli:
            run_cli(app)
        else:
            UIHandler.client_app = app
            ui = ThreadingHTTPServer(("127.0.0.1", args.ui_port), UIHandler)
            url = f"http://127.0.0.1:{args.ui_port}"
            print(f"Web UI: {url}")
            try:
                webbrowser.open(url)
                ui.serve_forever()
            finally:
                ui.server_close()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()


if __name__ == "__main__":
    main()
