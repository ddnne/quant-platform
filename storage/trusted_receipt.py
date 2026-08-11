"""TrustedReceiptIssuer — only ingestion transactions mint TRUSTED_COLLECTION.

Ops scripts / agents / general library callers cannot obtain the issuer
capability. build_synthetic_complete_receipt remains test-only via tests package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    build_collection_receipt,
)


@dataclass(frozen=True)
class TrustedReceiptIssuer:
    """Capability object granted only to the trusted ingestion transaction path.

    Construction is unrestricted in Python (cannot fully seal without runtime
    isolation), but Coverage COMPLETE only accepts receipts whose digests
    include issuer_class + issuer_id from this type, and production code paths
    only receive an issuer from the ingestion pipeline.
    """

    issuer_id: str
    issuer_class: str = "TrustedReceiptIssuer"
    parser_normalizer_version: str = "coverage-receipt/v2"

    def __post_init__(self) -> None:
        if self.issuer_class != "TrustedReceiptIssuer":
            raise ValueError("invalid issuer_class")
        if not self.issuer_id.strip():
            raise ValueError("issuer_id required")

    def issue(
        self,
        *,
        required: RequiredCoverageSegment,
        run_id: int,
        raw: bytes,
        observed_items: int,
        structured_row_count: int,
        raw_row_count: int | None = None,
        pagination_exhausted: bool = True,
        status: str = "SUCCESS",
        error: str | None = None,
        checked_at: str | None = None,
        source_request_digest: str | None = None,
        raw_manifest_digest: str | None = None,
        structured_generation: int | None = None,
        extra_digests: Mapping[str, Any] | None = None,
    ) -> CollectionReceipt:
        digests: dict[str, Any] = {
            "eligibility": "TRUSTED_COLLECTION",
            "issuer_class": self.issuer_class,
            "issuer_id": self.issuer_id,
            "parser_normalizer_version": self.parser_normalizer_version,
        }
        if source_request_digest:
            digests["source_request_digest"] = source_request_digest
        if raw_manifest_digest:
            digests["raw_manifest_digest"] = raw_manifest_digest
        if structured_generation is not None:
            digests["structured_generation"] = int(structured_generation)
        if extra_digests:
            digests.update(dict(extra_digests))
        # Prevent callers from downgrading eligibility via extras.
        digests["eligibility"] = "TRUSTED_COLLECTION"
        digests["issuer_class"] = self.issuer_class
        digests["issuer_id"] = self.issuer_id
        return build_collection_receipt(
            required=required,
            run_id=run_id,
            raw=raw,
            observed_items=observed_items,
            structured_row_count=structured_row_count,
            raw_row_count=raw_row_count,
            pagination_exhausted=pagination_exhausted,
            status=status,
            error=error,
            checked_at=checked_at,
            extra_digests=digests,
        )


def mint_ingestion_issuer(*, run_id: int, source: str) -> TrustedReceiptIssuer:
    """Factory used by the ingestion pipeline only."""
    return TrustedReceiptIssuer(issuer_id=f"{source}:run:{int(run_id)}")


__all__ = [
    "TrustedReceiptIssuer",
    "mint_ingestion_issuer",
]
