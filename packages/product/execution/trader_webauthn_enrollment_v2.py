"""Machine-readable, non-activating WebAuthn enrollment proposals.

This module deliberately stops on both sides of the human ceremony.  It emits
public WebAuthn creation parameters for a browser/OS prompt, then validates only
the public ceremony output (credential id and P-256 SPKI) and emits a root
review proposal.  It never obtains a credential private key, writes under
``/etc``, marks a protected store observed, or starts a positive Trader
authority operation.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    _canonical_bytes,
    _parsed_timestamp,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import _decode_canonical_base64url
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyV2,
)


TRADER_ENROLLMENT_REQUEST_FORMAT = "exact-four-trader-enrollment-request/v2"
TRADER_CEREMONY_PUBLIC_OUTPUT_FORMAT = (
    "exact-four-trader-webauthn-ceremony-public-output/v2"
)
TRADER_ACTIVATION_PROPOSAL_FORMAT = (
    "exact-four-trader-root-activation-proposal/v2"
)
TRADER_ENROLLMENT_HUMAN_ACTION = (
    "RUN_BROWSER_OR_OS_WEBAUTHN_CREATE_WITH_HUMAN_PRESENCE"
)
_PUBLIC_OUTPUT_FIELDS = (
    "credential_id_base64url",
    "public_key_spki_der_base64",
    "counter_mode",
    "initial_sign_count",
    "ceremony_observed_at",
)


class TraderWebAuthnEnrollmentV2Error(ExactFourAuthorityContractError):
    """An enrollment request or public ceremony proposal was unsafe."""


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _utc_text(value: datetime, label: str) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TraderWebAuthnEnrollmentV2Error(
            f"{label} must be an exact aware datetime"
        )
    return value.astimezone(timezone.utc).isoformat()


def build_trader_webauthn_enrollment_request_v2(
    *,
    environment: str,
    relying_party: ExactFourTraderRelyingPartyV2,
    created_at: datetime,
) -> bytes:
    """Emit creation parameters; the human browser/OS ceremony remains external."""

    if environment not in {"staging", "production"}:
        raise TraderWebAuthnEnrollmentV2Error(
            "enrollment request environment must be staging or production"
        )
    if (
        type(relying_party) is not ExactFourTraderRelyingPartyV2
        or relying_party.environment != environment
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "enrollment request requires the exact governed environment RP"
        )
    relying_party.__post_init__()
    body = {
        "format": TRADER_ENROLLMENT_REQUEST_FORMAT,
        "environment": environment,
        "status": "HUMAN_CEREMONY_REQUIRED",
        "request_id": str(uuid.uuid4()),
        "rp_policy_id": relying_party.policy_id,
        "rp_policy_generation": relying_party.policy_generation,
        "rp_policy_digest": relying_party.policy_digest,
        "rp_id": relying_party.rp_id,
        "origin": relying_party.origin,
        "challenge_base64url": _b64url(secrets.token_bytes(32)),
        "user_handle_base64url": _b64url(secrets.token_bytes(32)),
        "user_name": "quant-platform-trader-human",
        "credential_algorithm": "ES256",
        "cose_algorithm": -7,
        "attestation_preference": "none",
        "resident_key": "required",
        "user_presence_required": True,
        "user_verification": "required",
        "private_credential_export_allowed": False,
        "next_human_action": TRADER_ENROLLMENT_HUMAN_ACTION,
        "expected_public_outputs": list(_PUBLIC_OUTPUT_FIELDS),
        "rp_effective_at": relying_party.effective_at,
        "created_at": _utc_text(created_at, "enrollment request created_at"),
    }
    return _canonical_bytes(
        {**body, "request_digest": canonical_authority_digest(body)}
    )


def _parse_enrollment_request(raw: bytes | str) -> dict[str, Any]:
    document = _strict_json_loads(raw, label="Trader enrollment request")
    expected = {
        "format",
        "environment",
        "status",
        "request_id",
        "rp_policy_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "rp_id",
        "origin",
        "challenge_base64url",
        "user_handle_base64url",
        "user_name",
        "credential_algorithm",
        "cose_algorithm",
        "attestation_preference",
        "resident_key",
        "user_presence_required",
        "user_verification",
        "private_credential_export_allowed",
        "next_human_action",
        "expected_public_outputs",
        "rp_effective_at",
        "created_at",
        "request_digest",
    }
    body = dict(document)
    declared_digest = body.pop("request_digest", None)
    if (
        set(document) != expected
        or document.get("format") != TRADER_ENROLLMENT_REQUEST_FORMAT
        or document.get("environment") not in {"staging", "production"}
        or document.get("status") != "HUMAN_CEREMONY_REQUIRED"
        or document.get("credential_algorithm") != "ES256"
        or document.get("cose_algorithm") != -7
        or document.get("attestation_preference") != "none"
        or document.get("resident_key") != "required"
        or document.get("user_presence_required") is not True
        or document.get("user_verification") != "required"
        or document.get("private_credential_export_allowed") is not False
        or document.get("next_human_action") != TRADER_ENROLLMENT_HUMAN_ACTION
        or document.get("expected_public_outputs") != list(_PUBLIC_OUTPUT_FIELDS)
        or declared_digest != canonical_authority_digest(body)
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "Trader enrollment request identity or digest is invalid"
        )
    _decode_canonical_base64url(
        document["challenge_base64url"],
        label="enrollment challenge",
        minimum_bytes=32,
        maximum_bytes=32,
    )
    _decode_canonical_base64url(
        document["user_handle_base64url"],
        label="enrollment user handle",
        minimum_bytes=32,
        maximum_bytes=32,
    )
    _parsed_timestamp(document["created_at"], "enrollment request created_at")
    return document


def build_trader_root_activation_proposal_v2(
    enrollment_request_raw: bytes | str,
    ceremony_public_output_raw: bytes | str,
    *,
    service_uid: int,
    controlled_execution_uid: int,
    controlled_execution_socket_path: Path,
    store_path: Path,
    generated_at: datetime,
) -> bytes:
    """Validate public ceremony material and emit a non-activating root proposal."""

    request = _parse_enrollment_request(enrollment_request_raw)
    ceremony = _strict_json_loads(
        ceremony_public_output_raw,
        label="Trader WebAuthn ceremony public output",
    )
    expected_ceremony = {
        "format",
        "request_id",
        "status",
        "credential_id_base64url",
        "public_key_spki_der_base64",
        "credential_algorithm",
        "counter_mode",
        "initial_sign_count",
        "ceremony_observed_at",
        "authenticator_attachment",
        "private_credential_exported",
    }
    if (
        set(ceremony) != expected_ceremony
        or ceremony.get("format") != TRADER_CEREMONY_PUBLIC_OUTPUT_FORMAT
        or ceremony.get("request_id") != request["request_id"]
        or ceremony.get("status")
        != "HUMAN_PRESENCE_AND_USER_VERIFICATION_OBSERVED"
        or ceremony.get("credential_algorithm") != "ES256"
        or ceremony.get("counter_mode") not in {"COUNTING", "COUNTERLESS"}
        or ceremony.get("authenticator_attachment")
        not in {"platform", "cross-platform"}
        or ceremony.get("private_credential_exported") is not False
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "ceremony output must be exact public material from a human-present prompt"
        )
    observed_at = _parsed_timestamp(
        ceremony["ceremony_observed_at"], "ceremony observed_at"
    ).astimezone(timezone.utc)
    generated = datetime.fromisoformat(_utc_text(generated_at, "proposal generated_at"))
    if observed_at > generated:
        raise TraderWebAuthnEnrollmentV2Error(
            "ceremony observation cannot be after proposal generation"
        )
    credential_id = _decode_canonical_base64url(
        ceremony["credential_id_base64url"],
        label="enrolled credential id",
        minimum_bytes=16,
        maximum_bytes=1024,
    )
    key_text = ceremony["public_key_spki_der_base64"]
    if type(key_text) is not str or not key_text:
        raise TraderWebAuthnEnrollmentV2Error("enrolled public SPKI is missing")
    try:
        key_bytes = base64.b64decode(key_text, validate=True)
        if base64.b64encode(key_bytes).decode("ascii") != key_text:
            raise ValueError("non-canonical SPKI base64")
        public_key = serialization.load_der_public_key(key_bytes)
    except (TypeError, ValueError) as exc:
        raise TraderWebAuthnEnrollmentV2Error(
            "enrolled public SPKI is not canonical DER base64"
        ) from exc
    relying_party = ExactFourTraderRelyingPartyV2(
        environment=request["environment"],
        policy_id=request["rp_policy_id"],
        policy_generation=request["rp_policy_generation"],
        rp_id=request["rp_id"],
        origin=request["origin"],
        effective_at=request["rp_effective_at"],
    )
    if relying_party.policy_digest != request["rp_policy_digest"]:
        raise TraderWebAuthnEnrollmentV2Error(
            "enrollment request RP policy digest changed"
        )
    credential = ExactFourTraderCredentialV2(
        environment=request["environment"],
        credential_id=credential_id,
        public_key=public_key,  # type: ignore[arg-type]
        rp_policy_digest=relying_party.policy_digest,
        effective_at=ceremony["ceremony_observed_at"],
        initial_sign_count=ceremony["initial_sign_count"],
        counter_mode=ceremony["counter_mode"],
    )
    if (
        type(service_uid) is not int
        or service_uid <= 0
        or type(controlled_execution_uid) is not int
        or controlled_execution_uid <= 0
        or service_uid == controlled_execution_uid
        or not isinstance(controlled_execution_socket_path, Path)
        or not controlled_execution_socket_path.is_absolute()
        or not isinstance(store_path, Path)
        or not store_path.is_absolute()
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "activation proposal principal UIDs and protected paths are invalid"
        )
    rp_row = relying_party.to_dict()
    rp_row.pop("format")
    credential_row = {
        "environment": credential.environment,
        "credential_id_base64url": credential.credential_id_base64url,
        "public_key_spki_der_base64": key_text,
        "rp_policy_digest": credential.rp_policy_digest,
        "effective_at": credential.effective_at,
        "initial_sign_count": credential.initial_sign_count,
        "counter_mode": credential.counter_mode,
        "status": credential.status,
        "algorithm": credential.algorithm,
        "key_backend": credential.key_backend,
    }
    root_activation_document = {
        "format": "exact-four-trader-authority-activation/v2",
        "environment": request["environment"],
        "service_uid": service_uid,
        "controlled_execution_uid": controlled_execution_uid,
        "controlled_execution_socket_path": str(controlled_execution_socket_path),
        "store_path": str(store_path),
        "human_enrollment_observed": True,
        # A root administrator must provision and inspect the store before
        # changing this to true in the separately installed activation file.
        "protected_store_observed": False,
        "rp_registry": {"generation": 1, "entries": [rp_row]},
        "credential_registry": {
            "registry_id": "exact-four-trader-webauthn-credentials/v2",
            "generation": 1,
            "credentials": [credential_row],
        },
    }
    root_activation_digest = canonical_authority_digest(root_activation_document)
    request_raw = _canonical_bytes(request)
    ceremony_raw = _canonical_bytes(ceremony)
    proposal_body = {
        "format": TRADER_ACTIVATION_PROPOSAL_FORMAT,
        "status": "ROOT_REVIEW_REQUIRED",
        "environment": request["environment"],
        "enrollment_request_digest": _sha256_bytes(request_raw),
        "ceremony_public_output_digest": _sha256_bytes(ceremony_raw),
        "root_activation_document": root_activation_document,
        "root_activation_document_digest": root_activation_digest,
        "private_credential_material_obtained": False,
        "human_presence_required_for_only_external_step": True,
        "next_admin_actions": [
            "verify the browser/OS ceremony transcript and public credential",
            "provision the dedicated Trader principal and mode-0700 store",
            "verify the controlled_execution AF_UNIX peer and UID",
            "install a root-owned non-group/world-writable activation document",
            "set protected_store_observed true only after direct inspection",
            "leave all positive operations blocked until the strict P0 gate closes",
        ],
        "expected_activation_outputs": [
            "root-owned activation.json",
            "dedicated Trader service UID",
            "mode-0700 Trader ledger directory",
            "public-only P-256 credential registry",
            "no Trader file-backed private signing key",
        ],
        "generated_at": _utc_text(generated_at, "proposal generated_at"),
    }
    return _canonical_bytes(
        {**proposal_body, "proposal_digest": canonical_authority_digest(proposal_body)}
    )


__all__ = [
    "TRADER_ACTIVATION_PROPOSAL_FORMAT",
    "TRADER_CEREMONY_PUBLIC_OUTPUT_FORMAT",
    "TRADER_ENROLLMENT_HUMAN_ACTION",
    "TRADER_ENROLLMENT_REQUEST_FORMAT",
    "TraderWebAuthnEnrollmentV2Error",
    "build_trader_root_activation_proposal_v2",
    "build_trader_webauthn_enrollment_request_v2",
]
