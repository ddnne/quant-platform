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
def _load_verify_key_file(
    path_text: str, mtime_ns: int, size: int
) -> tuple[ReceiptVerifyKey, ...]:
    """Parse one committed registry generation; stat fields key the cache."""
    del mtime_ns, size
    keys_path = Path(path_text)
    out: dict[str, ReceiptVerifyKey] = {}
    try:
        doc = json.loads(keys_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptKeyConfigurationError(
            "cannot load the pinned receipt public-key registry"
        ) from exc
    if (
        not isinstance(doc, Mapping)
        or doc.get("schema_version") != 1
        or doc.get("purpose") != "receipt_verification"
        or not isinstance(doc.get("keys"), list)
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    for row in doc["keys"]:
        if not isinstance(row, Mapping) or row.get("algorithm") != "Ed25519":
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires Ed25519 entries"
            )
        status = row.get("status")
        if status not in {"active", "revoked"}:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires an explicit active/revoked status"
            )
        if status != "active":
            continue
        kid = str(row.get("key_id") or "").strip()
        if not kid or kid in out:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry key ids must be non-empty and unique"
            )
        try:
            raw = base64.b64decode(
                str(row.get("public_key_b64") or ""), validate=True
            )
            public_key = Ed25519PublicKey.from_public_bytes(raw)
        except (TypeError, ValueError) as exc:
            raise ReceiptKeyConfigurationError(
                f"invalid pinned receipt public key: {kid}"
            ) from exc
        out[kid] = ReceiptVerifyKey(key_id=kid, public_key=public_key)
    return tuple(out.values())


def load_verify_keys() -> dict[str, ReceiptVerifyKey]:
    """Load only the committed receipt verifier registry."""
    keys_path = _PINNED_VERIFY_KEYS_PATH
    try:
        stat = keys_path.stat()
        rows = _load_verify_key_file(
            str(keys_path.resolve()), stat.st_mtime_ns, stat.st_size
        )
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot stat the pinned receipt public-key registry"
        ) from exc
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
    body_b64 = digests.get("signed_body_b64")
    signature = digests.get("signature")
    key_id = digests.get("issuer_key_id")
    if not isinstance(body_b64, str) or not isinstance(signature, str):
        return False
    if not isinstance(key_id, str) or not key_id:
        return False
    keys = load_verify_keys()
    vk = keys.get(key_id)
    if vk is None:
        return False
    try:
        body = base64.b64decode(body_b64, validate=True)
    except (ValueError, TypeError):
        return False
    return vk.verify(body, signature)


__all__ = [
    "PARSER_NORMALIZER_VERSION",
    "LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION",
    "SIGNED_RECEIPT_CLAIMS_VERSION",
    "STANDARD_CLAIM_KEYS",
    "ReceiptKeyConfigurationError",
    "ReceiptVerifyKey",
    "canonical_evidence_digest",
    "canonical_receipt_body",
    "load_verify_keys",
    "partition_extra_digests",
    "verify_receipt_signature",
]
