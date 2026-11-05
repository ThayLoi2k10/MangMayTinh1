"""Independent bounded, valid-traffic integration probes; no production edits.

Run with the repository's cryptography-enabled Python. Own ports: 19000/19001.
All application output/downloads go to a disposable temporary directory.
"""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[3]
OUT = SCRIPT.parent
sys.path.insert(0, str(ROOT))
import config
os.environ["PYTHONIOENCODING"] = "utf-8"
config.TCP_PORT = 19000
config.UDP_PORT = 19001
config.SERVER_BIND_HOST = "127.0.0.1"
from protocol import *


def wait(predicate, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("condition not reached within %.1fs" % seconds)


@contextmanager
def temp_cwd():
    old = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="a1-review-") as tmp:
        try:
            os.chdir(tmp)
            yield tmp
        finally:
            os.chdir(old)


class RawPeer:
    def __init__(self, name):
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.tcp = socket.create_connection(("127.0.0.1", 19000), timeout=3)
        wire = encode_packet(Packet(MSG_HELLO_REQ))
        self.tcp.sendall(wire[:3])
        self.tcp.sendall(wire[3:])
        assert recv_tcp_packet(self.tcp).status == STATUS_OK
        self.send(MSG_AUTH_REQ, {"username": name, "udp_port": self.udp.getsockname()[1]})
        reply = recv_tcp_packet(self.tcp)
        assert reply.status == STATUS_OK, repr(reply)

    def send(self, kind, body):
        self.tcp.sendall(encode_packet(Packet(kind, payload=dump_json(body))))

    def close(self):
        self.tcp.close()
        self.udp.close()


def worker():
    import server
    server.CollaborationServer().start()


def silent_client():
    import client
    client.TCP_PORT = int(sys.argv[2])
    client.CollaborationClient("silent_probe", "", "127.0.0.1")


def main():
    import client
    from file_transfer import open_chat_text, seal_chat_text
    for kind, port in ((socket.SOCK_STREAM, 19000), (socket.SOCK_DGRAM, 19001)):
        with socket.socket(socket.AF_INET, kind) as probe:
            probe.bind(('127.0.0.1', port))
    records = []
    peers = []
    def record(name, fn):
        start = time.monotonic()
        try:
            detail = fn()
            row = {"name": name, "status": "PASS", "detail": detail}
        except Exception:
            row = {"name": name, "status": "FAIL", "traceback": traceback.format_exc()}
        row["seconds"] = round(time.monotonic() - start, 3)
        records.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)

    with temp_cwd() as tmp:
        with open(OUT / "server.log", "w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(SCRIPT), "server"], stdout=log, stderr=log)
            def ready():
                if process.poll() is not None:
                    raise RuntimeError("owned server failed; inspect server.log, possible port conflict")
                try:
                    with socket.create_connection(("127.0.0.1", 19000), timeout=.2):
                        return True
                except OSError:
                    return False
            try:
                wait(ready)
                alice = client.CollaborationClient("review_alice", "", "127.0.0.1")
                bob = client.CollaborationClient("review_bob", "", "127.0.0.1")
                raw = RawPeer("review_raw")
                peers.extend([alice, bob, raw])
                def encrypted_roundtrip():
                    wait(lambda: "review_raw" in alice.peer_addrs and "review_alice" in bob.peer_addrs)
                    text = "fresh review encrypted chat: Unicode tiếng Việt"
                    alice.send_message("review_raw", text)
                    packet = recv_tcp_packet(raw.tcp)
                    body = load_json(packet.payload)
                    assert body["enc"] is True
                    assert text.encode() not in packet.payload
                    assert open_chat_text(body["message"]) == text
                    raw.send(MSG_DATA, {"mode": "unicast", "recipient": "review_alice", "message": seal_chat_text(text + " reply"), "enc": True})
                    wait(lambda: any(x.get("text") == text + " reply" for x in alice.state()["messages"]))
                    alice.send_message("*", text + " broadcast")
                    wait(lambda: any(x.get("text") == text + " broadcast" for x in bob.state()["messages"]))
                    recv_tcp_packet(raw.tcp)  # Drain this broadcast before the next test.
                    return {"actual_wire_enc": True, "plaintext_absent": True, "decrypted_equal": True, "broadcast_and_private": True, "fragmented_hello": True}
                record("encrypted_chat_fragmented_handshake_and_discovery", encrypted_roundtrip)

                def upper_bound():
                    body = {"mode": "unicast", "recipient": "review_alice", "message": ""}
                    overhead = len(dump_json(body))
                    body["message"] = "x" * (65535 - overhead)
                    assert len(dump_json(body)) == 65535
                    raw.send(MSG_DATA, body)
                    response = recv_tcp_packet(raw.tcp)
                    assert response.status == STATUS_ERR, repr(response)
                    error = load_json(response.payload)
                    assert error.get("error") == "payload_too_large", error
                    raw.send(MSG_DATA, {"mode": "unicast", "recipient": "review_alice", "message": "valid_after_max_frame"})
                    wait(lambda: any(x.get("text") == "valid_after_max_frame" for x in alice.state()["messages"]))
                    return {"request_payload_bytes": 65535, "error": error, "same_session_survives": True, "legacy_plaintext_accepted": True}
                record("legal_maximum_frame_graceful_forward_overflow", upper_bound)

                def reserved_name():
                    star = RawPeer("*")
                    peers.append(star)
                    wait(lambda: "*" in alice.peer_addrs)
                    marker = "intended_private_to_username_star"
                    alice.send_message("*", marker)
                    star_body = load_json(recv_tcp_packet(star.tcp).payload)
                    assert open_chat_text(star_body["message"]) == marker
                    wait(lambda: any(x.get("text") == marker for x in bob.state()["messages"]))
                    assert not any(x.get("text") == marker for x in bob.state()["messages"]), "Server accepts username '*', but existing client/API reserves '*' for broadcast: unrelated bob receives intended private message."
                record("accepted_identity_has_unambiguous_private_address", reserved_name)
            finally:
                for peer in reversed(peers):
                    peer.close()
                process.terminate()
                process.wait(timeout=5)

        def bounded_handshake():
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(3)
            child = subprocess.Popen([sys.executable, str(SCRIPT), "silent-client", str(listener.getsockname()[1])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            conn = None
            try:
                conn, _ = listener.accept()
                conn.settimeout(2)
                assert conn.recv(100), "client never initiated handshake"
                try:
                    child.wait(timeout=6)
                    exited = True
                except subprocess.TimeoutExpired:
                    exited = False
                assert exited, "Client constructor remains blocked >6s after accepted TCP connection and unanswered HELLO; configured create_connection timeout does not bound handshake reads."
                return {"exited_without_response": True}
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
                if conn:
                    conn.close()
                listener.close()
        record("client_handshake_has_response_deadline", bounded_handshake)
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "python": sys.version, "platform": sys.platform, "results": records}
    (OUT / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(x["status"] != "PASS" for x in records))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        worker()
    elif len(sys.argv) > 1 and sys.argv[1] == "silent-client":
        silent_client()
    else:
        raise SystemExit(main())
