"""End-to-end HTTP ownership regression: each accepted request retains its bytes."""
import base64
import hashlib
import threading
import unittest
from role4_harness import Lab, api, names, wait_for


class Role4DeliveryTests(unittest.TestCase):
    def test_same_filename_uploads_preserve_request_content(self):
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
                        raise RuntimeError("test worker schedule gate expired")
                return original(target, path)
            alice.send_file = gated
            first, second = b"document for Bob", b"different document for Cara"
            try:
                for recipient, content in (("bob", first), ("cara", second)):
                    self.assertEqual(api(bridge.url, "/api/file", {"to": recipient, "name": "shared.txt",
                        "data": base64.b64encode(content).decode()}), {"ok": True})
                    if recipient == "bob":
                        self.assertTrue(entered.wait(3))
                wait_for(lambda: cara.state()["transfers"] and cara.state()["transfers"][0]["status"] == "completed")
                release.set()
                wait_for(lambda: bob.state()["transfers"] and bob.state()["transfers"][0]["status"] == "completed")
                for recipient, content in (("bob", first), ("cara", second)):
                    with self.subTest(recipient=recipient):
                        received = (lab.path / ("downloads_" + recipient) / "shared.txt").read_bytes()
                        self.assertEqual(hashlib.sha256(received).hexdigest(), hashlib.sha256(content).hexdigest(),
                            "HTTP staging must preserve the bytes from each request")
            finally:
                release.set()
                alice.send_file = original
