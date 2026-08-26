"""Pilot and Mass scheduler readiness scopes are nominally separated."""
from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research.artifacts import ExperimentPlan
from research.experiment_plans import load_experiment_plans
from research.phase7_pilot import (
    PILOT_MAX_HYPOTHESES,
    AuthorizedEvaluationService,
    ControlledPilotScheduler,
    MassResearchScheduler,
    bind_authorized_evaluation_service,
)
from research.readiness import (
    VerifiedMassReadiness,
    VerifiedPilotReadiness,
    require_mass_research_start,
)
from research.ready_manifest import build_ready_manifest, load_exact_four_pilot_ready_binding
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget
from storage.immutable_artifact import ImmutableArtifactStore
from tests.readiness_test_support import (
    _TestReadinessSigner,
    controlled_pilot_scheduler,
    make_readiness_signer,
    mint_pilot_readiness,
)

_SNAPSHOT_ID = "sha256:" + ("12" * 32)


def _publisher() -> _TestReadinessSigner:
    return make_readiness_signer(
        key_id="phase7-pilot-test",
        private_key=Ed25519PrivateKey.generate(),
    )


def _readiness(
    publisher: _TestReadinessSigner,
    *,
    snapshot_id: str = _SNAPSHOT_ID,
    expires_at: str | None = None,
    signature: str | None = None,
    **field_overrides: object,
) -> VerifiedPilotReadiness:
    digest = "sha256:" + ("ab" * 32)
    binding = load_exact_four_pilot_ready_binding()
    manifest = build_ready_manifest(
        snapshot_id=snapshot_id,
        publication_scope="PILOT",
        profile_id=binding.profile_id,
        profile_version=binding.profile_version,
        profile_digest=binding.profile_digest,
        plan_ids=binding.plan_ids,
        plan_set_digest=binding.plan_set_digest,
        dependency_closure_digest=binding.closure_set_digest,
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        resolved_universe_digest=digest,
        dataset_ids=binding.required_datasets,
        coverage_proof_digest=digest,
        raw_proof_digest=digest,
        receipt_proof_digest=digest,
        validation_proof_digest=digest,
        b0_proof_digest=digest,
        b4_proof_digest=digest,
        source_generation="g1",
        applied_sync_generation="g1",
        export_cursor="g1",
        applied_cursor="g1",
        pit_contract_digests={"pit_api": digest},
        feature_generation=digest,
        catalog_generation=digest,
        created_at="2026-01-01T00:00:00+00:00",
        published_at="2026-01-01T00:01:00+00:00",
    )
    current = datetime.now(timezone.utc)
    expiry = (
        current + timedelta(hours=1)
        if expires_at is None
        else datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    )
    mint_now = current if expiry > current else expiry - timedelta(seconds=60)
    pending = mint_pilot_readiness(
        manifest,
        publisher=publisher,
        immutable_db_digest=digest,
        now=mint_now,
        ttl_seconds=max(60, int((expiry - mint_now).total_seconds())),
    )
    if field_overrides:
        pending = replace(pending, **field_overrides)
    if signature is not None:
        pending = replace(pending, signature=signature)
    return pending


def _budget(tmp_path: Path) -> ResearchBudgetCapability:
    return ResearchBudgetCapability(
        "pilot-b",
        tmp_path / "pilot-b.sqlite",
        ExperimentBudget(),
    )


def _plan() -> ExperimentPlan:
    return load_experiment_plans()[0]


def _eval_service() -> AuthorizedEvaluationService:
    return bind_authorized_evaluation_service()


def _store(tmp_path: Path) -> ImmutableArtifactStore:
    return ImmutableArtifactStore(tmp_path / "artifacts")


def _construct(
    tmp_path: Path,
    publisher: _TestReadinessSigner | None = None,
    **overrides: object,
) -> ControlledPilotScheduler:
    publisher = publisher or _publisher()
    kwargs: dict[str, object] = {
        "readiness": _readiness(publisher),
        "budget": _budget(tmp_path),
        "plan": _plan(),
        "authorized_evaluation_service": _eval_service(),
        "immutable_artifact_store": _store(tmp_path),
    }
    kwargs.update(overrides)
    return controlled_pilot_scheduler(
        verifier=publisher._public_registry(),
        **kwargs,
    )


def test_pilot_scheduler_public_constructor_has_no_caller_trust_root() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        ControlledPilotScheduler(verifier=object())  # type: ignore[call-arg]


def test_pilot_readiness_is_final_and_method_override_cannot_authorize() -> None:
    with pytest.raises(TypeError, match="final"):

        class EvilPilot(VerifiedPilotReadiness):
            def require_valid(self) -> "EvilPilot":
                return self


def test_pilot_readiness_dto_rejects_caller_verifier_and_clock() -> None:
    readiness = _readiness(_publisher())
    with pytest.raises(TypeError, match="unexpected keyword argument 'verifier'"):
        readiness.require_valid(verifier=object())  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        readiness.is_valid(now=datetime.now(timezone.utc))  # type: ignore[call-arg]


class _ExplosiveStr(str):
    def __eq__(self, other: object) -> bool:
        raise AssertionError("stateful scalar comparison was invoked")


class _ExplosiveTuple(tuple):
    def __iter__(self):  # type: ignore[no-untyped-def]
        raise AssertionError("stateful tuple iteration was invoked")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("ready_state", _ExplosiveStr("READY"), "exact non-empty string"),
        ("plan_ids", _ExplosiveTuple(("forged",)), "exact non-empty string tuple"),
    ),
)
def test_scheduler_rejects_stateful_readiness_scalars_before_use(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    publisher = _publisher()
    poisoned = replace(_readiness(publisher), **{field: value})
    with pytest.raises(MassResearchDisabledError, match=message):
        _construct(tmp_path, publisher=publisher, readiness=poisoned)


def test_construct_fails_without_readiness(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="VerifiedPilotReadiness"):
        _construct(tmp_path, readiness=None)
    with pytest.raises(MassResearchDisabledError, match="VerifiedPilotReadiness"):
        _construct(tmp_path, readiness={"snapshot_id": "snap-1"})


def test_construct_fails_without_budget(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="ResearchBudgetCapability"):
        _construct(tmp_path, budget=None)


def test_construct_fails_without_plan(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="ExperimentPlan"):
        _construct(tmp_path, plan=None)


def test_experiment_plan_has_no_prepublication_snapshot_field(
    tmp_path: Path,
) -> None:
    plan = _plan()
    assert not hasattr(plan, "ready_snapshot_id")
    assert "ready_snapshot_id" not in plan.to_dict()
    assert isinstance(_construct(tmp_path, plan=plan), ControlledPilotScheduler)


def test_construct_fails_without_bound_evaluation_service(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="authorized_evaluation_service"):
        _construct(tmp_path, authorized_evaluation_service=None)
    with pytest.raises(MassResearchDisabledError, match="authorized_evaluation_service"):
        _construct(tmp_path, authorized_evaluation_service=SimpleNamespace(bound=True))
    with pytest.raises(MassResearchDisabledError, match="authorized_evaluation_service"):
        _construct(tmp_path, authorized_evaluation_service=SimpleNamespace())
    with pytest.raises(MassResearchDisabledError, match="authorized_evaluation_service"):
        AuthorizedEvaluationService()
    with pytest.raises(MassResearchDisabledError, match="authorized_evaluation_service"):
        _construct(tmp_path, authorized_evaluation_service=AuthorizedEvaluationService())


def test_construct_fails_without_artifact_store_create_if_absent(
    tmp_path: Path,
) -> None:
    with pytest.raises(MassResearchDisabledError, match="immutable_artifact_store"):
        _construct(tmp_path, immutable_artifact_store=None)
    with pytest.raises(MassResearchDisabledError, match="create_if_absent"):
        _construct(tmp_path, immutable_artifact_store=SimpleNamespace())
    with pytest.raises(MassResearchDisabledError, match="create_if_absent"):
        _construct(
            tmp_path,
            immutable_artifact_store=SimpleNamespace(create_if_absent=lambda *_a, **_k: None),
        )


def test_construct_rejects_operator_override(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="operator_override"):
        _construct(tmp_path, operator_override={"reason": "force"})


def test_construct_refuses_expired_or_bad_signature(tmp_path: Path) -> None:
    pub = _publisher()
    expired = _readiness(pub, expires_at="2000-01-01T00:00:00+00:00")
    with pytest.raises(MassResearchDisabledError, match="expired|time-incoherent"):
        _construct(tmp_path, publisher=pub, readiness=expired)
    bad_sig = _readiness(pub, signature="ed25519:not-a-real-signature")
    with pytest.raises(MassResearchDisabledError, match="signature"):
        _construct(tmp_path, publisher=pub, readiness=bad_sig)


def test_construct_refuses_noncanonical_plan_instead_of_mutating_snapshot(
    tmp_path: Path,
) -> None:
    plan = replace(_plan(), hypothesis="caller-substituted hypothesis")
    with pytest.raises(MassResearchDisabledError, match="canonical exact-four"):
        _construct(tmp_path, plan=plan)


def test_construct_refuses_empty_digest(tmp_path: Path) -> None:
    pub = _publisher()
    empty = _readiness(pub, b0_quality_proof_digest="")
    with pytest.raises(MassResearchDisabledError, match="digest"):
        _construct(tmp_path, publisher=pub, readiness=empty)


def test_construct_succeeds_with_all_deps(tmp_path: Path) -> None:
    sched = _construct(tmp_path)
    assert isinstance(sched, ControlledPilotScheduler)
    with pytest.raises(MassResearchDisabledError, match="cannot mint"):
        sched.mint_operator_override(reason="no")


def test_pilot_size_cap_refuses_n_over_32(tmp_path: Path) -> None:
    sched = _construct(tmp_path)
    too_many = [f"h{i}" for i in range(PILOT_MAX_HYPOTHESES + 1)]
    with pytest.raises(MassResearchDisabledError, match="n>32"):
        sched.select_pilot_hypotheses(too_many)
    with pytest.raises(MassResearchDisabledError, match="n>32"):
        _construct(tmp_path, n_hypotheses=33)
    ok = [f"h{i}" for i in range(8)]
    assert sched.select_pilot_hypotheses(ok) == tuple(ok)
    with pytest.raises(MassResearchDisabledError, match="semantically distinct"):
        sched.select_pilot_hypotheses(["a"] * 8)


def test_mass_2000_catalog_eval_is_not_started(tmp_path: Path) -> None:
    sched = _construct(tmp_path)
    with pytest.raises(MassResearchDisabledError, match="2000-catalog"):
        sched.start_mass_catalog_eval()
    with pytest.raises(MassResearchDisabledError, match="2000-catalog"):
        sched.start_mass_catalog_eval(n=2000)


def test_mass_scheduler_rejects_pilot_readiness(tmp_path: Path) -> None:
    pub = _publisher()
    pilot = _readiness(pub)
    with pytest.raises(MassResearchDisabledError, match="VerifiedMassReadiness"):
        MassResearchScheduler(
            readiness=pilot,  # type: ignore[arg-type]
        )


def test_mass_scheduler_and_start_are_hard_disabled_even_for_mass_nominal_type(
    tmp_path: Path,
) -> None:
    pub = _publisher()
    pilot = _readiness(pub)
    mass_like = VerifiedMassReadiness(
        **{
            field.name: (
                "MASS"
                if field.name == "readiness_scope"
                else "mass/governed-v1"
                if field.name == "profile_id"
                else object.__getattribute__(pilot, field.name)
            )
            for field in fields(VerifiedPilotReadiness)
        }
    )
    with pytest.raises(MassResearchDisabledError, match="hard-disabled"):
        MassResearchScheduler(
            readiness=mass_like,
        )
    with pytest.raises(MassResearchDisabledError, match="remains disabled"):
        require_mass_research_start(
            budget=_budget(tmp_path),
            readiness=mass_like,
        )
