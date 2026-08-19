"""W66 / w0815bg + W77 / w0816k — standard research eval checklist harness entry.

Locks:
* dry_run wiring completes with READY false / Mass NO-GO / Phase7 OFF
* gate pass still not READY / not research_candidate
* does not register new signals
* rejected baselines (S1–S5) remain rejected
* checklist v2: incomplete → not research_candidate
* leverage/short costs + risk scenarios required
"""

from __future__ import annotations

import ast
from pathlib import Path

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
    POSITION_STYLE_LONG_ONLY_UNLEVERED,
    POSITION_STYLE_LONG_SHORT,
    build_leverage_short_cost_assumption,
    default_long_only_unlevered_cost_assumption,
    short_borrow_daily_cost,
)
from research.eval_harness import (
    CHECKLIST_VERSION,
    CHECKLIST_VERSION_V1,
    MASS_RESEARCH,
    PHASE7,
    STANDARD_EVAL_DAILY_PATH_DD_PROOF,
    STANDARD_EVAL_MODES,
    EvalHarnessError,
    evaluate_checklist_v2_completeness,
    run_standard_research_eval,
    standard_research_eval_checklist_document,
    standard_research_eval_checklist_run,
)
from research.stats_metrics import (
    DAILY_PATH_DD_REQUIRED_FIELDS,
    W99_STICKY_DAILY_PATH_DD_REFERENCE,
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
    w99_sticky_daily_path_dd_reference,
)
from research.risk_scenarios import (
    RISK_SCENARIOS_VERSION,
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
    SCENARIO_LIQUIDITY_STRESS,
    SCENARIO_RATE_DOWN,
    SCENARIO_RATE_UP,
    evaluate_risk_scenarios,
    scenario_row,
)
from research.robustness_gate import evaluate_research_robustness_gate

REPO = Path(__file__).resolve().parents[1]
EVAL_HARNESS_PATH = REPO / "packages" / "product" / "research" / "eval_harness.py"

# W99 sticky w2017_2019 — measured daily path (period_net_DD=0 is contrast only).
W99_DAILY_PATH_PACK = {
    "daily_path_DD": W99_STICKY_DAILY_PATH_DD_REFERENCE[0]["daily_path_DD"],
    "dd_duration": W99_STICKY_DAILY_PATH_DD_REFERENCE[0]["dd_duration"],
    "recovered": W99_STICKY_DAILY_PATH_DD_REFERENCE[0]["recovered"],
    "recovery_days": W99_STICKY_DAILY_PATH_DD_REFERENCE[0]["recovery_days"],
    "total_ret_net": W99_STICKY_DAILY_PATH_DD_REFERENCE[0]["total_ret_net"],
    "period_net_DD": W99_STICKY_DAILY_PATH_DD_REFERENCE[0][
        "period_net_DD_w98_cf_artifact"
    ],
    "method": "daily_equity_level_peak_to_trough",
    "window": "w2017_2019",
    "logic_id": "xs_rank_ls_sticky",
}


def _complete_scenario_rows():
    return [
        scenario_row(SCENARIO_CRASH, gross_signed_mean=-0.001, net_one_way_mean=-0.002),
        scenario_row(
            SCENARIO_HIGH_VOL, gross_signed_mean=-0.0008, net_one_way_mean=-0.0018
        ),
        scenario_row(SCENARIO_RATE_UP, not_applicable=True, na_reason="no rate data"),
        scenario_row(SCENARIO_RATE_DOWN, not_applicable=True, na_reason="no rate data"),
        scenario_row(
            SCENARIO_LIQUIDITY_STRESS,
            not_applicable=True,
            na_reason="no liquidity stress series",
        ),
    ]


def test_dry_run_wiring_completes_mass_ready_phase7_closed():
    out = run_standard_research_eval(dry_run=True)
    assert out["checklist_version"] == CHECKLIST_VERSION
    assert out["checklist_version"] == "standard-research-eval-checklist/v2"
    assert out["prior_checklist_version"] == CHECKLIST_VERSION_V1
    assert out["mode"] == "wiring_only"
    assert out["dry_run"] is True
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["mass_research"] == "NO-GO"
    assert MASS_RESEARCH == "NO-GO"
    assert out["phase7"] == "OFF"
    assert PHASE7 == "OFF"
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["edge_claimed"] is False
    assert out["significance_claimed"] is False
    assert out["research_candidate"] is False
    assert out["checklist_skipped"] is False
    assert out["new_signals_registered"] is False
    assert out["short_window_only_sufficient"] is False
    assert out["densify"] is False
    assert "cost_assumption" in out
    assert out["cost_assumption"]["one_way_cost_bp"] == 10.0
    assert out["data_gap_notes"] is not None
    assert "assert_harness_closed" in out["steps_completed"]
    assert "cost_assumption" in out["steps_completed"]
    assert "multi_year_or_long_period_design" in out["steps_completed"]
    assert "data_gap_disclosure" in out["steps_completed"]
    assert "freeze_ready_mass_phase7_closed" in out["steps_completed"]
    assert "leverage_short_cost_assumptions" in out["steps_completed"]
    assert "risk_scenario_evaluation" in out["steps_completed"]
    assert "daily_path_dd" in out["steps_completed"]
    assert "checklist_v2_completeness" in out["steps_completed"]
    assert out["holding"] is not None
    assert out["multi_year"]["status"] == "wiring_only"
    assert len(out["designed_periods"]) >= 1
    # v2 surfaces always present
    assert out["leverage_short_costs"] is not None
    assert out["leverage_short_costs"]["assumptions_complete"] is True
    assert out["leverage_short_costs"]["position_style"] == POSITION_STYLE_LONG_ONLY_UNLEVERED
    assert out["risk_scenarios"] is not None
    assert out["risk_scenarios"]["version"] == RISK_SCENARIOS_VERSION
    assert out["checklist_completeness"] is not None
    # wiring_only leaves core scenarios + daily_path_DD unmeasured
    # → incomplete → not candidate
    assert out["checklist_complete"] is False
    assert out["research_candidate_allowed"] is False
    assert out["daily_path_dd"] is not None
    assert out["daily_path_dd"]["complete"] is False
    assert out["daily_path_dd"]["period_net_dd_only_pass_forbidden"] is True
    assert "daily_path_dd" in out["checklist_completeness"]["missing_required"]
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"


def test_alias_standard_research_eval_checklist_run():
    assert standard_research_eval_checklist_run is run_standard_research_eval
    out = standard_research_eval_checklist_run(dry_run=True, include_holding=False)
    assert out["ready_declared"] is False
    assert out["holding"] is None


def test_gate_pass_still_not_ready_or_candidate():
    """Even cost-aware gate PASS must not mint READY / research_candidate."""
    rows = [
        {
            "period_id": "y2015",
            "gross_signed_mean_active": -0.0005,
            "n_active_positions": 100,
        },
        {
            "period_id": "y2017",
            "gross_signed_mean_active": -0.0004,
            "n_active_positions": 100,
        },
        {
            "period_id": "y2019",
            "gross_signed_mean_active": -0.0006,
            "n_active_positions": 100,
        },
    ]
    # Direct gate still closed.
    gate = evaluate_research_robustness_gate(
        rows,
        signal_id=SIGNAL_ID_S4,
        require_net_sign_majority=True,
    )
    assert gate["passed"] is True
    assert gate["ready_declared"] is False
    assert gate["operational_go"] is False

    out = run_standard_research_eval(
        dry_run=True,
        mode="wiring_only",
        period_rows_for_gate=rows,
        min_active_per_period=20,
    )
    assert out["gate_passed"] is True
    assert out["robustness_gate"]["passed"] is True
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["phase7"] == "OFF"
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["research_candidate"] is False
    assert out["gate_pass_implies_ready"] is False
    assert out["gate_pass_implies_mass"] is False
    assert out["gate_pass_implies_research_candidate"] is False
    # incomplete risk scenarios still block candidate allowance
    assert out["research_candidate_allowed"] is False


def test_does_not_register_new_signals():
    out = run_standard_research_eval(dry_run=True)
    assert out["new_signals_registered"] is False
    assert out["baseline_demo"]["new_signals_registered"] is False
    # No new signal ids appear outside catalog surface.
    cat = rejected_baseline_catalog()
    assert set(cat["signal_ids"]) == {
        SIGNAL_ID_S1,
        SIGNAL_ID_S2,
        SIGNAL_ID_S3,
        SIGNAL_ID_S4,
        SIGNAL_ID_S5,
    }
    # Checklist document does not mint signals either.
    doc = standard_research_eval_checklist_document()
    assert doc["research_candidate"] is False
    assert doc["ready_declared"] is False
    assert doc["mass_research"] == "NO-GO"
    assert "run_standard_research_eval" == doc["default_entry"]
    assert doc["version"] == "standard-research-eval-checklist/v2"
    assert "leverage_short_cost_assumptions" in doc["required"]
    assert "risk_scenario_evaluation" in doc["required"]
    assert "daily_path_dd" in doc["required"]
    assert "period_net_dd_only_pass" in doc["insufficient"]
    assert "period_net_dd_zero_daily_unmeasured" in doc["insufficient"]
    assert doc["daily_path_dd_proof"] == STANDARD_EVAL_DAILY_PATH_DD_PROOF
    assert doc["daily_path_dd_surface"]["period_net_dd_only_pass_forbidden"] is True
    assert doc["incomplete_checklist_blocks_research_candidate"] is True


def test_rejected_baselines_still_rejected():
    for sid in (SIGNAL_ID_S1, SIGNAL_ID_S2, SIGNAL_ID_S3, SIGNAL_ID_S4, SIGNAL_ID_S5):
        assert is_research_baseline_rejected(sid) is True
        entry = rejected_baseline_catalog()["baselines"][sid]
        assert entry["research_status"] == RESEARCH_STATUS_REJECTED
        assert entry["ready_declared"] is False
        assert entry["mass_research"] == "NO-GO"

    # s1 dry demo mode still leaves S1 rejected and freezes closed.
    out = run_standard_research_eval(
        dry_run=True,
        mode="s1_rejected_baseline",
    )
    assert out["mode"] == "s1_rejected_baseline"
    assert out["baseline_demo"]["still_rejected"] is True
    assert out["baseline_demo"]["signal_id"] == SIGNAL_ID_S1
    assert out["research_candidate"] is False
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["phase7"] == "OFF"
    assert is_research_baseline_rejected(SIGNAL_ID_S1) is True

    out4 = run_standard_research_eval(
        dry_run=True,
        mode="s4_rejected_baseline",
    )
    assert out4["baseline_demo"]["still_rejected"] is True
    assert out4["baseline_demo"]["signal_id"] == SIGNAL_ID_S4
    assert is_research_baseline_rejected(SIGNAL_ID_S4) is True


def test_cost_change_requires_reason():
    try:
        run_standard_research_eval(dry_run=True, one_way_cost=0.002)
        raise AssertionError("expected EvalHarnessError for cost change without reason")
    except EvalHarnessError as exc:
        assert "cost_change_reason" in str(exc)

    out = run_standard_research_eval(
        dry_run=True,
        one_way_cost=0.002,
        cost_change_reason="unit-test override only",
    )
    assert out["cost_assumption"]["changed_from_default"] is True
    assert out["cost_assumption"]["change_reason"] == "unit-test override only"
    assert out["ready_declared"] is False


def test_holding_records_optional_annotation():
    records = [
        {"date": "2015-09-01", "code": "13010", "sign": 1},
        {"date": "2015-09-02", "code": "13010", "sign": 1},
        {"date": "2015-09-03", "code": "13010", "sign": -1},
        {"date": "2015-09-01", "code": "72030", "sign": 1},
        {"date": "2015-09-02", "code": "72030", "sign": 1},
        {"date": "2015-09-03", "code": "72030", "sign": 1},
    ]
    out = run_standard_research_eval(
        dry_run=True,
        holding_records=records,
    )
    assert "holding_turnover_metrics" in out["steps_completed"]
    assert out["holding"]["run_length_stats"]["n_runs_total"] >= 1
    assert out["holding"]["ready_declared"] is False
    assert out["holding"]["mass_research"] == "NO-GO"


def test_invalid_mode_rejected():
    try:
        run_standard_research_eval(dry_run=True, mode="invent_new_signal")
        raise AssertionError("expected EvalHarnessError")
    except EvalHarnessError as exc:
        assert "mode" in str(exc).lower()
    assert set(STANDARD_EVAL_MODES) == {
        "wiring_only",
        "s1_rejected_baseline",
        "s4_rejected_baseline",
        "class_hyp_offline",
    }


def test_standard_eval_ast_no_mass_import_no_new_signal_mint():
    src = EVAL_HARNESS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "mass_research" not in (node.module or "")
    assert "run_standard_research_eval" in src
    assert "CHECKLIST_VERSION" in src
    assert "research_candidate" in src
    # Function must not claim auto-promotion.
    assert "gate_pass_implies_research_candidate" in src
    assert "standard-research-eval-checklist/v2" in src
    assert "evaluate_checklist_v2_completeness" in src
    assert "daily_path_dd" in src
    assert "period_net_dd_only_pass" in src


# ---------------------------------------------------------------------------
# W77 / w0816k — checklist v2
# ---------------------------------------------------------------------------


def test_checklist_incomplete_not_research_candidate():
    """Incomplete checklist (default wiring) cannot become research_candidate."""
    out = run_standard_research_eval(dry_run=True)
    assert out["research_candidate"] is False
    assert out["research_candidate_allowed"] is False
    assert out["checklist_complete"] is False
    missing = out["checklist_completeness"]["missing_required"]
    assert "risk_scenario_evaluation" in missing
    assert "daily_path_dd" in missing
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False


def test_checklist_complete_still_not_auto_candidate_and_freeze():
    """Even with full scenario metrics + daily_path_DD, harness never auto-promotes."""
    scen = _complete_scenario_rows()
    rows = [
        {
            "period_id": "y2015",
            "gross_signed_mean_active": -0.0005,
            "n_active_positions": 100,
        },
        {
            "period_id": "y2017",
            "gross_signed_mean_active": -0.0004,
            "n_active_positions": 100,
        },
        {
            "period_id": "y2019",
            "gross_signed_mean_active": -0.0006,
            "n_active_positions": 100,
        },
    ]
    out = run_standard_research_eval(
        dry_run=True,
        mode="wiring_only",
        period_rows_for_gate=rows,
        scenario_rows=scen,
        baseline_majority_sign=-1,
        baseline_net_majority_sign=-1,
        daily_path_pack=W99_DAILY_PATH_PACK,
    )
    assert out["risk_scenarios"]["passed"] is True
    assert out["risk_scenarios"]["research_candidate_allowed"] is True
    assert out["daily_path_dd"]["complete"] is True
    assert out["daily_path_dd"]["scorecard"]["daily_path_DD"] == W99_DAILY_PATH_PACK[
        "daily_path_DD"
    ]
    assert out["checklist_complete"] is True
    assert out["research_candidate_allowed"] is True
    # Hard: harness never auto-sets research_candidate True
    assert out["research_candidate"] is False
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["phase7"] == "OFF"
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["gate_pass_implies_research_candidate"] is False


def test_scenario_sign_break_prefers_fail_candidate():
    """Core scenario sign flip vs baseline → not research_candidate (prefer fail)."""
    scen = [
        scenario_row(
            SCENARIO_CRASH,
            gross_signed_mean=0.002,  # flips vs baseline −
            net_one_way_mean=0.001,
        ),
        scenario_row(
            SCENARIO_HIGH_VOL, gross_signed_mean=-0.0005, net_one_way_mean=-0.0015
        ),
        scenario_row(SCENARIO_RATE_UP, not_applicable=True, na_reason="n/a"),
        scenario_row(SCENARIO_RATE_DOWN, not_applicable=True, na_reason="n/a"),
        scenario_row(SCENARIO_LIQUIDITY_STRESS, not_applicable=True, na_reason="n/a"),
    ]
    out = run_standard_research_eval(
        dry_run=True,
        scenario_rows=scen,
        baseline_majority_sign=-1,
        baseline_net_majority_sign=-1,
        prefer_fail_on_sign_break=True,
    )
    assert out["risk_scenarios"]["stability_broken"] is True
    assert out["risk_scenarios"]["research_candidate_allowed"] is False
    assert out["research_candidate"] is False
    assert out["research_candidate_allowed"] is False
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"


def test_leverage_short_costs_long_only_and_long_short():
    lo = default_long_only_unlevered_cost_assumption()
    assert lo["version"] == COST_MODELS_VERSION
    assert lo["assumptions_complete"] is True
    assert lo["short_borrow"]["not_applicable"] is True
    assert lo["leverage_financing"]["not_applicable"] is True
    assert lo["ready_declared"] is False
    assert lo["connected_to_mass"] is False

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
    # daily ≈ 50bp / 245 * 0.5
    expected = short_borrow_daily_cost(
        short_borrow_annual_bp=50.0, short_fraction=0.5
    )
    assert abs(ls["short_borrow"]["daily_cost"] - expected) < 1e-12

    out = run_standard_research_eval(
        dry_run=True,
        position_style=POSITION_STYLE_LONG_SHORT,
        short_fraction=0.5,
        uses_short=True,
    )
    assert out["leverage_short_costs"]["uses_short"] is True
    assert out["leverage_short_costs"]["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"


def test_high_frequency_hyp_requires_holding_for_completeness():
    """HF hyps without holding_records → holding near-required fails completeness."""
    scen = [
        scenario_row(SCENARIO_CRASH, gross_signed_mean=-0.001, net_one_way_mean=-0.002),
        scenario_row(
            SCENARIO_HIGH_VOL, gross_signed_mean=-0.0008, net_one_way_mean=-0.0018
        ),
        scenario_row(SCENARIO_RATE_UP, not_applicable=True, na_reason="n/a"),
        scenario_row(SCENARIO_RATE_DOWN, not_applicable=True, na_reason="n/a"),
        scenario_row(SCENARIO_LIQUIDITY_STRESS, not_applicable=True, na_reason="n/a"),
    ]
    out = run_standard_research_eval(
        dry_run=True,
        scenario_rows=scen,
        high_frequency_hyp=True,
        # no holding_records
    )
    assert out["checklist_complete"] is False
    assert "holding_turnover_metrics" in out["checklist_completeness"]["missing_required"]
    assert out["research_candidate"] is False
    assert out["research_candidate_allowed"] is False

    records = [
        {"date": "2015-09-01", "code": "13010", "sign": 1},
        {"date": "2015-09-02", "code": "13010", "sign": 1},
        {"date": "2015-09-03", "code": "13010", "sign": -1},
    ]
    out2 = run_standard_research_eval(
        dry_run=True,
        scenario_rows=scen,
        high_frequency_hyp=True,
        holding_records=records,
        baseline_majority_sign=-1,
        baseline_net_majority_sign=-1,
        daily_path_pack=W99_DAILY_PATH_PACK,
    )
    assert out2["checklist_complete"] is True
    assert out2["research_candidate"] is False  # still no auto-promote
    assert out2["ready_declared"] is False


def test_evaluate_checklist_v2_completeness_helper():
    incomplete = evaluate_checklist_v2_completeness(
        multi_year_present=True,
        cost_assumption_present=True,
        leverage_short_complete=False,
        robustness_gate_present=True,
        data_gap_disclosed=True,
        risk_scenarios_passed=False,
        risk_scenarios_candidate_allowed=False,
        freeze_closed=True,
    )
    assert incomplete["complete"] is False
    assert incomplete["research_candidate_allowed"] is False
    assert "leverage_short_cost_assumptions" in incomplete["missing_required"]
    assert incomplete["ready_declared"] is False
    assert incomplete["mass_research"] == "NO-GO"

    complete = evaluate_checklist_v2_completeness(
        multi_year_present=True,
        cost_assumption_present=True,
        leverage_short_complete=True,
        robustness_gate_present=True,
        data_gap_disclosed=True,
        risk_scenarios_passed=True,
        risk_scenarios_candidate_allowed=True,
        freeze_closed=True,
        daily_path_dd_complete=True,
    )
    assert complete["complete"] is True
    assert complete["research_candidate_allowed"] is True
    assert complete["connected_to_ready"] is False
    assert complete["connected_to_mass"] is False


def test_evaluate_risk_scenarios_standalone():
    pending = evaluate_risk_scenarios(None)
    assert pending["passed"] is False
    assert pending["research_candidate_allowed"] is False
    assert pending["ready_declared"] is False

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
    assert full["mass_research"] == "NO-GO"
    assert full["connected_to_mass"] is False


def test_mass_ready_frozen_false_on_all_v2_paths():
    """Mass/READY stay false across wiring, complete scen, and sign-break paths."""
    for kwargs in (
        {},
        {
            "scenario_rows": [
                scenario_row(SCENARIO_CRASH, gross_signed_mean=-0.001),
                scenario_row(SCENARIO_HIGH_VOL, gross_signed_mean=-0.001),
                scenario_row(SCENARIO_RATE_UP, not_applicable=True, na_reason="n/a"),
                scenario_row(SCENARIO_RATE_DOWN, not_applicable=True, na_reason="n/a"),
                scenario_row(
                    SCENARIO_LIQUIDITY_STRESS, not_applicable=True, na_reason="n/a"
                ),
            ]
        },
        {
            "mode": "s1_rejected_baseline",
        },
    ):
        out = run_standard_research_eval(dry_run=True, **kwargs)
        assert out["ready_declared"] is False
        assert out["operational_go"] is False
        assert out["mass_research"] == "NO-GO"
        assert out["phase7"] == "OFF"
        assert out["connected_to_ready"] is False
        assert out["connected_to_mass"] is False
        assert out["research_candidate"] is False


# ---------------------------------------------------------------------------
# W100 / w0819c — daily_path_DD mandatory gate
# ---------------------------------------------------------------------------


def test_daily_path_dd_unmeasured_is_incomplete():
    """Scenarios alone are not enough — missing daily_path_DD → incomplete."""
    out = run_standard_research_eval(
        dry_run=True,
        scenario_rows=_complete_scenario_rows(),
        baseline_majority_sign=-1,
        baseline_net_majority_sign=-1,
    )
    assert out["risk_scenarios"]["passed"] is True
    assert out["daily_path_dd"]["measured"] is False
    assert out["daily_path_dd"]["complete"] is False
    assert "daily_path_DD_unmeasured" in out["daily_path_dd"]["fails"]
    assert "daily_path_dd" in out["checklist_completeness"]["missing_required"]
    assert out["checklist_complete"] is False
    assert out["research_candidate_allowed"] is False
    assert out["research_candidate"] is False
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"


def test_period_net_dd_zero_daily_unmeasured_is_incomplete():
    """period_net_DD=0 AND daily unmeasured = incomplete (not riskless)."""
    out = run_standard_research_eval(
        dry_run=True,
        scenario_rows=_complete_scenario_rows(),
        period_net_dd=0.0,
    )
    pack = out["daily_path_dd"]
    assert pack["period_net_dd_zero_daily_unmeasured"] is True
    assert pack["period_net_dd_only"] is True
    assert pack["period_net_dd_only_pass_forbidden"] is True
    assert pack["complete"] is False
    assert pack["passed"] is False
    assert "period_net_DD_zero_daily_unmeasured" in pack["fails"]
    assert "period_net_DD_only_pass_forbidden" in pack["fails"]
    assert any("aggregation artifact" in w for w in pack["warnings"])
    assert out["checklist_complete"] is False
    assert out["research_candidate_allowed"] is False
    assert out["checklist_completeness"]["period_net_dd_zero_daily_unmeasured"] is True
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"


def test_period_net_dd_only_cannot_pass_even_if_nonzero():
    """Passing on period_net_DD alone is forbidden regardless of the number."""
    gate = evaluate_daily_path_dd_gate(period_net_dd=-0.0023)
    assert gate["period_net_dd_only"] is True
    assert gate["complete"] is False
    assert gate["passed"] is False
    assert "period_net_DD_only_pass_forbidden" in gate["fails"]
    assert gate["ready_declared"] is False

    out = run_standard_research_eval(
        dry_run=True,
        scenario_rows=_complete_scenario_rows(),
        period_net_dd=-0.0023,
        daily_path_method="period_net_cumsum_proxy",
    )
    assert out["daily_path_dd"]["period_net_dd_only"] is True
    assert out["daily_path_dd"]["complete"] is False
    assert out["checklist_complete"] is False
    assert out["research_candidate_allowed"] is False
    assert out["research_candidate"] is False


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


def test_w99_sticky_reference_daily_path_completes_item():
    """W99 sticky table is the reference measured daily-path example."""
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
    # period_net_DD=0 is a warning only when daily is measured
    assert gate["period_net_dd_zero_daily_unmeasured"] is False
    assert any("aggregation artifact" in w for w in gate["warnings"])
    assert set(DAILY_PATH_DD_REQUIRED_FIELDS) == {
        "daily_path_DD",
        "dd_duration",
        "recovery",
        "total_ret_net",
    }
    assert gate["ready_declared"] is False
    assert gate["mass_research"] == "NO-GO"


def test_daily_path_from_equity_curve():
    """Level equity peak-to-trough (not period-net cumsum) is the daily method."""
    # 1.0 → 1.2 → 0.9 → 1.2  (DD = 0.9/1.2 - 1 = -0.25, duration 1, recovery 1)
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
        # recovery_days missing
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


def test_evaluate_checklist_blocks_period_net_only_even_if_flagged_complete():
    """period_net_dd_only=True cannot pass the daily_path_dd item."""
    blocked = evaluate_checklist_v2_completeness(
        multi_year_present=True,
        cost_assumption_present=True,
        leverage_short_complete=True,
        robustness_gate_present=True,
        data_gap_disclosed=True,
        risk_scenarios_passed=True,
        risk_scenarios_candidate_allowed=True,
        freeze_closed=True,
        daily_path_dd_complete=True,  # caller lied
        period_net_dd_only=True,
    )
    assert blocked["complete"] is False
    assert blocked["research_candidate_allowed"] is False
    assert "daily_path_dd" in blocked["missing_required"]
    assert blocked["period_net_dd_only"] is True
    assert blocked["ready_declared"] is False
