"""Verify signed collection closures before coverage can observe them.

Persisted ``CollectionReceipt`` fields are untrusted mirrors.  This module is
the only constructor of ``VerifiedCollectionClosure`` and binds every field
used by COMPLETE policy to signed-receipt-claims/v2.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
import json
from types import MappingProxyType
from typing import Any, Mapping
from weakref import WeakSet

from qp_paths import repo_root
from storage.coverage_receipts import compute_raw_digest
from storage.receipt_crypto import (
    LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
    PARSER_NORMALIZER_VERSION,
    SIGNED_RECEIPT_CLAIMS_VERSION,
    STANDARD_CLAIM_KEYS,
    body_digest,
    canonical_evidence_digest,
    verify_receipt_signature_values,
)


_VERIFIED_CLOSURE = object()
_VERIFIED_CLOSURES: WeakSet[Any] = WeakSet()
_SCHEMA_PATH = (
    repo_root() / "specs" / "receipts" / "signed_receipt_claims.schema.json"
)


class ReceiptVerificationError(ValueError):
    """Signed claims do not close over the receipt or required segment."""


_RECEIPT_STRING_FIELDS = (
    "source",
    "dataset",
    "segment_id",
    "segment_start",
    "segment_end",
    "status",
    "checked_at",
)
_RECEIPT_INT_FIELDS = (
    "observed_items",
    "raw_page_count",
    "raw_row_count",
    "structured_row_count",
    "run_id",
)
_SIGNED_ENVELOPE_FIELDS = frozenset(
    {
        "eligibility",
        "issuer_class",
        "issuer_key_id",
        "issuer_id",
        "parser_normalizer_version",
        "signed_body_b64",
        "signature",
        "body_digest",
        "issued_at",
        "checked_at",
        "source_request_digest",
        "raw_manifest_digest",
        "raw",
        "structured_generation",
        "structured_digest",
        "scope_digest",
        "observation_digest",
        "extra_digests",
    }
)


@dataclass(frozen=True, slots=True)
class _FrozenReceiptInput:
    outer: Mapping[str, Any]
    digests: Mapping[str, Any]
    claims: Mapping[str, Any]
    signed_body: bytes


def _copy_exact_json(value: Any, *, field: str) -> Any:
    """Copy one JSON value while rejecting adapters and scalar subclasses."""
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in dict.items(value):
            if type(key) is not str or key in copied:
                raise ReceiptVerificationError(
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
    raise ReceiptVerificationError(
        f"{field} must contain only exact JSON built-in values"
    )


def _decode_strict_signed_claims(body_b64: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = base64.b64decode(body_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ReceiptVerificationError("signed body is not valid base64") from exc

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ReceiptVerificationError(
                    f"signed body contains duplicate key {key!r}"
                )
            document[key] = value
        return document

    def reject_nonfinite(value: str) -> None:
        raise ReceiptVerificationError(
            f"signed body contains non-finite value {value!r}"
        )

    try:
        claims = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except ReceiptVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptVerificationError("signed body is not valid JSON") from exc
    if type(claims) is not dict:
        raise ReceiptVerificationError("signed body must be an object")
    return _copy_exact_json(claims, field="signed claims"), raw


def _materialize_receipt_input(receipt: Any) -> _FrozenReceiptInput:
    """Read an exact receipt and its envelope once for all trust decisions."""
    from storage.coverage_ledger import CollectionReceipt

    if type(receipt) is not CollectionReceipt:
        raise ReceiptVerificationError("exact CollectionReceipt required")
    attribute_names = (
        *_RECEIPT_STRING_FIELDS,
        "expected_scope",
        "expected_items",
        *_RECEIPT_INT_FIELDS,
        "pagination_exhausted",
        "digests",
        "error",
    )
    observed = {
        name: object.__getattribute__(receipt, name) for name in attribute_names
    }
    if any(
        type(observed[name]) is not str or not observed[name]
        for name in _RECEIPT_STRING_FIELDS
    ):
        raise ReceiptVerificationError(
            "receipt string fields must be exact non-empty strings"
        )
    if any(
        type(observed[name]) is not int or observed[name] < 0
        for name in _RECEIPT_INT_FIELDS
    ):
        raise ReceiptVerificationError(
            "receipt count/run fields must be exact non-negative integers"
        )
    expected_items = observed["expected_items"]
    if expected_items is not None and (
        type(expected_items) is not int or expected_items < 0
    ):
        raise ReceiptVerificationError(
            "receipt expected_items must be an exact non-negative integer or null"
        )
    if type(observed["pagination_exhausted"]) is not bool:
        raise ReceiptVerificationError(
            "receipt pagination_exhausted must be an exact bool"
        )
    error = observed["error"]
    if error is not None and type(error) is not str:
        raise ReceiptVerificationError("receipt error must be an exact string or null")
    expected_scope = _copy_exact_json(
        observed["expected_scope"], field="receipt.expected_scope"
    )
    if type(expected_scope) is not dict:
        raise ReceiptVerificationError("receipt expected_scope must be an exact object")
    if type(observed["digests"]) is not dict:
        raise ReceiptVerificationError(
            "receipt digests must be an exact built-in dict"
        )
    digests = _copy_exact_json(observed["digests"], field="receipt.digests")
    body_b64 = digests.get("signed_body_b64")
    if type(body_b64) is not str or not body_b64:
        raise ReceiptVerificationError("missing signed_body_b64")
    claims, signed_body = _decode_strict_signed_claims(body_b64)
    extras = claims.get("extra_digests")
    if type(extras) is not dict:
        raise ReceiptVerificationError("signed extra_digests must be an exact object")
    expected_envelope_fields = _SIGNED_ENVELOPE_FIELDS | frozenset(extras)
    if set(digests) != expected_envelope_fields:
        missing = sorted(expected_envelope_fields - set(digests))
        extra = sorted(set(digests) - expected_envelope_fields)
        raise ReceiptVerificationError(
            "signed receipt envelope fields are not closed: "
            f"missing={missing}, extra={extra}"
        )
    string_envelope_fields = _SIGNED_ENVELOPE_FIELDS - {
        "structured_generation",
        "extra_digests",
    }
    if any(
        type(digests[field]) is not str or not digests[field]
        for field in string_envelope_fields
    ):
        raise ReceiptVerificationError(
            "signed receipt envelope strings must be exact and non-empty"
        )
    if (
        type(digests["structured_generation"]) is not int
        or digests["structured_generation"] < 0
        or type(digests["extra_digests"]) is not dict
    ):
        raise ReceiptVerificationError(
            "signed receipt envelope structured values are invalid"
        )
    outer = {
        **{name: observed[name] for name in _RECEIPT_STRING_FIELDS},
        **{name: observed[name] for name in _RECEIPT_INT_FIELDS},
        "expected_scope": expected_scope,
        "expected_items": expected_items,
        "pagination_exhausted": observed["pagination_exhausted"],
        "error": error,
    }
    return _FrozenReceiptInput(
        outer=MappingProxyType(outer),
        digests=MappingProxyType(digests),
        claims=MappingProxyType(claims),
        signed_body=signed_body,
    )


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze verified claims before exposing the capability."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True, eq=False)
class VerifiedCollectionClosure:
    """Opaque proof that every COMPLETE input is signed and bound."""

    _seal: object
    _claims: Mapping[str, Any]
    _receipt_digest: str

    def __post_init__(self) -> None:
        if self._seal is not _VERIFIED_CLOSURE:
            raise TypeError(
                "VerifiedCollectionClosure is opaque; call "
                "require_verified_collection_closure()"
            )

    def _assert_verifier_minted(self) -> None:
        if self not in _VERIFIED_CLOSURES:
            raise TypeError(
                "VerifiedCollectionClosure is not verifier-minted"
            )

    def _value(self, name: str) -> Any:
        self._assert_verifier_minted()
        return self._claims[name]

    @property
    def receipt_digest(self) -> str:
        self._assert_verifier_minted()
        return self._receipt_digest

    @property
    def coverage_policy_version(self) -> str:
        return str(self._value("coverage_policy_version"))

    @property
    def source(self) -> str:
        return str(self._value("source"))

    @property
    def dataset(self) -> str:
        return str(self._value("dataset"))

    @property
    def segment_id(self) -> str:
        return str(self._value("segment_id"))

    @property
    def segment_start(self) -> str:
        return str(self._value("segment_start"))

    @property
    def segment_end(self) -> str:
        return str(self._value("segment_end"))

    @property
    def expected_scope(self) -> Mapping[str, Any]:
        value = self._value("expected_scope")
        if not isinstance(value, Mapping):  # schema validation makes this unreachable
            raise ReceiptVerificationError("verified expected_scope is not a mapping")
        return value

    @property
    def expected_items(self) -> int | None:
        value = self._value("expected_items")
        return None if value is None else int(value)

    @property
    def observed_items(self) -> int:
        return int(self._value("observed_items"))

    @property
    def raw_page_count(self) -> int:
        return int(self._value("raw_page_count"))

    @property
    def raw_row_count(self) -> int:
        return int(self._value("raw_count"))

    @property
    def structured_row_count(self) -> int:
        return int(self._value("structured_count"))

    @property
    def pagination_exhausted(self) -> bool:
        return bool(self._value("pagination_exhausted"))

    @property
    def discovery_exhausted(self) -> bool:
        return bool(self._value("discovery_exhausted"))

    @property
    def status(self) -> str:
        return str(self._value("status"))

    @property
    def error(self) -> None:
        return None

    @property
    def raw_digest(self) -> str:
        return str(self._value("raw_digest"))

    @property
    def raw_manifest_digest(self) -> str:
        return str(self._value("raw_manifest_digest"))

    @property
    def structured_digest(self) -> str:
        return str(self._value("structured_digest"))

    @property
    def structured_generation(self) -> int:
        return int(self._value("structured_generation"))

    @property
    def scope_digest(self) -> str:
        return str(self._value("scope_digest"))

    @property
    def observation_digest(self) -> str:
        return str(self._value("observation_digest"))

    @property
    def run_id(self) -> int:
        return int(self._value("run_id"))

    @property
    def checked_at(self) -> str:
        return str(self._value("checked_at"))

    @property
    def extra_digests(self) -> Mapping[str, Any]:
        value = self._value("extra_digests")
        if not isinstance(value, Mapping):  # schema validation makes this unreachable
            raise ReceiptVerificationError("verified extra_digests is not a mapping")
        return value

    def to_proof_dict(self) -> dict[str, Any]:
        """Bound fields retained by the READY coverage proof."""
        return {
            "receipt_digest": self.receipt_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "source": self.source,
            "dataset": self.dataset,
            "segment_id": self.segment_id,
            "segment_start": self.segment_start,
            "segment_end": self.segment_end,
            "scope_digest": self.scope_digest,
            "expected_items": self.expected_items,
            "observed_items": self.observed_items,
            "raw_page_count": self.raw_page_count,
            "raw_row_count": self.raw_row_count,
            "structured_row_count": self.structured_row_count,
            "pagination_exhausted": self.pagination_exhausted,
            "discovery_exhausted": self.discovery_exhausted,
            "raw_manifest_digest": self.raw_manifest_digest,
            "raw_digest": self.raw_digest,
            "structured_digest": self.structured_digest,
            "structured_generation": self.structured_generation,
            "observation_digest": self.observation_digest,
            "run_id": self.run_id,
            "checked_at": self.checked_at,
        }


@lru_cache(maxsize=1)
def _claims_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _claims_validator() -> Any:
    """Compile the closed v2 schema once for large snapshot inventories."""
    try:
        import jsonschema
    except ImportError as exc:
        raise ReceiptVerificationError(
            "jsonschema is required to verify signed receipt claims"
        ) from exc
    validator = jsonschema.Draft202012Validator(_claims_schema())
    validator.check_schema(_claims_schema())
    return validator


def _validate_schema(claims: Mapping[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ReceiptVerificationError(
            "jsonschema is required to verify signed receipt claims"
        ) from exc
    try:
        _claims_validator().validate(dict(claims))
    except jsonschema.ValidationError as exc:
        raise ReceiptVerificationError(
            f"signed claims fail closed schema: {exc.message}"
        ) from exc


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return dict(left) == dict(right)
    if left is None or right is None:
        return left is right
    return type(left) is type(right) and left == right


def _require_same(label: str, signed_value: Any, outer_value: Any) -> None:
    if not _same(signed_value, outer_value):
        raise ReceiptVerificationError(
            f"signed {label} does not bind untrusted receipt"
        )


def _validate_digest_chain(claims: Mapping[str, Any]) -> None:
    """Recompute the signed scope -> observation digest chain."""
    scope = {
        "coverage_policy_version": claims["coverage_policy_version"],
        "source": claims["source"],
        "dataset": claims["dataset"],
        "segment_id": claims["segment_id"],
        "segment_start": claims["segment_start"],
        "segment_end": claims["segment_end"],
        "expected_scope": claims["expected_scope"],
        "expected_items": claims["expected_items"],
    }
    _require_same(
        "scope_digest chain",
        claims["scope_digest"],
        canonical_evidence_digest(scope),
    )
    observation = {
        **scope,
        "observed_items": claims["observed_items"],
        "raw_page_count": claims["raw_page_count"],
        "raw_count": claims["raw_count"],
        "structured_count": claims["structured_count"],
        "status": claims["status"],
        "error": claims["error"],
        "pagination_exhausted": claims["pagination_exhausted"],
        "discovery_exhausted": claims["discovery_exhausted"],
        "source_request_digest": claims["source_request_digest"],
        "raw_manifest_digest": claims["raw_manifest_digest"],
        "raw_digest": claims["raw_digest"],
        "structured_digest": claims["structured_digest"],
        "structured_generation": claims["structured_generation"],
        "scope_digest": claims["scope_digest"],
        "run_id": claims["run_id"],
        "checked_at": claims["checked_at"],
        "extra_digests": claims["extra_digests"],
    }
    _require_same(
        "observation_digest chain",
        claims["observation_digest"],
        canonical_evidence_digest(observation),
    )


def audit_signed_receipt_claims(
    receipt: Any,
) -> Mapping[str, Any]:
    """Decode a valid v1/v2 signature for audit without granting COMPLETE."""
    frozen = _materialize_receipt_input(receipt)
    digests = frozen.digests
    claims = frozen.claims
    if not verify_receipt_signature_values(
        body=frozen.signed_body,
        signature=digests["signature"],
        key_id=digests["issuer_key_id"],
    ):
        raise ReceiptVerificationError("Ed25519 signature is invalid")
    declared = digests.get("body_digest")
    if declared is not None and declared != body_digest(frozen.signed_body):
        raise ReceiptVerificationError("signed body_digest mismatch")
    version = claims.get("version")
    if version not in {
        LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
        SIGNED_RECEIPT_CLAIMS_VERSION,
    }:
        raise ReceiptVerificationError("unsupported signed claims version")
    key_id = digests.get("issuer_key_id")
    if claims.get("issuer_id") != key_id:
        raise ReceiptVerificationError("signed audit issuer_id mismatch")
    envelope_issuer = digests.get("issuer_id")
    if envelope_issuer is not None and envelope_issuer != key_id:
        raise ReceiptVerificationError("audit envelope issuer_id mismatch")
    return _deep_freeze(claims)


def verify_collection_closure(
    receipt: Any,
    *,
    required: Any = None,
    expected_policy_version: str | None = None,
    raw: bytes | None = None,
    structured_digest: str | None = None,
) -> VerifiedCollectionClosure:
    """Return an opaque v2 closure or fail without a partial trust result."""
    frozen = _materialize_receipt_input(receipt)
    digests = frozen.digests
    claims = frozen.claims
    outer = frozen.outer
    if digests.get("synthetic"):
        raise ReceiptVerificationError("synthetic receipts are not verifiable")
    if digests.get("eligibility") != "TRUSTED_COLLECTION":
        raise ReceiptVerificationError("receipt is not a trusted collection")
    if not verify_receipt_signature_values(
        body=frozen.signed_body,
        signature=digests["signature"],
        key_id=digests["issuer_key_id"],
    ):
        raise ReceiptVerificationError("Ed25519 signature is invalid")

    version = claims.get("version")
    if version == LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION:
        raise ReceiptVerificationError(
            "signed-receipt-claims/v1 is audit-only and not COMPLETE-eligible"
        )
    if version != SIGNED_RECEIPT_CLAIMS_VERSION:
        raise ReceiptVerificationError("unsupported signed claims version")
    _validate_schema(claims)
    _validate_digest_chain(claims)
    if body_digest(frozen.signed_body) != digests.get("body_digest"):
        raise ReceiptVerificationError("signed body_digest mismatch")

    extras = claims["extra_digests"]
    overlap = sorted(set(extras) & STANDARD_CLAIM_KEYS)
    if overlap:
        raise ReceiptVerificationError(
            f"extra_digests overrides standard claims: {overlap}"
        )
    if claims["parser_normalizer_version"] != PARSER_NORMALIZER_VERSION:
        raise ReceiptVerificationError("parser_normalizer_version mismatch")

    outer_bindings = {
        "source": outer["source"],
        "dataset": outer["dataset"],
        "segment_id": outer["segment_id"],
        "segment_start": outer["segment_start"],
        "segment_end": outer["segment_end"],
        "expected_scope": outer["expected_scope"],
        "expected_items": outer["expected_items"],
        "observed_items": outer["observed_items"],
        "raw_page_count": outer["raw_page_count"],
        "raw_count": outer["raw_row_count"],
        "structured_count": outer["structured_row_count"],
        "pagination_exhausted": outer["pagination_exhausted"],
        "run_id": outer["run_id"],
        "status": outer["status"],
        "error": outer["error"],
        "checked_at": outer["checked_at"],
    }
    for name, outer_value in outer_bindings.items():
        _require_same(name, claims[name], outer_value)

    envelope_bindings = {
        "raw_digest": digests.get("raw"),
        "structured_digest": digests.get("structured_digest"),
        "parser_normalizer_version": digests.get("parser_normalizer_version"),
        "source_request_digest": digests.get("source_request_digest"),
        "raw_manifest_digest": digests.get("raw_manifest_digest"),
        "structured_generation": digests.get("structured_generation"),
        "scope_digest": digests.get("scope_digest"),
        "observation_digest": digests.get("observation_digest"),
        "issued_at": digests.get("issued_at"),
    }
    for name, outer_value in envelope_bindings.items():
        _require_same(name, claims[name], outer_value)
    issuer_id = claims["issuer_id"]
    _require_same("issuer_id", issuer_id, digests.get("issuer_id"))
    _require_same("issuer_key_id", issuer_id, digests.get("issuer_key_id"))
    if digests.get("extra_digests") != extras:
        raise ReceiptVerificationError("extra_digests namespace does not bind")
    for key, value in extras.items():
        if key in digests and not _same(digests[key], value):
            raise ReceiptVerificationError(
                f"extra_digests {key!r} does not bind envelope"
            )

    if required is not None:
        from storage.coverage_ledger import RequiredCoverageSegment

        if type(required) is not RequiredCoverageSegment:
            raise ReceiptVerificationError(
                "exact RequiredCoverageSegment required"
            )
        required_names = (
            "source",
            "dataset",
            "segment_id",
            "segment_start",
            "segment_end",
            "expected_scope",
            "expected_items",
        )
        required_values = {
            name: object.__getattribute__(required, name)
            for name in required_names
        }
        required_scope = _copy_exact_json(
            required_values["expected_scope"], field="required.expected_scope"
        )
        if type(required_scope) is not dict:
            raise ReceiptVerificationError(
                "required expected_scope must be an exact object"
            )
        if any(
            type(required_values[name]) is not str or not required_values[name]
            for name in required_names[:5]
        ):
            raise ReceiptVerificationError(
                "required identity fields must be exact non-empty strings"
            )
        required_expected = required_values["expected_items"]
        if required_expected is not None and (
            type(required_expected) is not int or required_expected < 0
        ):
            raise ReceiptVerificationError(
                "required expected_items must be an exact non-negative integer or null"
            )
        required_bindings = {
            "source": required_values["source"],
            "dataset": required_values["dataset"],
            "segment_id": required_values["segment_id"],
            "segment_start": required_values["segment_start"],
            "segment_end": required_values["segment_end"],
            "expected_scope": required_scope,
            "expected_items": required_expected,
        }
        for name, value in required_bindings.items():
            _require_same(f"required.{name}", claims[name], value)
    if expected_policy_version is not None:
        if type(expected_policy_version) is not str:
            raise ReceiptVerificationError(
                "expected policy version must be an exact string"
            )
        _require_same(
            "coverage_policy_version",
            claims["coverage_policy_version"],
            expected_policy_version,
        )
    if raw is not None:
        if type(raw) is not bytes:
            raise ReceiptVerificationError("raw evidence must be exact bytes")
        _require_same("raw evidence", claims["raw_digest"], compute_raw_digest(raw))
    if structured_digest is not None:
        if type(structured_digest) is not str:
            raise ReceiptVerificationError(
                "structured digest must be an exact string"
            )
        _require_same(
            "structured evidence", claims["structured_digest"], structured_digest
        )

    closure = VerifiedCollectionClosure(
        _seal=_VERIFIED_CLOSURE,
        _claims=_deep_freeze(claims),
        _receipt_digest=str(digests["body_digest"]),
    )
    _VERIFIED_CLOSURES.add(closure)
    return closure


def require_verified_collection_closure(
    receipt: Any,
    **kwargs: Any,
) -> VerifiedCollectionClosure:
    return verify_collection_closure(receipt, **kwargs)


# Read compatibility only. New code must use the closure names above.
VerifiedReceipt = VerifiedCollectionClosure
verify = verify_collection_closure
require_verified_receipt = require_verified_collection_closure


__all__ = [
    "ReceiptVerificationError",
    "VerifiedCollectionClosure",
    "audit_signed_receipt_claims",
    "require_verified_collection_closure",
    "verify_collection_closure",
]
