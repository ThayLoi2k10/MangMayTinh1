"""Run unchanged integrated Role 4 tests; strict markers are removed in memory.

Run from repository root with .venv/Scripts/python.exe. Results stay in this audit.
Ports 9000/9001 must be free. No production source is modified.
"""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
KNOWN = {
    "test_upstream_final_ack_loss_should_recover",
    "test_upstream_receiver_timeout_should_reach_state",
    "test_existing_heartbeat_script",
}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), "test_role4_*.py")
    tests = list(flatten(suite))
    changed = []
    if args.strict:
        for test in tests:
            if test._testMethodName in KNOWN:
                method = getattr(type(test), test._testMethodName)
                if getattr(method, "__unittest_expecting_failure__", False):
                    method.__unittest_expecting_failure__ = False
                    changed.append(test.id())
    start = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = {
        "baseline": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "label": args.label, "strict": args.strict, "markers_disabled": changed,
        "tests": [t.id() for t in tests], "total": result.testsRun,
        "pass": result.testsRun - sum(map(len, [result.failures, result.errors,
            result.skipped, result.expectedFailures, result.unexpectedSuccesses])),
        "fail": len(result.failures), "error": len(result.errors),
        "skip": len(result.skipped), "expected_failure": len(result.expectedFailures),
        "unexpected_success": len(result.unexpectedSuccesses),
        "duration_seconds": round(time.monotonic() - start, 3),
        "failures": [(t.id(), trace) for t, trace in result.failures],
        "errors": [(t.id(), trace) for t, trace in result.errors],
        "unexpected_successes": [t.id() for t in result.unexpectedSuccesses],
    }
    out = Path(__file__).parent / "regression"
    out.mkdir(exist_ok=True)
    (out / (args.label + ".json")).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
