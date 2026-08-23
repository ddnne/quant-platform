"""MassResearchScheduler construct is fail-closed without each required dep."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.artifacts import ExperimentPlan
from research.phase7_pilot import (
    PILOT_MAX_HYPOTHESES,
    AuthorizedEvaluationService,
    MassResearchScheduler,
    bind_authorized_evaluation_service,
)
from research.readiness import (
    VerifiedResearchReadiness,
    _attestation_secret,
    _sign_attestation,
)
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget
from storage.immutable_artifact import ImmutableArtifactStore

_TEST_HMAC_SECRET = b"phase7-pilot-construct-test-hmac"


@pytest.fixture(autouse=True)
def _hmac_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANT_READINESS_HMAC_SECRET", _TEST_HMAC_SECRET.decode())


def _readiness(
    *,
    snapshot_id: str = "snap-1",
    expires_at: str = "2099-01-01T00:00:00+00:00",
    signature: str | None = None,
    **field_overrides: object,
) -> VerifiedResearchReadiness:
    digest = "sha256:" + ("ab" * 32)
    kwargs: dict[str, object] = {
        "attestation_id": "att-1",
        "snapshot_id": snapshot_id,
        "ready_state": "READY",
        "ready_manifest_digest": digest,
        "immutable_db_digest": digest,
        "coverage_policy_version": "v1",
        "coverage_proof_digest": digest,
        "governed_membership_digest": digest,
        "raw_proof_digest": digest,
        "b0_quality_proof_digest": digest,
        "source_generation": "g1",
        "applied_sync_generation": "g1",
        "verified_at": "2026-01-01T00:00:00+00:00",
        "expires_at": expires_at,
        "evidence_digest": digest,
        "signature": "hmac-sha256:pending",
    }
    kwargs.update(field_overrides)
    pending = VerifiedResearchReadiness(**kwargs)  # type: ignore[arg-type]
    if signature is None:
        signature = _sign_attestation(pending.to_canonical_body(), _attestation_secret())
    return replace(pending, signature=signature)


def _budget(tmp_path: Path) -> ResearchBudgetCapability:
    return ResearchBudgetCapability(
        "pilot-b",
        tmp_path / "pilot-b.sqlite",
        ExperimentBudget(),
    )


def _plan(*, snapshot_id: str = "snap-1") -> ExperimentPlan:
    return ExperimentPlan.from_dict(
        {
            "plan_id": "p1",
            "idea_id": "i1",
            "strategy_spec_id": "st1",
            "feature_refs": [{"id": "f", "version": "v1"}],
            "ready_snapshot_id": snapshot_id,
            "universe": ["1301"],
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "cost_scenario": "default",
            "evaluation_protocol": "signal-default",
            "budget_allocation": {"generations": 1},
        }
    )


def _eval_service() -> AuthorizedEvaluationService:
    return bind_authorized_evaluation_service()


def _store(tmp_path: Path) -> ImmutableArtifactStore:
    return ImmutableArtifactStore(tmp_path / "artifacts")


def _construct(tmp_path: Path, **overrides: object) -> MassResearchScheduler:
    kwargs: dict[str, object] = {
        "readiness": _readiness(),
        "budget": _budget(tmp_path),
        "plan": _plan(),
        "authorized_evaluation_service": _eval_service(),
        "immutable_artifact_store": _store(tmp_path),
    }
    kwargs.update(overrides)
    return MassResearchScheduler(**kwargs)  # type: ignore[arg-type]


def test_construct_fails_without_readiness(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="VerifiedResearchReadiness"):
        _construct(tmp_path, readiness=None)
    with pytest.raises(MassResearchDisabledError, match="VerifiedResearchReadiness"):
        _construct(tmp_path, readiness={"snapshot_id": "snap-1"})


def test_construct_fails_without_budget(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="ResearchBudgetCapability"):
        _construct(tmp_path, budget=None)


def test_construct_fails_without_plan(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="ExperimentPlan"):
        _construct(tmp_path, plan=None)


def test_construct_fails_without_ready_snapshot_id(tmp_path: Path) -> None:
    plan = replace(_plan(), ready_snapshot_id="")
    with pytest.raises(MassResearchDisabledError, match="ready_snapshot_id"):
        _construct(tmp_path, plan=plan)


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
    expired = _readiness(expires_at="2000-01-01T00:00:00+00:00")
    with pytest.raises(MassResearchDisabledError, match="invalid, expired"):
        _construct(tmp_path, readiness=expired)
    bad_sig = _readiness(signature="hmac-sha256:not-a-real-mac")
    with pytest.raises(MassResearchDisabledError, match="invalid, expired"):
        _construct(tmp_path, readiness=bad_sig)


def test_construct_refuses_snapshot_mismatch(tmp_path: Path) -> None:
    with pytest.raises(MassResearchDisabledError, match="invalid, expired"):
        _construct(tmp_path, plan=_plan(snapshot_id="other-snap"))


def test_construct_refuses_empty_digest(tmp_path: Path) -> None:
    empty = _readiness(b0_quality_proof_digest="")
    with pytest.raises(MassResearchDisabledError, match="non-empty digest"):
        _construct(tmp_path, readiness=empty)


def test_construct_succeeds_with_all_deps(tmp_path: Path) -> None:
    sched = _construct(tmp_path)
    assert isinstance(sched, MassResearchScheduler)
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
