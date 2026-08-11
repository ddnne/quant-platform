import pytest
from agents.mass_research import assert_mass_research_allowed
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget
from pathlib import Path


def test_mass_research_fail_closed_no_budget():
    with pytest.raises(MassResearchDisabledError):
        assert_mass_research_allowed(
            budget=None, ready_count=1, governed_complete=26, governed_total=26
        )


def test_mass_research_fail_closed_no_ready(tmp_path: Path):
    cap = ResearchBudgetCapability(
        "b", tmp_path / "b.sqlite", ExperimentBudget()
    )
    with pytest.raises(MassResearchDisabledError):
        assert_mass_research_allowed(
            budget=cap, ready_count=0, governed_complete=26, governed_total=26
        )
