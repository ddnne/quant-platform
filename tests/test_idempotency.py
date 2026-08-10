"""Idempotency + available_at gate at the storage and pipeline layers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ingestion.jquants.normalize import normalize_daily_bars
from storage.sqlite_store import MissingAvailableAt, SqliteStore

INGESTED = "2025-04-02T09:00:00+09:00"


def _bars():
    return [
        {"Code": "8697", "Date": "2025-04-01", "Open": 980, "High": 990,
         "Low": 975, "Close": 985, "Volume": 1000, "TurnoverValue": 985000},
        {"Code": "8697", "Date": "2025-04-02", "Open": 985, "High": 1000,
         "Low": 982, "Close": 995, "Volume": 1200, "TurnoverValue": 1194000},
    ]


def test_upsert_same_rows_twice_is_idempotent(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = normalize_daily_bars(_bars(), ingested_at=INGESTED)
    assert store.upsert("jquants_daily_bars", rows) == 2
    assert store.count("jquants_daily_bars") == 2

    # same rows again -> no duplicates, count unchanged
    assert store.upsert("jquants_daily_bars", rows) == 2
    assert store.count("jquants_daily_bars") == 2
    store.close()


def test_upsert_replaces_changed_values_on_same_natural_key(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    base = normalize_daily_bars(_bars(), ingested_at=INGESTED)
    store.upsert("jquants_daily_bars", base)
    # amend one bar's close and re-upsert same natural key
    amended = [dict(base[0])]
    amended[0]["close"] = 987.0
    store.upsert("jquants_daily_bars", amended)
    assert store.count("jquants_daily_bars") == 2  # still 2, not 3
    row = store.fetch_where(
        "jquants_daily_bars", "code=? AND date=?", ("8697", "2025-04-01")
    )[0]
    assert row["close"] == 987.0
    store.close()


def test_missing_available_at_rejected(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = normalize_daily_bars(_bars(), ingested_at=INGESTED)
    rows[0]["available_at"] = None  # violate PIT gate
    with pytest.raises(MissingAvailableAt):
        store.upsert("jquants_daily_bars", rows)
    # nothing partial persisted on this batch
    assert store.count("jquants_daily_bars") == 0
    store.close()


def test_empty_available_at_string_rejected(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = normalize_daily_bars(_bars(), ingested_at=INGESTED)
    rows[1]["available_at"] = "   "
    with pytest.raises(MissingAvailableAt):
        store.upsert("jquants_daily_bars", rows)
    store.close()


def test_run_log_recorded(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    store.log_run(source="jsda", runtime="local", status="ok", detail="x")
    rows = store.fetch_all("ingestion_run_log")
    assert len(rows) == 1
    assert rows[0]["source"] == "jsda"
    assert rows[0]["runtime"] == "local"
    store.close()
