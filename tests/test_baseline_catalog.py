"""W65 research baseline catalog — rejected S1–S5; Mass/READY remain false."""

from __future__ import annotations

import ast
from pathlib import Path

from research.baseline_catalog import (
    CATALOG_VERSION,
    REJECTED_SIMPLE_DAILY_SIGN_BASELINES,
    RESEARCH_STATUS_REJECTED,
    SIGNAL_ID_S1,
    SIGNAL_ID_S2,
    SIGNAL_ID_S3,
    SIGNAL_ID_S4,
    SIGNAL_ID_S5,
    assert_catalog_closed_to_ready_mass,
    get_rejected_baseline,
    is_research_baseline_rejected,
    rejected_baseline_catalog,
)
from research.robustness_gate import evaluate_research_robustness_gate

REPO = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO / "packages" / "product" / "research" / "baseline_catalog.py"


def test_rejected_catalog_exists_and_lists_s1_to_s5():
    doc = rejected_baseline_catalog()
    assert doc["version"] == CATALOG_VERSION
    assert doc["research_status_value"] == RESEARCH_STATUS_REJECTED
    assert set(doc["signal_ids"]) == {
        SIGNAL_ID_S1,
        SIGNAL_ID_S2,
        SIGNAL_ID_S3,
        SIGNAL_ID_S4,
        SIGNAL_ID_S5,
    }
    assert set(doc["hyp_ids"]) == {"S1", "S2", "S3", "S4", "S5"}
    assert len(REJECTED_SIMPLE_DAILY_SIGN_BASELINES) == 5
    for sid in (SIGNAL_ID_S1, SIGNAL_ID_S2, SIGNAL_ID_S3, SIGNAL_ID_S4, SIGNAL_ID_S5):
        entry = get_rejected_baseline(sid)
        assert entry is not None
        assert entry["research_status"] == RESEARCH_STATUS_REJECTED
        assert entry["ready_declared"] is False
        assert entry["mass_research"] == "NO-GO"
        assert entry["phase7"] == "OFF"
        assert entry["connected_to_ready"] is False
        assert entry["connected_to_mass"] is False
        assert entry["mass_generate_signals"] is False
        assert entry["edge_claimed"] is False
        assert is_research_baseline_rejected(sid) is True
        assert entry.get("cost_gate_result")
        assert entry.get("reasons")
        assert entry.get("wave")


def test_catalog_mass_ready_remain_false():
    assert_catalog_closed_to_ready_mass()
    doc = rejected_baseline_catalog()
    assert_catalog_closed_to_ready_mass(doc)
    assert doc["ready_declared"] is False
    assert doc["operational_go"] is False
    assert doc["connected_to_ready"] is False
    assert doc["connected_to_mass"] is False
    assert doc["mass_research"] == "NO-GO"
    assert doc["phase7"] == "OFF"
    assert doc["mass_generate_signals"] is False
    assert doc["edge_claimed"] is False
    assert doc["significance_claimed"] is False


def test_gate_pass_still_not_ready_with_catalog_present():
    """Keep gate pass ≠ READY even when rejected catalog exists."""
    # Soft cost-aware pass (e.g. S4-like all − after cost) still not READY.
    rows = [
        {
            "period_id": "p1",
            "gross_signed_mean_active": -0.0005,
            "n_active_positions": 100,
        },
        {
            "period_id": "p2",
            "gross_signed_mean_active": -0.0003,
            "n_active_positions": 100,
        },
        {
            "period_id": "p3",
            "gross_signed_mean_active": -0.0008,
            "n_active_positions": 100,
        },
    ]
    out = evaluate_research_robustness_gate(
        rows,
        signal_id=SIGNAL_ID_S4,
        require_net_sign_majority=True,
    )
    assert out["passed"] is True
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["mass_research"] == "NO-GO"
    # Catalog marks S4 rejected despite soft gate pass (weak not candidate).
    s4 = get_rejected_baseline(SIGNAL_ID_S4)
    assert s4 is not None
    assert s4["research_status"] == RESEARCH_STATUS_REJECTED
    assert s4["cost_gate_result"] == "PASS_weak_not_candidate"
    assert s4["ready_declared"] is False


def test_s1_cost_fail_recorded_in_catalog():
    s1 = get_rejected_baseline(SIGNAL_ID_S1)
    assert s1 is not None
    assert s1["cost_gate_result"] == "FAIL"
    assert "cost_after_multi_year_destroys_gross_majority" in s1["reasons"]


def test_unknown_signal_not_rejected_by_default():
    assert is_research_baseline_rejected("not_a_signal") is False
    assert get_rejected_baseline("not_a_signal") is None


def test_catalog_module_ast_bans_ready_mass_orders():
    tree = ast.parse(CATALOG_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            for a in node.names:
                imported.add(a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name.split(".")[0])
    src = CATALOG_PATH.read_text(encoding="utf-8")
    assert "mass_research" not in imported
    assert "start_mass_research" not in imported
    assert "VerifiedResearchReadiness" not in imported
    assert "READY_DECLARED: bool = True" not in src
    assert "OPERATIONAL_GO: bool = True" not in src
    assert "CONNECTED_TO_READY: bool = True" not in src
    assert "CONNECTED_TO_MASS: bool = True" not in src
    assert "MASS_GENERATE_SIGNALS: bool = True" not in src
