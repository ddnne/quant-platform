"""W62 research robustness gate — pass ≠ READY/Mass/GO."""

from __future__ import annotations

import pytest

from research.robustness_gate import (
    GATE_LABEL,
    GATE_VERSION,
    evaluate_research_robustness_gate,
    period_rows_from_cross_table,
    walk_forward_gross_from_compare,
)

def test_gate_document_closed_to_ready_mass():
    assert GATE_VERSION.startswith("research-robustness-gate/")
    assert "運用GO" in GATE_LABEL
    out = evaluate_research_robustness_gate([], signal_id="s")
    assert out["version"] == GATE_VERSION
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["phase7"] == "OFF"


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
    out = evaluate_research_robustness_gate(
        rows,
        signal_id="c21_topix_relative_sign",
        require_net_sign_majority=False,
    )
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
    out = evaluate_research_robustness_gate(
        rows, signal_id="s", require_net_sign_majority=False
    )
    assert out["passed"] is False
    assert out["criteria"]["sign_majority"]["passed"] is False
    assert out["ready_declared"] is False
    assert out["connected_to_ready"] is False


def test_gate_pass_does_not_arm_ready():
    # Gross well above 10bp so net remains majority +
    rows = [
        {
            "period_id": "p1",
            "gross_signed_mean_active": 0.003,
            "n_active_positions": 50,
        },
        {
            "period_id": "p2",
            "gross_signed_mean_active": 0.0025,
            "n_active_positions": 50,
        },
        {
            "period_id": "p3",
            "gross_signed_mean_active": 0.002,
            "n_active_positions": 50,
        },
    ]
    out = evaluate_research_robustness_gate(rows, signal_id="hyp")
    assert out["passed"] is True
    assert out["cost_aware_passed"] is True
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["significance_claimed"] is False
    assert out["edge_claimed"] is False


def test_gate_cost_after_fails_when_net_sign_splits():
    """W64: gross majority alone is insufficient if net signs split after 10bp."""
    rows = [
        # gross all + small (~8–12bp) → after 10bp cost half flip to −
        {"period_id": "a", "gross_signed_mean_active": 0.0012, "n_active_positions": 100},
        {"period_id": "b", "gross_signed_mean_active": 0.0011, "n_active_positions": 100},
        {"period_id": "c", "gross_signed_mean_active": 0.0005, "n_active_positions": 100},
        {"period_id": "d", "gross_signed_mean_active": 0.0004, "n_active_positions": 100},
    ]
    gross_only = evaluate_research_robustness_gate(
        rows, signal_id="s", require_net_sign_majority=False
    )
    cost_on = evaluate_research_robustness_gate(
        rows, signal_id="s", require_net_sign_majority=True
    )
    assert gross_only["gross_only_passed"] is True
    assert cost_on["passed"] is False
    assert cost_on["criteria"]["net_sign_majority"]["passed"] is False
    assert cost_on["ready_declared"] is False
    assert cost_on["operational_go"] is False


def test_gate_wf_full_flip_advisory_or_hard():
    rows = [
        {"period_id": "p1", "gross_signed_mean_active": 0.003, "n_active_positions": 50},
        {"period_id": "p2", "gross_signed_mean_active": 0.003, "n_active_positions": 50},
    ]
    wf = walk_forward_gross_from_compare(
        [{"signal_id": "s", "gross_signed_mean_active": 0.002}],
        [{"signal_id": "s", "gross_signed_mean_active": -0.002}],
        signal_id="s",
    )
    soft = evaluate_research_robustness_gate(
        rows,
        signal_id="s",
        walk_forward=wf,
        require_wf_check=False,
        require_net_sign_majority=True,
    )
    assert soft["criteria"]["wf_not_full_flip"]["full_flip"] is True
    # soft: flip is advisory, may still pass multi-period criteria
    hard = evaluate_research_robustness_gate(
        rows,
        signal_id="s",
        walk_forward=wf,
        require_wf_check=True,
        require_net_sign_majority=True,
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
