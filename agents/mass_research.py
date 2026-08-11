"""Mass research entry — fail-closed until trusted attestation exists.

Caller-supplied ready_count / governed_complete scalars and go_override:bool
are removed. Start requires ResearchBudgetCapability plus
VerifiedResearchReadiness (or a live OperatorOverrideCapability).
"""

from __future__ import annotations

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
)
from research.readiness import (
    OperatorOverrideCapability,
    VerifiedResearchReadiness,
    require_mass_research_start,
)


def start_mass_research(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedResearchReadiness | None = None,
    operator_override: OperatorOverrideCapability | None = None,
) -> tuple[ResearchBudgetCapability, VerifiedResearchReadiness | OperatorOverrideCapability]:
    """Authorize mass research start. Does not enable mass loops by itself."""
    return require_mass_research_start(
        budget=budget,
        readiness=readiness,
        operator_override=operator_override,
    )


# Backward-compatible name: still fail-closed, rejects scalar spoofing paths.
def assert_mass_research_allowed(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedResearchReadiness | None = None,
    operator_override: OperatorOverrideCapability | None = None,
    # Explicitly reject legacy kwargs if callers still pass them.
    ready_count: int | None = None,
    governed_complete: int | None = None,
    governed_total: int | None = None,
    go_override: bool | None = None,
) -> ResearchBudgetCapability:
    """Deprecated entry — use start_mass_research.

    Any legacy scalar / go_override argument is rejected as a hard error so
    spoofing paths cannot silently succeed.
    """
    if any(
        v is not None
        for v in (ready_count, governed_complete, governed_total, go_override)
    ):
        raise MassResearchDisabledError(
            "caller-supplied ready_count/governed_complete/governed_total/"
            "go_override are rejected; pass VerifiedResearchReadiness"
        )
    cap, _att = start_mass_research(
        budget=budget,
        readiness=readiness,
        operator_override=operator_override,
    )
    return cap


__all__ = [
    "MassResearchDisabledError",
    "assert_mass_research_allowed",
    "start_mass_research",
]
