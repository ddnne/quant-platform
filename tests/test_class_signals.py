"""W78–W80 class signals: multi_day_hold + event/flow/fund + macro (not daily sign)."""

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
    multi_year_skew_check,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    production_candidate_bar,
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


def test_event_post_pit_entry_no_lookahead():
    """W82: DiscTime after session close / missing → next bar; no invent times."""
    from features.class_signals import (
        event_post_available_at_from_fields,
        event_post_entry_bar_index,
        parse_disc_time_hhmmss,
        session_close_hhmmss,
    )

    assert parse_disc_time_hhmmss("10:05") == "10:05:00"
    assert parse_disc_time_hhmmss(None) is None
    assert parse_disc_time_hhmmss("") is None
    assert session_close_hhmmss("2023-08-31") == "15:00:00"
    assert session_close_hhmmss("2024-11-05") == "15:30:00"

    aa, meta = event_post_available_at_from_fields(
        disc_date="2023-08-31", disc_time="10:05"
    )
    assert aa == "2023-08-31T10:05:00+09:00"
    assert meta["time_known"] is True
    aa_miss, meta_miss = event_post_available_at_from_fields(
        disc_date="2023-08-31", disc_time=None
    )
    assert aa_miss is None
    assert meta_miss["time_known"] is False
    assert "no invent" in meta_miss["reason"].lower() or "unknown" in meta_miss["mode"]

    # Weekday sequence with gap-free bars
    dates = [
        "2023-08-28",
        "2023-08-29",
        "2023-08-30",
        "2023-08-31",
        "2023-09-01",
        "2023-09-04",
    ]
    date_to_idx = {d: i for i, d in enumerate(dates)}

    # Pre-close disclosure → same-day entry OK
    idx, ed, m = event_post_entry_bar_index(
        date_to_idx, disc_date="2023-08-31", disc_time="10:05"
    )
    assert idx == date_to_idx["2023-08-31"]
    assert ed == "2023-08-31"
    assert m["look_ahead"] is False
    assert m["pre_session_close"] is True

    # At session close (15:00 pre-2024-11-05) → next session (no same-day close)
    idx2, ed2, m2 = event_post_entry_bar_index(
        date_to_idx, disc_date="2023-08-31", disc_time="15:00"
    )
    assert ed2 == "2023-09-01"
    assert idx2 == date_to_idx["2023-09-01"]
    assert m2["look_ahead"] is False
    assert m2["pre_session_close"] is False

    # After close → next session
    idx3, ed3, m3 = event_post_entry_bar_index(
        date_to_idx, disc_date="2023-08-31", disc_time="16:30"
    )
    assert ed3 == "2023-09-01"
    assert m3["look_ahead"] is False

    # Missing DiscTime → conservative next session (no invent 00:00/09:00)
    idx4, ed4, m4 = event_post_entry_bar_index(
        date_to_idx, disc_date="2023-08-31", disc_time=None
    )
    assert ed4 == "2023-09-01"
    assert m4["time_known"] is False
    assert m4["look_ahead"] is False

    # Non-trading disc_date → first trading bar after calendar day
    weekend = {
        "2023-09-01": 0,
        "2023-09-04": 1,
    }
    idx5, ed5, m5 = event_post_entry_bar_index(
        weekend, disc_date="2023-09-02", disc_time="10:00"  # Saturday
    )
    assert ed5 == "2023-09-04"
    assert m5["look_ahead"] is False


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


def test_occurrence_rate_not_count_alone():
    """W80: rate OK with small absolute count; rate fail with large count."""
    # 27 events / 60 days / 30 codes — W79 sparse Q4 — rate still OK
    sparse = occurrence_rate_event_post(
        n_events=27, n_scored=27, n_trading_days=60, n_codes=30
    )
    assert sparse["sufficient"] is True
    assert sparse["reject_on_count_alone"] is False
    assert sparse["events_per_code_year_annualized"] > 0.5

    # zero days → cannot compute rate
    bad = occurrence_rate_event_post(n_events=1000, n_scored=1000, n_trading_days=0)
    assert bad["sufficient"] is False

    md = occurrence_rate_multiday(n_active=100, n_code_days=1000, hold_days=10)
    assert md["activation_rate"] == pytest.approx(0.1)
    assert md["sufficient"] is True


def test_production_candidate_bar_all_criteria():
    """research_candidate True only when all production criteria pass."""
    ok = production_candidate_bar(
        checklist_complete=True,
        gate_passed=True,
        risk_ok=True,
        economic_net_ok=True,
        occurrence_ok=True,
        multi_year_ok=True,
        skew_ok=True,
        n_ok_periods=6,
        stats_ok=True,
    )
    assert ok["research_candidate"] is True
    assert ok["candidate_yes_no"] == "yes"
    assert ok["ready_declared"] is False
    assert ok["mass_research"] == "NO-GO"
    assert ok["connected_to_ready"] is False

    # missing occurrence → discussion_only (not production)
    disc = production_candidate_bar(
        checklist_complete=True,
        gate_passed=True,
        risk_ok=True,
        economic_net_ok=True,
        occurrence_ok=False,
        multi_year_ok=True,
        skew_ok=True,
        n_ok_periods=6,
        stats_ok=True,
    )
    assert disc["research_candidate"] is False
    assert disc["candidate_yes_no"] == "no_discussion_only"

    # weak econ → not_candidate
    weak = production_candidate_bar(
        checklist_complete=True,
        gate_passed=True,
        risk_ok=True,
        economic_net_ok=False,
        occurrence_ok=True,
        multi_year_ok=True,
        skew_ok=True,
        n_ok_periods=6,
        stats_ok=True,
    )
    assert weak["research_candidate"] is False
    assert weak["verdict"] == "not_candidate_economic_net_not_meaningful"

    # W81: stats bar fail with W80 core ok → demote discussion_only
    noisy = production_candidate_bar(
        checklist_complete=True,
        gate_passed=True,
        risk_ok=True,
        economic_net_ok=True,
        occurrence_ok=True,
        multi_year_ok=True,
        skew_ok=True,
        n_ok_periods=6,
        stats_ok=False,
        stats_bar={"noisy": True, "stats_ok": False},
        require_stats=True,
    )
    assert noisy["research_candidate"] is False
    assert noisy["candidate_yes_no"] == "no_discussion_only"
    assert "stats_bar_failed" in noisy["production_criteria"]["fails"]
    assert noisy["verdict"] in (
        "discussion_only_noisy_stats",
        "discussion_only_stats_bar",
    )

    skew = multi_year_skew_check({"y1": 0.10, "y2": 0.01, "y3": 0.01})
    assert skew["ok"] is False  # y1 share 0.10/0.12 > 0.75


def test_stats_metrics_period_and_bar():
    """W81 stats helpers: t-stat / Sharpe / winrate / bar on synthetic nets."""
    from research.stats_metrics import (
        period_stats_report,
        stats_bar_check,
        t_stat_vs_zero,
        trade_stats_report,
    )

    # Stable positive: should pass bar
    strong = [0.01, 0.012, 0.008, 0.009, 0.011, 0.007]
    rep = period_stats_report(strong, period_ids=[f"y{i}" for i in range(6)])
    assert rep["mean_net"] is not None and rep["mean_net"] > 0
    assert rep["t_stat"] is not None and rep["t_stat"] > 1.5
    assert rep["sharpe"] is not None and rep["sharpe"] > 0.5
    assert rep["win_rate"] == 1.0
    bar_ok = stats_bar_check(rep)
    assert bar_ok["stats_ok"] is True

    # Noisy mixed signs (W80 multi_day_hold_10-like scale)
    noisy = [0.0065, 0.0151, 0.0008, -0.0080, -0.0052, 0.0035]
    nrep = period_stats_report(noisy)
    nbar = stats_bar_check(nrep)
    assert nbar["stats_ok"] is False
    assert nrep["abs_t_stat"] is not None and nrep["abs_t_stat"] < 1.5

    t0 = t_stat_vs_zero([])
    assert t0["t_stat"] is None

    # W95: near-identical 2-period nets → null t (fund 2017 giant-t case).
    giant = t_stat_vs_zero([0.008229283197313041, 0.008337431738535494])
    assert giant["reason"] == "low_variance_artifact"
    assert giant["t_stat"] is None
    assert giant.get("raw_t_stat") is not None and abs(giant["raw_t_stat"]) > 100

    trades = trade_stats_report(
        [0.02, -0.01, 0.015, 0.005, -0.008],
        hold_days=10,
        one_way_cost=0.001,
        amortize_cost=True,
    )
    assert trades["n_trades"] == 5
    assert trades["sharpe_ann"] is not None
    assert trades["win_rate"] is not None


def test_class_hyp_eval_pure_on_synthetic_bars():
    from research.class_hyp_eval import merge_event_calendars
    from research.cost_models import load_repo_rate_series_from_mapping
    from research.offline.bar_eval import (
        evaluate_event_post_on_bars,
        evaluate_flow_demand_on_bars,
        evaluate_fundamentals_price_on_bars,
        evaluate_macro_conditioned_on_bars,
        evaluate_multi_day_hold_on_bars,
    )

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
    assert md.get("occurrence") is not None
    assert "activation_rate" in md["occurrence"]

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
    earn_only = {
        "13010": [{"disc_date": dates[10], "source": "fins_earnings_date"}],
    }
    merged = merge_event_calendars(events, earn_only)
    assert len(merged["13010"]) == 2  # summary + earnings-date thicken
    ep = evaluate_event_post_on_bars(
        bars, events, post_hold_days=5, one_way_cost=0.001
    )
    assert ep["signal_id"] == SIGNAL_ID_EVENT_POST
    assert ep["n_events"] == 2
    assert ep.get("occurrence") is not None

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

    from research.offline.bar_eval import evaluate_cross_section_on_bars

    xs5 = evaluate_cross_section_on_bars(
        bars, momentum_n=5, hold_days=5, one_way_cost=0.001
    )
    assert xs5["hold_days"] == 5
    xs10 = evaluate_cross_section_on_bars(
        bars, momentum_n=5, hold_days=10, one_way_cost=0.001
    )
    assert xs10["hold_days"] == 10
    assert xs10.get("occurrence") is not None


def test_w83_wave_tags_and_default_path_params():
    """W83 / w0816r: wave tags + default path includes xs/fund hold=10 blocks."""
    import inspect

    from features.class_signals import (
        CLASS_SIGNALS_VERSION,
        CLASS_SIGNALS_WAVE,
        EVENT_POST_ENTRY_MODE,
    )
    from research.class_hyp_eval import (
        CLASS_HYP_EVAL_VERSION,
        CLASS_HYP_EVAL_WAVE,
        run_class_hyp_multi_year_eval,
    )

    # W95 / w0818e: class-signals/v10 held (+ skew/CM-term/ΔBaseVol deep-dive)
    assert CLASS_SIGNALS_VERSION in {
        "class-signals/v6",
        "class-signals/v7",
        "class-signals/v8",
        "class-signals/v9",
        "class-signals/v10",
    }
    assert (
        "W83" in CLASS_SIGNALS_WAVE
        or "W89" in CLASS_SIGNALS_WAVE
        or "W91" in CLASS_SIGNALS_WAVE
        or "W92" in CLASS_SIGNALS_WAVE
        or "W94" in CLASS_SIGNALS_WAVE
        or "W95" in CLASS_SIGNALS_WAVE
    )
    # W86 / w0816u: class_hyp_eval v7 adds sign-selection both-sides
    assert CLASS_HYP_EVAL_VERSION == "class-hyp-eval/v7"
    assert "W86" in CLASS_HYP_EVAL_WAVE
    # PIT event entry held (no look-ahead revival)
    assert EVENT_POST_ENTRY_MODE == "same_day_close_if_pre_close"

    sig = inspect.signature(run_class_hyp_multi_year_eval)
    assert sig.parameters["include_cross_section_hold_10"].default is True
    assert sig.parameters["include_fundamentals_hold_10"].default is True
    # W82 pin mom lookback for sticky hold=10 (content-matched mom=10 fails)
    assert sig.parameters["cross_section_hold10_momentum_n"].default == 5
    assert sig.parameters["fund_hold10_momentum_n"].default == 10
    # W85 promote_default: sticky hold=10 mom=3 parallel to mom=5 pin
    assert sig.parameters["include_cross_section_hold_10_mom3"].default is True
    assert sig.parameters["cross_section_hold10_mom3_momentum_n"].default == 3
    # Freezes: no Mass/READY auto
    doc = class_signals_document()
    assert doc["mass_research"] == "NO-GO"
    assert doc["ready_declared"] is False
    assert doc["phase7"] == "OFF"
