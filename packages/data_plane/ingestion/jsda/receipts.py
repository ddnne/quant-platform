"""JSDA governed receipts — signed authority required for SUCCESS.

Raw recovery (staging parse, FAILED unsigned evidence) is a separate path and
must not auto-COMPLETE. Empty-raw SUCCESS is forbidden.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ingestion.runtime_authority import open_ingestion_signing_authority
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.trusted_receipt import SignedReceiptAuthority


def require_jsda_receipt_authority(
    authority: SignedReceiptAuthority | None = None,
) -> SignedReceiptAuthority:
    """Verify TrustedReceiptIssuer/SignedReceiptAuthority before structured write."""
    if authority is None:
        return open_ingestion_signing_authority()
    if not isinstance(authority, SignedReceiptAuthority):
        raise TypeError("authority must be SignedReceiptAuthority")
    return authority


def record_governed_receipt(
    store,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    checked_at: str,
    status: str,
    error: Optional[str],
    observed_items: int,
    raw_page_count: int,
    raw_row_count: int,
    structured_row_count: int,
    pagination_exhausted: bool,
    digests: Mapping[str, Any],
    authority: SignedReceiptAuthority | None = None,
    raw: bytes = b"",
) -> None:
    """Record a collection receipt. SUCCESS requires verified authority + raw."""
    stamped = dict(digests)
    if status == "SUCCESS" and error is None:
        if not raw or int(raw_row_count) <= 0:
            raise ValueError("empty-raw governed SUCCESS is forbidden")
        if authority is None:
            raise RuntimeError(
                "SignedReceiptAuthority is required before governed SUCCESS"
            )
        source_request = stamped.get("source_request_digest")
        raw_manifest = stamped.get("raw_manifest_digest") or stamped.get("raw")
        issued = authority.issue(
            required=required,
            run_id=run_id,
            raw=raw,
            observed_items=observed_items,
            structured_row_count=structured_row_count,
            raw_row_count=raw_row_count,
            pagination_exhausted=pagination_exhausted,
            status="SUCCESS",
            error=None,
            checked_at=checked_at,
            extra_digests=stamped,
            source_request_digest=(
                source_request if isinstance(source_request, str) else None
            ),
            raw_manifest_digest=(
                raw_manifest if isinstance(raw_manifest, str) else None
            ),
            structured_generation=run_id,
        )
        stamped = dict(issued.digests)
    else:
        stamped.setdefault("eligibility", "RECOVERED_RAW_ONLY")
        stamped.setdefault("origin", "failed-collection")
    record_collection_receipt(store._conn, CollectionReceipt(  # noqa: SLF001
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=required.expected_scope,
        expected_items=required.expected_items,
        observed_items=observed_items,
        raw_page_count=raw_page_count,
        raw_row_count=raw_row_count,
        structured_row_count=structured_row_count,
        pagination_exhausted=pagination_exhausted,
        digests=stamped,
        run_id=run_id,
        status=status,
        error=error,
        checked_at=checked_at,
    ))
    store._conn.commit()  # noqa: SLF001


__all__ = [
    "record_governed_receipt",
    "require_jsda_receipt_authority",
]
