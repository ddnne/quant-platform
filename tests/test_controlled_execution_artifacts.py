"""Adversarial tests for the verify-only controlled artifact contract."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import execution
import execution.controlled_artifacts as artifact_module
import execution.trader_authority as trader_module
from execution.controlled_artifacts import (
    CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED,
    CONTROLLED_ARTIFACT_SCHEMA_VERSIONS,
    CONTROLLED_ARTIFACT_TYPES,
    ControlledArtifactAuthorityPending,
    ControlledArtifactPublicKeyRegistry,
    ControlledArtifactVerificationError,
    VerifiedControlledExecutionArtifacts,
    load_verified_controlled_execution_artifacts,
    verify_controlled_artifact_content,
)
from execution.trader_authority import (
    TraderAuthorizationPublicKeyRegistry,
    VerifiedTraderAuthorization,
)


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def _signature(private: Ed25519PrivateKey, body: dict) -> str:
    return "ed25519:" + base64.b64encode(private.sign(_canonical(body))).decode(
        "ascii"
    )


def _content_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorization(
    private: Ed25519PrivateKey,
    *,
    key_id: str,
    issued: datetime,
    ttl_seconds: int = 1800,
) -> VerifiedTraderAuthorization:
    digest = "sha256:" + "ab" * 32
    body = {
        "format": "verified-trader-authorization/v1",
        "mode": "paper",
        "strategy_id": "strategy-v1",
        "strategy_spec_hash": digest,
        "max_gross_weight": 0.5,
        "ready_snapshot_id": digest,
        "ready_manifest_digest": digest,
        "readiness_attestation_id": "attestation-v1",
        "profile_digest": digest,
        "plan_set_digest": digest,
        "dependency_closure_digest": digest,
        "universe_contract_id": "tse_prime_with_fins",
        "universe_rule_digest": digest,
        "resolved_universe_digest": digest,
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "cost_scenario": "BASE",
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(seconds=ttl_seconds)).isoformat(),
        "key_id": key_id,
        "issuer": "ControlledTraderAuthorizationService/v1",
    }
    body["authorization_id"] = _digest(body)
    signature = _signature(private, body)
    return VerifiedTraderAuthorization(
        signature=signature,
        **{key: value for key, value in body.items() if key != "format"},
    )


def _bundle(
    authorization: VerifiedTraderAuthorization,
    writer_private: Ed25519PrivateKey,
    *,
    writer_key_id: str,
    written_at: datetime,
    bundle_overrides: dict | None = None,
    mutate_artifact=None,
) -> bytes:
    document = {
        "format": "controlled-execution-artifact-bundle/v1",
        "authorization_id": authorization.authorization_id,
        "strategy_id": authorization.strategy_id,
        "strategy_spec_hash": authorization.strategy_spec_hash,
        "max_gross_weight": authorization.max_gross_weight,
        "ready_snapshot_id": authorization.ready_snapshot_id,
        "ready_manifest_digest": authorization.ready_manifest_digest,
        "readiness_attestation_id": authorization.readiness_attestation_id,
        "profile_digest": authorization.profile_digest,
        "plan_set_digest": authorization.plan_set_digest,
        "dependency_closure_digest": authorization.dependency_closure_digest,
        "universe_contract_id": authorization.universe_contract_id,
        "universe_rule_digest": authorization.universe_rule_digest,
        "resolved_universe_digest": authorization.resolved_universe_digest,
        "period_start": authorization.period_start,
        "period_end": authorization.period_end,
        "cost_scenario": authorization.cost_scenario,
        "generation_count": 1,
        "automatic_promotion": False,
        "written_at": written_at.isoformat(),
        "writer_key_id": writer_key_id,
        "issuer": "ControlledPilotArtifactWriter/v1",
    }
    document.update(bundle_overrides or {})
    artifacts: list[dict] = []
    for index, artifact_type in enumerate(CONTROLLED_ARTIFACT_TYPES):
        if index == 0:
            parents = [document["authorization_id"]]
        elif index == 1:
            parents = [artifacts[0]["artifact_id"]]
        elif index == 2:
            parents = [
                artifacts[0]["artifact_id"],
                artifacts[1]["artifact_id"],
            ]
        else:
            parents = [item["artifact_id"] for item in artifacts]
        if artifact_type == "Paper":
            stage_payload = {
                "content_digest": _content_digest("paper-content"),
                "experiment_id": "experiment-1",
                "run_id": "run-1",
                "lifecycle": "Paper",
            }
        elif artifact_type == "Risk":
            stage_payload = {
                "content_digest": _content_digest("risk-content"),
                "audit_id": "audit-1",
                "paper_artifact_id": artifacts[0]["artifact_id"],
                "status": "PASS",
            }
        elif artifact_type == "Selection":
            stage_payload = {
                "content_digest": _content_digest("selection-content"),
                "decision_id": "decision-1",
                "paper_artifact_id": artifacts[0]["artifact_id"],
                "risk_artifact_id": artifacts[1]["artifact_id"],
                "decision": "HOLD",
                "automatic_promotion": False,
            }
        else:
            stage_payload = {
                "content_digest": _content_digest("knowledge-content"),
                "knowledge_id": "knowledge-1",
                "selection_artifact_id": artifacts[2]["artifact_id"],
            }
        artifact = {
            "format": "controlled-execution-artifact/v1",
            "artifact_type": artifact_type,
            "schema_version": CONTROLLED_ARTIFACT_SCHEMA_VERSIONS[artifact_type],
            "producer": "ControlledPilotArtifactWriter/v1",
            "authorization_id": document["authorization_id"],
            "strategy_id": document["strategy_id"],
            "strategy_spec_hash": document["strategy_spec_hash"],
            "max_gross_weight": document["max_gross_weight"],
            "ready_snapshot_id": document["ready_snapshot_id"],
            "ready_manifest_digest": document["ready_manifest_digest"],
            "readiness_attestation_id": document["readiness_attestation_id"],
            "profile_digest": document["profile_digest"],
            "plan_set_digest": document["plan_set_digest"],
            "dependency_closure_digest": document["dependency_closure_digest"],
            "universe_contract_id": document["universe_contract_id"],
            "universe_rule_digest": document["universe_rule_digest"],
            "resolved_universe_digest": document["resolved_universe_digest"],
            "period_start": document["period_start"],
            "period_end": document["period_end"],
            "cost_scenario": document["cost_scenario"],
            "parent_artifact_ids": parents,
            "payload": stage_payload,
        }
        if mutate_artifact is not None:
            mutate_artifact(artifact_type, artifact)
        artifact["artifact_id"] = _digest(artifact)
        artifacts.append(artifact)
    document["artifacts"] = artifacts
    document["bundle_id"] = _digest(document)
    document["signature"] = _signature(writer_private, document)
    return _canonical(document)


def _install_test_roots(
    monkeypatch: pytest.MonkeyPatch,
    *,
    trader_private: Ed25519PrivateKey,
    trader_key_id: str,
    writer_private: Ed25519PrivateKey,
    writer_key_id: str,
    clock: datetime,
) -> None:
    monkeypatch.setattr(
        TraderAuthorizationPublicKeyRegistry,
        "load_pinned",
        classmethod(
            lambda cls: TraderAuthorizationPublicKeyRegistry(
                {trader_key_id: trader_private.public_key()}
            )
        ),
    )
    monkeypatch.setattr(
        ControlledArtifactPublicKeyRegistry,
        "load_pinned",
        classmethod(
            lambda cls: ControlledArtifactPublicKeyRegistry(
                {writer_key_id: writer_private.public_key()}
            )
        ),
    )
    monkeypatch.setattr(trader_module, "_now", lambda: clock)


def test_committed_artifact_registry_is_explicitly_unprovisioned() -> None:
    registry = ControlledArtifactPublicKeyRegistry.load_pinned()
    assert registry.active_key_count == 0


def test_unprovisioned_writer_reports_unknown_pending() -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )
    payload = _bundle(
        authorization,
        writer_private,
        writer_key_id="writer-test",
        written_at=issued,
    )

    with pytest.raises(ControlledArtifactAuthorityPending) as raised:
        load_verified_controlled_execution_artifacts(
            payload, authorization=authorization
        )
    assert raised.value.status == "UNKNOWN"
    assert raised.value.reason_code == CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED


def test_exact_four_stage_bundle_verifies_and_is_deep_frozen(monkeypatch) -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )
    payload = _bundle(
        authorization,
        writer_private,
        writer_key_id="writer-test",
        written_at=issued,
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )

    verified = load_verified_controlled_execution_artifacts(
        payload, authorization=authorization
    )
    assert [item["artifact_type"] for item in verified.artifacts] == list(
        CONTROLLED_ARTIFACT_TYPES
    )
    assert verified.authorization_id == authorization.authorization_id
    assert verified.artifact("Risk")["parent_artifact_ids"] == (
        verified.artifact("Paper")["artifact_id"],
    )
    with pytest.raises(TypeError):
        verified.artifact("Paper")["payload"]["lifecycle"] = "Draft"
    paper_digest = verified.artifact("Paper")["payload"]["content_digest"]
    assert verify_controlled_artifact_content(
        b"paper-content", expected_digest=paper_digest
    )
    assert not verify_controlled_artifact_content(
        b"tampered", expected_digest=paper_digest
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("ready_snapshot_id", "sha256:" + "cd" * 32),
        ("plan_set_digest", "sha256:" + "cd" * 32),
        ("dependency_closure_digest", "sha256:" + "cd" * 32),
        ("resolved_universe_digest", "sha256:" + "cd" * 32),
        ("max_gross_weight", 0.25),
    ),
)
def test_writer_signature_cannot_replace_trader_bound_values(
    monkeypatch, field, replacement
) -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )
    payload = _bundle(
        authorization,
        writer_private,
        writer_key_id="writer-test",
        written_at=issued,
        bundle_overrides={field: replacement},
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )

    with pytest.raises(
        ControlledArtifactVerificationError, match="exact Trader authorization"
    ):
        load_verified_controlled_execution_artifacts(
            payload, authorization=authorization
        )


def test_valid_writer_signature_cannot_break_stage_lineage(monkeypatch) -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )

    def replace_risk_parent(artifact_type: str, artifact: dict) -> None:
        if artifact_type == "Risk":
            artifact["parent_artifact_ids"] = [authorization.authorization_id]

    payload = _bundle(
        authorization,
        writer_private,
        writer_key_id="writer-test",
        written_at=issued,
        mutate_artifact=replace_risk_parent,
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )

    with pytest.raises(ControlledArtifactVerificationError, match="parent lineage"):
        load_verified_controlled_execution_artifacts(
            payload, authorization=authorization
        )


def test_valid_writer_signature_cannot_smuggle_stage_authority(monkeypatch) -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )

    def add_promotion_seam(artifact_type: str, artifact: dict) -> None:
        if artifact_type == "Selection":
            artifact["payload"]["mass_enabled"] = True

    payload = _bundle(
        authorization,
        writer_private,
        writer_key_id="writer-test",
        written_at=issued,
        mutate_artifact=add_promotion_seam,
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )

    with pytest.raises(ControlledArtifactVerificationError, match="not closed"):
        load_verified_controlled_execution_artifacts(
            payload, authorization=authorization
        )


def test_trader_key_never_falls_back_as_artifact_writer(monkeypatch) -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    real_writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )
    # Attacker has a valid Trader authorization key but not the independently
    # provisioned artifact-writer key.
    payload = _bundle(
        authorization,
        trader_private,
        writer_key_id="writer-test",
        written_at=issued,
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=real_writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )

    with pytest.raises(ControlledArtifactVerificationError, match="writer signature"):
        load_verified_controlled_execution_artifacts(
            payload, authorization=authorization
        )


def test_automatic_promotion_and_generation_two_are_rejected(monkeypatch) -> None:
    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )
    for overrides in (
        {"automatic_promotion": True},
        {"generation_count": 2},
    ):
        payload = _bundle(
            authorization,
            writer_private,
            writer_key_id="writer-test",
            written_at=issued,
            bundle_overrides=overrides,
        )
        with pytest.raises(
            ControlledArtifactVerificationError, match="policy identity"
        ):
            load_verified_controlled_execution_artifacts(
                payload, authorization=authorization
            )


def test_consumer_reverifies_expiry_and_has_no_clock_or_verifier_injection(
    monkeypatch,
) -> None:
    clock = datetime.now(timezone.utc)
    issued = clock - timedelta(hours=2)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private,
        key_id="trader-test",
        issued=issued,
        ttl_seconds=1800,
    )
    payload = _bundle(
        authorization,
        writer_private,
        writer_key_id="writer-test",
        written_at=clock,
    )
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=clock,
    )

    with pytest.raises(
        ControlledArtifactVerificationError, match="exact Trader authorization"
    ):
        load_verified_controlled_execution_artifacts(
            payload, authorization=authorization
        )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        load_verified_controlled_execution_artifacts(  # type: ignore[call-arg]
            payload,
            authorization=authorization,
            now=issued,
        )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        load_verified_controlled_execution_artifacts(  # type: ignore[call-arg]
            payload,
            authorization=authorization,
            verifier=object(),
        )


def test_product_exposes_no_writer_store_path_or_private_key_api() -> None:
    forbidden = (
        "ControlledArtifactWriter",
        "open_controlled_artifact_writer",
        "DEFAULT_CONTROLLED_ARTIFACT_PRIVATE_KEY_PATH",
        "Ed25519PrivateKey",
        "artifact_store",
        "output_path",
        "socket_path",
    )
    for name in forbidden:
        assert not hasattr(artifact_module, name)
        assert not hasattr(execution, name)
        assert name not in artifact_module.__all__
    parameters = inspect.signature(
        load_verified_controlled_execution_artifacts
    ).parameters
    assert set(parameters) == {"payload", "authorization"}

    with pytest.raises(
        ControlledArtifactVerificationError, match="pinned loader"
    ):
        VerifiedControlledExecutionArtifacts({})


def test_duplicate_json_key_and_post_signature_mutation_fail_closed(
    monkeypatch,
) -> None:
    duplicate = (
        '{"format":"controlled-execution-artifact-bundle/v1",'
        '"format":"forged"}'
    )
    with pytest.raises(ControlledArtifactVerificationError, match="duplicate key"):
        load_verified_controlled_execution_artifacts(
            duplicate, authorization=object()  # type: ignore[arg-type]
        )

    issued = datetime.now(timezone.utc)
    trader_private = Ed25519PrivateKey.generate()
    writer_private = Ed25519PrivateKey.generate()
    authorization = _authorization(
        trader_private, key_id="trader-test", issued=issued
    )
    payload = json.loads(
        _bundle(
            authorization,
            writer_private,
            writer_key_id="writer-test",
            written_at=issued,
        )
    )
    payload["artifacts"][0]["payload"]["experiment_id"] = "tampered"
    tampered = _canonical(payload)
    _install_test_roots(
        monkeypatch,
        trader_private=trader_private,
        trader_key_id="trader-test",
        writer_private=writer_private,
        writer_key_id="writer-test",
        clock=issued,
    )
    with pytest.raises(ControlledArtifactVerificationError, match="artifact_id"):
        load_verified_controlled_execution_artifacts(
            tampered, authorization=authorization
        )
