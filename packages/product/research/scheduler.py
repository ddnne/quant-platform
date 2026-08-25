"""Experiment scheduler. Mix is not mass-defaulted to simple_daily_sign."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from research.artifacts import ExperimentPlan
from research.hypothesis_classes import (
    CLASS_SIMPLE_DAILY_SIGN,
    assert_generation_mix_not_skewed,
    default_generation_class_ids,
    is_generation_enabled,
    select_generation_classes,
)
from research.readiness import (
    MassResearchDisabledError,
    ReadinessPublicKeyRegistry,
    VerifiedMassReadiness,
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


@dataclass(frozen=True)
class HypothesisClassScheduleSelection:
    """Class mix chosen for idea / experiment planning (Mass still OFF until READY)."""

    class_ids: tuple[str, ...]
    simple_daily_sign_included: bool
    simple_daily_sign_default_off: bool = True


def select_schedule_hypothesis_classes(
    *,
    n: int | None = None,
    class_ids: Sequence[str] | None = None,
    explicit_opt_in: Sequence[str] | None = None,
    include_simple_daily_sign: bool = False,
) -> HypothesisClassScheduleSelection:
    """Select classes for scheduling. simple_daily_sign is opt-in only."""
    selected = select_generation_classes(
        n=n,
        class_ids=class_ids,
        explicit_opt_in=explicit_opt_in,
        include_simple_daily_sign=include_simple_daily_sign,
    )
    assert_generation_mix_not_skewed(selected)
    return HypothesisClassScheduleSelection(
        class_ids=selected,
        simple_daily_sign_included=CLASS_SIMPLE_DAILY_SIGN in selected,
        simple_daily_sign_default_off=True,
    )


class ExperimentScheduler:
    def __init__(self, *, budget: ResearchBudgetCapability) -> None:
        self._budget = budget

    def default_hypothesis_class_mix(self) -> HypothesisClassScheduleSelection:
        """Default schedule class mix — excludes simple_daily_sign."""
        return select_schedule_hypothesis_classes()

    def schedule(
        self,
        *,
        plan: ExperimentPlan,
        readiness: VerifiedMassReadiness | None = None,
        verifier: ReadinessPublicKeyRegistry | None = None,
        hypothesis_class: str | None = None,
        explicit_opt_in: Sequence[str] | None = None,
    ) -> ScheduledExperiment:
        if not isinstance(plan, ExperimentPlan):
            raise MassResearchDisabledError("ExperimentPlan required")
        if not plan.ready_snapshot_id.strip():
            raise MassResearchDisabledError("plan.ready_snapshot_id required")
        if hypothesis_class is not None and str(hypothesis_class).strip():
            cid = str(hypothesis_class).strip()
            if not is_generation_enabled(cid, explicit_opt_in=explicit_opt_in):
                raise MassResearchDisabledError(
                    f"hypothesis_class {cid!r} not generation-enabled "
                    f"(simple_daily_sign requires explicit opt-in; "
                    f"default mix={list(default_generation_class_ids())})"
                )
        cap, att = require_mass_research_start(
            budget=self._budget,
            readiness=readiness,
            expected_snapshot_id=plan.ready_snapshot_id,
            verifier=verifier,
        )
        att.require_valid(
            expected_snapshot_id=plan.ready_snapshot_id,
            verifier=verifier,
        )
        # The capability owns the canonical policy-bound TTL (currently 1800s).
        # A scheduler caller cannot extend the lease ad hoc.
        lease = cap.acquire_slot()
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


__all__ = [
    "ExperimentScheduler",
    "HypothesisClassScheduleSelection",
    "ScheduledExperiment",
    "select_schedule_hypothesis_classes",
]
