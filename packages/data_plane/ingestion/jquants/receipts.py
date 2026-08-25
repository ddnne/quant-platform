"""JQ collection receipts — signed authority only inside ingestion transaction.

Phase 6.2.3: no automatic mint_ingestion_issuer(). Caller must pass
SignedReceiptAuthority from the trusted ingestion runtime. Receipt emit
failure must fail the surrounding transaction (commit=False by default for
pipeline composition).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from ingestion.runtime_authority import reconcile_collection_evidence
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    record_collection_receipt,
)
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
    raw_pages: Sequence[bytes],
    raw_records: Sequence[Any],
    structured_records: Sequence[Mapping[str, Any]],
    authority: SignedReceiptAuthority,
    pagination_exhausted: bool = True,
    discovery_exhausted: bool | None = None,
    checked_at: str | None = None,
    source_request: Mapping[str, Any] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
    commit: bool = False,
) -> CollectionReceipt:
    """Measure and record a signed SUCCESS closure for one J-Quants segment.

    ``authority`` is required (no None auto-mint). Default ``commit=False`` so
    the ingestion transaction commits structured rows + receipt together.
    Counts and digests are deliberately absent from this API: the trusted
    runtime derives them from the concrete artifacts supplied here.
    """
    authority = require_signed_receipt_authority(
        authority, open_if_missing=False
    )
    evidence = reconcile_collection_evidence(
        required=required,
        run_id=run_id,
        raw_pages=raw_pages,
        raw_records=raw_records,
        structured_records=structured_records,
        pagination_exhausted=pagination_exhausted,
        discovery_exhausted=discovery_exhausted,
        checked_at=checked_at,
        source_request=source_request,
        extra_evidence=extra_evidence,
    )
    receipt = authority.issue(evidence)
    record_collection_receipt(conn, receipt)
    if commit:
        conn.commit()
    return receipt


__all__ = ["emit_segment_receipt", "require_signed_receipt_authority"]
