"""Behavior tests for verified, one-use WebAuthn registration enrollment."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import pytest

from execution.exact_four_codec import canonical_authority_digest
from execution.trader_webauthn_authority_v2 import ExactFourTraderRelyingPartyV2
from execution.trader_webauthn_enrollment_v2 import (
    TRADER_ENROLLMENT_HUMAN_ACTION,
    TRADER_REGISTRATION_RESPONSE_FORMAT,
    TraderWebAuthnEnrollmentV2Error,
    build_trader_root_activation_proposal_v2,
    build_trader_webauthn_enrollment_request_v2,
)


ROOT = Path(__file__).resolve().parents[1]


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _cbor_head(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([(major << 5) | value])
    if value <= 0xFF:
        return bytes([(major << 5) | 24, value])
    if value <= 0xFFFF:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")


def _cbor(value: Any) -> bytes:
    if type(value) is int:
        return (
            _cbor_head(0, value)
            if value >= 0
            else _cbor_head(1, -1 - value)
        )
    if type(value) is bytes:
        return _cbor_head(2, len(value)) + value
    if type(value) is str:
        raw = value.encode("utf-8")
        return _cbor_head(3, len(raw)) + raw
    if type(value) is list:
        return _cbor_head(4, len(value)) + b"".join(_cbor(item) for item in value)
    if type(value) is dict:
        return _cbor_head(5, len(value)) + b"".join(
            _cbor(key) + _cbor(item) for key, item in value.items()
        )
    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if value is None:
        return b"\xf6"
    raise TypeError(f"unsupported test CBOR value: {type(value)!r}")


def _rp(now: datetime) -> ExactFourTraderRelyingPartyV2:
    return ExactFourTraderRelyingPartyV2(
        environment="staging",
        policy_id="exact-four-trader-staging-rp/v2",
        policy_generation=1,
        rp_id="trader.staging.quant-platform.local",
        origin="https://pilot.trader.staging.quant-platform.local",
        effective_at=(now - timedelta(days=1)).isoformat(),
    )


def _request(now: datetime, ledger: Path, *, ttl_seconds: int = 300) -> bytes:
    return build_trader_webauthn_enrollment_request_v2(
        environment="staging",
        relying_party=_rp(now),
        counter_mode="COUNTING",
        enrollment_ledger_path=ledger,
        created_at=now,
        ttl_seconds=ttl_seconds,
    )


def _registration(
    request: dict[str, Any],
    *,
    private_key: ec.EllipticCurvePrivateKey | None = None,
    challenge: str | None = None,
    origin: str | None = None,
    client_type: str = "webauthn.create",
    cross_origin: bool = False,
    rp_id: str | None = None,
    flags: int = 0x45,
    cose_algorithm: int = -7,
    raw_id: bytes = b"c" * 32,
    attested_id: bytes | None = None,
    trailing_auth_data: bytes = b"",
) -> tuple[bytes, ec.EllipticCurvePrivateKey]:
    key = private_key or ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    client = {
        "type": client_type,
        "challenge": challenge or request["challenge_base64url"],
        "origin": origin or request["origin"],
        "crossOrigin": cross_origin,
    }
    client_raw = json.dumps(
        client, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    credential_id = attested_id or raw_id
    cose = {
        1: 2,
        3: cose_algorithm,
        -1: 1,
        -2: numbers.x.to_bytes(32, "big"),
        -3: numbers.y.to_bytes(32, "big"),
    }
    auth_data = (
        hashlib.sha256((rp_id or request["rp_id"]).encode("utf-8")).digest()
        + bytes([flags])
        + (7).to_bytes(4, "big")
        + b"\x00" * 16
        + len(credential_id).to_bytes(2, "big")
        + credential_id
        + _cbor(cose)
        + trailing_auth_data
    )
    attestation = _cbor(
        {"fmt": "none", "attStmt": {}, "authData": auth_data}
    )
    output = {
        "format": TRADER_REGISTRATION_RESPONSE_FORMAT,
        "request_id": request["request_id"],
        "id": _b64url(raw_id),
        "rawId": _b64url(raw_id),
        "type": "public-key",
        "authenticatorAttachment": "platform",
        "response": {
            "clientDataJSON": _b64url(client_raw),
            "attestationObject": _b64url(attestation),
            "transports": ["internal"],
        },
        "clientExtensionResults": {},
    }
    return (
        json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        key,
    )


def _proposal(
    request_raw: bytes,
    response_raw: bytes,
    ledger: Path,
    generated_at: datetime,
) -> bytes:
    return build_trader_root_activation_proposal_v2(
        request_raw,
        response_raw,
        enrollment_ledger_path=ledger,
        service_uid=5011,
        controlled_execution_uid=5012,
        controlled_execution_socket_path=Path(
            "/var/run/quant-platform/staging/controlled_execution.sock"
        ),
        store_path=Path(
            "/var/lib/quant-platform/staging/trader/authority-events.sqlite3"
        ),
        generated_at=generated_at,
    )


def test_request_is_random_expiring_public_only_and_durably_recorded(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    first = json.loads(_request(now, ledger))
    second = json.loads(_request(now, ledger))
    assert ledger.is_file()
    assert first["challenge_base64url"] != second["challenge_base64url"]
    assert first["user_handle_base64url"] != second["user_handle_base64url"]
    assert datetime.fromisoformat(first["expires_at"]) - datetime.fromisoformat(
        first["created_at"]
    ) == timedelta(minutes=5)
    assert first["rp_id"] == "trader.staging.quant-platform.local"
    assert first["origin"] == "https://pilot.trader.staging.quant-platform.local"
    assert first["counter_mode"] == "COUNTING"
    assert first["user_presence_required"] is True
    assert first["user_verification"] == "required"
    assert first["private_credential_export_allowed"] is False
    assert first["next_human_action"] == TRADER_ENROLLMENT_HUMAN_ACTION
    assert "response.attestationObject" in first[
        "expected_registration_outputs"
    ]
    assert "public_key_spki_der_base64" not in first[
        "expected_registration_outputs"
    ]


def test_raw_registration_derives_key_and_binds_transcript_into_activation(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    request_raw = _request(now, ledger)
    response_raw, private_key = _registration(json.loads(request_raw))
    proposal = json.loads(
        _proposal(request_raw, response_raw, ledger, now + timedelta(seconds=1))
    )
    activation = proposal["root_activation_document"]
    transcript = proposal["registration_transcript"]
    expected_public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    credential = activation["credential_registry"]["credentials"][0]
    assert base64.b64decode(credential["public_key_spki_der_base64"]) == (
        expected_public_der
    )
    assert credential["initial_sign_count"] == 7
    assert credential["counter_mode"] == "COUNTING"
    assert transcript["user_presence_verified"] is True
    assert transcript["user_verification_verified"] is True
    assert activation["enrollment_transcript_digest"] == transcript[
        "transcript_digest"
    ]
    assert activation["human_enrollment_observed"] is True
    assert activation["protected_store_observed"] is False
    assert proposal["root_activation_document_digest"] == canonical_authority_digest(
        activation
    )
    body = dict(proposal)
    assert body.pop("proposal_digest") == canonical_authority_digest(body)
    assert proposal["private_credential_material_obtained"] is False


def test_same_verified_registration_can_be_consumed_only_once(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    request_raw = _request(now, ledger)
    response_raw, _ = _registration(json.loads(request_raw))
    _proposal(request_raw, response_raw, ledger, now + timedelta(seconds=1))
    with pytest.raises(TraderWebAuthnEnrollmentV2Error, match="consumed"):
        _proposal(request_raw, response_raw, ledger, now + timedelta(seconds=2))


def test_concurrent_registration_proposals_have_one_winner(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    request_raw = _request(now, ledger)
    response_raw, _ = _registration(json.loads(request_raw))

    def attempt() -> str:
        try:
            _proposal(request_raw, response_raw, ledger, now + timedelta(seconds=1))
            return "COMMITTED"
        except TraderWebAuthnEnrollmentV2Error:
            return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["COMMITTED", "REJECTED"]


def test_expired_registration_request_is_rejected(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    request_raw = _request(now, ledger, ttl_seconds=60)
    response_raw, _ = _registration(json.loads(request_raw))
    with pytest.raises(TraderWebAuthnEnrollmentV2Error, match="not current"):
        _proposal(request_raw, response_raw, ledger, now + timedelta(seconds=61))


@pytest.mark.parametrize(
    ("attack", "changes"),
    (
        ("challenge", {"challenge": _b64url(b"x" * 32)}),
        ("origin", {"origin": "https://attacker.invalid"}),
        ("type", {"client_type": "webauthn.get"}),
        ("cross-origin", {"cross_origin": True}),
        ("rp-id", {"rp_id": "attacker.invalid"}),
        ("missing-up", {"flags": 0x44}),
        ("missing-uv", {"flags": 0x41}),
        ("wrong-cose-alg", {"cose_algorithm": -257}),
        ("raw-id-mismatch", {"attested_id": b"d" * 32}),
        ("trailing-auth-data", {"trailing_auth_data": b"\x00"}),
    ),
)
def test_registration_rejects_unverified_client_authenticator_or_cose_data(
    tmp_path: Path,
    attack: str,
    changes: dict[str, Any],
) -> None:
    del attack
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    request_raw = _request(now, ledger)
    response_raw, _ = _registration(json.loads(request_raw), **changes)
    with pytest.raises(TraderWebAuthnEnrollmentV2Error):
        _proposal(request_raw, response_raw, ledger, now + timedelta(seconds=1))


def test_old_self_attested_public_key_json_has_no_happy_path(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    ledger = (tmp_path / "enrollment.sqlite3").resolve()
    request_raw = _request(now, ledger)
    old_output = {
        "format": "exact-four-trader-webauthn-ceremony-public-output/v2",
        "request_id": json.loads(request_raw)["request_id"],
        "status": "HUMAN_PRESENCE_AND_USER_VERIFICATION_OBSERVED",
        "credential_id_base64url": _b64url(b"c" * 32),
        "public_key_spki_der_base64": base64.b64encode(b"caller-key").decode(),
        "counter_mode": "COUNTING",
        "initial_sign_count": 0,
    }
    with pytest.raises(TraderWebAuthnEnrollmentV2Error, match="wrapper"):
        _proposal(
            request_raw,
            json.dumps(old_output).encode(),
            ledger,
            now + timedelta(seconds=1),
        )


def test_cli_prints_request_and_writes_only_expiring_ledger(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    enrollment_ledger = (tmp_path / "enrollment.sqlite3").resolve()
    activation_path = Path(
        "/etc/quant-platform/authorities/trader/activation.json"
    )
    before = (
        (activation_path.lstat(), activation_path.read_bytes())
        if activation_path.exists()
        else None
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "scripts/trader_webauthn_enrollment.py",
            "request",
            "--environment",
            "staging",
            "--policy-id",
            "exact-four-trader-staging-rp/v2",
            "--policy-generation",
            "1",
            "--rp-id",
            "trader.staging.quant-platform.local",
            "--origin",
            "https://pilot.trader.staging.quant-platform.local",
            "--rp-effective-at",
            (now - timedelta(days=1)).isoformat(),
            "--counter-mode",
            "COUNTING",
            "--enrollment-ledger",
            str(enrollment_ledger),
            "--created-at",
            now.isoformat(),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "HUMAN_CEREMONY_REQUIRED"
    assert output["next_human_action"] == TRADER_ENROLLMENT_HUMAN_ACTION
    assert enrollment_ledger.is_file()
    after = (
        (activation_path.lstat(), activation_path.read_bytes())
        if activation_path.exists()
        else None
    )
    assert after == before
