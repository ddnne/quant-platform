"""Event-filter unique_logic min-impl (not catalog remaps)."""

from __future__ import annotations

import pytest

from research.offline.factory import propose_profit_hypotheses
from research.unique_logic import event_filters
from research.unique_logic.constants import (
    EVENT_FILTER_LOGIC_IDS,
    EVENT_LOGIC_IDS,
    KNOWN_DEMOTED_OR_WEAK,
    KNOWN_WEAK_THESIS,
    LOGIC_CATALOG_HEADLINE_BAN,
)
from tests.research_eval_util import (
    _disc_event,
    _event_bars,
    _event_eval_kw,
    _logic_spec,
    _two_name_events,
    _with_min_hist,
)


def _bars():
    return _event_bars(mode="filter")


def _spec(lid: str) -> dict:
    return _logic_spec(event_filters.NEW_UNIQUE_LOGIC, lid)


def test_event_filters_proposals_are_new_unique_logic_not_catalog_or_prior_event():
    ids = [s["logic_id"] for s in event_filters.NEW_UNIQUE_LOGIC]
    assert ids == sorted(EVENT_FILTER_LOGIC_IDS)
    assert len(ids) == 4
    for s in event_filters.NEW_UNIQUE_LOGIC:
        assert s["new_unique_logic"] is True
        assert s["catalog"] is True
        assert s["catalog_map"] is None
        assert s.get("generation_enabled") is False
        assert s.get("go") is False
        assert s["logic_id"] not in LOGIC_CATALOG_HEADLINE_BAN
        assert s["logic_id"] not in EVENT_LOGIC_IDS
        assert s["logic_id"] not in KNOWN_WEAK_THESIS
        assert s["logic_id"] not in KNOWN_DEMOTED_OR_WEAK
        params = s["params"]
        assert "mode" in params or "gate" in params


def test_event_filters_propose_profit_hypotheses_accepts_adhoc_no_catalog_map():
    out = propose_profit_hypotheses(
        event_filters.NEW_UNIQUE_LOGIC,
        evaluate=False,
    )
    assert out["n_accepted"] == 4
    assert out["n_rejected"] == 0
    lids = [a["logic_id"] for a in out["accepted"]]
    assert lids == [s["logic_id"] for s in event_filters.NEW_UNIQUE_LOGIC]
    for a in out["accepted"]:
        assert a["logic_id"] not in LOGIC_CATALOG_HEADLINE_BAN
        assert a.get("eval_mapped_to_catalog") in (None, False)


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


def test_worker_leftover_pre_mom_uses_entryidx_not_combo_pre_mom() -> None:
    """Unique-22 leftover is still needed; do not unify with combo pre_mom."""
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

    src = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "daily_path.ts"
    ).read_text(encoding="utf-8")
    leftover_block = src.split("if (!comboImpl)", 1)[1].split(
        'if (lid === "event_afterclose_delay2")', 1
    )[0]
    assert 'if (lid === "event_pre_mom_agree_hold")' in leftover_block
    agree = leftover_block.split('if (lid === "event_pre_mom_agree_hold")', 1)[1]
    assert "const i = ev.entryIdx;" in agree
    assert "ev.entryIdx - 1" not in agree
    assert "momentumAt(entryIdx)" in agree
    assert "momentumAt(pairs, 5, i)" in agree
    pre = src.split('if (gate === "pre_mom")', 1)[1].split(
        "Unknown gate fails closed", 1
    )[0]
    assert "ev.entryIdx - 1" in pre

