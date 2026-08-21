"""W106 / w0820c — funding/surprise L/S min variants (not a kill)."""

from __future__ import annotations

import sys
from pathlib import Path

from research.mass_strategy_factory import (
    FROZEN_DEFAULT_PATH,
    RESEARCH_FAMILY_APPEND_LOGIC_IDS,
    RESEARCH_UNIQUE_LOGIC_IDS,
    propose_profit_hypotheses,
)

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_w104_new_hyps_daily_dd as w104  # noqa: E402
import run_w106_funding_surprise_ls as w106  # noqa: E402


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


def _overnight(*, stress_on: frozenset[str] | None = None) -> dict[str, float]:
    """History 5bp so event-day 1bp is strictly easy; stress_on dates 50bp."""
    stress_on = stress_on or frozenset()
    out = {f"2019-01-{d:02d}": 0.05 for d in range(1, 28)}
    out["2019-01-10"] = 0.01
    out["2019-01-12"] = 0.01
    for d in stress_on:
        out[d] = 0.50
    return out


def _funding_spec(spec: dict) -> dict:
    out = dict(spec)
    params = dict(spec.get("params") or {})
    params["min_hist"] = 5
    out["params"] = params
    out["min_hist"] = 5
    return out


def test_w106_ls_variants_are_min_impl_not_grid_or_kill():
    ids = [s["logic_id"] for s in w106.NEW_LS_VARIANTS]
    assert ids == [
        "event_funding_easy_short",
        "event_funding_stress_ls",
        "surprise_xs_rank_flip",
    ]
    assert len(ids) == 3
    assert set(ids) <= set(RESEARCH_UNIQUE_LOGIC_IDS)
    for s in w106.NEW_LS_VARIANTS:
        assert s["new_unique_logic"] is True
        assert s["catalog"] is False
        assert s["catalog_map"] is None
        assert s["parent_logic_id"] in w106.PARENT_LOGIC_IDS
        assert s["logic_id"] in RESEARCH_UNIQUE_LOGIC_IDS
        assert s["logic_id"] not in w106.LOGIC_CATALOG_HEADLINE_BAN
        assert s["variant_kind"] in {"sign_flip_short_side", "conditional_ls"}


def test_w106_propose_accepts_ls_no_catalog_map():
    out = propose_profit_hypotheses(
        w106.proposals_for_factory(),
        evaluate=False,
    )
    assert out["n_accepted"] == 3
    assert out["n_rejected"] == 0
    lids = [a["logic_id"] for a in out["accepted"]]
    assert lids == [s["logic_id"] for s in w106.NEW_LS_VARIANTS]
    for a in out["accepted"]:
        assert a.get("eval_mapped_to_catalog") in (None, False)
        assert a.get("go") in (None, False)


def test_w106_frozen_pins_untouched():
    pack = w106._assert_frozen_pins_untouched()
    assert pack["pins_untouched"] is True
    assert pack["frozen_defaults_retuned"] is False
    assert len(FROZEN_DEFAULT_PATH) == 3


def test_easy_short_same_occupancy_flipped_sign():
    bars = _bars()
    events = _events()
    overnight = _overnight()
    parent = w104.evaluate_event_funding_stress_skip_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(w104.NEW_UNIQUE_LOGIC[0]),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    pack = w106.evaluate_event_funding_easy_short_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(w106.NEW_LS_VARIANTS[0]),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_entered") == parent.get("n_entered")
    assert pack.get("n_entered", 0) >= 1
    assert pack.get("occupancy_vs_parent") == "same_as_skip"
    assert pack.get("ffill_applied") is False
    assert pack.get("go") is False
    assert pack.get("sign_flip_is_not_a_kill") is True
    p_g = parent.get("mean_gross_daily")
    c_g = pack.get("mean_gross_daily")
    if p_g is not None and c_g is not None and abs(float(p_g)) > 1e-12:
        assert float(p_g) * float(c_g) < 0.0


def test_stress_ls_occupancy_expands_not_collapse():
    bars = _bars()
    events = _events()
    overnight = _overnight(stress_on=frozenset({"2019-01-10"}))
    parent = w104.evaluate_event_funding_stress_skip_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(w104.NEW_UNIQUE_LOGIC[0]),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    pack = w106.evaluate_event_funding_stress_ls_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(w106.NEW_LS_VARIANTS[1]),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_stress_entered", 0) >= 1
    assert int(pack.get("n_entered") or 0) >= int(parent.get("n_entered") or 0)
    assert int(pack.get("n_entered") or 0) == int(pack.get("n_easy_entered") or 0) + int(
        pack.get("n_stress_entered") or 0
    )
    assert pack.get("occupancy_vs_parent") == "expanded_vs_skip"
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("go") is False


def test_stress_ls_skips_missing_overnight_no_ffill():
    bars = _bars()
    events = _events()
    overnight = {f"2019-01-{d:02d}": 0.01 for d in range(1, 9)}
    pack = w106.evaluate_event_funding_stress_ls_daily_mtm(
        bars,
        events,
        overnight,
        spec=_funding_spec(w106.NEW_LS_VARIANTS[1]),
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("n_skip_missing_overnight", 0) >= 1
    assert pack.get("go") is False


def test_surprise_flip_same_ranked_occupancy():
    bars = _bars()
    events = _events()
    parent = w104.evaluate_surprise_xs_rank_hold_daily_mtm(
        bars,
        events,
        spec=w104.NEW_UNIQUE_LOGIC[3],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    pack = w106.evaluate_surprise_xs_rank_flip_daily_mtm(
        bars,
        events,
        spec=w106.NEW_LS_VARIANTS[2],
        one_way_cost=0.001,
        period_start="2019-01-01",
        period_end="2019-01-28",
    )
    assert pack.get("sign_flip") is True
    assert pack.get("n_ranked_days") == parent.get("n_ranked_days")
    assert pack.get("n_flat_sparse_days") == parent.get("n_flat_sparse_days")
    assert pack.get("occupancy_vs_parent") == "same_as_rank_hold"
    assert pack.get("ffill_applied") is False
    assert pack.get("go") is False
    assert pack.get("sign_flip_is_not_a_kill") is True
    # After-cost nets can share sign when turnover drag dominates a tiny book.
    # Gross active mean should flip when the parent book is not flat.
    p_g = parent.get("mean_gross_daily")
    c_g = pack.get("mean_gross_daily")
    if p_g is not None and c_g is not None and abs(float(p_g)) > 1e-12:
        assert float(p_g) * float(c_g) < 0.0
