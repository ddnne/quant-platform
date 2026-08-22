"""COMPLETE 21 min features — PIT gates + seeded compute.

Rows with ``available_at > as_of`` must not affect values. Seeded paths
cover positive / empty / insufficient history for each min feature.
Shared builders: ``tests/complete21_min_util.py``.
"""

from __future__ import annotations

import json

import pytest

from features import compute, get
from storage.sqlite_store import SqliteStore

from tests.complete21_min_util import (
    CODES,
    _upsert_jquants_records,
    _upsert_repo_rates,
    close_iso,
    seed_db,
)


def test_pit_gate_hides_future_available_at_margin_and_disclosure(tmp_path):
    """PIT: rows with available_at > as_of must not affect feature values."""
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    store = SqliteStore(db)
    # D1 margin obs: published at D1 close (visible at as_of=D1).
    # D2 margin obs: published at D2 close only (hidden at as_of=D1).
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "markets_margin_interest",
                "natural_key": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-01"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-01T00:00:00+09:00",
                "available_at": close_iso("2025-04-01"),
                "ingested_at": close_iso("2025-04-01"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-01",
                        "Code": CODES[0],
                        "LongVol": 100.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-01",
                        "Code": CODES[0],
                        "LongVol": 100.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "source": "jquants",
                "dataset": "markets_margin_interest",
                "natural_key": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": CODES[0],
                        "LongVol": 200.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": CODES[0],
                        "LongVol": 200.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02", "NetSales": 1},
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02", "NetSales": 1},
                    ensure_ascii=False,
                ),
            },
        ],
    )
    store.close()

    # At D1 close: only one margin obs → insufficient; disclosure flag 0.
    margin_early = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert margin_early.value is None
    assert "insufficient" in margin_early.metadata["reason"]

    disc_early = compute(
        "disclosure_flag_fins",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert disc_early.value == 0.0

    # At D2 close: both margin obs + disclosure visible.
    margin_late = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert margin_late.value == pytest.approx(1.0)  # 100 → 200

    disc_late = compute(
        "disclosure_flag_fins",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert disc_late.value == 1.0


def test_pit_gate_hides_future_short_ratio_and_margin_alert(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    store = SqliteStore(db)
    # Short ratio published only at D2 close.
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "markets_short_ratio",
                "natural_key": json.dumps(
                    {"Date": "2025-04-02", "S33": "0050"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "S33": "0050",
                        "SellExShortVa": 200.0,
                        "ShrtWithResVa": 40.0,
                        "ShrtNoResVa": 10.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "S33": "0050",
                        "SellExShortVa": 200.0,
                        "ShrtWithResVa": 40.0,
                        "ShrtNoResVa": 10.0,
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "source": "jquants",
                "dataset": "markets_margin_alert",
                "natural_key": json.dumps(
                    {
                        "Code": CODES[0],
                        "PubDate": "2025-04-02",
                        "AppDate": "2025-04-02",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Code": CODES[0],
                        "PubDate": "2025-04-02",
                        "AppDate": "2025-04-02",
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Code": CODES[0],
                        "PubDate": "2025-04-02",
                        "AppDate": "2025-04-02",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    store.close()

    short_early = compute(
        "short_ratio_level",
        as_of=close_iso("2025-04-01"),
        section="0050",
        db_path=db,
    )
    assert short_early.value is None

    alert_early = compute(
        "margin_alert_flag",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert alert_early.value == 0.0

    short_late = compute(
        "short_ratio_level",
        as_of=close_iso("2025-04-02"),
        section="0050",
        db_path=db,
    )
    assert short_late.value == pytest.approx(0.25)

    alert_late = compute(
        "margin_alert_flag",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert alert_late.value == 1.0


def test_pit_gate_hides_future_futures_activity(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    store = SqliteStore(db)
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "derivatives_bars_daily_futures",
                "natural_key": json.dumps(
                    {"Date": "2025-04-02", "Code": "160060019"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": "160060019",
                        "Volume": 500.0,
                        "Close": 28000.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": "160060019",
                        "Volume": 500.0,
                        "Close": 28000.0,
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    )
    store.close()

    early = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-01"),
        db_path=db,
    )
    assert early.value is None

    late = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-02"),
        db_path=db,
    )
    assert late.value == pytest.approx(500.0)


def test_volume_change_1d_on_seeded_bars(tmp_path):
    """Seed volumes are constant 1000 → change 0.0 with >=2 sessions."""
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "volume_change_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(0.0)
    assert out.metadata["feature_id"] == "volume_change_1d"
    assert out.metadata["datasets"] == ["equities_bars_daily"]
    assert out.metadata["rows_seen"] >= 2


def test_volume_change_1d_insufficient_history(tmp_path):
    day = "2025-04-01"
    db = seed_db(
        tmp_path,
        days=[day],
        prices={CODES[0]: {day: 100.0}},
    )
    out = compute(
        "volume_change_1d",
        as_of=close_iso(day),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_topix_relative_1d_seeded_dual_leg(tmp_path):
    """W53: dual-leg integration — equity return minus TOPIX return on seeded DB."""
    days = ["2025-04-01", "2025-04-02"]
    # Equity: 100 → 110 = +10%; TOPIX: 3000 → 3030 = +1% → relative +9%.
    prices = {CODES[0]: {"2025-04-01": 100.0, "2025-04-02": 110.0}}
    db = seed_db(tmp_path, days=days, prices=prices)
    _upsert_jquants_records(
        db,
        dataset="indices_bars_daily_topix",
        payloads=[
            {"Date": "2025-04-01", "Close": 3000.0},
            {"Date": "2025-04-02", "Close": 3030.0},
        ],
    )
    out = compute(
        "topix_relative_1d",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(0.09)
    assert out.metadata["feature_id"] == "topix_relative_1d"
    assert out.metadata["datasets"] == [
        "equities_bars_daily",
        "indices_bars_daily_topix",
    ]
    assert out.metadata["equity_ret"] == pytest.approx(0.10)
    assert out.metadata["topix_ret"] == pytest.approx(0.01)


def test_topix_relative_1d_insufficient_missing_topix_leg(tmp_path):
    """Missing TOPIX leg → None (not raise)."""
    days = ["2025-04-01", "2025-04-02"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "topix_relative_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "missing" in out.metadata["reason"]


def test_disclosure_flag_fins_empty_db_is_zero(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    prices = {CODES[0]: {d: 100.0 for d in days}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "disclosure_flag_fins",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    # No fins_summary rows in coreseed → flag 0.0
    assert out.value == 0.0
    assert out.metadata["rows_seen"] == 0
    assert out.metadata["datasets"] == ["fins_summary"]


def test_disclosure_flag_fins_seeded_positive(tmp_path):
    """W53: positive path — any PIT-visible fins_summary row → 1.0."""
    days = ["2025-04-01", "2025-04-02"]
    prices = {CODES[0]: {d: 100.0 for d in days}}
    db = seed_db(tmp_path, days=days, prices=prices)
    _upsert_jquants_records(
        db,
        dataset="fins_summary",
        payloads=[
            {"Code": CODES[0], "Date": "2025-04-02", "NetSales": 123},
        ],
    )
    out = compute(
        "disclosure_flag_fins",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == 1.0
    assert out.metadata["rows_seen"] >= 1
    assert out.metadata["feature_id"] == "disclosure_flag_fins"


def test_v0_return_1d_still_works_with_guard(tmp_path):
    """Pipeline DEFER guard must not break existing COMPLETE bars features."""
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "return_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx((102.0 - 101.0) / 101.0)


def test_margin_interest_change_1d_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_margin_interest",
        payloads=[
            {
                "Date": "2025-04-01",
                "Code": CODES[0],
                "LongVol": 100.0,
                "ShrtVol": 50.0,
            },
            {
                "Date": "2025-04-08",
                "Code": CODES[0],
                "LongVol": 130.0,
                "ShrtVol": 50.0,
            },
        ],
    )
    # Total 150 → 180 = +20%
    out = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-08"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(0.20)
    assert out.metadata["datasets"] == ["markets_margin_interest"]
    assert out.metadata["feature_id"] == "margin_interest_change_1d"
    assert out.metadata["rows_seen"] == 2


def test_margin_interest_change_1d_insufficient(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_margin_interest",
        payloads=[
            {
                "Date": "2025-04-01",
                "Code": CODES[0],
                "LongVol": 100.0,
                "ShrtVol": 0.0,
            },
        ],
    )
    out = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_short_ratio_level_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_short_ratio",
        payloads=[
            {
                "Date": "2025-04-01",
                "S33": "0050",
                "SellExShortVa": 1000.0,
                "ShrtWithResVa": 100.0,
                "ShrtNoResVa": 50.0,
            },
            {
                "Date": "2025-04-02",
                "S33": "0050",
                "SellExShortVa": 200.0,
                "ShrtWithResVa": 40.0,
                "ShrtNoResVa": 10.0,
            },
            {
                "Date": "2025-04-02",
                "S33": "1050",
                "SellExShortVa": 999.0,
                "ShrtWithResVa": 1.0,
                "ShrtNoResVa": 1.0,
            },
        ],
    )
    out = compute(
        "short_ratio_level",
        as_of=close_iso("2025-04-02"),
        section="0050",
        db_path=db,
    )
    # Latest for 0050: (40+10)/200 = 0.25
    assert out.value == pytest.approx(0.25)
    assert out.metadata["datasets"] == ["markets_short_ratio"]
    assert out.metadata["section"] == "0050"
    assert out.metadata["date"] == "2025-04-02"


def test_short_ratio_level_missing_section(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "short_ratio_level",
        as_of=close_iso(days[0]),
        section="9999",
        db_path=db,
    )
    assert out.value is None
    assert "no short_ratio" in out.metadata["reason"]


def test_is_trading_day_on_seeded_calendar(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    # coreseed marks seeded days as holiday_division == "1"
    out = compute(
        "is_trading_day",
        as_of=close_iso("2025-04-01"),
        db_path=db,
    )
    assert out.value == 1.0
    assert out.metadata["date"] == "2025-04-01"
    assert out.metadata["datasets"] == ["markets_calendar"]

    # Explicit non-trading date with no row → None
    out_miss = compute(
        "is_trading_day",
        as_of=close_iso("2025-04-01"),
        date="2099-01-01",
        db_path=db,
    )
    assert out_miss.value is None
    assert out_miss.metadata["date"] == "2099-01-01"


def test_is_trading_day_non_trading_division(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    # Override calendar row to non-trading.
    store = SqliteStore(db)
    store.upsert(
        "jquants_market_calendar",
        [
            {
                "source": "jquants",
                "date": "2025-04-06",
                "event_time": "2025-04-06T09:00:00+09:00",
                "available_at": "2025-01-01T00:00:00+09:00",
                "ingested_at": "2025-01-01T00:00:00+09:00",
                "holiday_division": "0",
            }
        ],
    )
    store.close()
    out = compute(
        "is_trading_day",
        as_of=close_iso("2025-04-06"),
        date="2025-04-06",
        db_path=db,
    )
    assert out.value == 0.0


def test_repo_rate_level_on_seeded_rates(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_repo_rates(
        db,
        [
            {
                "source": "jsda",
                "as_of_date": "2025-04-01",
                "tenor": "overnight",
                "rate_type": "東京レポ・レート",
                "event_time": "2025-04-01T15:00:00+09:00",
                "available_at": close_iso("2025-04-01"),
                "ingested_at": close_iso("2025-04-01"),
                "rate": 0.10,
            },
            {
                "source": "jsda",
                "as_of_date": "2025-04-02",
                "tenor": "overnight",
                "rate_type": "東京レポ・レート",
                "event_time": "2025-04-02T15:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "rate": 0.15,
            },
        ],
    )
    out = compute(
        "repo_rate_level",
        as_of=close_iso("2025-04-02"),
        tenor="overnight",
        db_path=db,
    )
    assert out.value == pytest.approx(0.15)
    assert out.metadata["datasets"] == ["jsda_tokyo_repo_rates"]
    assert out.metadata["as_of_date"] == "2025-04-02"

    # PIT: earlier as_of hides the later rate.
    out_early = compute(
        "repo_rate_level",
        as_of=close_iso("2025-04-01"),
        tenor="overnight",
        db_path=db,
    )
    assert out_early.value == pytest.approx(0.10)


def test_repo_rate_level_empty_is_none(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "repo_rate_level",
        as_of=close_iso(days[0]),
        db_path=db,
    )
    assert out.value is None
    assert "no repo" in out.metadata["reason"]


def test_return_1d_c21_matches_simple_return_on_seeded_bars(tmp_path):
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "return_1d_c21",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx((102.0 - 101.0) / 101.0)
    assert out.metadata["feature_id"] == "return_1d_c21"
    assert out.metadata["datasets"] == ["equities_bars_daily"]
    assert out.metadata["export_of"] == "return_1d"
    assert out.metadata["path"] == "complete21_min"
    # Parity with approved v0 return_1d (same formula, different id/status).
    v0 = compute(
        "return_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(v0.value)
    assert get("return_1d_c21").status == "candidate"
    assert get("return_1d").status == "approved"


def test_return_1d_c21_insufficient_history(tmp_path):
    day = "2025-04-01"
    db = seed_db(
        tmp_path,
        days=[day],
        prices={CODES[0]: {day: 100.0}},
    )
    out = compute(
        "return_1d_c21",
        as_of=close_iso(day),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_margin_alert_flag_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_margin_alert",
        payloads=[
            {
                "Code": CODES[0],
                "PubDate": "2025-04-01",
                "AppDate": "2025-04-01",
                "Date": "2025-04-01",
            },
        ],
    )
    out = compute(
        "margin_alert_flag",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == 1.0
    assert out.metadata["datasets"] == ["markets_margin_alert"]
    assert out.metadata["feature_id"] == "margin_alert_flag"
    assert out.metadata["rows_seen"] >= 1


def test_margin_alert_flag_empty_is_zero(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "margin_alert_flag",
        as_of=close_iso(days[0]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == 0.0
    assert out.metadata["rows_seen"] == 0


def test_futures_activity_proxy_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="derivatives_bars_daily_futures",
        payloads=[
            {
                "Date": "2025-04-01",
                "Code": "160060019",
                "Volume": 100.0,
                "Close": 27000.0,
            },
            {
                "Date": "2025-04-02",
                "Code": "160060019",
                "Volume": 200.0,
                "Close": 27100.0,
            },
            {
                "Date": "2025-04-02",
                "Code": "160060020",
                "Volume": 50.0,
                "Close": 100.0,
            },
        ],
    )
    # All contracts: latest date sum = 200 + 50 = 250
    out = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-02"),
        db_path=db,
    )
    assert out.value == pytest.approx(250.0)
    assert out.metadata["datasets"] == ["derivatives_bars_daily_futures"]
    assert out.metadata["activity_date"] == "2025-04-02"
    assert out.metadata["contracts_on_date"] == 2

    # Optional code filter
    out_one = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-02"),
        code="160060019",
        db_path=db,
    )
    assert out_one.value == pytest.approx(200.0)


def test_futures_activity_proxy_empty_is_none(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "futures_activity_proxy",
        as_of=close_iso(days[0]),
        db_path=db,
    )
    assert out.value is None
    assert "no futures" in out.metadata["reason"]

