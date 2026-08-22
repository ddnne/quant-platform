"""Event-filter unique_logic min-impl (not catalog remaps)."""

from __future__ import annotations

import pytest

from research.offline.factory import propose_profit_hypotheses
from research.unique_logic import event_filters


def _bars(n: int = 40, start: str = "2019-01-") -> dict[str, list[tuple[str, float]]]:
    dates = [f"{start}{d:02d}" for d in range(1, min(n, 28) + 1)]
    out: dict[str, list[tuple[str, float]]] = {}
    for ci, code in enumerate(("13010", "72030", "67580", "99840")):
        px = 100.0 + 10 * ci
        series = []
        for i, d in enumerate(dates):
            if code == "13010":
                px = px * 1.004
            elif code == "72030":
                px = px * 0.996
            else:
                px = px * (1.0 + 0.002 * ((i + ci) % 3 - 1))
            series.append((d, px))
        out[code] = series
    return out


def _events() -> dict[str, list[dict]]:
    return {
        "13010": [
            {
                "disc_date": "2019-01-10",
                "disc_time": "16:00:00",  # after close
                "eps": 12.0,
                "feps": 10.0,
                "prior_eps": 9.0,
            }
        ],
        "72030": [
            {
                "disc_date": "2019-01-12",
                "disc_time": "12:00:00",  # pre-close
                "eps": 4.0,
                "feps": 6.0,
                "prior_eps": 5.0,
            }
        ],
    }


def test_event_filters_proposals_are_new_unique_logic_not_catalog_or_prior_event():
    ids = [s["logic_id"] for s in event_filters.NEW_UNIQUE_LOGIC]
    assert ids == [
        "large_surprise_event_hold",
        "afterclose_only_event_hold",
        "event_pre_mom_agree_hold",
        "event_margin_crowding_skip",
    ]
    assert len(ids) == 4
    for s in event_filters.NEW_UNIQUE_LOGIC:
        assert s["new_unique_logic"] is True
        assert s["catalog"] is False
        assert s["catalog_map"] is None
        assert s["logic_id"] not in event_filters.LOGIC_CATALOG_HEADLINE_BAN
        assert s["logic_id"] not in event_filters.EVENT_LOGIC_IDS
        assert s["logic_id"] not in event_filters.KNOWN_WEAK_THESIS
        assert s["logic_id"] not in event_filters.KNOWN_DEMOTED_OR_WEAK
        params = s["params"]
        assert "mode" in params or "gate" in params


def test_event_filters_propose_profit_hypotheses_accepts_adhoc_no_catalog_map():
    out = propose_profit_hypotheses(
        event_filters.proposals_for_factory(),
        evaluate=False,
    )
    assert out["n_accepted"] == 4
    assert out["n_rejected"] == 0
    lids = [a["logic_id"] for a in out["accepted"]]
    assert lids == [s["logic_id"] for s in event_filters.NEW_UNIQUE_LOGIC]
    for a in out["accepted"]:
        assert a["logic_id"] not in event_filters.LOGIC_CATALOG_HEADLINE_BAN
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
    bars = _bars()
    # Build enough prior |surprise| history so median forms, then a small one.
    events: dict[str, list[dict]] = {"13010": [], "72030": []}
    for i in range(1, 22):
        events["13010"].append(
            {
                "disc_date": f"2018-12-{i:02d}" if i <= 20 else "2019-01-10",
                "disc_time": "16:00:00",
                "eps": 20.0,
                "feps": 10.0,  # |surprise| = 10
                "prior_eps": 9.0,
            }
        )
    # Replace last with a tiny surprise on 2019-01-10 (in-shard).
    events["13010"][-1] = {
        "disc_date": "2019-01-10",
        "disc_time": "16:00:00",
        "eps": 10.1,
        "feps": 10.0,  # |surprise| = 0.1 << 10
        "prior_eps": 9.0,
    }
    spec = dict(event_filters.NEW_UNIQUE_LOGIC[0])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = 5
    spec["min_hist"] = 5
    pack = event_filters.evaluate_large_surprise_event_hold_daily_mtm(
        bars,
        events,
        spec=spec,
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False
    assert pack.get("go") is False
    assert pack.get("n_skip_small_surprise", 0) >= 1
    assert pack.get("n_entered", 0) == 0


def test_afterclose_skips_preclose_and_missing_disctime():
    bars = _bars()
    events = _events()
    events["13010"][0]["disc_time"] = None  # missing → skip
    pack = event_filters.evaluate_afterclose_only_event_hold_daily_mtm(
        bars,
        events,
        spec=event_filters.NEW_UNIQUE_LOGIC[1],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("n_skip_missing_disctime", 0) >= 1
    assert pack.get("n_skip_preclose", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("catalog") is False


def test_afterclose_accepts_post_session_close():
    bars = _bars()
    events = {
        "13010": [
            {
                "disc_date": "2019-01-10",
                "disc_time": "16:30:00",
                "eps": 12.0,
                "feps": 10.0,
                "prior_eps": 9.0,
            }
        ]
    }
    pack = event_filters.evaluate_afterclose_only_event_hold_daily_mtm(
        bars,
        events,
        spec=event_filters.NEW_UNIQUE_LOGIC[1],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_entered", 0) == 1
    assert pack.get("new_unique_logic") is True


def test_event_pre_mom_agree_skips_disagreement():
    bars = _bars()
    # 72030 is built with downward drift; give it a POSITIVE surprise.
    events = {
        "72030": [
            {
                "disc_date": "2019-01-12",
                "disc_time": "16:00:00",
                "eps": 10.0,
                "feps": 12.0,  # FEPS-EPS = +2 vs downward mom
                "prior_eps": 9.0,
            }
        ]
    }
    pack = event_filters.evaluate_event_pre_mom_agree_hold_daily_mtm(
        bars,
        events,
        spec=event_filters.NEW_UNIQUE_LOGIC[2],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_skip_mom_disagree", 0) + pack.get("n_skip_mom_history", 0) >= 1
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False


def test_event_margin_crowding_skips_missing_and_empty_is_incomplete():
    bars = _bars()
    events = _events()
    empty = event_filters.evaluate_event_margin_crowding_skip_daily_mtm(
        bars,
        events,
        {},
        spec=event_filters.NEW_UNIQUE_LOGIC[3],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert empty.get("daily_path_complete") is False
    assert "Not approximated" in str(empty.get("incomplete_reason") or "")

    # Margin only on 72030; 13010 missing → skip. 72030 crowded vs its median.
    margin = {
        "72030": {f"2019-01-{d:02d}": 100.0 for d in range(1, 12)},
    }
    margin["72030"]["2019-01-11"] = 500.0  # last print before 01-12 entry, crowded
    spec = dict(event_filters.NEW_UNIQUE_LOGIC[3])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = 5
    spec["min_hist"] = 5
    pack = event_filters.evaluate_event_margin_crowding_skip_daily_mtm(
        bars,
        events,
        margin,
        spec=spec,
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("n_skip_missing_margin", 0) >= 1
    assert pack.get("n_skip_margin_crowded", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("go") is False
