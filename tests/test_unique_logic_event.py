"""Event unique_logic min-impl (not catalog remaps)."""

from __future__ import annotations

import pytest

from research.offline.factory import propose_profit_hypotheses
from research.unique_logic import event


def _bars(n: int = 40, start: str = "2019-01-") -> dict[str, list[tuple[str, float]]]:
    dates = [f"{start}{d:02d}" for d in range(1, min(n, 28) + 1)]
    out: dict[str, list[tuple[str, float]]] = {}
    for ci, code in enumerate(("13010", "72030", "67580", "99840")):
        px = 100.0 + 10 * ci
        series = []
        for i, d in enumerate(dates):
            px = px * (1.0 + 0.002 * ((i + ci) % 3 - 1))
            series.append((d, px))
        out[code] = series
    return out


def _events() -> dict[str, list[dict]]:
    return {
        "13010": [
            {
                "disc_date": "2019-01-10",
                "disc_time": "12:00:00",
                "eps": 12.0,
                "feps": 10.0,
                "prior_eps": 9.0,
            }
        ],
        "72030": [
            {
                "disc_date": "2019-01-12",
                "disc_time": "12:00:00",
                "eps": 4.0,
                "feps": 6.0,
                "prior_eps": 5.0,
            }
        ],
    }


def test_event_proposals_are_new_unique_logic_not_catalog_remaps():
    ids = [s["logic_id"] for s in event.NEW_UNIQUE_LOGIC]
    assert ids == [
        "event_funding_stress_skip",
        "curve_steep_event_confirm",
        "disclosure_cluster_mom_gate",
        "surprise_xs_rank_hold",
    ]
    assert len(ids) == 4
    for s in event.NEW_UNIQUE_LOGIC:
        assert s["new_unique_logic"] is True
        assert s["catalog"] is True
        assert s["catalog_map"] is None
        assert s.get("generation_enabled") is False
        assert s.get("go") is False
        assert s["logic_id"] not in event.LOGIC_CATALOG_HEADLINE_BAN
        assert s["logic_id"] not in event.KNOWN_WEAK_THESIS
        assert s["logic_id"] not in event.KNOWN_DEMOTED_OR_WEAK
        params = s["params"]
        assert "mode" in params or "gate" in params


def test_event_new_unique_logic_is_yaml_backed():
    import inspect

    from research.unique_logic import catalog as catalog_mod
    from research.unique_logic.catalog import yaml_unique_rows

    ids = [s["logic_id"] for s in event.NEW_UNIQUE_LOGIC]
    rows = yaml_unique_rows(logic_ids=ids)
    assert [r["logic_id"] for r in rows] == ids
    src = inspect.getsource(catalog_mod.yaml_unique_rows)
    assert "NEW_UNIQUE_LOGIC" not in src
    assert "NEW_LS_VARIANTS" not in src
    assert "ADAPTIVE_VARIANTS" not in src


def test_event_propose_profit_hypotheses_accepts_adhoc_no_catalog_map():
    out = propose_profit_hypotheses(
        event.proposals_for_factory(),
        evaluate=False,
    )
    assert out["n_accepted"] == 4
    assert out["n_rejected"] == 0
    lids = [a["logic_id"] for a in out["accepted"]]
    assert lids == [s["logic_id"] for s in event.NEW_UNIQUE_LOGIC]
    for a in out["accepted"]:
        assert a["logic_id"] not in event.LOGIC_CATALOG_HEADLINE_BAN
        assert a.get("eval_mapped_to_catalog") in (None, False)


def test_pit_median_is_strictly_prior_dates():
    series = {"2019-01-01": 1.0, "2019-01-02": 3.0, "2019-01-03": 5.0}
    med = event.pit_median_on_dates(series, ["2019-01-01", "2019-01-02", "2019-01-03"], min_hist=2)
    assert med["2019-01-01"] is None
    assert med["2019-01-02"] is None  # only 1 prior
    assert med["2019-01-03"] == pytest.approx(2.0)  # median(1,3)


def _funding_spec(*, min_hist: int = 5) -> dict:
    spec = dict(event.NEW_UNIQUE_LOGIC[0])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = min_hist
    spec["min_hist"] = min_hist
    return spec


def test_event_funding_stress_skip_skips_missing_overnight_no_ffill():
    bars = _bars()
    events = _events()
    # Overnight only on some dates; 2019-01-10 (same-day pre-close entry) missing.
    overnight = {f"2019-01-{d:02d}": 0.01 for d in range(1, 9)}
    pack = event.evaluate_event_funding_stress_skip_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("n_skip_missing_overnight", 0) >= 1
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False
    assert pack.get("go") is False


def test_event_funding_stress_skip_skips_when_overnight_ge_median():
    bars = _bars()
    events = _events()
    overnight = {f"2019-01-{d:02d}": 0.01 for d in range(1, 28)}
    overnight["2019-01-10"] = 0.50  # stress vs 0.01 history
    overnight["2019-01-12"] = 0.50
    pack = event.evaluate_event_funding_stress_skip_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_skip_funding_stress", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("new_unique_logic") is True


def test_curve_steep_event_confirm_skips_non_steep_or_gap():
    bars = _bars()
    events = _events()
    curve = {
        "spread_by_date": {
            "2019-01-10": -0.05,  # inverted
            # 2019-01-12 missing → gap, no ffill
        }
    }
    pack = event.evaluate_curve_steep_event_confirm_daily_mtm(
        bars,
        events,
        curve,
        spec=event.NEW_UNIQUE_LOGIC[1],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("n_skip_not_steep", 0) >= 1
    assert pack.get("n_skip_curve_gap", 0) >= 1
    assert pack.get("n_entered", 0) == 0
    assert pack.get("catalog") is False


def test_curve_steep_empty_series_is_incomplete_not_approximated():
    pack = event.evaluate_curve_steep_event_confirm_daily_mtm(
        _bars(),
        _events(),
        {"spread_by_date": {}},
        spec=event.NEW_UNIQUE_LOGIC[1],
        one_way_cost=0.001,
    )
    assert pack.get("daily_path_complete") is False
    assert "Not approximated" in str(pack.get("incomplete_reason") or "")
