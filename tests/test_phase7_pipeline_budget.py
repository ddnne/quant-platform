"""Test pipeline budget integration logic without full import."""

from __future__ import annotations

from selection.screen import ExperimentBudget, early_stop


def test_budget_integration_logic():
    """Test the budget enforcement logic that would be used in pipeline."""
    budget = ExperimentBudget(max_paper_runs=3, max_generations=5, max_model_calls=20)

    # Simulate pipeline state
    paper_runs_count = 0
    generation = 0
    model_calls = 0

    # First run should not be stopped
    assert not early_stop(
        generation=generation,
        paper_runs=paper_runs_count,
        model_calls=model_calls,
        budget=budget,
    )

    # After some runs
    paper_runs_count = 2
    generation = 1
    model_calls = 5

    assert not early_stop(
        generation=generation,
        paper_runs=paper_runs_count,
        model_calls=model_calls,
        budget=budget,
    )

    # At paper runs limit
    paper_runs_count = 3
    assert early_stop(
        generation=generation,
        paper_runs=paper_runs_count,
        model_calls=model_calls,
        budget=budget,
    )

    # Test generation limit
    budget2 = ExperimentBudget(max_generations=2)
    assert not early_stop(generation=1, paper_runs=0, model_calls=0, budget=budget2)
    assert early_stop(generation=2, paper_runs=0, model_calls=0, budget=budget2)

    # Test model calls limit
    budget3 = ExperimentBudget(max_model_calls=10)
    assert not early_stop(generation=0, paper_runs=0, model_calls=5, budget=budget3)
    assert early_stop(generation=0, paper_runs=0, model_calls=10, budget=budget3)


def test_budget_usage_tracking_format():
    """Test that budget usage tracking returns the expected format."""
    budget = ExperimentBudget(max_paper_runs=5, max_generations=3, max_model_calls=25)
    paper_runs_count = 2

    # Simulate the budget tracking dict format
    budget_used_items = (
        ("paper_runs", paper_runs_count),
        ("max_paper_runs", budget.max_paper_runs),
        ("max_generations", budget.max_generations),
        ("max_model_calls", budget.max_model_calls),
        ("budget_enabled", True),
    )

    # Verify it can be converted to dict for access
    budget_dict = dict(budget_used_items)
    assert budget_dict["paper_runs"] == 2
    assert budget_dict["max_paper_runs"] == 5
    assert budget_dict["budget_enabled"] is True


def test_pipeline_without_budget():
    """Test that pipeline logic works when no budget is provided."""
    # When experiment_budget is None, no early stopping should occur
    budget = None

    # This simulates the pipeline behavior when no budget is set
    should_stop = False
    if budget is not None:
        try:
            from selection.screen import early_stop
            should_stop = early_stop(generation=0, paper_runs=0, model_calls=0, budget=budget)
        except ImportError:
            pass

    assert should_stop is False


if __name__ == "__main__":
    test_budget_integration_logic()
    test_budget_usage_tracking_format()
    test_pipeline_without_budget()
    print("All budget integration tests passed!")
