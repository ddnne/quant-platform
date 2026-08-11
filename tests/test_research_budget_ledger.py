from pathlib import Path

import pytest

from selection.budget_ledger import (
    BudgetExhaustedError,
    MassResearchDisabledError,
    ResearchBudgetCapability,
    require_budget_capability,
)
from selection.screen import ExperimentBudget


def test_require_budget_fail_closed():
    with pytest.raises(MassResearchDisabledError):
        require_budget_capability(None)


def test_atomic_consume_and_exhaust(tmp_path: Path):
    cap = ResearchBudgetCapability(
        budget_id="b1",
        ledger_path=tmp_path / "budget.sqlite",
        limits=ExperimentBudget(max_model_calls=3, max_generations=2, max_paper_runs=5),
    )
    cap.consume(model_calls=2)
    assert cap.snapshot()["model_calls"] == 2
    with pytest.raises(BudgetExhaustedError):
        cap.consume(model_calls=2)
    assert cap.snapshot()["model_calls"] == 2  # not partially applied
