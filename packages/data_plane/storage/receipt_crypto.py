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
PINNED_RECEIPT_REGISTRY_RAW_DIGEST = (
    "sha256:de08e72ea133bf4ab876944e27520a5aa7207e7bdfee412b8866131b9e7b1c90"
)
PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:087cfea679c27c267c4e79aaa7518097778d3b44d251c931e5bb6fd2803a2465"
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
        if not signature.startswith("ed25519:"):
            return False
        try:
            raw = base64.b64decode(signature[len("ed25519:") :], validate=True)
            self.public_key.verify(raw, body)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False


@lru_cache(maxsize=8)
def _parse_verify_key_document(raw: bytes) -> tuple[ReceiptVerifyKey, ...]:
    """Parse one exact registry byte string; content, not stat, keys the cache."""
    doc = _strict_json_document(raw)
    if set(doc) != {"schema_version", "purpose", "keys"}:
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    if (
        type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
        or type(doc["purpose"]) is not str
        or doc["purpose"] != "receipt_verification"
        or type(doc["keys"]) is not list
        or len(doc["keys"]) > 16
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    out: dict[str, ReceiptVerifyKey] = {}
    seen_ids: set[str] = set()
    active_count = 0
    base_fields = {"key_id", "algorithm", "public_key_b64", "status"}
    allowed_row_fields = (
        base_fields,
        base_fields | {"note"},
    )
    for row in doc["keys"]:
        if type(row) is not dict or all(
            set(row) != fields for fields in allowed_row_fields
        ):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry row is not closed"
            )
        if "note" in row and (type(row["note"]) is not str or not row["note"]):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry note is invalid"
            )
        if any(type(row[field]) is not str for field in base_fields):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry fields must be exact strings"
            )
        key_id = row["key_id"].strip()
        if not key_id or key_id in seen_ids:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry key ids must be non-empty and unique"
            )
        seen_ids.add(key_id)
        if row["algorithm"] != "Ed25519":
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires Ed25519 entries"
            )
        status = row["status"]
        if status not in {"active", "revoked"}:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires an explicit active/revoked status"
            )
        try:
            raw_key = base64.b64decode(row["public_key_b64"], validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(raw_key)
        except (TypeError, ValueError) as exc:
            raise ReceiptKeyConfigurationError(
                f"invalid pinned receipt public key: {key_id}"
            ) from exc
        if status == "active":
            active_count += 1
            out[key_id] = ReceiptVerifyKey(key_id=key_id, public_key=public_key)
    if active_count > 1:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry permits at most one active key"
        )
    return tuple(out.values())


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


def load_verify_keys() -> dict[str, ReceiptVerifyKey]:
    """Load only the committed receipt verifier registry."""
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
    rows = _parse_verify_key_document(raw)
    return {row.key_id: row for row in rows}


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
    if type(key_id) is not str or not key_id:
        return False
    try:
        body = base64.b64decode(body_b64, validate=True)
    except (ValueError, TypeError):
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
    ):
        return False
    vk = load_verify_keys().get(key_id)
    return False if vk is None else vk.verify(body, signature)


__all__ = [
    "PARSER_NORMALIZER_VERSION",
    "LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION",
    "SIGNED_RECEIPT_CLAIMS_VERSION",
    "STANDARD_CLAIM_KEYS",
    "ReceiptKeyConfigurationError",
    "ReceiptVerifyKey",
    "PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_RECEIPT_REGISTRY_RAW_DIGEST",
    "canonical_evidence_digest",
    "canonical_receipt_body",
    "load_verify_keys",
    "partition_extra_digests",
    "verify_receipt_signature",
    "verify_receipt_signature_values",
]
