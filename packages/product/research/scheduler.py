"""Experiment scheduler — readiness signature re-checked at schedule time.

W77 / w0816k: hypothesis-class mix helpers ensure schedule/generation selection
is **not** mass-defaulted to ``simple_daily_sign`` (opt-in only).
Mass experiment start remains fail-closed without VerifiedResearchReadiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from research.artifacts import ExperimentPlan
from research.hypothesis_classes import (
    CLASS_SIMPLE_DAILY_SIGN,
    DEFAULT_GENERATION_CLASS_IDS,
    assert_generation_mix_not_skewed,
    default_generation_class_ids,
    is_generation_enabled,
    is_simple_daily_sign,
    select_generation_classes,
)
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


@dataclass(frozen=True)
class HypothesisClassScheduleSelection:
    """Class mix chosen for idea / experiment planning (Mass still OFF until READY)."""

    class_ids: tuple[str, ...]
    simple_daily_sign_included: bool
    simple_daily_sign_default_off: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_ids": list(self.class_ids),
            "simple_daily_sign_included": self.simple_daily_sign_included,
            "simple_daily_sign_default_off": self.simple_daily_sign_default_off,
            "default_generation_class_ids": list(DEFAULT_GENERATION_CLASS_IDS),
        }


def select_schedule_hypothesis_classes(
    *,
    n: int | None = None,
    class_ids: Sequence[str] | None = None,
    explicit_opt_in: Sequence[str] | None = None,
    include_simple_daily_sign: bool = False,
) -> HypothesisClassScheduleSelection:
    """Select hypothesis classes for scheduling / generation planning.

    ``simple_daily_sign`` is **not** included unless
    ``include_simple_daily_sign=True`` or listed in ``explicit_opt_in``.
    Mix is fail-closed against simple_daily_sign-only / majority skew.
    """
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


def require_plan_hypothesis_class_allowed(
    plan: ExperimentPlan | Mapping[str, Any],
    *,
    explicit_opt_in: Sequence[str] | None = None,
) -> str | None:
    """If plan lineage declares hypothesis_class, enforce generation policy.

    Returns the class_id when present and allowed; None when no class pinned.
    Raises ValueError when class is known but not generation-enabled.
    """
    if isinstance(plan, ExperimentPlan):
        # ExperimentPlan has no lineage field; callers may pass idea lineage
        # via budget_allocation markers or wrap with Mapping.
        return None
    lineage = plan.get("lineage") if isinstance(plan, Mapping) else None
    if not isinstance(lineage, Mapping):
        return None
    class_id = lineage.get("hypothesis_class")
    if class_id is None or not str(class_id).strip():
        return None
    cid = str(class_id).strip()
    if not is_generation_enabled(cid, explicit_opt_in=explicit_opt_in):
        raise ValueError(
            f"plan hypothesis_class {cid!r} not allowed without explicit "
            f"opt-in (simple_daily_sign default generation OFF)"
        )
    if is_simple_daily_sign(cid):
        # Allowed only via opt-in path above; surface for callers.
        pass
    return cid


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
        readiness: VerifiedResearchReadiness | None = None,
        lease_ttl_seconds: int = 3600,
        hypothesis_class: str | None = None,
        explicit_opt_in: Sequence[str] | None = None,
    ) -> ScheduledExperiment:
        if not isinstance(plan, ExperimentPlan):
            raise MassResearchDisabledError("ExperimentPlan required")
        if not plan.ready_snapshot_id.strip():
            raise MassResearchDisabledError("plan.ready_snapshot_id required")
        # W77: if caller pins a hypothesis class, enforce generation policy
        # before any mass-gated lease (still fails closed without readiness).
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


__all__ = [
    "ExperimentScheduler",
    "HypothesisClassScheduleSelection",
    "ScheduledExperiment",
    "require_plan_hypothesis_class_allowed",
    "select_schedule_hypothesis_classes",
]
