"""W78–W80 class signals: multi_day_hold + event/flow/fund + macro (not daily sign)."""

from __future__ import annotations

import pytest

from tests.research_eval_util import _assert_mass_ready_off, _disc_event
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
    _assert_mass_ready_off(rec["metadata"])

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


def test_event_post_pit_entry_no_lookahead():
    """DiscTime after session close / missing → next bar; no invent times."""
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

    # Invented date-start event_time is not a known clock
    idx_mid, ed_mid, m_mid = event_post_entry_bar_index(
        date_to_idx,
        disc_date="2023-08-31",
        disc_time=None,
        event_time="2023-08-31T00:00:00+09:00",
    )
    assert ed_mid == "2023-09-01"
    assert m_mid["time_known"] is False

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


_PROD_OK = dict(
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


def _prod_bar(**overrides):
    return production_candidate_bar(**{**_PROD_OK, **overrides})


def test_production_candidate_bar_all_criteria():
    """research_candidate True only when all production criteria pass."""
    ok = _prod_bar()
    assert ok["research_candidate"] is True
    assert ok["candidate_yes_no"] == "yes"
    _assert_mass_ready_off(ok, allow_research_candidate=True)

    # missing occurrence → discussion_only (not production)
    disc = _prod_bar(occurrence_ok=False)
    assert disc["research_candidate"] is False
    assert disc["candidate_yes_no"] == "no_discussion_only"

    # weak econ → not_candidate
    weak = _prod_bar(economic_net_ok=False)
    assert weak["research_candidate"] is False
    assert weak["verdict"] == "not_candidate_economic_net_not_meaningful"

    # W81: stats bar fail with W80 core ok → demote discussion_only
    noisy = _prod_bar(
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


def test_nky_vol_signal_helpers_pure():
    from features.class_signals import (
        CLASS_INDEX_VOL_REGIME,
        compute_nky_vol_abs_level_signal,
        compute_nky_vol_term_levels_signal,
        compute_nky_vol_term_ratio_signal,
        nky_vol_regime_from_abs_level,
        nky_vol_regime_from_term_levels,
        nky_vol_regime_from_term_ratio,
    )

    assert nky_vol_regime_from_abs_level(0.05)[0] == "low"
    assert nky_vol_regime_from_abs_level(0.30)[0] == "high"
    assert nky_vol_regime_from_abs_level(0.15)[0] == "mid"
    assert nky_vol_regime_from_term_levels(0.05, 0.08)[0] == "low"
    assert nky_vol_regime_from_term_levels(0.30, 0.25)[0] == "high"
    assert nky_vol_regime_from_term_levels(0.05, 0.25)[0] == "mid"  # disagree
    assert nky_vol_regime_from_term_ratio(0.30, 0.20)[0] == "expanding"
    assert nky_vol_regime_from_term_ratio(0.10, 0.20)[0] == "compressing"

    abs_s = compute_nky_vol_abs_level_signal(cs_sign=1.0, vol_level=0.05)
    assert abs_s["value"] == 1.0  # low → keep
    abs_h = compute_nky_vol_abs_level_signal(cs_sign=1.0, vol_level=0.30)
    assert abs_h["value"] == -1.0  # high → reverse
    abs_m = compute_nky_vol_abs_level_signal(cs_sign=1.0, vol_level=0.15)
    assert abs_m["value"] is None  # mid → flat

    term = compute_nky_vol_term_levels_signal(
        cs_sign=1.0, short_vol=0.05, long_vol=0.08
    )
    assert term["value"] == 1.0
    ratio = compute_nky_vol_term_ratio_signal(
        cs_sign=1.0, short_vol=0.30, long_vol=0.20
    )
    assert ratio["value"] == -1.0  # expanding → reverse
    assert ratio["hypothesis_class"] == CLASS_INDEX_VOL_REGIME


def test_opt225_signal_helpers_pure():
    from features.class_signals import (
        CLASS_OPTIONS_VOL_REGIME,
        compute_opt225_basevol_abs_level_signal,
        compute_opt225_basevol_delta_abs_signal,
        compute_opt225_cm_term_abs_level_signal,
        compute_opt225_cm_term_ratio_signal,
        compute_opt225_iv_base_spread_abs_signal,
        compute_opt225_skew_abs_level_signal,
        compute_opt225_vol_signal,
    )

    low = compute_opt225_basevol_abs_level_signal(cs_sign=1.0, vol_level=10.0)
    assert low["hypothesis_class"] == CLASS_OPTIONS_VOL_REGIME
    assert low["value"] == 1.0
    high = compute_opt225_basevol_abs_level_signal(cs_sign=1.0, vol_level=30.0)
    assert high["value"] == -1.0
    mid = compute_opt225_basevol_abs_level_signal(cs_sign=1.0, vol_level=18.0)
    assert mid["value"] is None
    sp = compute_opt225_iv_base_spread_abs_signal(cs_sign=1.0, vol_level=2.0)
    assert sp["value"] == -1.0
    ratio = compute_opt225_vol_signal(
        mode="term_ratio",
        cs_sign=1.0,
        short_vol=20.0,
        long_vol=10.0,
        series_kind="atm_iv",
    )
    assert ratio["regime"] == "expanding"
    assert ratio["value"] == -1.0
    skew_hi = compute_opt225_skew_abs_level_signal(cs_sign=1.0, vol_level=4.0)
    assert skew_hi["value"] == -1.0
    skew_lo = compute_opt225_skew_abs_level_signal(cs_sign=1.0, vol_level=0.2)
    assert skew_lo["value"] == 1.0
    term_hi = compute_opt225_cm_term_abs_level_signal(cs_sign=1.0, vol_level=3.0)
    assert term_hi["value"] == -1.0
    term_ratio_hi = compute_opt225_cm_term_ratio_signal(
        cs_sign=1.0, vol_level=0.20
    )
    assert term_ratio_hi["value"] == -1.0
    term_ratio_equal = compute_opt225_cm_term_ratio_signal(
        cs_sign=1.0, vol_level=0.0
    )
    assert term_ratio_equal["value"] is None
    dlt_hi = compute_opt225_basevol_delta_abs_signal(cs_sign=1.0, vol_level=2.0)
    assert dlt_hi["value"] == -1.0
    dlt_lo = compute_opt225_basevol_delta_abs_signal(cs_sign=1.0, vol_level=-2.0)
    assert dlt_lo["value"] == 1.0
