"""W62 research robustness gate — pass ≠ READY/Mass/GO."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from research.robustness_gate import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    GATE_VERSION,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    evaluate_research_robustness_gate,
    period_rows_from_cross_table,
    research_robustness_gate_document,
    walk_forward_gross_from_compare,
)

REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "packages" / "product" / "research" / "robustness_gate.py"


def test_gate_document_closed_to_ready_mass():
    doc = research_robustness_gate_document()
    assert doc["version"] == GATE_VERSION
    assert doc["ready_declared"] is False
    assert doc["operational_go"] is False
    assert doc["connected_to_ready"] is False
    assert doc["connected_to_mass"] is False
    assert doc["mass_research"] == "NO-GO"
    assert doc["phase7"] == "OFF"
    assert READY_DECLARED is False
    assert OPERATIONAL_GO is False
    assert CONNECTED_TO_READY is False
    assert CONNECTED_TO_MASS is False
    assert MASS_RESEARCH == "NO-GO"
    assert PHASE7 == "OFF"


def test_gate_fails_single_period_tip_like_win():
    """One strong period is not enough (short-window illusion)."""
    rows = [
        {
            "period_id": "tip20",
            "status": "ok",
            "gross_signed_mean_active": 0.005,
            "n_active_positions": 600,
        }
    ]
    out = evaluate_research_robustness_gate(rows, signal_id="c21_topix_relative_sign")
    assert out["passed"] is False
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert any("multi_period" in r for r in out["reasons"])


def test_gate_fails_sign_disagreement():
    rows = [
        {
            "period_id": "a",
            "gross_signed_mean_active": 0.002,
            "n_active_positions": 100,
        },
        {
            "period_id": "b",
            "gross_signed_mean_active": -0.002,
            "n_active_positions": 100,
        },
    ]
    out = evaluate_research_robustness_gate(rows, signal_id="s")
    assert out["passed"] is False
    assert out["criteria"]["sign_majority"]["passed"] is False
    assert out["ready_declared"] is False
    assert out["connected_to_ready"] is False


def test_gate_pass_does_not_arm_ready():
    rows = [
        {
            "period_id": "p1",
            "gross_signed_mean_active": 0.001,
            "n_active_positions": 50,
        },
        {
            "period_id": "p2",
            "gross_signed_mean_active": 0.0015,
            "n_active_positions": 50,
        },
        {
            "period_id": "p3",
            "gross_signed_mean_active": 0.0008,
            "n_active_positions": 50,
        },
    ]
    out = evaluate_research_robustness_gate(rows, signal_id="hyp")
    assert out["passed"] is True
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["significance_claimed"] is False
    assert out["edge_claimed"] is False


def test_gate_wf_full_flip_advisory_or_hard():
    rows = [
        {"period_id": "p1", "gross_signed_mean_active": 0.001, "n_active_positions": 50},
        {"period_id": "p2", "gross_signed_mean_active": 0.001, "n_active_positions": 50},
    ]
    wf = walk_forward_gross_from_compare(
        [{"signal_id": "s", "gross_signed_mean_active": 0.002}],
        [{"signal_id": "s", "gross_signed_mean_active": -0.002}],
        signal_id="s",
    )
    soft = evaluate_research_robustness_gate(
        rows, signal_id="s", walk_forward=wf, require_wf_check=False
    )
    assert soft["criteria"]["wf_not_full_flip"]["full_flip"] is True
    # soft: flip is advisory, may still pass multi-period criteria
    hard = evaluate_research_robustness_gate(
        rows, signal_id="s", walk_forward=wf, require_wf_check=True
    )
    assert hard["passed"] is False
    assert any("wf_not_full_flip" in r for r in hard["reasons"])


def test_period_rows_from_cross_table():
    cross = [
        {
            "period_id": "w1",
            "signal_id": "c21_topix_relative_sign",
            "gross_signed_mean_active": 0.0,
            "n_active_positions": 100,
        },
        {
            "period_id": "w1",
            "signal_id": "c21_volume_change_sign",
            "gross_signed_mean_active": -0.001,
            "n_active_positions": 10,
        },
    ]
    rows = period_rows_from_cross_table(cross, signal_id="c21_topix_relative_sign")
    assert len(rows) == 1
    assert rows[0]["period_id"] == "w1"


def test_gate_module_ast_bans_ready_mass_orders():
    tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            for a in node.names:
                imported.add(a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name.split(".")[0])
    src = GATE_PATH.read_text(encoding="utf-8")
    assert "mass_research" not in imported
    assert "start_mass_research" not in imported
    assert "VerifiedResearchReadiness" not in imported
    assert "READY_DECLARED: bool = True" not in src
    assert "OPERATIONAL_GO: bool = True" not in src
    assert "CONNECTED_TO_READY: bool = True" not in src
    assert "CONNECTED_TO_MASS: bool = True" not in src
