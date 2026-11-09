"""Independent application integration: stream bytes before file commit and no
cross-stream head-of-line blocking when one transfer repeatedly loses data.
"""
import asyncio
import hashlib
import unittest
from role4_harness import Lab,names,wait_for
from file_transfer import decode_secure_json,FILE_CHUNK

class ReleaseSystemTests(unittest.TestCase):
    def test_async_real_file_bytes_and_another_transfer_survive_loss(self):
        with Lab() as lab:
            alice,bob,cara=[lab.client(n) for n in ('alice','bob','cara')]
            wait_for(lambda:names(alice)==names(bob)==names(cara)=={'alice','bob','cara'})
            source=lab.path/'async.bin'
            content=bytes(range(256))*8192
            source.write_bytes(content)
            other=lab.path/'other.bin'
            other.write_bytes(b'independent transfer')
            original=alice.file_handler.send_packet_fn
            drops=[]
            def lose(packet,recipient):
                body=decode_secure_json(packet.payload)
                if recipient=='bob' and body.get('kind')==FILE_CHUNK and body.get('chunk_index')==2 and len(drops)<2:
                    drops.append(2)
                    return
                original(packet,recipient)
            alice.file_handler.send_packet_fn=lose
            fid=alice.send_file('bob',source)
            wait_for(lambda:fid in bob.file_handler.receiver.incoming)
            stream=bob.file_handler.receiver.get_stream(fid)
            async def consume():
                first=await asyncio.wait_for(stream.read(),5)
                self.assertEqual(first,content[:len(first)])
                self.assertFalse((lab.path/'downloads_bob'/'async.bin').exists(),
                                 'byte API must deliver before application commit')
                other_id=alice.send_file('cara',other)
                alice.send_message('cara','chat while file has loss')
                end=asyncio.get_running_loop().time()+5
                while not (lab.path/'downloads_cara'/'other.bin').exists():
                    self.assertLess(asyncio.get_running_loop().time(),end)
                    await asyncio.sleep(.01)
                self.assertFalse(stream.snapshot()['finished'], 'independent small stream must not wait for large stream')
                result=bytearray(first)
                async for chunk in stream: result.extend(chunk)
                return bytes(result),other_id
            received,other_id=asyncio.run(asyncio.wait_for(consume(),45))
            self.assertEqual(drops,[2,2])
            self.assertEqual(hashlib.sha256(received).digest(),hashlib.sha256(content).digest())
            self.assertEqual((lab.path/'downloads_bob'/'async.bin').read_bytes(),content)
            self.assertEqual((lab.path/'downloads_cara'/'other.bin').read_bytes(),other.read_bytes())
            wait_for(lambda:any(m['text']=='chat while file has loss' for m in cara.messages))
            wait_for(lambda:all(r['status']=='done' for r in alice.state()['transfers']))
            wait_for(lambda:not alice.file_handler._pending)
            record=next(r for r in alice.state()['transfers'] if r['file_id']==fid)
            self.assertGreaterEqual(record['retransmissions'],2)
            self.assertGreaterEqual(record['congestion']['loss_events'],1)
