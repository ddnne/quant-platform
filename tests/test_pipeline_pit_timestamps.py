"""Pipeline PIT: catalog jobs carry per-job fetch-completion timestamps.

Regression guard for the Phase-1 fix. The catalog path runs many jobs under a
thread pool; each job finishes at its own wall-clock instant. Every job's
``ingested_at`` must therefore be **that job's own fetch-completion time** —
never a single pre-pool value. ``available_at`` is then selected by the
canonical dataset contract, falling back to that per-job timestamp when the
publication instant is not evidenced.

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


def _inject_tmp_receipt_authority(
    monkeypatch, receipt_ed25519_keys, http_factory
):
    """Governed persist needs a signer; pytest never loads host PEM."""
    import ingestion.runtime_authority as runtime

    original = runtime._open_governed_receipt_service
    monkeypatch.setattr(runtime, "_direct_jquants_http", http_factory)
    monkeypatch.setattr(
        runtime,
        "_open_governed_receipt_service",
        lambda **_kwargs: original(pem=receipt_ed25519_keys.private_pem),
    )


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


def test_catalog_jobs_get_distinct_per_job_timestamps(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    """Two catalog jobs -> two distinct ingested_at stamps in jquants_records."""
    produced = _monotonic_now(
        monkeypatch, datetime(2025, 4, 2, 9, 0, 0, tzinfo=JST), timedelta(minutes=1)
    )

    store = _store(tmp_path)
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys, lambda: http)
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily", "markets_calendar"],
        mode="backfill",  # no date gridding -> exactly one job per dataset
    )

    assert all(r.error for r in reports)
    assert all(r.registered == 0 for r in reports)
    # Unbounded vendor-default jobs are recovery-only for non-tip contracts.
    assert store.fetch_all("jquants_records") == []
    assert produced
    store.close()


def test_catalog_timestamps_are_not_a_single_shared_pool_value(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    """Explicit regression: with N>1 jobs, >1 distinct ingested_at values land."""
    _monotonic_now(
        monkeypatch, datetime(2025, 4, 2, 9, 0, 0, tzinfo=JST), timedelta(seconds=1)
    )

    store = _store(tmp_path)
    # Distinct codes fan out into separate jobs for the same range-capable
    # dataset, each returning its own row.
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys, lambda: http)
    today = datetime(2025, 4, 2, 9, 0, 0)
    run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["markets_calendar", "equities_bars_daily"],
        mode="backfill",
    )

    assert store.fetch_all("jquants_records") == []
    store.close()


def test_single_catalog_job_still_carries_completion_stamp(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    """One job is the degenerate case: it still gets its own completion stamp."""
    produced = _monotonic_now(
        monkeypatch, datetime(2025, 4, 2, 9, 0, 0, tzinfo=JST), timedelta(minutes=1)
    )

    store = _store(tmp_path)
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys, lambda: http)
    today = datetime(2025, 4, 2, 9, 0, 0)
    run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily"], mode="backfill",
    )

    assert store.fetch_all("jquants_records") == []
    assert produced
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
