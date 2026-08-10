"""Retry + rate-limit helpers (deterministic; no real sleeping)."""

from __future__ import annotations

import pytest

from ingestion.common.rate_limit import RateLimiter
from ingestion.common.retry import with_retry


# --------------------------------------------------------------------------- retry

def test_retry_succeeds_first_try():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    sleeps = []
    assert with_retry(fn, retries=3, sleep=sleeps.append) == "ok"
    assert calls["n"] == 1
    assert sleeps == []


def test_retry_retries_then_succeeds():
    state = {"n": 0}

    def fn():
        state["n"] += 1
        if state["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    sleeps = []
    assert with_retry(
        fn, retries=5, base_delay=0.1, exceptions=(ConnectionError,), sleep=sleeps.append
    ) == "ok"
    assert state["n"] == 3
    assert len(sleeps) == 2
    # exponential: 0.1, 0.2
    assert sleeps[0] == pytest.approx(0.1)
    assert sleeps[1] == pytest.approx(0.2)


def test_retry_exhausts_and_reraises():
    def fn():
        raise TimeoutError("nope")

    sleeps = []
    with pytest.raises(TimeoutError):
        with_retry(fn, retries=2, sleep=sleeps.append)
    assert len(sleeps) == 2  # retried twice


def test_retry_ignores_non_matching_exceptions():
    def fn():
        raise ValueError("not retriable")

    sleeps = []
    with pytest.raises(ValueError):
        with_retry(fn, retries=3, exceptions=(ConnectionError,), sleep=sleeps.append)
    assert sleeps == []


# --------------------------------------------------------------------------- rate limit

def test_rate_limiter_first_call_never_waits():
    sleeps = []
    t = {"v": 100.0}
    rl = RateLimiter(0.5, clock=lambda: t["v"], sleep=sleeps.append)
    assert rl.acquire() == 0.0
    assert sleeps == []


def test_rate_limiter_waits_when_too_soon():
    sleeps = []
    t = {"v": 100.0}
    rl = RateLimiter(1.0, clock=lambda: t["v"], sleep=sleeps.append)
    rl.acquire()           # t=100
    t["v"] = 100.3          # only 0.3s later
    waited = rl.acquire()
    assert waited == pytest.approx(0.7)
    assert sleeps == [pytest.approx(0.7)]


def test_rate_limiter_no_wait_after_interval_elapsed():
    sleeps = []
    t = {"v": 100.0}
    rl = RateLimiter(1.0, clock=lambda: t["v"], sleep=sleeps.append)
    rl.acquire()
    t["v"] = 101.5          # > interval
    assert rl.acquire() == 0.0
    assert sleeps == []


def test_rate_limiter_zero_interval_is_passthrough():
    sleeps = []
    t = {"v": 0.0}
    rl = RateLimiter(0.0, clock=lambda: t["v"], sleep=sleeps.append)
    assert rl.acquire() == 0.0
    assert rl.acquire() == 0.0
    assert sleeps == []
