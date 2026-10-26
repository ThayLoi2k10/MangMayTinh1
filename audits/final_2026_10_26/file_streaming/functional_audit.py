r"""Read-only production audit using valid local application traffic only.

Run from repository: .venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/file_streaming/functional_audit.py
Own disposable server ports 29000/29001. No packet mutation or security probes.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def wait(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError(f'Condition did not become true within {seconds} seconds')


class Lab:
    def __enter__(self):
        import client
        for kind, port in [(socket.SOCK_STREAM, 29000), (socket.SOCK_DGRAM, 29001)]:
            with socket.socket(socket.AF_INET, kind) as probe:
                probe.bind(('127.0.0.1', port))
        client.TCP_PORT, client.UDP_PORT = 29000, 29001
        self.tmp = tempfile.TemporaryDirectory(prefix='file-functional-audit-')
        self.path = Path(self.tmp.name)
        self.cwd = Path.cwd()
        self.apps = []
        self.log = (OUT / 'server.log').open('w', encoding='utf-8')
        os.chdir(self.path)
        self.process = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--server'],
                                        cwd=self.path, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(('127.0.0.1', 29000), timeout=.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.02)
        self.alice = client.CollaborationClient('audit_alice', '', '127.0.0.1')
        self.apps.append(self.alice)
        self.bob = client.CollaborationClient('audit_bob', '', '127.0.0.1')
        self.apps.append(self.bob)
        wait(lambda: 'audit_bob' in self.alice.peer_addrs and 'audit_alice' in self.bob.peer_addrs)
        return self

    def __exit__(self, *_):
        for app in self.apps:
            app.close()
        self.process.terminate()
        self.process.wait(timeout=5)
        self.log.close()
        os.chdir(self.cwd)
        time.sleep(1.1)
        self.tmp.cleanup()


def record(app, fid):
    return next((r for r in app.state()['transfers'] if r['file_id'] == fid), {})


def valid_file_cases():
    evidence = []
    with Lab() as lab:
        source = lab.path / 'ordinary.bin'
        first = bytes(range(256)) * 4
        source.write_bytes(first)
        fid = lab.alice.send_file('audit_bob', source)
        wait(lambda: record(lab.alice, fid).get('status') != 'sending')
        wait(lambda: record(lab.bob, fid).get('status') == 'completed')
        target = lab.path / 'downloads_audit_bob' / source.name
        evidence.append({'case':'normal_binary', 'sender':record(lab.alice,fid),
                         'receiver':record(lab.bob,fid), 'sha256_matches':hashlib.sha256(first).digest()==hashlib.sha256(target.read_bytes()).digest()})

        second = b'new content with the same filename' * 40
        source.write_bytes(second)
        fid2 = lab.alice.send_file('audit_bob', source)
        wait(lambda: record(lab.alice, fid2).get('status') != 'sending')
        evidence.append({'case':'same_filename_different_contents', 'sender':record(lab.alice,fid2),
                         'receiver':record(lab.bob,fid2),
                         'source_sha256':hashlib.sha256(second).hexdigest(),
                         'destination_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                         'destination_preserved':target.read_bytes()==first,
                         'delivered_new_content':target.read_bytes()==second})

        fid3 = lab.alice.send_file('audit_bob', source)
        wait(lambda: record(lab.alice, fid3).get('status') != 'sending')
        evidence.append({'case':'same_filename_repeat_confirmation', 'sender':record(lab.alice,fid3),
                         'receiver':record(lab.bob,fid3), 'delivered_new_content':target.read_bytes()==second})

        empty = lab.path / 'empty.bin'
        empty.write_bytes(b'')
        empty_id = lab.alice.send_file('audit_bob', empty)
        wait(lambda: record(lab.alice, empty_id).get('status') != 'sending')
        wait(lambda: record(lab.bob, empty_id).get('status') == 'completed')
        evidence.append({'case':'empty_file_integrated', 'sender':record(lab.alice,empty_id),
                         'receiver':record(lab.bob,empty_id),
                         'destination_size':(lab.path/'downloads_audit_bob'/'empty.bin').stat().st_size})

        marker = lab.path / 'literal_marker.bin'
        marker.write_bytes(b'__END__')
        marker_id = lab.alice.send_file('audit_bob', marker)
        wait(lambda: record(lab.alice, marker_id).get('status') != 'sending')
        wait(lambda: record(lab.bob, marker_id).get('status') == 'completed')
        evidence.append({'case':'literal_end_marker_integrated', 'sender':record(lab.alice,marker_id),
                         'receiver':record(lab.bob,marker_id),
                         'byte_exact':(lab.path/'downloads_audit_bob'/'literal_marker.bin').read_bytes()==b'__END__'})
    return evidence


def streaming_case(data, name):
    from udp_streamer import UDPStreamSender, UDPStreamReceiver
    sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender_sock.bind(('127.0.0.1', 0))
    receiver_sock.bind(('127.0.0.1', 0))
    receiver_sock.settimeout(.1)
    receiver = UDPStreamReceiver(receiver_sock)
    sender = UDPStreamSender(sender_sock, receiver_sock.getsockname())
    stop = threading.Event()
    errors = []
    def receive():
        while not stop.is_set() and not receiver.is_complete():
            try:
                raw, addr = receiver_sock.recvfrom(65535)
                receiver.handle_raw(raw, addr)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                errors.append(traceback.format_exc())
                break
    worker = threading.Thread(target=receive)
    worker.start()
    try:
        ok = sender.send_data(data, timeout=5)
        end = time.monotonic()+1
        while not receiver.is_complete() and time.monotonic()<end:
            time.sleep(.01)
        received = receiver.get_data()
        return {'case':name, 'input_size':len(data), 'output_size':len(received),
                'sender_result':ok, 'sender_finished':sender.is_finished,
                'receiver_complete':receiver.is_complete(), 'byte_exact':received==data,
                'source_sha256':hashlib.sha256(data).hexdigest(),
                'received_sha256':hashlib.sha256(received).hexdigest(),
                'sender_stats':sender.get_stats(), 'receiver_stats':receiver.get_stats(), 'errors':errors}
    finally:
        stop.set()
        sender_sock.close()
        receiver_sock.close()
        worker.join(2)


def main():
    results = {'baseline':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
               'scope':'valid application traffic only; isolated loopback; no malformed/security injection'}
    started = time.monotonic()
    results['integrated_file'] = valid_file_cases()
    results['standalone_streaming'] = [
        streaming_case(bytes(range(256))*4, 'normal_binary'),
        streaming_case(b'__END__', 'literal_end_marker'),
        streaming_case(b'x'*700+b'__END__', 'end_marker_as_last_data_chunk'),
        streaming_case(b'__END__', 'literal_end_marker_repeat_confirmation'),
        streaming_case(b'', 'empty_stream'),
    ]
    results['elapsed_seconds'] = round(time.monotonic()-started,3)
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    failures = [r['case'] for r in results['integrated_file'] if r.get('sender',{}).get('status')=='done' and r.get('delivered_new_content') is False]
    failures += [r['case'] for r in results['standalone_streaming'] if not(r['sender_result'] and r['receiver_complete'] and r['byte_exact'])]
    print('FUNCTIONAL_FAILURES:', failures)
    return 1 if failures else 0


if __name__=='__main__':
    if '--server' in sys.argv:
        import server
        server.SERVER_HOST, server.TCP_PORT, server.UDP_PORT = '127.0.0.1',29000,29001
        server.CollaborationServer().start()
    else:
        raise SystemExit(main())
