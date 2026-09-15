"""Tests for the token bucket that replaced blind random.uniform() sleeps."""
import threading
import time

import pytest

from sources.rate_limiter import TokenBucket


def test_first_acquire_is_immediate():
    bucket = TokenBucket(rate_per_min=60, burst=1)
    start = time.monotonic()
    bucket.acquire()
    assert time.monotonic() - start < 0.05


def test_exhausted_bucket_waits_roughly_the_refill_interval():
    # 60/min = 1 token/sec, burst of 1 -> second immediate call must wait ~1s.
    bucket = TokenBucket(rate_per_min=60, burst=1)
    bucket.acquire()
    start = time.monotonic()
    bucket.acquire()
    elapsed = time.monotonic() - start
    assert 0.8 <= elapsed <= 1.3


def test_burst_allows_immediate_back_to_back_calls_up_to_capacity():
    bucket = TokenBucket(rate_per_min=600, burst=5)
    start = time.monotonic()
    for _ in range(5):
        bucket.acquire()
    assert time.monotonic() - start < 0.1


def test_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate_per_min=0)


def test_thread_safe_under_concurrent_acquire():
    bucket = TokenBucket(rate_per_min=6000, burst=50)
    errors = []

    def worker():
        try:
            for _ in range(20):
                bucket.acquire()
        except Exception as e:  # pragma: no cover - failure path only
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    assert all(not t.is_alive() for t in threads)
