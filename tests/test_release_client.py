"""Release regressions on real sockets, HTTP and browser; isolated server ports."""
from pathlib import Path
import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import client
import server
from protocol import *
from role4_harness import Bridge, api, browser, wait_for


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class ReleaseClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='release-client-')
        self.old_cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.apps, self.raw, self.bridges = [], [], []
        self.tcp_port, self.udp_port = free_port(socket.SOCK_STREAM), free_port(socket.SOCK_DGRAM)
        self.patch_tcp = patch.object(client, 'TCP_PORT', self.tcp_port)
        self.patch_udp = patch.object(client, 'UDP_PORT', self.udp_port)
        self.patch_tcp.start(); self.patch_udp.start()
        script = (f"import sys;sys.path.insert(0,{str(ROOT)!r});import config;"
                  f"config.TCP_PORT={self.tcp_port};config.UDP_PORT={self.udp_port};"
                  "config.SERVER_BIND_HOST='127.0.0.1';import server;server.CollaborationServer().start()")
        self.process = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', '-c', script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def listening():
            self.assertIsNone(self.process.poll())
            with socket.create_connection(('127.0.0.1', self.tcp_port), timeout=.1):
                return True
        wait_for(listening, description='isolated release server')

    def tearDown(self):
        for bridge in self.bridges: bridge.close()
        for app in self.apps: app.close()
        for sock in self.raw: sock.close()
        self.process.terminate(); self.process.wait(5)
        self.patch_tcp.stop(); self.patch_udp.stop()
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def app(self, name):
        app = client.CollaborationClient(name, '', '127.0.0.1')
        self.apps.append(app)
        return app

    def raw_auth(self, name):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(('127.0.0.1', 0)); self.raw.append(udp)
        sock = socket.create_connection(('127.0.0.1', self.tcp_port), timeout=2)
        self.raw.append(sock)
        sock.sendall(encode_packet(Packet(MSG_HELLO_REQ)))
        self.assertEqual(recv_tcp_packet(sock).status, STATUS_OK)
        sock.sendall(encode_packet(Packet(MSG_AUTH_REQ, payload=dump_json({'username':name,'udp_port':udp.getsockname()[1]}))))
        return sock, recv_tcp_packet(sock)

    def test_reserved_identity_rejected_unicode_and_malformed_chat_survive(self):
        for name in ('*', '../alice', 'bad:name', [], ''):
            with self.subTest(name=name):
                sock, reply = self.raw_auth(name)
                self.assertEqual(reply.status, STATUS_ERR)
                self.assertEqual(sock.recv(1), b'')
        bob = self.app('Bình Nguyễn')
        raw, reply = self.raw_auth('alice-valid')
        self.assertEqual(reply.status, STATUS_OK)
        for bad in ([], {'mode': []}, {'mode':'unicast','recipient':[],'message':'x'}, {'mode':'broadcast','message':[]}):
            raw.sendall(encode_packet(Packet(MSG_DATA, seq_no=12, payload=dump_json(bad))))
            self.assertEqual(recv_tcp_packet(raw).status, STATUS_ERR)
        raw.sendall(encode_packet(Packet(MSG_DATA, payload=dump_json({'mode':'unicast','recipient':'Bình Nguyễn','message':'still works'}))))
        wait_for(lambda: any(m['text']=='still works' for m in bob.state()['messages']))
        self.assertNotIn('*', {u['username'] for u in bob.state()['users']})

    def test_http_worker_failure_is_visible_in_real_browser_and_session_disconnect(self):
        from playwright.sync_api import expect
        alice = self.app('alice')
        bridge = Bridge(alice); self.bridges.append(bridge)
        with browser() as instance:
            page = instance.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(bridge.url)
            expect(page.locator('#server-status')).to_contain_text('đã xác minh')
            self.assertEqual(api(bridge.url, '/api/file', {'to':'absent','name':'test.txt','data':base64.b64encode(b'x').decode()}), {'ok':True})
            expect(page.locator('#operations')).to_contain_text('absent')
            wait_for(lambda: any(o['status']=='failed' for o in api(bridge.url)['operations']))
            self.process.terminate(); self.process.wait(5)
            expect(page.locator('#server-status')).to_contain_text('mất kết nối')
            expect(page.locator('#api-status')).to_contain_text('hoạt động')
            self.assertEqual(api(bridge.url)['users'], [])
            self.assertFalse(errors)

    def test_upload_staging_is_request_owned_and_cleanup_runs_on_failure(self):
        alice = self.app('stage-alice')
        bridge = Bridge(alice); self.bridges.append(bridge)
        first_entered, release = threading.Event(), threading.Event()
        paths, contents = {}, {}
        # Observe the bridge boundary and select a valid worker interleaving.
        # Existing Role4DeliveryTests exercise the full UDP path with this race.
        original = alice.send_file
        def record(target, path):
            paths[target] = Path(path)
            if target=='first':
                first_entered.set()
                self.assertTrue(release.wait(3))
            contents[target] = Path(path).read_bytes()
            return original(target, path)  # unavailable target produces a real error
        alice.send_file = record
        try:
            api(bridge.url,'/api/file',{'to':'first','name':'same.txt','data':base64.b64encode(b'first').decode()})
            self.assertTrue(first_entered.wait(3))
            api(bridge.url,'/api/file',{'to':'second','name':'same.txt','data':base64.b64encode(b'second').decode()})
            wait_for(lambda: 'second' in contents)
            release.set()
            wait_for(lambda: len(contents)==2 and all(not p.exists() for p in paths.values()))
            self.assertEqual(contents, {'first':b'first','second':b'second'})
            self.assertNotEqual(paths['first'], paths['second'])
            self.assertTrue(all(not p.parent.exists() for p in paths.values()))
        finally:
            release.set()

    def test_http_disconnect_invalidates_browser_server_confirmation(self):
        from playwright.sync_api import expect
        alice = self.app('alice')
        bridge = Bridge(alice); self.bridges.append(bridge)
        with browser() as instance:
            page = instance.new_page()
            page.goto(bridge.url)
            expect(page.locator('#server-status')).to_contain_text('đã xác minh')
            page.locator('#draft').fill('retain while bridge is unavailable')
            bridge.close(); self.bridges.remove(bridge)
            expect(page.locator('#api-status')).to_contain_text('mất kết nối', timeout=12000)
            expect(page.locator('#server-status')).to_contain_text('chưa xác minh')
            expect(page.locator('#chat-submit')).to_be_disabled()
            expect(page.locator('#draft')).to_have_value('retain while bridge is unavailable')
            self.assertEqual(alice.state()['connection']['status'], 'connected')

    def test_offline_chat_error_correlates_to_operation(self):
        alice = self.app('alice')
        bridge = Bridge(alice); self.bridges.append(bridge)
        api(bridge.url, '/api/send', {'to':'absent','text':'test'})
        wait_for(lambda: any(o['kind']=='chat' and o['status']=='failed' for o in api(bridge.url)['operations']))
        self.assertEqual(alice.state()['connection']['status'], 'connected')

    def test_http_rejects_cross_origin_actions_and_rebinding_host(self):
        alice, bob = self.app('alice'), self.app('bob')
        bridge = Bridge(alice); self.bridges.append(bridge)
        port = bridge.server.server_port
        def request(method, path, headers, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                result = response.status, response.read()
                return result
            finally:
                connection.close()
        body = json.dumps({'to':'bob', 'text':'unauthorized webpage action'})
        for headers in (
            {'Content-Type':'text/plain', 'Origin':'https://untrusted.example'},
            {'Content-Type':'application/json', 'Origin':'https://untrusted.example'},
            {'Content-Type':'application/json', 'Origin':'null'},
            {'Content-Type':'application/json', 'Host':f'rebinding.example:{port}'},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(request('POST','/api/send',headers,body)[0],403)
        self.assertEqual(request('GET','/api/state',{'Host':f'rebinding.example:{port}'})[0],403)
        self.assertEqual(request('POST','/api/send',{'Content-Type':'text/plain'},body)[0],415)
        self.assertFalse(alice.messages)
        self.assertFalse(bob.messages)
        status, _ = request('POST','/api/send',
            {'Content-Type':'application/json','Origin':bridge.url},
            json.dumps({'to':'bob','text':'authorized local UI'}))
        self.assertEqual(status,200)
        wait_for(lambda:any(m['text']=='authorized local UI' for m in bob.state()['messages']))


class ReleaseDeadlineAndQueueTests(unittest.TestCase):
    def test_partial_hello_and_silent_auth_have_total_deadline(self):
        for mode in ('silent-hello','partial-hello','silent-auth'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='release-deadline-') as folder:
                listener = socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(1)
                finished = threading.Event(); errors=[]
                def serve():
                    try:
                        conn,_ = listener.accept()
                        with conn:
                            conn.settimeout(2)
                            recv_tcp_packet(conn)
                            if mode=='partial-hello': conn.sendall(encode_packet(Packet(MSG_HELLO_RESP, STATUS_OK))[:3])
                            if mode=='silent-auth':
                                conn.sendall(encode_packet(Packet(MSG_HELLO_RESP, STATUS_OK)))
                                recv_tcp_packet(conn)
                            self.assertEqual(conn.recv(100), b'')
                    except Exception as e:
                        errors.append(repr(e))
                    finally: finished.set()
                thread=threading.Thread(target=serve); thread.start()
                started=time.monotonic()
                with patch.object(client,'TCP_PORT',listener.getsockname()[1]), patch.object(client,'HANDSHAKE_TIMEOUT',.25):
                    with self.assertRaises((TimeoutError, socket.timeout)):
                        client.CollaborationClient('deadline', '', '127.0.0.1')
                self.assertLess(time.monotonic()-started, 1.5)
                self.assertTrue(finished.wait(2)); thread.join(2); listener.close()
                self.assertFalse(errors)

    def test_slow_reader_queue_does_not_block_healthy_peer(self):
        with patch.object(server, 'UDP_PORT', 0), patch.object(server, 'SERVER_HOST','127.0.0.1'):
            srv = server.CollaborationServer()
        sockets=[]; peers=[]
        try:
            for name in ('slow','healthy'):
                send, receive = socket.socketpair(); sockets.extend([send,receive])
                send.settimeout(.2); send.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4096)
                receive.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4096); receive.settimeout(2)
                srv.registry.register_peer(name,send,'127.0.0.1',1)
                peer=srv.registry.get_peer(name); peers.append(peer)
                threading.Thread(target=srv._peer_writer,args=(peer,),daemon=True).start()
            begin=time.monotonic()
            rejected=False
            for _ in range(200):
                if not srv._send_safely(peers[0], Packet(MSG_DATA,payload=b'x'*60000)):
                    rejected=True;break
            self.assertTrue(rejected)
            self.assertTrue(srv._send_safely(peers[1],Packet(MSG_DATA,payload=b'healthy')))
            self.assertEqual(recv_tcp_packet(sockets[3]).payload,b'healthy')
            self.assertLess(time.monotonic()-begin,1.5)
            self.assertTrue(peers[0]['closed'].is_set())
        finally:
            for peer in peers: srv._close_peer_socket(peer)
            for sock in sockets: sock.close()
            srv.udp_sock.close()

if __name__=='__main__':
    unittest.main()
