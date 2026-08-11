"""Mass research entry — fail-closed until Phase 7 GO conditions.

Must not start without ResearchBudgetCapability. Does not enable mass loops.
"""
from __future__ import annotations

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
    require_budget_capability,
)


def assert_mass_research_allowed(
    *,
    budget: ResearchBudgetCapability | None,
    ready_count: int,
    governed_complete: int,
    governed_total: int,
    go_override: bool = False,
) -> ResearchBudgetCapability:
    """Raise unless structural GO gates pass. Never auto-enables mass loops."""
    cap = require_budget_capability(budget)
    if go_override:
        return cap
    if ready_count < 1:
        raise MassResearchDisabledError("READY < 1 — mass research NO-GO")
    if governed_complete < governed_total or governed_total <= 0:
        raise MassResearchDisabledError(
            f"governed COMPLETE {governed_complete}/{governed_total} — mass research NO-GO"
        )
    return cap


__all__ = ["assert_mass_research_allowed"]
