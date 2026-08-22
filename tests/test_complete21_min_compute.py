"""COMPLETE 21 min features — PIT gates + seeded compute.

Rows with ``available_at > as_of`` must not affect values. Seeded paths
cover positive / empty / insufficient history for each min feature.
Shared builders: ``tests/complete21_min_util.py``.
"""

from __future__ import annotations

import pytest

from features import get
from storage.sqlite_store import SqliteStore

from tests.complete21_min_util import (
    CODES,
    _alert_row,
    _const_px,
    _feat,
    _fins_row,
    _fut_row,
    _margin_row,
    _ramp,
    _repo_row,
    _seed_c21,
    _seed_feat,
    _seed_payloads,
    _short_ratio_payload,
    _topix_row,
)


def test_pit_gate_hides_future_available_at_margin_and_disclosure(tmp_path):
    """PIT: rows with available_at > as_of must not affect feature values."""
    _days, db = _seed_payloads(
        tmp_path,
        {
            "markets_margin_interest": [
                _margin_row("2025-04-01", 100.0),
                _margin_row("2025-04-02", 200.0),
            ],
            "fins_summary": [_fins_row("2025-04-02", NetSales=1)],
        },
    )
    # D1 margin obs visible at as_of=D1; D2 published at D2 close only.
    margin_early = _feat(
        "margin_interest_change_1d", db, "2025-04-01", code=CODES[0]
    )
    assert margin_early.value is None
    assert "insufficient" in margin_early.metadata["reason"]

    disc_early = _feat("disclosure_flag_fins", db, "2025-04-01", code=CODES[0])
    assert disc_early.value == 0.0

    margin_late = _feat(
        "margin_interest_change_1d", db, "2025-04-02", code=CODES[0]
    )
    assert margin_late.value == pytest.approx(1.0)  # 100 → 200

    disc_late = _feat("disclosure_flag_fins", db, "2025-04-02", code=CODES[0])
    assert disc_late.value == 1.0


def test_pit_gate_hides_future_short_ratio_and_margin_alert(tmp_path):
    _days, db = _seed_payloads(
        tmp_path,
        {
            "markets_short_ratio": [
                _short_ratio_payload("2025-04-02", "0050", 200.0, 40.0, 10.0),
            ],
            "markets_margin_alert": [_alert_row("2025-04-02")],
        },
    )
    short_early = _feat("short_ratio_level", db, "2025-04-01", section="0050")
    assert short_early.value is None

    alert_early = _feat("margin_alert_flag", db, "2025-04-01", code=CODES[0])
    assert alert_early.value == 0.0

    short_late = _feat("short_ratio_level", db, "2025-04-02", section="0050")
    assert short_late.value == pytest.approx(0.25)

    alert_late = _feat("margin_alert_flag", db, "2025-04-02", code=CODES[0])
    assert alert_late.value == 1.0


def test_pit_gate_hides_future_futures_activity(tmp_path):
    _days, db = _seed_payloads(
        tmp_path,
        {
            "derivatives_bars_daily_futures": [
                _fut_row("2025-04-02", "160060019", 500.0, 28000.0),
            ]
        },
    )
    early = _feat("futures_activity_proxy", db, "2025-04-01")
    assert early.value is None
    late = _feat("futures_activity_proxy", db, "2025-04-02")
    assert late.value == pytest.approx(500.0)


def test_volume_change_1d_on_seeded_bars(tmp_path):
    """Seed volumes are constant 1000 → change 0.0 with >=2 sessions."""
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    out, _, _ = _seed_feat(
        tmp_path, "volume_change_1d", days=days, prices=_ramp(days), code=CODES[0]
    )
    assert out.value == pytest.approx(0.0)
    assert out.metadata["feature_id"] == "volume_change_1d"
    assert out.metadata["datasets"] == ["equities_bars_daily"]
    assert out.metadata["rows_seen"] >= 2


def test_volume_change_1d_insufficient_history(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path, "volume_change_1d", days=["2025-04-01"], code=CODES[0]
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_topix_relative_1d_seeded_dual_leg(tmp_path):
    """W53: dual-leg integration — equity return minus TOPIX return on seeded DB."""
    days = ["2025-04-01", "2025-04-02"]
    out, _, _ = _seed_feat(
        tmp_path,
        "topix_relative_1d",
        days=days,
        prices={CODES[0]: {"2025-04-01": 100.0, "2025-04-02": 110.0}},
        payloads={
            "indices_bars_daily_topix": [
                _topix_row("2025-04-01", 3000.0),
                _topix_row("2025-04-02", 3030.0),
            ]
        },
        code=CODES[0],
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
    out, _, _ = _seed_feat(
        tmp_path, "topix_relative_1d", days=days, prices=_ramp(days), code=CODES[0]
    )
    assert out.value is None
    assert "missing" in out.metadata["reason"]


def test_disclosure_flag_fins_empty_db_is_zero(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    out, _, _ = _seed_feat(
        tmp_path,
        "disclosure_flag_fins",
        days=days,
        prices=_const_px(days),
        code=CODES[0],
    )
    # No fins_summary rows in coreseed → flag 0.0
    assert out.value == 0.0
    assert out.metadata["rows_seen"] == 0
    assert out.metadata["datasets"] == ["fins_summary"]


def test_disclosure_flag_fins_seeded_positive(tmp_path):
    """W53: positive path — any PIT-visible fins_summary row → 1.0."""
    days = ["2025-04-01", "2025-04-02"]
    out, _, _ = _seed_feat(
        tmp_path,
        "disclosure_flag_fins",
        days=days,
        prices=_const_px(days),
        payloads={"fins_summary": [_fins_row("2025-04-02", NetSales=123)]},
        code=CODES[0],
    )
    assert out.value == 1.0
    assert out.metadata["rows_seen"] >= 1
    assert out.metadata["feature_id"] == "disclosure_flag_fins"


def test_v0_return_1d_still_works_with_guard(tmp_path):
    """Pipeline DEFER guard must not break existing COMPLETE bars features."""
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    out, _, _ = _seed_feat(
        tmp_path, "return_1d", days=days, prices=_ramp(days), code=CODES[0]
    )
    assert out.value == pytest.approx((102.0 - 101.0) / 101.0)


def test_margin_interest_change_1d_on_seeded_records(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path,
        "margin_interest_change_1d",
        payloads={
            "markets_margin_interest": [
                _margin_row("2025-04-01", 100.0, 50.0),
                _margin_row("2025-04-08", 130.0, 50.0),
            ]
        },
        as_of="2025-04-08",
        code=CODES[0],
    )
    # Total 150 → 180 = +20%
    assert out.value == pytest.approx(0.20)
    assert out.metadata["datasets"] == ["markets_margin_interest"]
    assert out.metadata["feature_id"] == "margin_interest_change_1d"
    assert out.metadata["rows_seen"] == 2


def test_margin_interest_change_1d_insufficient(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path,
        "margin_interest_change_1d",
        days=["2025-04-01"],
        payloads={
            "markets_margin_interest": [_margin_row("2025-04-01", 100.0)],
        },
        code=CODES[0],
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_short_ratio_level_on_seeded_records(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path,
        "short_ratio_level",
        payloads={
            "markets_short_ratio": [
                _short_ratio_payload("2025-04-01", "0050", 1000.0, 100.0, 50.0),
                _short_ratio_payload("2025-04-02", "0050", 200.0, 40.0, 10.0),
                _short_ratio_payload("2025-04-02", "1050", 999.0, 1.0, 1.0),
            ]
        },
        section="0050",
    )
    # Latest for 0050: (40+10)/200 = 0.25
    assert out.value == pytest.approx(0.25)
    assert out.metadata["datasets"] == ["markets_short_ratio"]
    assert out.metadata["section"] == "0050"
    assert out.metadata["date"] == "2025-04-02"


def test_short_ratio_level_missing_section(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path, "short_ratio_level", days=["2025-04-01"], section="9999"
    )
    assert out.value is None
    assert "no short_ratio" in out.metadata["reason"]


def test_is_trading_day_on_seeded_calendar(tmp_path):
    _days, db = _seed_c21(tmp_path)
    # coreseed marks seeded days as holiday_division == "1"
    out = _feat("is_trading_day", db, "2025-04-01")
    assert out.value == 1.0
    assert out.metadata["date"] == "2025-04-01"
    assert out.metadata["datasets"] == ["markets_calendar"]

    out_miss = _feat("is_trading_day", db, "2025-04-01", date="2099-01-01")
    assert out_miss.value is None
    assert out_miss.metadata["date"] == "2099-01-01"


def test_is_trading_day_non_trading_division(tmp_path):
    _days, db = _seed_c21(tmp_path, ["2025-04-01"])
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
    out = _feat("is_trading_day", db, "2025-04-06", date="2025-04-06")
    assert out.value == 0.0


def test_repo_rate_level_on_seeded_rates(tmp_path):
    _days, db = _seed_payloads(
        tmp_path,
        repo=[_repo_row("2025-04-01", 0.10), _repo_row("2025-04-02", 0.15)],
    )
    out = _feat("repo_rate_level", db, "2025-04-02", tenor="overnight")
    assert out.value == pytest.approx(0.15)
    assert out.metadata["datasets"] == ["jsda_tokyo_repo_rates"]
    assert out.metadata["as_of_date"] == "2025-04-02"

    out_early = _feat("repo_rate_level", db, "2025-04-01", tenor="overnight")
    assert out_early.value == pytest.approx(0.10)


def test_repo_rate_level_empty_is_none(tmp_path):
    out, _, _ = _seed_feat(tmp_path, "repo_rate_level", days=["2025-04-01"])
    assert out.value is None
    assert "no repo" in out.metadata["reason"]


def test_return_1d_c21_matches_simple_return_on_seeded_bars(tmp_path):
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    out, _, db = _seed_feat(
        tmp_path, "return_1d_c21", days=days, prices=_ramp(days), code=CODES[0]
    )
    assert out.value == pytest.approx((102.0 - 101.0) / 101.0)
    assert out.metadata["feature_id"] == "return_1d_c21"
    assert out.metadata["datasets"] == ["equities_bars_daily"]
    assert out.metadata["export_of"] == "return_1d"
    assert out.metadata["path"] == "complete21_min"
    v0 = _feat("return_1d", db, days[-1], code=CODES[0])
    assert out.value == pytest.approx(v0.value)
    assert get("return_1d_c21").status == "candidate"
    assert get("return_1d").status == "approved"


def test_return_1d_c21_insufficient_history(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path, "return_1d_c21", days=["2025-04-01"], code=CODES[0]
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_margin_alert_flag_on_seeded_records(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path,
        "margin_alert_flag",
        payloads={"markets_margin_alert": [_alert_row("2025-04-01")]},
        as_of="2025-04-01",
        code=CODES[0],
    )
    assert out.value == 1.0
    assert out.metadata["datasets"] == ["markets_margin_alert"]
    assert out.metadata["feature_id"] == "margin_alert_flag"
    assert out.metadata["rows_seen"] >= 1


def test_margin_alert_flag_empty_is_zero(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path, "margin_alert_flag", days=["2025-04-01"], code=CODES[0]
    )
    assert out.value == 0.0
    assert out.metadata["rows_seen"] == 0


def test_futures_activity_proxy_on_seeded_records(tmp_path):
    _days, db = _seed_payloads(
        tmp_path,
        {
            "derivatives_bars_daily_futures": [
                _fut_row("2025-04-01", "160060019", 100.0, 27000.0),
                _fut_row("2025-04-02", "160060019", 200.0, 27100.0),
                _fut_row("2025-04-02", "160060020", 50.0, 100.0),
            ]
        },
    )
    # All contracts: latest date sum = 200 + 50 = 250
    out = _feat("futures_activity_proxy", db, "2025-04-02")
    assert out.value == pytest.approx(250.0)
    assert out.metadata["datasets"] == ["derivatives_bars_daily_futures"]
    assert out.metadata["activity_date"] == "2025-04-02"
    assert out.metadata["contracts_on_date"] == 2

    out_one = _feat("futures_activity_proxy", db, "2025-04-02", code="160060019")
    assert out_one.value == pytest.approx(200.0)


def test_futures_activity_proxy_empty_is_none(tmp_path):
    out, _, _ = _seed_feat(
        tmp_path, "futures_activity_proxy", days=["2025-04-01"]
    )
    assert out.value is None
    assert "no futures" in out.metadata["reason"]
