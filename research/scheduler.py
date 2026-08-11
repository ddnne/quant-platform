"""Experiment scheduler — fail-closed until readiness + budget + plan exist.

Does not enable mass autonomous research loops. Single experiment execution
authority only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research.artifacts import ExperimentPlan
from research.readiness import (
    MassResearchDisabledError,
    OperatorOverrideCapability,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan.plan_id,
            "lease_id": self.lease.lease_id,
            "readiness_attestation_id": self.readiness_attestation_id,
            "budget_id": self.budget_id,
            "ready_snapshot_id": self.plan.ready_snapshot_id,
        }


class ExperimentScheduler:
    """Schedules one experiment when all three authorities are present."""

    def __init__(self, *, budget: ResearchBudgetCapability) -> None:
        self._budget = budget

    def schedule(
        self,
        *,
        plan: ExperimentPlan,
        readiness: VerifiedResearchReadiness | None = None,
        operator_override: OperatorOverrideCapability | None = None,
        lease_ttl_seconds: int = 3600,
    ) -> ScheduledExperiment:
        if not isinstance(plan, ExperimentPlan):
            raise MassResearchDisabledError("ExperimentPlan required")
        if not plan.ready_snapshot_id.strip():
            raise MassResearchDisabledError("plan.ready_snapshot_id required")
        if readiness is not None and plan.ready_snapshot_id != readiness.snapshot_id:
            raise MassResearchDisabledError(
                "ExperimentPlan.ready_snapshot_id must match VerifiedResearchReadiness"
            )
        cap, att = require_mass_research_start(
            budget=self._budget,
            readiness=readiness,
            operator_override=operator_override,
        )
        lease = cap.acquire_slot(ttl_seconds=lease_ttl_seconds)
        # Charge one generation reservation.
        try:
            cap.consume(generations=1)
        except Exception:
            cap.release(lease)
            raise
        att_id = (
            readiness.attestation_id
            if isinstance(readiness, VerifiedResearchReadiness)
            else f"override:{operator_override.override_id}"  # type: ignore[union-attr]
        )
        return ScheduledExperiment(
            plan=plan,
            lease=lease,
            readiness_attestation_id=att_id,
            budget_id=cap.budget_id,
        )

    def release(self, scheduled: ScheduledExperiment) -> None:
        self._budget.release(scheduled.lease)


__all__ = ["ExperimentScheduler", "ScheduledExperiment"]
