"""Valid-traffic backend audit; unchanged production modules, disposable localhost.

Use --repeat to repeat short terminal-loss cases without the 24 MiB transfer.
No malformed file payloads; only intentional loss of valid emitted packets.
"""
from __future__ import annotations
import argparse
import contextlib
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
PORTS = (29000, 29001)


def wait(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError(f"condition not reached within {timeout}s")


class Lab:
    def __enter__(self):
        for kind, port in ((socket.SOCK_STREAM, PORTS[0]), (socket.SOCK_DGRAM, PORTS[1])):
            with socket.socket(socket.AF_INET, kind) as probe:
                probe.bind(("127.0.0.1", port))
        self.temp = tempfile.TemporaryDirectory(prefix="a1-backend-")
        self.path = Path(self.temp.name)
        self.cwd = Path.cwd()
        self.apps = []
        os.chdir(self.path)
        self.log = (OUT / "server_execution.txt").open("a", encoding="utf-8")
        self.server = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--server"],
                                       cwd=self.path, stdout=self.log, stderr=subprocess.STDOUT)
        def ready():
            if self.server.poll() is not None:
                raise RuntimeError("server exited")
            try:
                with socket.create_connection(("127.0.0.1", PORTS[0]), timeout=.2):
                    return True
            except OSError:
                return False
        wait(ready, 5)
        import client
        client.TCP_PORT, client.UDP_PORT = PORTS
        self.alice = client.CollaborationClient("audit_alice", "", "127.0.0.1")
        self.apps.append(self.alice)
        self.bob = client.CollaborationClient("audit_bob", "", "127.0.0.1")
        self.apps.append(self.bob)
        wait(lambda: "audit_bob" in self.alice.peer_addrs and "audit_alice" in self.bob.peer_addrs)
        return self

    def __exit__(self, *_):
        for app in self.apps:
            app.close()
        self.server.terminate()
        self.server.wait(5)
        self.log.close()
        os.chdir(self.cwd)
        time.sleep(1.1)
        self.temp.cleanup()


def record(app, fid):
    return next((r for r in app.state()["transfers"] if r["file_id"] == fid), {})


def sha(data):
    return hashlib.sha256(data).hexdigest()


def terminal_loss(e, mode):
    from file_transfer import decode_secure_json
    with Lab() as lab:
        original = lab.bob.file_handler.send_packet_fn
        dropped = []
        def loss(packet, recipient):
            body = decode_secure_json(packet.payload)
            match = (mode == "result" and body.get("kind") == "FILE_RESULT") or (
                mode == "ack" and body.get("kind") == "ACK" and body.get("chunk_index") == 0)
            if match and not dropped:
                dropped.append(body)
                return
            original(packet, recipient)
        lab.bob.file_handler.send_packet_fn = loss
        content = b"valid terminal reliability control" * 3
        source = lab.path / "terminal.bin"
        source.write_bytes(content)
        start = time.monotonic()
        fid = lab.alice.send_file("audit_bob", source)
        wait(lambda: record(lab.bob, fid).get("status") == "completed")
        history = []
        last = None
        # Observe past the full retry budget. Early 'done' is not final evidence.
        while time.monotonic() - start < 7:
            current = record(lab.alice, fid)
            state = (current.get("status"), current.get("progress"))
            if state != last:
                history.append({"seconds": round(time.monotonic()-start, 3), **current})
                last = state
            time.sleep(.02)
        target = lab.path / "downloads_audit_bob" / source.name
        e.update(dropped=dropped, sender=record(lab.alice, fid), receiver=record(lab.bob, fid),
                 sender_history=history, bytes_match=target.read_bytes()==content,
                 pending_count=len(lab.alice.file_handler._pending), observation_seconds=7)
        lab.alice.send_message("audit_bob", "chat after terminal loss")
        wait(lambda: any(m["text"] == "chat after terminal loss" for m in lab.bob.messages))
        e["chat_still_operates"] = True
        assert len(dropped) == 1
        assert e["bytes_match"]
        assert e["sender"]["status"] == "done", "Sender must recover one lost terminal packet and remain done after retry horizon"


def valid_files(e):
    with Lab() as lab:
        cases = []
        for name, content in (("empty.bin",b""), ("marker.bin",b"__END__"),
                              ("binary unicode tên.bin",bytes(range(256))*17)):
            source = lab.path / name
            source.write_bytes(content)
            fid = lab.alice.send_file("audit_bob", source)
            wait(lambda: record(lab.alice, fid).get("status") == "done")
            wait(lambda: record(lab.bob, fid).get("status") == "completed")
            actual = (lab.path / "downloads_audit_bob" / name).read_bytes()
            cases.append({"name":name,"expected_sha256":sha(content),"actual_sha256":sha(actual),
                          "sender":record(lab.alice,fid),"receiver":record(lab.bob,fid)})
            assert actual == content
        e["files"] = cases


def destination_collision(e):
    with Lab() as lab:
        source = lab.path / "same.bin"
        first, second = b"original"*200, b"new content"*200
        source.write_bytes(first)
        fid = lab.alice.send_file("audit_bob",source)
        wait(lambda:record(lab.alice,fid).get("status")=="done")
        source.write_bytes(second)
        fid2 = lab.alice.send_file("audit_bob",source)
        wait(lambda:record(lab.alice,fid2).get("status","").startswith("failed"))
        time.sleep(3.5)  # Observe beyond sender retry budget, not a wait-to-pass workaround.
        target = lab.path / "downloads_audit_bob" / source.name
        e.update(sender=record(lab.alice,fid2), receiver=record(lab.bob,fid2),
                 destination_preserved=target.read_bytes()==first,
                 pending_count=len(lab.alice.file_handler._pending))
        assert e["destination_preserved"]
        assert e["sender"]["status"].startswith("failed")
        assert e["receiver"]["status"].startswith("failed")


def large_file(e):
    with Lab() as lab:
        content = bytes(range(256)) * (24*1024*1024//256)
        source = lab.path / "24-mib.bin"
        source.write_bytes(content)
        start = time.monotonic()
        fid = lab.alice.send_file("audit_bob",source)
        samples=[]
        observed=set()
        next_sample=0
        while time.monotonic()-start < 180:
            elapsed=time.monotonic()-start
            send,receive=record(lab.alice,fid),record(lab.bob,fid)
            observed.add(receive.get("progress",0))
            if elapsed>=next_sample:
                samples.append({"seconds":round(elapsed,2),"sender":send,"receiver":receive})
                next_sample+=15
            if send.get("status") != "sending" and receive.get("status") not in (None,"receiving"):
                break
            time.sleep(.05)
        target=lab.path / "downloads_audit_bob" / source.name
        e.update(bytes=len(content),seconds=round(time.monotonic()-start,3),samples=samples,
                 sender=record(lab.alice,fid),receiver=record(lab.bob,fid),
                 expected_sha256=sha(content),actual_sha256=sha(target.read_bytes()) if target.exists() else None,
                 intermediate_progress=any(0<x<100 for x in observed),natural_timeout=True)
        assert e["actual_sha256"]==e["expected_sha256"]
        assert e["sender"]["status"]=="done" and e["receiver"]["status"]=="completed"


def encrypted_chat(e):
    from protocol import encode_packet
    with Lab() as lab:
        sent=[]
        original=lab.alice._send_tcp
        def observe(packet):
            sent.append(encode_packet(packet))
            original(packet)
        lab.alice._send_tcp=observe
        text="fresh encrypted audit marker 2026_11_05"
        lab.alice.send_message("audit_bob",text)
        wait(lambda:any(m["text"]==text for m in lab.bob.messages))
        e.update(plaintext_absent_from_emitted_wire=all(text.encode() not in wire for wire in sent),
                 receiver_decrypted_correctly=True,wire_packet_count=len(sent))
        assert e["plaintext_absent_from_emitted_wire"]


def streams(e):
    from udp_streamer import UDPStreamSender,UDPStreamReceiver
    from protocol import decode_packet,MSG_ACK
    results=[]
    for name,data,drop_eof_ack in (("empty",b"",False),("literal_marker",b"__END__",False),
                                 ("marker_boundary",b"x"*700+b"__END__",False),
                                 ("lost_eof_ack",bytes(range(256))*5,True)):
        sender_sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        receiver_sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        sender_sock.bind(("127.0.0.1",0));receiver_sock.bind(("127.0.0.1",0));receiver_sock.settimeout(.1)
        dropped=[]
        class ReplySocket:
            def sendto(self,raw,addr):
                packet=decode_packet(raw)
                if drop_eof_ack and packet.msg_type==MSG_ACK and packet.seq_no==(len(data)+699)//700 and not dropped:
                    dropped.append(packet.seq_no);return len(raw)
                return receiver_sock.sendto(raw,addr)
        receiver=UDPStreamReceiver(ReplySocket());sender=UDPStreamSender(sender_sock,receiver_sock.getsockname())
        stop=threading.Event();errors=[]
        def receive():
            while not stop.is_set():
                try:
                    raw,addr=receiver_sock.recvfrom(65535);receiver.handle_raw(raw,addr)
                except socket.timeout:continue
                except OSError:break
                except Exception:errors.append(traceback.format_exc());break
        worker=threading.Thread(target=receive);worker.start()
        try:
            success=sender.send_data(data,timeout=8)
            actual=receiver.get_data()
            row={"case":name,"input_bytes":len(data),"output_bytes":len(actual),"bytes_equal":actual==data,
                 "sender_success":success,"sender_finished":sender.is_finished,"receiver_complete":receiver.is_complete(),
                 "dropped_eof_ack":dropped,"errors":errors}
            results.append(row)
        finally:
            stop.set();sender_sock.close();receiver_sock.close();worker.join(2)
    e["streams"]=results
    assert all(r["sender_success"] and r["sender_finished"] and r["receiver_complete"] and r["bytes_equal"] and not r["errors"] for r in results)
    assert results[-1]["dropped_eof_ack"]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--repeat",action="store_true");args=parser.parse_args()
    cases=[("lost_file_result",lambda e:terminal_loss(e,"result")),("lost_final_chunk_ack",lambda e:terminal_loss(e,"ack"))]
    if not args.repeat:
        cases += [("valid_files",valid_files),("destination_collision",destination_collision),
                  ("encrypted_chat",encrypted_chat),("standalone_streams",streams),("24_mib_natural",large_file)]
    report={"baseline":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
            "python":sys.executable,"ports":PORTS,"cases":[],"production_edits":False}
    started=time.monotonic()
    for name,case in cases:
        evidence={};begin=time.monotonic()
        try:
            case(evidence);row={"name":name,"status":"PASS","evidence":evidence}
        except Exception:
            row={"name":name,"status":"FAIL","evidence":evidence,"traceback":traceback.format_exc()}
        row["seconds"]=round(time.monotonic()-begin,3);report["cases"].append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
        (OUT / ("repeat_results.json" if args.repeat else "results.json")).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    report.update(seconds=round(time.monotonic()-started,3),passed=sum(c["status"]=="PASS" for c in report["cases"]),failed=sum(c["status"]=="FAIL" for c in report["cases"]))
    (OUT / ("repeat_results.json" if args.repeat else "results.json")).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    return int(report["failed"]>0)


if __name__=="__main__":
    if "--server" in sys.argv:
        import config
        config.SERVER_BIND_HOST="127.0.0.1";config.TCP_PORT,config.UDP_PORT=PORTS
        import server
        server.CollaborationServer().start()
    else:
        raise SystemExit(main())
