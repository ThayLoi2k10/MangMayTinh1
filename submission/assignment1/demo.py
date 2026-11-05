"""Role 4 demo: existing server and two client.main HTTP runtimes, isolated data.

Run from any directory with the project Python. Enter closes only this demo's
processes. --smoke performs actual chat/file/hash verification and exits.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from role4_harness import Lab, api, wait_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    start = time.monotonic()
    evidence = {"mode": "real client.main + HTTP + TCP/UDP", "status": "running"}
    try:
        with Lab() as lab:
            alice = lab.client_runtime("demo-alice")
            bob = lab.client_runtime("demo-bob")
            wait_for(lambda: len(api(alice)["users"]) == len(api(bob)["users"]) == 2)
            print(f"Alice: {alice}\nBob: {bob}\nDemo downloads: {lab.path}")
            if not args.smoke:
                webbrowser.open(alice)
                webbrowser.open(bob)
                input("Press Enter to stop this demo. Copy any wanted downloads first. ")
            else:
                api(alice, "/api/send", {"to": "*", "text": "demo broadcast"})
                api(bob, "/api/send", {"to": "demo-alice", "text": "demo private"})
                wait_for(lambda: any(m["text"] == "demo broadcast" for m in api(bob)["messages"]))
                wait_for(lambda: any(m["text"] == "demo private" for m in api(alice)["messages"]))
                content = bytes(range(256)) * 32
                api(alice, "/api/file", {"to": "demo-bob", "name": "demo.bin",
                    "data": base64.b64encode(content).decode("ascii")})
                wait_for(lambda: api(bob)["transfers"] and api(bob)["transfers"][0]["status"] == "completed")
                wait_for(lambda: api(alice)["transfers"] and api(alice)["transfers"][0]["status"] == "done")
                got = (lab.path / "downloads_demo-bob" / "demo.bin").read_bytes()
                assert hashlib.sha256(got).digest() == hashlib.sha256(content).digest()
                evidence.update(alice=api(alice), bob=api(bob), sha256=hashlib.sha256(got).hexdigest(), bytes=len(got))
        evidence["status"] = "PASS"
    except Exception as error:
        evidence.update(status="FAIL", error=repr(error))
        raise
    finally:
        evidence["seconds"] = round(time.monotonic() - start, 3)
        if args.output:
            args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
            args.output.resolve().write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(evidence, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
