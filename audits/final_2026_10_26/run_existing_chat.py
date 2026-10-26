"""Run unchanged teammate script and inspect its printed results, not just exit0."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from role4_harness import Lab

begin = time.monotonic()
with Lab() as lab:
    result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "test_chat_routing.py")],
        cwd=lab.path, capture_output=True, text=True, encoding="utf-8", timeout=60)
text = result.stdout + result.stderr
(OUT / "existing_chat.txt").write_text(text, encoding="utf-8")
summaries = re.findall(r"^\s+(PASS|FAIL)\s+\|", text, re.MULTILINE)
data = {"exit_code": result.returncode, "summary_statuses": summaries,
    "seconds": round(time.monotonic() - begin, 3),
    "pass": result.returncode == 0 and summaries == ["PASS"] * 4 and "[FAIL]" not in text}
(OUT / "existing_chat_summary.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
print(json.dumps(data))
raise SystemExit(0 if data["pass"] else 1)
