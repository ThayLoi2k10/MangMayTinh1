"""Role 4 test infrastructure only. Imports the team's runtime unchanged.

Tests are serial: the production server uses fixed ports 9000/9001, and client
downloads are relative to cwd. Refuse occupied ports; use a temporary cwd.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

# Production modules print Vietnamese/file names from background threads.
# Make captured Windows test output deterministic without changing those modules.
for output in (sys.stdout, sys.stderr):
    if hasattr(output, "reconfigure"):
        output.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client import CollaborationClient, UIHandler
from http.server import ThreadingHTTPServer


def wait_for(predicate, timeout=10, description="condition"):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, ValueError) as error:
            last_error = error
        time.sleep(0.05)
    raise AssertionError(f"Timed out after {timeout}s: {description}; last error={last_error}")


def api(url, path="/api/state", body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def names(app):
    return {user["username"] for user in app.state()["users"]}


class Bridge:
    def __init__(self, app, handler_base=UIHandler):
        # Bind per-server subclass; do not overwrite the shared handler attribute.
        handler = type("Role4TestUIHandler", (handler_base,), {"client_app": app})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class Lab:
    def __enter__(self):
        # Never connect tests to or terminate a user's already running server.
        for socktype, port in ((socket.SOCK_STREAM, 9000), (socket.SOCK_DGRAM, 9001)):
            with socket.socket(socket.AF_INET, socktype) as probe:
                try:
                    probe.bind(("0.0.0.0", port))
                except OSError as error:
                    raise RuntimeError(f"Port {port} is occupied. Stop your demo before running tests.") from error
        self.temp = tempfile.TemporaryDirectory(prefix="role4-")
        self.path = Path(self.temp.name)
        self.previous_cwd = Path.cwd()
        self.clients = []
        self.bridges = []
        self.children = []
        self.log = (self.path / "server.log").open("w", encoding="utf-8")
        os.chdir(self.path)
        try:
            self.start_server()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def start_server(self):
        self.server = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "server.py")],
            cwd=self.path, stdout=self.log, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

        def ready():
            if self.server.poll() is not None:
                raise RuntimeError("Test server exited before listening")
            with socket.create_connection(("127.0.0.1", 9000), timeout=0.2):
                return True
        wait_for(ready, description="server TCP listener")

    def stop_server(self):
        if self.server.poll() is None:
            self.server.terminate()
            self.server.wait(timeout=5)

    def client(self, username):
        app = CollaborationClient(username, "", "127.0.0.1")
        self.clients.append(app)
        return app

    def bridge(self, app):
        bridge = Bridge(app)
        self.bridges.append(bridge)
        return bridge

    def crashable_client(self, username):
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--child", username],
            cwd=self.path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.children.append(process)
        return process

    def client_runtime(self, username):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--runtime", username, str(port)],
            cwd=self.path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.children.append(process)
        url = f"http://127.0.0.1:{port}"

        def ready():
            if process.poll() is not None:
                raise RuntimeError("Existing client.main exited before its HTTP listener started")
            return api(url).get("username") == username
        wait_for(ready, description="existing client.main HTTP runtime")
        return url

    def __exit__(self, *_):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        for bridge in reversed(self.bridges):
            bridge.close()
        for app in self.clients:
            app.close()
        if hasattr(self, "server"):
            self.stop_server()
        self.log.close()
        os.chdir(self.previous_cwd)
        # Let the existing daemon receive loops notice socket closure.
        time.sleep(1.1)
        self.temp.cleanup()


@contextlib.contextmanager
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        # Use a system browser when installed, otherwise Playwright Chromium.
        channel = os.environ.get("ROLE4_BROWSER_CHANNEL")
        if not channel and sys.platform == "win32":
            channel = "msedge"
        instance = playwright.chromium.launch(headless=True, channel=channel)
        try:
            yield instance
        finally:
            instance.close()


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--child":
    child_app = CollaborationClient(sys.argv[2], "", "127.0.0.1")
    try:
        while not child_app.stop_event.wait(1):
            pass
    finally:
        child_app.close()

if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--runtime":
    from unittest.mock import patch
    from client import main
    runtime_username, runtime_port = sys.argv[2:]
    sys.argv = ["client.py", "--username", runtime_username, "--host", "127.0.0.1", "--ui-port", runtime_port]
    # Suppress only opening a visible system browser; run the existing CLI entrypoint.
    with patch("webbrowser.open", return_value=True):
        main()
