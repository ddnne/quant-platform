"""PIT API contract: ``as_of`` is mandatory on every read.

``as_of`` is the point-in-time gate. There is no "latest" fallback — omitting
it must fail with :class:`pit.AsOfRequired`, never silently return current
data (a look-ahead footgun). These tests pin that contract plus the
``as_of`` parsing rules and the empty-result behavior.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from pit import (
    AsOfRequired,
    InvalidAsOf,
    InvalidDataset,
    PIT_API_VERSION,
    get_equity_bars_daily,
    get_equity_master,
    get_jsda_bond_trades,
    get_jquants_records,
    get_market_calendar,
)
from pit.query import normalize_as_of
from storage.sqlite_store import SqliteStore


# --- helpers ---------------------------------------------------------------


def _seed(tmp_path, table: str, rows: list[dict]) -> "object":
    """Write ``rows`` into a fresh DB at ``tmp_path`` and return its path.

    Uses the real :class:`SqliteStore` so ``available_at`` is canonicalized
    exactly as ingestion would store it. The store is closed (WAL checkpointed)
    so the read-only PIT connection sees a self-contained file.
    """
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    if rows:
        store.upsert(table, rows)
    store.close()
    return path


# Every public read function — each must refuse a missing as_of. (name, fn)
_ALL_GETTERS = [
    ("equity_master", lambda **k: get_equity_master(**k)),
    ("bars_daily", lambda **k: get_equity_bars_daily(**k)),
    ("market_calendar", lambda **k: get_market_calendar(**k)),
    # dataset required too, but as_of is validated FIRST -> AsOfRequired anyway
    ("jquants_records", lambda **k: get_jquants_records(dataset="fins_dividend", **k)),
    ("jsda_bond_trades", lambda **k: get_jsda_bond_trades(**k)),
]


# --- as_of is mandatory ----------------------------------------------------


@pytest.mark.parametrize("name, getter", _ALL_GETTERS, ids=[n for n, _ in _ALL_GETTERS])
def test_missing_as_of_raises_as_of_required(name, getter):
    """No as_of at all -> AsOfRequired (never a 'latest' default)."""
    with pytest.raises(AsOfRequired):
        getter(db_path="/dev/null/nonexistent.sqlite")  # path never reached


def test_none_as_of_raises_as_of_required():
    with pytest.raises(AsOfRequired):
        get_equity_master(as_of=None, db_path="/dev/null/nonexistent.sqlite")


def test_empty_string_as_of_raises_as_of_required():
    with pytest.raises(AsOfRequired):
        get_equity_master(as_of="   ", db_path="/dev/null/nonexistent.sqlite")


def test_jquants_records_requires_dataset_when_as_of_present():
    """as_of supplied but dataset omitted -> InvalidDataset (not a silent empty)."""
    with pytest.raises(InvalidDataset):
        get_jquants_records(as_of="2025-04-01T00:00:00+09:00", db_path="/dev/null/x.sqlite")


def test_jquants_records_empty_dataset_rejected():
    with pytest.raises(InvalidDataset):
        get_jquants_records(
            as_of="2025-04-01T00:00:00+09:00",
            dataset="  ",
            db_path="/dev/null/x.sqlite",
        )


# --- as_of parsing ---------------------------------------------------------


def test_normalize_accepts_iso_string_with_offset():
    assert normalize_as_of("2025-04-01T08:00:00+00:00") == "2025-04-01T17:00:00+09:00"


def test_normalize_accepts_iso_jst_string():
    assert normalize_as_of("2025-04-01T17:00:00+09:00") == "2025-04-01T17:00:00+09:00"


def test_normalize_accepts_date_only_string_as_jst_midnight():
    assert normalize_as_of("2025-04-01") == "2025-04-01T00:00:00+09:00"


def test_normalize_accepts_aware_datetime_utc():
    dt = datetime(2025, 4, 1, 8, 0, 0, tzinfo=ZoneInfo("UTC"))
    assert normalize_as_of(dt) == "2025-04-01T17:00:00+09:00"


def test_normalize_accepts_naive_datetime_assumed_jst():
    dt = datetime(2025, 4, 1, 17, 0, 0)  # no tzinfo -> JST
    assert normalize_as_of(dt) == "2025-04-01T17:00:00+09:00"


def test_normalize_accepts_date_as_jst_midnight():
    assert normalize_as_of(date(2025, 4, 1)) == "2025-04-01T00:00:00+09:00"


@pytest.mark.parametrize("bad", ["not-a-date", "2025-13-99", "2025/04/01T99:99"])
def test_normalize_rejects_garbage(bad):
    with pytest.raises(InvalidAsOf):
        normalize_as_of(bad)


def test_normalize_rejects_unsupported_type():
    with pytest.raises(InvalidAsOf):
        normalize_as_of(12345)


# --- empty result is an empty list, not an error ---------------------------


def test_empty_result_is_empty_list_not_error(tmp_path):
    """A query that matches no rows returns ``rows == []`` — no exception."""
    path = _seed(
        tmp_path,
        "jquants_daily_bars",
        [
            {
                "source": "jquants", "code": "8697", "date": "2025-03-31",
                "event_time": "2025-03-31T15:00:00+09:00",
                "available_at": "2025-04-02T17:00:00+09:00",
                "ingested_at": "2025-04-02T17:00:00+09:00",
                "close": 1000.0,
            }
        ],
    )
    # as_of strictly before the only row's available_at -> nothing visible.
    res = get_equity_bars_daily(as_of="2025-04-01T00:00:00+09:00", db_path=path)
    assert res.rows == []
    assert res.count == 0
    assert len(res) == 0
    assert not res
    # metadata still complete even on an empty result.
    assert res.metadata["as_of"] == "2025-04-01T00:00:00+09:00"
    assert res.metadata["table"] == "jquants_daily_bars"
    assert res.metadata["source"] == "jquants"
    assert res.metadata["count"] == 0
    assert res.metadata["pit_api_version"] == PIT_API_VERSION


def test_metadata_records_normalized_as_of_and_version(tmp_path):
    path = _seed(
        tmp_path,
        "jquants_daily_bars",
        [
            {
                "source": "jquants", "code": "8697", "date": "2025-03-31",
                "event_time": "2025-03-31T15:00:00+09:00",
                "available_at": "2025-04-01T17:00:00+09:00",
                "ingested_at": "2025-04-01T17:00:00+09:00",
                "close": 1000.0,
            }
        ],
    )
    # Pass a UTC instant; metadata must echo the normalized JST form.
    res = get_equity_bars_daily(as_of="2025-04-01T08:00:00+00:00", db_path=path)
    assert res.metadata["as_of"] == "2025-04-01T17:00:00+09:00"
    assert res.metadata["pit_api_version"] == "0.2.0"
    assert res.count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
