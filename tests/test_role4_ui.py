"""Browser tests for the actual single-file UI. Requires optional Playwright.

Fixture tests exercise rendering/failure boundaries; the last class uses real
server/client/HTTP traffic and verifies a browser-originated file's SHA-256.
"""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest

from playwright.sync_api import expect
from role4_harness import Bridge, Lab, UIHandler, browser, names, wait_for


class StateFixture:
    def __init__(self):
        self.state_gate = None
        self.post_gate = None
        self.calls = 0
        self.value = {
            "username": "alice",
            "users": [
                {"username": "alice", "ip": "127.0.0.1", "udp_port": 9005},
                {"username": "bob", "ip": "127.0.0.1", "udp_port": 9006},
            ],
            "messages": [], "transfers": [],
        }

    def state(self):
        self.calls += 1
        gate = self.state_gate
        if gate is not None:
            gate.wait(timeout=12)
        return copy.deepcopy(self.value)


class FixtureHandler(UIHandler):
    """Only fixture HTTP delays. Real-browser integration uses UIHandler unchanged."""
    def do_POST(self):
        gate = self.client_app.post_gate
        if gate is not None:
            self.read_json()
            gate.wait(timeout=12)
            self.reply(200, '{"ok":true}')
        else:
            super().do_POST()

    def reply(self, *args, **kwargs):
        try:
            super().reply(*args, **kwargs)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Expected: browser AbortController closed the timed-out fixture request.


class Role4BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser_context = browser()
        cls.browser = cls.browser_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.browser_context.__exit__(None, None, None)

    def setUp(self):
        self.fixture = StateFixture()
        self.bridge = Bridge(self.fixture, FixtureHandler)
        self.addCleanup(self.bridge.close)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.bridge.url)
        expect(self.page.locator("#username")).to_have_text("alice")

    def tearDown(self):
        self.assertEqual(self.errors, [], "uncaught JavaScript errors")

    def test_real_schema_polling_selection_and_disappearing_recipient(self):
        page = self.page
        expect(page.locator("#users")).to_contain_text("alice · Bạn")
        expect(page.locator("#users")).to_contain_text("127.0.0.1:9006")
        page.get_by_role("button", name="bob").click()
        page.locator("#draft").fill("keep this draft")
        self.fixture.value["messages"] = [
            {"from": "bob", "to": "alice", "text": "same message", "time": "12:00:00"},
            {"from": "bob", "to": "alice", "text": "same message", "time": "12:00:00"},
        ]
        expect(page.locator(".message")).to_have_count(2)
        page.wait_for_timeout(1200)  # At least one subsequent snapshot: no append-duplication.
        expect(page.locator(".message")).to_have_count(2)
        expect(page.locator("#chat-to")).to_have_value("bob")
        self.fixture.value["users"] = self.fixture.value["users"][:1]
        expect(page.locator("#chat-to")).to_have_value("")
        expect(page.locator("#file-to")).to_have_value("")
        expect(page.locator("#draft")).to_have_value("keep this draft")
        expect(page.locator("#chat-submit")).to_be_disabled()

    def test_injection_and_bounded_history(self):
        attack = '<img src=x onerror="window.pwned=1"><script>window.pwned=1</script>'
        self.fixture.value["username"] = attack
        self.fixture.value["users"].append({"username": attack, "ip": attack, "udp_port": 42})
        self.fixture.value["messages"] = [{"from": attack, "to": attack, "text": attack, "time": attack}] * 130
        self.fixture.value["transfers"] = [{
            "filename": attack, "peer": attack, "direction": "send", "status": attack,
            "progress": 25, "file_id": attack,
        }] * 60
        expect(self.page.locator("#username")).to_have_text(attack)
        expect(self.page.locator(".message")).to_have_count(100)
        expect(self.page.locator(".transfer")).to_have_count(40)
        self.assertEqual(self.page.locator("img").count(), 0)
        self.assertIsNone(self.page.evaluate("window.pwned"))
        expect(self.page.locator(".transfer-name").first).to_have_text(attack)

    def test_malformed_missing_collections_and_progress(self):
        self.fixture.value.update(users=[None, "bob", {}, {"username": 42}], messages=None, transfers="bad")
        expect(self.page.locator("#user-count")).to_have_text("0")
        expect(self.page.locator("#messages")).to_contain_text("Chưa có tin nhắn")
        self.fixture.value["transfers"] = [
            {"filename": "bad", "progress": "100", "status": None},
            {"filename": "high", "progress": 140, "status": "sending"},
            {"filename": "low", "progress": -20, "status": "receiving"},
        ]
        expect(self.page.locator(".transfer")).to_have_count(3)
        self.assertIsNone(self.page.locator("progress").nth(0).get_attribute("value"))
        expect(self.page.locator("progress").nth(1)).to_have_attribute("value", "100")
        expect(self.page.locator("progress").nth(1).locator("..")).to_contain_text("Đang gửi")
        expect(self.page.locator("progress").nth(2)).to_have_attribute("value", "0")
        self.fixture.value = {"username": "alice"}
        expect(self.page.locator(".transfer")).to_have_count(0)
        self.fixture.value = {}
        expect(self.page.locator("#api-status")).to_contain_text("Dữ liệu phiên không hợp lệ", timeout=10000)
        expect(self.page.locator("#chat-submit")).to_be_disabled()

    def test_drafts_enter_shift_enter_and_honest_submission(self):
        page = self.page
        submissions = []

        def accept(route):
            submissions.append(route.request.post_data_json)
            route.fulfill(json={"ok": True})
        page.route("**/api/send", accept)
        page.locator("#draft").fill("   ")
        expect(page.locator("#chat-submit")).to_be_disabled()
        page.locator("#draft").fill("hello")
        page.locator("#draft").press("Shift+Enter")
        expect(page.locator("#draft")).to_have_value("hello\n")
        page.locator("#draft").press("Enter")
        expect(page.locator("#chat-feedback")).to_contain_text("chưa xác nhận")
        self.assertEqual(submissions, [{"to": "*", "text": "hello\n"}])
        expect(page.locator("#draft")).to_have_value("")
        page.unroute("**/api/send")
        attack = "<script>window.pwned=1</script>"
        page.route("**/api/send", lambda route: route.fulfill(status=400, json={"error": attack}))
        page.locator("#chat-to").select_option("bob")
        page.locator("#draft").fill("private draft")
        page.locator("#chat-submit").click()
        expect(page.locator("#chat-feedback")).to_contain_text(attack)
        expect(page.locator("#draft")).to_have_value("private draft")
        self.assertIsNone(page.evaluate("window.pwned"))

    def test_request_timeouts_recovery_and_no_overlapping_poll(self):
        page = self.page
        state_gate = threading.Event()
        self.addCleanup(state_gate.set)
        before_calls = self.fixture.calls
        self.fixture.state_gate = state_gate
        expect(page.locator("#api-status")).to_contain_text("hết thời gian chờ", timeout=12000)
        self.assertEqual(self.fixture.calls - before_calls, 1)
        expect(page.locator("#snapshot-time")).to_contain_text("có thể đã cũ")
        expect(page.locator("#chat-submit")).to_be_disabled()
        self.fixture.state_gate = None
        state_gate.set()
        expect(page.locator("#api-status")).to_contain_text("hoạt động", timeout=10000)
        expect(page.locator("#server-status")).to_contain_text("chưa xác minh")
        post_gate = threading.Event()
        self.addCleanup(post_gate.set)
        self.fixture.post_gate = post_gate
        page.locator("#draft").fill("timeout draft")
        page.locator("#chat-submit").click()
        expect(page.locator("#chat-submit")).to_be_disabled()
        expect(page.locator("#chat-feedback")).to_contain_text("hết thời gian chờ", timeout=12000)
        expect(page.locator("#draft")).to_have_value("timeout draft")
        post_gate.set()

    def test_file_validation_submission_and_backend_status_transitions(self):
        page = self.page
        expect(page.locator("#file-submit")).to_be_disabled()
        page.locator("#file-input").set_input_files({"name": "ghi chú.txt", "mimeType": "text/plain", "buffer": b"hello"})
        expect(page.locator("#file-submit")).to_be_disabled()
        page.locator("#file-to").select_option("bob")
        submissions = []
        page.route("**/api/file", lambda route: (submissions.append(route.request.post_data_json), route.fulfill(json={"ok": True})))
        page.locator("#file-submit").click()
        expect(page.locator("#file-feedback")).to_contain_text("chờ trạng thái")
        self.assertEqual(submissions, [{"to": "bob", "name": "ghi chú.txt", "data": "aGVsbG8="}])
        expect(page.locator(".transfer")).to_have_count(0)  # HTTP ok alone cannot complete a transfer.
        record = {"filename": "ghi chú.txt", "peer": "bob", "file_id": "abc", "direction": "send", "status": "sending", "progress": 31}
        self.fixture.value["transfers"] = [record]
        expect(page.locator("progress")).to_have_attribute("value", "31")
        record.update(status="failed: Timeout ACK", progress=31)
        expect(page.locator(".transfer")).to_contain_text("failed: Timeout ACK")
        record.update(status="done", progress=100)
        expect(page.locator(".transfer")).to_contain_text("Bên gửi báo xong")
        record.update(direction="receive", status="completed")
        expect(page.locator(".transfer")).to_contain_text("Bên nhận đã hoàn tất")
        # Sparse file exercises File.size validation without transferring 83 MiB.
        with tempfile.TemporaryDirectory(prefix="role4-ui-file-") as directory:
            oversized = Path(directory) / "too-large.bin"
            with oversized.open("wb") as stream:
                stream.truncate(83 * 1024 * 1024)
            page.locator("#file-input").set_input_files(oversized)
            page.locator("#file-submit").click()
            expect(page.locator("#file-feedback")).to_contain_text("quá lớn")
        self.assertEqual(len(submissions), 1)
        page.locator("#file-input").set_input_files({"name": "bad?.txt", "mimeType": "text/plain", "buffer": b""})
        page.locator("#file-submit").click()
        expect(page.locator("#file-feedback")).to_contain_text("Tên file không hợp lệ")
        page.unroute("**/api/file")
        page.route("**/api/file", lambda route: route.abort())
        page.locator("#file-input").set_input_files({"name": "empty.txt", "mimeType": "text/plain", "buffer": b""})
        page.locator("#file-submit").click()
        expect(page.locator("#file-feedback")).to_contain_text("được giữ lại")
        self.assertEqual(page.locator("#file-input").evaluate("(el) => el.files[0].name"), "empty.txt")

    def test_mobile_layout_keyboard_and_snapshot_bounds(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.locator("#chat-to").focus()
        page.keyboard.press("Tab")
        expect(page.locator("#draft")).to_be_focused()
        expect(page.locator("#draft")).to_have_accessible_name("Nội dung")
        expect(page.locator("#file-input")).to_have_accessible_name("Chọn file từ máy này")


class Role4RealBrowserIntegration(unittest.TestCase):
    def test_two_browser_clients_chat_file_progress_hash_and_disconnect(self):
        with Lab() as lab, browser() as instance:
            alice, bob = lab.client("alice"), lab.client("bob")
            wait_for(lambda: names(alice) == names(bob) == {"alice", "bob"})
            a, b = lab.bridge(alice), lab.bridge(bob)
            context = instance.new_context()
            try:
                page_a, page_b = context.new_page(), context.new_page()
                page_a.goto(a.url)
                page_b.goto(b.url)
                expect(page_a.locator("#users")).to_contain_text("bob")
                page_a.locator("#draft").fill("browser broadcast")
                page_a.locator("#draft").press("Enter")
                expect(page_b.locator("#messages")).to_contain_text("browser broadcast")
                page_b.locator("#chat-to").select_option("alice")
                page_b.locator("#draft").fill("browser private")
                page_b.locator("#chat-submit").click()
                expect(page_a.locator("#messages")).to_contain_text("browser private")
                content = bytes(range(256)) * 4096  # 1 MiB, enough for real intermediate progress.
                page_a.locator("#file-to").select_option("bob")
                page_a.locator("#file-input").set_input_files({"name": "browser tiếng Việt.bin", "mimeType": "application/octet-stream", "buffer": content})
                page_a.locator("#file-submit").click()
                page_a.wait_for_function("Array.from(document.querySelectorAll('progress')).some(p => p.value > 0 && p.value < 100)", timeout=30000)
                expect(page_b.locator("#transfers")).to_contain_text("Bên nhận đã hoàn tất", timeout=120000)
                expect(page_a.locator("#transfers")).to_contain_text("Bên gửi báo xong", timeout=15000)
                target = lab.path / "downloads_bob" / "browser tiếng Việt.bin"
                self.assertEqual(hashlib.sha256(target.read_bytes()).digest(), hashlib.sha256(content).digest())
                output = Path(os.environ.get("ROLE4_SCREENSHOTS", str(Path(__file__).resolve().parents[1] / "test-results")))
                output.mkdir(parents=True, exist_ok=True)
                page_a.screenshot(path=str(output / "role4-desktop.png"), full_page=True)
                page_a.set_viewport_size({"width": 390, "height": 844})
                page_a.screenshot(path=str(output / "role4-mobile.png"), full_page=True)
                lab.stop_server()
                wait_for(lambda: alice.stop_event.is_set())
                expect(page_a.locator("#api-status")).to_contain_text("hoạt động")
                expect(page_a.locator("#server-status")).to_contain_text("chưa xác minh")
                a.close()
                lab.bridges.remove(a)
                expect(page_a.locator("#api-status")).to_contain_text("mất kết nối", timeout=12000)
                expect(page_a.locator("#chat-submit")).to_be_disabled()
                page_a.locator("#draft").fill("UI remains responsive offline")
                expect(page_a.locator("#draft")).to_have_value("UI remains responsive offline")
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
