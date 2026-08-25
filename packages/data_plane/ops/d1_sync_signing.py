"""Dedicated Ed25519 authority for authenticated D1 mirror sync audits.

Only the private Wrangler acquisition path loads this key.  Projection and
READY readers use the committed public registry, so mutable SQLite audit rows
cannot assert that an export came from the governed production D1.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


SIGNED_DOCUMENT_SCHEMA = "d1-sync-signed-audit/v1"
AUDIT_ENVELOPE_SCHEMA = "d1-sync-audit-envelope/v1"
REGISTRY_PURPOSE = "d1_sync_audit_verification"
GOVERNED_D1_NAME = "quant-ingest"
GOVERNED_D1_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
GOVERNED_AUTHORITY_ID = f"cloudflare-d1:{GOVERNED_D1_ID}"
DEFAULT_SIGNING_KEY_PATH = (
    Path.home() / ".config" / "quant-platform" / "d1_sync_signing_key.pem"
)
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
        "schema_digest",
        "table_counts",
        "prior_audit_digest",
        "registry_digest",
        "issued_at",
    }
)
_DOCUMENT_FIELDS = frozenset(
    {"schema_version", "algorithm", "issuer_key_id", "envelope", "signature"}
)


class D1SyncAuditError(RuntimeError):
    """A D1 sync signing key, audit, or public registry is invalid."""


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
            or status_value not in {"active", "retired"}
            or _decode_public_key(candidate.get("public_key_base64")) is None
        ):
            raise D1SyncAuditError("pinned D1 sync registry key is invalid")
        seen.add(key_id)
        active += int(status_value == "active")
    if active != 1:
        raise D1SyncAuditError(
            "pinned D1 sync registry must contain exactly one active key"
        )
    return raw


def _validate_envelope(envelope: Mapping[str, Any]) -> None:
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
    issued_at = envelope.get("issued_at")
    if not isinstance(issued_at, str):
        raise D1SyncAuditError("D1 sync audit issued_at is invalid")
    try:
        parsed = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise D1SyncAuditError("D1 sync audit issued_at is invalid") from exc
    if parsed.tzinfo is None:
        raise D1SyncAuditError("D1 sync audit issued_at must include a timezone")


@dataclass(frozen=True)
class _D1SyncAuditSigner:
    key_id: str
    _private_key: Ed25519PrivateKey
    _registry_digest: str

    def sign(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        _validate_envelope(envelope)
        if envelope.get("registry_digest") != self._registry_digest:
            raise D1SyncAuditError("D1 sync audit registry digest is not pinned")
        body = {
            "schema_version": SIGNED_DOCUMENT_SCHEMA,
            "algorithm": "Ed25519",
            "issuer_key_id": self.key_id,
            "envelope": dict(envelope),
        }
        signature = self._private_key.sign(canonical_d1_sync_bytes(body))
        return {
            **body,
            "signature": "ed25519:" + base64.b64encode(signature).decode("ascii"),
        }


def _load_pinned_d1_sync_signer() -> _D1SyncAuditSigner:
    """Load the fixed host key and derive its id from the committed registry.

    There is deliberately no path, PEM, key-id, environment, or registry
    argument. Missing or overly permissive private material is fail-closed.
    """

    try:
        metadata = DEFAULT_SIGNING_KEY_PATH.lstat()
    except OSError as exc:
        raise D1SyncAuditError("dedicated D1 sync signing key is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise D1SyncAuditError("dedicated D1 sync signing key permissions are invalid")
    try:
        private_key = serialization.load_pem_private_key(
            DEFAULT_SIGNING_KEY_PATH.read_bytes(), password=None
        )
    except (OSError, TypeError, ValueError) as exc:
        raise D1SyncAuditError("dedicated D1 sync signing key PEM is invalid") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise D1SyncAuditError("dedicated D1 sync signing key must be Ed25519")

    registry = _load_registry_document()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    matching = []
    for row in registry["keys"]:
        if row["status"] != "active":
            continue
        try:
            registered = base64.b64decode(row["public_key_base64"], validate=True)
        except (TypeError, ValueError):  # validated above; defensive only
            continue
        if registered == public_raw:
            matching.append(row["key_id"])
    if len(matching) != 1:
        raise D1SyncAuditError(
            "dedicated D1 sync key does not match exactly one active registry key"
        )
    return _D1SyncAuditSigner(
        key_id=matching[0],
        _private_key=private_key,
        _registry_digest=d1_sync_digest(registry),
    )


def verify_signed_d1_sync_audit(document: object) -> dict[str, Any]:
    """Verify one closed signed audit using only the pinned public registry."""

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
    _validate_envelope(envelope)
    registry = _load_registry_document()
    if envelope["registry_digest"] != d1_sync_digest(registry):
        raise D1SyncAuditError("signed D1 sync audit registry digest is stale")
    matching = [
        row
        for row in registry["keys"]
        if row["key_id"] == document["issuer_key_id"] and row["status"] == "active"
    ]
    if len(matching) != 1:
        raise D1SyncAuditError("signed D1 sync audit issuer is not active")
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
