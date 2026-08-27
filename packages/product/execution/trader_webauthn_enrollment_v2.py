"""Verified, non-activating WebAuthn registration and root proposal flow.

The only external step is a browser/OS ``navigator.credentials.create`` call
with human presence.  Product code accepts the raw registration response,
parses its CBOR authenticator data, derives the ES256 public key itself, and
atomically consumes the expiring challenge before emitting a root-review
proposal.  No private credential material or caller-asserted public key is
accepted.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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
from execution.trader_webauthn_enrollment_ledger_v2 import (
    ENROLLMENT_LEDGER_BACKEND,
    SQLiteTraderWebAuthnEnrollmentLedgerV2,
    TraderWebAuthnEnrollmentLedgerV2Error,
)


TRADER_ENROLLMENT_REQUEST_FORMAT = "exact-four-trader-enrollment-request/v2"
TRADER_REGISTRATION_RESPONSE_FORMAT = (
    "exact-four-trader-webauthn-registration-response/v2"
)
TRADER_REGISTRATION_TRANSCRIPT_FORMAT = (
    "exact-four-trader-webauthn-registration-transcript/v2"
)
TRADER_ACTIVATION_PROPOSAL_FORMAT = (
    "exact-four-trader-root-activation-proposal/v2"
)
TRADER_ENROLLMENT_HUMAN_ACTION = (
    "RUN_BROWSER_OR_OS_WEBAUTHN_CREATE_WITH_HUMAN_PRESENCE"
)
_EXPECTED_REGISTRATION_OUTPUTS = (
    "id",
    "rawId",
    "type",
    "authenticatorAttachment",
    "response.clientDataJSON",
    "response.attestationObject",
    "response.transports",
    "clientExtensionResults",
)
_MIN_REQUEST_TTL_SECONDS = 60
_MAX_REQUEST_TTL_SECONDS = 900
_FLAG_UP = 0x01
_FLAG_UV = 0x04
_FLAG_BE = 0x08
_FLAG_BS = 0x10
_FLAG_AT = 0x40
_ALLOWED_AUTH_DATA_FLAGS = _FLAG_UP | _FLAG_UV | _FLAG_BE | _FLAG_BS | _FLAG_AT


class TraderWebAuthnEnrollmentV2Error(ExactFourAuthorityContractError):
    """A WebAuthn registration transcript or proposal was unsafe."""


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


def _read_cbor_length(data: bytes, offset: int, additional: int) -> tuple[int, int]:
    if additional < 24:
        return additional, offset
    widths = {24: 1, 25: 2, 26: 4, 27: 8}
    width = widths.get(additional)
    if width is None or offset + width > len(data):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn CBOR uses an indefinite, truncated, or reserved length"
        )
    value = int.from_bytes(data[offset : offset + width], "big")
    minimum = {1: 24, 2: 256, 4: 65_536, 8: 4_294_967_296}[width]
    if value < minimum:
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn CBOR length or integer is not canonically encoded"
        )
    return value, offset + width


def _decode_cbor_item(
    data: bytes, offset: int = 0, *, depth: int = 0
) -> tuple[Any, int]:
    if depth > 8 or offset >= len(data):
        raise TraderWebAuthnEnrollmentV2Error("WebAuthn CBOR is truncated or too deep")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    additional = initial & 0x1F
    if major in {0, 1}:
        value, offset = _read_cbor_length(data, offset, additional)
        return (value if major == 0 else -1 - value), offset
    if major in {2, 3}:
        length, offset = _read_cbor_length(data, offset, additional)
        end = offset + length
        if end > len(data):
            raise TraderWebAuthnEnrollmentV2Error("WebAuthn CBOR string is truncated")
        raw = data[offset:end]
        if major == 2:
            return raw, end
        try:
            return raw.decode("utf-8"), end
        except UnicodeDecodeError as exc:
            raise TraderWebAuthnEnrollmentV2Error(
                "WebAuthn CBOR text is not UTF-8"
            ) from exc
    if major == 4:
        length, offset = _read_cbor_length(data, offset, additional)
        if length > 64:
            raise TraderWebAuthnEnrollmentV2Error("WebAuthn CBOR array is too large")
        values: list[Any] = []
        for _ in range(length):
            value, offset = _decode_cbor_item(data, offset, depth=depth + 1)
            values.append(value)
        return values, offset
    if major == 5:
        length, offset = _read_cbor_length(data, offset, additional)
        if length > 64:
            raise TraderWebAuthnEnrollmentV2Error("WebAuthn CBOR map is too large")
        result: dict[Any, Any] = {}
        for _ in range(length):
            key, offset = _decode_cbor_item(data, offset, depth=depth + 1)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise TraderWebAuthnEnrollmentV2Error(
                    "WebAuthn CBOR map key is not scalar"
                ) from exc
            if duplicate:
                raise TraderWebAuthnEnrollmentV2Error(
                    "WebAuthn CBOR map contains a duplicate key"
                )
            value, offset = _decode_cbor_item(data, offset, depth=depth + 1)
            result[key] = value
        return result, offset
    if major == 7 and additional in {20, 21, 22}:
        return {20: False, 21: True, 22: None}[additional], offset
    raise TraderWebAuthnEnrollmentV2Error(
        "WebAuthn CBOR contains an unsupported tag, float, or simple value"
    )


def _decode_one_cbor(raw: bytes, *, label: str) -> Any:
    value, consumed = _decode_cbor_item(raw)
    if consumed != len(raw):
        raise TraderWebAuthnEnrollmentV2Error(f"{label} has trailing CBOR bytes")
    return value


def build_trader_webauthn_enrollment_request_v2(
    *,
    environment: str,
    relying_party: ExactFourTraderRelyingPartyV2,
    counter_mode: str,
    enrollment_ledger_path: Path,
    created_at: datetime,
    ttl_seconds: int = 300,
) -> bytes:
    """Persist and emit one expiring browser/OS creation challenge."""

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
    if counter_mode not in {"COUNTING", "COUNTERLESS"}:
        raise TraderWebAuthnEnrollmentV2Error(
            "enrollment counter policy must be COUNTING or COUNTERLESS"
        )
    if (
        type(ttl_seconds) is not int
        or ttl_seconds < _MIN_REQUEST_TTL_SECONDS
        or ttl_seconds > _MAX_REQUEST_TTL_SECONDS
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "enrollment request TTL must be an exact int in [60, 900]"
        )
    relying_party.__post_init__()
    created_text = _utc_text(created_at, "enrollment request created_at")
    expires_text = _utc_text(
        created_at + timedelta(seconds=ttl_seconds),
        "enrollment request expires_at",
    )
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
        "counter_mode": counter_mode,
        "user_presence_required": True,
        "user_verification": "required",
        "private_credential_export_allowed": False,
        "next_human_action": TRADER_ENROLLMENT_HUMAN_ACTION,
        "expected_registration_outputs": list(_EXPECTED_REGISTRATION_OUTPUTS),
        "rp_effective_at": relying_party.effective_at,
        "created_at": created_text,
        "expires_at": expires_text,
        "ledger_backend": ENROLLMENT_LEDGER_BACKEND,
    }
    request = {**body, "request_digest": canonical_authority_digest(body)}
    try:
        SQLiteTraderWebAuthnEnrollmentLedgerV2(enrollment_ledger_path).issue(
            request
        )
    except TraderWebAuthnEnrollmentLedgerV2Error as exc:
        raise TraderWebAuthnEnrollmentV2Error(str(exc)) from exc
    return _canonical_bytes(request)


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
        "counter_mode",
        "user_presence_required",
        "user_verification",
        "private_credential_export_allowed",
        "next_human_action",
        "expected_registration_outputs",
        "rp_effective_at",
        "created_at",
        "expires_at",
        "ledger_backend",
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
        or document.get("counter_mode") not in {"COUNTING", "COUNTERLESS"}
        or document.get("user_presence_required") is not True
        or document.get("user_verification") != "required"
        or document.get("private_credential_export_allowed") is not False
        or document.get("next_human_action") != TRADER_ENROLLMENT_HUMAN_ACTION
        or document.get("expected_registration_outputs")
        != list(_EXPECTED_REGISTRATION_OUTPUTS)
        or document.get("ledger_backend") != ENROLLMENT_LEDGER_BACKEND
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
    created = _parsed_timestamp(
        document["created_at"], "enrollment request created_at"
    )
    expires = _parsed_timestamp(
        document["expires_at"], "enrollment request expires_at"
    )
    ttl = expires - created
    if ttl < timedelta(seconds=60) or ttl > timedelta(seconds=900):
        raise TraderWebAuthnEnrollmentV2Error(
            "Trader enrollment request expiry is not governed"
        )
    return document


def _parse_registration_response(raw: bytes | str) -> dict[str, Any]:
    document = _strict_json_loads(raw, label="Trader WebAuthn registration response")
    if set(document) != {
        "format",
        "request_id",
        "id",
        "rawId",
        "type",
        "authenticatorAttachment",
        "response",
        "clientExtensionResults",
    } or document.get("format") != TRADER_REGISTRATION_RESPONSE_FORMAT:
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn registration response wrapper is not exact"
        )
    response = document.get("response")
    if (
        document.get("type") != "public-key"
        or document.get("authenticatorAttachment")
        not in {"platform", "cross-platform"}
        or document.get("clientExtensionResults") != {}
        or type(response) is not dict
        or set(response) != {
            "clientDataJSON",
            "attestationObject",
            "transports",
        }
        or type(response.get("transports")) is not list
        or any(
            type(item) is not str
            or item not in {"internal", "usb", "nfc", "ble", "hybrid"}
            for item in response.get("transports", [])
        )
        or len(set(response.get("transports", [])))
        != len(response.get("transports", []))
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn registration response fields are not governed"
        )
    raw_id = _decode_canonical_base64url(
        document["rawId"],
        label="registration rawId",
        minimum_bytes=16,
        maximum_bytes=1024,
    )
    if document.get("id") != _b64url(raw_id):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn registration id and rawId differ"
        )
    return document


def _verify_registration_response(
    request: dict[str, Any], registration: dict[str, Any]
) -> dict[str, Any]:
    if registration["request_id"] != request["request_id"]:
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn registration request identity mismatch"
        )
    response = registration["response"]
    client_raw = _decode_canonical_base64url(
        response["clientDataJSON"],
        label="registration clientDataJSON",
        minimum_bytes=2,
        maximum_bytes=16_384,
    )
    client = _strict_json_loads(client_raw, label="registration clientDataJSON")
    if (
        set(client) != {"type", "challenge", "origin", "crossOrigin"}
        or client.get("type") != "webauthn.create"
        or client.get("challenge") != request["challenge_base64url"]
        or client.get("origin") != request["origin"]
        or client.get("crossOrigin") is not False
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn clientDataJSON challenge/type/origin is invalid"
        )
    attestation_raw = _decode_canonical_base64url(
        response["attestationObject"],
        label="registration attestationObject",
        minimum_bytes=64,
        maximum_bytes=65_536,
    )
    attestation = _decode_one_cbor(attestation_raw, label="attestationObject")
    if (
        type(attestation) is not dict
        or set(attestation) != {"fmt", "attStmt", "authData"}
        or attestation.get("fmt") != "none"
        or attestation.get("attStmt") != {}
        or type(attestation.get("authData")) is not bytes
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn attestationObject must be exact none attestation"
        )
    auth_data = attestation["authData"]
    if len(auth_data) < 55:
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn authenticator data is truncated"
        )
    expected_rp_hash = hashlib.sha256(request["rp_id"].encode("utf-8")).digest()
    flags = auth_data[32]
    sign_count = int.from_bytes(auth_data[33:37], "big")
    if (
        auth_data[:32] != expected_rp_hash
        or flags & (_FLAG_UP | _FLAG_UV | _FLAG_AT)
        != (_FLAG_UP | _FLAG_UV | _FLAG_AT)
        or flags & ~_ALLOWED_AUTH_DATA_FLAGS
        or flags & _FLAG_BS and not flags & _FLAG_BE
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn authenticator rpIdHash, UP, UV, AT, or flags are invalid"
        )
    offset = 37
    aaguid = auth_data[offset : offset + 16]
    offset += 16
    credential_length = int.from_bytes(auth_data[offset : offset + 2], "big")
    offset += 2
    if credential_length < 16 or offset + credential_length >= len(auth_data):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn attested credential id length is invalid"
        )
    credential_id = auth_data[offset : offset + credential_length]
    offset += credential_length
    cose, consumed = _decode_cbor_item(auth_data, offset)
    if consumed != len(auth_data):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn authenticator data has extensions or trailing bytes"
        )
    if (
        type(cose) is not dict
        or set(cose) != {1, 3, -1, -2, -3}
        or cose.get(1) != 2
        or cose.get(3) != -7
        or cose.get(-1) != 1
        or type(cose.get(-2)) is not bytes
        or type(cose.get(-3)) is not bytes
        or len(cose[-2]) != 32
        or len(cose[-3]) != 32
    ):
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn credentialPublicKey must be exact COSE ES256"
        )
    try:
        public_key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(cose[-2], "big"),
            int.from_bytes(cose[-3], "big"),
            ec.SECP256R1(),
        ).public_key()
    except ValueError as exc:
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn COSE public point is not on P-256"
        ) from exc
    raw_id = _decode_canonical_base64url(
        registration["rawId"],
        label="registration rawId",
        minimum_bytes=16,
        maximum_bytes=1024,
    )
    if raw_id != credential_id:
        raise TraderWebAuthnEnrollmentV2Error(
            "WebAuthn rawId differs from attested credential id"
        )
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    transcript_body = {
        "format": TRADER_REGISTRATION_TRANSCRIPT_FORMAT,
        "environment": request["environment"],
        "request_digest": request["request_digest"],
        "client_data_json_digest": _sha256_bytes(client_raw),
        "attestation_object_digest": _sha256_bytes(attestation_raw),
        "authenticator_data_digest": _sha256_bytes(auth_data),
        "rp_id": request["rp_id"],
        "origin": request["origin"],
        "credential_id_base64url": _b64url(credential_id),
        "credential_public_key_digest": _sha256_bytes(public_der),
        "aaguid_base64url": _b64url(aaguid),
        "authenticator_flags": flags,
        "attested_sign_count": sign_count,
        "counter_mode": request["counter_mode"],
        "user_presence_verified": True,
        "user_verification_verified": True,
    }
    return {
        "credential_id": credential_id,
        "public_key": public_key,
        "public_key_der": public_der,
        "sign_count": sign_count,
        "transcript": {
            **transcript_body,
            "transcript_digest": canonical_authority_digest(transcript_body),
        },
    }


def build_trader_root_activation_proposal_v2(
    enrollment_request_raw: bytes | str,
    registration_response_raw: bytes | str,
    *,
    enrollment_ledger_path: Path,
    service_uid: int,
    controlled_execution_uid: int,
    controlled_execution_socket_path: Path,
    store_path: Path,
    generated_at: datetime,
) -> bytes:
    """Verify raw WebAuthn bytes, consume the request, and emit root review."""

    request = _parse_enrollment_request(enrollment_request_raw)
    registration = _parse_registration_response(registration_response_raw)
    verified = _verify_registration_response(request, registration)
    generated_text = _utc_text(generated_at, "proposal generated_at")
    generated = datetime.fromisoformat(generated_text)
    created = _parsed_timestamp(request["created_at"], "request created_at")
    expires = _parsed_timestamp(request["expires_at"], "request expires_at")
    if generated < created or generated > expires:
        raise TraderWebAuthnEnrollmentV2Error(
            "enrollment request is not current at proposal generation"
        )
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
        credential_id=verified["credential_id"],
        public_key=verified["public_key"],
        rp_policy_digest=relying_party.policy_digest,
        effective_at=generated_text,
        initial_sign_count=verified["sign_count"],
        counter_mode=request["counter_mode"],
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
    key_text = base64.b64encode(verified["public_key_der"]).decode("ascii")
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
    transcript = verified["transcript"]
    root_activation_document = {
        "format": "exact-four-trader-authority-activation/v2",
        "environment": request["environment"],
        "service_uid": service_uid,
        "controlled_execution_uid": controlled_execution_uid,
        "controlled_execution_socket_path": str(controlled_execution_socket_path),
        "store_path": str(store_path),
        "human_enrollment_observed": True,
        "protected_store_observed": False,
        "enrollment_transcript_digest": transcript["transcript_digest"],
        "rp_registry": {"generation": 1, "entries": [rp_row]},
        "credential_registry": {
            "registry_id": "exact-four-trader-webauthn-credentials/v2",
            "generation": 1,
            "credentials": [credential_row],
        },
    }
    root_activation_digest = canonical_authority_digest(root_activation_document)
    proposal_body = {
        "format": TRADER_ACTIVATION_PROPOSAL_FORMAT,
        "status": "ROOT_REVIEW_REQUIRED",
        "environment": request["environment"],
        "enrollment_request_digest": _sha256_bytes(_canonical_bytes(request)),
        "registration_response_digest": _sha256_bytes(
            _canonical_bytes(registration)
        ),
        "registration_transcript": transcript,
        "root_activation_document": root_activation_document,
        "root_activation_document_digest": root_activation_digest,
        "private_credential_material_obtained": False,
        "human_presence_required_for_only_external_step": True,
        "next_admin_actions": [
            "verify the WebAuthn transcript digest and public credential",
            "provision the dedicated Trader principal and mode-0700 store",
            "verify the controlled_execution AF_UNIX peer and UID",
            "install a root-owned non-group/world-writable activation document",
            "set protected_store_observed true only after direct inspection",
            "leave positive operations blocked until the strict P0 gate closes",
        ],
        "expected_activation_outputs": [
            "root-owned activation.json bound to enrollment transcript",
            "dedicated Trader service UID",
            "mode-0700 Trader ledger directory",
            "public-only P-256 credential registry derived from COSE",
            "no Trader file-backed private signing key",
        ],
        "generated_at": generated_text,
    }
    proposal = {
        **proposal_body,
        "proposal_digest": canonical_authority_digest(proposal_body),
    }
    try:
        SQLiteTraderWebAuthnEnrollmentLedgerV2(enrollment_ledger_path).consume(
            request,
            consumed_at=generated_text,
            transcript_digest=transcript["transcript_digest"],
            proposal_digest=proposal["proposal_digest"],
        )
    except TraderWebAuthnEnrollmentLedgerV2Error as exc:
        raise TraderWebAuthnEnrollmentV2Error(str(exc)) from exc
    return _canonical_bytes(proposal)


__all__ = [
    "TRADER_ACTIVATION_PROPOSAL_FORMAT",
    "TRADER_ENROLLMENT_HUMAN_ACTION",
    "TRADER_ENROLLMENT_REQUEST_FORMAT",
    "TRADER_REGISTRATION_RESPONSE_FORMAT",
    "TRADER_REGISTRATION_TRANSCRIPT_FORMAT",
    "TraderWebAuthnEnrollmentV2Error",
    "build_trader_root_activation_proposal_v2",
    "build_trader_webauthn_enrollment_request_v2",
]
