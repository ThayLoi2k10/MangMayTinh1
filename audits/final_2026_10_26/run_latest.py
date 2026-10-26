"""Revalidate the new upstream commit discovered at audit close-out."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
jobs = [
    ("http_latest", [str(OUT / "audit_http.py"), "http_latest"]),
    ("strict_latest_1", [str(OUT / "run_regression.py"), "--strict", "--label", "strict_latest_1"]),
    ("strict_latest_2", [str(OUT / "run_regression.py"), "--strict", "--label", "strict_latest_2"]),
    ("original_latest", [str(OUT / "run_regression.py"), "--label", "original_latest"]),
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
    (OUT / "execution_latest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results[-1]), flush=True)
