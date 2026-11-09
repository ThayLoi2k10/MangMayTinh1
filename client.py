from __future__ import annotations

import argparse
import base64
import json
import socket
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import (
    SERVER_HOST,
    TCP_PORT,
    UDP_PORT,
    HEARTBEAT_INTERVAL,
    HANDSHAKE_TIMEOUT,
    SERVER_LIVENESS_TIMEOUT,
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
    validate_username,
)
from file_client import FileTransferHandler
from file_transfer import (
    FileTransferError,
    seal_chat_text,
    open_chat_text,
    safe_filename,
    MAX_FILE_SIZE,
)


class CollaborationClient:
    def __init__(self, username: str, password: str, server_host: str):
        self.username = validate_username(username)
        self.server_host = server_host
        self.users: list = []
        self.messages: list = []
        self.peer_addrs: dict[str, tuple[str, int]] = {}  # username -> (ip, udp_port)
        self.session_id = ""
        self.latest_user_list_seq = 0
        self.stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._closed = False
        self._last_server_seen = 0.0
        self._connection_reason = "Đang đăng nhập"
        self.operations: list[dict] = []
        self._operation_slots = threading.BoundedSemaphore(8)
        self._chat_errors: dict[int, str] = {}
        self._heartbeat_pending: dict[int, float] = {}
        self.tcp = self.udp = None
        self.file_handler = None

        self.tcp_send_lock = threading.Lock()
        self.udp_send_lock = threading.Lock()
        self.seq_lock = threading.Lock()
        self.seq = 1

        try:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                try:
                    self.udp.ioctl(socket.SIO_UDP_CONNRESET, False)
                except OSError:
                    pass
            self.udp.bind(("0.0.0.0", 0))
            self.udp_port = self.udp.getsockname()[1]
            self.udp.settimeout(1.0)
            self.server_udp = (socket.gethostbyname(server_host), UDP_PORT)
            self.tcp = socket.create_connection((server_host, TCP_PORT), timeout=HANDSHAKE_TIMEOUT)
            deadline = time.monotonic() + HANDSHAKE_TIMEOUT
            self._send_tcp(Packet(MSG_HELLO_REQ))
            hello = recv_tcp_packet(self.tcp, deadline=deadline)
            if hello.msg_type != MSG_HELLO_RESP or hello.status != STATUS_OK:
                raise RuntimeError("Server handshake thất bại")
            auth_body = {"username": self.username, "udp_port": self.udp_port}
            if password:
                auth_body["password"] = password
            self._send_tcp(Packet(MSG_AUTH_REQ, payload=dump_json(auth_body)))
            reply = recv_tcp_packet(self.tcp, deadline=deadline)
            detail = load_json(reply.payload)
            if not isinstance(detail, dict):
                raise RuntimeError("Phản hồi xác thực không hợp lệ")
            if reply.msg_type != MSG_AUTH_RESP or reply.status != STATUS_OK:
                raise RuntimeError(detail.get("message", "Xác thực thất bại"))
            self.session_id = detail.get("session_id", "")
            if not isinstance(self.session_id, str) or not self.session_id:
                raise RuntimeError("Server không cấp session_id")
            self.tcp.settimeout(None)
            self.file_handler = FileTransferHandler(
                send_packet_fn=self._send_file_packet, next_seq_fn=self._next_seq,
                download_dir=f"downloads_{self.username}",
            )
            self._mark_server_seen()
        except Exception:
            self._shutdown_resources(False, "Đăng nhập thất bại")
            raise

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
        if self.stop_event.is_set() or self.tcp is None:
            raise ConnectionError("Phiên server đã đóng; khởi động lại client để đăng nhập")
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
        for name, (pip, pport) in list(self.peer_addrs.items()):
            if pip == ip and pport == port:
                return name
        return None

    # ------------------------------------------------------------------
    # Chat (TCP)
    # ------------------------------------------------------------------
    def send_message(self, target: str, text: str) -> int:
        if not isinstance(text, str) or not isinstance(target, str):
            raise ValueError("Tin nhắn và người nhận phải là chuỗi")
        text = text.strip()
        if not text:
            raise ValueError("Tin nhắn không được để trống")
        if target != "*":
            target = validate_username(target)
        
        sealed_message = seal_chat_text(text)
        if target == "*":
            body = {"mode": "broadcast", "message": sealed_message, "enc": True,}
        else:
            body = {"mode": "unicast", "recipient": target, "message": sealed_message, "enc": True,}
        seq = self._next_seq()
        with self._state_lock:
            self._chat_errors.pop(seq, None)
        self._send_tcp(
            Packet(
                MSG_DATA,
                status=STATUS_OK,
                seq_no=seq,
                payload=dump_json(body),
            )
        )
        self._append_message(
            {
                "from": self.username,
                "to": target,
                "text": text,
                "time": time.strftime("%H:%M:%S"),
            }
        )
        return seq

    # ------------------------------------------------------------------
    # File 
    # ------------------------------------------------------------------
    def send_file(self, target: str, path: str | Path) -> str:
        if self.stop_event.is_set():
            raise ConnectionError("Phiên server đã đóng; không thể gửi file")
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
                    self._shutdown_resources(False, "Kết nối TCP với server đã đóng")
                break

            if packet.msg_type != MSG_DATA:
                continue
            try:
                body = load_json(packet.payload)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(body, dict):
                continue
            self._mark_server_seen()

            if packet.status == STATUS_ERR or body.get("error"):
                print(f"[CHAT] {body.get('message', body.get('error'))}")
                error = str(body.get("message", body.get("error", "Server từ chối tin nhắn")))[:1000]
                with self._state_lock:
                    self._chat_errors[packet.seq_no] = error
                    if len(self._chat_errors) > 100:
                        self._chat_errors.pop(next(iter(self._chat_errors)))
                    matched = False
                    for operation in self.operations:
                        if operation.get("seq") == packet.seq_no:
                            operation.update(status="failed", error=error)
                            matched = True
                    if not matched:
                        self.operations.append({"id": uuid.uuid4().hex, "kind": "server", "target": body.get("recipient", "*"), "status": "failed", "error": error})
                        self.operations = self.operations[-100:]
                continue

            sender = body.get("sender", "?")
            message = body.get("message", "")
            if not isinstance(sender, str) or not isinstance(message, str):
                continue
            if body.get("enc") is True and isinstance(message, str):
                try:
                    message = open_chat_text(message)
                except FileTransferError:
                    message = "[Không thể giải mã tin nhắn]"
                    
            self._append_message(
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

            if packet.msg_type == MSG_HEARTBEAT and addr == self.server_udp:
                with self._state_lock:
                    if packet.status == STATUS_OK and self._heartbeat_pending.pop(packet.seq_no, None) is not None:
                        self._mark_server_seen()
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
                duplicate = False
                if self.latest_user_list_seq != 0:
                    diff = (packet.seq_no - self.latest_user_list_seq) & 0xFFFF
                    if packet.seq_no == 0 or diff >= 0x8000:
                        continue
                    duplicate = diff == 0

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
                            and type(port) is int and 1 <= port <= 65535
                        ):
                            addrs[str(name)] = (str(ip), int(port))
                            valid_users.append(u)

                    with self._state_lock:
                        self._mark_server_seen()
                        if not duplicate and not self.stop_event.is_set():
                            self.users = valid_users
                            self.peer_addrs = addrs
                            if packet.seq_no != 0:
                                self.latest_user_list_seq = packet.seq_no
                except Exception:
                    pass
                continue

            if packet.msg_type == MSG_DATA:
                sender = self._username_from_addr(addr) or "?"
                if sender == "?":
                    continue
                if self.file_handler.handle_packet(packet, sender=sender):
                    continue

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_INTERVAL):
            try:
                seq = self._next_seq()
                with self._state_lock:
                    self._heartbeat_pending[seq] = time.monotonic()
                    if len(self._heartbeat_pending) > 4:
                        self._heartbeat_pending.pop(next(iter(self._heartbeat_pending)))
                self._send_udp_to_server(
                    Packet(MSG_HEARTBEAT, status=STATUS_OK, seq_no=seq)
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
    def _mark_server_seen(self):
        with self._state_lock:
            if not self.stop_event.is_set():
                self._last_server_seen = time.monotonic()
                self._connection_reason = "Đã xác thực phiên; có phản hồi server"

    def _append_message(self, message):
        with self._state_lock:
            self.messages.append(message)
            del self.messages[:-100]

    def submit_operation(self, kind, target, function, cleanup=None):
        """Bounded bridge jobs; local submission is distinct from peer delivery."""
        if self.stop_event.is_set():
            raise ConnectionError("Phiên server đã đóng; khởi động lại client")
        if not self._operation_slots.acquire(blocking=False):
            raise RuntimeError("Client đang xử lý quá nhiều yêu cầu; thử lại sau")
        record = {"id": uuid.uuid4().hex, "kind": kind, "target": target, "status": "queued"}
        with self._state_lock:
            self.operations.append(record)
            self.operations = self.operations[-100:]
        def work():
            try:
                result = function()
                with self._state_lock:
                    record["status"] = "submitted"
                    if kind == "file":
                        record["file_id"] = result
                    else:
                        record["seq"] = result
                        if result in self._chat_errors:
                            record.update(status="failed", error=self._chat_errors.pop(result))
            except Exception as exc:
                with self._state_lock:
                    record.update(status="failed", error=str(exc)[:1000])
            finally:
                try:
                    if cleanup:
                        cleanup()
                finally:
                    self._operation_slots.release()
        try:
            threading.Thread(target=work, daemon=True).start()
        except Exception:
            self._operation_slots.release()
            with self._state_lock:
                record.update(status="failed", error="Không tạo được worker")
            raise
        return record["id"]

    def state(self) -> dict:
        with self._state_lock:
            age = max(0.0, time.monotonic() - self._last_server_seen) if self._last_server_seen else None
            status = "disconnected" if self.stop_event.is_set() else "connected" if age is not None and age <= SERVER_LIVENESS_TIMEOUT else "stale"
            return {
                "username": self.username,
                "users": [dict(user) for user in self.users],
                "messages": [dict(message) for message in self.messages[-100:]],
                "transfers": self.file_handler.get_progress()[-50:] if self.file_handler else [],
                "connection": {"status": status, "server": self.server_host, "session_id": self.session_id,
                               "last_response_age_seconds": round(age, 2) if age is not None else None,
                               "reason": self._connection_reason},
                "operations": [dict(operation) for operation in self.operations[-100:]],
            }

    def close(self) -> None:
        self._shutdown_resources(True, "Client đã đóng phiên")

    def _shutdown_resources(self, send_logout, reason):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self.stop_event.set()
        with self._state_lock:
            self._connection_reason = reason
            self.users = []
            self.peer_addrs = {}
        if self.tcp:
            if send_logout and self.session_id and self.tcp_send_lock.acquire(blocking=False):
                try:
                    self.tcp.settimeout(.2)
                    self.tcp.sendall(encode_packet(Packet(MSG_LOGOUT_REQ, payload=dump_json({"session_id": self.session_id}))))
                except OSError:
                    pass
                finally:
                    self.tcp_send_lock.release()
            try:
                self.tcp.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for sock in (self.tcp, self.udp):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        handler_close = getattr(self.file_handler, "close", None)
        if handler_close:
            handler_close()


# ======================================================================
# HTTP UI 
# ======================================================================
class UIHandler(BaseHTTPRequestHandler):
    client_app: CollaborationClient | None = None
    index_file = Path(__file__).with_name("static") / "index.html"

    def local_request(self):
        """Only the local UI origin may use this unauthenticated loopback bridge.

        Requiring a literal loopback Host also prevents a DNS-rebinding origin
        from reading the state API. Native clients may omit Origin, but browser
        POSTs must use the matching origin and the non-simple JSON content type.
        """
        host = self.headers.get("Host", "").lower()
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update(("127.0.0.1", "localhost"))
        origin = self.headers.get("Origin")
        if host not in allowed or (origin is not None and origin.lower() != "http://" + host):
            self.reply(403, '{"ok":false,"error":"Only the local UI origin is allowed"}')
            return False
        return True

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
        self.connection.settimeout(10.0)
        value = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Request phải là JSON object")
        return value

    def do_GET(self):
        if not self.local_request():
            return
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
        if not self.local_request():
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415, '{"ok":false,"error":"Content-Type must be application/json"}')
            return
        try:
            body = self.read_json()
            if self.path == "/api/send":
                target, message = body.get("to", "*"), body.get("text", "")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("Tin nhắn không được để trống")
                if target != "*":
                    target = validate_username(target)
                self.client_app.submit_operation("chat", target,
                    lambda: self.client_app.send_message(target, message))
                self.reply(200, '{"ok":true}')
            elif self.path == "/api/file":
                data = base64.b64decode(body["data"], validate=True)
                if len(data) > MAX_FILE_SIZE:
                    raise ValueError("File vượt giới hạn backend")
                name = safe_filename(body["name"])
                target = body.get("to", "*")
                if not target or target == "*":
                    raise ValueError("Truyền file cần chỉ định người nhận")
                target = validate_username(target)
                # The worker owns an immutable request directory. Public
                # send_file snapshots bytes before returning its transfer id.
                stage = tempfile.TemporaryDirectory(prefix="collaboration-upload-")
                try:
                    path = Path(stage.name) / name
                    path.write_bytes(data)
                    self.client_app.submit_operation("file", target,
                        lambda: self.client_app.send_file(target, path), cleanup=stage.cleanup)
                except Exception:
                    stage.cleanup()
                    raise
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
