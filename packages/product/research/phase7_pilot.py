"""Phase 7 pilot scheduler — construct-gated, not enabled.

MassResearchScheduler cannot be constructed without the required
capabilities. It does not arm Phase 7, Mass, READY, or a 2000-catalog eval.
Agent code cannot mint operator_override.
"""
from __future__ import annotations

from typing import Sequence

from research.artifacts import ExperimentPlan
from research.readiness import VerifiedResearchReadiness
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability

PILOT_MIN_HYPOTHESES: int = 8
PILOT_MAX_HYPOTHESES: int = 32
MASS_CATALOG_EVAL_SIZE: int = 2000


def _require_bound_evaluation_service(service: object | None) -> object:
    if service is None:
        raise MassResearchDisabledError("authorized_evaluation_service required")
    bound = getattr(service, "bound", None)
    if bound is not True:
        raise MassResearchDisabledError(
            "authorized_evaluation_service must have bound=True"
        )
    return service


def _require_artifact_store(store: object | None) -> object:
    if store is None:
        raise MassResearchDisabledError("immutable_artifact_store required")
    create = getattr(store, "create_if_absent", None)
    if not callable(create):
        raise MassResearchDisabledError(
            "immutable_artifact_store.create_if_absent required"
        )
    return store


class MassResearchScheduler:
    """Pilot-only scheduler. Fail-closed at construct. Phase 7 stays OFF."""

    def __init__(
        self,
        *,
        readiness: VerifiedResearchReadiness | None = None,
        budget: ResearchBudgetCapability | None = None,
        plan: ExperimentPlan | None = None,
        authorized_evaluation_service: object | None = None,
        immutable_artifact_store: object | None = None,
        operator_override: object | None = None,
        n_hypotheses: int | None = None,
    ) -> None:
        if operator_override is not None:
            raise MassResearchDisabledError(
                "operator_override cannot substitute; agent cannot mint "
                "operator_override"
            )
        if not isinstance(readiness, VerifiedResearchReadiness):
            raise MassResearchDisabledError(
                "VerifiedResearchReadiness required (type check)"
            )
        if not isinstance(budget, ResearchBudgetCapability):
            raise MassResearchDisabledError("ResearchBudgetCapability required")
        if not isinstance(plan, ExperimentPlan):
            raise MassResearchDisabledError("ExperimentPlan required")
        if not str(plan.ready_snapshot_id or "").strip():
            raise MassResearchDisabledError("plan.ready_snapshot_id required")
        self._readiness = readiness
        self._budget = budget
        self._plan = plan
        self._evaluation_service = _require_bound_evaluation_service(
            authorized_evaluation_service
        )
        self._artifact_store = _require_artifact_store(immutable_artifact_store)
        if n_hypotheses is not None:
            self._require_pilot_n(int(n_hypotheses))

    @staticmethod
    def _require_pilot_n(n: int) -> int:
        if n > PILOT_MAX_HYPOTHESES:
            raise MassResearchDisabledError(
                f"pilot size refuses n>{PILOT_MAX_HYPOTHESES} (got {n})"
            )
        if n < PILOT_MIN_HYPOTHESES:
            raise MassResearchDisabledError(
                f"pilot size requires n>={PILOT_MIN_HYPOTHESES} (got {n})"
            )
        return n

    def mint_operator_override(self, *args: object, **kwargs: object) -> None:
        raise MassResearchDisabledError("agent cannot mint operator_override")

    def select_pilot_hypotheses(self, hypotheses: Sequence[str]) -> tuple[str, ...]:
        ids = tuple(str(h).strip() for h in hypotheses if str(h).strip())
        if len(set(ids)) != len(ids):
            raise MassResearchDisabledError(
                "pilot hypotheses must be semantically distinct"
            )
        self._require_pilot_n(len(ids))
        return ids

    def start_mass_catalog_eval(self, n: int = MASS_CATALOG_EVAL_SIZE) -> None:
        raise MassResearchDisabledError(
            "mass 2000-catalog eval is not started; Phase 7 pilot stays closed"
        )


__all__ = [
    "MASS_CATALOG_EVAL_SIZE",
    "MassResearchDisabledError",
    "MassResearchScheduler",
    "PILOT_MAX_HYPOTHESES",
    "PILOT_MIN_HYPOTHESES",
]
