"""COMPLETE 21 min features — data-free pure helpers.

No SQLite / PIT. Catalog and PIT/seeded paths live in sibling modules.
"""

from __future__ import annotations

import pytest

from features.complete21_min import (
    disclosure_flag_from_count,
    futures_activity_from_volume_pairs,
    is_trading_day_from_division,
    margin_alert_flag_from_count,
    margin_interest_change_from_pairs,
    repo_rate_level_from_rows,
    short_ratio_level_from_components,
    simple_return_from_closes,
    topix_relative_from_returns,
    volume_change_from_pairs,
)


def test_volume_change_from_pairs_data_free():
    value, meta = volume_change_from_pairs(
        [("2025-04-01", 1000.0), ("2025-04-02", 1500.0)]
    )
    assert value == pytest.approx(0.5)
    assert meta["prior_volume"] == 1000.0
    assert meta["last_volume"] == 1500.0

    none_v, none_m = volume_change_from_pairs([("2025-04-01", 10.0)])
    assert none_v is None
    assert "insufficient" in none_m["reason"]

    zero_v, zero_m = volume_change_from_pairs(
        [("2025-04-01", 0.0), ("2025-04-02", 10.0)]
    )
    assert zero_v is None
    assert "zero prior" in zero_m["reason"]


def test_topix_relative_and_disclosure_helpers_data_free():
    eq, _ = simple_return_from_closes(
        [("2025-04-01", 100.0), ("2025-04-02", 110.0)]
    )
    tx, _ = simple_return_from_closes(
        [("2025-04-01", 2000.0), ("2025-04-02", 2020.0)]
    )
    rel, meta = topix_relative_from_returns(eq, tx)
    assert eq == pytest.approx(0.10)
    assert tx == pytest.approx(0.01)
    assert rel == pytest.approx(0.09)
    assert meta["equity_ret"] == pytest.approx(0.10)

    missing, m2 = topix_relative_from_returns(0.1, None)
    assert missing is None
    assert "missing" in m2["reason"]

    flag, fmeta = disclosure_flag_from_count(3)
    assert flag == 1.0
    assert fmeta["rows_seen"] == 3
    flag0, _ = disclosure_flag_from_count(0)
    assert flag0 == 0.0


def test_margin_interest_change_helper_data_free():
    value, meta = margin_interest_change_from_pairs(
        [("2025-04-01", 100.0), ("2025-04-08", 120.0)]
    )
    assert value == pytest.approx(0.20)
    assert meta["prior_margin"] == 100.0
    assert meta["last_margin"] == 120.0

    none_v, none_m = margin_interest_change_from_pairs([("2025-04-01", 10.0)])
    assert none_v is None
    assert "insufficient" in none_m["reason"]

    zero_v, zero_m = margin_interest_change_from_pairs(
        [("2025-04-01", 0.0), ("2025-04-08", 10.0)]
    )
    assert zero_v is None
    assert "zero prior" in zero_m["reason"]


def test_short_ratio_level_helper_data_free():
    ratio, meta = short_ratio_level_from_components(40.0, 10.0, 200.0)
    assert ratio == pytest.approx(0.25)
    assert meta["sell_ex_short"] == 200.0

    none_v, none_m = short_ratio_level_from_components(1.0, 2.0, 0.0)
    assert none_v is None
    assert "denominator" in none_m["reason"]

    # Missing short legs treated as zero numerator.
    ratio0, _ = short_ratio_level_from_components(None, None, 100.0)
    assert ratio0 == pytest.approx(0.0)


def test_is_trading_day_helper_data_free():
    yes, m1 = is_trading_day_from_division("1")
    assert yes == 1.0
    no, m2 = is_trading_day_from_division("0")
    assert no == 0.0
    miss, m3 = is_trading_day_from_division(None)
    assert miss is None
    assert "no calendar" in m3["reason"]


def test_repo_rate_level_helper_data_free():
    rate, meta = repo_rate_level_from_rows(
        [
            {"as_of_date": "2025-04-01", "rate": 0.10, "tenor": "overnight"},
            {"as_of_date": "2025-04-02", "rate": 0.12, "tenor": "overnight"},
        ]
    )
    assert rate == pytest.approx(0.12)
    assert meta["as_of_date"] == "2025-04-02"

    none_v, none_m = repo_rate_level_from_rows([])
    assert none_v is None
    assert "no repo" in none_m["reason"]


def test_margin_alert_and_futures_helpers_data_free():
    flag, meta = margin_alert_flag_from_count(2)
    assert flag == 1.0
    assert meta["rows_seen"] == 2
    flag0, _ = margin_alert_flag_from_count(0)
    assert flag0 == 0.0

    activity, ameta = futures_activity_from_volume_pairs(
        [
            ("2025-04-01", 100.0),
            ("2025-04-02", 50.0),
            ("2025-04-02", 75.0),
        ]
    )
    assert activity == pytest.approx(125.0)
    assert ameta["activity_date"] == "2025-04-02"
    assert ameta["contracts_on_date"] == 2

    none_v, none_m = futures_activity_from_volume_pairs([])
    assert none_v is None
    assert "no futures" in none_m["reason"]

