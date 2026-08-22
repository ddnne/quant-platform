"""Standard research eval surfaces: Mass/READY closed, no auto-candidate.

Harness/checklist runners deleted; keep cost_models / daily_path_DD / risk /
baseline occupancy tests.
"""

from __future__ import annotations

from research.baseline_catalog import (
    RESEARCH_STATUS_REJECTED,
    SIGNAL_ID_S1,
    SIGNAL_ID_S2,
    SIGNAL_ID_S3,
    SIGNAL_ID_S4,
    SIGNAL_ID_S5,
    is_research_baseline_rejected,
    rejected_baseline_catalog,
)
from research.cost_models import (
    COST_MODELS_VERSION,
    POSITION_STYLE_LONG_SHORT,
    build_leverage_short_cost_assumption,
    default_long_only_unlevered_cost_assumption,
    short_borrow_daily_cost,
)
from research.stats_metrics import (
    DAILY_PATH_DD_REQUIRED_FIELDS,
    W99_STICKY_DAILY_PATH_DD_REFERENCE,
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
    w99_sticky_daily_path_dd_reference,
)
from research.risk_scenarios import (
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
    SCENARIO_LIQUIDITY_STRESS,
    SCENARIO_RATE_DOWN,
    SCENARIO_RATE_UP,
    evaluate_risk_scenarios,
    scenario_row,
)
from research.robustness_gate import evaluate_research_robustness_gate
from tests.research_eval_util import _assert_mass_ready_off

_W99_REF0 = W99_STICKY_DAILY_PATH_DD_REFERENCE[0]
W99_DAILY_PATH_PACK = {
    "daily_path_DD": _W99_REF0["daily_path_DD"],
    "dd_duration": _W99_REF0["dd_duration"],
    "recovered": _W99_REF0["recovered"],
    "recovery_days": _W99_REF0["recovery_days"],
    "total_ret_net": _W99_REF0["total_ret_net"],
    "period_net_DD": _W99_REF0["period_net_DD_w98_cf_artifact"],
    "method": "daily_equity_level_peak_to_trough",
    "window": "w2017_2019",
    "logic_id": "xs_rank_ls_sticky",
}

_GATE_PASS_ROWS = [
    {"period_id": "y2015", "gross_signed_mean_active": -0.0005, "n_active_positions": 100},
    {"period_id": "y2017", "gross_signed_mean_active": -0.0004, "n_active_positions": 100},
    {"period_id": "y2019", "gross_signed_mean_active": -0.0006, "n_active_positions": 100},
]


def test_gate_pass_still_not_ready_or_candidate():
    """Even cost-aware gate PASS must not mint READY / research_candidate."""
    gate = evaluate_research_robustness_gate(
        _GATE_PASS_ROWS,
        signal_id=SIGNAL_ID_S4,
        require_net_sign_majority=True,
    )
    assert gate["passed"] is True
    assert gate["ready_declared"] is False
    assert gate["operational_go"] is False
    _assert_mass_ready_off(gate)


def test_does_not_register_new_signals():
    cat = rejected_baseline_catalog()
    assert set(cat["signal_ids"]) == {
        SIGNAL_ID_S1,
        SIGNAL_ID_S2,
        SIGNAL_ID_S3,
        SIGNAL_ID_S4,
        SIGNAL_ID_S5,
    }


def test_rejected_baselines_still_rejected():
    for sid in (SIGNAL_ID_S1, SIGNAL_ID_S2, SIGNAL_ID_S3, SIGNAL_ID_S4, SIGNAL_ID_S5):
        assert is_research_baseline_rejected(sid) is True
        entry = rejected_baseline_catalog()["baselines"][sid]
        assert entry["research_status"] == RESEARCH_STATUS_REJECTED
        _assert_mass_ready_off(entry)


def test_leverage_short_costs_long_only_and_long_short():
    lo = default_long_only_unlevered_cost_assumption()
    assert lo["version"] == COST_MODELS_VERSION
    assert lo["assumptions_complete"] is True
    assert lo["short_borrow"]["not_applicable"] is True
    assert lo["leverage_financing"]["not_applicable"] is True
    _assert_mass_ready_off(lo)

    ls = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        short_fraction=0.5,
        uses_short=True,
        uses_leverage=False,
    )
    assert ls["uses_short"] is True
    assert ls["short_borrow"]["not_applicable"] is False
    assert ls["short_borrow"]["daily_cost"] > 0
    assert ls["assumptions_complete"] is True
    expected = short_borrow_daily_cost(
        short_borrow_annual_bp=50.0, short_fraction=0.5
    )
    assert abs(ls["short_borrow"]["daily_cost"] - expected) < 1e-12
    _assert_mass_ready_off(ls)


def test_evaluate_risk_scenarios_standalone():
    pending = evaluate_risk_scenarios(None)
    assert pending["passed"] is False
    assert pending["research_candidate_allowed"] is False
    _assert_mass_ready_off(pending)

    full = evaluate_risk_scenarios(
        [
            scenario_row(SCENARIO_CRASH, gross_signed_mean=-0.01),
            scenario_row(SCENARIO_HIGH_VOL, gross_signed_mean=-0.005),
            scenario_row(SCENARIO_RATE_UP, not_applicable=True, na_reason="no rates"),
            scenario_row(SCENARIO_RATE_DOWN, not_applicable=True, na_reason="no rates"),
            scenario_row(
                SCENARIO_LIQUIDITY_STRESS, not_applicable=True, na_reason="no liq"
            ),
        ],
        baseline_majority_sign=-1,
    )
    assert full["passed"] is True
    assert full["coverage_ok"] is True
    _assert_mass_ready_off(full)


def test_period_net_method_stuffed_as_daily_fails():
    """A period-net proxy cannot be relabeled as daily_path_DD."""
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=0.0,
        dd_duration=0,
        recovered=True,
        recovery_days=0,
        total_ret_net=0.05,
        method="period_net_cumsum_proxy",
    )
    assert gate["measured"] is False
    assert gate["complete"] is False
    assert "period_net_DD_method_is_not_daily_path" in gate["fails"]


def test_period_net_dd_only_cannot_pass_even_if_nonzero():
    """Passing on period_net_DD alone is forbidden regardless of the number."""
    gate = evaluate_daily_path_dd_gate(period_net_dd=-0.0023)
    assert gate["period_net_dd_only"] is True
    assert gate["complete"] is False
    assert gate["passed"] is False
    assert "period_net_DD_only_pass_forbidden" in gate["fails"]
    assert gate["ready_declared"] is False


def test_w99_sticky_reference_daily_path_completes_item():
    ref = w99_sticky_daily_path_dd_reference()
    assert ref["logic_id"] == "xs_rank_ls_sticky"
    assert ref["stance"] == "STABLE_RESEARCH_ONLY"
    assert ref["promote_as_main"] is False
    assert ref["go"] is False
    assert len(ref["windows"]) == 3

    gate = evaluate_daily_path_dd_gate(daily_path_pack=W99_DAILY_PATH_PACK)
    assert gate["complete"] is True
    assert gate["passed"] is True
    assert gate["measured"] is True
    assert gate["scorecard"]["daily_path_DD"] == -0.143741
    assert gate["scorecard"]["dd_duration"] == 85
    assert gate["scorecard"]["recovery"]["recovered"] is False
    assert gate["scorecard"]["recovery"]["recovery_days"] is None
    assert gate["scorecard"]["total_ret_net"] == 0.034975
    assert gate["period_net_dd_zero_daily_unmeasured"] is False
    assert any("aggregation artifact" in w for w in gate["warnings"])
    assert set(DAILY_PATH_DD_REQUIRED_FIELDS) == {
        "daily_path_DD",
        "dd_duration",
        "recovery",
        "total_ret_net",
    }
    _assert_mass_ready_off(gate)


def test_daily_path_from_equity_curve():
    """Level equity peak-to-trough (not period-net cumsum) is the daily method."""
    eq = [1.0, 1.2, 0.9, 1.2]
    dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]
    dd = equity_path_drawdown(eq, dates)
    assert abs(dd["max_dd"] - (0.9 / 1.2 - 1.0)) < 1e-12
    assert dd["dd_duration_days"] == 1
    assert dd["recovered"] is True
    assert dd["recovery_days"] == 1
    assert dd["method"] == "daily_equity_level_peak_to_trough"
    assert abs(dd["total_return"] - 0.2) < 1e-12

    gate = evaluate_daily_path_dd_gate(equities=eq, dates=dates)
    assert gate["complete"] is True
    assert gate["daily_path_DD"] == dd["max_dd"]
    assert gate["dd_duration"] == 1
    assert gate["recovered"] is True
    assert gate["recovery_days"] == 1
    assert abs(gate["total_ret_net"] - 0.2) < 1e-12


def test_recovered_true_requires_recovery_days():
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=-0.05,
        dd_duration=10,
        recovered=True,
        total_ret_net=0.01,
    )
    assert gate["complete"] is False
    assert "recovery_days" in gate["missing_required"]


def test_no_drawdown_path_does_not_require_recovery_days():
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=0.0,
        dd_duration=0,
        recovered=True,
        recovery_days=None,
        total_ret_net=0.04,
        method="daily_equity_level_peak_to_trough",
    )
    assert gate["complete"] is True
    assert gate["missing_required"] == []
