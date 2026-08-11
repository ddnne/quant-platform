"""Mass research gate — attestation required; scalar spoof rejected."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.mass_research import assert_mass_research_allowed, start_mass_research
from research.readiness import (
    OperatorOverrideService,
    VerifiedResearchReadiness,
)
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget


def _cap(tmp_path: Path) -> ResearchBudgetCapability:
    return ResearchBudgetCapability(
        "b", tmp_path / "b.sqlite", ExperimentBudget()
    )


def test_mass_research_fail_closed_no_budget():
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)


def test_mass_research_fail_closed_no_readiness(tmp_path: Path):
    cap = _cap(tmp_path)
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=cap, readiness=None)


def test_legacy_scalar_kwargs_rejected(tmp_path: Path):
    cap = _cap(tmp_path)
    with pytest.raises(MassResearchDisabledError, match="caller-supplied"):
        assert_mass_research_allowed(
            budget=cap,
            ready_count=1,
            governed_complete=26,
            governed_total=26,
        )


def test_go_override_bool_rejected(tmp_path: Path):
    cap = _cap(tmp_path)
    with pytest.raises(MassResearchDisabledError, match="caller-supplied"):
        assert_mass_research_allowed(budget=cap, go_override=True)


def test_start_with_verified_readiness(tmp_path: Path):
    cap = _cap(tmp_path)
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
    got_cap, got_att = start_mass_research(budget=cap, readiness=readiness)
    assert got_cap is cap
    assert got_att is readiness


def test_operator_override_live(tmp_path: Path):
    cap = _cap(tmp_path)
    ov = OperatorOverrideService(audit_dir=tmp_path / "audit").mint(
        reason="emergency test",
        operator_identity="operator:test",
        ttl_seconds=600,
    )
    got_cap, got = start_mass_research(budget=cap, operator_override=ov)
    assert got_cap is cap
    assert got.override_id == ov.override_id
