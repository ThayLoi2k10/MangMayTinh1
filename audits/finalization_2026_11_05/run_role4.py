"""Run owned tests against this checkout; preserve exact results and tracebacks."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), "test_role4_*.py")
    tests = list(flatten(suite))
    disabled = []
    if args.strict:
        for test in tests:
            method = getattr(type(test), test._testMethodName)
            if getattr(method, "__unittest_expecting_failure__", False):
                disabled.append(test.id())
                method.__unittest_expecting_failure__ = False
    start = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = {"baseline": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "strict": args.strict, "disabled_markers": disabled, "tests": [t.id() for t in tests],
        "total": result.testsRun, "pass": result.testsRun - sum(map(len,
            [result.failures, result.errors, result.skipped, result.expectedFailures, result.unexpectedSuccesses])),
        "fail": len(result.failures), "error": len(result.errors), "skip": len(result.skipped),
        "expected_failure": len(result.expectedFailures), "unexpected_success": len(result.unexpectedSuccesses),
        "duration_seconds": round(time.monotonic() - start, 3),
        "failures": [(t.id(), trace) for t, trace in result.failures],
        "errors": [(t.id(), trace) for t, trace in result.errors]}
    (Path(__file__).parent / (args.label + ".json")).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
