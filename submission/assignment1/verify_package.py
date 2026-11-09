"""Validate an archive manifest and run real demo from its isolated extraction."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive_path, output = args.archive.resolve(), args.output.resolve()
    temp_root = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir()))
    if os.name == 'nt':
        temp_root /= 'Temp'
    assert shutil.disk_usage(temp_root).free > 40*1024**2
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='a1-package-', dir=temp_root) as folder:
        destination = Path(folder).resolve()
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None
            for member in archive.infolist():
                assert (destination/member.filename).resolve().is_relative_to(destination), 'unsafe archive path'
            manifest = json.loads(archive.read('MANIFEST.json'))
            for name, info in manifest['files'].items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == info['sha256'], name
            archive.extractall(destination)
        command = [sys.executable, '-X', 'utf8', str(destination/'submission/assignment1/demo.py'),
                   '--smoke', '--output', str(destination/'package-smoke.json')]
        env = dict(os.environ, TEMP=str(temp_root), TMP=str(temp_root))
        result = subprocess.run(command, cwd=destination, env=env, text=True, encoding='utf-8',
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        smoke = json.loads((destination/'package-smoke.json').read_text(encoding='utf-8'))
        evidence = {'status': 'PASS' if result.returncode == 0 and smoke['status'] == 'PASS' else 'FAIL',
            'archive': str(archive_path), 'archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            'manifest_files_verified': len(manifest['files']), 'packaged_head': manifest['packaged_head'],
            'command': command, 'exit_code': result.returncode, 'smoke': smoke,
            'stdout': result.stdout, 'seconds': round(time.monotonic()-started,3)}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False),encoding='utf-8')
        assert evidence['status'] == 'PASS', result.stdout
        print(json.dumps({k:v for k,v in evidence.items() if k not in ('smoke','stdout','command')},indent=2))

if __name__ == '__main__':
    main()
