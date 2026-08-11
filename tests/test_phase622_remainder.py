"""Phase 6.2.2/623 remainder: signature, scheduler, evaluation."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from research.artifacts import ExperimentPlan, ResearchIdea
from research.evaluation import EvaluationHarness
from research.scheduler import ExperimentScheduler
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    build_collection_receipt,
    is_complete_eligible_receipt,
)
from storage.receipt_crypto import ReceiptSigningKey, generate_keypair
from storage.trusted_receipt import SignedReceiptAuthority


def _auth(tmp_path: Path) -> SignedReceiptAuthority:
    import storage.receipt_crypto as rc

    priv_pem, pub, kid = generate_keypair(key_id="t1")
    keys_path = rc.PUBLIC_KEYS_PATH
    try:
        doc = json.loads(keys_path.read_text(encoding="utf-8"))
    except Exception:
        doc = {"schema_version": 1, "keys": []}
    klist = [k for k in (doc.get("keys") or []) if k.get("key_id") != kid]
    klist.append(
        {
            "key_id": kid,
            "public_key_b64": base64.b64encode(pub).decode(),
            "algorithm": "Ed25519",
        }
    )
    doc["keys"] = klist
    keys_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    priv = load_pem_private_key(priv_pem, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    return SignedReceiptAuthority(
        signing_key=ReceiptSigningKey(key_id=kid, _private=priv)
    )


def test_storage_package_hides_synthetic():
    import storage

    assert not hasattr(storage, "build_synthetic_complete_receipt")
    assert hasattr(storage, "SignedReceiptAuthority") or hasattr(
        storage, "TrustedReceiptIssuer"
    )


def test_issuer_required_for_complete_eligible(tmp_path: Path):
    req = RequiredCoverageSegment(
        source="jquants",
        dataset="markets_calendar",
        segment_id="2025-01",
        segment_start="2025-01-01",
        segment_end="2025-01-31",
        expected_scope={"month": "2025-01"},
        expected_items=1,
    )
    bare = build_collection_receipt(
        required=req,
        run_id=1,
        raw=b"{}",
        observed_items=1,
        structured_row_count=1,
    )
    assert not is_complete_eligible_receipt(bare)
    issued = _auth(tmp_path).issue(
        required=req,
        run_id=1,
        raw=b"{}",
        observed_items=1,
        structured_row_count=1,
    )
    assert is_complete_eligible_receipt(issued)


def test_experiment_scheduler_requires_readiness(tmp_path: Path):
    cap = ResearchBudgetCapability("s", tmp_path / "s.sqlite", ExperimentBudget())
    plan = ExperimentPlan.from_dict(
        {
            "plan_id": "p1",
            "idea_id": "i1",
            "strategy_spec_id": "st1",
            "feature_refs": [{"id": "f", "version": "v1"}],
            "ready_snapshot_id": "snap-1",
            "universe": ["1301"],
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "cost_scenario": "default",
            "evaluation_protocol": "signal-default",
            "budget_allocation": {"generations": 1},
        }
    )
    sched = ExperimentScheduler(budget=cap)
    with pytest.raises(MassResearchDisabledError):
        sched.schedule(plan=plan, readiness=None)


def test_evaluation_harness_signal_vs_state():
    h = EvaluationHarness()
    incomplete = h.evaluate(
        plan_id="p",
        feature_role="signal",
        metrics={"drawdown": 0.1},
    )
    assert not incomplete.complete
    full_metrics = {
        m: 0.0
        for m in (
            "cost_before",
            "cost_after",
            "drawdown",
            "turnover",
            "stability",
            "walk_forward",
            "regime_breakdown",
        )
    }
    complete = h.evaluate(plan_id="p", feature_role="signal", metrics=full_metrics)
    assert complete.complete


def test_research_idea_closed_schema():
    idea = ResearchIdea.from_dict(
        {
            "idea_id": "idea-1",
            "hypothesis": "h",
            "target_horizon": "20d",
            "intended_universe": ["1301"],
            "author": "human",
        }
    )
    assert idea.version.startswith("research-idea/")


def test_backfill_status_has_26_governed():
    from ops.backfill_planner import backfill_status_rows, inventory_all_governed_datasets

    assert len(inventory_all_governed_datasets()) == 26
    rows = backfill_status_rows()
    assert len(rows) == 26
    assert any(r["dataset"].startswith("jsda_") for r in rows)
