"""Scope-separated Phase 7 schedulers; both execution loops remain disabled.

The controlled-pilot boundary accepts only ``VerifiedPilotReadiness`` while
the Mass boundary accepts only ``VerifiedMassReadiness``. Neither class arms
READY, promotion, a next generation, or the legacy 2,000-catalog evaluation.
"""
from __future__ import annotations

from typing import Sequence

from research.artifacts import ExperimentPlan
from research.readiness import (
    ReadinessPublicKeyRegistry,
    VerifiedMassReadiness,
    VerifiedPilotReadiness,
)
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from storage.immutable_artifact import ImmutableArtifactStore

PILOT_MIN_HYPOTHESES: int = 2
PILOT_MAX_HYPOTHESES: int = 32
MASS_CATALOG_EVAL_SIZE: int = 2000

_BIND_TOKEN = object()

_DIGEST_ATTRS = (
    "plan_set_digest",
    "dependency_closure_digest",
    "ready_manifest_digest",
    "immutable_db_digest",
    "coverage_proof_digest",
    "governed_membership_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "validation_proof_digest",
    "b0_quality_proof_digest",
    "b4_quality_proof_digest",
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
    verifier: ReadinessPublicKeyRegistry | None,
) -> VerifiedPilotReadiness:
    if not isinstance(readiness, VerifiedPilotReadiness):
        raise MassResearchDisabledError(
            "VerifiedPilotReadiness required (type check)"
        )
    readiness.require_valid(
        expected_snapshot_id=expected_snapshot_id,
        verifier=verifier,
    )
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


class ControlledPilotScheduler:
    """Exact pilot scheduler. Fail-closed at construct. Execution stays OFF."""

    def __init__(
        self,
        *,
        readiness: VerifiedPilotReadiness | None = None,
        verifier: ReadinessPublicKeyRegistry | None = None,
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
            readiness,
            expected_snapshot_id=str(plan.ready_snapshot_id),
            verifier=verifier,
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


class MassResearchScheduler:
    """Mass-only scheduler boundary; pilot capability is structurally rejected."""

    def __init__(
        self,
        *,
        readiness: VerifiedMassReadiness | None = None,
        verifier: ReadinessPublicKeyRegistry | None = None,
    ) -> None:
        if not isinstance(readiness, VerifiedMassReadiness):
            raise MassResearchDisabledError(
                "VerifiedMassReadiness required; VerifiedPilotReadiness cannot "
                "authorize Mass"
            )
        readiness.require_valid(verifier=verifier)
        self._readiness = readiness

    def start_mass_catalog_eval(self, n: int = MASS_CATALOG_EVAL_SIZE) -> None:
        raise MassResearchDisabledError(
            "mass 2000-catalog eval is not enabled; Mass remains NO-GO"
        )


__all__ = [
    "AuthorizedEvaluationService",
    "ControlledPilotScheduler",
    "MASS_CATALOG_EVAL_SIZE",
    "MassResearchDisabledError",
    "MassResearchScheduler",
    "PILOT_MAX_HYPOTHESES",
    "PILOT_MIN_HYPOTHESES",
    "bind_authorized_evaluation_service",
]
