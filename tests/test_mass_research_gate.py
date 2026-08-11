"""Mass research gate — signed READY attestation only; no override bypass."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.mass_research import assert_mass_research_allowed, start_mass_research
from research.readiness import OperatorOverrideService
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


def test_operator_override_cannot_substitute(tmp_path: Path):
    cap = _cap(tmp_path)
    ov = OperatorOverrideService(audit_dir=tmp_path / "audit").mint(
        reason="test",
        operator_identity="op",
        scope="hold_period",
        ttl_seconds=600,
    )
    with pytest.raises(MassResearchDisabledError, match="operator_override"):
        start_mass_research(budget=cap, operator_override=ov)  # type: ignore[arg-type]


def test_safety_scope_override_rejected():
    with pytest.raises(ValueError):
        OperatorOverrideService().mint(
            reason="x",
            operator_identity="op",
            scope="mass_research",  # type: ignore[arg-type]
        )
