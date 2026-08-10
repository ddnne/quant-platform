"""Pipeline PIT: catalog jobs carry per-job fetch-completion timestamps.

Regression guard for the Phase-1 fix. The catalog path runs many jobs under a
thread pool; each job finishes at its own wall-clock instant. Every job's
``available_at`` / ``ingested_at`` default must therefore be **that job's own
fetch-completion time** — never a single pre-pool ``ingested`` value stamped
onto all jobs alike.

Offline: a canned HTTP double stands in for the transport, and an in-memory
SQLite store proves the timestamps that land in ``jquants_records``.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta

import pytest

from ingestion import pipeline
from ingestion.common.http import HttpResponse
from ingestion.common.timeutil import JST, to_iso
from ingestion.pipeline import run_jquants
from storage.sqlite_store import SqliteStore


class _CatalogHttp:
    """Returns canned ``data`` for any path."""

    name = "local"

    def __init__(self, rows):
        self._rows = rows

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        return HttpResponse(
            200,
            {"content-type": "application/json"},
            json.dumps({"data": self._rows}).encode("utf-8"),
            url,
        )


def _store(tmp_path):
    return SqliteStore(tmp_path / "t.sqlite")


def _monotonic_now(monkeypatch, start: datetime, step: timedelta):
    """Patch ``pipeline.now_iso`` to advance ``step`` on every call.

    Returns the list of produced strings in call order. ``itertools.count``'s
    ``next()`` is atomic under the GIL, so concurrent worker threads still each
    get a distinct, strictly increasing value — the per-job stamps can never
    collide even though real ``now_iso`` is only seconds-precision.
    """
    produced: list[str] = []
    counter = itertools.count()

    def _fake() -> str:
        s = to_iso(start + step * next(counter))
        produced.append(s)
        return s

    monkeypatch.setattr(pipeline, "now_iso", _fake)
    return produced


def test_catalog_jobs_get_distinct_per_job_timestamps(tmp_path, monkeypatch):
    """Two catalog jobs -> two distinct ingested_at stamps in jquants_records."""
    produced = _monotonic_now(
        monkeypatch, datetime(2025, 4, 2, 9, 0, 0, tzinfo=JST), timedelta(minutes=1)
    )

    store = _store(tmp_path)
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily", "markets_calendar"],
        mode="backfill",  # no date gridding -> exactly one job per dataset
    )

    ok_reports = [r for r in reports if not r.skipped and not r.error]
    assert len(ok_reports) == 2

    rows = store.fetch_all("jquants_records")
    assert len(rows) == 2  # distinct datasets -> distinct PKs -> both persist

    stamps = {row["ingested_at"] for row in rows}
    assert len(stamps) == 2, (
        f"catalog jobs must carry per-job timestamps, got a shared {sorted(stamps)}"
    )
    # Every stamp actually came from the patched clock (no stale pre-pool value).
    assert stamps.issubset(set(produced))
    # available_at defaults to each job's own ingested_at (no explicit override).
    for row in rows:
        assert row["available_at"] == row["ingested_at"]
    store.close()


def test_catalog_timestamps_are_not_a_single_shared_pool_value(tmp_path, monkeypatch):
    """Explicit regression: with N>1 jobs, >1 distinct ingested_at values land."""
    _monotonic_now(
        monkeypatch, datetime(2025, 4, 2, 9, 0, 0, tzinfo=JST), timedelta(seconds=1)
    )

    store = _store(tmp_path)
    # Distinct codes fan out into separate jobs for the same range-capable
    # dataset, each returning its own row.
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    today = datetime(2025, 4, 2, 9, 0, 0)
    run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["markets_calendar", "equities_bars_daily"],
        mode="backfill",
    )

    rows = store.fetch_all("jquants_records")
    assert len(rows) == 2
    ingested = [row["ingested_at"] for row in rows]
    # The bug stamped every job with one value; assert that is no longer so.
    assert len(set(ingested)) == len(ingested) == 2
    store.close()


def test_single_catalog_job_still_carries_completion_stamp(tmp_path, monkeypatch):
    """One job is the degenerate case: it still gets its own completion stamp."""
    produced = _monotonic_now(
        monkeypatch, datetime(2025, 4, 2, 9, 0, 0, tzinfo=JST), timedelta(minutes=1)
    )

    store = _store(tmp_path)
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    today = datetime(2025, 4, 2, 9, 0, 0)
    run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily"], mode="backfill",
    )

    rows = store.fetch_all("jquants_records")
    assert len(rows) == 1
    # The persisted stamp is one produced by the per-job completion capture,
    # not the pre-pool call that happened before the fetch pool started.
    assert rows[0]["ingested_at"] in produced
    assert rows[0]["available_at"] == rows[0]["ingested_at"]
    store.close()


def test_catalog_raw_partitions_by_completion_day_not_process_start(
    tmp_path, monkeypatch
):
    """Raw bytes land in the yyyy/mm/dd of the job's fetch-completion time.

    A run that starts just before midnight (``today`` = 2025-04-02 23:58) but
    whose job completes after midnight (completion stamp on 2025-04-03) must file
    its raw under ``2025/04/03`` — the per-job completion day — not the
    process-start day ``2025/04/02``. Regression for the save_raw partition
    using ``today`` instead of the per-job completion timestamp.
    """
    # Patched clock: every now_iso() call lands on the calendar day AFTER the
    # process-start ``today`` the CLI passed in (a midnight-spanning completion).
    _monotonic_now(
        monkeypatch,
        datetime(2025, 4, 3, 0, 5, 0, tzinfo=JST),
        timedelta(minutes=1),
    )

    store = _store(tmp_path)
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    today = datetime(2025, 4, 2, 23, 58, 0)  # process start: just before midnight
    run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily"], mode="backfill",  # exactly one job
    )

    # Raw must sit under the COMPLETION day, not the process-start day.
    assert not list((tmp_path / "raw" / "jquants" / "2025" / "04" / "02").glob("*.json"))
    matches = list((tmp_path / "raw" / "jquants" / "2025" / "04" / "03").glob("*.json"))
    assert matches and matches[0].exists(), (
        "raw must partition by the per-job completion date, not process-start today"
    )
    store.close()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
