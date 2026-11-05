"""Run the original 24 MiB audit separately with a bounded C: temp directory."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import traceback

import verify_backend as audit

temp_root = Path(os.environ["LOCALAPPDATA"]) / "Temp"
tempfile.tempdir = str(temp_root)
result = {"name": "24_mib_natural", "temp_root": str(temp_root),
          "free_bytes_before": shutil.disk_usage(temp_root).free,
          "evidence": {}, "baseline": "3c4174791a7e796a18e6d57c98c03111359cc1a5"}
started = time.monotonic()
try:
    if result["free_bytes_before"] < 128 * 1024 * 1024:
        raise OSError("Insufficient free space for isolated 24 MiB source and destination")
    audit.large_file(result["evidence"])
    result["status"] = "PASS"
except Exception:
    result.update(status="FAIL", traceback=traceback.format_exc())
result.update(seconds=round(time.monotonic()-started, 3),
              free_bytes_after=shutil.disk_usage(temp_root).free)
(audit.OUT / "large_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result), flush=True)
raise SystemExit(result["status"] != "PASS")
