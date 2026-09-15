"""A real token bucket, replacing the blind fixed-range sleeps that used to
gate LinkedIn traffic.

The old approach — `time.sleep(random.uniform(8, 16))` before every call —
paces requests at a flat rate regardless of how much headroom actually
exists, and does nothing to smooth out bursts across concurrent callers. A
token bucket refills continuously at a target rate and lets `acquire()`
callers through as soon as a token is available, so pacing stays close to
the target rate under concurrency instead of stacking sleeps.
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe token bucket. `acquire()` blocks the calling thread (not
    the asyncio event loop — call it from a worker thread, as the LinkedIn
    adapter already does) until a token is available.
    """

    def __init__(self, rate_per_min: float, burst: int | None = None):
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be positive")
        self._rate_per_sec = rate_per_min / 60.0
        self._capacity = float(burst if burst is not None else max(1, round(rate_per_min)))
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self._rate_per_sec
            time.sleep(wait)
