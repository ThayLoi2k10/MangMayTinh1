"""Real maximum-size transfer, logical indices across 16-bit wrap, SHA-256.

Run separately from suites using ports9000/9001. Only owned temp data is removed.
The deadline bounds this experiment, not the production retransmission timeout.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from role4_harness import Lab,names,wait_for

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mib',type=int,default=100)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    evidence={'bytes':args.mib*1024**2,'status':'RUNNING'}
    started=time.monotonic()
    try:
        with Lab() as lab:
            assert shutil.disk_usage(lab.path).free > (args.mib*3+100)*1024**2
            alice,bob=lab.client('large_alice'),lab.client('large_bob')
            wait_for(lambda:names(alice)==names(bob)=={'large_alice','large_bob'})
            source=lab.path/'maximum.bin'
            block=bytes(range(256))*4096
            with source.open('wb') as stream:
                for _ in range(args.mib): stream.write(block)
            expected=digest(source)
            # Test the real encoder wrap rather than artificially shrinking its range.
            alice.seq=65530
            fid=alice.send_file('large_bob',source)
            samples=[]
            deadline=time.monotonic()+600
            next_sample=0
            def state(app):
                return next((r for r in app.state()['transfers'] if r['file_id']==fid),{})
            while time.monotonic()<deadline:
                elapsed=time.monotonic()-started
                send,receive=state(alice),state(bob)
                if elapsed>=next_sample:
                    samples.append({'seconds':round(elapsed,2),'sender':send,'receiver':receive})
                    next_sample=elapsed+15
                    print('progress',round(elapsed,1),send.get('progress'),receive.get('progress'),flush=True)
                if send.get('status')!='sending' and receive.get('status') not in (None,'receiving'): break
                time.sleep(.05)
            target=lab.path/'downloads_large_bob'/'maximum.bin'
            evidence.update(sender=state(alice),receiver=state(bob),samples=samples,
                expected_sha256=expected,actual_sha256=digest(target) if target.exists() else None,
                header_sequence_start=65530,pending=len(alice.file_handler._pending))
            assert evidence['sender']['status']=='done',evidence['sender']
            assert evidence['receiver']['status']=='completed',evidence['receiver']
            assert evidence['actual_sha256']==expected
            wait_for(lambda:not alice.file_handler._pending,description='pending ACK cleanup')
            alice.send_message('large_bob','chat after maximum file')
            wait_for(lambda:any(m['text']=='chat after maximum file' for m in bob.messages))
            evidence['chat_survives']=True
        evidence['status']='PASS'
    except Exception:
        evidence.update(status='FAIL',traceback=traceback.format_exc())
    evidence['seconds']=round(time.monotonic()-started,3)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k!='samples'},indent=2))
    return int(evidence['status']!='PASS')

if __name__=='__main__': raise SystemExit(main())
