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
from storage.immutable_artifact import ImmutableArtifactStore

PILOT_MIN_HYPOTHESES: int = 2
PILOT_MAX_HYPOTHESES: int = 32
MASS_CATALOG_EVAL_SIZE: int = 2000

_BIND_TOKEN = object()

_DIGEST_ATTRS = (
    "ready_manifest_digest",
    "immutable_db_digest",
    "coverage_proof_digest",
    "governed_membership_digest",
    "raw_proof_digest",
    "b0_quality_proof_digest",
    "evidence_digest",
)


class AuthorizedEvaluationService:
    """Nominal eval capability. Only bind_authorized_evaluation_service may construct."""

    __slots__ = ()

    def __init__(self, *, _factory_token: object = None) -> None:
        if _factory_token is not _BIND_TOKEN:
            raise MassResearchDisabledError(
                "authorized_evaluation_service must be issued by "
                "bind_authorized_evaluation_service"
            )


def bind_authorized_evaluation_service() -> AuthorizedEvaluationService:
    """Factory for AuthorizedEvaluationService. Does not arm Phase 7 or mass eval."""
    return AuthorizedEvaluationService(_factory_token=_BIND_TOKEN)


def _require_authorized_evaluation_service(
    service: object | None,
) -> AuthorizedEvaluationService:
    if not isinstance(service, AuthorizedEvaluationService):
        raise MassResearchDisabledError(
            "authorized_evaluation_service required "
            "(AuthorizedEvaluationService from bind_authorized_evaluation_service)"
        )
    return service


def _require_artifact_store(store: object | None) -> ImmutableArtifactStore:
    if store is None or not isinstance(store, ImmutableArtifactStore):
        raise MassResearchDisabledError(
            "immutable_artifact_store required "
            "(ImmutableArtifactStore with create_if_absent)"
        )
    if not callable(getattr(store, "create_if_absent", None)):
        raise MassResearchDisabledError(
            "immutable_artifact_store.create_if_absent required"
        )
    return store


def _require_signed_readiness(
    readiness: object | None,
    *,
    expected_snapshot_id: str,
) -> VerifiedResearchReadiness:
    if not isinstance(readiness, VerifiedResearchReadiness):
        raise MassResearchDisabledError(
            "VerifiedResearchReadiness required (type check)"
        )
    readiness.require_valid(expected_snapshot_id=expected_snapshot_id)
    if str(readiness.snapshot_id) != expected_snapshot_id:
        raise MassResearchDisabledError(
            "plan.ready_snapshot_id must match readiness.snapshot_id"
        )
    ready_state = getattr(readiness, "ready_state", None)
    if ready_state is not None and ready_state != "READY":
        raise MassResearchDisabledError("readiness ready_state must be READY")
    for name in _DIGEST_ATTRS:
        if not hasattr(readiness, name):
            continue
        value = str(getattr(readiness, name) or "").strip()
        if not value:
            raise MassResearchDisabledError(
                f"readiness {name} required (non-empty digest)"
            )
    return readiness


class MassResearchScheduler:
    """Pilot-only scheduler. Fail-closed at construct. Phase 7 stays OFF."""

    def __init__(
        self,
        *,
        readiness: VerifiedResearchReadiness | None = None,
        budget: ResearchBudgetCapability | None = None,
        plan: ExperimentPlan | None = None,
        authorized_evaluation_service: AuthorizedEvaluationService | None = None,
        immutable_artifact_store: ImmutableArtifactStore | None = None,
        operator_override: object | None = None,
        n_hypotheses: int | None = None,
    ) -> None:
        if operator_override is not None:
            raise MassResearchDisabledError(
                "operator_override cannot substitute; agent cannot mint "
                "operator_override"
            )
        if not isinstance(budget, ResearchBudgetCapability):
            raise MassResearchDisabledError("ResearchBudgetCapability required")
        if not isinstance(plan, ExperimentPlan):
            raise MassResearchDisabledError("ExperimentPlan required")
        if not str(plan.ready_snapshot_id or "").strip():
            raise MassResearchDisabledError("plan.ready_snapshot_id required")
        self._readiness = _require_signed_readiness(
            readiness, expected_snapshot_id=str(plan.ready_snapshot_id)
        )
        self._budget = budget
        self._plan = plan
        self._evaluation_service = _require_authorized_evaluation_service(
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
    "AuthorizedEvaluationService",
    "MASS_CATALOG_EVAL_SIZE",
    "MassResearchDisabledError",
    "MassResearchScheduler",
    "PILOT_MAX_HYPOTHESES",
    "PILOT_MIN_HYPOTHESES",
    "bind_authorized_evaluation_service",
]
