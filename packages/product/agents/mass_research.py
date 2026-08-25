"""Mass entry — fail-closed until a signed Mass-scoped READY exists.

Operator override and pilot-scoped readiness cannot substitute for
``VerifiedMassReadiness``.
"""

from __future__ import annotations

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
)
from research.readiness import (
    VerifiedMassReadiness,
    require_mass_research_start,
)


def start_mass_research(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedMassReadiness | None = None,
    expected_snapshot_id: str | None = None,
    # Explicitly reject legacy / unsafe kwargs.
    operator_override: object | None = None,
    ready_count: int | None = None,
    governed_complete: int | None = None,
    governed_total: int | None = None,
    go_override: bool | None = None,
) -> tuple[ResearchBudgetCapability, VerifiedMassReadiness]:
    if operator_override is not None:
        raise MassResearchDisabledError(
            "operator_override cannot substitute for VerifiedMassReadiness"
        )
    if any(
        v is not None
        for v in (ready_count, governed_complete, governed_total, go_override)
    ):
        raise MassResearchDisabledError(
            "caller-supplied ready_count/governed_complete/governed_total/"
            "go_override are rejected"
        )
    return require_mass_research_start(
        budget=budget,
        readiness=readiness,
        expected_snapshot_id=expected_snapshot_id,
    )


def assert_mass_research_allowed(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedMassReadiness | None = None,
    **legacy: object,
) -> ResearchBudgetCapability:
    cap, _ = start_mass_research(budget=budget, readiness=readiness, **legacy)  # type: ignore[arg-type]
    return cap


__all__ = [
    "MassResearchDisabledError",
    "assert_mass_research_allowed",
    "start_mass_research",
]
