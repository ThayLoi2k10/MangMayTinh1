"""Package source unchanged plus Role 4 submission artifacts; exclude downloads/venv.

The archive root README is a new package guide, not a modification of shared README.
Hashes and source paths make this distinction reviewable. Output is outside Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ["client.py", "server.py", "protocol.py", "config.py", "client_handshake.py",
              "file_client.py", "file_transfer.py", "udp_streamer.py", "requirements.txt"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "Assignment1_Submission_Candidate_2026-11-05.zip")
    args = parser.parse_args()
    files = {name: ROOT / name for name in PRODUCTION}
    for pattern in ("static/*", "tests/*.py", "test_*.py", "docs/*.md", "submission/assignment1/*", "output/pdf/*.pdf"):
        for path in ROOT.glob(pattern):
            if path.is_file():
                files[path.relative_to(ROOT).as_posix()] = path
    for path in (ROOT / "audits/finalization_2026_11_05").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in (".py", ".json", ".txt", ".md"):
            files[path.relative_to(ROOT).as_posix()] = path
    files["README.md"] = ROOT / "submission/assignment1/README.md"
    files["docs/upstream_README_unchanged.md"] = ROOT / "README.md"
    manifest = {"tested_baseline": "3c4174791a7e796a18e6d57c98c03111359cc1a5",
        "packaged_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "readiness": "submission candidate; unresolved blockers documented; not all tests pass",
        "files": {name: {"source": str(path.relative_to(ROOT)),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in sorted(files.items())}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        for name in PRODUCTION:
            assert hashlib.sha256(archive.read(name)).hexdigest() == manifest["files"][name]["sha256"]
    print(json.dumps({"archive": str(args.output.resolve()), "files": len(files) + 1,
        "bytes": args.output.stat().st_size, "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))

if __name__ == "__main__":
    main()
