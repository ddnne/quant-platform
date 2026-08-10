"""J-Quants normalizer: V2 short field names, zero preservation, close time."""

from __future__ import annotations

from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_listed_info,
    normalize_market_calendar,
)

ING = "2025-04-02T09:00:00+09:00"


# --------------------------------------------------------------------------- short names

def test_v2_short_field_names_produce_ohlcv():
    rows = [{
        "Code": "8697", "Date": "2025-04-01",
        "O": 100, "H": 110, "L": 90, "C": 105, "Vo": 1000, "Va": 105000,
        "AdjO": 100, "AdjH": 110, "AdjL": 90, "AdjC": 105, "AdjVo": 1000,
    }]
    out = normalize_daily_bars(rows, ingested_at=ING)
    assert len(out) == 1
    r = out[0]
    assert r["open"] == 100.0 and r["high"] == 110.0 and r["low"] == 90.0
    assert r["close"] == 105.0
    assert r["volume"] == 1000.0 and r["turnover_value"] == 105000.0
    assert r["adjustment_open"] == 100.0 and r["adjustment_close"] == 105.0
    assert r["adjustment_volume"] == 1000.0


def test_v1_long_names_still_work():
    rows = [{
        "Code": "8697", "Date": "2025-04-01",
        "Open": 1, "High": 2, "Low": 3, "Close": 4, "Volume": 5,
        "TurnoverValue": 6,
    }]
    r = normalize_daily_bars(rows, ingested_at=ING)[0]
    assert (r["open"], r["high"], r["low"], r["close"]) == (1.0, 2.0, 3.0, 4.0)
    assert r["volume"] == 5.0 and r["turnover_value"] == 6.0


def test_zero_volume_preserved_not_dropped():
    rows = [{"Code": "8697", "Date": "2025-04-01", "Vo": 0, "Va": 0}]
    r = normalize_daily_bars(rows, ingested_at=ING)[0]
    assert r["volume"] == 0.0
    assert r["turnover_value"] == 0.0


def test_listed_info_short_names():
    rows = [{"Code": "8697", "CoName": "野村ホールディングス", "Sec17Code": "1"}]
    r = normalize_listed_info(rows, ingested_at=ING, snapshot_date="2025-04-01")[0]
    assert r["company_name"] == "野村ホールディングス"
    assert r["sector_17_code"] == "1"


def test_calendar_short_names():
    rows = [{"Date": "2025-05-03", "HolDiv": "1"}]
    r = normalize_market_calendar(rows, ingested_at=ING)[0]
    assert r["holiday_division"] == "1"


# --------------------------------------------------------------------------- close time

def test_close_time_15_00_before_2024_11_05():
    r = normalize_daily_bars(
        [{"Code": "1", "Date": "2024-11-04"}], ingested_at=ING
    )[0]
    assert r["event_time"] == "2024-11-04T15:00:00+09:00"


def test_close_time_15_30_on_and_after_2024_11_05():
    on = normalize_daily_bars(
        [{"Code": "1", "Date": "2024-11-05"}], ingested_at=ING
    )[0]
    after = normalize_daily_bars(
        [{"Code": "1", "Date": "2025-04-01"}], ingested_at=ING
    )[0]
    assert on["event_time"] == "2024-11-05T15:30:00+09:00"
    assert after["event_time"] == "2025-04-01T15:30:00+09:00"
