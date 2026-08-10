"""PIT API coverage: each structured table has at least one happy-path read.

Seeds one realistic row per table through the real :class:`SqliteStore` (so
``available_at`` is canonicalized as in production), then reads it back
through the public ``get_*`` API and asserts the row, the decoded JSON
payload, and the additive range/equality filters all behave.
"""

from __future__ import annotations

import pytest

from pit import (
    get_equity_bars_daily,
    get_equity_master,
    get_jsda_bond_trades,
    get_jquants_records,
    get_market_calendar,
)
from storage.sqlite_store import SqliteStore

# A single publication instant late enough that every seeded row is visible.
AS_OF = "2025-04-02T09:00:00+09:00"


def _store(tmp_path):
    return SqliteStore(tmp_path / "ing.sqlite")


# --- jquants_listed_info ---------------------------------------------------


def test_equity_master_happy_path(tmp_path):
    rows = [
        {
            "source": "jquants", "code": "8697", "snapshot_date": "2025-03-31",
            "event_time": "2025-03-31T09:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
            "company_name": "日本取引所グループ",
            "market_code": "1",
            "raw_payload": '{"Code": "8697", "CompanyName": "JPX"}',
        }
    ]
    with _store(tmp_path) as s:
        s.upsert("jquants_listed_info", rows)
    path = tmp_path / "ing.sqlite"

    res = get_equity_master(as_of=AS_OF, code="8697", db_path=path)
    assert res.count == 1
    row = res.rows[0]
    assert row["code"] == "8697"
    assert row["company_name"] == "日本取引所グループ"
    # raw_payload decoded from JSON string into a dict.
    assert row["raw_payload"] == {"Code": "8697", "CompanyName": "JPX"}
    assert res.metadata["source"] == "jquants"


def test_equity_master_code_filter_excludes_other(tmp_path):
    rows = [
        {
            "source": "jquants", "code": c, "snapshot_date": "2025-03-31",
            "event_time": "2025-03-31T09:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
        }
        for c in ("8697", "7203")
    ]
    with _store(tmp_path) as s:
        s.upsert("jquants_listed_info", rows)
    path = tmp_path / "ing.sqlite"

    only_8697 = get_equity_master(as_of=AS_OF, code="8697", db_path=path)
    assert {r["code"] for r in only_8697} == {"8697"}
    all_both = get_equity_master(as_of=AS_OF, db_path=path)
    assert {r["code"] for r in all_both} == {"8697", "7203"}


# --- jquants_daily_bars ----------------------------------------------------


def test_bars_daily_happy_path_with_date_range(tmp_path):
    rows = [
        {
            "source": "jquants", "code": "8697", "date": d,
            "event_time": f"{d}T15:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
            "close": close,
            "raw_payload": f'{{"Code": "8697", "Date": "{d}", "Close": {close}}}',
        }
        for d, close in (("2025-03-28", 100.0), ("2025-03-31", 110.0), ("2025-04-01", 120.0))
    ]
    with _store(tmp_path) as s:
        s.upsert("jquants_daily_bars", rows)
    path = tmp_path / "ing.sqlite"

    res = get_equity_bars_daily(
        as_of=AS_OF, code="8697",
        from_event="2025/03/30",  # flexible input reduced to 2025-03-30
        to_event="2025-03-31",
        db_path=path,
    )
    assert [r["date"] for r in res] == ["2025-03-31"]  # range excludes 03-28 and 04-01
    assert res.rows[0]["raw_payload"]["Close"] == 110.0


# --- jquants_market_calendar -----------------------------------------------


def test_market_calendar_happy_path(tmp_path):
    rows = [
        {
            "source": "jquants", "date": d,
            "event_time": f"{d}T09:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
            "holiday_division": "1",
            "raw_payload": f'{{"Date": "{d}", "HolidayDivision": "1"}}',
        }
        for d in ("2025-03-31", "2025-04-15")
    ]
    with _store(tmp_path) as s:
        s.upsert("jquants_market_calendar", rows)
    path = tmp_path / "ing.sqlite"

    res = get_market_calendar(as_of=AS_OF, from_date="2025-04-01", db_path=path)
    assert [r["date"] for r in res] == ["2025-04-15"]


# --- jquants_records -------------------------------------------------------


def test_jquants_records_happy_path_with_code_filter(tmp_path):
    rows = [
        {
            "source": "jquants",
            "dataset": "fins_dividend",
            "natural_key": '{"AnnouncementDate": "2025-03-15", "Code": "8697"}',
            "event_time": "2025-03-15T09:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
            "payload": '{"AnnouncementDate": "2025-03-15", "Code": "8697", "Dividend": 15.0}',
            "raw_payload": '{"Code": "8697", "AnnouncementDate": "2025-03-15", "Dividend": 15.0}',
        },
        {
            "source": "jquants",
            "dataset": "fins_dividend",
            "natural_key": '{"AnnouncementDate": "2025-03-16", "Code": "7203"}',
            "event_time": "2025-03-16T09:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
            "payload": '{"AnnouncementDate": "2025-03-16", "Code": "7203", "Dividend": 25.0}',
            "raw_payload": '{"Code": "7203", "AnnouncementDate": "2025-03-16", "Dividend": 25.0}',
        },
    ]
    with _store(tmp_path) as s:
        s.upsert("jquants_records", rows)
    path = tmp_path / "ing.sqlite"

    # code filter on the canonical natural-key "Code" field.
    res = get_jquants_records(as_of=AS_OF, dataset="fins_dividend", code="8697", db_path=path)
    assert res.count == 1
    assert res.rows[0]["payload"]["Dividend"] == 15.0
    assert res.metadata["dataset"] == "fins_dividend"

    # event_time range filter (additive on top of available_at).
    ranged = get_jquants_records(
        as_of=AS_OF, dataset="fins_dividend",
        from_event="2025-03-16T00:00:00+09:00", db_path=path,
    )
    assert {r["payload"]["Code"] for r in ranged} == {"7203"}

    # unknown dataset -> empty (not an error).
    unknown = get_jquants_records(as_of=AS_OF, dataset="no_such_dataset", db_path=path)
    assert unknown.count == 0


# --- jsda_bond_trades ------------------------------------------------------


def test_jsda_bond_trades_happy_path(tmp_path):
    rows = [
        {
            "source": "jsda", "trade_date": "2025-03-31", "isin": "JP123456789",
            "issuer_name": "XYZ Corp", "event_time": "2025-03-31T17:00:00+09:00",
            "available_at": "2025-04-01T17:00:00+09:00",
            "ingested_at": "2025-04-01T17:00:00+09:00",
            "close_yield": 0.512, "trade_amount_mil_jpy": 12345.0,
            "raw_payload": '{"ISIN": "JP123456789", "CloseYield": 0.512}',
        }
    ]
    with _store(tmp_path) as s:
        s.upsert("jsda_bond_trades", rows)
    path = tmp_path / "ing.sqlite"

    res = get_jsda_bond_trades(
        as_of=AS_OF, isin="JP123456789",
        from_event="2025-03-01", to_event="2025-03-31",
        db_path=path,
    )
    assert res.count == 1
    assert res.rows[0]["close_yield"] == 0.512
    assert res.rows[0]["raw_payload"]["ISIN"] == "JP123456789"
    assert res.metadata["source"] == "jsda"


# --- read-only enforcement -------------------------------------------------


def test_pit_connection_is_read_only(tmp_path):
    """The underlying connection must refuse writes (defense-in-depth)."""
    with _store(tmp_path) as s:
        s.upsert(
            "jquants_daily_bars",
            [
                {
                    "source": "jquants", "code": "8697", "date": "2025-03-31",
                    "event_time": "2025-03-31T15:00:00+09:00",
                    "available_at": "2025-04-01T17:00:00+09:00",
                    "ingested_at": "2025-04-01T17:00:00+09:00", "close": 1.0,
                }
            ],
        )
    from pit.query import connect_readonly
    import sqlite3

    conn = connect_readonly(tmp_path / "ing.sqlite")
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO jquants_daily_bars (source, code, date, event_time, "
                "available_at, ingested_at) VALUES ('x','x','x','x','x','x')"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
