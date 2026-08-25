"""Receipt signing boundary for reconciled collection evidence.

``CollectionReceipt`` is a persisted, untrusted transport document.  The
signing authority never accepts loose counts or digests; it accepts only the
opaque ``ReconciledCollectionEvidence`` produced by the ingestion runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping
from weakref import WeakSet

from storage.coverage_ledger import CollectionReceipt, RequiredCoverageSegment
from storage.receipt_crypto import (
    PARSER_NORMALIZER_VERSION,
    ReceiptSigningKey,
    build_signed_digest_fields,
    load_signing_key,
)

if TYPE_CHECKING:
    from pathlib import Path


_RECONCILED = object()
_RUNTIME_EVIDENCE: WeakSet[Any] = WeakSet()
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


@dataclass(frozen=True, eq=False)
class ReconciledCollectionEvidence:
    """Opaque, measured SUCCESS evidence accepted by the signer.

    Construction is intentionally sealed.  The trusted ingestion runtime
    measures raw pages and structured records, then calls the private factory
    below.  Recovery, partial, and failed observations never obtain this type.
    """

    _seal: object
    required: RequiredCoverageSegment
    coverage_policy_version: str
    run_id: int
    observed_items: int
    raw_page_count: int
    raw_row_count: int
    structured_row_count: int
    pagination_exhausted: bool
    discovery_exhausted: bool
    source_request_digest: str
    raw_manifest_digest: str
    raw_digest: str
    structured_digest: str
    structured_generation: int
    scope_digest: str
    observation_digest: str
    checked_at: str
    extra_digests: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self._seal is not _RECONCILED:
            raise TypeError(
                "ReconciledCollectionEvidence is opaque; use the ingestion "
                "reconciliation boundary"
            )
        counts = (
            self.run_id,
            self.observed_items,
            self.raw_page_count,
            self.raw_row_count,
            self.structured_row_count,
            self.structured_generation,
        )
        if any(int(value) < 0 for value in counts):
            raise ValueError("reconciled collection counts must be non-negative")
        if self.raw_page_count < 1:
            raise ValueError("reconciled SUCCESS requires at least one measured raw page")
        if not self.pagination_exhausted or not self.discovery_exhausted:
            raise ValueError("non-exhausted collection evidence is not signable")
        if not self.coverage_policy_version or not self.checked_at:
            raise ValueError("coverage policy version and checked_at are required")
        for name in (
            "source_request_digest",
            "raw_manifest_digest",
            "raw_digest",
            "structured_digest",
            "scope_digest",
            "observation_digest",
        ):
            if not _SHA256_RE.fullmatch(str(getattr(self, name))):
                raise ValueError(f"{name} must be a sha256 digest")
        object.__setattr__(
            self,
            "extra_digests",
            _deep_freeze(self.extra_digests),
        )

    def to_closure_claims(self) -> dict[str, Any]:
        required = self.required
        return {
            "coverage_policy_version": self.coverage_policy_version,
            "source": required.source,
            "dataset": required.dataset,
            "segment_id": required.segment_id,
            "segment_start": required.segment_start,
            "segment_end": required.segment_end,
            "expected_scope": _deep_thaw(required.expected_scope),
            "expected_items": required.expected_items,
            "observed_items": self.observed_items,
            "raw_page_count": self.raw_page_count,
            "raw_count": self.raw_row_count,
            "structured_count": self.structured_row_count,
            "status": "SUCCESS",
            "error": None,
            "pagination_exhausted": self.pagination_exhausted,
            "discovery_exhausted": self.discovery_exhausted,
            "source_request_digest": self.source_request_digest,
            "raw_manifest_digest": self.raw_manifest_digest,
            "raw_digest": self.raw_digest,
            "structured_digest": self.structured_digest,
            "structured_generation": self.structured_generation,
            "scope_digest": self.scope_digest,
            "observation_digest": self.observation_digest,
            "run_id": self.run_id,
            "checked_at": self.checked_at,
            "extra_digests": _deep_thaw(self.extra_digests),
        }


def _make_reconciled_collection_evidence(
    *,
    required: RequiredCoverageSegment,
    coverage_policy_version: str,
    run_id: int,
    observed_items: int,
    raw_page_count: int,
    raw_row_count: int,
    structured_row_count: int,
    pagination_exhausted: bool,
    discovery_exhausted: bool,
    source_request_digest: str,
    raw_manifest_digest: str,
    raw_digest: str,
    structured_digest: str,
    structured_generation: int,
    scope_digest: str,
    observation_digest: str,
    checked_at: str,
    extra_digests: Mapping[str, Any],
) -> ReconciledCollectionEvidence:
    """Private constructor used by ``ingestion.runtime_authority`` only."""
    frozen_required = RequiredCoverageSegment(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=_deep_freeze(required.expected_scope),
        expected_items=required.expected_items,
    )
    evidence = ReconciledCollectionEvidence(
        _seal=_RECONCILED,
        required=frozen_required,
        coverage_policy_version=coverage_policy_version,
        run_id=int(run_id),
        observed_items=int(observed_items),
        raw_page_count=int(raw_page_count),
        raw_row_count=int(raw_row_count),
        structured_row_count=int(structured_row_count),
        pagination_exhausted=bool(pagination_exhausted),
        discovery_exhausted=bool(discovery_exhausted),
        source_request_digest=source_request_digest,
        raw_manifest_digest=raw_manifest_digest,
        raw_digest=raw_digest,
        structured_digest=structured_digest,
        structured_generation=int(structured_generation),
        scope_digest=scope_digest,
        observation_digest=observation_digest,
        checked_at=checked_at,
        extra_digests=extra_digests,
    )
    _RUNTIME_EVIDENCE.add(evidence)
    return evidence


@dataclass(frozen=True)
class SignedReceiptAuthority:
    """Private-key capability that signs only reconciled SUCCESS evidence."""

    signing_key: ReceiptSigningKey
    parser_normalizer_version: str = PARSER_NORMALIZER_VERSION

    def issue(self, evidence: ReconciledCollectionEvidence) -> CollectionReceipt:
        if (
            not isinstance(evidence, ReconciledCollectionEvidence)
            or evidence not in _RUNTIME_EVIDENCE
        ):
            raise TypeError(
                "SignedReceiptAuthority.issue requires "
                "runtime-minted ReconciledCollectionEvidence"
            )
        if self.parser_normalizer_version != PARSER_NORMALIZER_VERSION:
            raise ValueError("receipt authority parser version is not current")
        signed = build_signed_digest_fields(
            signing_key=self.signing_key,
            closure_claims=evidence.to_closure_claims(),
        )
        required = evidence.required
        return CollectionReceipt(
            source=required.source,
            dataset=required.dataset,
            segment_id=required.segment_id,
            segment_start=required.segment_start,
            segment_end=required.segment_end,
            expected_scope=_deep_thaw(required.expected_scope),
            expected_items=required.expected_items,
            observed_items=evidence.observed_items,
            raw_page_count=evidence.raw_page_count,
            raw_row_count=evidence.raw_row_count,
            structured_row_count=evidence.structured_row_count,
            pagination_exhausted=evidence.pagination_exhausted,
            digests=MappingProxyType(dict(signed)),
            run_id=evidence.run_id,
            status="SUCCESS",
            error=None,
            checked_at=evidence.checked_at,
        )


def _open_signed_receipt_authority(
    *,
    pem: bytes | str | None = None,
    path: Path | None = None,
    key_id: str | None = None,
) -> SignedReceiptAuthority:
    """Private key loader for :mod:`ingestion.runtime_authority` only."""
    key = load_signing_key(pem=pem, path=path, key_id=key_id)
    if key is None:
        raise RuntimeError("receipt signing authority is not configured")
    return SignedReceiptAuthority(signing_key=key)


TrustedReceiptIssuer = SignedReceiptAuthority


__all__ = [
    "ReconciledCollectionEvidence",
    "SignedReceiptAuthority",
    "TrustedReceiptIssuer",
]
