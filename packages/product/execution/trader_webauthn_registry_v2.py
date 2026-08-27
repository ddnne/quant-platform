"""READY/WebAuthn verification types and governed public registries."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    _canonical_bytes,
    _parsed_timestamp,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import (
    UnverifiedExactFourTraderApprovalSubjectV2,
    _validate_rp_origin,
)
from research.readiness import (
    VerifiedPilotReadiness,
    derive_ready_authority_resource_digest,
    ready_authority_instance_id,
    verify_pinned_pilot_readiness,
)
from selection.budget_ledger import MassResearchDisabledError


TRADER_RP_REGISTRY_FORMAT = "exact-four-trader-rp-registry/v2"
TRADER_CREDENTIAL_REGISTRY_FORMAT = "exact-four-trader-credential-registry/v2"
TRADER_CHALLENGE_FORMAT = "exact-four-trader-webauthn-challenge/v2"
TRADER_ASSERTION_FORMAT = "exact-four-trader-webauthn-assertion/v2"
TRADER_LEDGER_EVENT_FORMAT = "exact-four-trader-ledger-event/v2"
TRADER_COMMITTED_HANDOFF_FORMAT = "exact-four-trader-committed-handoff/v2"
TRADER_VERIFIER_BACKEND = "ExactFourTraderWebAuthnVerifier/v2"
TRADER_LEDGER_BACKEND = "ExactFourTraderOneUseCounterEventLedger/v2"
TRADER_AUTHORITY_LIVE_STATE = (
    "PENDING_HUMAN_ENROLLMENT_AND_PROTECTED_PRINCIPAL_STORE"
)
_CHALLENGE_BYTES = 32
_MAX_CLOCK_SKEW = timedelta(seconds=5)
_READY_EVIDENCE_TOKEN = object()
_COMMITTED_HANDOFF_TOKEN = object()

_ASSERTION_FIELDS = frozenset(
    {
        "format",
        "environment",
        "status",
        "challenge_id",
        "challenge_digest",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "credential_id_base64url",
        "authenticator_data_base64url",
        "client_data_json_base64url",
        "signature_base64url",
        "rp_id",
        "origin",
        "user_present",
        "user_verified",
        "sign_count",
        "asserted_at",
        "one_use_key",
        "assertion_digest",
    }
)


class ExactFourTraderAuthorityV2Error(ExactFourAuthorityContractError):
    """A governed Trader registry, assertion, or transaction was rejected."""


def _require_exact_text(value: Any, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ExactFourTraderAuthorityV2Error(
            f"{label} must be an exact non-empty string"
        )
    return value


def _require_positive_generation(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ExactFourTraderAuthorityV2Error(
            f"{label} must be a positive exact integer"
        )
    return value


def _iso_utc(value: datetime, label: str) -> str:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ExactFourTraderAuthorityV2Error(
            f"{label} must be an exact aware datetime"
        )
    return value.astimezone(timezone.utc).isoformat()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


_READY_RESPONSE_RESULT_FIELDS = frozenset(
    {
        "status",
        "environment",
        "authority_instance_id",
        "authority_resource_digest",
        "snapshot_id",
        "attestation_id",
        "attestation_base64",
        "attestation_digest",
        "ready_manifest_digest",
        "immutable_db_digest",
        "signed_projection_document_digest",
        "issuer_key_id",
    }
)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedReadyAuthorityEvidenceV2:
    """READY local-service response reverified against the pinned public key."""

    _canonical_response: bytes
    _canonical_attestation: bytes
    subject: UnverifiedExactFourTraderApprovalSubjectV2

    def __init__(
        self,
        response: dict[str, Any],
        attestation: bytes,
        subject: UnverifiedExactFourTraderApprovalSubjectV2,
        *,
        _token: object,
    ) -> None:
        if _token is not _READY_EVIDENCE_TOKEN:
            raise ExactFourTraderAuthorityV2Error(
                "READY evidence requires pinned external verification"
            )
        object.__setattr__(self, "_canonical_response", _canonical_bytes(response))
        object.__setattr__(self, "_canonical_attestation", bytes(attestation))
        object.__setattr__(self, "subject", subject)

    @property
    def response_digest(self) -> str:
        return _sha256_bytes(self._canonical_response)

    @property
    def canonical_response(self) -> bytes:
        return self._canonical_response


def verify_ready_authority_response_v2(
    raw: bytes | str,
    *,
    expected_environment: str,
) -> VerifiedReadyAuthorityEvidenceV2:
    """Verify the READY service response; no caller trust root or clock exists."""

    if expected_environment not in {"staging", "production"}:
        raise ExactFourTraderAuthorityV2Error(
            "READY response verifier requires the expected environment"
        )

    response = _strict_json_loads(raw, label="READY local authority response")
    if set(response) != {"format", "request_id", "status", "result"} or (
        response.get("format") != "local-authority-response/v1"
        or response.get("status") != "COMMITTED"
        or type(response.get("request_id")) is not str
        or not response["request_id"]
        or type(response.get("result")) is not dict
    ):
        raise ExactFourTraderAuthorityV2Error(
            "READY local authority response identity is invalid"
        )
    result = response["result"]
    if set(result) != set(_READY_RESPONSE_RESULT_FIELDS) or result.get(
        "status"
    ) != "SIGNED":
        raise ExactFourTraderAuthorityV2Error(
            "READY local authority result fields or status are invalid"
        )
    encoded = result.get("attestation_base64")
    if type(encoded) is not str or not encoded:
        raise ExactFourTraderAuthorityV2Error(
            "READY attestation_base64 is missing"
        )
    try:
        attestation_bytes = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise ExactFourTraderAuthorityV2Error(
            "READY attestation is not canonical base64"
        ) from exc
    if base64.b64encode(attestation_bytes).decode("ascii") != encoded:
        raise ExactFourTraderAuthorityV2Error(
            "READY attestation is not canonical base64"
        )
    if result.get("attestation_digest") != _sha256_bytes(attestation_bytes):
        raise ExactFourTraderAuthorityV2Error(
            "READY attestation byte digest mismatch"
        )
    document = _strict_json_loads(
        attestation_bytes,
        label="signed READY attestation",
    )
    canonical_fields = {item.name for item in fields(VerifiedPilotReadiness)}
    if set(document) != canonical_fields | {"format"} or document.get(
        "format"
    ) != VerifiedPilotReadiness.FORMAT:
        raise ExactFourTraderAuthorityV2Error(
            "signed READY attestation shape or format is invalid"
        )
    init_payload = {name: document[name] for name in canonical_fields}
    for name in ("plan_ids", "dataset_ids"):
        value = init_payload[name]
        if type(value) is not list or any(type(item) is not str for item in value):
            raise ExactFourTraderAuthorityV2Error(
                f"signed READY {name} must be an exact string array"
            )
        init_payload[name] = tuple(value)
    try:
        candidate = VerifiedPilotReadiness(**init_payload)
        verified = verify_pinned_pilot_readiness(
            candidate,
            expected_environment=expected_environment,
            expected_snapshot_id=result.get("snapshot_id"),
            expected_ready_manifest_digest=result.get("ready_manifest_digest"),
        )
    except (MassResearchDisabledError, TypeError, ValueError) as exc:
        raise ExactFourTraderAuthorityV2Error(
            "READY attestation is not current under the pinned verifier"
        ) from exc
    try:
        expected_resource_digest = derive_ready_authority_resource_digest(
            environment=expected_environment,
            authority_instance_id=ready_authority_instance_id(
                expected_environment
            ),
        snapshot_id=verified.snapshot_id,
        immutable_db_digest=verified.immutable_db_digest,
        ready_manifest_digest=verified.ready_manifest_digest,
        signed_projection_document_digest=(
            verified.signed_projection_document_digest
        ),
        )
    except MassResearchDisabledError as exc:
        raise ExactFourTraderAuthorityV2Error(
            "READY authority resource identity is malformed"
        ) from exc
    if (
        verified.environment != expected_environment
        or result.get("environment") != expected_environment
        or verified.authority_instance_id
        != ready_authority_instance_id(expected_environment)
        or result.get("authority_instance_id")
        != verified.authority_instance_id
        or verified.authority_resource_digest != expected_resource_digest
        or result.get("authority_resource_digest") != expected_resource_digest
        or result.get("signed_projection_document_digest")
        != verified.signed_projection_document_digest
        or verified.attestation_id != result.get("attestation_id")
        or verified.snapshot_id != result.get("snapshot_id")
        or verified.ready_manifest_digest != result.get("ready_manifest_digest")
        or verified.immutable_db_digest != result.get("immutable_db_digest")
        or verified.key_id != result.get("issuer_key_id")
    ):
        raise ExactFourTraderAuthorityV2Error(
            "READY service result does not bind its signed attestation"
        )
    from execution.exact_four_binding import load_exact_four_execution_binding

    exact_four = load_exact_four_execution_binding()
    subject = UnverifiedExactFourTraderApprovalSubjectV2(
        pilot_run_id=response["request_id"],
        environment=verified.environment,
        ready_authority_instance_id=verified.authority_instance_id,
        ready_authority_resource_digest=verified.authority_resource_digest,
        readiness_attestation_id=result["attestation_digest"],
        snapshot_id=verified.snapshot_id,
        ready_manifest_digest=verified.ready_manifest_digest,
        immutable_snapshot_digest=verified.immutable_db_digest,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=exact_four.policy.policy_digest,
        budget_scope_digest=exact_four.budget_scope_digest,
        execution_limit_set_digest=exact_four.execution_limit_set_digest,
        lease_ttl_seconds=exact_four.lease_ttl_seconds,
        ready_issued_at=verified.verified_at,
        ready_expires_at=verified.expires_at,
    )
    return VerifiedReadyAuthorityEvidenceV2(
        response,
        attestation_bytes,
        subject,
        _token=_READY_EVIDENCE_TOKEN,
    )


def _require_ready_authority_evidence_v2(
    value: Any,
    *,
    expected_environment: str,
) -> VerifiedReadyAuthorityEvidenceV2:
    if type(value) is not VerifiedReadyAuthorityEvidenceV2:
        raise ExactFourTraderAuthorityV2Error(
            "exact verified READY authority evidence is required"
        )
    reverified = verify_ready_authority_response_v2(
        value.canonical_response,
        expected_environment=expected_environment,
    )
    if (
        reverified.response_digest != value.response_digest
        or reverified.subject != value.subject
    ):
        raise ExactFourTraderAuthorityV2Error(
            "READY authority evidence provenance changed"
        )
    return value


@dataclass(frozen=True, slots=True)
class ExactFourTraderRelyingPartyV2:
    environment: str
    policy_id: str
    policy_generation: int
    rp_id: str
    origin: str
    effective_at: str
    status: str = "ACTIVE"
    user_presence_required: bool = True
    user_verification_required: bool = True

    def __post_init__(self) -> None:
        _require_exact_text(self.environment, "RP environment")
        _require_exact_text(self.policy_id, "RP policy_id")
        _require_positive_generation(self.policy_generation, "RP policy_generation")
        _validate_rp_origin(self.rp_id, self.origin)
        _parsed_timestamp(self.effective_at, "RP effective_at")
        if (
            self.status != "ACTIVE"
            or self.user_presence_required is not True
            or self.user_verification_required is not True
        ):
            raise ExactFourTraderAuthorityV2Error(
                "Trader RP must be ACTIVE and require both user presence and verification"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": TRADER_RP_REGISTRY_FORMAT,
            "environment": self.environment,
            "policy_id": self.policy_id,
            "policy_generation": self.policy_generation,
            "rp_id": self.rp_id,
            "origin": self.origin,
            "effective_at": self.effective_at,
            "status": self.status,
            "user_presence_required": self.user_presence_required,
            "user_verification_required": self.user_verification_required,
        }

    @property
    def policy_digest(self) -> str:
        return canonical_authority_digest(self.to_dict())


class ExactFourTraderRelyingPartyRegistryV2:
    """Immutable environment-indexed RP policy registry."""

    __slots__ = ("_entries", "_digest", "generation")

    def __init__(
        self,
        entries: tuple[ExactFourTraderRelyingPartyV2, ...],
        *,
        generation: int,
    ) -> None:
        _require_positive_generation(generation, "RP registry generation")
        exact_entries = tuple(entries)
        if not exact_entries or any(
            type(item) is not ExactFourTraderRelyingPartyV2
            for item in exact_entries
        ):
            raise ExactFourTraderAuthorityV2Error(
                "RP registry requires exact RP entries"
            )
        mapped: dict[str, ExactFourTraderRelyingPartyV2] = {}
        for entry in exact_entries:
            if entry.environment in mapped:
                raise ExactFourTraderAuthorityV2Error(
                    "RP registry environment is duplicated"
                )
            mapped[entry.environment] = entry
        document = {
            "format": TRADER_RP_REGISTRY_FORMAT,
            "generation": generation,
            "entries": [item.to_dict() for item in exact_entries],
        }
        self._entries = MappingProxyType(mapped)
        self._digest = canonical_authority_digest(document)
        self.generation = generation

    @property
    def registry_digest(self) -> str:
        return self._digest

    def require(self, environment: str) -> ExactFourTraderRelyingPartyV2:
        try:
            return self._entries[environment]
        except KeyError as exc:
            raise ExactFourTraderAuthorityV2Error(
                "no active governed RP for the requested environment"
            ) from exc


@dataclass(frozen=True, slots=True)
class ExactFourTraderCredentialV2:
    environment: str
    credential_id: bytes
    public_key: ec.EllipticCurvePublicKey
    rp_policy_digest: str
    effective_at: str
    initial_sign_count: int = 0
    counter_mode: str = "COUNTING"
    status: str = "ACTIVE"
    algorithm: str = "ES256"
    key_backend: str = "webauthn_platform_or_hardware"

    def __post_init__(self) -> None:
        _require_exact_text(self.environment, "credential environment")
        if type(self.credential_id) is not bytes or not 16 <= len(
            self.credential_id
        ) <= 1024:
            raise ExactFourTraderAuthorityV2Error(
                "credential id must be 16..1024 exact bytes"
            )
        if not isinstance(self.public_key, ec.EllipticCurvePublicKey) or not isinstance(
            self.public_key.curve, ec.SECP256R1
        ):
            raise ExactFourTraderAuthorityV2Error(
                "Trader credential must be a P-256 public key"
            )
        if (
            type(self.rp_policy_digest) is not str
            or not self.rp_policy_digest.startswith("sha256:")
            or len(self.rp_policy_digest) != 71
        ):
            raise ExactFourTraderAuthorityV2Error(
                "credential RP policy digest is invalid"
            )
        _parsed_timestamp(self.effective_at, "credential effective_at")
        if (
            type(self.initial_sign_count) is not int
            or self.initial_sign_count < 0
            or self.counter_mode not in {"COUNTING", "COUNTERLESS"}
            or (
                self.counter_mode == "COUNTERLESS"
                and self.initial_sign_count != 0
            )
            or self.status != "ACTIVE"
            or self.algorithm != "ES256"
            or self.key_backend != "webauthn_platform_or_hardware"
        ):
            raise ExactFourTraderAuthorityV2Error(
                "credential status, counter, algorithm, or backend is invalid"
            )

    @property
    def credential_id_base64url(self) -> str:
        return _b64url(self.credential_id)

    @property
    def public_key_digest(self) -> str:
        encoded = self.public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def registry_row(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "credential_id_base64url": self.credential_id_base64url,
            "credential_public_key_digest": self.public_key_digest,
            "rp_policy_digest": self.rp_policy_digest,
            "effective_at": self.effective_at,
            "initial_sign_count": self.initial_sign_count,
            "counter_mode": self.counter_mode,
            "status": self.status,
            "algorithm": self.algorithm,
            "key_backend": self.key_backend,
        }


class ExactFourTraderCredentialRegistryV2:
    """Immutable public-key-only credential registry."""

    __slots__ = ("_credentials", "_digest", "generation", "registry_id")

    def __init__(
        self,
        credentials: tuple[ExactFourTraderCredentialV2, ...],
        *,
        generation: int,
        registry_id: str = "exact-four-trader-webauthn-credentials/v2",
    ) -> None:
        _require_positive_generation(generation, "credential registry generation")
        _require_exact_text(registry_id, "credential registry id")
        exact_credentials = tuple(credentials)
        if not exact_credentials or any(
            type(item) is not ExactFourTraderCredentialV2
            for item in exact_credentials
        ):
            raise ExactFourTraderAuthorityV2Error(
                "credential registry requires exact public credential entries"
            )
        mapped: dict[tuple[str, str], ExactFourTraderCredentialV2] = {}
        for credential in exact_credentials:
            key = (
                credential.environment,
                credential.credential_id_base64url,
            )
            if key in mapped:
                raise ExactFourTraderAuthorityV2Error(
                    "credential registry identity is duplicated"
                )
            mapped[key] = credential
        document = {
            "format": TRADER_CREDENTIAL_REGISTRY_FORMAT,
            "registry_id": registry_id,
            "generation": generation,
            "credentials": [item.registry_row() for item in exact_credentials],
        }
        self._credentials = MappingProxyType(mapped)
        self._digest = canonical_authority_digest(document)
        self.generation = generation
        self.registry_id = registry_id

    @property
    def registry_digest(self) -> str:
        return self._digest

    @property
    def credentials(self) -> tuple[ExactFourTraderCredentialV2, ...]:
        return tuple(self._credentials.values())

    def require(
        self, environment: str, credential_id_base64url: str
    ) -> ExactFourTraderCredentialV2:
        try:
            return self._credentials[(environment, credential_id_base64url)]
        except KeyError as exc:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn credential is absent or inactive"
            ) from exc


@dataclass(frozen=True, slots=True)
class IssuedExactFourTraderChallengeV2:
    """Canonical challenge registered AVAILABLE in the authority ledger."""

    _canonical_document: bytes

    @classmethod
    def from_document(
        cls, document: Mapping[str, Any]
    ) -> "IssuedExactFourTraderChallengeV2":
        if type(document) is not dict:
            raise ExactFourTraderAuthorityV2Error(
                "issued challenge must be an exact dict"
            )
        return cls(_canonical_bytes(document))

    def to_dict(self) -> dict[str, Any]:
        return _strict_json_loads(
            self._canonical_document,
            label="issued exact-four Trader challenge",
        )

    @property
    def challenge_digest(self) -> str:
        return self.to_dict()["challenge_digest"]

    @property
    def challenge_base64url(self) -> str:
        return self.to_dict()["challenge_base64url"]


@dataclass(frozen=True, slots=True, init=False)
class CommittedExactFourTraderHandoffV2:
    """Non-reusable canonical bytes for a kernel-authenticated direct handoff."""

    _canonical_document: bytes

    def __init__(self, document: dict[str, Any], *, _token: object) -> None:
        if _token is not _COMMITTED_HANDOFF_TOKEN:
            raise ExactFourTraderAuthorityV2Error(
                "Trader handoff requires a committed authority transaction"
            )
        object.__setattr__(self, "_canonical_document", _canonical_bytes(document))

    @property
    def canonical_bytes(self) -> bytes:
        return self._canonical_document

    @property
    def handoff_id(self) -> str:
        return self.to_dict()["handoff_id"]

    def to_dict(self) -> dict[str, Any]:
        return _strict_json_loads(
            self._canonical_document,
            label="committed exact-four Trader handoff",
        )


__all__ = [
    "TRADER_ASSERTION_FORMAT",
    "TRADER_CHALLENGE_FORMAT",
    "TRADER_COMMITTED_HANDOFF_FORMAT",
    "TRADER_CREDENTIAL_REGISTRY_FORMAT",
    "TRADER_LEDGER_BACKEND",
    "TRADER_LEDGER_EVENT_FORMAT",
    "TRADER_RP_REGISTRY_FORMAT",
    "TRADER_VERIFIER_BACKEND",
    "CommittedExactFourTraderHandoffV2",
    "ExactFourTraderAuthorityV2Error",
    "ExactFourTraderCredentialRegistryV2",
    "ExactFourTraderCredentialV2",
    "ExactFourTraderRelyingPartyRegistryV2",
    "ExactFourTraderRelyingPartyV2",
    "IssuedExactFourTraderChallengeV2",
    "VerifiedReadyAuthorityEvidenceV2",
    "verify_ready_authority_response_v2",
]
