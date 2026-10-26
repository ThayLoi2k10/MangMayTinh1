"""Independent bounded protocol audit. No production file modifications.

Run from repository: .venv/Scripts/python.exe -X utf8 audits/final_2026_10_26/protocol_security/audit_protocol.py
Uses a disposable loopback server on 19000/19001, isolated temporary cwd.
Assertions express desired behaviour; failures are reported, never skipped.
"""
from __future__ import annotations
import base64
import contextlib
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
from protocol import *

TCP, UDP = 19000, 19001

def wait(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError(f"Condition not met within {timeout}s")

def observe(predicate, timeout=1):
    """Bounded observation of an unwanted event, not an assertion it must occur."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.02)
    return False

def server_worker():
    import server
    server.SERVER_HOST, server.TCP_PORT, server.UDP_PORT = '127.0.0.1', TCP, UDP
    app = server.CollaborationServer()
    threading.Thread(target=app.start, daemon=True).start()
    # Replay a captured genuine server snapshot from the same server socket.
    # This models late UDP delivery; production receive/control logic is unchanged.
    for line in sys.stdin:
        request = json.loads(line)
        app.udp_sock.sendto(base64.b64decode(request['packet']), tuple(request['target']))

class RawPeer:
    def __init__(self, username, password=None, udp_port=None):
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(('127.0.0.1', 0))
        self.udp.settimeout(2)
        self.tcp = socket.create_connection(('127.0.0.1', TCP), timeout=2)
        self.tcp.sendall(encode_packet(Packet(MSG_HELLO_REQ)))
        assert recv_tcp_packet(self.tcp).msg_type == MSG_HELLO_RESP
        body = {'username':username, 'udp_port':udp_port if udp_port is not None else self.udp.getsockname()[1]}
        if password is not None:
            body['password'] = password
        self.tcp.sendall(encode_packet(Packet(MSG_AUTH_REQ, payload=dump_json(body))))
        self.auth = recv_tcp_packet(self.tcp)
        self.session_id = load_json(self.auth.payload).get('session_id')
    def close(self):
        if self.session_id:
            with contextlib.suppress(OSError):
                self.tcp.sendall(encode_packet(Packet(MSG_LOGOUT_REQ, payload=dump_json({'session_id':self.session_id}))))
        self.tcp.close()
        self.udp.close()

class Lab:
    def __enter__(self):
        for kind, port in ((socket.SOCK_STREAM,TCP),(socket.SOCK_DGRAM,UDP)):
            with socket.socket(socket.AF_INET,kind) as probe:
                probe.bind(('127.0.0.1',port))  # Never use or terminate a user's listener.
        self.temp = tempfile.TemporaryDirectory(prefix='audit-protocol-')
        self.previous = Path.cwd()
        os.chdir(self.temp.name)
        self.log = (OUT / 'server.log').open('a', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--server'],
            stdin=subprocess.PIPE,stdout=self.log,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
            env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        def ready():
            if self.process.poll() is not None:
                raise RuntimeError('Disposable server exited')
            try:
                with socket.create_connection(('127.0.0.1',TCP),timeout=.2):
                    return True
            except OSError:
                return False
        wait(ready)
        import client
        client.TCP_PORT, client.UDP_PORT = TCP, UDP
        self.client_module = client
        self.apps, self.raws = [], []
        return self
    def app(self, name):
        app = self.client_module.CollaborationClient(name,'','127.0.0.1')
        self.apps.append(app)
        return app
    def raw(self, *args, **kwargs):
        peer = RawPeer(*args, **kwargs)
        self.raws.append(peer)
        return peer
    def replay(self, packet, target):
        self.process.stdin.write(json.dumps({'packet':base64.b64encode(packet).decode(),'target':target})+'\n')
        self.process.stdin.flush()
    def __exit__(self,*args):
        for raw in self.raws:
            raw.close()
        for app in self.apps:
            app.close()
        self.process.terminate()
        self.process.wait(timeout=5)
        self.process.stdin.close()
        self.log.close()
        os.chdir(self.previous)
        time.sleep(1.1)
        self.temp.cleanup()

def usernames(app):
    return {row['username'] for row in app.users}

def tcp_framing_and_logout(e):
    with Lab() as lab:
        with socket.create_connection(('127.0.0.1',TCP),timeout=2) as sock:
            wire = encode_packet(Packet(MSG_HELLO_REQ))
            sock.sendall(wire[:3]); sock.sendall(wire[3:])
            hello = recv_tcp_packet(sock)
            assert hello.msg_type == MSG_HELLO_RESP and hello.status == STATUS_OK
        bob = lab.raw('bob')
        assert bob.auth.status == STATUS_OK
        duplicate = lab.raw('bob')
        assert duplicate.auth.status == STATUS_ERR
        # Wrong session token cannot log out this connection; next chat still routes.
        alice = lab.app('alice')
        bob.tcp.sendall(encode_packet(Packet(MSG_LOGOUT_REQ,payload=dump_json({'session_id':'wrong'}))) +
                       encode_packet(Packet(MSG_DATA,payload=dump_json({'mode':'unicast','recipient':'alice','message':'after wrong logout'}))))
        wait(lambda:any(m['text']=='after wrong logout' for m in alice.messages))
        bob.tcp.sendall(encode_packet(Packet(MSG_LOGOUT_REQ,payload=dump_json({'session_id':bob.session_id}))))
        reply = recv_tcp_packet(bob.tcp)
        assert reply.msg_type == MSG_LOGOUT_RESP and reply.status == STATUS_OK
        bob.session_id = None
        e.update(fragmented_handshake=True,coalesced_frames=True,duplicate_rejected=True,wrong_token_did_not_logout=True,graceful_logout=True)

def chat_payload_encryption(e):
    with Lab() as lab:
        alice = lab.app('alice')
        bob = lab.raw('bob')
        marker = 'AUDIT_PRIVATE_PAYLOAD_20261026'
        alice.send_message('bob',marker)
        packet = recv_tcp_packet(bob.tcp)
        e.update(payload_hex=packet.payload.hex(), plaintext=packet.payload.decode('utf-8', errors='replace'), transport='raw TCP')
        assert marker.encode() not in packet.payload, 'Private chat payload is readable without decrypting'

def unauthenticated_discovery_poison(e):
    with Lab() as lab:
        alice = lab.app('alice')
        wait(lambda:'alice' in usernames(alice))
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as attacker:
            attacker.bind(('127.0.0.1',0))
            forged = {'users':[{'username':'mallory','ip':'127.0.0.1','udp_port':attacker.getsockname()[1]}]}
            attacker.sendto(encode_packet(Packet(MSG_USER_LIST,payload=dump_json(forged))),('127.0.0.1',alice.udp_port))
            observe(lambda:'mallory' in alice.peer_addrs)
            e.update(attacker_source=attacker.getsockname(), expected_server_source=['127.0.0.1',UDP],users=alice.users,peer_addrs=alice.peer_addrs)
            assert 'mallory' not in alice.peer_addrs, 'Unauthenticated UDP source overwrote discovery and file routing'

def malformed_discovery_survival(e):
    with Lab() as lab:
        alice, bob = lab.app('alice'), lab.app('bob')
        wait(lambda:usernames(alice)=={'alice','bob'})
        receiver = next(thread for thread in threading.enumerate()
                        if getattr(getattr(thread,'_target',None),'__self__',None) is alice
                        and getattr(getattr(thread,'_target',None),'__name__','') == '_udp_receive_loop')
        exceptions = []
        previous_hook = threading.excepthook
        def capture(args):
            exceptions.append({'thread':args.thread.name,'error':str(args.exc_value),'type':args.exc_type.__name__})
        threading.excepthook = capture
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as attacker:
                attacker.sendto(encode_packet(Packet(MSG_USER_LIST,payload=b'[]')),('127.0.0.1',alice.udp_port))
            observe(lambda:not receiver.is_alive())
            carol = lab.app('carol')
            wait(lambda:'carol' in usernames(bob))
            bob.send_message('alice','tcp remains alive')
            wait(lambda:any(m['text']=='tcp remains alive' for m in alice.messages))
            e.update(exceptions=exceptions,udp_thread_alive=receiver.is_alive(),stop_event=alice.stop_event.is_set(),
                     alice_users=alice.users,bob_users=bob.users,tcp_chat_still_received=True)
            assert receiver.is_alive(), 'One unauthenticated valid-JSON UDP datagram permanently killed discovery/file receive thread'
        finally:
            threading.excepthook = previous_hook

def delayed_server_snapshot(e):
    with Lab() as lab:
        # Raw peer captures actual bytes emitted by the real server, no synthesized list.
        observer = lab.raw('observer')
        old, source = observer.udp.recvfrom(65535)
        assert source[1] == UDP
        alice = lab.app('alice')
        wait(lambda:usernames(alice)=={'observer','alice'})
        lab.replay(old,('127.0.0.1',alice.udp_port))
        observe(lambda:usernames(alice)=={'observer'})
        # Allow at least one real heartbeat interval: heartbeat does not refresh lists.
        deadline = time.monotonic()+5.3
        while time.monotonic()<deadline:
            time.sleep(.05)
        e.update(captured_source=source,old_packet_seq=decode_packet(old).seq_no,
                 users_after_delayed_snapshot=alice.users,client_stopped=alice.stop_event.is_set(),observed_seconds=5.3)
        assert usernames(alice)=={'observer','alice'}, 'Delayed genuine server snapshot overwrites newer users and is not repaired by heartbeat'

def valid_chat_payload_boundary(e):
    with Lab() as lab:
        sender, receiver = lab.raw('sender'), lab.raw('receiver')
        fixed = dump_json({'mode':'unicast','recipient':'receiver','message':''})
        text_value = 'x' * (65535-len(fixed))
        payload = dump_json({'mode':'unicast','recipient':'receiver','message':text_value})
        assert len(payload)==65535
        sender.tcp.sendall(encode_packet(Packet(MSG_DATA,payload=payload)))
        try:
            packet = recv_tcp_packet(receiver.tcp)
            delivered = load_json(packet.payload).get('message')==text_value
        except socket.timeout:
            delivered = False
        rejected, closed = False, False
        if not delivered:
            try:
                response = recv_tcp_packet(sender.tcp)
                rejected = response.status == STATUS_ERR
            except (ConnectionResetError, OSError) as exc:
                closed = not isinstance(exc, socket.timeout)
        e.update(input_payload_bytes=len(payload),message_bytes=len(text_value),delivered=delivered,
                 sender_closed=closed,explicit_error_response=rejected)
        assert delivered or rejected, 'Wire-valid maximum-sized chat is neither delivered nor explicitly rejected; sender disconnects'

def auth_port_validation(e):
    with Lab() as lab:
        peer = lab.raw('badport',udp_port=70000)
        e.update(auth_status=peer.auth.status,auth_payload=load_json(peer.auth.payload),submitted_udp_port=70000)
        # Keep an unrelated healthy client alive to distinguish per-session failure from server crash.
        healthy = lab.raw('healthy')
        e['server_accepts_next_client'] = healthy.auth.status == STATUS_OK
        assert peer.auth.status == STATUS_ERR, 'Server reports successful authentication for impossible UDP port 70000'

def password_semantics_observation(e):
    with Lab() as lab:
        peer = lab.raw('identity_without_account',password='arbitrary-unverified-value')
        e.update(login_kind='unique username registration; not credential verification',arbitrary_password_accepted=peer.auth.status==STATUS_OK,
                 grading_note='Specification does not explicitly require password verification; risk observation, not failed requirement')

CASES = [
    ('P01_tcp_framing_auth_logout',tcp_framing_and_logout),
    ('P02_chat_payload_encryption',chat_payload_encryption),
    ('P03_unauthenticated_discovery_poison',unauthenticated_discovery_poison),
    ('P04_malformed_discovery_survival',malformed_discovery_survival),
    ('P05_delayed_server_snapshot',delayed_server_snapshot),
    ('P06_valid_chat_payload_boundary',valid_chat_payload_boundary),
    ('P07_auth_port_validation',auth_port_validation),
    ('P08_password_semantics_observation',password_semantics_observation),
]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report = {'baseline':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'ports':[TCP,UDP],'interpreter':sys.executable,'cases':[]}
    started=time.monotonic()
    with (OUT/'execution.log').open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        for name, test in CASES:
            evidence={}
            begin=time.monotonic()
            try:
                test(evidence)
                result={'name':name,'status':'OBSERVATION' if name.startswith('P08') else 'PASS','evidence':evidence}
            except Exception:
                result={'name':name,'status':'FAIL','evidence':evidence,'traceback':traceback.format_exc()}
            result['duration_s']=round(time.monotonic()-begin,3)
            report['cases'].append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    report['duration_s']=round(time.monotonic()-started,3)
    report['passed']=sum(case['status']=='PASS' for case in report['cases'])
    report['failed']=sum(case['status']=='FAIL' for case in report['cases'])
    report['observations']=sum(case['status']=='OBSERVATION' for case in report['cases'])
    (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'total':len(CASES),'passed':report['passed'],'failed':report['failed'],'observations':report['observations'],'duration_s':report['duration_s']}))
    return 1 if report['failed'] else 0

if __name__=='__main__':
    if '--server' in sys.argv:
        server_worker()
    else:
        raise SystemExit(main())
