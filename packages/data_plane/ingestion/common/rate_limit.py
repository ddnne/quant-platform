"""Minimum-interval rate limiter (thread-safe).

The first call never waits. Subsequent calls wait just enough to keep calls
at least ``min_interval_seconds`` apart **globally** (shared across threads).

Sleep happens **outside** the lock so other threads can reserve subsequent
slots while one is sleeping — critical for overlapping I/O RTT under a shared
Premium budget (500 req/min).

``clock`` / ``sleep`` are injectable for fast, deterministic tests.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class RateLimiter:
    def __init__(
        self,
        min_interval_seconds: float = 0.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min = max(0.0, float(min_interval_seconds))
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def min_interval(self) -> float:
        return self._min

    def acquire(self) -> float:
        """Reserve the next slot; sleep if needed. Returns seconds waited."""
        if self._min <= 0:
            with self._lock:
                self._next_allowed = self._clock()
            return 0.0

        with self._lock:
            now = self._clock()
            if self._next_allowed is None or now >= self._next_allowed:
                # Slot is free now.
                self._next_allowed = now + self._min
                wait = 0.0
            else:
                # Reserve a future slot and sleep until then.
                wait = self._next_allowed - now
                self._next_allowed = self._next_allowed + self._min

        if wait > 0:
            self._sleep(wait)
        return wait
