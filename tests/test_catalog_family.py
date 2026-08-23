"""Family reclass: flow gates are not a flow thesis. Not GO."""
from __future__ import annotations

from research.catalog_family import catalog_family_report, classify_catalog_row


def test_surprise_with_flow_gate_is_not_flow_family() -> None:
    row = classify_catalog_row(
        {
            "logic_id": "surprise_xs_crowded_margin",
            "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
            "params": {"gates": ["crowded_margin", "liq_high"]},
        }
    )
    assert row["primary_hypothesis"] == "surprise_xs"
    assert row["flow_family"] is False
    assert "flow_gate" in row["gate_tags"]
    assert row["go"] is False


def test_catalog_family_report_counts() -> None:
    rep = catalog_family_report()
    assert rep["n"] >= 1
    assert rep["n_flow_gate_but_not_flow_family"] >= 0
    assert rep["go"] is False
    assert rep["not_a_pass"] is True
