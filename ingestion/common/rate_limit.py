"""Simple minimum-interval rate limiter.

The first call never waits. Subsequent calls wait just enough to keep calls
at least ``min_interval_seconds`` apart. ``clock`` / ``sleep`` are injectable
for fast, deterministic tests.
"""

from __future__ import annotations

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
        self._last: Optional[float] = None

    @property
    def min_interval(self) -> float:
        return self._min

    def acquire(self) -> float:
        """Block (via injected sleep) until enough time elapsed. Returns wait."""
        if self._min <= 0:
            self._last = self._clock()
            return 0.0
        now = self._clock()
        waited = 0.0
        if self._last is not None:
            elapsed = now - self._last
            if elapsed < self._min:
                wait = self._min - elapsed
                self._sleep(wait)
                waited = wait
        self._last = self._clock()
        return waited
