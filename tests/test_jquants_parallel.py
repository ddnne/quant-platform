"""Tests for date-grid expansion and parallel job execution."""

from __future__ import annotations

import threading
import time
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
    """Under concurrency, min interval is respected globally."""
    times: list[float] = []
    lock = threading.Lock()
    rl = RateLimiter(0.05)

    def worker():
        for _ in range(3):
            rl.acquire()
            with lock:
                times.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    times.sort()
    # 12 acquires with 0.05s spacing → at least ~0.55s wall if serial slots
    assert times[-1] - times[0] >= 0.05 * (len(times) - 1) * 0.85  # slack
    # gaps between consecutive reserved times should be ~min_interval
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    assert min(gaps) >= 0.03  # allow scheduler jitter


def test_run_parallel_faster_than_serial_with_rtt():
    """With RTT simulation, parallel wall time < serial estimate."""
    http = _FakeHttp()
    http.delay = 0.05
    # No rate limit so only RTT matters for the comparison.
    client = JQuantsClient(http, api_key="", rate_limiter=RateLimiter(0.0))
    jobs = [
        FetchJob("equities_bars_daily", {"from": "2020-01-01", "to": "2020-01-31"}),
        FetchJob("equities_bars_daily", {"from": "2020-02-01", "to": "2020-02-28"}),
        FetchJob("markets_calendar", {"from": "2020-01-01", "to": "2020-01-31"}),
        FetchJob("markets_calendar", {"from": "2020-02-01", "to": "2020-02-28"}),
    ]
    t0 = time.monotonic()
    results = run_parallel(client, jobs, max_workers=4)
    wall = time.monotonic() - t0
    assert all(r.ok for r in results)
    assert len(http.calls) == 4
    # Serial would be ~4 * 0.05 = 0.20s; parallel should be clearly under that.
    assert wall < 0.15


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
