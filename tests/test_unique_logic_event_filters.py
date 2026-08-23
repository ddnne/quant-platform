"""Event-filter unique_logic min-impl (not catalog remaps)."""

from __future__ import annotations

import pytest

from research.unique_logic import event_filters
from research.unique_logic.constants import EVENT_FILTER_LOGIC_IDS, EVENT_LOGIC_IDS
from tests.research_eval_util import (
    _disc_event,
    _event_bars,
    _event_eval_kw,
    _logic_spec,
    _two_name_events,
    _with_min_hist,
    assert_unique_family_specs,
)


def _bars():
    return _event_bars(mode="filter")


def _spec(lid: str) -> dict:
    return _logic_spec(event_filters.NEW_UNIQUE_LOGIC, lid)


def test_event_filters_proposals_are_new_unique_logic_not_catalog_or_prior_event():
    assert_unique_family_specs(
        list(event_filters.NEW_UNIQUE_LOGIC),
        EVENT_FILTER_LOGIC_IDS,
        disjoint_from=(EVENT_LOGIC_IDS,),
    )


def test_pit_median_from_pairs_keeps_same_date_multiset():
    pairs = [
        ("2019-01-01", 1.0),
        ("2019-01-01", 3.0),
        ("2019-01-02", 5.0),
    ]
    med = event_filters.pit_median_from_pairs(
        pairs, ["2019-01-01", "2019-01-02", "2019-01-03"], min_hist=2
    )
    assert med["2019-01-01"] is None
    assert med["2019-01-02"] == pytest.approx(2.0)  # median(1,3)
    assert med["2019-01-03"] == pytest.approx(3.0)  # median(1,3,5)


def test_large_surprise_skips_below_pit_median():
    # Enough prior |surprise| history so median forms, then a small in-shard print.
    events: dict[str, list[dict]] = {"13010": [], "72030": []}
    for i in range(1, 22):
        events["13010"].append(
            _disc_event(
                f"2018-12-{i:02d}" if i <= 20 else "2019-01-10",
                disc_time="16:00:00",
                eps=20.0,
                feps=10.0,
                prior_eps=9.0,
            )
        )
    events["13010"][-1] = _disc_event(
        "2019-01-10",
        disc_time="16:00:00",
        eps=10.1,
        feps=10.0,
        prior_eps=9.0,
    )
    pack = event_filters.evaluate_large_surprise_event_hold_daily_mtm(
        _bars(),
        events,
        **_event_eval_kw(spec=_with_min_hist(_spec("large_surprise_event_hold"))),
    )
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False
    assert pack.get("go") is False
    assert pack.get("n_skip_small_surprise", 0) >= 1
    assert pack.get("n_entered", 0) == 0


def test_afterclose_skips_preclose_and_missing_disctime():
    pack = event_filters.evaluate_afterclose_only_event_hold_daily_mtm(
        _bars(),
        _two_name_events(t13010=None),
        **_event_eval_kw(spec=_spec("afterclose_only_event_hold")),
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("n_skip_missing_disctime", 0) >= 1
    assert pack.get("n_skip_preclose", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("catalog") is False


def test_afterclose_accepts_post_session_close():
    pack = event_filters.evaluate_afterclose_only_event_hold_daily_mtm(
        _bars(),
        {
            "13010": [
                _disc_event(
                    "2019-01-10",
                    disc_time="16:30:00",
                    eps=12.0,
                    feps=10.0,
                    prior_eps=9.0,
                )
            ]
        },
        **_event_eval_kw(spec=_spec("afterclose_only_event_hold")),
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_entered", 0) == 1
    assert pack.get("new_unique_logic") is True


def test_event_pre_mom_agree_skips_disagreement():
    # 72030 has downward drift; POSITIVE surprise (FEPS-EPS = +2) disagrees.
    pack = event_filters.evaluate_event_pre_mom_agree_hold_daily_mtm(
        _bars(),
        {
            "72030": [
                _disc_event(
                    "2019-01-12",
                    disc_time="16:00:00",
                    eps=10.0,
                    feps=12.0,
                    prior_eps=9.0,
                )
            ]
        },
        **_event_eval_kw(spec=_spec("event_pre_mom_agree_hold")),
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_skip_mom_disagree", 0) + pack.get("n_skip_mom_history", 0) >= 1
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False


def test_event_margin_crowding_skips_missing_and_empty_is_incomplete():
    bars = _bars()
    events = _two_name_events(t13010="16:00:00")
    empty = event_filters.evaluate_event_margin_crowding_skip_daily_mtm(
        bars,
        events,
        {},
        **_event_eval_kw(spec=_spec("event_margin_crowding_skip")),
    )
    assert empty.get("daily_path_complete") is False
    assert "Not approximated" in str(empty.get("incomplete_reason") or "")

    # Margin only on 72030; 13010 missing → skip. 72030 crowded vs its median.
    margin = {
        "72030": {f"2019-01-{d:02d}": 100.0 for d in range(1, 12)},
    }
    margin["72030"]["2019-01-11"] = 500.0  # last print before 01-12 entry, crowded
    pack = event_filters.evaluate_event_margin_crowding_skip_daily_mtm(
        bars,
        events,
        margin,
        **_event_eval_kw(spec=_with_min_hist(_spec("event_margin_crowding_skip"))),
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("n_skip_missing_margin", 0) >= 1
    assert pack.get("n_skip_margin_crowded", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("go") is False


def test_event_filter_yaml_leftover_vs_lifted_gates() -> None:
    """Unique-22 leftover still needed; occupancy-equal lifts keep params.gates."""
    from pathlib import Path

    from research.unique_logic.catalog import load_catalog_specs

    leftover = (
        "event_funding_adaptive_side",
        "event_funding_stress_ls",
        "event_pre_mom_agree_hold",
        "large_surprise_event_hold",
    )
    lifted = (
        "afterclose_only_event_hold",
        "curve_steep_event_confirm",
        "event_funding_easy_short",
        "event_funding_stress_skip",
        "event_margin_crowding_skip",
    )
    by_id = {s["logic_id"]: s for s in load_catalog_specs()}
    for lid in leftover:
        params = by_id[lid].get("params") or {}
        assert not params.get("gates"), f"{lid} leftover still needed (not comboImpl)"
    for lid in lifted:
        params = by_id[lid].get("params") or {}
        assert params.get("gates"), f"{lid} occupancy-equal lift needs params.gates"

