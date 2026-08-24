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
from storage.receipt_crypto import partition_extra_digests
from storage.trusted_receipt import SignedReceiptAuthority


def require_signed_receipt_authority(
    authority: SignedReceiptAuthority | None = None,
    *,
    open_if_missing: bool = True,
) -> SignedReceiptAuthority:
    """Verify issuer before governed structured mutation.

    Call this *before* ``Registrar.register`` / fact upsert. ``emit_segment_receipt``
    still requires an explicit authority (no auto-mint).
    """
    if authority is None:
        if not open_if_missing:
            raise TypeError(
                "SignedReceiptAuthority is required; automatic issuer mint is removed"
            )
        from ingestion.runtime_authority import open_ingestion_signing_authority

        return open_ingestion_signing_authority()
    if not isinstance(authority, SignedReceiptAuthority):
        raise TypeError("authority must be SignedReceiptAuthority")
    return authority


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
    authority = require_signed_receipt_authority(
        authority, open_if_missing=False
    )
    if status == "SUCCESS" and error is None and not raw:
        raise ValueError("empty-raw SUCCESS is forbidden")
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
        extra_digests=partition_extra_digests(extra_digests),
    )
    record_collection_receipt(conn, receipt)
    if commit:
        conn.commit()
    return receipt


__all__ = ["emit_segment_receipt", "require_signed_receipt_authority"]
