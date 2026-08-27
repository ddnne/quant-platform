"""Public, verify-only support for authenticated D1 mirror sync audits.

The former same-UID HOME-key path is retired.  Production minting remains
disabled until a separately provisioned full-source authority derives and
signs the entire D1 generation.  This module never loads private material.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ops.trust_domain import (
    d1_resource_identity,
    require_d1_resource_identity,
    require_environment,
)


SIGNED_DOCUMENT_SCHEMA = "d1-sync-signed-audit/v1"
AUDIT_ENVELOPE_SCHEMA = "d1-sync-audit-envelope/v1"
REGISTRY_PURPOSE = "d1_sync_audit_verification"
GOVERNED_D1_NAME = "quant-ingest"
GOVERNED_D1_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
GOVERNED_AUTHORITY_ID = f"cloudflare-d1:{GOVERNED_D1_ID}"
STAGING_D1_NAME = "quant-ingest-staging"
STAGING_D1_ID = "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb"
D1_SYNC_AUDIT_MAX_AGE_SECONDS = 1_800
D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS = 60
_PINNED_VERIFY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "d1_sync"
    / "verify_public_keys.json"
)
_PINNED_STAGING_VERIFY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "d1_sync"
    / "verify_public_keys.staging.json"
)
PINNED_D1_SYNC_REGISTRY_GENERATION = 2
# These values are an independent code pin. Replacing or redirecting the JSON
# cannot replace the production trust root without a reviewed code change.
PINNED_D1_SYNC_PRIOR_REGISTRY_DIGEST = (
    "sha256:6e632d3e2d5753b0ab7ea5b1959084c78c44d764805bd69b952def2dac7bd0c7"
)
PINNED_D1_SYNC_REGISTRY_BODY_DIGEST = (
    "sha256:90b0e08c7098b3662f1ea805ffdf7acfc0b22304795f013623d7232fdb933644"
)
PINNED_D1_SYNC_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:e469f909faddcfbf8702f07a3a9f6bce5605b4b1252433bee31675c3ba67a60a"
)
PINNED_STAGING_D1_SYNC_REGISTRY_GENERATION = 1
PINNED_STAGING_D1_SYNC_PRIOR_REGISTRY_DIGEST = None
PINNED_STAGING_D1_SYNC_REGISTRY_BODY_DIGEST = (
    "sha256:0db8ec5977a98a265d20f34d6ae95d09d3af39926c62a061671868f3a3250489"
)
PINNED_STAGING_D1_SYNC_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:0229b1e65bc7ce1980669954fba295b8ecdba55607d0001f37b3f33263396f43"
)

_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "authority_id",
        "source_mode",
        "environment",
        "resource_identity",
        "d1_name",
        "d1_id",
        "sync_kind",
        "export_digest",
        "artifact_format",
        "source_change_seq",
        "applied_change_seq",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
        "table_counts",
        "prior_audit_digest",
        "registry_digest",
        "exported_at",
        "issued_at",
    }
)
_DOCUMENT_FIELDS = frozenset(
    {"schema_version", "algorithm", "issuer_key_id", "envelope", "signature"}
)
_REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        "purpose",
        "generation",
        "authority_status",
        "prior_registry_digest",
        "keys",
        "registry_digest",
    }
)
_REGISTRY_KEY_FIELDS = frozenset(
    {"key_id", "algorithm", "public_key_base64", "status"}
)


class D1SyncAuditError(RuntimeError):
    """A D1 sync signing key, audit, or public registry is invalid."""


@dataclass(frozen=True, slots=True)
class _VerifiedD1SyncAuditDocument:
    """Private immutable facts from one strict decode and signature check."""

    envelope: Mapping[str, Any]
    issuer_key_id: str
    signature: str
    document_digest: str
    canonical_document_json: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_d1_sync_bytes(value: dict[str, Any]) -> bytes:
    """Canonicalize one exact JSON object; adapters are not an input contract."""

    if type(value) is not dict:
        raise TypeError("D1 sync canonical input must be one exact dict")
    frozen = _copy_exact_json(value, field="D1 sync canonical input")
    assert type(frozen) is dict
    return json.dumps(
        frozen,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def d1_sync_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_d1_sync_bytes(value)).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _decode_public_key(value: object) -> Ed25519PublicKey | None:
    if type(value) is not str:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 32:
            return None
        return Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError):
        return None


def _copy_exact_json(value: Any, *, field: str) -> Any:
    """Take one snapshot and reject adapters and scalar subclasses."""

    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in dict.items(value):
            if type(key) is not str or key in copied:
                raise D1SyncAuditError(f"{field} keys must be unique exact strings")
            copied[key] = _copy_exact_json(item, field=f"{field}.{key}")
        return copied
    if type(value) is list:
        return [
            _copy_exact_json(item, field=f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise D1SyncAuditError(
        f"{field} must contain only exact finite JSON built-in values"
    )


def _decode_strict_json(raw: bytes | str, *, field: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise D1SyncAuditError(f"{field} contains duplicate key {key!r}")
            document[key] = value
        return document

    def reject_nonfinite(value: str) -> None:
        raise D1SyncAuditError(f"{field} contains non-finite value {value!r}")

    try:
        document = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except D1SyncAuditError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D1SyncAuditError(f"{field} is invalid JSON") from exc
    frozen = _copy_exact_json(document, field=field)
    if type(frozen) is not dict:
        raise D1SyncAuditError(f"{field} must be an object")
    return frozen


def _deep_immutable(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_immutable(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_immutable(item) for item in value)
    return value


def _registry_body_digest(document: dict[str, Any]) -> str:
    return d1_sync_digest(
        {key: value for key, value in document.items() if key != "registry_digest"}
    )


def _registry_contract(environment: str) -> tuple[Path, int, str | None, str, str]:
    selected = require_environment(environment)
    if selected == "staging":
        return (
            _PINNED_STAGING_VERIFY_REGISTRY_PATH,
            PINNED_STAGING_D1_SYNC_REGISTRY_GENERATION,
            PINNED_STAGING_D1_SYNC_PRIOR_REGISTRY_DIGEST,
            PINNED_STAGING_D1_SYNC_REGISTRY_BODY_DIGEST,
            PINNED_STAGING_D1_SYNC_REGISTRY_DOCUMENT_DIGEST,
        )
    return (
        _PINNED_VERIFY_REGISTRY_PATH,
        PINNED_D1_SYNC_REGISTRY_GENERATION,
        PINNED_D1_SYNC_PRIOR_REGISTRY_DIGEST,
        PINNED_D1_SYNC_REGISTRY_BODY_DIGEST,
        PINNED_D1_SYNC_REGISTRY_DOCUMENT_DIGEST,
    )


def registry_document_digest(environment: str) -> str:
    return _registry_contract(environment)[4]


def _load_registry_document(environment: str = "production") -> dict[str, Any]:
    path, generation, prior_digest, body_digest, document_digest = (
        _registry_contract(environment)
    )
    try:
        raw = path.read_bytes()
        document = _decode_strict_json(raw, field="pinned D1 sync registry")
    except (OSError, D1SyncAuditError) as exc:
        raise D1SyncAuditError(
            "cannot load pinned D1 sync public-key registry"
        ) from exc
    if d1_sync_digest(document) != document_digest:
        raise D1SyncAuditError("pinned D1 sync registry digest mismatch")
    if (
        set(document) != _REGISTRY_FIELDS
        or type(document.get("schema_version")) is not int
        or document.get("schema_version") != 2
        or document.get("purpose") != REGISTRY_PURPOSE
        or type(document.get("generation")) is not int
        or document.get("generation") != generation
        or document.get("authority_status") not in {"ACTIVE", "PENDING"}
        or document.get("prior_registry_digest")
        != prior_digest
        or document.get("registry_digest")
        != body_digest
        or _registry_body_digest(document) != body_digest
    ):
        raise D1SyncAuditError("pinned D1 sync registry policy is invalid")
    rows = document.get("keys")
    if type(rows) is not list or len(rows) > 16:
        raise D1SyncAuditError("pinned D1 sync registry keys are invalid")
    seen: set[str] = set()
    active = 0
    for candidate in rows:
        if (
            type(candidate) is not dict
            or set(candidate) != _REGISTRY_KEY_FIELDS
        ):
            raise D1SyncAuditError("pinned D1 sync registry key shape is invalid")
        if any(type(candidate[field]) is not str for field in _REGISTRY_KEY_FIELDS):
            raise D1SyncAuditError("pinned D1 sync registry key is invalid")
        key_id = candidate["key_id"].strip()
        status_value = candidate.get("status")
        if (
            not key_id
            or key_id in seen
            or candidate.get("algorithm") != "Ed25519"
            or status_value not in {"active", "pending", "retired", "revoked"}
            or _decode_public_key(candidate.get("public_key_base64")) is None
        ):
            raise D1SyncAuditError("pinned D1 sync registry key is invalid")
        seen.add(key_id)
        active += int(status_value == "active")
    expected_active = 1 if document["authority_status"] == "ACTIVE" else 0
    if active != expected_active:
        raise D1SyncAuditError(
            "pinned D1 sync registry active keys do not match authority status"
        )
    return document


def _validate_envelope(
    envelope: Mapping[str, Any], *, expected_environment: str
) -> tuple[datetime, datetime]:
    expected_environment = require_environment(expected_environment)
    expected_resource = dict(d1_resource_identity(expected_environment))
    if type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS:
        raise D1SyncAuditError("D1 sync audit envelope fields are not closed")
    if (
        envelope.get("schema_version") != AUDIT_ENVELOPE_SCHEMA
        or envelope.get("environment") != expected_environment
        or envelope.get("resource_identity") != expected_resource
        or envelope.get("authority_id") != expected_resource["authority_id"]
        or envelope.get("source_mode") != "WRANGLER_REMOTE"
        or envelope.get("d1_name") != expected_resource["name"]
        or envelope.get("d1_id") != expected_resource["database_id"]
        or envelope.get("sync_kind") not in {"FULL", "INCREMENTAL"}
        or envelope.get("artifact_format") not in {"sql", "sqlite"}
    ):
        raise D1SyncAuditError("D1 sync audit authority or mode is invalid")
    for field in (
        "schema_version",
        "authority_id",
        "source_mode",
        "environment",
        "d1_name",
        "d1_id",
        "sync_kind",
        "artifact_format",
    ):
        if type(envelope[field]) is not str:
            raise D1SyncAuditError(f"D1 sync audit {field} is invalid")
    for field in (
        "export_digest",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
        "registry_digest",
    ):
        if not _is_digest(envelope.get(field)):
            raise D1SyncAuditError(f"D1 sync audit {field} is invalid")
    try:
        require_d1_resource_identity(
            envelope["resource_identity"],
            expected_environment=expected_environment,
        )
    except ValueError as exc:
        raise D1SyncAuditError("D1 sync resource identity is invalid") from exc
    if envelope["registry_digest"] != registry_document_digest(expected_environment):
        raise D1SyncAuditError("D1 sync audit registry digest is not pinned")
    if envelope["source_content_digest"] != envelope["local_content_digest"]:
        raise D1SyncAuditError("D1 sync audit source/local content differs")
    source_cursor = envelope.get("source_change_seq")
    applied_cursor = envelope.get("applied_change_seq")
    if (
        type(source_cursor) is not int
        or source_cursor < 0
        or type(applied_cursor) is not int
        or applied_cursor != source_cursor
    ):
        raise D1SyncAuditError("D1 sync audit cursor chain is invalid")
    counts = envelope.get("table_counts")
    if type(counts) is not dict or not counts:
        raise D1SyncAuditError("D1 sync audit table counts are missing")
    for table, count in dict.items(counts):
        if (
            type(table) is not str
            or not table
            or type(count) is not int
            or count < 0
        ):
            raise D1SyncAuditError("D1 sync audit table counts are invalid")
    prior = envelope.get("prior_audit_digest")
    if envelope["sync_kind"] == "FULL":
        if prior is not None:
            raise D1SyncAuditError("full D1 sync audit cannot claim a prior audit")
    elif not _is_digest(prior):
        raise D1SyncAuditError("incremental D1 sync audit requires a prior digest")
    exported_at = envelope.get("exported_at")
    issued_at = envelope.get("issued_at")
    if type(exported_at) is not str or type(issued_at) is not str:
        raise D1SyncAuditError("D1 sync audit timestamps are invalid")
    try:
        exported_parsed = datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
        issued_parsed = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise D1SyncAuditError("D1 sync audit timestamps are invalid") from exc
    if exported_parsed.tzinfo is None or issued_parsed.tzinfo is None:
        raise D1SyncAuditError("D1 sync audit timestamps must include a timezone")
    exported_utc = exported_parsed.astimezone(timezone.utc)
    issued_utc = issued_parsed.astimezone(timezone.utc)
    if (
        issued_utc + timedelta(seconds=D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS)
        < exported_utc
    ):
        raise D1SyncAuditError("D1 sync audit issued_at predates exported_at")
    return exported_utc, issued_utc


def _require_fresh_audit(exported_utc: datetime, issued_utc: datetime) -> None:
    """Apply the internal clock only at the final verified return boundary."""

    now = _utc_now()
    if exported_utc > now + timedelta(
        seconds=D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS
    ) or issued_utc > now + timedelta(
        seconds=D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS
    ):
        raise D1SyncAuditError("signed D1 sync audit issued_at is in the future")
    if (
        now - issued_utc > timedelta(seconds=D1_SYNC_AUDIT_MAX_AGE_SECONDS)
        or now - exported_utc
        > timedelta(seconds=D1_SYNC_AUDIT_MAX_AGE_SECONDS)
    ):
        raise D1SyncAuditError("signed D1 sync audit is stale")


def _preflight_d1_sync_signing_authority() -> None:
    """Fail before acquisition while the full-source authority is absent."""
    raise D1SyncAuditError(
        "dedicated D1 full-source authority is not provisioned; sync is UNKNOWN"
    )


def _bind_authenticated_export_authority(_export_type: type, _consume: Any) -> None:
    """Compatibility hook only; it grants no signing capability."""


def _seal_authenticated_wrangler_export(_authenticated_export: object) -> None:
    """Fail closed; same-process reconciled facts cannot mint COMPLETE."""
    raise D1SyncAuditError(
        "dedicated D1 full-source authority is not provisioned; sync is UNKNOWN"
    )


def _verify_signed_d1_sync_audit_document(
    document: object,
    *,
    require_fresh: bool,
    eligibility: str = "current",
    expected_environment: str | None = None,
) -> _VerifiedD1SyncAuditDocument:
    if type(eligibility) is not str or eligibility not in {
        "current",
        "historical",
    }:
        raise D1SyncAuditError("D1 sync audit eligibility is invalid")
    if type(document) is str:
        frozen = _decode_strict_json(document, field="signed D1 sync audit")
    else:
        frozen = _copy_exact_json(document, field="signed D1 sync audit")
    if type(frozen) is not dict or set(frozen) != _DOCUMENT_FIELDS:
        raise D1SyncAuditError("signed D1 sync audit document shape is invalid")
    if (
        frozen.get("schema_version") != SIGNED_DOCUMENT_SCHEMA
        or frozen.get("algorithm") != "Ed25519"
        or type(frozen.get("schema_version")) is not str
        or type(frozen.get("algorithm")) is not str
        or type(frozen.get("issuer_key_id")) is not str
        or type(frozen.get("envelope")) is not dict
        or type(frozen.get("signature")) is not str
    ):
        raise D1SyncAuditError("signed D1 sync audit document is invalid")
    envelope = frozen["envelope"]
    if expected_environment is None:
        try:
            expected_environment = require_environment(envelope.get("environment"))
        except ValueError as exc:
            raise D1SyncAuditError("D1 sync environment is invalid") from exc
    exported_utc, issued_utc = _validate_envelope(
        envelope, expected_environment=expected_environment
    )
    registry = _load_registry_document(expected_environment)
    matching = [
        row
        for row in registry["keys"]
        if row["key_id"] == frozen["issuer_key_id"]
    ]
    if len(matching) != 1:
        raise D1SyncAuditError("signed D1 sync audit issuer is unknown")
    status = matching[0]["status"]
    if eligibility == "current":
        if status != "active":
            raise D1SyncAuditError("signed D1 sync audit issuer is not active")
    elif status == "revoked":
        raise D1SyncAuditError("signed D1 sync audit issuer is revoked")
    elif status not in {"active", "retired"}:
        raise D1SyncAuditError(
            "signed D1 sync audit issuer is not historically auditable"
        )
    public_key = _decode_public_key(matching[0]["public_key_base64"])
    signature = frozen["signature"]
    if not signature.startswith("ed25519:") or public_key is None:
        raise D1SyncAuditError("signed D1 sync audit signature is malformed")
    try:
        signature_bytes = base64.b64decode(
            signature[len("ed25519:") :], validate=True
        )
        body = {key: frozen[key] for key in _DOCUMENT_FIELDS if key != "signature"}
        public_key.verify(signature_bytes, canonical_d1_sync_bytes(body))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise D1SyncAuditError("signed D1 sync audit signature is invalid") from exc
    canonical_document = canonical_d1_sync_bytes(frozen)
    verified = _VerifiedD1SyncAuditDocument(
        envelope=_deep_immutable(envelope),
        issuer_key_id=frozen["issuer_key_id"],
        signature=signature,
        document_digest="sha256:" + hashlib.sha256(canonical_document).hexdigest(),
        canonical_document_json=canonical_document.decode("utf-8"),
    )
    if require_fresh:
        _require_fresh_audit(exported_utc, issued_utc)
    return verified


def _verify_signed_d1_sync_audit(
    document: object,
    *,
    require_fresh: bool,
    eligibility: str = "current",
    expected_environment: str | None = None,
) -> Mapping[str, Any]:
    return _verify_signed_d1_sync_audit_document(
        document,
        require_fresh=require_fresh,
        eligibility=eligibility,
        expected_environment=expected_environment,
    ).envelope


def verify_signed_d1_sync_audit(
    document: object, *, expected_environment: str
) -> Mapping[str, Any]:
    """Verify one current closed audit using only the pinned public registry."""

    return _verify_signed_d1_sync_audit(
        document,
        require_fresh=True,
        eligibility="current",
        expected_environment=expected_environment,
    )


__all__ = [
    "AUDIT_ENVELOPE_SCHEMA",
    "D1SyncAuditError",
    "GOVERNED_AUTHORITY_ID",
    "GOVERNED_D1_ID",
    "GOVERNED_D1_NAME",
    "STAGING_D1_ID",
    "STAGING_D1_NAME",
    "PINNED_D1_SYNC_PRIOR_REGISTRY_DIGEST",
    "PINNED_D1_SYNC_REGISTRY_BODY_DIGEST",
    "PINNED_D1_SYNC_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_D1_SYNC_REGISTRY_GENERATION",
    "canonical_d1_sync_bytes",
    "d1_sync_digest",
    "registry_document_digest",
    "verify_signed_d1_sync_audit",
]
