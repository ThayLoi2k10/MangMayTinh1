"""Serialize labs and preserve exact child exit codes/UTF-8 logs on Windows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
jobs = [
    ("http_1", [str(OUT / "audit_http.py"), "http_1"]),
    ("http_2", [str(OUT / "audit_http.py"), "http_2"]),
    ("strict_2", [str(OUT / "run_regression.py"), "--strict", "--label", "strict_2"]),
    ("original", [str(OUT / "run_regression.py"), "--label", "original"]),
]
results = []
for name, arguments in jobs:
    command = [sys.executable, "-X", "utf8", *arguments]
    start = time.monotonic()
    with (OUT / (name + ".log")).open("w", encoding="utf-8") as log:
        child = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=600)
    results.append({"name": name, "command": command, "exit_code": child.returncode,
        "wall_seconds": round(time.monotonic() - start, 3)})
    (OUT / "execution_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results[-1]), flush=True)
