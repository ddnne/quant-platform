"""W78 / w0816m class signals: multi_day_hold + macro_conditioned (not daily sign)."""

from __future__ import annotations

import pytest

from features.class_signals import (
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    amortized_one_way_cost,
    apply_sticky_hold,
    class_signal_definitions,
    class_signals_document,
    compute_macro_conditioned_signal,
    compute_multi_day_hold_signal,
    condition_signal_on_regime,
    cross_section_rank_signs,
    multi_day_forward_return,
    repo_regime_from_change,
    repo_regime_from_level,
    sign_from_numeric,
)
from features.complete21_min import repo_rate_change_from_rows


def test_sign_and_sticky_hold_fixed_horizon():
    assert sign_from_numeric(0.2) == 1.0
    assert sign_from_numeric(-0.1) == -1.0
    assert sign_from_numeric(0.0) == 0.0
    assert sign_from_numeric(None) is None

    entries = [1.0, -1.0, -1.0, 1.0, 1.0, -1.0]
    held = apply_sticky_hold(entries, hold_days=3, rebalance_mode="fixed_horizon")
    # rebalance at 0, 3: positions stick for 3 days
    assert held[0] == 1.0
    assert held[1] == 1.0
    assert held[2] == 1.0
    assert held[3] == 1.0  # entry at 3 is +1
    assert len(held) == 6


def test_sticky_hold_min_hold():
    entries = [1.0, -1.0, -1.0, -1.0, 1.0]
    held = apply_sticky_hold(entries, hold_days=3, rebalance_mode="min_hold")
    # cannot flip until held_for reaches hold_days (3 sessions)
    assert held[0] == 1.0
    assert held[1] == 1.0  # held_for=2 < 3 → blocked flip
    # day index 2: held_for becomes 3 → flip to -1 allowed
    assert held[2] == -1.0
    assert held[3] == -1.0


def test_multi_day_forward_return_and_amortized_cost():
    closes = [100.0, 101.0, 102.0, 103.0, 110.0]
    r = multi_day_forward_return(closes, hold_days=4, entry_index=0)
    assert r == pytest.approx(0.10)
    assert multi_day_forward_return(closes, hold_days=4, entry_index=2) is None
    assert amortized_one_way_cost(0.001, 5) == pytest.approx(0.0002)


def test_compute_multi_day_hold_signal():
    rec = compute_multi_day_hold_signal(
        momentum=0.03, is_trading_day=1.0, hold_days=5, code="13010"
    )
    assert rec["signal_id"] == SIGNAL_ID_MULTI_DAY_HOLD
    assert rec["hypothesis_class"] == CLASS_MULTI_DAY_HOLD
    assert rec["value"] == 1.0
    assert rec["metadata"]["not_simple_daily_sign"] is True
    assert rec["metadata"]["ready_declared"] is False
    assert rec["metadata"]["mass_research"] == "NO-GO"

    off = compute_multi_day_hold_signal(
        momentum=0.03, is_trading_day=0.0, hold_days=5
    )
    assert off["value"] is None


def test_repo_regime_and_macro_condition():
    reg, meta = repo_regime_from_level(0.10, high_threshold=0.05, low_threshold=0.0)
    assert reg == "high"
    reg2, _ = repo_regime_from_level(-0.05, high_threshold=0.05, low_threshold=0.0)
    assert reg2 == "low"
    ch, cmeta = repo_regime_from_change(0.20, 0.10)
    assert ch == "rate_up"
    assert cmeta["delta"] == pytest.approx(0.10)
    ch2, _ = repo_regime_from_change(0.05, 0.10)
    assert ch2 == "rate_down"

    v, info = condition_signal_on_regime(1.0, "rate_down", mode="rate_change")
    assert v == 1.0
    v2, _ = condition_signal_on_regime(-1.0, "rate_down", mode="rate_change")
    assert v2 is None  # short blocked on rate_down
    v3, _ = condition_signal_on_regime(-1.0, "rate_up", mode="rate_change")
    assert v3 == -1.0


def test_compute_macro_conditioned_signal():
    rec = compute_macro_conditioned_signal(
        momentum=0.02,
        repo_rate=0.15,
        prev_repo_rate=0.20,
        is_trading_day=1.0,
        mode="rate_change",
        code="72030",
    )
    assert rec["signal_id"] == SIGNAL_ID_MACRO_CONDITIONED
    assert rec["hypothesis_class"] == CLASS_MACRO_CONDITIONED
    assert rec["regime"] == "rate_down"
    assert rec["value"] == 1.0  # long kept on rate_down
    assert rec["metadata"]["datasets_required"]
    assert "jsda_tokyo_repo_rates" in rec["metadata"]["datasets_required"]

    short_blocked = compute_macro_conditioned_signal(
        momentum=-0.02,
        repo_rate=0.15,
        prev_repo_rate=0.20,
        mode="rate_change",
    )
    assert short_blocked["value"] is None


def test_repo_rate_change_from_rows():
    rows = [
        {"as_of_date": f"2020-01-{d:02d}", "rate": 0.10 + 0.01 * d}
        for d in range(1, 10)
    ]
    delta, meta = repo_rate_change_from_rows(rows, lookback=5)
    assert delta is not None
    assert meta["lookback"] == 5
    assert meta["base_date"] == "2020-01-04"
    assert meta["as_of_date"] == "2020-01-09"


def test_cross_section_rank_signs():
    vals = {"A": 0.1, "B": 0.05, "C": 0.0, "D": -0.02, "E": -0.1, "F": None}
    ranks = cross_section_rank_signs(vals, long_frac=0.3, short_frac=0.3)
    assert ranks["A"] == 1.0
    assert ranks["E"] == -1.0
    assert ranks["F"] is None


def test_class_signal_definitions_not_daily_sign():
    defs = class_signal_definitions(hold_days=10)
    ids = {d["signal_id"] for d in defs}
    assert SIGNAL_ID_MULTI_DAY_HOLD in ids
    assert SIGNAL_ID_MACRO_CONDITIONED in ids
    for d in defs:
        assert d.get("not_simple_daily_sign") is True
        assert d.get("hypothesis_class") != "simple_daily_sign"
    doc = class_signals_document()
    assert doc["mass_research"] == "NO-GO"
    assert doc["ready_declared"] is False
    assert doc["s1_s5_unreject"] is False


def test_class_hyp_eval_pure_on_synthetic_bars():
    from research.class_hyp_eval import (
        evaluate_macro_conditioned_on_bars,
        evaluate_multi_day_hold_on_bars,
    )
    from research.cost_models import load_repo_rate_series_from_mapping

    # Rising then falling prices for two codes
    dates = [f"2020-01-{d:02d}" for d in range(2, 30) if d < 28]
    bars = {
        "13010": [(d, 100.0 + i) for i, d in enumerate(dates)],
        "72030": [(d, 200.0 - 0.5 * i) for i, d in enumerate(dates)],
    }
    md = evaluate_multi_day_hold_on_bars(bars, hold_days=5, one_way_cost=0.001)
    assert md["signal_id"] == SIGNAL_ID_MULTI_DAY_HOLD
    assert md["hold_days"] == 5
    assert md["ready_declared"] is False

    repo = load_repo_rate_series_from_mapping(
        {d: 0.10 + 0.001 * i for i, d in enumerate(dates)}
    )
    macro = evaluate_macro_conditioned_on_bars(
        bars, repo, momentum_n=5, mode="rate_change", one_way_cost=0.001
    )
    assert macro["signal_id"] == SIGNAL_ID_MACRO_CONDITIONED
    assert macro["repo_dataset"] == "jsda_tokyo_repo_rates"
