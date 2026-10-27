"""Controlled faults at the existing file send callback, still using real UDP.

No production source is patched. Faults are deterministic, scoped to these
client instances, and deliberately independent of protocol retry logic.
"""
import threading
import unittest

from role4_harness import Lab, names, wait_for
from file_transfer import decode_secure_json, FILE_CHUNK


class Role4NetworkTests(unittest.TestCase):
    def setUp(self):
        self.lab = Lab().__enter__()
        self.addCleanup(self.lab.__exit__, None, None, None)
        self.alice = self.lab.client("alice")
        self.bob = self.lab.client("bob")
        wait_for(lambda: names(self.alice) == names(self.bob) == {"alice", "bob"})

    def source(self, name="network.bin", size=32768):
        path = self.lab.path / name
        path.write_bytes((bytes(range(256)) * ((size + 255) // 256))[:size])
        return path

    def record(self, app, file_id):
        return next((item for item in app.state()["transfers"] if item["file_id"] == file_id), {"status": "pending"})

    def test_loss_delay_duplicate_reorder_recover(self):
        original = self.alice.file_handler.send_packet_fn
        seen = set()
        held = []
        timers = []

        def fault(packet, recipient):
            body = decode_secure_json(packet.payload)
            index = body.get("chunk_index") if body.get("kind") == FILE_CHUNK else None
            if index in (2, 3, 4, 5, 6) and index not in seen:
                seen.add(index)
                if index == 2:  # Drop the first copy only.
                    return
                if index == 3:
                    timer = threading.Timer(0.08, original, args=(packet, recipient))
                    timers.append(timer)
                    timer.start()
                    return
                if index == 4:
                    original(packet, recipient)  # Duplicate before completion.
                if index == 5:
                    held.append((packet, recipient))
                    return
                if index == 6:
                    original(packet, recipient)
                    original(*held.pop())  # Deliver 6 before 5.
                    return
            original(packet, recipient)

        self.alice.file_handler.send_packet_fn = fault
        source = self.source()
        file_id = self.alice.send_file("bob", source)
        try:
            wait_for(lambda: self.record(self.alice, file_id)["status"] == "done", timeout=20, description="UDP retry recovery")
            wait_for(lambda: self.record(self.bob, file_id)["status"] == "completed")
            self.assertEqual(seen, {2, 3, 4, 5, 6})
            self.assertEqual((self.lab.path / "downloads_bob" / source.name).read_bytes(), source.read_bytes())
        finally:
            for timer in timers:
                timer.join(timeout=1)

    def test_interrupted_transfer_sender_fails_and_chat_survives(self):
        original = self.alice.file_handler.send_packet_fn

        def interrupt(packet, recipient):
            body = decode_secure_json(packet.payload)
            if body.get("kind") == FILE_CHUNK and body["chunk_index"] >= 8:
                return  # Permanent interruption after one complete window.
            original(packet, recipient)

        self.alice.file_handler.send_packet_fn = interrupt
        file_id = self.alice.send_file("bob", self.source())
        wait_for(lambda: self.record(self.alice, file_id)["status"].startswith("failed:"), timeout=15, description="retry exhaustion")
        self.assertLess(self.record(self.alice, file_id)["progress"], 100)
        self.assertFalse((self.lab.path / "downloads_bob" / "network.bin").exists())
        self.alice.send_message("bob", "chat works despite file failure")
        wait_for(lambda: any(m["text"] == "chat works despite file failure" for m in self.bob.messages))

    def test_unavailable_recipient_rejected_by_existing_client(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.alice.send_file("missing", self.source())
        self.assertEqual(self.alice.state()["transfers"], [])

    # @unittest.expectedFailure
    def test_upstream_final_ack_loss_should_recover(self):
        """Known Role 3 defect: completed receiver ignores retransmit without ACK."""
        original = self.bob.file_handler.send_packet_fn
        dropped = []

        def lose_final_ack(packet, recipient):
            body = decode_secure_json(packet.payload)
            if body.get("kind") == "ACK" and body.get("chunk_index") == 0 and not dropped:
                dropped.append(True)
                return
            original(packet, recipient)

        self.bob.file_handler.send_packet_fn = lose_final_ack
        file_id = self.alice.send_file("bob", self.source("one-chunk.bin", 100))
        wait_for(lambda: self.record(self.bob, file_id)["status"] == "completed")
        wait_for(lambda: self.record(self.alice, file_id)["status"] != "sending", timeout=15)
        print("Known final-ACK defect:", self.record(self.alice, file_id)["status"])
        self.assertEqual(self.record(self.alice, file_id)["status"], "done")

    # @unittest.expectedFailure
    def test_upstream_receiver_timeout_should_reach_state(self):
        """Known Role 3 contract gap; accelerate cleanup, not network timeout."""
        original = self.alice.file_handler.send_packet_fn

        def no_chunks(packet, recipient):
            if decode_secure_json(packet.payload).get("kind") != FILE_CHUNK:
                original(packet, recipient)

        self.alice.file_handler.send_packet_fn = no_chunks
        file_id = self.alice.send_file("bob", self.source())
        wait_for(lambda: bool(self.bob.state()["transfers"]))
        wait_for(lambda: self.record(self.alice, file_id)["status"].startswith("failed:"), timeout=15)
        expired = self.bob.file_handler.receiver.cleanup_expired(max_age=0)
        self.assertIn(file_id, expired)
        self.assertEqual(self.bob.file_handler.receiver.get_progress(file_id)["status"], "timeout")
        print("Known timeout-state gap:", self.record(self.bob, file_id)["status"])
        self.assertEqual(self.record(self.bob, file_id)["status"], "timeout")

    def test_meta_ack_allows_transfer_to_complete(self):
        """Receiver must ACK FILE_META so sender can finish."""
        file_id = self.alice.send_file("bob", self.source("meta-ack.bin", 200))
        wait_for(lambda: self.record(self.alice, file_id)["status"] == "done")
        wait_for(lambda: self.record(self.bob, file_id)["status"] == "completed")
        
if __name__ == "__main__":
    unittest.main()
