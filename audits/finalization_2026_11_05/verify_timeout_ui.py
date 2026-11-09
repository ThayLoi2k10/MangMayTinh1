"""Trace receiver expiry through unchanged state API and actual browser DOM."""
from pathlib import Path
import json
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT/'tests'))
sys.path.insert(0, str(ROOT))
from role4_harness import Lab, api, browser, names, wait_for
from file_transfer import FILE_CHUNK, decode_secure_json
from playwright.sync_api import expect

started = time.monotonic()
with Lab() as lab, browser() as instance:
    alice, bob = lab.client('timeout_alice'), lab.client('timeout_bob')
    wait_for(lambda: 'timeout_bob' in names(alice))
    original = alice.file_handler.send_packet_fn
    def no_chunks(packet, recipient):
        if decode_secure_json(packet.payload).get('kind') != FILE_CHUNK:
            original(packet, recipient)
    alice.file_handler.send_packet_fn = no_chunks
    source = lab.path/'interrupted.bin'
    source.write_bytes(b'x'*100)
    file_id = alice.send_file('timeout_bob', source)
    wait_for(lambda: bool(bob.state()['transfers']))
    bridge = lab.bridge(bob)
    page = instance.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(bridge.url)
    expect(page.locator('.transfer')).to_contain_text('Đang nhận')
    wait_for(lambda: alice.state()['transfers'][0]['status'].startswith('failed:'), timeout=15)
    expired = bob.file_handler.receiver.cleanup_expired(max_age=0)
    assert file_id in expired
    snapshot = api(bridge.url)
    assert snapshot['transfers'][0]['status'] == 'timeout'
    expect(page.locator('.transfer')).to_contain_text('Hết thời gian chờ')
    assert not errors
    evidence = {'status': 'PASS', 'file_id': file_id, 'http_state': snapshot,
        'dom_text': page.locator('.transfer').inner_text(), 'javascript_errors': errors,
        'expiry_trigger': 'cleanup_expired(max_age=0), no wall-clock timeout claim',
        'seconds': round(time.monotonic()-started,3)}
(OUT/'timeout_http_ui.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False),encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=True))
