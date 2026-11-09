"""Serialize real-port test suites and preserve failures without masking them."""
import json
from pathlib import Path
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
jobs = [
    ("final_1", [str(OUT / "run_role4.py"), "--label", "final_1"]),
    ("final_2", [str(OUT / "run_role4.py"), "--label", "final_2"]),
    ("demo_smoke", [str(ROOT / "submission/assignment1/demo.py"), "--smoke", "--output", str(OUT / "demo_smoke.json")]),
]
summary = []
for label, arguments in jobs:
    command = [sys.executable, "-X", "utf8", *arguments]
    begin = time.monotonic()
    with (OUT / (label + ".txt")).open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=450)
    summary.append({"label": label, "command": command, "exit_code": result.returncode,
                    "seconds": round(time.monotonic() - begin, 3)})
    (OUT / "execution.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary[-1]), flush=True)
raise SystemExit(int(any(job["exit_code"] != 0 for job in summary)))
