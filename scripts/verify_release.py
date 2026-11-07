"""Run the entire owned suite plus team file tests; preserve every outcome.

No xfail/skip is accepted as a successful release. Legacy scripts are exercised
by the integration suite; standalone UDP script is a separate explicit check.
"""
from pathlib import Path
import argparse
import json
import hashlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def source_hashes():
    paths = set(ROOT.glob('*.py')) | set((ROOT/'tests').glob('*.py')) | set((ROOT/'static').glob('*'))
    paths |= set(ROOT.glob('requirements*.txt'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'audits/release_2026_11_07')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    xml = (args.output/f'{args.label}.xml').resolve()
    command = [sys.executable, '-X', 'utf8', '-m', 'pytest', 'tests',
               'test_file_client.py', 'test_file_transfer.py', '-v', '-p', 'no:cacheprovider',
               f'--junitxml={xml}']
    started = time.monotonic()
    before = source_hashes()
    with (args.output/f'{args.label}.txt').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    suites = ET.parse(xml).getroot().findall('testsuite')
    # Pytest 9 includes successful unittest subtests in the suite's tests
    # attribute, without separate testcase nodes. Count collected test functions
    # independently so nested cases never inflate the release test count.
    cases = [c for s in suites for c in s.findall('testcase')]
    groups = {}
    for case in cases:
        groups.setdefault((case.get('classname'), case.get('name')), []).append(case)
    counts = {'tests': len(groups)}
    for tag, key in (('failure','failures'),('error','errors'),('skipped','skipped')):
        counts[key] = sum(any(c.find(tag) is not None for c in group) for group in groups.values())
    counts['passed'] = sum(all(not any(c.find(tag) is not None for tag in ('failure','error','skipped'))
                              for c in group) for group in groups.values())
    log_text = (args.output/f'{args.label}.txt').read_text(encoding='utf-8')
    collected = re.search(r'collected (\d+) items?', log_text)
    collection_matches = collected is not None and int(collected[1]) == counts['tests']
    stable = before == source_hashes()
    evidence = {'head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'command': command,'exit_code': result.returncode, 'counts': counts,
                'source_sha256': before, 'source_unchanged_during_run': stable,
                'collection_count_matches': collection_matches,
                'seconds': round(time.monotonic()-started,3),
                'status': 'PASS' if result.returncode==0 and counts['skipped']==0 and stable and collection_matches else 'FAIL'}
    (args.output/f'{args.label}.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence,indent=2))
    return int(evidence['status']!='PASS')

if __name__=='__main__':
    raise SystemExit(main())
