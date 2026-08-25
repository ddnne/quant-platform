"""Bind signed receipt claims to the outer receipt and evidence.

Success returns an opaque VerifiedReceipt. Failure raises.
This module does not decide coverage status.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from types import MappingProxyType
from typing import Any, Mapping

from qp_paths import repo_root
from storage.coverage_receipts import compute_raw_digest
from storage.receipt_crypto import (
    PARSER_NORMALIZER_VERSION,
    SIGNED_RECEIPT_CLAIMS_VERSION,
    STANDARD_CLAIM_KEYS,
    verify_receipt_signature,
)

_VERIFIED = object()
_SCHEMA_PATH = (
    repo_root() / "specs" / "receipts" / "signed_receipt_claims.schema.json"
)


class ReceiptVerificationError(ValueError):
    """Signed claims do not bind the outer receipt or evidence."""


@dataclass(frozen=True)
class VerifiedReceipt:
    """Opaque proof that signed claims bind the outer receipt."""

    _ok: object
    _claims: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self._ok is not _VERIFIED:
            raise TypeError("VerifiedReceipt is opaque; call verify()")


@lru_cache(maxsize=1)
def _claims_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _decode_signed_claims(digests: Mapping[str, Any]) -> dict[str, Any]:
    import base64

    body_b64 = digests.get("signed_body_b64")
    if not isinstance(body_b64, str) or not body_b64:
        raise ReceiptVerificationError("missing signed_body_b64")
    try:
        raw = base64.b64decode(body_b64, validate=True)
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ReceiptVerificationError("signed body is not valid JSON") from exc
    if not isinstance(claims, dict):
        raise ReceiptVerificationError("signed body must be an object")
    return claims


def _validate_schema(claims: Mapping[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ReceiptVerificationError(
            "jsonschema is required to verify signed receipt claims"
        ) from exc
    try:
        jsonschema.validate(instance=dict(claims), schema=_claims_schema())
    except jsonschema.ValidationError as exc:
        raise ReceiptVerificationError(
            f"signed claims fail closed schema: {exc.message}"
        ) from exc


def _same(left: Any, right: Any) -> bool:
    return left == right


def _require_same(label: str, signed_value: Any, outer_value: Any) -> None:
    if not _same(signed_value, outer_value):
        raise ReceiptVerificationError(
            f"signed {label} does not bind outer receipt"
        )


def verify(
    receipt: Any,
    *,
    required: Any = None,
    raw: bytes | None = None,
    structured_digest: str | None = None,
    verify_keys: Mapping[str, Any] | None = None,
) -> VerifiedReceipt:
    """Compare signed claims vs outer receipt vs required vs evidence.

    Raises ReceiptVerificationError on any mismatch or invalid signature.
    """
    if receipt is None:
        raise ReceiptVerificationError("missing collection receipt")
    digests = receipt.digests if hasattr(receipt, "digests") else None
    if not isinstance(digests, Mapping):
        raise ReceiptVerificationError("receipt digests must be a mapping")
    if digests.get("synthetic"):
        raise ReceiptVerificationError("synthetic receipts are not verifiable")
    if digests.get("eligibility") != "TRUSTED_COLLECTION":
        raise ReceiptVerificationError("receipt is not a trusted collection")
    if not verify_receipt_signature(digests, verify_keys=verify_keys):
        raise ReceiptVerificationError("Ed25519 signature is invalid")

    claims = _decode_signed_claims(digests)
    _validate_schema(claims)
    extras = claims.get("extra_digests")
    if not isinstance(extras, dict):
        raise ReceiptVerificationError("extra_digests must be an object")
    overlap = sorted(set(extras) & STANDARD_CLAIM_KEYS)
    if overlap:
        raise ReceiptVerificationError(
            f"extra_digests overrides standard claims: {overlap}"
        )
    if claims.get("version") != SIGNED_RECEIPT_CLAIMS_VERSION:
        raise ReceiptVerificationError("unsupported signed claims version")
    if claims.get("parser_normalizer_version") != PARSER_NORMALIZER_VERSION:
        raise ReceiptVerificationError("parser_normalizer_version mismatch")

    _require_same("dataset", claims["dataset"], receipt.dataset)
    _require_same("source", claims["source"], receipt.source)
    _require_same("segment_id", claims["segment_id"], receipt.segment_id)
    if claims.get("segment_start") is not None:
        _require_same(
            "segment_start", claims["segment_start"], receipt.segment_start
        )
    if claims.get("segment_end") is not None:
        _require_same(
            "segment_end", claims["segment_end"], receipt.segment_end
        )
    _require_same("run_id", int(claims["run_id"]), int(receipt.run_id))
    _require_same("raw_count", int(claims["raw_count"]), int(receipt.raw_row_count))
    _require_same(
        "structured_count",
        int(claims["structured_count"]),
        int(receipt.structured_row_count),
    )
    _require_same(
        "pagination_exhausted",
        bool(claims["pagination_exhausted"]),
        bool(receipt.pagination_exhausted),
    )
    _require_same(
        "discovery_exhausted",
        bool(claims["discovery_exhausted"]),
        bool(receipt.pagination_exhausted),
    )
    _require_same("raw_digest", claims["raw_digest"], digests.get("raw"))
    _require_same(
        "structured_digest",
        claims.get("structured_digest"),
        digests.get("structured_digest"),
    )
    _require_same(
        "parser_normalizer_version",
        claims["parser_normalizer_version"],
        digests.get("parser_normalizer_version"),
    )
    issuer_id = claims["issuer_id"]
    envelope_issuer = digests.get("issuer_id", digests.get("issuer_key_id"))
    _require_same("issuer_id", issuer_id, envelope_issuer)
    _require_same("issuer_key_id", issuer_id, digests.get("issuer_key_id"))
    _require_same("issued_at", claims["issued_at"], digests.get("issued_at"))
    _require_same("checked_at", claims["checked_at"], receipt.checked_at)
    _require_same(
        "source_request_digest",
        claims.get("source_request_digest"),
        digests.get("source_request_digest"),
    )
    _require_same(
        "raw_manifest_digest",
        claims.get("raw_manifest_digest"),
        digests.get("raw_manifest_digest"),
    )
    _require_same(
        "structured_generation",
        claims.get("structured_generation"),
        digests.get("structured_generation"),
    )

    outer_extras = digests.get("extra_digests")
    if outer_extras is not None and outer_extras != extras:
        raise ReceiptVerificationError("extra_digests namespace does not bind")
    for key, value in extras.items():
        if key in digests and digests[key] != value:
            raise ReceiptVerificationError(
                f"extra_digests {key!r} does not bind outer receipt"
            )
    for key, value in digests.items():
        if key not in STANDARD_CLAIM_KEYS:
            continue
        if key in {
            "eligibility",
            "signature",
            "signed_body_b64",
            "issuer_class",
            "body_digest",
            "extra_digests",
            "raw",
            "issuer_key_id",
            "issuer_id",
        }:
            continue
        if key in claims and not _same(value, claims[key]):
            raise ReceiptVerificationError(
                f"outer digest {key!r} overrides signed claim"
            )

    if required is not None:
        _require_same("required.dataset", claims["dataset"], required.dataset)
        _require_same("required.source", claims["source"], required.source)
        _require_same(
            "required.segment_id", claims["segment_id"], required.segment_id
        )
        if claims.get("segment_start") is not None:
            _require_same(
                "required.segment_start",
                claims["segment_start"],
                required.segment_start,
            )
        if claims.get("segment_end") is not None:
            _require_same(
                "required.segment_end",
                claims["segment_end"],
                required.segment_end,
            )

    if raw is not None:
        _require_same("raw evidence", claims["raw_digest"], compute_raw_digest(raw))
    if structured_digest is not None:
        _require_same(
            "structured evidence", claims.get("structured_digest"), structured_digest
        )

    return VerifiedReceipt(
        _ok=_VERIFIED,
        _claims=MappingProxyType(dict(claims)),
    )


def require_verified_receipt(
    receipt: Any,
    *,
    required: Any = None,
    raw: bytes | None = None,
    structured_digest: str | None = None,
    verify_keys: Mapping[str, Any] | None = None,
) -> VerifiedReceipt:
    """Gate used by coverage evaluation: VerifiedReceipt or raise."""
    return verify(
        receipt,
        required=required,
        raw=raw,
        structured_digest=structured_digest,
        verify_keys=verify_keys,
    )


__all__ = [
    "ReceiptVerificationError",
    "VerifiedReceipt",
    "require_verified_receipt",
    "verify",
]
