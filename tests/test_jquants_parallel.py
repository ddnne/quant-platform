"""Tests for date-grid expansion and parallel job execution."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from ingestion.common.rate_limit import RateLimiter
from ingestion.jquants.client import JQuantsClient
from ingestion.jquants.parallel import (
    expand_jobs,
    iter_date_windows,
    run_parallel,
    run_datasets_parallel,
    summarize_results,
    FetchJob,
)


class _FakeHttp:
    """Thread-safe fake: records call params; returns empty data pages."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._lock = threading.Lock()
        self.delay = 0.02  # simulate RTT

    def get(self, url: str, *, headers=None, params=None, **_kw):
        time.sleep(self.delay)
        with self._lock:
            self.calls.append((url, dict(params or {})))
        return _Resp({"data": [{"Date": "2020-01-01", "Code": "7203", "C": 1.0}]})


class _Resp:
    def __init__(self, body: dict):
        self.status = 200
        self._body = body

    @property
    def ok(self) -> bool:
        return True

    def json(self) -> Any:
        return self._body

    def text(self) -> str:
        return str(self._body)


def test_iter_date_windows_basic():
    wins = iter_date_windows("2020-01-01", "2020-02-15", chunk_days=30)
    assert wins == [
        ("2020-01-01", "2020-01-30"),
        ("2020-01-31", "2020-02-15"),
    ]


def test_iter_date_windows_single_day():
    assert iter_date_windows("2020-01-05", "2020-01-05", 30) == [
        ("2020-01-05", "2020-01-05")
    ]


def test_expand_jobs_grids_range_datasets():
    jobs = expand_jobs(
        ["equities_bars_daily", "markets_calendar"],
        from_date="2020-01-01",
        to_date="2020-03-01",
        chunk_days=30,
    )
    datasets = {j.dataset_id for j in jobs}
    assert datasets == {"equities_bars_daily", "markets_calendar"}
    # bars: date-or-code API → per-day date=
    bars = [j for j in jobs if j.dataset_id == "equities_bars_daily"]
    assert bars and all("date" in j.params for j in bars)
    # calendar: pure range → from/to windows
    cal = [j for j in jobs if j.dataset_id == "markets_calendar"]
    assert cal and all("from" in j.params and "to" in j.params for j in cal)


def test_expand_jobs_codes_fanout():
    jobs = expand_jobs(
        ["equities_bars_daily"],
        from_date="2020-01-01",
        to_date="2020-01-10",
        chunk_days=30,
        codes=["7203", "6758"],
    )
    codes = {j.params.get("code") for j in jobs}
    assert codes == {"7203", "6758"}


def test_expand_jobs_no_range_single():
    jobs = expand_jobs(["equities_master"])
    assert len(jobs) == 1
    assert jobs[0].dataset_id == "equities_master"


def test_thread_safe_rate_limiter_spacing():
    """Concurrent acquires share one global reservation schedule.

    Returned waits are reserved slot offsets, not vendor HTTP arrival
    times. A stalled worker after acquire returns can delay the actual
    request; this does not claim physical min-spacing of HTTP sends.
    Sleep runs outside the reservation lock, so later callers can reserve
    while earlier ones are still sleeping.
    """
    sleep_durations: list[float] = []
    rec_lock = threading.Lock()
    n_waiting = 0
    all_waiting = threading.Event()
    release = threading.Event()

    def sleep(duration: float) -> None:
        nonlocal n_waiting
        with rec_lock:
            sleep_durations.append(duration)
            n_waiting += 1
            if n_waiting >= 3:
                all_waiting.set()
        if not release.wait(timeout=5.0):
            raise TimeoutError("sleeping acquire was not released")

    rl = RateLimiter(0.05, clock=lambda: 0.0, sleep=sleep)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(rl.acquire) for _ in range(4)]
        try:
            entered = all_waiting.wait(timeout=5.0)
        finally:
            release.set()
        assert entered, "deadlock: waiting acquires never entered sleep"
        waits = [fut.result(timeout=5.0) for fut in futures]

    assert sorted(waits) == pytest.approx([0.0, 0.05, 0.10, 0.15])
    assert sorted(sleep_durations) == pytest.approx([0.05, 0.10, 0.15])
    # Reuse is okay: clock is still 0 and the release Event is already set.
    assert rl.acquire() == pytest.approx(0.20)
    assert sleep_durations[-1] == pytest.approx(0.20)


def test_run_parallel_faster_than_serial_with_rtt():
    """max_workers=4 overlaps HTTP gets; barrier is a deadlock guard.

    Serial execution cannot fill a 4-party barrier. This is not a wall-time
    oracle. Vendor params, client fetch, and the fake response path stay
    unchanged. Overlap is concurrent get invocation, not physical HTTP
    arrival spacing under RateLimiter.
    """

    class _BarrierHttp(_FakeHttp):
        def __init__(self) -> None:
            super().__init__()
            self.delay = 0.0
            self._barrier = threading.Barrier(4)

        def get(self, url: str, *, headers=None, params=None, **kw):
            self._barrier.wait(timeout=5.0)
            return super().get(url, headers=headers, params=params, **kw)

    http = _BarrierHttp()
    client = JQuantsClient(http, api_key="", rate_limiter=RateLimiter(0.0))
    jobs = [
        FetchJob("equities_bars_daily", {"from": "2020-01-01", "to": "2020-01-31"}),
        FetchJob("equities_bars_daily", {"from": "2020-02-01", "to": "2020-02-28"}),
        FetchJob("markets_calendar", {"from": "2020-01-01", "to": "2020-01-31"}),
        FetchJob("markets_calendar", {"from": "2020-02-01", "to": "2020-02-28"}),
    ]
    results = run_parallel(client, jobs, max_workers=4)
    assert all(r.ok for r in results)
    assert len(http.calls) == 4


def test_run_datasets_parallel_and_summary():
    http = _FakeHttp()
    http.delay = 0.0
    client = JQuantsClient(http, api_key="", rate_limiter=RateLimiter(0.0))
    results = run_datasets_parallel(
        client,
        ["equities_bars_daily"],
        from_date="2020-01-01",
        to_date="2020-02-15",
        chunk_days=30,
        max_workers=2,
    )
    summary = summarize_results(results)
    assert summary["ok"] == summary["jobs"]
    assert summary["rows"] == summary["jobs"]  # one row per fake page
    assert summary["errors"] == 0
