"""Byte-stream ordering and a CUBIC congestion window for the UDP application.

These primitives have no file names, encryption, JSON, socket ownership or global
stream lock. Application code authenticates frames and supplies per-stream chunk
indices; those indices are not the packet header's wrapping 16-bit sequence.

CubicWindow implements the window equations and timeout response of RFC 9438
sections 4.2-4.8: https://www.rfc-editor.org/rfc/rfc9438.html . This bounded lab
controller is not a complete TCP/QUIC stack: ACK validation, selective retries,
Karn RTT sampling and loss-episode grouping belong to the caller. It has no ECN,
HyStart++, BBR, internet fairness or throughput-conformance claim.
"""
from __future__ import annotations

import asyncio
from collections import deque
import math
import threading
import time
from typing import Callable


class CubicWindow:
    """ACK-clocked window, measured in segments; owned by one sending worker."""

    C = 0.4
    BETA = 0.7

    def __init__(self, initial_window: int = 2, max_window: int = 64,
                 initial_ssthresh: int = 8, clock: Callable[[], float] = time.monotonic):
        if not 1 <= initial_window <= max_window or max_window < 2 or initial_ssthresh < 2:
            raise ValueError("invalid CUBIC window limits")
        self.max_window = max_window
        self.cwnd = float(initial_window)
        self.ssthresh = float(min(initial_ssthresh, max_window))
        self.w_max = self.cwnd
        self.cwnd_prior = self.cwnd
        self.w_est = self.cwnd
        self.srtt = 0.1
        self._sampled_rtt = False
        self._clock = clock
        self._epoch: float | None = None
        self._last_ack: float | None = None
        self._k = 0.0
        self.loss_events = 0
        self.acked_segments = 0

    @property
    def window(self) -> int:
        return max(1, min(self.max_window, math.floor(self.cwnd)))

    def on_ack(self, rtt: float | None = None, segments: int = 1,
               app_limited: bool = False) -> None:
        """Only newly acknowledged data may call this; duplicates cannot grow cwnd.

        Pass rtt=None for retransmitted segments (Karn's ambiguity). Set
        app_limited when no application data was available during this interval;
        that interval must not accelerate the CUBIC epoch.
        """
        if type(segments) is not int or segments < 1:
            raise ValueError("segments must be a positive integer")
        now = self._clock()
        if rtt is not None:
            if not math.isfinite(rtt) or rtt <= 0:
                raise ValueError("rtt must be positive and finite")
            self.srtt = rtt if not self._sampled_rtt else 0.875*self.srtt + 0.125*rtt
            self._sampled_rtt = True
        self.acked_segments += segments
        if app_limited:
            if self._epoch is not None and self._last_ack is not None:
                self._epoch += max(0.0, now-self._last_ack)
            self._last_ack = now
            return
        self._last_ack = now
        for _ in range(segments):
            if self.cwnd < self.ssthresh:
                self.cwnd = min(self.max_window, self.cwnd+1.0)
                continue
            if self._epoch is None:
                self._epoch = now
                self.w_est = self.cwnd
                if self.w_max < self.cwnd:
                    self.w_max = self.cwnd
                self._k = math.cbrt((self.w_max-self.cwnd)/self.C)
            elapsed = max(0.0, now-self._epoch)
            cubic_now = self.C*(elapsed-self._k)**3+self.w_max
            target = self.C*(elapsed+self.srtt-self._k)**3+self.w_max
            target = min(1.5*self.cwnd, max(self.cwnd, target))
            alpha = 1.0 if self.w_est >= self.cwnd_prior else 3*(1-self.BETA)/(1+self.BETA)
            self.w_est += alpha/self.cwnd
            if cubic_now < self.w_est:
                self.cwnd = max(self.cwnd, self.w_est)
            else:
                self.cwnd += (target-self.cwnd)/self.cwnd
            self.cwnd = min(float(self.max_window), self.cwnd)

    def on_loss(self, timeout: bool = False) -> None:
        """Call once per loss episode, not once for each missing chunk in a flight."""
        prior = self.cwnd
        self.cwnd_prior = prior
        self.w_max = prior*(1+self.BETA)/2 if prior < self.w_max else prior
        self.ssthresh = max(2.0, prior*self.BETA)
        self.cwnd = 1.0 if timeout else self.ssthresh
        self._epoch = None
        self.w_est = self.cwnd
        self.loss_events += 1

    def snapshot(self) -> dict:
        return {"algorithm": "CUBIC", "cwnd": round(self.cwnd, 6),
                "window": self.window, "ssthresh": round(self.ssthresh, 6),
                "srtt": self.srtt, "loss_events": self.loss_events,
                "acked_segments": self.acked_segments, "max_window": self.max_window}


class OrderedByteStream:
    """Thread-safe producer / asynchronous consumer, bounded per logical stream.

    read() returns the next contiguous nonempty chunk, or b'' after successful
    completion. finish(total_chunks) supplies EOF; fail(error) aborts readers and
    releases buffered bytes. Consumer cancellation removes its waiter immediately
    and never leaves a blocking worker thread behind. Bytes read before finish are
    provisional: application integrity checks must succeed before finish is called.

    Authentication and validation of repeated, already-delivered chunks belong to
    the application. This layer rejects conflicting duplicates still buffered and
    ignores old indices rather than retaining unbounded duplicate history.
    """

    def __init__(self, max_buffer_bytes: int = 100*1024*1024, max_chunks: int = 200000):
        if max_buffer_bytes < 0 or max_chunks < 1:
            raise ValueError("invalid stream capacity")
        self.max_buffer_bytes = max_buffer_bytes
        self.max_chunks = max_chunks
        self._pending: dict[int, bytes] = {}
        self._ready: deque[bytes] = deque()
        self._next = 0
        self._total: int | None = None
        self._buffered = 0
        self._error: Exception | None = None
        self._lock = threading.Lock()
        self._waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Future]] = set()

    @staticmethod
    def _resolve(future: asyncio.Future) -> None:
        if not future.done():
            future.set_result(None)

    def _wake_locked(self) -> None:
        waiters, self._waiters = self._waiters, set()
        for loop, future in waiters:
            try:
                loop.call_soon_threadsafe(self._resolve, future)
            except RuntimeError:
                pass  # The consumer's event loop was closed/cancelled.

    def feed(self, index: int, data: bytes) -> bool:
        if type(index) is not int or not 0 <= index < self.max_chunks:
            raise ValueError("stream index out of range")
        if not isinstance(data, bytes):
            raise TypeError("stream data must be bytes")
        with self._lock:
            if self._error:
                raise self._error
            if self._total is not None and index >= self._total:
                raise ValueError("chunk beyond stream EOF")
            if index < self._next:
                return False
            if index in self._pending:
                if self._pending[index] != data:
                    raise ValueError("conflicting buffered stream chunk")
                return False
            if self._buffered+len(data) > self.max_buffer_bytes:
                raise BufferError("stream buffer capacity exceeded")
            self._pending[index] = data
            self._buffered += len(data)
            while self._next in self._pending:
                chunk = self._pending.pop(self._next)
                if chunk:
                    self._ready.append(chunk)
                self._next += 1
            self._wake_locked()
            return True

    def finish(self, total_chunks: int) -> None:
        if type(total_chunks) is not int or not 0 <= total_chunks <= self.max_chunks:
            raise ValueError("invalid stream length")
        with self._lock:
            if self._error:
                raise self._error
            if self._total is not None and self._total != total_chunks:
                raise ValueError("conflicting stream EOF")
            if self._next > total_chunks or any(i >= total_chunks for i in self._pending):
                raise ValueError("stream EOF truncates received data")
            self._total = total_chunks
            self._wake_locked()

    def fail(self, error: Exception | str) -> None:
        with self._lock:
            if self._total is not None and self._next == self._total:
                return  # A successful terminal stream cannot later turn into failure.
            if self._error is None:
                self._error = error if isinstance(error, Exception) else OSError(error)
                self._pending.clear()
                self._ready.clear()
                self._buffered = 0
            self._wake_locked()

    async def read(self) -> bytes:
        while True:
            loop = asyncio.get_running_loop()
            with self._lock:
                if self._error:
                    raise self._error
                if self._ready:
                    chunk = self._ready.popleft()
                    self._buffered -= len(chunk)
                    return chunk
                if self._total is not None and self._next == self._total:
                    return b""
                future = loop.create_future()
                waiter = (loop, future)
                self._waiters.add(waiter)
            try:
                await future
            finally:
                with self._lock:
                    self._waiters.discard(waiter)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        data = await self.read()
        if not data:
            raise StopAsyncIteration
        return data

    def snapshot(self) -> dict:
        with self._lock:
            return {"next_index": self._next, "total_chunks": self._total,
                    "buffered_bytes": self._buffered, "pending_chunks": len(self._pending),
                    "waiters": len(self._waiters), "failed": self._error is not None,
                    "finished": self._total is not None and self._next == self._total}
