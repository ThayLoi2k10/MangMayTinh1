"""24 MiB valid file, unchanged natural production timeout, bounded 180 seconds."""
import hashlib
import json
from pathlib import Path
import sys
import time
from functional_audit import Lab, record, OUT

with Lab() as lab:
    content = bytes(range(256)) * (24 * 1024 * 1024 // 256)
    source = lab.path / "large-24-mib.bin"
    source.write_bytes(content)
    begin = time.monotonic()
    fid = lab.alice.send_file("audit_bob", source)
    samples = []
    next_sample = 0
    while time.monotonic() - begin < 180:
        elapsed = time.monotonic() - begin
        send, receive = record(lab.alice, fid), record(lab.bob, fid)
        if elapsed >= next_sample:
            samples.append({"seconds": round(elapsed, 2), "sender": send, "receiver": receive})
            print(json.dumps(samples[-1]), flush=True)
            next_sample += 10
        if send.get("status") != "sending" and receive.get("status") not in (None, "receiving"):
            break
        time.sleep(.1)
    target = lab.path / "downloads_audit_bob" / source.name
    actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    expected = hashlib.sha256(content).hexdigest()
    result = {"bytes": len(content), "seconds": round(time.monotonic() - begin, 3),
        "natural_timeout": True, "sender": record(lab.alice, fid), "receiver": record(lab.bob, fid),
        "destination_exists": target.exists(), "expected_sha256": expected, "actual_sha256": actual,
        "samples": samples, "pass": actual == expected and record(lab.bob, fid).get("status") == "completed"
        and record(lab.alice, fid).get("status") == "done"}
    label = sys.argv[1] if len(sys.argv) > 1 else "large_file_results"
    (OUT / (label + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
raise SystemExit(0 if result["pass"] else 1)
