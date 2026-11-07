"""Build the reviewed release with exact hashes; no venv, downloads or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ['client.py', 'server.py', 'protocol.py', 'config.py', 'client_handshake.py',
              'file_client.py', 'file_transfer.py', 'udp_streamer.py', 'stream_transport.py']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT.parent/'Assignment1_Release_2026-11-07.zip')
    args = parser.parse_args()
    files = {name: ROOT/name for name in PRODUCTION}
    for pattern in ('requirements*.txt', 'README.md', 'static/*', 'tests/*.py', 'test_*.py',
                    'scripts/*.py', 'docs/*.md', 'submission/assignment1/*.py',
                    'submission/assignment1/README.md', 'output/pdf/*.pdf'):
        for path in ROOT.glob(pattern):
            if path.is_file():
                files[path.relative_to(ROOT).as_posix()] = path
    # Historical audit sources/evidence remain clearly dated, so links in the
    # historical reports stay usable and the before/after claims are reviewable.
    for directory in ('final_2026_10_26','finalization_2026_11_05'):
        for path in (ROOT/'audits'/directory).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.md','.txt','.json','.xml') and '__pycache__' not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path
    for path in (ROOT/'audits/release_2026_11_07').rglob('*'):
        if (path.is_file() and path.suffix in ('.json','.txt','.md','.xml')
                and path.name != 'package_build.json'):
            files[path.relative_to(ROOT).as_posix()] = path
    report = ROOT/'output/pdf/Assignment1_Release_Report.pdf'
    assert report.exists(), 'Build and visually review the PDF before packaging'
    manifest = {
        'integrated_team_baseline': '3c4174791a7e796a18e6d57c98c03111359cc1a5',
        'packaged_head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'working_tree_diff': subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True),
        'assessment': 'See docs/release_closure.md for evidence, scope and remaining uncertainties',
        'files': {name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                  for name,path in sorted(files.items())},
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()):
            archive.write(path,name)
        archive.writestr('MANIFEST.json',json.dumps(manifest,indent=2,ensure_ascii=False))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        for name,detail in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==detail['sha256'],name
    print(json.dumps({'archive':str(args.output.resolve()),'files':len(files)+1,
                      'bytes':args.output.stat().st_size,
                      'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()},indent=2))

if __name__=='__main__':
    main()
