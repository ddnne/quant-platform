"""Phase 3.5 — local sync script behavior.

Exit 2 when no URL/config is available (never touch the network). Require a
real worker URL — the secrets-proxy worker has no /v1/export/d1. Offline
paths only; live smokes are ``@pytest.mark.live``.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import pit
from storage.sqlite_store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]
_SYNC = _REPO / "scripts" / "sync_d1_to_sqlite.py"


def test_sync_script_exists():
    assert _SYNC.exists()


def test_sync_exits_2_when_no_url(tmp_path, sync_module, monkeypatch):
    """Offline-safe: no URL → exit 2, no network touch."""
    db = tmp_path / "x.sqlite"
    monkeypatch.delenv("INGESTION_PREMIUM_URL", raising=False)
    monkeypatch.delenv("INGESTION_PROXY_TOKEN", raising=False)

    rc = sync_module.main([
        "--db", str(db),
        "--url", "",
    ])
    assert rc == 2
    assert not db.exists()


def test_sync_default_tables_include_pit_tables(sync_module):
    """The default table set covers every PIT fact table."""
    for t in (
        "jquants_records",
        "jquants_daily_bars",
        "jquants_listed_info",
        "jquants_market_calendar",
    ):
        assert t in sync_module.DEFAULT_TABLES
    assert "coverage_segments" in sync_module.DEFAULT_TABLES
    assert "collection_receipts" in sync_module.DEFAULT_TABLES


def test_sync_preserves_nullable_collection_receipt_evidence(tmp_path, sync_module):
    path = tmp_path / "receipt-sync.sqlite"
    store = SqliteStore(path)
    receipt = {
        "source": "jquants",
        "dataset": "fins_summary",
        "segment_id": "2025-01",
        "segment_start": "2025-01-01",
        "segment_end": "2025-01-31",
        "expected_scope": '{"expected_frequency":"event_driven"}',
        "expected_items": None,
        "observed_items": 0,
        "raw_page_count": 1,
        "raw_row_count": 0,
        "structured_row_count": 0,
        "pagination_exhausted": 1,
        "digests_json": '{"raw":"sha256:test"}',
        "run_id": 7,
        "status": "SUCCESS",
        "error": None,
        "checked_at": "2025-02-01T00:00:00Z",
    }

    assert sync_module._sync_one(store, "collection_receipts", [receipt]) == (1, 1)
    saved = store.fetch_all("collection_receipts")
    assert saved[0]["expected_items"] is None
    assert saved[0]["error"] is None
    assert saved[0]["pagination_exhausted"] == 1
    store.close()


def test_sync_preserves_request_planned_coverage_inventory(tmp_path, sync_module):
    store = SqliteStore(tmp_path / "segment-sync.sqlite")
    segment = {
        "source": "jquants",
        "dataset": "equities_bars_daily",
        "segment_id": "2025-01",
        "policy_version": "collection-coverage/v2",
        "segment_start": "2025-01-01",
        "segment_end": "2025-01-31",
        "expected_scope": '{"expected_frequency":"trading_day"}',
        "expected_items": 31,
        "status": "UNKNOWN",
        "receipt_run_id": None,
        "evaluated_at": "2025-01-01T00:00:00Z",
        "detail_json": '{"expected_item_unit":"source_query"}',
    }

    assert sync_module._sync_one(store, "coverage_segments", [segment]) == (1, 1)
    saved = store.fetch_all("coverage_segments")
    assert saved[0]["expected_items"] == 31
    assert saved[0]["receipt_run_id"] is None
    store.close()


def test_cf_export_sync_reaches_nonempty_pit_path(synced_cf_d1_db):
    """CF-shaped export → paginated sync → generic-record PIT bars."""
    assert synced_cf_d1_db.rc == 0
    assert len(synced_cf_d1_db.calls) > 1
    queries = [parse_qs(urlparse(url).query) for url in synced_cf_d1_db.calls]
    assert all(query["limit"] == ["2"] for query in queries)
    assert any("cursor" in query for query in queries[1:])

    bars = pit.get_equity_bars_daily(
        as_of="2025-04-04T15:30:00+09:00",
        code="8697",
        db_path=synced_cf_d1_db.db,
    )
    assert len(bars.rows) == 4
    assert [row["close"] for row in bars.rows] == [100.0, 102.0, 101.0, 104.0]


@pytest.mark.live
def test_sync_live_requires_worker_url(tmp_path, sync_module):
    """Live smoke. Skipped unless ``QP_LIVE=1`` and a worker URL is set.

    Run with:
      QP_LIVE=1 INGESTION_PREMIUM_URL=https://... INGESTION_PROXY_TOKEN=... \\
        .venv/bin/python -m pytest tests/test_phase35_sync_script.py::test_sync_live_requires_worker_url
    """
    if not os.environ.get("QP_LIVE"):
        pytest.skip("set QP_LIVE=1 to run live sync smoke")
    url = os.environ.get("INGESTION_PREMIUM_URL")
    if not url:
        pytest.skip("INGESTION_PREMIUM_URL not set")
    rc = sync_module.main([
        "--db", str(tmp_path / "live.sqlite"),
        "--url", url,
        "--table", "jquants_market_calendar",
    ])
    assert rc == 0
