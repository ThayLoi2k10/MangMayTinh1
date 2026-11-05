"""Bounded additional checks; only own temporary data, unchanged team tests."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT))
tempfile.tempdir = str(Path(os.environ['LOCALAPPDATA']) / 'Temp')
assert shutil.disk_usage(tempfile.tempdir).free > 160 * 1024**2, 'Need 160 MiB free for isolated 24 MiB case'

def run():
    spec = importlib.util.spec_from_file_location('backend_audit', OUT/'backend/verify_backend.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = {}
    started = time.monotonic()
    try:
        module.large_file(evidence)
        result = {'status': 'PASS'}
    except Exception:
        result = {'status': 'FAIL', 'traceback': traceback.format_exc()}
    result.update(evidence=evidence, seconds=round(time.monotonic()-started,3))
    (OUT/'backend/large_file.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
    command = [sys.executable, '-X', 'utf8', '-m', 'unittest', 'test_file_client', 'test_file_transfer', '-v']
    env = dict(os.environ, TEMP=tempfile.tempdir, TMP=tempfile.tempdir)
    started = time.monotonic()
    with (OUT/'team_file_tests.txt').open('w', encoding='utf-8') as log:
        proc = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    (OUT/'team_file_tests.json').write_text(json.dumps({'command': command, 'exit_code': proc.returncode,
        'seconds': round(time.monotonic()-started,3)}, indent=2), encoding='utf-8')
    print('Team file unit tests exit:', proc.returncode, flush=True)
    return int(result['status'] != 'PASS' or proc.returncode != 0)

if __name__ == '__main__':
    raise SystemExit(run())
