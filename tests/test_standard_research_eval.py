"""W66 / w0815bg — standard research eval checklist harness entry.

Locks:
* dry_run wiring completes with READY false / Mass NO-GO / Phase7 OFF
* gate pass still not READY / not research_candidate
* does not register new signals
* rejected baselines (S1–S5) remain rejected
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
from research.eval_harness import (
    CHECKLIST_VERSION,
    MASS_RESEARCH,
    PHASE7,
    STANDARD_EVAL_MODES,
    EvalHarnessError,
    run_standard_research_eval,
    standard_research_eval_checklist_document,
    standard_research_eval_checklist_run,
)
from research.robustness_gate import evaluate_research_robustness_gate

REPO = Path(__file__).resolve().parents[1]
EVAL_HARNESS_PATH = REPO / "packages" / "product" / "research" / "eval_harness.py"


def test_dry_run_wiring_completes_mass_ready_phase7_closed():
    out = run_standard_research_eval(dry_run=True)
    assert out["checklist_version"] == CHECKLIST_VERSION
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
    assert out["holding"] is not None
    assert out["multi_year"]["status"] == "wiring_only"
    assert len(out["designed_periods"]) >= 1


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
