"""Adversarial contract tests for the PENDING exact-four Trader v2 path."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from execution.exact_four_authority_contract import (
    HISTORICAL_TRADER_AUTHORIZATION_CLAIMS_FORMAT,
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    ExactFourTraderAuthorityDecisionStoreV2,
    PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_DIGEST,
    PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_RAW_DIGEST,
    PilotReadinessAttestationClaimsV2,
    ReadySnapshotLineage,
    TRADER_AUTHORIZATION_V2_STATE,
    TRADER_V2_ACTIVE_CREDENTIAL_REGISTRY_COUNT,
    TRADER_V2_ACTIVE_RP_REGISTRY_COUNT,
    TraderAuthorizationClaimsV2,
    UnverifiedExactFourTraderApprovalSubjectV2,
    UnverifiedExactFourTraderAuthorizationEnvelopeV2,
    VerifiedExactFourTraderAuthorizationV2,
    VerifiedPilotReadinessV2,
    authorize_controlled_exact_four_execution_v2,
    build_controlled_execution_claims_v2,
    build_trader_authorization_claims_v2,
    canonical_authority_digest,
    compile_unverified_exact_four_trader_approval_subject_v2,
    derive_exact_four_trader_one_use_key_v2,
    exact_four_trader_authorization_schema_path,
    load_exact_four_execution_binding,
    load_exact_four_trader_authorization_schema,
    parse_and_validate_unverified_exact_four_trader_approval_subject_v2,
    parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2,
    prepare_exact_four_trader_approval_subject_v2,
    require_current_exact_four_trader_authorization_v2,
)
from execution.trader_authority import TraderAuthorizationPublicKeyRegistry
from scripts import (
    authority_principal_manifest as principal_manifest,
    authority_protocol_runtime,
)


def _digest(label: str) -> str:
    return canonical_authority_digest({"test": label})


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _with_digest(body: dict[str, Any], field: str) -> dict[str, Any]:
    return {**body, field: canonical_authority_digest(body)}


def _raw(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=True, separators=(",", ":"))


def _readiness(*, pilot_run_id: str = "pilot-run-trader-v2") -> tuple[
    PilotReadinessAttestationClaimsV2, datetime
]:
    now = datetime.now(timezone.utc)
    exact_four = load_exact_four_execution_binding()
    snapshot = ReadySnapshotLineage(
        snapshot_id=_digest("snapshot"),
        ready_manifest_digest=_digest("ready-manifest"),
        immutable_snapshot_digest=_digest("immutable-snapshot"),
        governed_membership_digest=(
            exact_four.required_dataset_membership_digest
        ),
        universe_rule_digest=exact_four.universe_rule_digest,
        resolved_universe_digest=_digest("resolved-universe"),
        coverage_policy_version=exact_four.coverage_policy_version,
        coverage_policy_digest=exact_four.coverage_policy_digest,
        coverage_status="COMPLETE",
        coverage_proof_digest=_digest("coverage"),
        raw_status="PRESENT",
        raw_proof_digest=_digest("raw"),
        trusted_receipt_status="COMPLETE",
        receipt_proof_digest=_digest("receipt"),
        validation_status="PASS",
        validation_proof_digest=_digest("validation"),
        natural_key_status="PASS",
        natural_key_proof_digest=_digest("natural-key"),
        b0_status="PASS",
        b0_proof_digest=_digest("b0"),
        b4_status="PASS",
        b4_proof_digest=_digest("b4"),
        pit_contract_set_digest=_digest("pit-contracts"),
        projection_status="FRESH",
        projection_refresh_success=True,
        projection_is_current=True,
        projection_generation="projection-generation-trader-v2",
        source_generation=42,
        applied_sync_generation=42,
        source_cursor=2_891_821,
        export_cursor=2_891_821,
        applied_cursor=2_891_821,
        feature_generation=_digest("features"),
        catalog_generation=_digest("catalog"),
    )
    return (
        PilotReadinessAttestationClaimsV2(
            pilot_run_id=pilot_run_id,
            snapshot=snapshot,
            exact_four=exact_four,
            issued_at=_iso(now - timedelta(minutes=5)),
            expires_at=_iso(now + timedelta(minutes=25)),
        ),
        now,
    )


def _authority_request_id(
    *,
    environment: str,
    subject_id: str,
    challenge_digest: str,
    assertion_digest: str,
    registry_evidence_digest: str,
    ledger_transaction_digest: str,
    ledger_event_digest: str,
) -> str:
    return canonical_authority_digest(
        {
            "format": "exact-four-trader-authority-request/v2",
            "environment": environment,
            "approval_subject_id": subject_id,
            "challenge_digest": challenge_digest,
            "assertion_digest": assertion_digest,
            "credential_registry_evidence_digest": registry_evidence_digest,
            "one_use_ledger_transaction_digest": ledger_transaction_digest,
            "one_use_ledger_event_digest": ledger_event_digest,
        }
    )


def _authority_idempotency(
    *,
    environment: str,
    request_id: str,
    subject_id: str,
    payload_schema: str,
    payload_digest: str,
) -> str:
    return canonical_authority_digest(
        {
            "environment": environment,
            "authority_id": "trader",
            "request_id": request_id,
            "event_type": "COMMITTED",
            "subject_id": subject_id,
            "payload_schema": payload_schema,
            "payload_digest": payload_digest,
        }
    )


def _authorization_decision_id(
    *,
    environment: str,
    subject_id: str,
    request_id: str,
    challenge_digest: str,
    assertion_digest: str,
    registry_evidence_digest: str,
    ledger_transaction_digest: str,
    ledger_event_digest: str,
) -> str:
    return canonical_authority_digest(
        {
            "format": "exact-four-trader-authorization-decision/v2",
            "environment": environment,
            "authority_id": "trader",
            "approval_subject_id": subject_id,
            "authority_request_id": request_id,
            "challenge_digest": challenge_digest,
            "assertion_digest": assertion_digest,
            "credential_registry_evidence_digest": registry_evidence_digest,
            "one_use_ledger_transaction_digest": ledger_transaction_digest,
            "one_use_ledger_event_digest": ledger_event_digest,
            "authorization_status": "AUTHORIZED",
        }
    )


def _authority_transaction_idempotency_key(
    *,
    environment: str,
    subject_id: str,
    request_id: str,
    authorization_decision_id: str,
    ledger_transaction_digest: str,
    ledger_event_digest: str,
) -> str:
    return canonical_authority_digest(
        {
            "format": "exact-four-trader-authority-transaction-idempotency/v2",
            "environment": environment,
            "authority_id": "trader",
            "approval_subject_id": subject_id,
            "authority_request_id": request_id,
            "authorization_decision_id": authorization_decision_id,
            "one_use_ledger_transaction_digest": ledger_transaction_digest,
            "one_use_ledger_event_digest": ledger_event_digest,
        }
    )


def _envelope(
    subject: UnverifiedExactFourTraderApprovalSubjectV2,
    *,
    now: datetime,
    environment: str = "production",
    ledger_environment: str | None = None,
    counter_mode: str = "COUNTING",
    stored_sign_count: int = 6,
    assertion_sign_count: int = 7,
    ledger_asserted_sign_count: int | None = None,
    ledger_result_sign_count: int | None = None,
    counter_cas_status: str | None = None,
    challenge_base64url: str | None = None,
    challenge_expires_at: str | None = None,
    sequence: int = 2,
    prior_sequence: int | None = None,
    prior_event_digest: str | None | object = ...,
    authority_event_id: str = "55555555-5555-4555-8555-555555555555",
    authority_transaction_id: str = "66666666-6666-4666-8666-666666666666",
) -> dict[str, Any]:
    rp_id = "example.invalid"
    origin = "https://pilot.example.invalid"
    challenge_body: dict[str, Any] = {
        "format": "exact-four-trader-webauthn-challenge/v2",
        "environment": environment,
        "status": "ISSUED",
        "challenge_id": "11111111-1111-4111-8111-111111111111",
        "challenge_base64url": (
            challenge_base64url
            if challenge_base64url is not None
            else _b64(bytes(range(32)))
        ),
        "approval_subject_id": subject.approval_subject_id,
        "rp_policy_generation": 2,
        "rp_policy_digest": _digest("rp-policy-generation-2"),
        "rp_id": rp_id,
        "origin": origin,
        "user_presence_required": True,
        "user_verification_required": True,
        "issued_at": _iso(now - timedelta(minutes=4)),
        "expires_at": (
            challenge_expires_at
            if challenge_expires_at is not None
            else _iso(now + timedelta(minutes=15))
        ),
    }
    challenge_body["one_use_key"] = derive_exact_four_trader_one_use_key_v2(
        dict(challenge_body)
    )
    challenge = _with_digest(challenge_body, "challenge_digest")

    credential_id = _b64(hashlib.sha256(b"credential-id-v2").digest())
    client = {
        "type": "webauthn.get",
        "challenge": challenge["challenge_base64url"],
        "origin": origin,
        "crossOrigin": False,
    }
    authenticator = (
        hashlib.sha256(rp_id.encode("utf-8")).digest()
        + bytes([0x05])
        + assertion_sign_count.to_bytes(4, "big")
    )
    assertion = _with_digest(
        {
            "format": "exact-four-trader-webauthn-assertion/v2",
            "environment": environment,
            "status": "VERIFIED",
            "challenge_id": challenge["challenge_id"],
            "challenge_digest": challenge["challenge_digest"],
            "approval_subject_id": subject.approval_subject_id,
            "rp_policy_generation": challenge["rp_policy_generation"],
            "rp_policy_digest": challenge["rp_policy_digest"],
            "credential_id_base64url": credential_id,
            "authenticator_data_base64url": _b64(authenticator),
            "client_data_json_base64url": _b64(
                _canonical_json(client).encode("utf-8")
            ),
            "signature_base64url": _b64(bytes(range(64))),
            "rp_id": rp_id,
            "origin": origin,
            "user_present": True,
            "user_verified": True,
            "sign_count": assertion_sign_count,
            "asserted_at": _iso(now - timedelta(minutes=3)),
            "one_use_key": challenge["one_use_key"],
        },
        "assertion_digest",
    )
    registry = _with_digest(
        {
            "format": "exact-four-trader-credential-registry-evidence/v2",
            "environment": environment,
            "evidence_status": "PASS",
            "credential_status": "ACTIVE",
            "registry_id": "exact-four-trader-webauthn-credentials/v2",
            "registry_generation": 3,
            "registry_digest": _digest("credential-registry-generation-3"),
            "rp_policy_id": "exact-four-trader-rp-policy/v2",
            "rp_policy_generation": challenge["rp_policy_generation"],
            "rp_policy_digest": challenge["rp_policy_digest"],
            "rp_id": rp_id,
            "origin": origin,
            "credential_id_base64url": credential_id,
            "credential_public_key_digest": _digest("credential-public-key"),
            "credential_algorithm": "ES256",
            "key_backend": "webauthn_platform_or_hardware",
            "counter_mode": counter_mode,
            "stored_sign_count": stored_sign_count,
            "effective_at": _iso(now - timedelta(days=1)),
            "observed_at": _iso(now - timedelta(minutes=2, seconds=30)),
            "verification_backend_id": "ExactFourTraderWebAuthnVerifier/v2",
            "verification_backend_version": "v2",
            "verification_backend_generation": 2,
            "verification_event_id": "22222222-2222-4222-8222-222222222222",
            "verification_event_digest": _digest("credential-verification-event"),
        },
        "evidence_digest",
    )
    ledger_asserted = (
        assertion_sign_count
        if ledger_asserted_sign_count is None
        else ledger_asserted_sign_count
    )
    ledger_result = (
        ledger_asserted
        if ledger_result_sign_count is None
        else ledger_result_sign_count
    )
    counter_cas = (
        ("NOT_APPLICABLE" if counter_mode == "COUNTERLESS" else "APPLIED")
        if counter_cas_status is None
        else counter_cas_status
    )
    ledger_transaction_body: dict[str, Any] = {
        "format": "exact-four-trader-one-use-ledger-event/v2",
        "environment": ledger_environment or environment,
        "ledger_id": "exact-four-trader-one-use-ledger/v2",
        "ledger_backend_id": "ExactFourTraderOneUseLedger/v2",
        "ledger_generation": 5,
        "ledger_transaction_id": "33333333-3333-4333-8333-333333333333",
        "transaction_status": "COMMITTED",
        "transaction_committed_at": _iso(
            now - timedelta(minutes=1, seconds=50)
        ),
        "event_id": "44444444-4444-4444-8444-444444444444",
        "approval_subject_id": subject.approval_subject_id,
        "challenge_id": challenge["challenge_id"],
        "challenge_digest": challenge["challenge_digest"],
        "assertion_digest": assertion["assertion_digest"],
        "one_use_key": challenge["one_use_key"],
        "credential_id_base64url": credential_id,
        "credential_registry_generation": registry["registry_generation"],
        "credential_registry_digest": registry["registry_digest"],
        "counter_mode": counter_mode,
        "prior_sign_count": stored_sign_count,
        "asserted_sign_count": ledger_asserted,
        "result_sign_count": ledger_result,
        "one_use_prior_status": "AVAILABLE",
        "one_use_result_status": "CONSUMED",
        "one_use_cas_status": "APPLIED",
        "counter_cas_status": counter_cas,
        "consumed_at": _iso(now - timedelta(minutes=2)),
    }
    ledger_transaction_body["ledger_transaction_digest"] = (
        canonical_authority_digest(ledger_transaction_body)
    )
    ledger = _with_digest(ledger_transaction_body, "event_digest")

    authority_sequence = sequence
    payload_prior_sequence = (
        sequence - 1 if prior_sequence is None else prior_sequence
    )
    if prior_event_digest is ...:
        authority_prior_digest: str | None = (
            None if sequence == 1 else _digest("prior-authority-event")
        )
    else:
        authority_prior_digest = prior_event_digest  # type: ignore[assignment]
    request_id = _authority_request_id(
        environment=environment,
        subject_id=subject.approval_subject_id,
        challenge_digest=challenge["challenge_digest"],
        assertion_digest=assertion["assertion_digest"],
        registry_evidence_digest=registry["evidence_digest"],
        ledger_transaction_digest=ledger["ledger_transaction_digest"],
        ledger_event_digest=ledger["event_digest"],
    )
    authorization_decision_id = _authorization_decision_id(
        environment=environment,
        subject_id=subject.approval_subject_id,
        request_id=request_id,
        challenge_digest=challenge["challenge_digest"],
        assertion_digest=assertion["assertion_digest"],
        registry_evidence_digest=registry["evidence_digest"],
        ledger_transaction_digest=ledger["ledger_transaction_digest"],
        ledger_event_digest=ledger["event_digest"],
    )
    authority_transaction_idempotency_key = (
        _authority_transaction_idempotency_key(
            environment=environment,
            subject_id=subject.approval_subject_id,
            request_id=request_id,
            authorization_decision_id=authorization_decision_id,
            ledger_transaction_digest=ledger["ledger_transaction_digest"],
            ledger_event_digest=ledger["event_digest"],
        )
    )
    payload_body: dict[str, Any] = {
        "format": "exact-four-trader-authority-event-payload/v2",
        "environment": environment,
        "authority_backend_id": (
            "ExactFourTraderAuthorizationAuthorityBackend/v2"
        ),
        "authority_backend_generation": 4,
        "prior_sequence": payload_prior_sequence,
        "prior_event_digest": authority_prior_digest,
        "authority_transaction_id": authority_transaction_id,
        "authority_event_id": authority_event_id,
        "authority_request_id": request_id,
        "authorization_decision_id": authorization_decision_id,
        "authority_transaction_idempotency_key": (
            authority_transaction_idempotency_key
        ),
        "authority_sequence": authority_sequence,
        "authority_transaction_status": "COMMITTED",
        "approval_subject_id": subject.approval_subject_id,
        "challenge_digest": challenge["challenge_digest"],
        "assertion_digest": assertion["assertion_digest"],
        "credential_registry_evidence_digest": registry["evidence_digest"],
        "one_use_ledger_generation": ledger["ledger_generation"],
        "one_use_ledger_transaction_id": ledger["ledger_transaction_id"],
        "one_use_ledger_transaction_digest": ledger[
            "ledger_transaction_digest"
        ],
        "one_use_ledger_event_id": ledger["event_id"],
        "one_use_ledger_event_digest": ledger["event_digest"],
        "one_use_ledger_commit_status": ledger["transaction_status"],
        "recorded_at": _iso(now - timedelta(minutes=1, seconds=40)),
    }
    payload_body["authority_transaction_digest"] = canonical_authority_digest(
        payload_body
    )
    payload_json = _canonical_json(payload_body)
    payload_schema = "exact-four-trader-authority-event-payload/v2"
    payload_digest = canonical_authority_digest(payload_body)
    idempotency_key = _authority_idempotency(
        environment=environment,
        request_id=request_id,
        subject_id=subject.approval_subject_id,
        payload_schema=payload_schema,
        payload_digest=payload_digest,
    )
    authority = _with_digest(
        {
            "schema_version": "authority-event/v2",
            "environment": environment,
            "authority_id": "trader",
            "sequence": authority_sequence,
            "event_id": authority_event_id,
            "idempotency_key": idempotency_key,
            "request_id": request_id,
            "event_type": "COMMITTED",
            "subject_id": subject.approval_subject_id,
            "prior_event_digest": authority_prior_digest,
            "payload_schema": payload_schema,
            "payload_digest": payload_digest,
            "payload_json": payload_json,
            "observed_at": _iso(now - timedelta(minutes=1, seconds=30)),
        },
        "event_digest",
    )
    return _with_digest(
        {
            "format": "exact-four-trader-authorization-envelope/v2",
            "issuer": "ExactFourTraderAuthorizationAuthority/v2",
            "authority_scope": "EXACT_FOUR_TRADER_AUTHORIZATION",
            "execution_mode": "paper",
            "approval_subject_id": subject.approval_subject_id,
            "authorization_decision_id": authorization_decision_id,
            "issuer_key_id": credential_id,
            "issuer_key_algorithm": registry["credential_algorithm"],
            "issuer_key_backend": registry["key_backend"],
            "issuer_key_registry_generation": registry["registry_generation"],
            "issuer_key_registry_digest": registry["registry_digest"],
            "issuer_backend_id": payload_body["authority_backend_id"],
            "issuer_backend_generation": payload_body[
                "authority_backend_generation"
            ],
            "authorization_status": "AUTHORIZED",
            "challenge_evidence": challenge,
            "assertion_evidence": assertion,
            "credential_registry_evidence": registry,
            "one_use_ledger_event": ledger,
            "authority_event": authority,
            "issued_at": authority["observed_at"],
            "expires_at": challenge["expires_at"],
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        },
        "authorization_id",
    )


def _rehash_authority(document: dict[str, Any]) -> None:
    authority = dict(document["authority_event"])
    authority.pop("event_digest", None)
    document["authority_event"] = _with_digest(authority, "event_digest")
    body = dict(document)
    body.pop("authorization_id", None)
    document.clear()
    document.update(_with_digest(body, "authorization_id"))


def _replace_payload(document: dict[str, Any], **changes: Any) -> None:
    authority = dict(document["authority_event"])
    payload = json.loads(authority["payload_json"])
    payload.update(changes)
    payload.pop("authority_transaction_digest", None)
    payload["authority_transaction_digest"] = canonical_authority_digest(payload)
    authority["payload_json"] = _canonical_json(payload)
    authority["payload_digest"] = canonical_authority_digest(payload)
    authority["idempotency_key"] = _authority_idempotency(
        environment=authority["environment"],
        request_id=authority["request_id"],
        subject_id=authority["subject_id"],
        payload_schema=authority["payload_schema"],
        payload_digest=authority["payload_digest"],
    )
    document["authority_event"] = authority
    _rehash_authority(document)


def test_schema_and_manifest_pins_keep_all_registries_inactive() -> None:
    schema = load_exact_four_trader_authorization_schema()
    raw = exact_four_trader_authorization_schema_path().read_bytes()
    assert canonical_authority_digest(schema) == (
        PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_DIGEST
    )
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == (
        PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_RAW_DIGEST
    )
    assert b"human_approval_event" not in raw
    assert b"staging.quant-platform.local" not in raw
    challenge_properties = schema["$defs"]["challengeEvidence"]["properties"]
    assert challenge_properties["rp_id"] == {"$ref": "#/$defs/rpId"}
    assert challenge_properties["origin"] == {"$ref": "#/$defs/httpsOrigin"}
    assert TRADER_V2_ACTIVE_RP_REGISTRY_COUNT == 0
    assert TRADER_V2_ACTIVE_CREDENTIAL_REGISTRY_COUNT == 0
    registry = TraderAuthorizationPublicKeyRegistry.load_pinned()
    assert not registry.verify(
        key_id="trader-authorization-20260825-v1",
        body={"not": "an authorization"},
        signature="ed25519:" + "A" * 88,
    )


def test_audit_compiler_is_named_unverified_and_positive_ready_stays_pending() -> None:
    readiness, _now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    assert type(subject) is UnverifiedExactFourTraderApprovalSubjectV2
    assert subject.readiness_attestation_id == readiness.attestation_id
    assert "human_approval" not in _raw(subject.to_dict())
    assert tuple(
        inspect.signature(
            compile_unverified_exact_four_trader_approval_subject_v2
        ).parameters
    ) == ("readiness",)
    parsed = parse_and_validate_unverified_exact_four_trader_approval_subject_v2(
        _raw(subject.to_dict())
    )
    assert parsed == subject

    forged_ready = object.__new__(VerifiedPilotReadinessV2)
    with pytest.raises(ExactFourAuthorityPending, match="verified READY"):
        prepare_exact_four_trader_approval_subject_v2(forged_ready)
    assert (
        inspect.signature(prepare_exact_four_trader_approval_subject_v2)
        .parameters["readiness"]
        .annotation
        == "VerifiedPilotReadinessV2"
    )


def test_valid_counting_envelope_is_structural_and_positive_gate_is_pending() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = _envelope(subject, now=now)
    parsed = (
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(document),
            subject=subject,
        )
    )
    assert type(parsed) is UnverifiedExactFourTraderAuthorizationEnvelopeV2
    assert parsed.to_dict() == document
    assert parsed.authorization_id == document["authorization_id"]
    assert parsed.authorization_decision_id == document[
        "authorization_decision_id"
    ]
    assert TRADER_AUTHORIZATION_V2_STATE.startswith("PENDING_")
    with pytest.raises(ExactFourAuthorityPending):
        require_current_exact_four_trader_authorization_v2(parsed)
    with pytest.raises(ExactFourAuthorityContractError, match="exact Trader"):
        build_controlled_execution_claims_v2(  # type: ignore[arg-type]
            readiness,
            parsed,
            issued_at=_iso(now),
            expires_at=_iso(now + timedelta(minutes=5)),
        )


def test_same_authority_evidence_cannot_mint_caller_selected_lifetimes() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    original = _envelope(subject, now=now)
    mutations = {
        "issued_at": _iso(now - timedelta(minutes=1)),
        "expires_at": _iso(now + timedelta(minutes=14)),
    }
    for field, value in mutations.items():
        mutated = json.loads(_raw(original))
        mutated[field] = value
        body = dict(mutated)
        body.pop("authorization_id")
        mutated = _with_digest(body, "authorization_id")
        assert mutated["authority_event"] == original["authority_event"]
        assert mutated["one_use_ledger_event"] == original["one_use_ledger_event"]
        with pytest.raises(
            ExactFourAuthorityContractError,
            match="lifetime is not deterministically derived",
        ):
            parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
                _raw(mutated),
                subject=subject,
            )


def test_sequence_rewrap_has_one_stable_store_key_and_stays_pending() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    first = _envelope(subject, now=now, sequence=2)
    second = _envelope(
        subject,
        now=now,
        sequence=3,
        prior_sequence=2,
        prior_event_digest=first["authority_event"]["event_digest"],
        authority_event_id="77777777-7777-4777-8777-777777777777",
        authority_transaction_id="88888888-8888-4888-8888-888888888888",
    )
    first_parsed = (
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(first),
            subject=subject,
        )
    )
    second_parsed = (
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(second),
            subject=subject,
        )
    )
    first_payload = json.loads(first["authority_event"]["payload_json"])
    second_payload = json.loads(second["authority_event"]["payload_json"])
    assert first["authority_event"]["request_id"] == second["authority_event"][
        "request_id"
    ]
    assert first["one_use_ledger_event"] == second["one_use_ledger_event"]
    assert first["authorization_decision_id"] == second[
        "authorization_decision_id"
    ]
    assert first_payload["authority_transaction_idempotency_key"] == (
        second_payload["authority_transaction_idempotency_key"]
    )
    assert first["authority_event"]["idempotency_key"] != second[
        "authority_event"
    ]["idempotency_key"]
    assert first["authorization_id"] != second["authorization_id"]
    for parsed in (first_parsed, second_parsed):
        with pytest.raises(ExactFourAuthorityPending):
            require_current_exact_four_trader_authorization_v2(parsed)

    store_signature = inspect.signature(
        ExactFourTraderAuthorityDecisionStoreV2.append_decision_once
    )
    assert tuple(store_signature.parameters) == (
        "self",
        "environment",
        "authority_id",
        "authorization_decision_id",
        "authority_transaction_idempotency_key",
        "authority_request_id",
        "one_use_ledger_transaction_digest",
        "one_use_ledger_event_digest",
        "canonical_authority_event",
    )


def test_ledger_rejects_assertion_7_with_asserted_and_result_8() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = _envelope(
        subject,
        now=now,
        assertion_sign_count=7,
        ledger_asserted_sign_count=8,
        ledger_result_sign_count=8,
    )
    with pytest.raises(ExactFourAuthorityContractError, match="assertion state"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(document),
            subject=subject,
        )


def test_counting_and_counterless_modes_are_exact() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    non_advance = _envelope(
        subject,
        now=now,
        stored_sign_count=7,
        assertion_sign_count=7,
    )
    with pytest.raises(ExactFourAuthorityContractError, match="must advance"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(non_advance),
            subject=subject,
        )

    counterless = _envelope(
        subject,
        now=now,
        counter_mode="COUNTERLESS",
        stored_sign_count=0,
        assertion_sign_count=0,
    )
    parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
        _raw(counterless),
        subject=subject,
    )
    bad_counterless = _envelope(
        subject,
        now=now,
        counter_mode="COUNTERLESS",
        stored_sign_count=1,
        assertion_sign_count=0,
    )
    with pytest.raises(ExactFourAuthorityContractError, match="counterless"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(bad_counterless),
            subject=subject,
        )


def test_environment_splice_is_rejected_after_all_digests_are_valid() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = _envelope(
        subject,
        now=now,
        environment="production",
        ledger_environment="staging",
    )
    with pytest.raises(ExactFourAuthorityContractError, match="environment splice"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(document),
            subject=subject,
        )


@pytest.mark.parametrize(
    "invalid_challenge",
    [
        "AAAAA",
        "AB",
        _b64(b"too-short"),
        _b64(bytes(range(32))) + "=",
    ],
)
def test_challenge_base64url_size_padding_and_pad_bits_fail_closed(
    invalid_challenge: str,
) -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = _envelope(
        subject,
        now=now,
        challenge_base64url=invalid_challenge,
    )
    with pytest.raises(ExactFourAuthorityContractError, match="base64url|size|pad bits"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(document),
            subject=subject,
        )


def test_changed_challenge_time_changes_key_and_old_ledger_cannot_be_spliced() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    first = _envelope(subject, now=now)
    second = _envelope(
        subject,
        now=now,
        challenge_expires_at=_iso(now + timedelta(minutes=14)),
    )
    first_challenge = first["challenge_evidence"]
    second_challenge = second["challenge_evidence"]
    assert first_challenge["one_use_key"] != second_challenge["one_use_key"]
    assert first_challenge["challenge_digest"] != second_challenge[
        "challenge_digest"
    ]
    second["one_use_ledger_event"] = first["one_use_ledger_event"]
    body = dict(second)
    body.pop("authorization_id")
    second = _with_digest(body, "authorization_id")
    with pytest.raises(ExactFourAuthorityContractError, match="transaction|evidence"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(second),
            subject=subject,
        )


def test_authority_event_uses_exact_v2_append_only_field_convention() -> None:
    trader_schema = load_exact_four_trader_authorization_schema()
    authority_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "specs"
            / "authorities"
            / "authority_event.schema.json"
        ).read_text(encoding="utf-8")
    )
    nested = trader_schema["$defs"]["authorityEvent"]
    assert set(nested["required"]) == set(authority_schema["required"])
    assert nested["properties"]["schema_version"]["const"] == (
        "authority-event/v2"
    )


def test_authority_event_is_accepted_by_shared_v2_inspector() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = _envelope(subject, now=now)
    authority = document["authority_event"]
    candidate = authority_protocol_runtime.inspect_authority_event_candidate(
        _raw(authority),
        expected_authority="trader",
        expected_environment="production",
        expected_sequence=authority["sequence"],
        expected_prior_event_digest=authority["prior_event_digest"],
        expected_prior_observed_at=_iso(now - timedelta(minutes=2)),
    )
    assert dict(candidate.payload) == json.loads(authority["payload_json"])


@pytest.mark.parametrize(
    ("document_factory", "message"),
    [
        (
            lambda subject, now: _envelope(
                subject,
                now=now,
                sequence=3,
                prior_sequence=1,
            ),
            "prior sequence plus one",
        ),
        (
            lambda subject, now: _envelope(
                subject,
                now=now,
                sequence=1,
                prior_sequence=0,
                prior_event_digest=_digest("illegal-prior"),
            ),
            "schema violation|prior sequence and digest",
        ),
    ],
)
def test_authority_prior_sequence_and_digest_fail_closed(
    document_factory: Any,
    message: str,
) -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = document_factory(subject, now)
    with pytest.raises(ExactFourAuthorityContractError, match=message):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(document),
            subject=subject,
        )


def test_authority_idempotency_and_ledger_linkage_are_remeasured() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    bad_idempotency = _envelope(subject, now=now)
    bad_idempotency["authority_event"]["idempotency_key"] = _digest(
        "caller-idempotency"
    )
    _rehash_authority(bad_idempotency)
    with pytest.raises(ExactFourAuthorityContractError, match="idempotency"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(bad_idempotency),
            subject=subject,
        )

    bad_link = _envelope(subject, now=now)
    _replace_payload(
        bad_link,
        one_use_ledger_event_id="77777777-7777-4777-8777-777777777777",
    )
    with pytest.raises(ExactFourAuthorityContractError, match="evidence transaction"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(bad_link),
            subject=subject,
        )


def test_credential_registry_rp_counter_and_time_are_cross_linked() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    document = _envelope(subject, now=now)
    registry = dict(document["credential_registry_evidence"])
    registry["rp_policy_digest"] = _digest("different-rp-policy")
    registry.pop("evidence_digest")
    document["credential_registry_evidence"] = _with_digest(
        registry,
        "evidence_digest",
    )
    body = dict(document)
    body.pop("authorization_id")
    document = _with_digest(body, "authorization_id")
    with pytest.raises(ExactFourAuthorityContractError, match="governed RP"):
        parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
            _raw(document),
            subject=subject,
        )


def test_old_unsigned_and_forged_positive_types_never_enter_new_path() -> None:
    readiness, now = _readiness()
    historical = build_trader_authorization_claims_v2(
        readiness,
        human_approval_event_id="caller-self-report",
        human_approval_event_digest=_digest("caller-self-report"),
        issued_at=_iso(now - timedelta(minutes=4)),
        expires_at=_iso(now + timedelta(minutes=15)),
    )
    assert type(historical) is TraderAuthorizationClaimsV2
    assert historical.format == HISTORICAL_TRADER_AUTHORIZATION_CLAIMS_FORMAT
    with pytest.raises(ExactFourAuthorityContractError):
        parse_and_validate_unverified_exact_four_trader_approval_subject_v2(
            _raw(historical.to_dict())
        )
    with pytest.raises(ExactFourAuthorityContractError, match="VerifiedPilot"):
        prepare_exact_four_trader_approval_subject_v2(  # type: ignore[arg-type]
            readiness
        )
    with pytest.raises(ExactFourAuthorityContractError, match="VerifiedPilot"):
        authorize_controlled_exact_four_execution_v2(  # type: ignore[arg-type]
            readiness,
            historical,
        )

    forged_ready = object.__new__(VerifiedPilotReadinessV2)
    forged_trader = object.__new__(VerifiedExactFourTraderAuthorizationV2)
    with pytest.raises(ExactFourAuthorityPending):
        authorize_controlled_exact_four_execution_v2(forged_ready, forged_trader)
    signature = inspect.signature(authorize_controlled_exact_four_execution_v2)
    assert signature.parameters["readiness"].annotation == "VerifiedPilotReadinessV2"
    assert signature.parameters["trader"].annotation == (
        "VerifiedExactFourTraderAuthorizationV2"
    )


def test_schema_rejects_missing_atomic_ledger_and_arbitrary_status() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    validator = Draft202012Validator(
        load_exact_four_trader_authorization_schema(),
        format_checker=FormatChecker(),
    )
    validator.validate(subject.to_dict())
    validator.validate(_envelope(subject, now=now))
    missing = _envelope(subject, now=now)
    missing.pop("one_use_ledger_event")
    with pytest.raises(ValidationError):
        validator.validate(missing)
    wrong = _envelope(subject, now=now)
    wrong["one_use_ledger_event"]["transaction_status"] = "PREPARED"
    with pytest.raises(ValidationError):
        validator.validate(wrong)


def test_manifest_lists_every_trader_activation_blocker() -> None:
    manifest = principal_manifest.load_and_validate_manifest()
    dependencies = manifest["principals"]["trader"]["pending_dependencies"]
    assert [item["dependency_id"] for item in dependencies] == [
        "verified_pilot_readiness_v2",
        "governed_trader_rp_registry",
        "governed_webauthn_challenge_generator",
        "webauthn_credential_registry_and_signature_verifier",
        "atomic_one_use_and_counter_ledger",
        "append_only_trader_authority_event_store",
        "controlled_execution_v2_consumer",
    ]
    assert all(item["status"] == "PENDING" for item in dependencies)
    assert all(item["activation_blocked"] is True for item in dependencies)
    event_store = next(
        item
        for item in dependencies
        if item["dependency_id"] == "append_only_trader_authority_event_store"
    )
    assert "atomically unique" in event_store["required_contract"]
    assert "byte-identical committed event" in event_store["required_contract"]


def test_structural_parser_does_not_claim_to_measure_challenge_entropy() -> None:
    readiness, now = _readiness()
    subject = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    canonical_low_diversity = _b64(b"\x00" * 32)
    document = _envelope(
        subject,
        now=now,
        challenge_base64url=canonical_low_diversity,
    )
    parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
        _raw(document),
        subject=subject,
    )


def test_subject_id_remains_deterministic_without_human_event_input() -> None:
    readiness, _now = _readiness()
    first = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    second = compile_unverified_exact_four_trader_approval_subject_v2(readiness)
    assert first.approval_subject_id == second.approval_subject_id
    changed = replace(readiness, pilot_run_id="pilot-run-trader-v2-other")
    assert (
        compile_unverified_exact_four_trader_approval_subject_v2(
            changed
        ).approval_subject_id
        != first.approval_subject_id
    )
