"""Public, verify-only support for authenticated D1 mirror sync audits.

The former same-UID HOME-key path is retired.  Production minting remains
disabled until a separately provisioned full-source authority derives and
signs the entire D1 generation.  This module never loads private material.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


SIGNED_DOCUMENT_SCHEMA = "d1-sync-signed-audit/v1"
AUDIT_ENVELOPE_SCHEMA = "d1-sync-audit-envelope/v1"
REGISTRY_PURPOSE = "d1_sync_audit_verification"
GOVERNED_D1_NAME = "quant-ingest"
GOVERNED_D1_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
GOVERNED_AUTHORITY_ID = f"cloudflare-d1:{GOVERNED_D1_ID}"
D1_SYNC_AUDIT_MAX_AGE_SECONDS = 1_800
D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS = 60
DEFAULT_VERIFY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "d1_sync"
    / "verify_public_keys.json"
)

_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "authority_id",
        "source_mode",
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


class D1SyncAuditError(RuntimeError):
    """A D1 sync signing key, audit, or public registry is invalid."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_d1_sync_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def d1_sync_digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_d1_sync_bytes(value)).hexdigest()


def _is_digest(value: object) -> bool:
    text = str(value or "")
    return len(text) == 71 and text.startswith("sha256:") and all(
        character in "0123456789abcdef" for character in text[7:]
    )


def _decode_public_key(value: object) -> Ed25519PublicKey | None:
    try:
        raw = base64.b64decode(str(value), validate=True)
        if len(raw) != 32:
            return None
        return Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError):
        return None


def _load_registry_document() -> dict[str, Any]:
    try:
        raw = json.loads(DEFAULT_VERIFY_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise D1SyncAuditError("cannot load pinned D1 sync public-key registry") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "purpose",
        "keys",
    }:
        raise D1SyncAuditError("pinned D1 sync registry shape is invalid")
    if (
        raw.get("schema_version") != 1
        or raw.get("purpose") != REGISTRY_PURPOSE
        or not isinstance(raw.get("keys"), list)
        or not 1 <= len(raw["keys"]) <= 16
    ):
        raise D1SyncAuditError("pinned D1 sync registry policy is invalid")
    seen: set[str] = set()
    active = 0
    for candidate in raw["keys"]:
        if not isinstance(candidate, dict) or set(candidate) != {
            "key_id",
            "algorithm",
            "public_key_base64",
            "status",
        }:
            raise D1SyncAuditError("pinned D1 sync registry key shape is invalid")
        key_id = str(candidate.get("key_id") or "").strip()
        status_value = candidate.get("status")
        if (
            not key_id
            or key_id in seen
            or candidate.get("algorithm") != "Ed25519"
            or status_value not in {"active", "retired", "revoked"}
            or _decode_public_key(candidate.get("public_key_base64")) is None
        ):
            raise D1SyncAuditError("pinned D1 sync registry key is invalid")
        seen.add(key_id)
        active += int(status_value == "active")
    if active > 1:
        raise D1SyncAuditError(
            "pinned D1 sync registry cannot contain multiple active keys"
        )
    return raw


def _validate_envelope(
    envelope: Mapping[str, Any], *, require_fresh: bool
) -> None:
    if set(envelope) != _ENVELOPE_FIELDS:
        raise D1SyncAuditError("D1 sync audit envelope fields are not closed")
    if (
        envelope.get("schema_version") != AUDIT_ENVELOPE_SCHEMA
        or envelope.get("authority_id") != GOVERNED_AUTHORITY_ID
        or envelope.get("source_mode") != "WRANGLER_REMOTE"
        or envelope.get("d1_name") != GOVERNED_D1_NAME
        or envelope.get("d1_id") != GOVERNED_D1_ID
        or envelope.get("sync_kind") not in {"FULL", "INCREMENTAL"}
        or envelope.get("artifact_format") not in {"sql", "sqlite"}
    ):
        raise D1SyncAuditError("D1 sync audit authority or mode is invalid")
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
    if envelope["source_content_digest"] != envelope["local_content_digest"]:
        raise D1SyncAuditError("D1 sync audit source/local content differs")
    source_cursor = envelope.get("source_change_seq")
    applied_cursor = envelope.get("applied_change_seq")
    if (
        isinstance(source_cursor, bool)
        or not isinstance(source_cursor, int)
        or source_cursor < 0
        or applied_cursor != source_cursor
    ):
        raise D1SyncAuditError("D1 sync audit cursor chain is invalid")
    counts = envelope.get("table_counts")
    if not isinstance(counts, dict) or not counts:
        raise D1SyncAuditError("D1 sync audit table counts are missing")
    for table, count in counts.items():
        if (
            not isinstance(table, str)
            or not table
            or isinstance(count, bool)
            or not isinstance(count, int)
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
    if not isinstance(exported_at, str) or not isinstance(issued_at, str):
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
    if issued_utc + timedelta(seconds=D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS) < exported_utc:
        raise D1SyncAuditError("D1 sync audit issued_at predates exported_at")
    if require_fresh:
        now = _utc_now()
        if exported_utc > now + timedelta(
            seconds=D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS
        ) or issued_utc > now + timedelta(
            seconds=D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS
        ):
            raise D1SyncAuditError("signed D1 sync audit issued_at is in the future")
        if now - issued_utc > timedelta(seconds=D1_SYNC_AUDIT_MAX_AGE_SECONDS):
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


def _verify_signed_d1_sync_audit(
    document: object,
    *,
    require_fresh: bool,
    eligibility: str = "current",
) -> dict[str, Any]:
    if eligibility not in {"current", "historical"}:
        raise D1SyncAuditError("D1 sync audit eligibility is invalid")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError as exc:
            raise D1SyncAuditError("signed D1 sync audit is invalid JSON") from exc
    if not isinstance(document, dict) or set(document) != _DOCUMENT_FIELDS:
        raise D1SyncAuditError("signed D1 sync audit document shape is invalid")
    if (
        document.get("schema_version") != SIGNED_DOCUMENT_SCHEMA
        or document.get("algorithm") != "Ed25519"
        or not isinstance(document.get("issuer_key_id"), str)
        or not isinstance(document.get("envelope"), dict)
        or not isinstance(document.get("signature"), str)
    ):
        raise D1SyncAuditError("signed D1 sync audit document is invalid")
    envelope = document["envelope"]
    _validate_envelope(envelope, require_fresh=require_fresh)
    registry = _load_registry_document()
    matching = [
        row
        for row in registry["keys"]
        if row["key_id"] == document["issuer_key_id"]
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
        raise D1SyncAuditError("signed D1 sync audit issuer is not historically auditable")
    public_key = _decode_public_key(matching[0]["public_key_base64"])
    signature = document["signature"]
    if not signature.startswith("ed25519:") or public_key is None:
        raise D1SyncAuditError("signed D1 sync audit signature is malformed")
    try:
        signature_bytes = base64.b64decode(
            signature[len("ed25519:") :], validate=True
        )
        body = {key: document[key] for key in _DOCUMENT_FIELDS if key != "signature"}
        public_key.verify(signature_bytes, canonical_d1_sync_bytes(body))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise D1SyncAuditError("signed D1 sync audit signature is invalid") from exc
    return dict(envelope)


def verify_signed_d1_sync_audit(document: object) -> dict[str, Any]:
    """Verify one current closed audit using only the pinned public registry."""

    return _verify_signed_d1_sync_audit(
        document, require_fresh=True, eligibility="current"
    )


__all__ = [
    "AUDIT_ENVELOPE_SCHEMA",
    "D1SyncAuditError",
    "GOVERNED_AUTHORITY_ID",
    "GOVERNED_D1_ID",
    "GOVERNED_D1_NAME",
    "canonical_d1_sync_bytes",
    "d1_sync_digest",
    "verify_signed_d1_sync_audit",
]
