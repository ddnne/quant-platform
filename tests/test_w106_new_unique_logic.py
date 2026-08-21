"""W106 / w0820c — NEW unique_logic min-impl (mixed funding/macro/XS, not event-only)."""

from __future__ import annotations

from typing import Any

import pytest

from research.mass_strategy_factory import (
    FROZEN_DEFAULT_PATH,
    propose_profit_hypotheses,
)
from research.unique_logic import w106b as w106


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


def _overnight(*, jump_date: str = "2019-01-20", jump: float = 0.50) -> dict[str, float]:
    out = {f"2019-01-{d:02d}": 0.01 for d in range(1, 28)}
    out[jump_date] = jump
    return out


def _curve(*, steepen_date: str = "2019-01-20") -> dict[str, Any]:
    spread = {f"2019-01-{d:02d}": 0.01 for d in range(1, 28)}
    spread[steepen_date] = 0.40
    return {"spread_by_date": spread}


def _margin() -> dict[str, dict[str, float]]:
    # Two prints before mid-January so delta is defined; 13010 de-crowds, 72030 crowds.
    return {
        "13010": {"2018-12-20": 200.0, "2019-01-08": 50.0},
        "72030": {"2018-12-20": 50.0, "2019-01-08": 400.0},
        "67580": {"2018-12-20": 100.0, "2019-01-08": 110.0},
        "99840": {"2018-12-20": 100.0, "2019-01-08": 90.0},
    }


def _topix(*, quiet: bool = False) -> dict[str, float]:
    dates = [f"2019-01-{d:02d}" for d in range(1, 28)]
    px = 1500.0
    out: dict[str, float] = {}
    for i, d in enumerate(dates):
        if quiet:
            px = px * 1.0001
        else:
            # Large move around mid-month so |mom| can exceed PIT median.
            px = px * (1.02 if i >= 12 else 1.001)
        out[d] = px
    return out


def test_w106_proposals_are_new_unique_logic_mixed_not_event_only():
    ids = [s["logic_id"] for s in w106.NEW_UNIQUE_LOGIC]
    assert ids == [
        "funding_impulse_cs_tilt",
        "curve_steepen_impulse_cs",
        "xs_margin_delta_rank",
        "idio_mom_macro_impulse",
    ]
    assert len(ids) == 4
    axes = {s["axis"] for s in w106.NEW_UNIQUE_LOGIC}
    assert "funding" in axes
    assert "macro" in axes
    assert "cross_section" in axes
    assert "event" not in axes
    assert w106.PACK_BIAS == "mixed"
    for s in w106.NEW_UNIQUE_LOGIC:
        assert s["new_unique_logic"] is True
        assert s["catalog"] is False
        assert s["catalog_map"] is None
        assert s["logic_id"] not in w106.LOGIC_CATALOG_HEADLINE_BAN
        assert s["logic_id"] not in w106.W104_UNIQUE_LOGIC_IDS
        assert s["logic_id"] not in w106.W105_UNIQUE_LOGIC_IDS
        assert s["logic_id"] not in w106.KNOWN_WEAK_THESIS
        assert s["logic_id"] not in w106.KNOWN_DEMOTED_OR_WEAK
        params = s["params"]
        assert "mode" in params or "gate" in params
        # Not an event-book filter pack.
        assert "post_hold_days" not in params
        assert "fins_summary" not in s["datasets"]


def test_w106_propose_profit_hypotheses_accepts_adhoc_no_catalog_map():
    out = propose_profit_hypotheses(
        w106.proposals_for_factory(),
        evaluate=False,
    )
    assert out["n_accepted"] == 4
    assert out["n_rejected"] == 0
    lids = [a["logic_id"] for a in out["accepted"]]
    assert lids == [s["logic_id"] for s in w106.NEW_UNIQUE_LOGIC]
    for a in out["accepted"]:
        assert a["logic_id"] not in w106.LOGIC_CATALOG_HEADLINE_BAN
        assert a.get("eval_mapped_to_catalog") in (None, False)


def test_w106_frozen_pins_untouched():
    pack = w106._assert_frozen_pins_untouched()
    assert pack["pins_untouched"] is True
    assert pack["frozen_defaults_retuned"] is False
    assert len(FROZEN_DEFAULT_PATH) == 3


def test_prior_delta_by_date_uses_strictly_prior_print():
    series = {"2019-01-01": 1.0, "2019-01-03": 1.5, "2019-01-04": 1.4}
    dlt = w106.prior_delta_by_date(series)
    assert "2019-01-01" not in dlt
    assert dlt["2019-01-03"] == pytest.approx(0.5)
    assert dlt["2019-01-04"] == pytest.approx(-0.1)


def _funding_spec(*, min_hist: int = 5) -> dict:
    spec = dict(w106.NEW_UNIQUE_LOGIC[0])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = min_hist
    spec["min_hist"] = min_hist
    return spec


def test_funding_impulse_empty_overnight_is_incomplete_not_approximated():
    pack = w106.evaluate_funding_impulse_cs_tilt_daily_mtm(
        _bars(),
        {},
        spec=_funding_spec(),
        one_way_cost=0.001,
    )
    assert pack.get("daily_path_complete") is False
    assert "Not approximated" in str(pack.get("incomplete_reason") or "")
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False
    assert pack.get("go") is False


def test_funding_impulse_skips_missing_overnight_no_ffill():
    bars = _bars()
    overnight = {f"2019-01-{d:02d}": 0.01 for d in range(1, 10)}
    overnight["2019-01-20"] = 0.50  # isolated print, no ffill onto gap days
    pack = w106.evaluate_funding_impulse_cs_tilt_daily_mtm(
        bars,
        overnight,
        spec=_funding_spec(min_hist=3),
        one_way_cost=0.001,
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("invent_fill") is False
    assert pack.get("n_skip_missing_overnight", 0) >= 1
    assert pack.get("sticky_approx_always_on_gate") is False


def test_funding_impulse_tilts_fade_on_large_tightening():
    bars = _bars()
    overnight = _overnight(jump_date="2019-01-20", jump=0.80)
    pack = w106.evaluate_funding_impulse_cs_tilt_daily_mtm(
        bars,
        overnight,
        spec=_funding_spec(min_hist=5),
        one_way_cost=0.001,
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_gate_on_days", 0) >= 1
    assert pack.get("n_tilt_fade_days", 0) >= 1
    assert pack.get("new_unique_logic") is True
    assert pack.get("occupancy_frac", 1.0) < 0.85


def test_curve_steepen_empty_series_is_incomplete_not_approximated():
    pack = w106.evaluate_curve_steepen_impulse_cs_daily_mtm(
        _bars(),
        {"spread_by_date": {}},
        spec=w106.NEW_UNIQUE_LOGIC[1],
        one_way_cost=0.001,
    )
    assert pack.get("daily_path_complete") is False
    assert "Not approximated" in str(pack.get("incomplete_reason") or "")


def test_curve_steepen_skips_gap_and_flattening():
    bars = _bars()
    spec = dict(w106.NEW_UNIQUE_LOGIC[1])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = 5
    spec["min_hist"] = 5
    curve = {
        "spread_by_date": {
            f"2019-01-{d:02d}": 0.01 for d in range(1, 12)
        }
    }
    curve["spread_by_date"]["2019-01-12"] = 0.00  # flattening / not steepen
    # 2019-01-13+ missing → gap, no ffill
    pack = w106.evaluate_curve_steepen_impulse_cs_daily_mtm(
        bars,
        curve,
        spec=spec,
        one_way_cost=0.001,
    )
    assert pack.get("ffill_applied") is False
    assert pack.get("n_skip_curve_gap", 0) >= 1
    assert pack.get("n_skip_not_steepen", 0) + pack.get("n_skip_small_delta", 0) >= 1
    assert pack.get("catalog") is False
    assert pack.get("go") is False


def test_curve_steepen_turns_on_for_large_positive_delta():
    bars = _bars()
    spec = dict(w106.NEW_UNIQUE_LOGIC[1])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = 5
    spec["min_hist"] = 5
    pack = w106.evaluate_curve_steepen_impulse_cs_daily_mtm(
        bars,
        _curve(steepen_date="2019-01-20"),
        spec=spec,
        one_way_cost=0.001,
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_gate_on_days", 0) >= 1
    assert pack.get("occupancy_frac", 1.0) < 0.85
    assert pack.get("sticky_approx_always_on_gate") is False


def test_xs_margin_delta_empty_is_incomplete_not_approximated():
    pack = w106.evaluate_xs_margin_delta_rank_daily_mtm(
        _bars(),
        {},
        spec=w106.NEW_UNIQUE_LOGIC[2],
        one_way_cost=0.001,
    )
    assert pack.get("daily_path_complete") is False
    assert "Not approximated" in str(pack.get("incomplete_reason") or "")
    assert pack.get("ffill_applied") is not True


def test_xs_margin_delta_ranks_decrowd_long_crowd_short():
    bars = _bars()
    pack = w106.evaluate_xs_margin_delta_rank_daily_mtm(
        bars,
        _margin(),
        spec=w106.NEW_UNIQUE_LOGIC[2],
        one_way_cost=0.001,
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_ranked_days", 0) >= 1
    assert pack.get("n_gate_on_days", 0) >= 1
    assert pack.get("catalog") is False
    assert pack.get("promote_as_main") is False
    # 13010 de-crowds (score +), 72030 crowds (score −). Live path required.
    assert pack.get("n_active_days", 0) >= 1
    assert pack.get("new_unique_logic") is True


def test_idio_mom_empty_topix_is_incomplete_not_approximated():
    pack = w106.evaluate_idio_mom_macro_impulse_daily_mtm(
        _bars(),
        {},
        spec=w106.NEW_UNIQUE_LOGIC[3],
        one_way_cost=0.001,
    )
    assert pack.get("daily_path_complete") is False
    assert "Not approximated" in str(pack.get("incomplete_reason") or "")


def test_idio_mom_skips_quiet_macro_days():
    bars = _bars()
    spec = dict(w106.NEW_UNIQUE_LOGIC[3])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = 5
    spec["min_hist"] = 5
    pack = w106.evaluate_idio_mom_macro_impulse_daily_mtm(
        bars,
        _topix(quiet=True),
        spec=spec,
        one_way_cost=0.001,
    )
    assert pack.get("ffill_applied") is False
    # Quiet |TOPIX mom| stays below / at median after hist forms → mostly off.
    assert pack.get("n_skip_quiet_macro", 0) + pack.get("n_skip_median_unformed", 0) >= 1
    assert pack.get("go") is False
    assert pack.get("sticky_approx_always_on_gate") is False


def test_idio_mom_turns_on_for_large_index_move():
    bars = _bars()
    spec = dict(w106.NEW_UNIQUE_LOGIC[3])
    spec["params"] = dict(spec["params"])
    spec["params"]["min_hist"] = 5
    spec["min_hist"] = 5
    pack = w106.evaluate_idio_mom_macro_impulse_daily_mtm(
        bars,
        _topix(quiet=False),
        spec=spec,
        one_way_cost=0.001,
    )
    assert pack.get("status") == "ok"
    assert pack.get("n_gate_on_days", 0) >= 1
    assert pack.get("occupancy_frac", 1.0) < 0.85
    assert pack.get("new_unique_logic") is True
    assert pack.get("catalog") is False
