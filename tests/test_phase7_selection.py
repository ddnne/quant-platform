"""Phase 7 selection and budget tests."""

from __future__ import annotations

from selection.screen import ExperimentBudget, early_stop, screen_candidates


def test_experiment_budget_defaults():
    """ExperimentBudget should have sensible defaults."""
    budget = ExperimentBudget()
    assert budget.max_parallel_experiments == 2
    assert budget.max_generations == 1
    assert budget.max_model_calls == 16
    assert budget.max_paper_runs == 8
    assert budget.max_input_tokens == 400_000
    assert budget.max_output_tokens == 80_000
    assert budget.max_estimated_cost_micros == 20_000_000
    assert budget.lease_ttl_seconds == 1800
    assert budget.automatic_promotion is False


def test_experiment_budget_custom_values():
    """ExperimentBudget should accept custom values."""
    budget = ExperimentBudget(
        max_parallel_experiments=8,
        max_generations=5,
        max_model_calls=100,
        max_paper_runs=40,
    )
    assert budget.max_parallel_experiments == 8
    assert budget.max_generations == 5
    assert budget.max_model_calls == 100
    assert budget.max_paper_runs == 40


def test_experiment_budget_validation_min_parallel():
    """max_parallel_experiments must be >= 1."""
    try:
        ExperimentBudget(max_parallel_experiments=0)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "max_parallel_experiments must be >= 1" in str(e)


def test_experiment_budget_validation_min_generations():
    """max_generations must be >= 1."""
    try:
        ExperimentBudget(max_generations=0)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "max_generations must be >= 1" in str(e)


def test_early_stop_generation_limit():
    """Should stop when generation limit is reached."""
    budget = ExperimentBudget(max_generations=3)
    assert early_stop(generation=3, paper_runs=0, model_calls=0, budget=budget)
    assert not early_stop(generation=2, paper_runs=0, model_calls=0, budget=budget)


def test_early_stop_paper_runs_limit():
    """Should stop when paper runs limit is reached."""
    budget = ExperimentBudget(max_paper_runs=10)
    assert early_stop(generation=0, paper_runs=10, model_calls=0, budget=budget)
    assert not early_stop(generation=0, paper_runs=9, model_calls=0, budget=budget)


def test_early_stop_model_calls_limit():
    """Should stop when model calls limit is reached."""
    budget = ExperimentBudget(max_model_calls=25)
    assert early_stop(generation=0, paper_runs=0, model_calls=25, budget=budget)
    assert not early_stop(generation=0, paper_runs=0, model_calls=24, budget=budget)


def test_early_stop_floor_score():
    """Should stop when best_score falls below floor."""
    budget = ExperimentBudget()
    assert early_stop(
        generation=0, paper_runs=0, model_calls=0, budget=budget,
        best_score=0.3, floor=0.5,
    )
    # Should not stop if score is above floor
    assert not early_stop(
        generation=0, paper_runs=0, model_calls=0, budget=budget,
        best_score=0.6, floor=0.5,
    )


def test_early_stop_no_floor():
    """Without floor, should only stop on explicit limits."""
    budget = ExperimentBudget()
    # Low score alone shouldn't trigger stop without floor
    assert not early_stop(
        generation=0, paper_runs=0, model_calls=0, budget=budget,
        best_score=0.1, floor=None,
    )


def test_early_stop_combined_conditions():
    """Should stop when any condition is met."""
    budget = ExperimentBudget(max_generations=5, max_paper_runs=15)
    # Generation limit
    assert early_stop(generation=5, paper_runs=0, model_calls=0, budget=budget)
    # Paper runs limit
    assert early_stop(generation=0, paper_runs=15, model_calls=0, budget=budget)
    # Both limits exceeded
    assert early_stop(generation=10, paper_runs=20, model_calls=0, budget=budget)


def test_screen_candidates_basic():
    """Should screen candidates by minimum score."""
    candidates = [
        {"id": "a", "score": 0.1},
        {"id": "b", "score": 0.5},
        {"id": "c", "score": 0.9},
    ]
    result = screen_candidates(candidates, min_score=0.5)
    assert len(result) == 2
    assert all(c["score"] >= 0.5 for c in result)


def test_screen_candidates_ranking():
    """Should return candidates sorted by score (highest first)."""
    candidates = [
        {"id": "a", "score": 0.7},
        {"id": "b", "score": 0.9},
        {"id": "c", "score": 0.5},
    ]
    result = screen_candidates(candidates, min_score=0.0)
    assert result[0]["id"] == "b"  # highest
    assert result[1]["id"] == "a"  # middle
    assert result[2]["id"] == "c"  # lowest


def test_screen_candidates_limit():
    """Should respect limit parameter."""
    candidates = [
        {"id": str(i), "score": float(i)}
        for i in range(10)
    ]
    result = screen_candidates(candidates, min_score=0.0, limit=3)
    assert len(result) == 3
    assert result[0]["id"] == "9"  # highest score
    assert result[1]["id"] == "8"
    assert result[2]["id"] == "7"


def test_screen_candidates_zero_limit():
    """Should return empty list when limit is 0."""
    candidates = [{"id": "a", "score": 0.9}]
    result = screen_candidates(candidates, min_score=0.0, limit=0)
    assert len(result) == 0


def test_screen_candidates_no_score_field():
    """Should handle candidates without score field (default to 0.0)."""
    candidates = [
        {"id": "a", "score": 0.5},
        {"id": "b"},  # no score
        {"id": "c", "score": 0.8},
    ]
    result = screen_candidates(candidates, min_score=0.4)
    assert len(result) == 2
    assert result[0]["id"] == "c"
    assert result[1]["id"] == "a"


def test_screen_candidates_negative_scores():
    """Should handle negative scores correctly."""
    candidates = [
        {"id": "a", "score": -0.5},
        {"id": "b", "score": 0.5},
        {"id": "c", "score": 0.0},
    ]
    result = screen_candidates(candidates, min_score=0.0)
    assert len(result) == 2
    assert all(c["score"] >= 0.0 for c in result)
    assert not any(c["id"] == "a" for c in result)  # negative filtered


def test_screen_candidates_empty_input():
    """Should handle empty input gracefully."""
    result = screen_candidates([], min_score=0.5, limit=10)
    assert len(result) == 0


def test_screen_candidates_all_filtered():
    """Should return empty list when all candidates filtered out."""
    candidates = [
        {"id": "a", "score": 0.1},
        {"id": "b", "score": 0.2},
        {"id": "c", "score": 0.3},
    ]
    result = screen_candidates(candidates, min_score=0.5)
    assert len(result) == 0


def test_experiment_budget_multiple_limits_interaction():
    """Test that multiple budget limits work together correctly."""
    budget = ExperimentBudget(
        max_generations=2,
        max_paper_runs=5,
        max_model_calls=10,
    )

    # Within all limits
    assert not early_stop(generation=1, paper_runs=3, model_calls=5, budget=budget)

    # At generation limit (but others under)
    assert early_stop(generation=2, paper_runs=3, model_calls=5, budget=budget)

    # At paper runs limit (but others under)
    assert early_stop(generation=1, paper_runs=5, model_calls=5, budget=budget)

    # At model calls limit (but others under)
    assert early_stop(generation=1, paper_runs=3, model_calls=10, budget=budget)

    # Multiple limits exceeded
    assert early_stop(generation=3, paper_runs=6, model_calls=11, budget=budget)
