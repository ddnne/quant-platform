"""Experiment scheduler — readiness signature re-checked at schedule time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research.artifacts import ExperimentPlan
from research.readiness import (
    MassResearchDisabledError,
    VerifiedResearchReadiness,
    require_mass_research_start,
)
from selection.budget_ledger import (
    ExperimentSlotLease,
    ResearchBudgetCapability,
)


@dataclass(frozen=True)
class ScheduledExperiment:
    plan: ExperimentPlan
    lease: ExperimentSlotLease
    readiness_attestation_id: str
    budget_id: str
    snapshot_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan.plan_id,
            "lease_id": self.lease.lease_id,
            "readiness_attestation_id": self.readiness_attestation_id,
            "budget_id": self.budget_id,
            "ready_snapshot_id": self.snapshot_id,
        }


class ExperimentScheduler:
    def __init__(self, *, budget: ResearchBudgetCapability) -> None:
        self._budget = budget

    def schedule(
        self,
        *,
        plan: ExperimentPlan,
        readiness: VerifiedResearchReadiness | None = None,
        lease_ttl_seconds: int = 3600,
    ) -> ScheduledExperiment:
        if not isinstance(plan, ExperimentPlan):
            raise MassResearchDisabledError("ExperimentPlan required")
        if not plan.ready_snapshot_id.strip():
            raise MassResearchDisabledError("plan.ready_snapshot_id required")
        cap, att = require_mass_research_start(
            budget=self._budget,
            readiness=readiness,
            expected_snapshot_id=plan.ready_snapshot_id,
        )
        # Re-verify immediately before lease (expired/forged rejection).
        att.require_valid(expected_snapshot_id=plan.ready_snapshot_id)
        lease = cap.acquire_slot(ttl_seconds=lease_ttl_seconds)
        try:
            cap.consume(generations=1)
        except Exception:
            cap.release(lease)
            raise
        return ScheduledExperiment(
            plan=plan,
            lease=lease,
            readiness_attestation_id=att.attestation_id,
            budget_id=cap.budget_id,
            snapshot_id=att.snapshot_id,
        )

    def release(self, scheduled: ScheduledExperiment) -> None:
        self._budget.release(scheduled.lease)


__all__ = ["ExperimentScheduler", "ScheduledExperiment"]
