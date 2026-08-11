"""Phase 6.2.2 remainder: issuer, scheduler, evaluation, JSDA parse discover."""

from __future__ import annotations

from pathlib import Path

import pytest

from research.artifacts import ExperimentPlan, ResearchIdea
from research.evaluation import EvaluationHarness
from research.readiness import VerifiedResearchReadiness
from research.scheduler import ExperimentScheduler
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget
from storage.trusted_receipt import TrustedReceiptIssuer
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    build_collection_receipt,
    is_complete_eligible_receipt,
)


def test_storage_package_hides_synthetic():
    import storage

    assert not hasattr(storage, "build_synthetic_complete_receipt")
    assert hasattr(storage, "TrustedReceiptIssuer")


def test_issuer_required_for_complete_eligible():
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
    issued = TrustedReceiptIssuer(issuer_id="t:1").issue(
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

    readiness = VerifiedResearchReadiness(
        attestation_id="a1",
        snapshot_id="snap-1",
        ready_state="READY",
        ready_manifest_digest="sha256:" + "a" * 64,
        coverage_policy_version="collection-coverage/v2",
        coverage_proof_digest="sha256:" + "b" * 64,
        governed_membership_digest="sha256:" + "c" * 64,
        governed_complete=26,
        governed_total=26,
        b0_status="PASS",
        quality_status="PASS",
        source_generation=1,
        sync_generation=1,
        raw_proof_status="COMPLETE",
        verified_at="2026-01-01T00:00:00+00:00",
        evidence_digest="sha256:" + "d" * 64,
    )
    scheduled = sched.schedule(plan=plan, readiness=readiness)
    assert scheduled.lease.lease_id
    assert scheduled.plan.plan_id == "p1"
    sched.release(scheduled)


def test_evaluation_harness_signal_vs_state():
    h = EvaluationHarness()
    incomplete = h.evaluate(
        plan_id="p",
        feature_role="signal",
        metrics={"drawdown": 0.1},
    )
    assert not incomplete.complete
    assert "cost_before" in incomplete.missing_required
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
    sel = h.selection_inputs(complete)
    assert sel["reason_hint"] == "REVIEW_REQUIRED"


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
