"""Public, verify-only cryptography for immutable Ops Projection envelopes.

Production minting belongs to the ingestion-premium cloud publisher, which
derives the envelope from governed source observations.  This local module is
verify-only: it has no private-key loader or caller-envelope signing API.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ops.projection_content import PROJECTED_CONTENT_TABLES, projection_content_digest
from ops.trust_domain import projection_resource_identity, require_environment


SIGNED_DOCUMENT_SCHEMA = "ops-projection-signed-envelope/v1"
ENVELOPE_SCHEMA = "ops-projection-envelope/v1"
_CANONICAL_PRODUCTION_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ops_projection"
    / "verify_public_keys.json"
)
_CANONICAL_STAGING_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ops_projection"
    / "verify_public_keys.staging.json"
)
_PINNED_VERIFY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ops_projection"
    / "verify_public_keys.json"
)
_PINNED_STAGING_VERIFY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ops_projection"
    / "verify_public_keys.staging.json"
)
PINNED_OPS_PROJECTION_REGISTRY_GENERATION = 3
# These four values are an independent code pin.  Replacing the checked-in
# JSON (or redirecting its path) cannot replace the production trust root.
# They are updated atomically with the governed registry document.
PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST = (
    "sha256:bb1dc1ae823784db8b53147891d425b027c02cbf022023a74affa2ce46909abe"
)
PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST = (
    "sha256:32bd179616eb9e848a47d56c38c2e12b243249b05321a0999fed53d22cd47362"
)
PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:5bebf8906b263fd9a2edf295a4e1e64e0a5a7e52bb3160123c455ebc3d39dadb"
)
PINNED_STAGING_OPS_PROJECTION_REGISTRY_GENERATION = 2
PINNED_STAGING_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST = None
PINNED_STAGING_OPS_PROJECTION_REGISTRY_BODY_DIGEST = (
    "sha256:c97a025ecf3525e8405cac95ffae73393e687ecba5111165a8a71d4ebc99af1e"
)
PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:093fb04a3530cb094b4c4eaf2bbd92f9813706c12a885aa70931fbc4d605b7b9"
)


class OpsProjectionSignatureError(RuntimeError):
    """Projection envelope is unsigned, malformed, or unverifiable."""


_CANONICAL_UTC = __import__("re").compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)


def require_canonical_utc(value: object, *, label: str = "timestamp") -> str:
    if type(value) is not str or _CANONICAL_UTC.fullmatch(value) is None:
        raise OpsProjectionSignatureError(f"{label} is not canonical UTC")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    if canonical != value or parsed.tzinfo is not timezone.utc:
        raise OpsProjectionSignatureError(f"{label} is not canonical UTC")
    return value


@dataclass(frozen=True, slots=True)
class _VerifiedOpsProjectionDocument:
    """Private immutable identity from one signed-document observation."""

    envelope: Mapping[str, Any]
    issuer_key_id: str
    document_digest: str


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    if type(value) is not dict:
        raise TypeError("Ops Projection canonical input must be one exact dict")
    frozen = _copy_exact_json(value, field="Ops Projection canonical input")
    assert type(frozen) is dict
    return json.dumps(
        frozen,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _copy_exact_json(value: Any, *, field: str) -> Any:
    """Take one JSON snapshot and reject adapters and scalar subclasses."""
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in dict.items(value):
            if type(key) is not str or key in copied:
                raise OpsProjectionSignatureError(
                    f"{field} keys must be unique exact strings"
                )
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
    raise OpsProjectionSignatureError(
        f"{field} must contain only exact finite JSON built-in values"
    )


def _decode_strict_json(raw: bytes | str, *, field: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise OpsProjectionSignatureError(
                    f"{field} contains duplicate key {key!r}"
                )
            document[key] = value
        return document

    def reject_nonfinite(value: str) -> None:
        raise OpsProjectionSignatureError(
            f"{field} contains non-finite value {value!r}"
        )

    try:
        document = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except OpsProjectionSignatureError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpsProjectionSignatureError(f"{field} is invalid JSON") from exc
    frozen = _copy_exact_json(document, field=field)
    if type(frozen) is not dict:
        raise OpsProjectionSignatureError(f"{field} must be an object")
    return frozen


def _deep_immutable(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_immutable(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_immutable(item) for item in value)
    return value


def _signed_body(*, key_id: str, envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SIGNED_DOCUMENT_SCHEMA,
        "algorithm": "Ed25519",
        "issuer_key_id": key_id,
        "envelope": envelope,
    }


def _validate_envelope(
    envelope: Mapping[str, Any], *, expected_environment: str
) -> None:
    try:
        expected_environment = require_environment(expected_environment)
    except ValueError as exc:
        raise OpsProjectionSignatureError("invalid environment") from exc
    required = {
        "schema_version",
        "environment",
        "resource_identity",
        "generation_id",
        "content_digest",
        "source_db_digest",
        "generated_at",
        "producer_commit_sha",
        "worker_version_id",
        "contract_digest",
        "registry_digest",
        "coverage_policy_version",
        "coverage_policy_digest",
        "projection_status",
        "source_generation",
        "source_snapshot_generation",
        "source_cursor",
        "export_cursor",
        "applied_cursor",
        "coverage_status_digest",
        "dataset_coverage",
        "b0_status",
        "b0_evidence_digest",
        "b4_status",
        "b4_evidence_digest",
        "evidence_digests",
        "content_manifest",
        "row_counts",
    }
    if type(envelope) is not dict or set(envelope) != required:
        raise OpsProjectionSignatureError(
            "Ops Projection envelope fields are not closed"
        )
    if envelope.get("schema_version") != ENVELOPE_SCHEMA:
        raise OpsProjectionSignatureError("unsupported Ops Projection envelope schema")
    if envelope.get("environment") != expected_environment:
        raise OpsProjectionSignatureError("Ops Projection environment mismatch")
    resource = envelope.get("resource_identity")
    if type(resource) is not dict or resource.get("environment") != expected_environment:
        raise OpsProjectionSignatureError("Ops Projection resource identity invalid")
    try:
        expected_resource = projection_resource_identity(
            environment=expected_environment,
            source={
                "resource_identity": resource.get("source_d1"),
                "audit_digest": resource.get("source_audit_digest"),
                "export_digest": resource.get("source_export_digest"),
                "source_change_seq": resource.get("source_change_seq"),
            },
        )
    except ValueError as exc:
        raise OpsProjectionSignatureError("Ops Projection resource identity invalid") from exc
    if resource != expected_resource:
        raise OpsProjectionSignatureError("Ops Projection resource identity invalid")
    for field in (
        "generation_id",
        "generated_at",
        "producer_commit_sha",
        "worker_version_id",
        "coverage_policy_version",
        "projection_status",
    ):
        if type(envelope[field]) is not str or not envelope[field]:
            raise OpsProjectionSignatureError(f"invalid {field}")
    require_canonical_utc(envelope["generated_at"], label="generated_at")
    import re as _re
    if _re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        str(envelope.get("worker_version_id") or ""),
    ) is None:
        raise OpsProjectionSignatureError("invalid worker_version_id")
    if envelope.get("worker_version_id") == envelope.get("producer_commit_sha"):
        raise OpsProjectionSignatureError("invalid worker_version_id")
    for field in (
        "content_digest",
        "source_db_digest",
        "contract_digest",
        "registry_digest",
        "coverage_status_digest",
        "coverage_policy_digest",
        "b0_evidence_digest",
        "b4_evidence_digest",
    ):
        value = envelope.get(field)
        if (
            type(value) is not str
            or not value.startswith("sha256:")
            or len(value) != 71
            or any(character not in "0123456789abcdef" for character in value[7:])
        ):
            raise OpsProjectionSignatureError(f"invalid {field}")
    if envelope.get("b0_status") not in {"PASS", "FAIL", "UNKNOWN"}:
        raise OpsProjectionSignatureError("invalid b0_status")
    if envelope.get("b4_status") not in {"PASS", "FAIL", "UNKNOWN"}:
        raise OpsProjectionSignatureError("invalid b4_status")
    if envelope.get("projection_status") not in {"FRESH", "STALE", "FAILED", "UNKNOWN"}:
        raise OpsProjectionSignatureError("invalid projection_status")
    for field in ("source_generation", "source_cursor", "export_cursor", "applied_cursor"):
        value = envelope.get(field)
        if value is not None and (
            type(value) is not int or value < 0
        ):
            raise OpsProjectionSignatureError(f"invalid {field}")
    snapshot_generation = envelope.get("source_snapshot_generation")
    if snapshot_generation is not None and (
        type(snapshot_generation) not in {str, int}
        or type(snapshot_generation) is int and snapshot_generation < 0
        or type(snapshot_generation) is str and not snapshot_generation
    ):
        raise OpsProjectionSignatureError("invalid source_snapshot_generation")
    if type(envelope.get("evidence_digests")) is not dict:
        raise OpsProjectionSignatureError("evidence_digests must be an object")
    for key, value in envelope["evidence_digests"].items():
        if (
            type(key) is not str
            or not key
            or type(value) is not str
            or not value.startswith("sha256:")
            or len(value) != 71
            or any(character not in "0123456789abcdef" for character in value[7:])
        ):
            raise OpsProjectionSignatureError("evidence_digests row is invalid")
    if type(envelope.get("dataset_coverage")) is not dict:
        raise OpsProjectionSignatureError("dataset_coverage must be an object")
    dataset_fields = {
        "status",
        "coverage_mode",
        "policy_id",
        "policy_version",
        "policy_digest",
        "collection_scope",
        "observed_start",
        "observed_end",
    }
    for dataset_id, row in envelope["dataset_coverage"].items():
        if (
            type(dataset_id) is not str
            or not dataset_id
            or type(row) is not dict
            or set(row) != dataset_fields
        ):
            raise OpsProjectionSignatureError("dataset_coverage rows must be named objects")
        if row.get("policy_id") != dataset_id:
            raise OpsProjectionSignatureError(
                f"dataset_coverage policy_id mismatch for {dataset_id}"
            )
        if type(row.get("policy_version")) is not str or not row["policy_version"]:
            raise OpsProjectionSignatureError(
                f"dataset_coverage policy_version missing for {dataset_id}"
            )
        policy_digest = row.get("policy_digest")
        if (
            type(policy_digest) is not str
            or not policy_digest.startswith("sha256:")
            or len(policy_digest) != 71
            or any(
                character not in "0123456789abcdef"
                for character in policy_digest[7:]
            )
        ):
            raise OpsProjectionSignatureError(
                f"dataset_coverage policy_digest invalid for {dataset_id}"
            )
        for field in ("status", "coverage_mode", "collection_scope"):
            if type(row.get(field)) is not str:
                raise OpsProjectionSignatureError(
                    f"dataset_coverage {field} invalid for {dataset_id}"
                )
        for field in ("observed_start", "observed_end"):
            if row.get(field) is not None and type(row[field]) is not str:
                raise OpsProjectionSignatureError(
                    f"dataset_coverage {field} invalid for {dataset_id}"
                )
    if type(envelope.get("row_counts")) is not dict:
        raise OpsProjectionSignatureError("row_counts must be an object")
    content_manifest = envelope.get("content_manifest")
    row_counts = envelope["row_counts"]
    if type(content_manifest) is not dict:
        raise OpsProjectionSignatureError("content_manifest must be an object")
    expected_tables = set(PROJECTED_CONTENT_TABLES)
    if set(content_manifest) != expected_tables or set(row_counts) != expected_tables:
        raise OpsProjectionSignatureError(
            "Ops Projection content manifest membership drift"
        )
    normalized_manifest: dict[str, dict[str, Any]] = {}
    for table in PROJECTED_CONTENT_TABLES:
        row = content_manifest.get(table)
        if type(row) is not dict or set(row) != {
            "content_digest",
            "row_count",
        }:
            raise OpsProjectionSignatureError(
                f"invalid content manifest row for {table}"
            )
        count = row.get("row_count")
        digest = str(row.get("content_digest") or "")
        if (
            type(count) is not int
            or count < 0
            or type(row_counts.get(table)) is not int
            or row_counts.get(table) != count
            or type(row.get("content_digest")) is not str
            or not digest.startswith("sha256:")
            or len(digest) != 71
            or any(character not in "0123456789abcdef" for character in digest[7:])
        ):
            raise OpsProjectionSignatureError(
                f"invalid content manifest row for {table}"
            )
        normalized_manifest[table] = {
            "row_count": count,
            "content_digest": digest,
        }
    if projection_content_digest({"tables": normalized_manifest}) != envelope.get(
        "content_digest"
    ):
        raise OpsProjectionSignatureError(
            "Ops Projection content digest does not bind its manifest"
        )


def open_ops_projection_signing_service() -> None:
    """Return the explicit PENDING state; no production signer is provisioned."""

    return None


_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "generation",
    "authority_status",
    "authority_instance",
    "prior_registry_digest",
    "keys",
    "registry_digest",
}
_REGISTRY_KEY_FIELDS = {
    "key_id",
    "algorithm",
    "public_key_base64",
    "status",
    "environment",
    "not_before",
    "not_after",
    "revoked_at",
}


def _registry_digest(document: dict[str, Any]) -> str:
    return sha256_digest(
        {key: value for key, value in document.items() if key != "registry_digest"}
    )


PINNED_OPS_PROJECTION_REGISTRY_RAW_SHA = (
    "sha256:b8dbdbc826c7d6af6546fd3ba7b681a5c03a688cb0899ac449d1adbfaf96387a"
)
PINNED_OPS_PROJECTION_REGISTRY_RAW_SIZE = 1078
PINNED_STAGING_OPS_PROJECTION_REGISTRY_RAW_SHA = (
    "sha256:ae06407af2401545e59fb507aa9f9765b9840b4d7cfeb6d8fc528dc43416f2b0"
)
PINNED_STAGING_OPS_PROJECTION_REGISTRY_RAW_SIZE = 655


def _ops_registry_raw_pin(environment: str) -> tuple[int, str]:
    if environment == "staging":
        return (
            PINNED_STAGING_OPS_PROJECTION_REGISTRY_RAW_SIZE,
            PINNED_STAGING_OPS_PROJECTION_REGISTRY_RAW_SHA,
        )
    return (
        PINNED_OPS_PROJECTION_REGISTRY_RAW_SIZE,
        PINNED_OPS_PROJECTION_REGISTRY_RAW_SHA,
    )


def _ops_registry_contract(environment: str) -> tuple[Path, int, str | None, str, str]:
    selected = require_environment(environment)
    if selected == "staging":
        return (
            _PINNED_STAGING_VERIFY_REGISTRY_PATH,
            PINNED_STAGING_OPS_PROJECTION_REGISTRY_GENERATION,
            PINNED_STAGING_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
            PINNED_STAGING_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
            PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
        )
    return (
        _PINNED_VERIFY_REGISTRY_PATH,
        PINNED_OPS_PROJECTION_REGISTRY_GENERATION,
        PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
        PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
        PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    )


def ops_registry_document_digest(environment: str) -> str:
    return _ops_registry_contract(environment)[4]


_KEY_WINDOWS: dict[str, tuple[str, str]] = {}


def _load_pinned_active_keys(
    expected_environment: str = "production",
) -> Mapping[str, Ed25519PublicKey]:
    """Load exactly the code-pinned production root (never a caller path)."""

    path, generation, prior_digest, body_digest, document_digest = (
        _ops_registry_contract(expected_environment)
    )
    try:
        raw_document = path.read_bytes()
        document = _decode_strict_json(raw_document, field="Ops Projection registry")
    except (OSError, OpsProjectionSignatureError) as exc:
        raise OpsProjectionSignatureError(
            "cannot load the pinned Ops Projection public-key registry"
        ) from exc
    canonical_path, _generation, _prior, _body, _document = _ops_registry_contract(
        expected_environment
    )
    frozen_path = (
        _CANONICAL_STAGING_REGISTRY_PATH
        if expected_environment == "staging"
        else _CANONICAL_PRODUCTION_REGISTRY_PATH
    )
    if path.resolve() == frozen_path.resolve():
        raw_size, raw_sha = _ops_registry_raw_pin(expected_environment)
        if len(raw_document) != raw_size:
            raise OpsProjectionSignatureError("pinned Ops Projection registry size mismatch")
        raw_digest = "sha256:" + hashlib.sha256(raw_document).hexdigest()
        if raw_digest != raw_sha:
            raise OpsProjectionSignatureError("pinned Ops Projection registry raw SHA mismatch")
    if type(document) is not dict:
        raise OpsProjectionSignatureError("pinned Ops Projection registry is invalid")
    if sha256_digest(document) != document_digest:
        raise OpsProjectionSignatureError(
            "pinned Ops Projection registry digest mismatch"
        )
    if (
        set(document) != _REGISTRY_FIELDS
        or type(document.get("schema_version")) is not int
        or document.get("schema_version") != 3
        or document.get("purpose") != "ops_projection_verification"
        or type(document.get("generation")) is not int
        or document.get("generation") != generation
        or document.get("authority_instance") != "ops-projection-cloud"
        or document.get("authority_status") not in {"ACTIVE", "PENDING"}
        or document.get("prior_registry_digest")
        != prior_digest
        or document.get("registry_digest")
        != body_digest
        or _registry_digest(document) != body_digest
    ):
        raise OpsProjectionSignatureError("pinned Ops Projection registry is invalid")

    rows = document.get("keys")
    if type(rows) is not list or len(rows) > 16:
        raise OpsProjectionSignatureError("pinned Ops Projection registry keys invalid")
    keys: dict[str, Ed25519PublicKey] = {}
    seen: set[str] = set()
    for row in rows:
        if (
            type(row) is not dict
            or set(row) != _REGISTRY_KEY_FIELDS
            or row.get("algorithm") != "Ed25519"
            or row.get("status") not in {"active", "pending", "revoked"}
            or row.get("environment") not in {"production", "staging"}
            or (row.get("status") == "revoked" and row.get("revoked_at") in {None, ""})
            or (row.get("status") != "revoked" and row.get("revoked_at") is not None)
        ):
            raise OpsProjectionSignatureError(
                "pinned Ops Projection registry key invalid"
            )
        if any(
            type(row[field]) is not str
            for field in row
            if field != "revoked_at"
        ) or row.get("revoked_at") not in {None} | (
            {row["revoked_at"]} if type(row.get("revoked_at")) is str else set()
        ):
            raise OpsProjectionSignatureError(
                "pinned Ops Projection registry key invalid"
            )
        key_id = row["key_id"].strip()
        if not key_id or key_id in seen:
            raise OpsProjectionSignatureError("Ops Projection key ids must be unique")
        seen.add(key_id)
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(
                    str(row.get("public_key_base64") or ""), validate=True
                )
            )
        except (ValueError, TypeError) as exc:
            raise OpsProjectionSignatureError(
                f"invalid Ops Projection public key: {key_id}"
            ) from exc
        if row.get("status") == "active":
            if row.get("environment") != expected_environment:
                raise OpsProjectionSignatureError(
                    "Ops Projection active key environment does not match"
                )
            keys[key_id] = public_key
            _KEY_WINDOWS[key_id] = (
                require_canonical_utc(row["not_before"], label="not_before"),
                require_canonical_utc(row["not_after"], label="not_after"),
            )
    expected_active = 1 if document.get("authority_status") == "ACTIVE" else 0
    if len(keys) != expected_active:
        raise OpsProjectionSignatureError(
            "Ops Projection active keys do not match authority status"
        )
    return keys


def verify_pinned_ops_projection(
    document: dict[str, Any] | bytes | str,
    *,
    expected_environment: str,
) -> Mapping[str, Any]:
    """Verify an envelope only against the compile-time production trust root."""

    return _verify_pinned_document(
        document, expected_environment=expected_environment
    ).envelope


def _verify_pinned_document(
    document: dict[str, Any] | bytes | str,
    *,
    expected_environment: str = "production",
) -> _VerifiedOpsProjectionDocument:
    keys = _load_pinned_active_keys(expected_environment)
    return _verify_document_identity(
        document, keys, expected_environment=expected_environment
    )


def _verify_document(
    document: dict[str, Any] | bytes | str,
    keys: Mapping[str, Ed25519PublicKey],
    *,
    expected_environment: str = "production",
) -> Mapping[str, Any]:
    return _verify_document_identity(
        document, keys, expected_environment=expected_environment
    ).envelope


def _verify_document_identity(
    document: dict[str, Any] | bytes | str,
    keys: Mapping[str, Ed25519PublicKey],
    *,
    expected_environment: str = "production",
) -> _VerifiedOpsProjectionDocument:
    if type(keys) is not dict:
        raise OpsProjectionSignatureError(
            "Ops Projection verifier key set is not canonical"
        )
    if type(document) in {bytes, str}:
        frozen = _decode_strict_json(
            document, field="signed Ops Projection document"
        )
    else:
        frozen = _copy_exact_json(
            document, field="signed Ops Projection document"
        )
    if type(frozen) is not dict:
        raise OpsProjectionSignatureError(
            "signed Ops Projection document must be an object"
        )
    allowed = {
        "schema_version", "algorithm", "issuer_key_id", "envelope", "signature"
    }
    if set(frozen) != allowed:
        raise OpsProjectionSignatureError(
            "signed Ops Projection document shape invalid"
        )
    if (
        frozen.get("schema_version") != SIGNED_DOCUMENT_SCHEMA
        or frozen.get("algorithm") != "Ed25519"
        or type(frozen.get("issuer_key_id")) is not str
        or type(frozen.get("signature")) is not str
    ):
        raise OpsProjectionSignatureError(
            "signed Ops Projection document identity invalid"
        )
    key_id = frozen["issuer_key_id"]
    public_key = keys.get(key_id)
    if public_key is None:
        raise OpsProjectionSignatureError("Ops Projection issuer is not trusted")
    envelope = frozen.get("envelope")
    if type(envelope) is not dict:
        raise OpsProjectionSignatureError("Ops Projection envelope is missing")
    _validate_envelope(envelope, expected_environment=expected_environment)
    window = _KEY_WINDOWS.get(key_id)
    generated_at = require_canonical_utc(envelope.get("generated_at"), label="generated_at")
    if window is not None:
        not_before = require_canonical_utc(window[0], label="not_before")
        not_after = require_canonical_utc(window[1], label="not_after")
        if generated_at < not_before or generated_at > not_after:
            raise OpsProjectionSignatureError(
                "Ops Projection issuer is outside its validity window"
            )
    body = _signed_body(key_id=key_id, envelope=envelope)
    signature_value = frozen["signature"]
    if not signature_value.startswith("ed25519:"):
        raise OpsProjectionSignatureError("Ops Projection signature must use Ed25519")
    try:
        signature = base64.b64decode(
            signature_value.removeprefix("ed25519:"), validate=True
        )
        public_key.verify(signature, canonical_json_bytes(body))
    except (ValueError, InvalidSignature) as exc:
        raise OpsProjectionSignatureError(
            "Ops Projection signature is invalid"
        ) from exc
    return _VerifiedOpsProjectionDocument(
        envelope=_deep_immutable(envelope),
        issuer_key_id=key_id,
        document_digest=sha256_digest(frozen),
    )


def verified_pinned_ops_projection_dataset_evidence(
    document: dict[str, Any] | bytes | str,
    required_datasets: tuple[str, ...] | list[str],
    *,
    expected_environment: str,
) -> tuple[Mapping[str, Any], Mapping[str, Mapping[str, Any]]]:
    """Derive immutable READY rows plus identity from one verified document."""

    if type(required_datasets) not in {tuple, list}:
        raise TypeError("required_datasets must be one exact tuple or list")
    selected = tuple(required_datasets)
    if (
        not selected
        or any(type(dataset) is not str or not dataset for dataset in selected)
        or len(set(selected)) != len(selected)
    ):
        raise OpsProjectionSignatureError(
            "required_datasets must be unique exact non-empty strings"
        )
    verified_document = _verify_pinned_document(
        document, expected_environment=expected_environment
    )
    envelope = verified_document.envelope
    coverage = envelope["dataset_coverage"]
    assert isinstance(coverage, Mapping)  # validated by verify
    evidence: dict[str, dict[str, Any]] = {}
    for dataset in selected:
        row = coverage.get(dataset)
        if not isinstance(row, Mapping):
            raise OpsProjectionSignatureError(
                f"signed Ops Projection Coverage missing for {dataset}"
            )
        evidence[str(dataset)] = {
            "dataset": str(dataset),
            "status": row.get("status"),
            "coverage_mode": row.get("coverage_mode"),
            "policy_id": row.get("policy_id"),
            "policy_version": row.get("policy_version"),
            "policy_digest": row.get("policy_digest"),
            "observed_start": row.get("observed_start"),
            "observed_end": row.get("observed_end"),
            "projection_status": envelope["projection_status"],
            "projection_generation": envelope["generation_id"],
            "projection_content_digest": envelope["content_digest"],
            "source_generation": envelope["source_generation"],
            "export_cursor": envelope["export_cursor"],
            "applied_cursor": envelope["applied_cursor"],
            "signed_projection_document_digest": (
                verified_document.document_digest
            ),
            "signed_projection_issuer_key_id": (
                verified_document.issuer_key_id
            ),
        }
    return envelope, _deep_immutable(evidence)


__all__ = [
    "ENVELOPE_SCHEMA",
    "OpsProjectionSignatureError",
    "PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST",
    "PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST",
    "PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_OPS_PROJECTION_REGISTRY_GENERATION",
    "SIGNED_DOCUMENT_SCHEMA",
    "canonical_json_bytes",
    "open_ops_projection_signing_service",
    "sha256_digest",
    "verified_pinned_ops_projection_dataset_evidence",
    "verify_pinned_ops_projection",
]
