"""Retry with deterministic exponential backoff.

``sleep`` is injectable so tests run without real delays. Jitter is opt-in
via a ``jitter`` callable to keep default behaviour deterministic.
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Tuple, Type


def with_retry(
    fn: Callable,
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    jitter: Optional[Callable[[float, int], float]] = None,
    logger=None,
):
    """Call ``fn`` up to ``retries + 1`` times.

    Retries only on ``exceptions``. Backoff doubles each attempt, capped at
    ``max_delay``; optional ``jitter(delay, attempt)`` may perturb it.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except exceptions as exc:  # noqa: PERF203 - intentional
            attempt += 1
            if attempt > retries:
                if logger is not None:
                    logger.warning("retry exhausted after %d attempts: %s", attempt, exc)
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if jitter is not None:
                delay = max(0.0, jitter(delay, attempt))
            if logger is not None:
                logger.debug("retry %d in %.2fs: %s", attempt, delay, exc)
            sleep(delay)
