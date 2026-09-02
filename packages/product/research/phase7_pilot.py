"""Scope-separated Phase 7 schedulers; both execution loops remain disabled.

The controlled-pilot boundary accepts only ``VerifiedPilotReadiness`` while
the Mass boundary accepts only ``VerifiedMassReadiness``. Neither class arms
READY, promotion, a next generation, or the legacy 2,000-catalog evaluation.
"""
from __future__ import annotations

from typing import Sequence, final

from research.artifacts import ExperimentPlan
from research.readiness import (
    VerifiedMassReadiness,
    VerifiedPilotReadiness,
    verify_pinned_pilot_readiness,
)
from selection.budget_ledger import MassResearchDisabledError
from selection.controlled_pilot_policy import (
    ControlledPilotPolicyPin,
    load_controlled_pilot_policy,
)

PILOT_MIN_HYPOTHESES: int = 2
PILOT_MAX_HYPOTHESES: int = 32
MASS_CATALOG_EVAL_SIZE: int = 2000

_BIND_TOKEN = object()

_DIGEST_ATTRS = (
    "plan_set_digest",
    "dependency_closure_digest",
    "ready_manifest_digest",
    "immutable_db_digest",
    "coverage_policy_digest",
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



def _require_signed_readiness(
    readiness: object | None,
    *,
    binding: object,
    expected_environment: str,
) -> VerifiedPilotReadiness:
    readiness = verify_pinned_pilot_readiness(
        readiness, expected_environment=expected_environment
    )
    if (
        tuple(readiness.plan_ids) != tuple(getattr(binding, "plan_ids", ()))
        or readiness.profile_digest != getattr(binding, "profile_digest", None)
        or tuple(readiness.dataset_ids)
        != tuple(getattr(binding, "required_datasets", ()))
    ):
        raise MassResearchDisabledError(
            "VerifiedPilotReadiness does not match the canonical exact-four binding"
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


def _require_pilot_hypothesis_count(n: int) -> int:
    if n > PILOT_MAX_HYPOTHESES:
        raise MassResearchDisabledError(
            f"pilot size refuses n>{PILOT_MAX_HYPOTHESES} (got {n})"
        )
    if n < PILOT_MIN_HYPOTHESES:
        raise MassResearchDisabledError(
            f"pilot size requires n>={PILOT_MIN_HYPOTHESES} (got {n})"
        )
    return n


def _require_canonical_controlled_policy() -> ControlledPilotPolicyPin:
    policy = load_controlled_pilot_policy()
    if (
        policy.max_parallel_experiments != 2
        or policy.max_generations != 1
        or policy.automatic_promotion is not False
        or policy.plans_exactly != 4
    ):
        raise MassResearchDisabledError(
            "controlled pilot rejects caller budget overrides; canonical "
            "ControlledPilotPolicyPin is required"
        )
    return policy


def _validated_controlled_pilot_scheduler_state(
    *,
    expected_environment: str,
    readiness: VerifiedPilotReadiness | None,
    budget: object | None,
    plan: ExperimentPlan | None,
    authorized_evaluation_service: AuthorizedEvaluationService | None,
    immutable_artifact_store: object | None,
    operator_override: object | None,
) -> tuple[
    ControlledPilotPolicyPin,
    ExperimentPlan,
    VerifiedPilotReadiness,
    AuthorizedEvaluationService,
]:
    """Validate every authority input before scheduler state is assigned."""

    if operator_override is not None:
        raise MassResearchDisabledError(
            "operator_override cannot substitute; agent cannot mint "
            "operator_override"
        )
    if budget is not None:
        raise MassResearchDisabledError(
            "controlled scheduler has no local budget; Worker BudgetLedger only"
        )
    if immutable_artifact_store is not None:
        raise MassResearchDisabledError(
            "controlled scheduler has no local artifact store"
        )
    controlled_policy = _require_canonical_controlled_policy()
    if type(plan) is not ExperimentPlan:
        raise MassResearchDisabledError("ExperimentPlan required")
    from research.ready_manifest import load_exact_four_pilot_ready_binding

    binding = load_exact_four_pilot_ready_binding()
    canonical_plan = next(
        (item for item in binding.plans if item.plan_id == plan.plan_id), None
    )
    if canonical_plan is None or canonical_plan.to_dict() != plan.to_dict():
        raise MassResearchDisabledError(
            "ControlledPilotScheduler requires a canonical exact-four ExperimentPlan"
        )
    verified_readiness = _require_signed_readiness(
        readiness,
        binding=binding,
        expected_environment=expected_environment,
    )
    evaluation_service = _require_authorized_evaluation_service(
        authorized_evaluation_service
    )
    return (
        controlled_policy,
        canonical_plan,
        verified_readiness,
        evaluation_service,
    )


@final
class ControlledPilotScheduler:
    """Exact pilot scheduler. Fail-closed at construct. Execution stays OFF."""

    __slots__ = (
        "_controlled_policy",
        "_evaluation_service",
        "_plan",
        "_readiness",
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ControlledPilotScheduler is a final authority boundary")

    def __init__(
        self,
        *,
        expected_environment: str | None = None,
        readiness: VerifiedPilotReadiness | None = None,
        budget: object | None = None,
        plan: ExperimentPlan | None = None,
        authorized_evaluation_service: AuthorizedEvaluationService | None = None,
        immutable_artifact_store: object | None = None,
        operator_override: object | None = None,
        n_hypotheses: int | None = None,
    ) -> None:
        if type(self) is not ControlledPilotScheduler:
            raise MassResearchDisabledError(
                "controlled pilot scheduler requires exact ControlledPilotScheduler"
            )
        if n_hypotheses is not None:
            if type(n_hypotheses) is not int:
                raise MassResearchDisabledError(
                    "controlled pilot n_hypotheses requires an exact int"
                )
            _require_pilot_hypothesis_count(n_hypotheses)
        if expected_environment not in {"staging", "production"}:
            raise MassResearchDisabledError(
                "controlled pilot requires explicit staging or production environment"
            )
        (
            controlled_policy,
            canonical_plan,
            verified_readiness,
            evaluation_service,
        ) = _validated_controlled_pilot_scheduler_state(
            expected_environment=expected_environment,
            readiness=readiness,
            budget=budget,
            plan=plan,
            authorized_evaluation_service=authorized_evaluation_service,
            immutable_artifact_store=immutable_artifact_store,
            operator_override=operator_override,
        )
        self._controlled_policy = controlled_policy
        self._plan = canonical_plan
        self._readiness = verified_readiness
        self._evaluation_service = evaluation_service

    def mint_operator_override(self, *args: object, **kwargs: object) -> None:
        raise MassResearchDisabledError("agent cannot mint operator_override")

    def select_pilot_hypotheses(self, hypotheses: Sequence[str]) -> tuple[str, ...]:
        ids = tuple(str(h).strip() for h in hypotheses if str(h).strip())
        if len(set(ids)) != len(ids):
            raise MassResearchDisabledError(
                "pilot hypotheses must be semantically distinct"
            )
        _require_pilot_hypothesis_count(len(ids))
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
    ) -> None:
        if not isinstance(readiness, VerifiedMassReadiness):
            raise MassResearchDisabledError(
                "VerifiedMassReadiness required; VerifiedPilotReadiness cannot "
                "authorize Mass"
            )
        raise MassResearchDisabledError(
            "Mass scheduler is hard-disabled in Phase 6.3.1"
        )

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
