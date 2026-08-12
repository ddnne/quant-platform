"""Deterministic selection and experiment budget enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExperimentBudget:
    max_parallel_experiments: int = 4
    max_generations: int = 3
    max_model_calls: int = 50
    max_paper_runs: int = 20
    # Hard token/cost caps (required for mass research; never leave None).
    max_input_tokens: int = 2_000_000
    max_output_tokens: int = 500_000
    max_cached_tokens: int = 2_000_000
    max_compute_time_ms: int = 3_600_000
    max_estimated_cost_micros: int = 50_000_000  # $50 in micros

    def __post_init__(self) -> None:
        if self.max_parallel_experiments < 1:
            raise ValueError("max_parallel_experiments must be >= 1")
        if self.max_generations < 1:
            raise ValueError("max_generations must be >= 1")
        if self.max_input_tokens < 1 or self.max_output_tokens < 1:
            raise ValueError("token budgets must be >= 1")


def screen_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    min_score: float = 0.0,
    limit: int = 10,
) -> list[Mapping[str, Any]]:
    """Keep candidates with score >= min_score, highest first, bounded."""
    ranked = sorted(
        (c for c in candidates if float(c.get("score", 0.0)) >= min_score),
        key=lambda c: float(c.get("score", 0.0)),
        reverse=True,
    )
    return list(ranked[: max(0, limit)])


def early_stop(
    *,
    generation: int,
    paper_runs: int,
    model_calls: int,
    budget: ExperimentBudget,
    best_score: float | None = None,
    floor: float | None = None,
) -> bool:
    """Return True when the orchestrator must stop spending budget."""
    if generation >= budget.max_generations:
        return True
    if paper_runs >= budget.max_paper_runs:
        return True
    if model_calls >= budget.max_model_calls:
        return True
    if floor is not None and best_score is not None and best_score < floor:
        return True
    return False
