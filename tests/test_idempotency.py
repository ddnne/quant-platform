"""Idempotency + available_at gate at the storage and pipeline layers."""

from __future__ import annotations

import sqlite3
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
    # amend one bar's close via the source record and re-normalize, so the
    # amendment is visible in raw_payload (how real amendments arrive)
    amended_src = [dict(_bars()[0])]
    amended_src[0]["Close"] = 987
    amended = normalize_daily_bars(amended_src, ingested_at=INGESTED)
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


# --------------------------------------------------------------------------- earliest available_at

def test_upsert_preserves_earliest_available_at(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    base = normalize_daily_bars(_bars(), ingested_at=INGESTED)  # available_at == INGESTED
    store.upsert("jquants_daily_bars", base)

    # re-upsert the SAME natural key with a LATER available_at -> earliest kept
    later = [dict(base[0])]
    later[0]["available_at"] = "2025-04-10T09:00:00+09:00"
    store.upsert("jquants_daily_bars", later)

    row = store.fetch_where(
        "jquants_daily_bars", "code=? AND date=?", ("8697", "2025-04-01")
    )[0]
    assert row["available_at"] == INGESTED  # earliest preserved
    store.close()


def test_upsert_keeps_earlier_available_at_against_earlier_payload(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    # first write a LATE available_at, then re-upsert an EARLIER one -> earliest wins
    late = normalize_daily_bars(_bars(), ingested_at="2025-04-10T09:00:00+09:00")
    store.upsert("jquants_daily_bars", late)
    early = normalize_daily_bars(_bars(), ingested_at=INGESTED)  # earlier
    store.upsert("jquants_daily_bars", early)
    row = store.fetch_where(
        "jquants_daily_bars", "code=? AND date=?", ("8697", "2025-04-01")
    )[0]
    assert row["available_at"] == INGESTED
    store.close()


def test_unchanged_reupsert_keeps_earliest_available_and_refreshes_ingested(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    first = normalize_daily_bars(_bars(), ingested_at="2025-04-02T09:00:00+09:00")
    store.upsert("jquants_daily_bars", first)

    # re-upsert the SAME source later in time -> available_at preserved,
    # ingested_at refreshed to the latest fetch.
    second = normalize_daily_bars(_bars(), ingested_at="2025-04-20T09:00:00+09:00")
    store.upsert("jquants_daily_bars", second)

    row = store.fetch_where(
        "jquants_daily_bars", "code=? AND date=?", ("8697", "2025-04-01")
    )[0]
    assert row["available_at"] == "2025-04-02T09:00:00+09:00"  # earliest kept
    assert row["ingested_at"] == "2025-04-20T09:00:00+09:00"  # refreshed
    store.close()


def test_amended_close_with_later_available_at_is_not_backdated(tmp_path):
    """P1: an amended close published LATER must take the later available_at,
    not be backdated to the original publication time."""
    store = SqliteStore(tmp_path / "ing.sqlite")
    base = normalize_daily_bars(_bars(), ingested_at="2025-04-02T09:00:00+09:00")
    store.upsert("jquants_daily_bars", base)

    # amend the 04-01 close via the source record, published LATER.
    amended_src = [dict(_bars()[0])]
    amended_src[0]["Close"] = 987
    amended = normalize_daily_bars(amended_src, ingested_at="2025-04-20T09:00:00+09:00")
    store.upsert("jquants_daily_bars", amended)

    row = store.fetch_where(
        "jquants_daily_bars", "code=? AND date=?", ("8697", "2025-04-01")
    )[0]
    assert row["close"] == 987.0                              # amended value stored
    assert row["available_at"] == "2025-04-20T09:00:00+09:00"  # NOT backdated
    store.close()


def test_offset_equivalent_available_at_does_not_backdate(tmp_path):
    """Canonicalization: 17:00+09:00 and 08:00+00:00 are the same instant and
    must compare equal, so a re-fetch in a different offset is treated as an
    unchanged re-fetch (earliest kept), not an amendment."""
    store = SqliteStore(tmp_path / "ing.sqlite")
    base = normalize_daily_bars(_bars(), ingested_at="2025-04-01T17:00:00+09:00")
    store.upsert("jquants_daily_bars", base)

    later = [dict(base[0])]
    # same instant, expressed in UTC -> canonicalizes to the same +09:00 string
    later[0]["available_at"] = "2025-04-01T08:00:00+00:00"
    store.upsert("jquants_daily_bars", later)

    row = store.fetch_where(
        "jquants_daily_bars", "code=? AND date=?", ("8697", "2025-04-01")
    )[0]
    assert row["available_at"] == "2025-04-01T17:00:00+09:00"
    store.close()


# --------------------------------------------------------------------------- rollback

def _bar(code, event_time="2025-04-01T15:00:00+09:00"):
    return {
        "source": "jquants",
        "code": code,
        "date": "2025-04-01",
        "event_time": event_time,
        "available_at": "2025-04-02T09:00:00+09:00",
        "ingested_at": "2025-04-02T09:00:00+09:00",
    }


def test_upsert_rolls_back_on_midbatch_failure(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    good = _bar("8697")
    bad = _bar("8698", event_time=None)  # NOT NULL violation mid-batch
    rows = [good, bad, _bar("8699")]
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert("jquants_daily_bars", rows)
    # nothing partial persisted
    assert store.count("jquants_daily_bars") == 0
    # connection is still usable after rollback
    store.upsert("jquants_daily_bars", [good])
    assert store.count("jquants_daily_bars") == 1
    store.close()
