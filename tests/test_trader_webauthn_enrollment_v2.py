"""Behavior tests for the non-activating Trader WebAuthn enrollment CLI."""

from __future__ import annotations

import base64
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import pytest

from execution.exact_four_codec import canonical_authority_digest
from execution.trader_webauthn_authority_v2 import ExactFourTraderRelyingPartyV2
from execution.trader_webauthn_enrollment_v2 import (
    TRADER_CEREMONY_PUBLIC_OUTPUT_FORMAT,
    TRADER_ENROLLMENT_HUMAN_ACTION,
    TraderWebAuthnEnrollmentV2Error,
    build_trader_root_activation_proposal_v2,
    build_trader_webauthn_enrollment_request_v2,
)


ROOT = Path(__file__).resolve().parents[1]


def _rp(now: datetime) -> ExactFourTraderRelyingPartyV2:
    return ExactFourTraderRelyingPartyV2(
        environment="staging",
        policy_id="exact-four-trader-staging-rp/v2",
        policy_generation=1,
        rp_id="trader.staging.quant-platform.local",
        origin="https://pilot.trader.staging.quant-platform.local",
        effective_at=(now - timedelta(days=1)).isoformat(),
    )


def _request(now: datetime) -> bytes:
    return build_trader_webauthn_enrollment_request_v2(
        environment="staging",
        relying_party=_rp(now),
        created_at=now,
    )


def _ceremony(request: dict[str, object], now: datetime) -> bytes:
    public_key = ec.generate_private_key(ec.SECP256R1()).public_key()
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    output = {
        "format": TRADER_CEREMONY_PUBLIC_OUTPUT_FORMAT,
        "request_id": request["request_id"],
        "status": "HUMAN_PRESENCE_AND_USER_VERIFICATION_OBSERVED",
        "credential_id_base64url": base64.urlsafe_b64encode(b"c" * 32)
        .decode("ascii")
        .rstrip("="),
        "public_key_spki_der_base64": base64.b64encode(public_der).decode("ascii"),
        "credential_algorithm": "ES256",
        "counter_mode": "COUNTING",
        "initial_sign_count": 0,
        "ceremony_observed_at": now.isoformat(),
        "authenticator_attachment": "platform",
        "private_credential_exported": False,
    }
    return json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_request_is_random_public_only_and_names_the_single_human_action() -> None:
    now = datetime.now(timezone.utc)
    first = json.loads(_request(now))
    second = json.loads(_request(now))
    assert first["challenge_base64url"] != second["challenge_base64url"]
    assert first["user_handle_base64url"] != second["user_handle_base64url"]
    for field in ("challenge_base64url", "user_handle_base64url"):
        raw = base64.urlsafe_b64decode(first[field] + "=" * (-len(first[field]) % 4))
        assert len(raw) == 32
    assert first["rp_id"] == "trader.staging.quant-platform.local"
    assert first["origin"] == "https://pilot.trader.staging.quant-platform.local"
    assert first["user_presence_required"] is True
    assert first["user_verification"] == "required"
    assert first["private_credential_export_allowed"] is False
    assert first["next_human_action"] == TRADER_ENROLLMENT_HUMAN_ACTION
    assert first["expected_public_outputs"] == [
        "credential_id_base64url",
        "public_key_spki_der_base64",
        "counter_mode",
        "initial_sign_count",
        "ceremony_observed_at",
    ]


def test_public_ceremony_material_yields_digest_bound_nonactivating_root_proposal() -> None:
    now = datetime.now(timezone.utc)
    request_raw = _request(now)
    request = json.loads(request_raw)
    ceremony_raw = _ceremony(request, now + timedelta(seconds=1))
    proposal_raw = build_trader_root_activation_proposal_v2(
        request_raw,
        ceremony_raw,
        service_uid=5011,
        controlled_execution_uid=5012,
        controlled_execution_socket_path=Path(
            "/var/run/quant-platform/staging/controlled_execution.sock"
        ),
        store_path=Path(
            "/var/lib/quant-platform/staging/trader/authority-events.sqlite3"
        ),
        generated_at=now + timedelta(seconds=2),
    )
    proposal = json.loads(proposal_raw)
    activation = proposal["root_activation_document"]
    assert proposal["status"] == "ROOT_REVIEW_REQUIRED"
    assert proposal["private_credential_material_obtained"] is False
    assert proposal["human_presence_required_for_only_external_step"] is True
    assert activation["human_enrollment_observed"] is True
    assert activation["protected_store_observed"] is False
    assert activation["credential_registry"]["credentials"][0][
        "credential_id_base64url"
    ]
    assert activation["credential_registry"]["credentials"][0][
        "public_key_spki_der_base64"
    ]
    assert proposal["root_activation_document_digest"] == canonical_authority_digest(
        activation
    )
    body = dict(proposal)
    declared = body.pop("proposal_digest")
    assert declared == canonical_authority_digest(body)
    assert "no Trader file-backed private signing key" in proposal[
        "expected_activation_outputs"
    ]


@pytest.mark.parametrize("attack", ["private_field", "private_export", "wrong_key"])
def test_proposal_rejects_private_material_or_non_p256_public_output(
    attack: str,
) -> None:
    now = datetime.now(timezone.utc)
    request_raw = _request(now)
    ceremony = json.loads(_ceremony(json.loads(request_raw), now))
    if attack == "private_field":
        ceremony["private_key_base64"] = "must-never-be-accepted"
    elif attack == "private_export":
        ceremony["private_credential_exported"] = True
    else:
        ceremony["public_key_spki_der_base64"] = base64.b64encode(
            b"not-a-public-key"
        ).decode("ascii")
    ceremony_raw = json.dumps(
        ceremony, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with pytest.raises(TraderWebAuthnEnrollmentV2Error):
        build_trader_root_activation_proposal_v2(
            request_raw,
            ceremony_raw,
            service_uid=5011,
            controlled_execution_uid=5012,
            controlled_execution_socket_path=Path(
                "/var/run/quant-platform/staging/controlled_execution.sock"
            ),
            store_path=Path("/var/lib/quant-platform/staging/trader/events.sqlite3"),
            generated_at=now + timedelta(seconds=1),
        )


def test_cli_prints_request_without_writing_activation_state() -> None:
    now = datetime.now(timezone.utc)
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
    after = (
        (activation_path.lstat(), activation_path.read_bytes())
        if activation_path.exists()
        else None
    )
    assert after == before
