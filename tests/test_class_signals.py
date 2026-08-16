"""W78–W79 class signals: multi_day_hold + event/flow/fund + macro (not daily sign)."""

from __future__ import annotations

import pytest

from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    amortized_one_way_cost,
    apply_sticky_hold,
    class_signal_definitions,
    class_signals_document,
    compute_event_post_signal,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    compute_macro_conditioned_signal,
    compute_multi_day_hold_signal,
    condition_signal_on_regime,
    cross_section_rank_signs,
    earnings_surprise_proxy,
    economic_net_meaningful,
    fundamental_value_score,
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
    assert SIGNAL_ID_EVENT_POST in ids
    assert SIGNAL_ID_FLOW_DEMAND in ids
    assert SIGNAL_ID_FUNDAMENTALS_PRICE in ids
    for d in defs:
        assert d.get("not_simple_daily_sign") is True
        assert d.get("hypothesis_class") != "simple_daily_sign"
    doc = class_signals_document()
    assert doc["mass_research"] == "NO-GO"
    assert doc["ready_declared"] is False
    assert doc["s1_s5_unreject"] is False


def test_event_post_flow_fund_signals():
    surp, meta = earnings_surprise_proxy(eps=10.0, feps=12.0)
    assert surp == pytest.approx(2.0)
    assert meta["mode"] == "feps_minus_eps"
    surp2, meta2 = earnings_surprise_proxy(eps=11.0, prior_eps=10.0)
    assert surp2 == pytest.approx(1.0)
    assert meta2["mode"] == "eps_minus_prior"
    none_s, _ = earnings_surprise_proxy(eps=None, feps=None)
    assert none_s is None

    ep = compute_event_post_signal(
        surprise=2.0, is_event_day=True, post_hold_days=5, code="13010"
    )
    assert ep["signal_id"] == SIGNAL_ID_EVENT_POST
    assert ep["hypothesis_class"] == CLASS_EVENT_POST
    assert ep["value"] == 1.0
    ep_off = compute_event_post_signal(surprise=2.0, is_event_day=False)
    assert ep_off["value"] is None

    flow = compute_flow_demand_signal(
        margin_change=0.05, hold_days=5, code="72030"
    )
    assert flow["signal_id"] == SIGNAL_ID_FLOW_DEMAND
    assert flow["hypothesis_class"] == CLASS_FLOW_DEMAND
    assert flow["value"] == 1.0
    assert flow["metadata"]["not_s4_rehash"] is True
    flow_conf = compute_flow_demand_signal(
        margin_change=0.05,
        short_ratio_change=-0.02,
        require_short_confirm=True,
    )
    assert flow_conf["value"] is None  # sign conflict

    vs, vmeta = fundamental_value_score(close=100.0, bps=50.0)
    assert vs == pytest.approx(0.5)
    assert vmeta["mode"] == "bps_over_price"
    fund = compute_fundamentals_price_signal(
        value_score=0.6,
        momentum=0.02,
        value_benchmark=0.4,
        hold_days=20,
        mode="value_momentum_agree",
    )
    assert fund["signal_id"] == SIGNAL_ID_FUNDAMENTALS_PRICE
    assert fund["hypothesis_class"] == CLASS_FUNDAMENTALS_PRICE
    assert fund["value"] == 1.0
    fund_disagree = compute_fundamentals_price_signal(
        value_score=0.6,
        momentum=-0.02,
        value_benchmark=0.4,
        mode="value_momentum_agree",
    )
    assert fund_disagree["value"] is None


def test_economic_net_meaningful_bar():
    # weak consistent-negative → not meaningful
    weak = economic_net_meaningful([-0.001, -0.0005, -0.002])
    assert weak["meaningful"] is False
    assert weak.get("weak_consistent_negative") is True
    # positive majority but tiny residual → not meaningful
    tiny = economic_net_meaningful([0.0001, 0.0002, -0.00005], min_mean_net=0.002)
    assert tiny["meaningful"] is False
    # economically meaningful positive
    good = economic_net_meaningful([0.01, 0.005, 0.003], min_mean_net=0.002)
    assert good["meaningful"] is True


def test_class_hyp_eval_pure_on_synthetic_bars():
    from research.class_hyp_eval import (
        evaluate_event_post_on_bars,
        evaluate_flow_demand_on_bars,
        evaluate_fundamentals_price_on_bars,
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

    events = {
        "13010": [
            {
                "disc_date": dates[5],
                "eps": 10.0,
                "feps": 12.0,
                "bps": 50.0,
                "prior_eps": 9.0,
            }
        ],
        "72030": [
            {
                "disc_date": dates[8],
                "eps": 5.0,
                "feps": 4.0,
                "bps": 20.0,
                "prior_eps": 6.0,
            }
        ],
    }
    ep = evaluate_event_post_on_bars(
        bars, events, post_hold_days=5, one_way_cost=0.001
    )
    assert ep["signal_id"] == SIGNAL_ID_EVENT_POST
    assert ep["n_events"] == 2

    margin = {
        "13010": [(dates[i], 1000.0 + 50 * i) for i in range(0, len(dates), 3)],
        "72030": [(dates[i], 2000.0 - 30 * i) for i in range(0, len(dates), 3)],
    }
    flow = evaluate_flow_demand_on_bars(
        bars, margin, hold_days=5, one_way_cost=0.001
    )
    assert flow["signal_id"] == SIGNAL_ID_FLOW_DEMAND
    assert flow["hypothesis_class"] == CLASS_FLOW_DEMAND

    fund = evaluate_fundamentals_price_on_bars(
        bars, events, hold_days=5, momentum_n=5, one_way_cost=0.001
    )
    assert fund["signal_id"] == SIGNAL_ID_FUNDAMENTALS_PRICE
    assert fund["hypothesis_class"] == CLASS_FUNDAMENTALS_PRICE
