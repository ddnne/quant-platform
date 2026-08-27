"""Public, verify-only Ed25519 receipt cryptography.

This product module deliberately has no private-key type, private-key loader,
or signing helper.  Receipt minting belongs to a separately provisioned
evidence authority; Coverage and READY consume only signed documents verified
against the committed public-key registry.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_PINNED_VERIFY_KEYS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data_contracts"
    / "receipt_verify_public_keys.json"
)
_PINNED_PRIOR_VERIFY_KEYS_PATH = _PINNED_VERIFY_KEYS_PATH.with_name(
    "receipt_verify_public_keys.generation-1.json"
)
PINNED_RECEIPT_REGISTRY_RAW_DIGEST = (
    "sha256:dc6095db1d09bf775f972cb428944a1ba5bc47fefa0af19e77c3f3a157ae47f5"
)
PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:188c39c9833802026ff614a2de6ad3c48e7c83e628c43958b00f003097a36516"
)
PINNED_RECEIPT_REGISTRY_GENERATION = 2
PINNED_RECEIPT_AUTHORITY_STATUS = "PENDING"
PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST = (
    "sha256:087cfea679c27c267c4e79aaa7518097778d3b44d251c931e5bb6fd2803a2465"
)
PINNED_RECEIPT_PRIOR_REGISTRY_RAW_DIGEST = (
    "sha256:de08e72ea133bf4ab876944e27520a5aa7207e7bdfee412b8866131b9e7b1c90"
)
PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:087cfea679c27c267c4e79aaa7518097778d3b44d251c931e5bb6fd2803a2465"
)
PINNED_RECEIPT_PRIOR_REGISTRY_GENERATION = 1
PINNED_RECEIPT_PRIOR_AUTHORITY_STATUS = "REVOKED"
PINNED_RECEIPT_REGISTRY_BODY_DIGEST = (
    "sha256:7dbf4eae91e927d74bd7075bc69210232030bb9077052d55853dc09f0c7bb921"
)


class ReceiptKeyConfigurationError(RuntimeError):
    """Receipt verification keys are absent, malformed, or unpinned."""


PARSER_NORMALIZER_VERSION = "coverage-receipt/v4-ed25519-closure"
SIGNED_RECEIPT_CLAIMS_VERSION = "signed-receipt-claims/v2"
LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION = "signed-receipt-claims/v1"

# Closed claim names plus envelope aliases. extra_digests cannot occupy these.
STANDARD_CLAIM_KEYS = frozenset(
    {
        "version",
        "coverage_policy_version",
        "dataset",
        "source",
        "segment_id",
        "segment_start",
        "segment_end",
        "expected_scope",
        "expected_items",
        "observed_items",
        "raw_page_count",
        "source_request_digest",
        "raw_manifest_digest",
        "raw_digest",
        "raw_count",
        "structured_digest",
        "structured_count",
        "parser_normalizer_version",
        "structured_generation",
        "pagination_exhausted",
        "discovery_exhausted",
        "status",
        "error",
        "scope_digest",
        "observation_digest",
        "run_id",
        "issuer_id",
        "issued_at",
        "checked_at",
        "extra_digests",
        "raw",
        "eligibility",
        "signature",
        "signed_body_b64",
        "issuer_class",
        "issuer_key_id",
        "body_digest",
    }
)


def canonical_receipt_body(fields: Mapping[str, Any]) -> bytes:
    """Deterministic JSON bytes for signing (sorted keys, no whitespace)."""
    return json.dumps(
        dict(fields),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def _strict_json_document(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ReceiptKeyConfigurationError(
                    f"receipt registry contains duplicate key {key!r}"
                )
            document[key] = value
        return document

    def reject_nonfinite(value: str) -> None:
        raise ReceiptKeyConfigurationError(
            f"receipt registry contains non-finite value {value!r}"
        )

    try:
        document = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except ReceiptKeyConfigurationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptKeyConfigurationError(
            "cannot load the pinned receipt public-key registry"
        ) from exc
    if type(document) is not dict:
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    return document


def _canonical_registry_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def body_digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def canonical_evidence_digest(payload: Any) -> str:
    """Digest bytes verbatim or structured evidence as closed canonical JSON."""
    raw = payload if isinstance(payload, bytes) else json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return body_digest(raw)


@dataclass(frozen=True)
class ReceiptVerifyKey:
    key_id: str
    public_key: Ed25519PublicKey

    def verify(self, body: bytes, signature: str) -> bool:
        if type(body) is not bytes or type(signature) is not str:
            return False
        if not signature.startswith("ed25519:"):
            return False
        raw = _decode_canonical_base64(
            signature[len("ed25519:") :], expected_length=64
        )
        if raw is None:
            return False
        try:
            self.public_key.verify(raw, body)
            return True
        except InvalidSignature:
            return False


@dataclass(frozen=True)
class _ReceiptVerifyRegistryEntry:
    key_id: str
    public_key_bytes: bytes
    status: str


@dataclass(frozen=True)
class _ReceiptVerifyRegistry:
    generation: int
    authority_status: str
    prior_registry_digest: str | None
    registry_digest: str
    entries: tuple[_ReceiptVerifyRegistryEntry, ...]
    active_keys: tuple[ReceiptVerifyKey, ...]
    audit_keys: tuple[ReceiptVerifyKey, ...]


@dataclass(frozen=True)
class _PriorReceiptVerifyRegistry:
    generation: int
    authority_status: str
    document_digest: str
    entries: tuple[_ReceiptVerifyRegistryEntry, ...]


_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "generation",
    "authority_status",
    "prior_registry_digest",
    "keys",
    "registry_digest",
}
_REGISTRY_KEY_FIELDS = {
    "key_id",
    "algorithm",
    "public_key_base64",
    "status",
}
_PRIOR_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "keys",
}
_PRIOR_REGISTRY_KEY_FIELDS = {
    "key_id",
    "public_key_b64",
    "algorithm",
    "status",
    "note",
}


def _decode_canonical_base64(
    value: object, *, expected_length: int | None = None
) -> bytes | None:
    if type(value) is not str:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    if base64.b64encode(raw).decode("ascii") != value:
        return None
    if expected_length is not None and len(raw) != expected_length:
        return None
    return raw


def decode_canonical_signed_body(value: object) -> bytes | None:
    """Decode one receipt body only when its Base64 spelling is canonical."""
    return _decode_canonical_base64(value)


def _registry_body_digest(document: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in document.items()
        if key != "registry_digest"
    }
    return body_digest(_canonical_registry_bytes(body))


@lru_cache(maxsize=8)
def _parse_registry_document(raw: bytes) -> _ReceiptVerifyRegistry:
    """Parse one exact registry byte string; content, not stat, keys the cache."""
    doc = _strict_json_document(raw)
    if set(doc) != _REGISTRY_FIELDS:
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    if (
        type(doc["schema_version"]) is not int
        or doc["schema_version"] != 2
        or type(doc["purpose"]) is not str
        or doc["purpose"] != "receipt_verification"
        or type(doc["generation"]) is not int
        or doc["generation"] < 1
        or type(doc["authority_status"]) is not str
        or doc["authority_status"] not in {"ACTIVE", "PENDING"}
        or (
            doc["generation"] == 1
            and doc["prior_registry_digest"] is not None
        )
        or (
            doc["generation"] > 1
            and (
                type(doc["prior_registry_digest"]) is not str
                or not _is_sha256_digest(doc["prior_registry_digest"])
            )
        )
        or type(doc["registry_digest"]) is not str
        or not _is_sha256_digest(doc["registry_digest"])
        or type(doc["keys"]) is not list
        or len(doc["keys"]) < 1
        or len(doc["keys"]) > 16
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    if _registry_body_digest(doc) != doc["registry_digest"]:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry body digest mismatch"
        )
    active: dict[str, ReceiptVerifyKey] = {}
    audit: dict[str, ReceiptVerifyKey] = {}
    entries: list[_ReceiptVerifyRegistryEntry] = []
    seen_ids: set[str] = set()
    seen_public_key_status: dict[bytes, str] = {}
    pending_count = 0
    for row in doc["keys"]:
        if type(row) is not dict or set(row) != _REGISTRY_KEY_FIELDS:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry row is not closed"
            )
        if any(type(row[field]) is not str for field in _REGISTRY_KEY_FIELDS):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry fields must be exact strings"
            )
        raw_key_id = row["key_id"]
        key_id = raw_key_id.strip()
        if raw_key_id != key_id or not key_id or key_id in seen_ids:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry key ids must be trimmed, non-empty, and unique"
            )
        seen_ids.add(key_id)
        if row["algorithm"] != "Ed25519":
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires Ed25519 entries"
            )
        status = row["status"]
        if status not in {"active", "pending", "revoked"}:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires an explicit key status"
            )
        try:
            raw_key = _decode_canonical_base64(
                row["public_key_base64"], expected_length=32
            )
            if raw_key is None:
                raise ValueError("receipt public key is not canonical Ed25519 base64")
            public_key = Ed25519PublicKey.from_public_bytes(raw_key)
        except (TypeError, ValueError) as exc:
            raise ReceiptKeyConfigurationError(
                f"invalid pinned receipt public key: {key_id}"
            ) from exc
        prior_status = seen_public_key_status.get(raw_key)
        if prior_status is not None and (
            prior_status != "revoked" or status != "revoked"
        ):
            raise ReceiptKeyConfigurationError(
                "active or pending receipt public keys must not reuse public-key bytes"
            )
        seen_public_key_status[raw_key] = status
        entries.append(
            _ReceiptVerifyRegistryEntry(
                key_id=key_id,
                public_key_bytes=raw_key,
                status=status,
            )
        )
        verify_key = ReceiptVerifyKey(key_id=key_id, public_key=public_key)
        if status == "active":
            active[key_id] = verify_key
            audit[key_id] = verify_key
        elif status == "revoked":
            audit[key_id] = verify_key
        else:
            pending_count += 1
    expected_active = 1 if doc["authority_status"] == "ACTIVE" else 0
    if len(active) != expected_active:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry active keys do not match authority status"
        )
    if pending_count > 1:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry permits at most one pending key"
        )
    return _ReceiptVerifyRegistry(
        generation=doc["generation"],
        authority_status=doc["authority_status"],
        prior_registry_digest=doc["prior_registry_digest"],
        registry_digest=doc["registry_digest"],
        entries=tuple(entries),
        active_keys=tuple(active.values()),
        audit_keys=tuple(audit.values()),
    )


@lru_cache(maxsize=4)
def _parse_prior_registry_document(raw: bytes) -> _PriorReceiptVerifyRegistry:
    """Parse the exact legacy generation-1 audit artifact."""
    doc = _strict_json_document(raw)
    if (
        set(doc) != _PRIOR_REGISTRY_FIELDS
        or type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
        or type(doc["purpose"]) is not str
        or doc["purpose"] != "receipt_verification"
        or type(doc["keys"]) is not list
        or not 1 <= len(doc["keys"]) <= 16
    ):
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry is invalid"
        )

    entries: list[_ReceiptVerifyRegistryEntry] = []
    seen_ids: set[str] = set()
    for row in doc["keys"]:
        if type(row) is not dict or set(row) != _PRIOR_REGISTRY_KEY_FIELDS:
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry row is not closed"
            )
        if any(type(row[field]) is not str for field in _PRIOR_REGISTRY_KEY_FIELDS):
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry fields must be exact strings"
            )
        raw_key_id = row["key_id"]
        key_id = raw_key_id.strip()
        if raw_key_id != key_id or not key_id or key_id in seen_ids:
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry key ids must be trimmed, "
                "non-empty, and unique"
            )
        seen_ids.add(key_id)
        if (
            row["algorithm"] != "Ed25519"
            or row["status"] != "revoked"
            or row["note"] != row["note"].strip()
            or not row["note"]
        ):
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry must remain revoked audit evidence"
            )
        raw_key = _decode_canonical_base64(
            row["public_key_b64"], expected_length=32
        )
        if raw_key is None:
            raise ReceiptKeyConfigurationError(
                f"invalid pinned prior receipt public key: {key_id}"
            )
        entries.append(
            _ReceiptVerifyRegistryEntry(
                key_id=key_id,
                public_key_bytes=raw_key,
                status="revoked",
            )
        )
    return _PriorReceiptVerifyRegistry(
        generation=1,
        authority_status="REVOKED",
        document_digest=body_digest(_canonical_registry_bytes(doc)),
        entries=tuple(entries),
    )


def _is_sha256_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _parse_verify_key_document(raw: bytes) -> tuple[ReceiptVerifyKey, ...]:
    """Return only ACTIVE keys; PENDING and revoked keys cannot grant COMPLETE."""
    return _parse_registry_document(raw).active_keys


def _parse_audit_key_document(raw: bytes) -> tuple[ReceiptVerifyKey, ...]:
    """Return ACTIVE/revoked public keys for explicitly audit-only verification."""
    return _parse_registry_document(raw).audit_keys


def _load_verify_key_file(
    path_text: str, mtime_ns: int | None = None, size: int | None = None
) -> tuple[ReceiptVerifyKey, ...]:
    """Parse a registry for diagnostics; production additionally pins bytes."""
    del mtime_ns, size
    try:
        raw = Path(path_text).read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot load the pinned receipt public-key registry"
        ) from exc
    return _parse_verify_key_document(raw)


def _load_pinned_registry() -> _ReceiptVerifyRegistry:
    """Load and pin the complete committed receipt verifier registry."""
    keys_path = _PINNED_VERIFY_KEYS_PATH
    try:
        raw = keys_path.read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot read the pinned receipt public-key registry"
        ) from exc
    raw_digest = body_digest(raw)
    if raw_digest != PINNED_RECEIPT_REGISTRY_RAW_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry raw digest mismatch"
        )
    document = _strict_json_document(raw)
    document_digest = body_digest(_canonical_registry_bytes(document))
    if document_digest != PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry document digest mismatch"
        )
    registry = _parse_registry_document(raw)
    if (
        registry.generation != PINNED_RECEIPT_REGISTRY_GENERATION
        or registry.authority_status != PINNED_RECEIPT_AUTHORITY_STATUS
        or registry.prior_registry_digest
        != PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST
        or registry.registry_digest != PINNED_RECEIPT_REGISTRY_BODY_DIGEST
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry generation chain mismatch"
        )
    if registry.generation > 1:
        prior = _load_pinned_prior_registry()
        _validate_registry_chain(prior=prior, current=registry)
    return registry


def _load_pinned_prior_registry() -> _PriorReceiptVerifyRegistry:
    """Load the immutable predecessor artifact and all of its code pins."""
    try:
        raw = _PINNED_PRIOR_VERIFY_KEYS_PATH.read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot read the pinned prior receipt public-key registry"
        ) from exc
    if body_digest(raw) != PINNED_RECEIPT_PRIOR_REGISTRY_RAW_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry raw digest mismatch"
        )
    document = _strict_json_document(raw)
    document_digest = body_digest(_canonical_registry_bytes(document))
    if document_digest != PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry document digest mismatch"
        )
    prior = _parse_prior_registry_document(raw)
    if (
        prior.generation != PINNED_RECEIPT_PRIOR_REGISTRY_GENERATION
        or prior.authority_status != PINNED_RECEIPT_PRIOR_AUTHORITY_STATUS
        or prior.document_digest != PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST
    ):
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry code pins mismatch"
        )
    return prior


def _validate_registry_chain(
    *, prior: _PriorReceiptVerifyRegistry, current: _ReceiptVerifyRegistry
) -> None:
    """Validate the repository-pinned generation-1 -> generation-2 transition.

    This closes the immutable repository chain. An external monotonic state is
    still required before a future authority can prove rollback resistance.
    """
    if (
        current.generation != prior.generation + 1
        or current.prior_registry_digest != prior.document_digest
        or (prior.authority_status, current.authority_status)
        != ("REVOKED", "PENDING")
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry prior chain mismatch"
        )
    current_by_id = {entry.key_id: entry for entry in current.entries}
    for prior_entry in prior.entries:
        current_entry = current_by_id.get(prior_entry.key_id)
        if (
            current_entry is None
            or current_entry.public_key_bytes != prior_entry.public_key_bytes
            or prior_entry.status != "revoked"
            or current_entry.status != "revoked"
        ):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry revoked history transition mismatch"
            )


def load_verify_keys() -> dict[str, ReceiptVerifyKey]:
    """Load only ACTIVE keys eligible to verify a COMPLETE receipt."""
    return {row.key_id: row for row in _load_pinned_registry().active_keys}


def load_audit_verify_keys() -> dict[str, ReceiptVerifyKey]:
    """Load ACTIVE/revoked keys for audit; never use this result for COMPLETE."""
    return {row.key_id: row for row in _load_pinned_registry().audit_keys}


def receipt_verify_key_status(key_id: str) -> str | None:
    """Return the pinned lifecycle state for one exact receipt key id.

    Callers may use this only to decide whether a cryptographically valid
    receipt is historical audit evidence.  COMPLETE eligibility must continue
    to use :func:`load_verify_keys` and the full collection-closure verifier.
    """
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        return None
    matches = [
        entry.status
        for entry in _load_pinned_registry().entries
        if entry.key_id == key_id
    ]
    if len(matches) > 1:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry contains a duplicate key id"
        )
    return matches[0] if matches else None


def partition_extra_digests(extra_digests: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy extra_digests excluding standard claims and envelope aliases."""
    if extra_digests is None:
        return {}
    if not isinstance(extra_digests, Mapping):
        raise TypeError("extra_digests must be a mapping")
    return {
        str(key): value
        for key, value in extra_digests.items()
        if str(key) not in STANDARD_CLAIM_KEYS
    }


def verify_receipt_signature(
    digests: Mapping[str, Any],
) -> bool:
    """True iff digests carry a valid Ed25519 signature over the body."""
    if type(digests) is not dict:
        return False
    frozen = dict(digests)
    body_b64 = frozen.get("signed_body_b64")
    signature = frozen.get("signature")
    key_id = frozen.get("issuer_key_id")
    if type(body_b64) is not str or type(signature) is not str:
        return False
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        return False
    body = decode_canonical_signed_body(body_b64)
    if body is None:
        return False
    return verify_receipt_signature_values(
        body=body,
        signature=signature,
        key_id=key_id,
    )


def verify_receipt_signature_values(
    *, body: bytes, signature: str, key_id: str
) -> bool:
    """Verify one already-materialized receipt body and signature."""
    if (
        type(body) is not bytes
        or type(signature) is not str
        or type(key_id) is not str
        or not key_id
        or key_id != key_id.strip()
    ):
        return False
    vk = load_verify_keys().get(key_id)
    return False if vk is None else vk.verify(body, signature)


def verify_receipt_signature_values_for_audit(
    *, body: bytes, signature: str, key_id: str
) -> bool:
    """Verify with ACTIVE/revoked public keys without granting eligibility."""
    if (
        type(body) is not bytes
        or type(signature) is not str
        or type(key_id) is not str
        or not key_id
        or key_id != key_id.strip()
    ):
        return False
    vk = load_audit_verify_keys().get(key_id)
    return False if vk is None else vk.verify(body, signature)


__all__ = [
    "PARSER_NORMALIZER_VERSION",
    "LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION",
    "SIGNED_RECEIPT_CLAIMS_VERSION",
    "STANDARD_CLAIM_KEYS",
    "ReceiptKeyConfigurationError",
    "ReceiptVerifyKey",
    "PINNED_RECEIPT_AUTHORITY_STATUS",
    "PINNED_RECEIPT_PRIOR_AUTHORITY_STATUS",
    "PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST",
    "PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_RECEIPT_PRIOR_REGISTRY_GENERATION",
    "PINNED_RECEIPT_PRIOR_REGISTRY_RAW_DIGEST",
    "PINNED_RECEIPT_REGISTRY_BODY_DIGEST",
    "PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_RECEIPT_REGISTRY_GENERATION",
    "PINNED_RECEIPT_REGISTRY_RAW_DIGEST",
    "canonical_evidence_digest",
    "canonical_receipt_body",
    "decode_canonical_signed_body",
    "load_audit_verify_keys",
    "load_verify_keys",
    "partition_extra_digests",
    "verify_receipt_signature",
    "verify_receipt_signature_values",
    "verify_receipt_signature_values_for_audit",
]
