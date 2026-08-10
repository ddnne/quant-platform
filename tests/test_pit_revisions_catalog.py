"""Regressions for revision-aware PIT reads and catalog/curated dual-read."""

from __future__ import annotations

from ingestion.jquants.normalize import normalize_daily_bars, normalize_generic
from pit import get_equity_bars_daily, get_equity_master, get_market_calendar
from storage.sqlite_store import SqliteStore


ORIGINAL_AT = "2025-04-02T09:00:00+09:00"
AMENDED_AT = "2025-04-20T09:00:00+09:00"


def test_original_revision_is_visible_before_later_amendment(tmp_path):
    """An amendment must not erase the value known earlier in history."""
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    source = {
        "Code": "8697",
        "Date": "2025-04-01",
        "Open": 980,
        "High": 990,
        "Low": 975,
        "Close": 985,
        "Volume": 1000,
    }
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars([source], ingested_at=ORIGINAL_AT),
    )
    amended = {**source, "Close": 987}
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars([amended], ingested_at=AMENDED_AT),
    )

    assert store.count("jquants_daily_bars") == 1
    assert store.count("jquants_daily_bars_revisions") == 1
    store.close()

    between = get_equity_bars_daily(
        as_of="2025-04-10T09:00:00+09:00", code="8697", db_path=path
    )
    after = get_equity_bars_daily(
        as_of="2025-04-21T09:00:00+09:00", code="8697", db_path=path
    )

    assert len(between.rows) == 1
    assert between.rows[0]["close"] == 985.0
    assert between.rows[0]["available_at"] == ORIGINAL_AT
    assert len(after.rows) == 1
    assert after.rows[0]["close"] == 987.0
    assert after.rows[0]["available_at"] == AMENDED_AT


def test_curated_getters_return_catalog_partition_rows(tmp_path):
    """Catalog ingestion writes only generic rows; all curated reads see them."""
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    rows = []
    rows.extend(
        normalize_generic(
            [
                {
                    "Code": "8697",
                    "Date": "2025-04-01",
                    "CompanyName": "Japan Exchange Group",
                    "MarketCode": "0111",
                }
            ],
            dataset="equities_master",
            ingested_at=ORIGINAL_AT,
        )
    )
    rows.extend(
        normalize_generic(
            [
                {
                    "Code": "8697",
                    "Date": "2025-04-01",
                    "Open": 980,
                    "High": 990,
                    "Low": 975,
                    "Close": 985,
                    "Volume": 1000,
                }
            ],
            dataset="equities_bars_daily",
            ingested_at=ORIGINAL_AT,
        )
    )
    rows.extend(
        normalize_generic(
            [{"Date": "2025-04-01", "HolidayDivision": "1"}],
            dataset="markets_calendar",
            ingested_at=ORIGINAL_AT,
        )
    )
    store.upsert("jquants_records", rows)
    assert store.count("jquants_listed_info") == 0
    assert store.count("jquants_daily_bars") == 0
    assert store.count("jquants_market_calendar") == 0
    store.close()

    master = get_equity_master(
        as_of=AMENDED_AT, code="8697", db_path=path
    )
    bars = get_equity_bars_daily(
        as_of=AMENDED_AT,
        code="8697",
        from_event="2025-04-01",
        to_event="2025-04-01",
        db_path=path,
    )
    calendar = get_market_calendar(
        as_of=AMENDED_AT,
        from_date="2025-04-01",
        to_date="2025-04-01",
        db_path=path,
    )

    assert len(master.rows) == 1
    assert master.rows[0]["code"] == "8697"
    assert master.rows[0]["snapshot_date"] == "2025-04-01"
    assert master.rows[0]["company_name"] == "Japan Exchange Group"

    assert len(bars.rows) == 1
    assert bars.rows[0]["code"] == "8697"
    assert bars.rows[0]["date"] == "2025-04-01"
    assert bars.rows[0]["close"] == 985.0

    assert len(calendar.rows) == 1
    assert calendar.rows[0]["date"] == "2025-04-01"
    assert calendar.rows[0]["holiday_division"] == "1"


def test_dual_read_deduplicates_shared_business_key_by_latest_availability(tmp_path):
    """Legacy and catalog rows coexist without duplicate curated observations."""
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    original = {"Code": "8697", "Date": "2025-04-01", "Close": 985}
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars([original], ingested_at=ORIGINAL_AT),
    )
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{**original, "Close": 987}],
            dataset="equities_bars_daily",
            ingested_at=AMENDED_AT,
        ),
    )
    store.close()

    between = get_equity_bars_daily(
        as_of="2025-04-10T09:00:00+09:00", code="8697", db_path=path
    )
    after = get_equity_bars_daily(
        as_of="2025-04-21T09:00:00+09:00", code="8697", db_path=path
    )

    assert [row["close"] for row in between.rows] == [985.0]
    assert [row["close"] for row in after.rows] == [987.0]
