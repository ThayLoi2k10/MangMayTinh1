"""Real server for the legacy chat script; standalone UDP loss script separately.

Legacy chat main lacks exit status on failed assertions; require all four PASS
lines as well as successful process exit. Do not silently accept printed FAIL.
"""
from pathlib import Path
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from role4_harness import Lab

def main():
    out=ROOT/'audits/release_2026_11_07'
    rows=[]
    for script in ('test_chat_routing.py','test_udp_streaming.py'):
        command=[sys.executable,'-X','utf8',str(ROOT/script)]
        started=time.monotonic()
        if script=='test_chat_routing.py':
            with Lab():
                result=subprocess.run(command,text=True,encoding='utf-8',stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT,timeout=150)
        else:
            result=subprocess.run(command,cwd=ROOT,text=True,encoding='utf-8',stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,timeout=300)
        (out/(script+'.txt')).write_text(result.stdout,encoding='utf-8')
        summary=[line for line in result.stdout.splitlines() if line.strip().startswith(('PASS |','FAIL |'))]
        # Actual scripts pad PASS to four columns, so whitespace is significant only inside label.
        failed=any(line.lstrip().startswith('FAIL') for line in result.stdout.splitlines())
        pass_lines=[line for line in result.stdout.splitlines() if line.lstrip().startswith('PASS') and '|' in line]
        expected=4 if script=='test_chat_routing.py' else 6
        ok=result.returncode==0 and not failed and len(pass_lines)==expected
        rows.append({'command':command,'exit_code':result.returncode,'pass_groups':len(pass_lines),
                     'expected_groups':expected,'status':'PASS' if ok else 'FAIL',
                     'seconds':round(time.monotonic()-started,3)})
        print(rows[-1],flush=True)
    (out/'legacy.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return int(any(r['status']!='PASS' for r in rows))

if __name__=='__main__': raise SystemExit(main())
