"""Deterministic selection and experiment budget enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

@dataclass(frozen=True)
class OfflineExperimentBudget:
    """Caller-tunable budget for DRAFT/offline screening and fixture runs.

    This value is not a controlled-pilot policy or authorization capability.
    Controlled v2 claims pin ``ControlledPilotPolicyPin`` loaded from the
    digest-checked policy source of truth and never consume these overrides.
    """

    max_parallel_experiments: int = 2
    max_generations: int = 1
    max_model_calls: int = 16
    max_paper_runs: int = 8
    max_input_tokens: int = 400_000
    max_output_tokens: int = 80_000
    max_cached_tokens: int = 400_000
    max_compute_time_ms: int = 3_600_000
    max_estimated_cost_micros: int = 20_000_000
    lease_ttl_seconds: int = 1_800
    automatic_promotion: bool = False

    def __post_init__(self) -> None:
        if self.max_parallel_experiments < 1:
            raise ValueError("max_parallel_experiments must be >= 1")
        if self.max_generations < 1:
            raise ValueError("max_generations must be >= 1")
        if self.max_input_tokens < 1 or self.max_output_tokens < 1:
            raise ValueError("token budgets must be >= 1")
        if self.lease_ttl_seconds < 30:
            raise ValueError("lease_ttl_seconds must be >= 30")
        if self.automatic_promotion:
            raise ValueError("automatic promotion is disabled")


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
    budget: OfflineExperimentBudget,
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


# Compatibility name for the offline API.  New controlled code must never use
# this alias as an authority or policy input.
ExperimentBudget = OfflineExperimentBudget


__all__ = [
    "ExperimentBudget",
    "OfflineExperimentBudget",
    "early_stop",
    "screen_candidates",
]
