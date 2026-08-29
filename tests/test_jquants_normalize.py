"""J-Quants normalizer: V2 short field names, zero preservation, close time."""

from __future__ import annotations

import json

import pytest

from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_generic,
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
        "MktCap": 123456789,
    }]
    out = normalize_daily_bars(rows, ingested_at=ING)
    assert len(out) == 1
    r = out[0]
    assert r["open"] == 100.0 and r["high"] == 110.0 and r["low"] == 90.0
    assert r["close"] == 105.0
    assert r["volume"] == 1000.0 and r["turnover_value"] == 105000.0
    assert r["adjustment_open"] == 100.0 and r["adjustment_close"] == 105.0
    assert r["adjustment_volume"] == 1000.0
    assert r["market_cap"] == 123456789.0


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


def test_listed_info_v2_live_short_names():
    """V2 /v2/equities/master uses S17/S33/Mkt (not Sec17Code/MktCode)."""
    rows = [{
        "Date": "2026-08-13",
        "Code": "13010",
        "CoName": "極洋",
        "CoNameEn": "KYOKUYO CO.,LTD.",
        "S17": "1",
        "S17Nm": "食品",
        "S33": "0050",
        "S33Nm": "水産・農林業",
        "ScaleCat": "TOPIX Small 1",
        "Mkt": "0111",
        "MktNm": "プライム",
        "Mrgn": "2",
        "MrgnNm": "貸借",
        "ProdCat": "011",
    }]
    r = normalize_listed_info(rows, ingested_at=ING, snapshot_date="2026-08-13")[0]
    assert r["company_name"] == "極洋"
    assert r["company_name_en"] == "KYOKUYO CO.,LTD."
    assert r["sector_17_code"] == "1"
    assert r["sector_17_name"] == "食品"
    assert r["sector_33_code"] == "0050"
    assert r["sector_33_name"] == "水産・農林業"
    assert r["scale_category"] == "TOPIX Small 1"
    assert r["market_code"] == "0111"
    assert r["market_name"] == "プライム"
    # ListingDate not published on V2 master surface
    assert r["listing_date"] is None


def test_bars_aadj_is_not_all_day_adjustment_alias():
    """AAdj* is afternoon-session adjusted OHLCV, not a fallback for Adj*."""
    rows = [{
        "Code": "13010",
        "Date": "2024-01-04",
        "O": None,
        "H": None,
        "L": None,
        "C": None,
        "Vo": None,
        "Va": None,
        "AdjO": None,
        "AdjH": None,
        "AdjL": None,
        "AdjC": None,
        "AdjVo": None,
        "AAdjO": 3785.0,
        "AAdjH": 3825.0,
        "AAdjL": 3785.0,
        "AAdjC": 3815.0,
        "AAdjVo": 12000.0,
    }]
    r = normalize_daily_bars(rows, ingested_at=ING)[0]
    assert r["adjustment_open"] is None
    assert r["adjustment_high"] is None
    assert r["adjustment_low"] is None
    assert r["adjustment_close"] is None
    assert r["adjustment_volume"] is None


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


# --------------------------------------------------------------------------- generic

def test_generic_natural_key_from_catalog_identity_fields():
    rows = [{"Code": "8697", "Date": "2025-04-01", "Close": 100}]
    out = normalize_generic(rows, dataset="equities_bars_daily", ingested_at=ING)
    assert len(out) == 1
    r = out[0]
    assert r["dataset"] == "equities_bars_daily"
    assert r["source"] == "jquants"
    # identity fields land in the natural key
    nk = json.loads(r["natural_key"])
    assert nk == {"Code": "8697", "Date": "2025-04-01"}
    # daily bars reuse the close-time rule
    assert r["event_time"] == "2025-04-01T15:30:00+09:00"
    # payload (sorted) + raw_payload (verbatim) both present
    assert json.loads(r["raw_payload"])["Close"] == 100
    assert json.loads(r["payload"]) == rows[0]
    assert r["available_at"] == "2025-04-01T15:30:00+09:00"


def test_source_available_at_is_raw_only_and_cannot_override_contract_metadata():
    forged = "1999-01-01T00:00:00+09:00"
    source = {
        "Code": "8697",
        "Date": "2025-04-01",
        "Close": 100,
        "available_at": forged,
    }
    daily = normalize_daily_bars([source], ingested_at=ING)[0]
    generic = normalize_generic(
        [source], dataset="equities_bars_daily", ingested_at=ING
    )[0]

    assert daily["available_at"] == "2025-04-01T15:30:00+09:00"
    assert generic["available_at"] == "2025-04-01T15:30:00+09:00"
    assert json.loads(daily["raw_payload"])["available_at"] == forged
    assert json.loads(generic["raw_payload"])["available_at"] == forged


def test_available_at_keyword_remains_an_explicit_trusted_caller_path():
    trusted = "2025-04-20T09:00:00+09:00"
    row = {
        "Code": "8697",
        "Date": "2025-04-01",
        "available_at": "1999-01-01T00:00:00+09:00",
    }
    normalized = normalize_generic(
        [row],
        dataset="equities_bars_daily",
        ingested_at=ING,
        available_at=trusted,
    )[0]
    assert normalized["available_at"] == trusted


def test_generic_event_time_from_disclosed_date():
    rows = [{
        "Code": "8697",
        "DisclosedDate": "2025-05-01",
        "DisclosedTime": "09:00",
        "DiscNo": "1",
        "Foo": 1,
    }]
    out = normalize_generic(rows, dataset="fins_details", ingested_at=ING)
    assert out[0]["event_time"] == "2025-05-01T09:00:00+09:00"
    assert json.loads(out[0]["natural_key"]) == {
        "Code": "8697",
        "DiscDate": "2025-05-01",
        "DiscNo": "1",
    }
    assert out[0]["available_at"] == "2025-05-01T09:00:00+09:00"


def test_generic_key_falls_back_to_row_hash_when_no_identity_fields():
    rows = [{"SomethingUnrelated": "x"}]
    out = normalize_generic(rows, dataset="markets_breakdown", ingested_at=ING)
    nk = out[0]["natural_key"]
    assert nk.startswith("hash:sha256:")
    assert len(nk.removeprefix("hash:sha256:")) == 64
    # event_time falls back to available_at (ingested) when no date present
    assert out[0]["event_time"] == ING


def test_generic_unknown_dataset_raises():
    with pytest.raises(KeyError):
        normalize_generic([{"a": 1}], dataset="nope", ingested_at=ING)


def test_generic_skips_non_dict_rows():
    out = normalize_generic(
        [{"Code": "1", "Date": "2025-04-01"}, "junk", None],
        dataset="equities_bars_daily",
        ingested_at=ING,
    )
    assert len(out) == 1
