"""Storage layer — SQLite schema + writer for structured ingestion rows.

Every structured row carries the PIT columns:
``event_time`` / ``available_at`` / ``source`` / ``ingested_at``.
``available_at`` is mandatory (enforced in :mod:`storage.sqlite_store`).
"""

from .coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    SYNTHETIC_RECEIPT_MARKER,
    aggregate_status_from_segment_counts,
    build_collection_receipt,
    build_surgical_reagg_detail,
    compute_raw_digest,
    coverage_gaps,
    coverage_summary,
    evaluate_required_segments,
    evaluate_segment,
    honest_status_counts,
    is_complete_eligible_receipt,
    is_synthetic_receipt,
    plan_required_segments,
    read_collection_receipts,
    read_coverage_segments,
    read_dataset_coverage,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
    sync_dataset_coverage_from_segments,
)
from .trusted_receipt import SignedReceiptAuthority, TrustedReceiptIssuer

# build_synthetic_complete_receipt is intentionally NOT re-exported.

__all__ = [
    "__version__",
    "CollectionReceipt",
    "RequiredCoverageSegment",
    "SYNTHETIC_RECEIPT_MARKER",
    "SignedReceiptAuthority",
    "TrustedReceiptIssuer",
    "aggregate_status_from_segment_counts",
    "build_collection_receipt",
    "build_surgical_reagg_detail",
    "compute_raw_digest",
    "coverage_gaps",
    "coverage_summary",
    "evaluate_required_segments",
    "evaluate_segment",
    "honest_status_counts",
    "is_complete_eligible_receipt",
    "is_synthetic_receipt",
    "plan_required_segments",
    "read_collection_receipts",
    "read_coverage_segments",
    "read_dataset_coverage",
    "record_collection_receipt",
    "record_required_segments",
    "refresh_coverage_ledger",
    "sync_dataset_coverage_from_segments",
]
__version__ = "0.1.0"
