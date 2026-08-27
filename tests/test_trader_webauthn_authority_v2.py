"""Behavior tests for the inactive exact-four Trader WebAuthn authority."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import (
    require_current_exact_four_trader_authorization_v2,
)
from execution.trader_webauthn_authority_v2 import (
    CommittedExactFourTraderHandoffV2,
    ExactFourTraderAuthorityV2Error,
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderRelyingPartyV2,
    _create_test_exact_four_trader_authority_v2,
    open_live_exact_four_trader_authority_v2,
    verify_ready_authority_response_v2,
)
import execution.trader_webauthn_authority_v2 as trader_authority_module
from research.ready_manifest import (
    build_ready_manifest,
    load_exact_four_pilot_ready_binding,
)
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
import research.readiness as readiness_module
from tests.readiness_test_support import make_readiness_signer, mint_pilot_readiness


def _digest(label: str) -> str:
    return canonical_authority_digest({"test": label})


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _ready_evidence(
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    binding = load_exact_four_pilot_ready_binding()
    snapshot_id = _digest("snapshot")
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
        resolved_universe_digest=_digest("resolved-universe"),
        dataset_ids=binding.required_datasets,
        coverage_proof_digest=_digest("coverage"),
        raw_proof_digest=_digest("raw"),
        receipt_proof_digest=_digest("receipt"),
        validation_proof_digest=_digest("validation"),
        b0_proof_digest=_digest("b0"),
        b4_proof_digest=_digest("b4"),
        source_generation="7",
        applied_sync_generation="7",
        export_cursor="7",
        applied_cursor="7",
        pit_contract_digests={"pit": _digest("pit")},
        feature_generation=_digest("features"),
        catalog_generation=_digest("catalog"),
        created_at=(now - timedelta(minutes=2)).isoformat(),
        published_at=(now - timedelta(minutes=1)).isoformat(),
    )
    signer = make_readiness_signer(
        key_id="test-ready-authority-v1",
        environment="staging",
    )
    immutable = _digest("immutable-db")
    projection_digest = _digest("signed-projection")
    readiness = mint_pilot_readiness(
        manifest,
        publisher=signer,
        immutable_db_digest=immutable,
        now=now,
        ttl_seconds=1_200,
        signed_projection_document_digest=projection_digest,
    )
    monkeypatch.setattr(
        readiness_module.ReadinessPublicKeyRegistry,
        "load_pinned",
        classmethod(
            lambda cls, *, expected_environment: signer.public_registry()
        ),
    )
    monkeypatch.setattr(readiness_module, "_now", lambda: now)
    attestation = _canonical(readiness.to_dict())
    result = {
        "status": "SIGNED",
        "environment": readiness.environment,
        "authority_instance_id": readiness.authority_instance_id,
        "authority_resource_digest": readiness.authority_resource_digest,
        "snapshot_id": snapshot_id,
        "attestation_id": readiness.attestation_id,
        "attestation_base64": base64.b64encode(attestation).decode("ascii"),
        "attestation_digest": "sha256:"
        + hashlib.sha256(attestation).hexdigest(),
        "ready_manifest_digest": manifest.to_dict()["manifest_digest"],
        "immutable_db_digest": immutable,
        "signed_projection_document_digest": projection_digest,
        "issuer_key_id": readiness.key_id,
    }
    response = {
        "format": "local-authority-response/v1",
        "request_id": "test-ready-request",
        "status": "COMMITTED",
        "result": result,
    }
    return verify_ready_authority_response_v2(
        _canonical(response),
        expected_environment="staging",
    )


def _authority(
    tmp_path: Path,
    now_box: list[datetime],
    *,
    positive_gate: Any = lambda: object(),
    server_bound: bool = True,
) -> tuple[Any, ec.EllipticCurvePrivateKey, Any, Any]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    rp = ExactFourTraderRelyingPartyV2(
        environment="staging",
        policy_id="exact-four-trader-test-rp/v2",
        policy_generation=1,
        rp_id="trader.test.invalid",
        origin="https://pilot.trader.test.invalid",
        effective_at=(now_box[0] - timedelta(days=1)).isoformat(),
    )
    rps = ExactFourTraderRelyingPartyRegistryV2((rp,), generation=1)
    credential = ExactFourTraderCredentialV2(
        environment="staging",
        credential_id=hashlib.sha256(b"test-webauthn-credential").digest(),
        public_key=private_key.public_key(),
        rp_policy_digest=rp.policy_digest,
        effective_at=(now_box[0] - timedelta(days=1)).isoformat(),
        initial_sign_count=6,
    )
    credentials = ExactFourTraderCredentialRegistryV2(
        (credential,), generation=1
    )
    authority = _create_test_exact_four_trader_authority_v2(
        ledger_path=(tmp_path / "trader-authority.sqlite").resolve(),
        relying_parties=rps,
        credentials=credentials,
        clock=lambda: now_box[0],
        positive_gate=positive_gate,
        server_bound=server_bound,
    )
    return authority, private_key, rp, credential


def test_signed_staging_ready_response_cannot_authorize_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    staging = _ready_evidence(now, monkeypatch)

    with pytest.raises(
        ExactFourTraderAuthorityV2Error,
        match="pinned verifier",
    ):
        verify_ready_authority_response_v2(
            staging.canonical_response,
            expected_environment="production",
        )


def _assertion(
    *,
    challenge: Any,
    private_key: ec.EllipticCurvePrivateKey,
    credential: Any,
    now: datetime,
    sign_count: int,
    signature_mutation: bool = False,
) -> dict[str, Any]:
    challenge_document = challenge.to_dict()
    client = {
        "type": "webauthn.get",
        "challenge": challenge_document["challenge_base64url"],
        "origin": challenge_document["origin"],
        "crossOrigin": False,
    }
    client_raw = _canonical(client)
    authenticator = (
        hashlib.sha256(challenge_document["rp_id"].encode("utf-8")).digest()
        + bytes([0x05])
        + sign_count.to_bytes(4, "big")
    )
    signature = private_key.sign(
        authenticator + hashlib.sha256(client_raw).digest(),
        ec.ECDSA(hashes.SHA256()),
    )
    if signature_mutation:
        signature = signature[:-1] + bytes([signature[-1] ^ 1])
    body = {
        "format": "exact-four-trader-webauthn-assertion/v2",
        "environment": challenge_document["environment"],
        "status": "VERIFIED",
        "challenge_id": challenge_document["challenge_id"],
        "challenge_digest": challenge_document["challenge_digest"],
        "approval_subject_id": challenge_document["approval_subject_id"],
        "rp_policy_generation": challenge_document["rp_policy_generation"],
        "rp_policy_digest": challenge_document["rp_policy_digest"],
        "credential_id_base64url": credential.credential_id_base64url,
        "authenticator_data_base64url": _b64(authenticator),
        "client_data_json_base64url": _b64(client_raw),
        "signature_base64url": _b64(signature),
        "rp_id": challenge_document["rp_id"],
        "origin": challenge_document["origin"],
        "user_present": True,
        "user_verified": True,
        "sign_count": sign_count,
        "asserted_at": now.isoformat(),
        "one_use_key": challenge_document["one_use_key"],
    }
    return {**body, "assertion_digest": canonical_authority_digest(body)}


def test_challenges_use_distinct_32_byte_random_values_and_live_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=2)]
    authority, _private, _rp, _credential = _authority(tmp_path, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    first = authority.issue_challenge(ready).to_dict()
    second = authority.issue_challenge(ready).to_dict()
    first_raw = base64.urlsafe_b64decode(
        first["challenge_base64url"]
        + "=" * (-len(first["challenge_base64url"]) % 4)
    )
    second_raw = base64.urlsafe_b64decode(
        second["challenge_base64url"]
        + "=" * (-len(second["challenge_base64url"]) % 4)
    )
    assert len(first_raw) == len(second_raw) == 32
    assert first_raw != second_raw
    assert first["one_use_key"] != second["one_use_key"]
    with pytest.raises(ExactFourAuthorityPending, match="HUMAN_ENROLLMENT"):
        open_live_exact_four_trader_authority_v2()


def test_real_es256_verification_commits_once_and_retry_is_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=2)]
    authority, private_key, _rp, credential = _authority(tmp_path, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = authority.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    first = authority.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )
    assert type(first) is CommittedExactFourTraderHandoffV2
    first_payload = first.to_dict()
    assert first_payload["handoff_status"] == "COMMITTED"
    assert first_payload["automatic_promotion"] is False
    assert first_payload["mass_research_enabled"] is False
    assert first_payload["live_trading_enabled"] is False
    with pytest.raises(ExactFourAuthorityPending):
        require_current_exact_four_trader_authorization_v2(first)
    assert authority.ledger.challenge_status(
        challenge.to_dict()["challenge_id"]
    ) == "CONSUMED"
    assert authority.ledger.credential_sign_count(
        credential.credential_id_base64url
    ) == 7
    assert authority.ledger.event_count() == 1

    retry = authority.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )
    assert retry.canonical_bytes == first.canonical_bytes
    assert authority.ledger.event_count() == 1
    fd = authority.open_handoff_descriptor(first)
    try:
        assert os.pread(fd, len(first.canonical_bytes), 0) == first.canonical_bytes
        with pytest.raises(OSError):
            os.write(fd, b"tamper")
    finally:
        os.close(fd)


def test_bad_signature_and_replay_cannot_consume_or_rewrap_challenge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=2)]
    authority, private_key, _rp, credential = _authority(tmp_path, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = authority.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    bad = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
        signature_mutation=True,
    )
    with pytest.raises(ExactFourTraderAuthorityV2Error, match="signature"):
        authority.authorize(
            readiness=ready,
            challenge=challenge,
            assertion_raw=_canonical(bad),
        )
    assert authority.ledger.challenge_status(
        challenge.to_dict()["challenge_id"]
    ) == "AVAILABLE"
    assert authority.ledger.credential_sign_count(
        credential.credential_id_base64url
    ) == 6

    valid = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    authority.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(valid),
    )
    replay = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=8,
    )
    with pytest.raises(ExactFourTraderAuthorityV2Error, match="unavailable"):
        authority.authorize(
            readiness=ready,
            challenge=challenge,
            assertion_raw=_canonical(replay),
        )
    assert authority.ledger.credential_sign_count(
        credential.credential_id_base64url
    ) == 7
    assert authority.ledger.event_count() == 1


def test_event_insert_failure_rolls_back_one_use_and_counter_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=2)]
    authority, private_key, _rp, credential = _authority(tmp_path, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = authority.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    ledger_path = (tmp_path / "trader-authority.sqlite").resolve()
    with sqlite3.connect(ledger_path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_test_event BEFORE INSERT ON trader_events "
            "BEGIN SELECT RAISE(ABORT, 'test event failure'); END"
        )
    with pytest.raises(ExactFourTraderAuthorityV2Error, match="transaction failed"):
        authority.authorize(
            readiness=ready,
            challenge=challenge,
            assertion_raw=_canonical(assertion),
        )
    assert authority.ledger.challenge_status(
        challenge.to_dict()["challenge_id"]
    ) == "AVAILABLE"
    assert authority.ledger.credential_sign_count(
        credential.credential_id_base64url
    ) == 6
    assert authority.ledger.event_count() == 0

    with sqlite3.connect(ledger_path) as connection:
        connection.execute("DROP TRIGGER fail_test_event")
    authority.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )
    assert authority.ledger.event_count() == 1


def test_positive_issue_authorize_and_handoff_all_require_the_strict_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=3)]
    allowed_dir = tmp_path / "allowed"
    blocked_dir = tmp_path / "blocked"
    allowed_dir.mkdir()
    blocked_dir.mkdir()
    allowed, private_key, _rp, credential = _authority(allowed_dir, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = allowed.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    handoff = allowed.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )

    gate_calls = 0

    def blocked_gate() -> object:
        nonlocal gate_calls
        gate_calls += 1
        raise ExactFourAuthorityPending("strict all-P0 finding gate is OPEN")

    blocked, _blocked_private, _blocked_rp, _blocked_credential = _authority(
        blocked_dir,
        now_box,
        positive_gate=blocked_gate,
    )
    with pytest.raises(ExactFourAuthorityPending, match="all-P0"):
        blocked.issue_challenge(ready)
    with pytest.raises(ExactFourAuthorityPending, match="all-P0"):
        blocked.authorize(
            readiness=ready,
            challenge=challenge,
            assertion_raw=_canonical(assertion),
        )
    trader_side, controlled_side = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    try:
        with pytest.raises(ExactFourAuthorityPending, match="all-P0"):
            blocked.send_handoff(trader_side, handoff)
    finally:
        trader_side.close()
        controlled_side.close()
    assert gate_calls == 3
    assert blocked.ledger.event_count() == 0


def test_public_live_opener_is_observation_only_not_a_positive_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=2)]
    observed, _private, _rp, _credential = _authority(
        tmp_path,
        now_box,
        server_bound=False,
    )
    seen: list[bool] = []

    def fake_loader(*, server_bound: bool) -> Any:
        seen.append(server_bound)
        return observed

    monkeypatch.setattr(
        trader_authority_module,
        "_load_live_exact_four_trader_authority_v2",
        fake_loader,
    )
    returned = trader_authority_module.open_live_exact_four_trader_authority_v2()
    assert returned is observed
    assert seen == [False]
    with pytest.raises(ExactFourAuthorityPending, match="AuthorityServer"):
        returned.issue_challenge(object())  # type: ignore[arg-type]
