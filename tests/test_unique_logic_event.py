"""Event unique_logic min-impl (not catalog remaps)."""

from __future__ import annotations

import pytest

from research.unique_logic import event
from research.unique_logic.constants import EVENT_LOGIC_IDS
from tests.research_eval_util import (
    _event_bars,
    _event_eval_kw,
    _logic_spec,
    _two_name_events,
    _with_min_hist,
    assert_unique_family_specs,
)


def _spec(lid: str) -> dict:
    return _logic_spec(event.NEW_UNIQUE_LOGIC, lid)


def test_event_proposals_are_new_unique_logic_not_catalog_remaps():
    from research.unique_logic.catalog import yaml_unique_rows

    assert_unique_family_specs(list(event.NEW_UNIQUE_LOGIC), EVENT_LOGIC_IDS)
    ids = [s["logic_id"] for s in event.NEW_UNIQUE_LOGIC]
    rows = yaml_unique_rows(logic_ids=ids)
    assert [r["logic_id"] for r in rows] == ids


def test_pit_median_is_strictly_prior_dates():
    series = {"2019-01-01": 1.0, "2019-01-02": 3.0, "2019-01-03": 5.0}
    med = event.pit_median_on_dates(series, ["2019-01-01", "2019-01-02", "2019-01-03"], min_hist=2)
    assert med["2019-01-01"] is None
    assert med["2019-01-02"] is None  # only 1 prior
    assert med["2019-01-03"] == pytest.approx(2.0)  # median(1,3)


def test_event_funding_stress_skip_skips_missing_overnight_no_ffill():
    # Overnight only on some dates; 2019-01-10 (same-day pre-close entry) missing.
    overnight = {f"2019-01-{d:02d}": 0.01 for d in range(1, 9)}
    pack = event.evaluate_event_funding_stress_skip_daily_mtm(
        _event_bars(),
        _two_name_events(),
        overnight,
        **_event_eval_kw(spec=_with_min_hist(_spec("event_funding_stress_skip"))),
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("n_skip_missing_overnight", 0) >= 1
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False
    assert pack.get("go") is False


def test_event_funding_stress_skip_skips_when_overnight_ge_median():
    overnight = {f"2019-01-{d:02d}": 0.01 for d in range(1, 28)}
    overnight["2019-01-10"] = 0.50  # stress vs 0.01 history
    overnight["2019-01-12"] = 0.50
    pack = event.evaluate_event_funding_stress_skip_daily_mtm(
        _event_bars(),
        _two_name_events(),
        overnight,
        **_event_eval_kw(spec=_with_min_hist(_spec("event_funding_stress_skip"))),
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_skip_funding_stress", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("new_unique_logic") is True


def test_curve_steep_event_confirm_skips_non_steep_or_gap():
    curve = {
        "spread_by_date": {
            "2019-01-10": -0.05,  # inverted
            # 2019-01-12 missing → gap, no ffill
        }
    }
    pack = event.evaluate_curve_steep_event_confirm_daily_mtm(
        _event_bars(),
        _two_name_events(),
        curve,
        **_event_eval_kw(spec=_spec("curve_steep_event_confirm")),
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("n_skip_not_steep", 0) >= 1
    assert pack.get("n_skip_curve_gap", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("catalog") is False


def test_curve_steep_empty_series_is_incomplete_not_approximated():
    pack = event.evaluate_curve_steep_event_confirm_daily_mtm(
        _event_bars(),
        _two_name_events(),
        {"spread_by_date": {}},
        **_event_eval_kw(with_period=False, spec=_spec("curve_steep_event_confirm")),
    )
    assert pack.get("daily_path_complete") is False
    assert "Not approximated" in str(pack.get("incomplete_reason") or "")
