"""Inactive authority-side WebAuthn implementation for exact-four Trader v2.

The code in this module is the non-human half of the future Trader authority:
governed RP and public-credential registries, CSPRNG challenge issuance, ES256
assertion verification, and an atomic SQLite one-use/counter/event ledger.

It never mints a reusable product-plane Trader capability and owns no generic
signer.  A committed assertion is exported only as read-only bytes for a
kernel-authenticated direct handoff to ``controlled_execution``.  The live
opener reads a fixed root-owned activation record and remains fail closed until
the dedicated OS principal, protected store, and human enrollment are observed.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import os
import secrets
import sqlite3
import stat
import tempfile
import uuid
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    _canonical_bytes,
    _parsed_timestamp,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import (
    UnverifiedExactFourTraderApprovalSubjectV2,
    _decode_canonical_base64url,
    _require_content_digest,
    _validate_rp_origin,
    _validate_webauthn_bytes,
    derive_exact_four_trader_one_use_key_v2,
)
from research.readiness import (
    VerifiedPilotReadiness,
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
_AUTHORITY_CONSTRUCTION_TOKEN = object()
_READY_EVIDENCE_TOKEN = object()
_COMMITTED_HANDOFF_TOKEN = object()
TRADER_AUTHORITY_ACTIVATION_PATH = Path(
    "/etc/quant-platform/authorities/trader/activation.json"
)

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
) -> VerifiedReadyAuthorityEvidenceV2:
    """Verify the READY service response; no caller trust root or clock exists."""

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
            expected_snapshot_id=result.get("snapshot_id"),
            expected_ready_manifest_digest=result.get("ready_manifest_digest"),
        )
    except (MassResearchDisabledError, TypeError, ValueError) as exc:
        raise ExactFourTraderAuthorityV2Error(
            "READY attestation is not current under the pinned verifier"
        ) from exc
    if (
        verified.attestation_id != result.get("attestation_id")
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
) -> VerifiedReadyAuthorityEvidenceV2:
    if type(value) is not VerifiedReadyAuthorityEvidenceV2:
        raise ExactFourTraderAuthorityV2Error(
            "exact verified READY authority evidence is required"
        )
    reverified = verify_ready_authority_response_v2(value.canonical_response)
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


class SQLiteExactFourTraderLedgerV2:
    """Authority-owned atomic challenge/counter/append-only decision store."""

    __slots__ = ("_path", "_environment", "_registry_digest")

    def __init__(
        self,
        path: Path,
        *,
        environment: str,
        credentials: ExactFourTraderCredentialRegistryV2,
        _token: object,
    ) -> None:
        if _token is not _AUTHORITY_CONSTRUCTION_TOKEN:
            raise ExactFourAuthorityPending(TRADER_AUTHORITY_LIVE_STATE)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ExactFourTraderAuthorityV2Error(
                "Trader authority ledger requires an absolute authority-owned path"
            )
        self._path = path
        self._environment = environment
        self._registry_digest = credentials.registry_digest
        self._initialize(credentials)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._path),
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(
        self, credentials: ExactFourTraderCredentialRegistryV2
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS authority_metadata (
                    environment TEXT PRIMARY KEY,
                    credential_registry_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS credential_counters (
                    environment TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    public_key_digest TEXT NOT NULL,
                    registry_digest TEXT NOT NULL,
                    counter_mode TEXT NOT NULL,
                    sign_count INTEGER NOT NULL CHECK(sign_count >= 0),
                    PRIMARY KEY(environment, credential_id)
                );
                CREATE TABLE IF NOT EXISTS challenges (
                    environment TEXT NOT NULL,
                    challenge_id TEXT NOT NULL,
                    challenge_digest TEXT NOT NULL UNIQUE,
                    approval_subject_id TEXT NOT NULL,
                    one_use_key TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    canonical_challenge BLOB NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('AVAILABLE','CONSUMED')),
                    consumed_at TEXT,
                    PRIMARY KEY(environment, challenge_id)
                );
                CREATE TABLE IF NOT EXISTS trader_events (
                    environment TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_digest TEXT NOT NULL UNIQUE,
                    prior_event_digest TEXT,
                    request_digest TEXT NOT NULL UNIQUE,
                    approval_subject_id TEXT NOT NULL,
                    one_use_key TEXT NOT NULL UNIQUE,
                    credential_id TEXT NOT NULL,
                    prior_sign_count INTEGER NOT NULL,
                    result_sign_count INTEGER NOT NULL,
                    canonical_event BLOB NOT NULL,
                    PRIMARY KEY(environment, sequence)
                );
                CREATE TABLE IF NOT EXISTS trader_decisions (
                    environment TEXT NOT NULL,
                    authorization_id TEXT NOT NULL UNIQUE,
                    request_digest TEXT NOT NULL UNIQUE,
                    approval_subject_id TEXT NOT NULL UNIQUE,
                    assertion_digest TEXT NOT NULL UNIQUE,
                    event_digest TEXT NOT NULL UNIQUE,
                    canonical_authorization BLOB NOT NULL,
                    PRIMARY KEY(environment, authorization_id),
                    FOREIGN KEY(event_digest) REFERENCES trader_events(event_digest)
                );
                CREATE TRIGGER IF NOT EXISTS trader_events_no_update
                    BEFORE UPDATE ON trader_events BEGIN
                    SELECT RAISE(ABORT, 'trader events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS trader_events_no_delete
                    BEFORE DELETE ON trader_events BEGIN
                    SELECT RAISE(ABORT, 'trader events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS trader_decisions_no_update
                    BEFORE UPDATE ON trader_decisions BEGIN
                    SELECT RAISE(ABORT, 'trader decisions are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS trader_decisions_no_delete
                    BEFORE DELETE ON trader_decisions BEGIN
                    SELECT RAISE(ABORT, 'trader decisions are immutable');
                    END;
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT credential_registry_digest FROM authority_metadata "
                    "WHERE environment = ?",
                    (self._environment,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO authority_metadata VALUES (?, ?)",
                        (self._environment, credentials.registry_digest),
                    )
                elif row["credential_registry_digest"] != credentials.registry_digest:
                    raise ExactFourTraderAuthorityV2Error(
                        "credential registry generation changed without migration"
                    )
                for credential in credentials.credentials:
                    if credential.environment != self._environment:
                        continue
                    existing = connection.execute(
                        "SELECT * FROM credential_counters WHERE environment = ? "
                        "AND credential_id = ?",
                        (self._environment, credential.credential_id_base64url),
                    ).fetchone()
                    expected = (
                        credential.public_key_digest,
                        credentials.registry_digest,
                        credential.counter_mode,
                    )
                    if existing is None:
                        connection.execute(
                            "INSERT INTO credential_counters VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                self._environment,
                                credential.credential_id_base64url,
                                *expected,
                                credential.initial_sign_count,
                            ),
                        )
                    elif (
                        existing["public_key_digest"],
                        existing["registry_digest"],
                        existing["counter_mode"],
                    ) != expected:
                        raise ExactFourTraderAuthorityV2Error(
                            "stored credential identity differs from governed registry"
                        )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def register_challenge(self, document: dict[str, Any]) -> None:
        canonical = _canonical_bytes(document)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO challenges VALUES (?, ?, ?, ?, ?, ?, ?, 'AVAILABLE', NULL)",
                    (
                        document["environment"],
                        document["challenge_id"],
                        document["challenge_digest"],
                        document["approval_subject_id"],
                        document["one_use_key"],
                        document["expires_at"],
                        canonical,
                    ),
                )
                connection.execute("COMMIT")
        except sqlite3.Error as exc:
            raise ExactFourTraderAuthorityV2Error(
                "challenge identity is already issued or ledger registration failed"
            ) from exc

    def _decision_for_request(
        self, connection: sqlite3.Connection, request_digest: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT canonical_authorization FROM trader_decisions "
            "WHERE environment = ? AND request_digest = ?",
            (self._environment, request_digest),
        ).fetchone()
        if row is None:
            return None
        return _strict_json_loads(
            bytes(row["canonical_authorization"]),
            label="stored Trader authorization decision",
        )

    def commit_verified_assertion(
        self,
        *,
        ready_response_digest: str,
        approval_subject: dict[str, Any],
        challenge: dict[str, Any],
        assertion: dict[str, Any],
        credential: ExactFourTraderCredentialV2,
        credential_registry: ExactFourTraderCredentialRegistryV2,
        committed_at: str,
    ) -> dict[str, Any]:
        """Consume challenge, CAS counter, append event, and store decision once."""

        request_body = {
            "format": "exact-four-trader-authority-request/v2",
            "environment": self._environment,
            "approval_subject_id": challenge["approval_subject_id"],
            "ready_authority_response_digest": ready_response_digest,
            "challenge_digest": challenge["challenge_digest"],
            "assertion_digest": assertion["assertion_digest"],
            "credential_registry_digest": credential_registry.registry_digest,
            "credential_public_key_digest": credential.public_key_digest,
        }
        request_digest = canonical_authority_digest(request_body)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._decision_for_request(connection, request_digest)
            if prior is not None:
                connection.execute("COMMIT")
                return prior
            challenge_row = connection.execute(
                "SELECT * FROM challenges WHERE environment = ? AND challenge_id = ?",
                (self._environment, challenge["challenge_id"]),
            ).fetchone()
            if (
                challenge_row is None
                or challenge_row["status"] != "AVAILABLE"
                or bytes(challenge_row["canonical_challenge"])
                != _canonical_bytes(challenge)
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "WebAuthn challenge is unavailable, consumed, or not ledger-identical"
                )
            counter = connection.execute(
                "SELECT * FROM credential_counters WHERE environment = ? "
                "AND credential_id = ?",
                (self._environment, credential.credential_id_base64url),
            ).fetchone()
            if (
                counter is None
                or counter["public_key_digest"] != credential.public_key_digest
                or counter["registry_digest"] != credential_registry.registry_digest
                or counter["counter_mode"] != credential.counter_mode
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "credential counter state is not registry-bound"
                )
            prior_count = int(counter["sign_count"])
            asserted_count = assertion["sign_count"]
            if credential.counter_mode == "COUNTING":
                if type(asserted_count) is not int or asserted_count <= prior_count:
                    raise ExactFourTraderAuthorityV2Error(
                        "WebAuthn signature counter did not advance"
                    )
                updated = connection.execute(
                    "UPDATE credential_counters SET sign_count = ? WHERE "
                    "environment = ? AND credential_id = ? AND sign_count = ?",
                    (
                        asserted_count,
                        self._environment,
                        credential.credential_id_base64url,
                        prior_count,
                    ),
                ).rowcount
                if updated != 1:
                    raise ExactFourTraderAuthorityV2Error(
                        "WebAuthn signature counter CAS failed"
                    )
            elif prior_count != 0 or asserted_count != 0:
                raise ExactFourTraderAuthorityV2Error(
                    "counterless WebAuthn credential must remain at zero"
                )
            consumed = connection.execute(
                "UPDATE challenges SET status = 'CONSUMED', consumed_at = ? "
                "WHERE environment = ? AND challenge_id = ? AND status = 'AVAILABLE'",
                (committed_at, self._environment, challenge["challenge_id"]),
            ).rowcount
            if consumed != 1:
                raise ExactFourTraderAuthorityV2Error(
                    "WebAuthn challenge one-use CAS failed"
                )
            tail = connection.execute(
                "SELECT sequence, event_digest FROM trader_events WHERE "
                "environment = ? ORDER BY sequence DESC LIMIT 1",
                (self._environment,),
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            prior_event_digest = None if tail is None else tail["event_digest"]
            event_body = {
                "format": TRADER_LEDGER_EVENT_FORMAT,
                "environment": self._environment,
                "ledger_backend_id": TRADER_LEDGER_BACKEND,
                "sequence": sequence,
                "event_id": str(uuid.uuid4()),
                "prior_event_digest": prior_event_digest,
                "request_digest": request_digest,
                "approval_subject_id": challenge["approval_subject_id"],
                "challenge_id": challenge["challenge_id"],
                "challenge_digest": challenge["challenge_digest"],
                "assertion_digest": assertion["assertion_digest"],
                "one_use_key": challenge["one_use_key"],
                "one_use_prior_status": "AVAILABLE",
                "one_use_result_status": "CONSUMED",
                "one_use_cas_status": "APPLIED",
                "credential_id_base64url": credential.credential_id_base64url,
                "credential_registry_generation": credential_registry.generation,
                "credential_registry_digest": credential_registry.registry_digest,
                "counter_mode": credential.counter_mode,
                "prior_sign_count": prior_count,
                "asserted_sign_count": asserted_count,
                "result_sign_count": asserted_count,
                "counter_cas_status": (
                    "APPLIED"
                    if credential.counter_mode == "COUNTING"
                    else "NOT_APPLICABLE"
                ),
                "transaction_status": "COMMITTED",
                "committed_at": committed_at,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            event = {
                **event_body,
                "event_digest": canonical_authority_digest(event_body),
            }
            credential_evidence = {
                "format": "exact-four-trader-credential-evidence/v2",
                "environment": self._environment,
                "credential_id_base64url": credential.credential_id_base64url,
                "credential_public_key_digest": credential.public_key_digest,
                "credential_algorithm": credential.algorithm,
                "key_backend": credential.key_backend,
                "credential_registry_generation": credential_registry.generation,
                "credential_registry_digest": credential_registry.registry_digest,
                "rp_policy_digest": credential.rp_policy_digest,
                "counter_mode": credential.counter_mode,
            }
            handoff_body = {
                "format": TRADER_COMMITTED_HANDOFF_FORMAT,
                "environment": self._environment,
                "handoff_status": "COMMITTED",
                "ready_authority_response_digest": ready_response_digest,
                "approval_subject_id": challenge["approval_subject_id"],
                "approval_subject": approval_subject,
                "challenge_evidence": challenge,
                "assertion_evidence": assertion,
                "credential_registry_evidence": credential_evidence,
                "one_use_counter_event": event,
                "issued_at": committed_at,
                "expires_at": challenge["expires_at"],
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            handoff = {
                **handoff_body,
                "handoff_id": canonical_authority_digest(handoff_body),
            }
            connection.execute(
                "INSERT INTO trader_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._environment,
                    sequence,
                    event["event_id"],
                    event["event_digest"],
                    prior_event_digest,
                    request_digest,
                    challenge["approval_subject_id"],
                    challenge["one_use_key"],
                    credential.credential_id_base64url,
                    prior_count,
                    asserted_count,
                    _canonical_bytes(event),
                ),
            )
            connection.execute(
                "INSERT INTO trader_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._environment,
                    handoff["handoff_id"],
                    request_digest,
                    challenge["approval_subject_id"],
                    assertion["assertion_digest"],
                    event["event_digest"],
                    _canonical_bytes(handoff),
                ),
            )
            connection.execute("COMMIT")
            return handoff
        except ExactFourTraderAuthorityV2Error:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ExactFourTraderAuthorityV2Error(
                "atomic Trader one-use/counter/event transaction failed"
            ) from exc
        finally:
            connection.close()

    def challenge_status(self, challenge_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM challenges WHERE environment = ? AND challenge_id = ?",
                (self._environment, challenge_id),
            ).fetchone()
            return None if row is None else str(row["status"])

    def credential_sign_count(self, credential_id_base64url: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sign_count FROM credential_counters WHERE environment = ? "
                "AND credential_id = ?",
                (self._environment, credential_id_base64url),
            ).fetchone()
            return None if row is None else int(row["sign_count"])

    def event_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM trader_events WHERE environment = ?",
                (self._environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])


class ExactFourTraderWebAuthnAuthorityV2:
    """Authority-side verifier; constructed only by an activation boundary."""

    __slots__ = (
        "environment",
        "_rps",
        "_credentials",
        "_ledger",
        "_clock",
    )

    def __init__(
        self,
        *,
        environment: str,
        relying_parties: ExactFourTraderRelyingPartyRegistryV2,
        credentials: ExactFourTraderCredentialRegistryV2,
        ledger: SQLiteExactFourTraderLedgerV2,
        clock: Callable[[], datetime],
        _token: object,
    ) -> None:
        if _token is not _AUTHORITY_CONSTRUCTION_TOKEN:
            raise ExactFourAuthorityPending(TRADER_AUTHORITY_LIVE_STATE)
        rp = relying_parties.require(environment)
        for credential in credentials.credentials:
            if credential.environment == environment and (
                credential.rp_policy_digest != rp.policy_digest
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "credential registry is not bound to the active RP policy"
                )
        self.environment = environment
        self._rps = relying_parties
        self._credentials = credentials
        self._ledger = ledger
        self._clock = clock

    @property
    def ledger(self) -> SQLiteExactFourTraderLedgerV2:
        return self._ledger

    def issue_challenge(
        self,
        readiness: VerifiedReadyAuthorityEvidenceV2,
    ) -> IssuedExactFourTraderChallengeV2:
        verified_ready = _require_ready_authority_evidence_v2(readiness)
        subject = verified_ready.subject
        now = self._clock()
        issued_at = _iso_utc(now, "Trader challenge clock")
        ready_expires = _parsed_timestamp(
            subject.ready_expires_at, "subject ready_expires_at"
        ).astimezone(timezone.utc)
        expires = min(
            now.astimezone(timezone.utc)
            + timedelta(seconds=subject.lease_ttl_seconds),
            ready_expires,
        )
        if expires <= now.astimezone(timezone.utc):
            raise ExactFourTraderAuthorityV2Error(
                "READY window expired before Trader challenge issuance"
            )
        rp = self._rps.require(self.environment)
        challenge_body: dict[str, Any] = {
            "format": TRADER_CHALLENGE_FORMAT,
            "environment": self.environment,
            "status": "ISSUED",
            "challenge_id": str(uuid.uuid4()),
            "challenge_base64url": _b64url(secrets.token_bytes(_CHALLENGE_BYTES)),
            "approval_subject_id": subject.approval_subject_id,
            "rp_policy_generation": rp.policy_generation,
            "rp_policy_digest": rp.policy_digest,
            "rp_id": rp.rp_id,
            "origin": rp.origin,
            "user_presence_required": True,
            "user_verification_required": True,
            "issued_at": issued_at,
            "expires_at": _iso_utc(expires, "Trader challenge expiry"),
        }
        challenge_body["one_use_key"] = (
            derive_exact_four_trader_one_use_key_v2(dict(challenge_body))
        )
        document = {
            **challenge_body,
            "challenge_digest": canonical_authority_digest(challenge_body),
        }
        self._ledger.register_challenge(document)
        return IssuedExactFourTraderChallengeV2.from_document(document)

    def authorize(
        self,
        *,
        readiness: VerifiedReadyAuthorityEvidenceV2,
        challenge: IssuedExactFourTraderChallengeV2,
        assertion_raw: bytes | str,
    ) -> CommittedExactFourTraderHandoffV2:
        verified_ready = _require_ready_authority_evidence_v2(readiness)
        subject = verified_ready.subject
        if type(challenge) is not IssuedExactFourTraderChallengeV2:
            raise ExactFourTraderAuthorityV2Error(
                "exact issued Trader challenge is required"
            )
        challenge_document = challenge.to_dict()
        if (
            challenge_document["approval_subject_id"]
            != subject.approval_subject_id
            or challenge_document["environment"] != self.environment
        ):
            raise ExactFourTraderAuthorityV2Error(
                "Trader challenge is not bound to READY subject/environment"
            )
        assertion = _strict_json_loads(
            assertion_raw,
            label="exact-four Trader WebAuthn assertion",
        )
        if set(assertion) != set(_ASSERTION_FIELDS):
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion fields are not closed"
            )
        if (
            assertion["format"] != TRADER_ASSERTION_FORMAT
            or assertion["status"] != "VERIFIED"
        ):
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion identity is invalid"
            )
        _require_content_digest(
            assertion,
            digest_field="assertion_digest",
            label="WebAuthn assertion",
        )
        for field in (
            "environment",
            "challenge_id",
            "approval_subject_id",
            "rp_policy_generation",
            "rp_policy_digest",
            "rp_id",
            "origin",
            "one_use_key",
        ):
            if assertion[field] != challenge_document[field]:
                raise ExactFourTraderAuthorityV2Error(
                    f"WebAuthn assertion {field} does not bind the issued challenge"
                )
        if assertion["challenge_digest"] != challenge_document["challenge_digest"]:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion challenge digest mismatch"
            )
        _validate_webauthn_bytes(challenge_document, assertion)
        credential = self._credentials.require(
            self.environment,
            assertion["credential_id_base64url"],
        )
        rp = self._rps.require(self.environment)
        if credential.rp_policy_digest != rp.policy_digest:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn credential is not bound to the current RP generation"
            )
        authenticator_data = _decode_canonical_base64url(
            assertion["authenticator_data_base64url"],
            label="authenticatorData",
            minimum_bytes=37,
            maximum_bytes=4096,
        )
        client_data = _decode_canonical_base64url(
            assertion["client_data_json_base64url"],
            label="clientDataJSON",
            minimum_bytes=32,
            maximum_bytes=8192,
        )
        signature = _decode_canonical_base64url(
            assertion["signature_base64url"],
            label="WebAuthn signature",
            minimum_bytes=8,
            maximum_bytes=1024,
        )
        signed_bytes = authenticator_data + hashlib.sha256(client_data).digest()
        try:
            credential.public_key.verify(
                signature,
                signed_bytes,
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn ES256 assertion signature is invalid"
            ) from exc
        current = self._clock()
        committed_at = _iso_utc(current, "Trader authority clock")
        asserted_at = _parsed_timestamp(
            assertion["asserted_at"], "assertion asserted_at"
        )
        challenge_issued = _parsed_timestamp(
            challenge_document["issued_at"], "challenge issued_at"
        )
        challenge_expires = _parsed_timestamp(
            challenge_document["expires_at"], "challenge expires_at"
        )
        credential_effective = _parsed_timestamp(
            credential.effective_at, "credential effective_at"
        )
        rp_effective = _parsed_timestamp(rp.effective_at, "RP effective_at")
        current_utc = current.astimezone(timezone.utc)
        if not (
            credential_effective <= asserted_at
            and rp_effective <= asserted_at
            and challenge_issued <= asserted_at <= current_utc + _MAX_CLOCK_SKEW
            and asserted_at <= challenge_expires
            and current_utc < challenge_expires
        ):
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion or authority observation is outside challenge window"
            )
        handoff = self._ledger.commit_verified_assertion(
            ready_response_digest=verified_ready.response_digest,
            approval_subject=subject.to_dict(),
            challenge=challenge_document,
            assertion=assertion,
            credential=credential,
            credential_registry=self._credentials,
            committed_at=committed_at,
        )
        return CommittedExactFourTraderHandoffV2(
            handoff,
            _token=_COMMITTED_HANDOFF_TOKEN,
        )

    def open_handoff_descriptor(
        self,
        handoff: CommittedExactFourTraderHandoffV2,
    ) -> int:
        """Return an unlinked, read-only, CLOEXEC descriptor for SCM_RIGHTS."""

        if type(handoff) is not CommittedExactFourTraderHandoffV2:
            raise ExactFourTraderAuthorityV2Error(
                "exact committed Trader handoff is required"
            )
        document = handoff.to_dict()
        body = dict(document)
        declared = body.pop("handoff_id", None)
        if declared != canonical_authority_digest(body):
            raise ExactFourTraderAuthorityV2Error(
                "committed Trader handoff content id is invalid"
            )
        fd, name = tempfile.mkstemp(
            prefix="trader-handoff-",
            suffix=".json",
            dir=str(self._ledger._path.parent),
        )
        path = Path(name)
        readonly_fd: int | None = None
        try:
            payload = handoff.canonical_bytes
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise ExactFourTraderAuthorityV2Error(
                        "cannot materialize committed Trader handoff bytes"
                    )
                offset += written
            os.fsync(fd)
            os.fchmod(fd, 0o400)
            os.close(fd)
            fd = -1
            readonly_fd = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
            )
            os.unlink(path)
            flags = fcntl.fcntl(readonly_fd, fcntl.F_GETFL)
            descriptor_flags = fcntl.fcntl(readonly_fd, fcntl.F_GETFD)
            measured = os.fstat(readonly_fd)
            if (
                flags & os.O_ACCMODE != os.O_RDONLY
                or descriptor_flags & fcntl.FD_CLOEXEC == 0
                or not stat.S_ISREG(measured.st_mode)
                or measured.st_size != len(payload)
                or os.pread(readonly_fd, len(payload), 0) != payload
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "committed Trader handoff descriptor is not immutable/read-only"
                )
            result = readonly_fd
            readonly_fd = None
            return result
        finally:
            if fd >= 0:
                os.close(fd)
            if path.exists():
                path.unlink()
            if readonly_fd is not None:
                os.close(readonly_fd)


def _create_test_exact_four_trader_authority_v2(
    *,
    ledger_path: Path,
    relying_parties: ExactFourTraderRelyingPartyRegistryV2,
    credentials: ExactFourTraderCredentialRegistryV2,
    clock: Callable[[], datetime],
) -> ExactFourTraderWebAuthnAuthorityV2:
    """Construct an intentionally non-activatable authority for behavior tests."""

    environment = "test"
    rp = relying_parties.require(environment)
    if not rp.rp_id.endswith(".invalid"):
        raise ExactFourTraderAuthorityV2Error(
            "test Trader authority RP must use the reserved .invalid suffix"
        )
    ledger = SQLiteExactFourTraderLedgerV2(
        ledger_path,
        environment=environment,
        credentials=credentials,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )
    return ExactFourTraderWebAuthnAuthorityV2(
        environment=environment,
        relying_parties=relying_parties,
        credentials=credentials,
        ledger=ledger,
        clock=clock,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )


def _load_live_activation_document() -> dict[str, Any]:
    path = TRADER_AUTHORITY_ACTIVATION_PATH
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise ExactFourAuthorityPending(TRADER_AUTHORITY_LIVE_STATE) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise ExactFourAuthorityPending(
            "Trader activation state is not a root-owned non-writable regular file"
        )
    document = _strict_json_loads(raw, label="Trader authority activation state")
    required = {
        "format",
        "environment",
        "service_uid",
        "controlled_execution_uid",
        "controlled_execution_socket_path",
        "store_path",
        "human_enrollment_observed",
        "protected_store_observed",
        "rp_registry",
        "credential_registry",
    }
    if set(document) != required or document.get("format") != (
        "exact-four-trader-authority-activation/v2"
    ):
        raise ExactFourAuthorityPending(
            "Trader activation state fields or format are invalid"
        )
    return document


def open_live_exact_four_trader_authority_v2() -> ExactFourTraderWebAuthnAuthorityV2:
    """Open only from fixed root-owned activation and observed OS/store state."""

    document = _load_live_activation_document()
    environment = document["environment"]
    service_uid = document["service_uid"]
    controlled_uid = document["controlled_execution_uid"]
    store_text = document["store_path"]
    controlled_socket_text = document["controlled_execution_socket_path"]
    if (
        environment not in {"staging", "production"}
        or type(service_uid) is not int
        or service_uid <= 0
        or type(controlled_uid) is not int
        or controlled_uid <= 0
        or controlled_uid == service_uid
        or os.geteuid() != service_uid
        or type(store_text) is not str
        or type(controlled_socket_text) is not str
        or document["human_enrollment_observed"] is not True
        or document["protected_store_observed"] is not True
    ):
        raise ExactFourAuthorityPending(
            "Trader principal, enrollment, or controlled peer is not observed"
        )
    controlled_socket_path = Path(controlled_socket_text)
    if not controlled_socket_path.is_absolute():
        raise ExactFourAuthorityPending(
            "controlled execution socket path is not absolute"
        )
    try:
        controlled_socket_stat = controlled_socket_path.lstat()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "controlled execution socket is not observed"
        ) from exc
    if (
        not stat.S_ISSOCK(controlled_socket_stat.st_mode)
        or controlled_socket_stat.st_uid != controlled_uid
        or controlled_socket_stat.st_mode & 0o002
    ):
        raise ExactFourAuthorityPending(
            "controlled execution socket identity or permissions are invalid"
        )
    store_path = Path(store_text)
    if not store_path.is_absolute() or not store_path.parent.exists():
        raise ExactFourAuthorityPending(
            "Trader protected store path is absent or not absolute"
        )
    parent_stat = store_path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != service_uid
        or parent_stat.st_mode & 0o077
    ):
        raise ExactFourAuthorityPending(
            "Trader store directory is not service-owned mode 0700"
        )
    if store_path.exists():
        store_stat = store_path.lstat()
        if (
            not stat.S_ISREG(store_stat.st_mode)
            or store_stat.st_uid != service_uid
            or store_stat.st_mode & 0o077
        ):
            raise ExactFourAuthorityPending(
                "Trader ledger is not service-owned and private"
            )
    rp_document = document["rp_registry"]
    if (
        type(rp_document) is not dict
        or set(rp_document) != {"generation", "entries"}
        or type(rp_document["entries"]) is not list
    ):
        raise ExactFourAuthorityPending("Trader RP activation registry is invalid")
    rp_entries: list[ExactFourTraderRelyingPartyV2] = []
    for row in rp_document["entries"]:
        if type(row) is not dict or set(row) != {
            "environment",
            "policy_id",
            "policy_generation",
            "rp_id",
            "origin",
            "effective_at",
            "status",
            "user_presence_required",
            "user_verification_required",
        }:
            raise ExactFourAuthorityPending(
                "Trader RP activation row is not closed"
            )
        rp_entries.append(ExactFourTraderRelyingPartyV2(**row))
    relying_parties = ExactFourTraderRelyingPartyRegistryV2(
        tuple(rp_entries), generation=rp_document["generation"]
    )
    credential_document = document["credential_registry"]
    if (
        type(credential_document) is not dict
        or set(credential_document) != {"registry_id", "generation", "credentials"}
        or type(credential_document["credentials"]) is not list
    ):
        raise ExactFourAuthorityPending(
            "Trader credential activation registry is invalid"
        )
    credential_entries: list[ExactFourTraderCredentialV2] = []
    for row in credential_document["credentials"]:
        required_fields = {
            "environment",
            "credential_id_base64url",
            "public_key_spki_der_base64",
            "rp_policy_digest",
            "effective_at",
            "initial_sign_count",
            "counter_mode",
            "status",
            "algorithm",
            "key_backend",
        }
        if type(row) is not dict or set(row) != required_fields:
            raise ExactFourAuthorityPending(
                "Trader credential activation row is not closed"
            )
        try:
            credential_id = _decode_canonical_base64url(
                row["credential_id_base64url"],
                label="activation credential id",
                minimum_bytes=16,
                maximum_bytes=1024,
            )
            encoded_key = row["public_key_spki_der_base64"]
            key_bytes = base64.b64decode(encoded_key, validate=True)
            if base64.b64encode(key_bytes).decode("ascii") != encoded_key:
                raise ValueError("non-canonical public key base64")
            public_key = serialization.load_der_public_key(key_bytes)
        except (TypeError, ValueError) as exc:
            raise ExactFourAuthorityPending(
                "Trader activation credential public material is invalid"
            ) from exc
        credential_entries.append(
            ExactFourTraderCredentialV2(
                environment=row["environment"],
                credential_id=credential_id,
                public_key=public_key,  # type: ignore[arg-type]
                rp_policy_digest=row["rp_policy_digest"],
                effective_at=row["effective_at"],
                initial_sign_count=row["initial_sign_count"],
                counter_mode=row["counter_mode"],
                status=row["status"],
                algorithm=row["algorithm"],
                key_backend=row["key_backend"],
            )
        )
    credentials = ExactFourTraderCredentialRegistryV2(
        tuple(credential_entries),
        generation=credential_document["generation"],
        registry_id=credential_document["registry_id"],
    )
    ledger = SQLiteExactFourTraderLedgerV2(
        store_path,
        environment=environment,
        credentials=credentials,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )
    return ExactFourTraderWebAuthnAuthorityV2(
        environment=environment,
        relying_parties=relying_parties,
        credentials=credentials,
        ledger=ledger,
        clock=lambda: datetime.now(timezone.utc),
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "ExactFourTraderAuthorityV2Error",
    "ExactFourTraderCredentialRegistryV2",
    "ExactFourTraderCredentialV2",
    "ExactFourTraderRelyingPartyRegistryV2",
    "ExactFourTraderRelyingPartyV2",
    "ExactFourTraderWebAuthnAuthorityV2",
    "CommittedExactFourTraderHandoffV2",
    "IssuedExactFourTraderChallengeV2",
    "TRADER_AUTHORITY_ACTIVATION_PATH",
    "TRADER_AUTHORITY_LIVE_STATE",
    "VerifiedReadyAuthorityEvidenceV2",
    "open_live_exact_four_trader_authority_v2",
    "verify_ready_authority_response_v2",
]
