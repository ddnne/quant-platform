"""Storage layer — SQLite schema + writer for structured ingestion rows.

Every structured row carries the PIT columns:
``event_time`` / ``available_at`` / ``source`` / ``ingested_at``.
``available_at`` is mandatory (enforced in :mod:`storage.sqlite_store`).
"""

from .coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    SYNTHETIC_RECEIPT_MARKER,
    build_collection_receipt,
    compute_raw_digest,
    coverage_gaps,
    coverage_summary,
    evaluate_required_segments,
    evaluate_segment,
    is_complete_eligible_receipt,
    is_synthetic_receipt,
    plan_required_segments,
    read_collection_receipts,
    read_coverage_segments,
    read_dataset_coverage,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
)
from .trusted_receipt import TrustedReceiptIssuer, mint_ingestion_issuer

# build_synthetic_complete_receipt is intentionally NOT re-exported from the
# production storage package. Tests import it from storage.coverage_ledger
# or tests._fixtures.synthetic_receipts.

__all__ = [
    "__version__",
    "CollectionReceipt",
    "RequiredCoverageSegment",
    "SYNTHETIC_RECEIPT_MARKER",
    "TrustedReceiptIssuer",
    "build_collection_receipt",
    "compute_raw_digest",
    "coverage_gaps",
    "coverage_summary",
    "evaluate_required_segments",
    "evaluate_segment",
    "is_complete_eligible_receipt",
    "is_synthetic_receipt",
    "mint_ingestion_issuer",
    "plan_required_segments",
    "read_collection_receipts",
    "read_coverage_segments",
    "read_dataset_coverage",
    "record_collection_receipt",
    "record_required_segments",
    "refresh_coverage_ledger",
]
__version__ = "0.1.0"
