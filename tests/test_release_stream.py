"""Real UDP and async lifecycle checks for the byte transport primitives."""
import asyncio
from collections import Counter
import socket
import threading
import time
import unittest

from protocol import Packet, MSG_DATA, MSG_ACK, MSG_EOF, STATUS_OK, encode_packet, decode_packet
from stream_transport import CubicWindow, OrderedByteStream
from udp_streamer import UDPStreamSender, UDPStreamReceiver, CHUNK_SIZE


def udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.settimeout(.1)
    return sock


class SocketAdapter:
    def __init__(self, sock, send):
        self.sock, self.send = sock, send

    def sendto(self, data, addr):
        return self.send(data, addr)

    def recvfrom(self, size):
        return self.sock.recvfrom(size)

    def settimeout(self, value):
        return self.sock.settimeout(value)

    def gettimeout(self):
        return self.sock.gettimeout()


class ReleaseStreamTests(unittest.TestCase):
    def transfer(self, data, faults=False):
        sender_sock, receiver_sock = udp(), udp()
        before_eof = threading.Event()
        sent, replies = Counter(), Counter()
        errors, read_chunks = [], []
        eof_index = (len(data)+CHUNK_SIZE-1)//CHUNK_SIZE

        def send(raw, addr):
            packet = decode_packet(raw)
            sent[packet.seq_no] += 1
            if packet.msg_type == MSG_EOF and data:
                if not before_eof.wait(3):
                    raise OSError('async consumer did not receive bytes before EOF')
            if faults and packet.msg_type == MSG_DATA and packet.seq_no == 1 and sent[1] == 1:
                return len(raw)  # A genuine missing byte range while later data arrives.
            result = sender_sock.sendto(raw, addr)
            if faults and packet.seq_no == 2 and sent[2] == 1:
                sender_sock.sendto(raw, addr)
            return result

        def reply(raw, addr):
            packet = decode_packet(raw)
            replies[packet.seq_no] += 1
            if faults and packet.seq_no == eof_index and replies[eof_index] == 1:
                return len(raw)
            return receiver_sock.sendto(raw, addr)

        receiver = UDPStreamReceiver(SocketAdapter(receiver_sock, reply))
        sender = UDPStreamSender(SocketAdapter(sender_sock, send), receiver_sock.getsockname())
        stop = threading.Event()

        def receive():
            while not stop.is_set():
                try:
                    raw, addr = receiver_sock.recvfrom(2048)
                    receiver.handle_raw(raw, addr)
                except socket.timeout:
                    continue
                except OSError:
                    break
                except Exception as exc:
                    errors.append(repr(exc))
                    break

        async def consume():
            while True:
                chunk = await asyncio.wait_for(receiver.read(), timeout=8)
                if not chunk:
                    return
                read_chunks.append(chunk)
                if receiver.total_chunks is None:
                    before_eof.set()

        def consumer():
            try:
                asyncio.run(consume())
            except Exception as exc:
                errors.append(repr(exc))

        workers = [threading.Thread(target=receive), threading.Thread(target=consumer)]
        for thread in workers:
            thread.start()
        try:
            self.assertTrue(sender.send_data(data, timeout=8))
            workers[1].join(9)
            self.assertFalse(workers[1].is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(receiver.get_data(), data)
            self.assertEqual(b''.join(read_chunks), data)
            self.assertTrue(receiver.is_complete())
            self.assertTrue(sender.is_finished)
            self.assertEqual(sender_sock.gettimeout(), .1)
            if data:
                self.assertTrue(before_eof.is_set())
            if faults:
                self.assertGreater(sent[1], 1)
                self.assertGreater(replies[eof_index], 1)
                self.assertGreater(receiver.stats['out_of_order'], 0)
                self.assertGreater(receiver.stats['duplicate'], 0)
                self.assertGreater(sender.get_stats()['congestion']['loss_events'], 0)
                self.assertEqual(sender.get_stats()['acked'], eof_index+1)
                # Acknowledged data0 is never retransmitted: selective retry.
                self.assertEqual(sent[0], 1)
        finally:
            stop.set()
            sender_sock.close()
            receiver_sock.close()
            receiver.stream.fail(OSError('test cleanup'))
            for thread in workers:
                thread.join(2)

    def test_real_udp_loss_duplicate_order_async_and_final_ack_recovery(self):
        self.transfer(bytes(range(256))*30, faults=True)

    def test_empty_and_literal_end_payload_are_byte_exact(self):
        for data in (b'', b'__END__', b'x'*700+b'__END__'):
            with self.subTest(bytes=len(data)):
                self.transfer(data)

    def test_independent_udp_stream_does_not_wait_for_another_stream_gap(self):
        async def scenario():
            sockets = [udp() for _ in range(4)]
            a, b = UDPStreamReceiver(sockets[0]), UDPStreamReceiver(sockets[1])
            try:
                pending = asyncio.create_task(a.read())
                for source, target, packet in (
                    (sockets[2], sockets[0], Packet(MSG_DATA, seq_no=1, payload=b'later')),
                    (sockets[3], sockets[1], Packet(MSG_DATA, seq_no=0, payload=b'independent')),
                    (sockets[3], sockets[1], Packet(MSG_EOF, seq_no=1)),
                ):
                    source.sendto(encode_packet(packet), target.getsockname())
                    raw, addr = target.recvfrom(2048)
                    (a if target is sockets[0] else b).handle_raw(raw, addr)
                self.assertEqual(await asyncio.wait_for(b.read(), 1), b'independent')
                self.assertEqual(await b.read(), b'')
                self.assertFalse(pending.done())
                a.stream.fail(OSError('missing range cancelled'))
                with self.assertRaisesRegex(OSError, 'cancelled'):
                    await pending
            finally:
                for sock in sockets:
                    sock.close()
        asyncio.run(scenario())

    def test_invalid_eof_duplicate_and_other_peer_are_not_acknowledged(self):
        a, b, alien = udp(), udp(), udp()
        receiver = UDPStreamReceiver(b)
        def deliver(source, packet):
            source.sendto(encode_packet(packet), b.getsockname())
            raw, addr = b.recvfrom(2048)
            return receiver.handle_raw(raw, addr)
        try:
            deliver(a, Packet(MSG_DATA, seq_no=1, payload=b'one'))
            self.assertEqual(decode_packet(a.recvfrom(2048)[0]).seq_no, 1)
            for source, packet in (
                (a, Packet(MSG_EOF, seq_no=1)),
                (a, Packet(MSG_DATA, seq_no=1, payload=b'changed')),
                (alien, Packet(MSG_DATA, seq_no=0, payload=b'zero')),
            ):
                self.assertFalse(deliver(source, packet))
                with self.assertRaises(socket.timeout):
                    source.recvfrom(2048)
            deliver(a, Packet(MSG_DATA, seq_no=0, payload=b'zero'))
            a.recvfrom(2048)
            deliver(a, Packet(MSG_EOF, seq_no=2))
            a.recvfrom(2048)
            self.assertEqual(receiver.get_data(), b'zeroone')
            self.assertTrue(receiver.is_complete())
        finally:
            a.close(); b.close(); alien.close()

    def test_socket_send_error_cannot_report_success(self):
        a, b = udp(), udp()
        a.close()
        try:
            sender = UDPStreamSender(a, b.getsockname())
            self.assertFalse(sender.send_data(b'not sent', timeout=.5))
            self.assertFalse(sender.is_finished)
            self.assertEqual(sender.stats['acked'], 0)
        finally:
            b.close()

    def test_wrong_peer_and_malformed_ack_cannot_complete_sender(self):
        a, b, alien = udp(), udp(), udp()
        sender = UDPStreamSender(a, b.getsockname())
        result = []
        worker = threading.Thread(target=lambda: result.append(sender.send_data(b'bytes', timeout=.3)))
        worker.start()
        try:
            raw, address = b.recvfrom(2048)
            self.assertEqual(decode_packet(raw).seq_no, 0)
            for seq in (0, 1):
                alien.sendto(encode_packet(Packet(MSG_ACK, STATUS_OK, seq)), address)
                b.sendto(encode_packet(Packet(MSG_ACK, STATUS_OK, seq, b'invalid')), address)
                b.sendto(encode_packet(Packet(MSG_ACK, 2, seq)), address)
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [False])
            self.assertEqual(sender.stats['acked'], 0)
            self.assertFalse(sender.is_finished)
        finally:
            a.close(); b.close(); alien.close()
            worker.join(2)

    def test_sequence_capacity_rejects_before_sending(self):
        a, b = udp(), udp()
        try:
            sender = UDPStreamSender(a, b.getsockname())
            # Avoid allocating45MiB; exercise the declared logical sequence bound.
            sender._split_chunks = lambda data: [b'x']*65536
            with self.assertRaisesRegex(ValueError, '16-bit'):
                sender.send_data(b'x')
            with self.assertRaises(socket.timeout):
                b.recvfrom(2048)
        finally:
            a.close(); b.close()


class ReleaseByteStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordering_eof_and_conflicting_buffered_duplicate(self):
        stream = OrderedByteStream(20, 5)
        stream.feed(1, b'b')
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            stream.feed(1, b'changed')
        stream.finish(2)
        task = asyncio.create_task(stream.read())
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        stream.feed(0, b'a')
        self.assertEqual(await task, b'a')
        self.assertEqual(await stream.read(), b'b')
        self.assertEqual(await stream.read(), b'')
        self.assertEqual(stream.snapshot()['buffered_bytes'], 0)

    async def test_cancelled_reader_removes_waiter_and_does_not_consume(self):
        stream = OrderedByteStream(8, 2)
        task = asyncio.create_task(stream.read())
        await asyncio.sleep(0)
        self.assertEqual(stream.snapshot()['waiters'], 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(stream.snapshot()['waiters'], 0)
        stream.feed(0, b'abc')
        stream.finish(1)
        self.assertEqual(await stream.read(), b'abc')
        self.assertEqual(await stream.read(), b'')

    async def test_capacity_failure_and_terminal_state(self):
        stream = OrderedByteStream(3, 4)
        stream.feed(2, b'abc')
        with self.assertRaises(BufferError):
            stream.feed(0, b'd')
        self.assertEqual(stream.snapshot()['buffered_bytes'], 3)
        pending = asyncio.create_task(stream.read())
        await asyncio.sleep(0)
        stream.fail(OSError('integrity failure'))
        with self.assertRaisesRegex(OSError, 'integrity'):
            await pending
        self.assertEqual(stream.snapshot()['buffered_bytes'], 0)
        with self.assertRaises(OSError):
            stream.finish(3)
        complete = OrderedByteStream()
        complete.finish(0)
        complete.fail(OSError('late failure'))
        self.assertEqual(await complete.read(), b'')

    async def test_logical_indices_are_not_limited_by_packet_header_wrap(self):
        stream = OrderedByteStream(2, 70000)
        for index in range(65538):
            stream.feed(index, b'x')
            self.assertEqual(await stream.read(), b'x')
        stream.finish(65538)
        self.assertEqual(await stream.read(), b'')


class ReleaseCubicTests(unittest.TestCase):
    def test_growth_loss_recovery_and_idle_cap(self):
        now = [0.0]
        cc = CubicWindow(clock=lambda: now[0], max_window=32)
        for _ in range(250):
            now[0] += .02
            cc.on_ack(.02)
        peak = cc.cwnd
        self.assertGreater(peak, 8)
        self.assertLessEqual(peak, 32)
        cc.on_loss()
        self.assertLess(cc.cwnd, peak)
        self.assertGreaterEqual(cc.cwnd, 2)
        for _ in range(40):
            now[0] += .02
            cc.on_ack(.02)
        before_idle = cc.cwnd
        now[0] += 1000
        cc.on_ack(.02, app_limited=True)
        self.assertEqual(cc.cwnd, before_idle)
        now[0] += .02
        cc.on_ack(.02)
        self.assertLess(cc.cwnd, before_idle+1)
        cc.on_loss(timeout=True)
        self.assertEqual(cc.window, 1)
        for _ in range(8):
            now[0] += .02
            cc.on_ack(None)
        self.assertGreater(cc.window, 1)
        self.assertEqual(cc.loss_events, 2)

    def test_invalid_measurements_are_rejected(self):
        cc = CubicWindow()
        for rtt in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                cc.on_ack(rtt)
        with self.assertRaises(ValueError):
            cc.on_ack(segments=0)


if __name__ == '__main__':
    unittest.main()
