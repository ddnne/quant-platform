"""JQ collection receipts — signed authority only inside ingestion transaction.

Phase 6.2.3: no automatic mint_ingestion_issuer(). Caller must pass
SignedReceiptAuthority from the trusted ingestion runtime. Receipt emit
failure must fail the surrounding transaction (commit=False by default for
pipeline composition).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.trusted_receipt import SignedReceiptAuthority


def emit_segment_receipt(
    conn: sqlite3.Connection,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    raw: bytes,
    observed_items: int,
    structured_row_count: int,
    authority: SignedReceiptAuthority,
    raw_row_count: int | None = None,
    pagination_exhausted: bool = True,
    status: str = "SUCCESS",
    error: str | None = None,
    checked_at: str | None = None,
    extra_digests: Mapping[str, Any] | None = None,
    source_request_digest: str | None = None,
    raw_manifest_digest: str | None = None,
    structured_generation: int | None = None,
    structured_digest: str | None = None,
    commit: bool = False,
) -> CollectionReceipt:
    """Record a signed collection receipt for one planned J-Quants segment.

    ``authority`` is required (no None auto-mint). Default ``commit=False`` so
    the ingestion transaction commits structured rows + receipt together.
    """
    if authority is None:
        raise TypeError(
            "SignedReceiptAuthority is required; automatic issuer mint is removed"
        )
    if not isinstance(authority, SignedReceiptAuthority):
        raise TypeError("authority must be SignedReceiptAuthority")
    receipt = authority.issue(
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
        source_request_digest=source_request_digest,
        raw_manifest_digest=raw_manifest_digest,
        structured_generation=structured_generation,
        structured_digest=structured_digest,
        extra_digests=extra_digests,
    )
    record_collection_receipt(conn, receipt)
    if commit:
        conn.commit()
    return receipt


__all__ = ["emit_segment_receipt"]
