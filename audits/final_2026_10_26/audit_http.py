"""Bounded functional HTTP audit with real unchanged clients/UDP/file receiver.

The first worker is gated at the public send_file boundary, representing a legal
thread schedule. This exposes whether upload staging preserves each request's
bytes. No malformed packets, production edits, or third-party traffic are used.
"""
import base64
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from role4_harness import Lab, api, names, wait_for, browser
from file_transfer import decode_secure_json, FILE_CHUNK

EVIDENCE = []
sha = lambda data: hashlib.sha256(data).hexdigest()


class HTTPAudit(unittest.TestCase):
    def test_final_ack_recovery_and_receiver_timeout_reach_http_and_browser(self):
        with Lab() as lab:
            alice, bob = lab.client("alice"), lab.client("bob")
            wait_for(lambda: names(alice) == names(bob) == {"alice", "bob"})
            sender, receiver = lab.bridge(alice), lab.bridge(bob)
            original_ack = bob.file_handler.send_packet_fn
            dropped = []

            def lose_one_ack(packet, recipient):
                body = decode_secure_json(packet.payload)
                if body.get("kind") == "ACK" and body.get("chunk_index") == 0 and not dropped:
                    dropped.append(True)
                    return
                original_ack(packet, recipient)

            bob.file_handler.send_packet_fn = lose_one_ack
            content = b"final ACK audit\n"
            source = lab.path / "ack.txt"
            source.write_bytes(content)
            fid = alice.send_file("bob", source)
            def rec(url, file_id):
                return next((r for r in api(url)["transfers"] if r["file_id"] == file_id), {})
            wait_for(lambda: rec(sender.url, fid).get("status") == "done")
            wait_for(lambda: rec(receiver.url, fid).get("status") == "completed")
            self.assertEqual(dropped, [True])
            self.assertEqual((lab.path / "downloads_bob" / "ack.txt").read_bytes(), content)
            bob.file_handler.send_packet_fn = original_ack
            original_send = alice.file_handler.send_packet_fn
            def lose_all_chunks(packet, recipient):
                if decode_secure_json(packet.payload).get("kind") != FILE_CHUNK:
                    original_send(packet, recipient)
            alice.file_handler.send_packet_fn = lose_all_chunks
            source = lab.path / "timeout.bin"
            source.write_bytes(b"timeout" * 200)
            timeout_id = alice.send_file("bob", source)
            wait_for(lambda: bool(rec(receiver.url, timeout_id)))
            wait_for(lambda: rec(sender.url, timeout_id).get("status", "").startswith("failed"), timeout=15)
            expired = bob.file_handler.receiver.cleanup_expired(max_age=0)
            self.assertIn(timeout_id, expired)
            self.assertEqual(rec(receiver.url, timeout_id)["status"], "timeout")
            with browser() as instance:
                page = instance.new_page()
                page.goto(receiver.url)
                from playwright.sync_api import expect
                expect(page.locator("#transfers")).to_contain_text("Hết thời gian chờ")
                expect(page.locator("#transfers")).to_contain_text("timeout.bin")
                visible = page.locator("#transfers").inner_text()
                page.close()
            EVIDENCE.append({"case": self._testMethodName, "dropped_final_ack": len(dropped),
                "ack_sender_http": rec(sender.url, fid), "ack_receiver_http": rec(receiver.url, fid),
                "timeout_sender_http": rec(sender.url, timeout_id), "timeout_receiver_http": rec(receiver.url, timeout_id),
                "timeout_browser_text": visible, "expiry": "cleanup_expired(max_age=0), accelerated clock boundary; not 120-second natural expiry"})

    def test_concurrent_uploads_same_name_preserve_each_request_bytes(self):
        with Lab() as lab:
            alice, bob, cara = [lab.client(name) for name in ("alice", "bob", "cara")]
            wait_for(lambda: names(alice) == names(bob) == names(cara) == {"alice", "bob", "cara"})
            bridge = lab.bridge(alice)
            entered, release = threading.Event(), threading.Event()
            original = alice.send_file

            def gated(target, path):
                if target == "bob":
                    entered.set()
                    if not release.wait(10):
                        raise AssertionError("audit gate timed out")
                return original(target, path)

            alice.send_file = gated
            first, second = b"first user's document\n" * 100, b"second user's document\n" * 100
            try:
                one = api(bridge.url, "/api/file", {"to": "bob", "name": "shared.txt", "data": base64.b64encode(first).decode()})
                self.assertTrue(entered.wait(3))
                two = api(bridge.url, "/api/file", {"to": "cara", "name": "shared.txt", "data": base64.b64encode(second).decode()})
                wait_for(lambda: bool(cara.state()["transfers"]) and cara.state()["transfers"][0]["status"] == "completed")
                release.set()
                wait_for(lambda: bool(bob.state()["transfers"]) and bob.state()["transfers"][0]["status"] == "completed")
                got_first = (lab.path / "downloads_bob" / "shared.txt").read_bytes()
                got_second = (lab.path / "downloads_cara" / "shared.txt").read_bytes()
                EVIDENCE.append({"case": self._testMethodName, "http": [one, two],
                    "expected_first_sha256": sha(first), "actual_first_sha256": sha(got_first),
                    "expected_second_sha256": sha(second), "actual_second_sha256": sha(got_second),
                    "sender": api(bridge.url)["transfers"], "receiver_bob": bob.state()["transfers"],
                    "receiver_cara": cara.state()["transfers"], "schedule": "hold first public send_file until second upload completes"})
                self.assertEqual(sha(got_second), sha(second))
                self.assertEqual(sha(got_first), sha(first), "HTTP staging overwrote the first upload before its worker read it")
            finally:
                release.set()
                alice.send_file = original

    def test_eight_mib_valid_file_integrity_and_http_terminal_state(self):
        with Lab() as lab:
            alice, bob = lab.client("alice"), lab.client("bob")
            wait_for(lambda: names(alice) == names(bob) == {"alice", "bob"})
            sender, receiver = lab.bridge(alice), lab.bridge(bob)
            content = bytes(range(256)) * (8 * 1024 * 1024 // 256)
            start = time.monotonic()
            response = api(sender.url, "/api/file", {"to": "bob", "name": "eight-mib.bin", "data": base64.b64encode(content).decode()})
            observed = set()

            def complete():
                records = api(receiver.url)["transfers"]
                observed.update(r["progress"] for r in records)
                return records and records[0]["status"] == "completed"

            wait_for(complete, timeout=180, description="8 MiB receiver completion")
            wait_for(lambda: api(sender.url)["transfers"][0]["status"] == "done")
            actual = (lab.path / "downloads_bob" / "eight-mib.bin").read_bytes()
            EVIDENCE.append({"case": self._testMethodName, "bytes": len(content), "http": response,
                "seconds": round(time.monotonic() - start, 3), "expected_sha256": sha(content),
                "actual_sha256": sha(actual), "observed_receiver_progress": sorted(observed),
                "sender": api(sender.url)["transfers"], "receiver": api(receiver.url)["transfers"]})
            self.assertEqual(sha(actual), sha(content))
            self.assertTrue(any(0 < percent < 100 for percent in observed))


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "http_1"
    start = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HTTPAudit))
    out = Path(__file__).parent / "http"
    out.mkdir(exist_ok=True)
    data = {"baseline": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "total": result.testsRun, "pass": result.testsRun - len(result.failures) - len(result.errors),
        "fail": len(result.failures), "error": len(result.errors), "duration_seconds": round(time.monotonic() - start, 3),
        "failures": [(t.id(), trace) for t, trace in result.failures], "errors": [(t.id(), trace) for t, trace in result.errors],
        "evidence": EVIDENCE}
    (out / (label + ".json")).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0 if result.wasSuccessful() else 1)
