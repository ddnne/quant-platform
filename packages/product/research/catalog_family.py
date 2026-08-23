"""Reclassify catalog families. Gate tags are not the hypothesis.

Does not add YAML. Does not GO. surprise_xs/event evaluator with a
flow gate is not a flow thesis.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from research.unique_logic.catalog import load_catalog_specs, spec_gates
from research.unique_logic.constants import PRI_FLOW_GATES, PRI_FUND_GATES, PRI_RATE_GATES, PRI_VOL_GATES


def classify_catalog_row(spec: Mapping[str, Any]) -> dict[str, Any]:
    lid = str(spec.get("logic_id") or "")
    evaluator = str(spec.get("evaluator") or "")
    gates = spec_gates(spec)
    primary_gate = gates[0] if gates else ""
    if "surprise_xs" in lid or "surprise_xs" in evaluator:
        hypothesis = "surprise_xs"
        evaluator_family = "event_combos"
    elif lid.startswith("event_") or "event_combos" in evaluator:
        hypothesis = "event"
        evaluator_family = "event_combos"
    elif lid.startswith("cs_") or "cross_section" in evaluator:
        hypothesis = "cross_section"
        evaluator_family = "cross_section"
    else:
        hypothesis = "other"
        evaluator_family = evaluator.rsplit(".", 1)[-1] or "other"
    gate_tags = []
    gset = set(gates)
    if gset & PRI_FLOW_GATES:
        gate_tags.append("flow_gate")
    if gset & PRI_VOL_GATES:
        gate_tags.append("vol_gate")
    if gset & PRI_RATE_GATES:
        gate_tags.append("rate_gate")
    if gset & PRI_FUND_GATES:
        gate_tags.append("fund_gate")
    return {
        "logic_id": lid,
        "primary_hypothesis": hypothesis,
        "evaluator_family": evaluator_family,
        "primary_gate": primary_gate,
        "n_ands": len(gates),
        "secondary_gates": gates[1:],
        "gate_tags": gate_tags,
        "flow_family": hypothesis == "other" and "flow_gate" in gate_tags and len(gates) == 1,
        "go": False,
        "not_a_pass": True,
    }


def catalog_family_report(specs: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    rows = [classify_catalog_row(s) for s in (specs or load_catalog_specs())]
    hyp = Counter(r["primary_hypothesis"] for r in rows)
    return {
        "n": len(rows),
        "primary_hypothesis": dict(hyp),
        "n_flow_family_true": sum(1 for r in rows if r["flow_family"]),
        "n_flow_gate_but_not_flow_family": sum(
            1 for r in rows if "flow_gate" in r["gate_tags"] and not r["flow_family"]
        ),
        "go": False,
        "not_a_pass": True,
    }
