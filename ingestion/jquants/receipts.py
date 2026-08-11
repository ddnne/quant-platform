"""Collection-receipt emit path for J-Quants catalog ingestion (Lane H).

The JSDA governed archive runners (:mod:`ingestion.jsda.archive`,
:mod:`ingestion.jsda.repo_archive`, :mod:`ingestion.jsda.corrections`) write
real collection receipts inline as each archive segment is fetched. The
J-Quants catalog path (:func:`ingestion.pipeline.run_jquants`) historically
persisted raw bytes and structured rows but emitted **no** receipts — leaving
every J-Quants governed dataset at PARTIAL/UNKNOWN with zero receipts.

This module is the minimal, honest writer that closes that gap. It computes a
real SHA-256 digest over the *actual* persisted source bytes for a planned
segment and records a :class:`~storage.coverage_ledger.CollectionReceipt` via
:func:`storage.coverage_ledger.record_collection_receipt`.

It records the truth; :func:`storage.coverage_ledger.evaluate_segment` (run by
:func:`~storage.coverage_ledger.refresh_coverage_ledger`) decides whether the
segment is COMPLETE. A non-event segment without an explicit expected-items
count therefore stays PARTIAL rather than being faked to COMPLETE — this is
the safety property that keeps live COMPLETE honest.

The operational entry point is :func:`scripts.write_collection_receipts`;
both share :func:`~storage.coverage_ledger.build_collection_receipt` so the
raw digest is always computed over real bytes.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    build_collection_receipt,
    record_collection_receipt,
)


def emit_segment_receipt(
    conn: sqlite3.Connection,
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
    extra_digests: Mapping[str, Any] | None = None,
    commit: bool = True,
) -> CollectionReceipt:
    """Record a real collection receipt for one planned J-Quants segment.

    Parameters mirror :func:`~storage.coverage_ledger.build_collection_receipt`.
    ``raw`` must be the verbatim bytes persisted for the segment (the digest is
    computed over it). The caller owns segment identity: pass the exact
    :class:`~storage.coverage_ledger.RequiredCoverageSegment` produced by
    :func:`~storage.coverage_ledger.plan_required_segments` so the receipt's
    expected scope matches and the segment can evaluate to COMPLETE once the
    policy gates (pagination, expected items, raw retention) are satisfied.

    Set ``commit=False`` to batch several receipts inside one caller-owned
    transaction.
    """
    receipt = build_collection_receipt(
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
        extra_digests=extra_digests,
    )
    record_collection_receipt(conn, receipt)
    if commit:
        conn.commit()
    return receipt


__all__ = ["emit_segment_receipt"]
