"""Storage layer — SQLite schema + writer for structured ingestion rows.

Every structured row carries the PIT columns:
``event_time`` / ``available_at`` / ``source`` / ``ingested_at``.
``available_at`` is mandatory (enforced in :mod:`storage.sqlite_store`).
"""

from .coverage_ledger import (
    CanonicalCoverageSegmentIdentity,
    CollectionReceipt,
    CoverageInventoryAuthorityUnavailable,
    ExactCoverageCompleteVerification,
    ExactCoverageInventoryComparison,
    RequiredCoverageSegment,
    SYNTHETIC_RECEIPT_MARKER,
    aggregate_status_from_segment_counts,
    build_collection_receipt,
    build_surgical_reagg_detail,
    compute_raw_digest,
    compare_exact_coverage_inventory,
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
    verify_exact_coverage_complete,
)
from .coverage_transition import (
    CoverageTransitionAlreadyConsumed,
    CoverageTransitionAuthorityPending,
    CoverageTransitionError,
    apply_signed_coverage_transition,
    build_coverage_transition_request,
    coverage_transition_availability,
)
from .verified_receipt import (
    VerifiedCollectionClosure,
    require_verified_collection_closure,
)

# build_synthetic_complete_receipt is intentionally NOT re-exported.

__all__ = [
    "__version__",
    "CanonicalCoverageSegmentIdentity",
    "CollectionReceipt",
    "CoverageInventoryAuthorityUnavailable",
    "CoverageTransitionAlreadyConsumed",
    "CoverageTransitionAuthorityPending",
    "CoverageTransitionError",
    "ExactCoverageCompleteVerification",
    "ExactCoverageInventoryComparison",
    "RequiredCoverageSegment",
    "SYNTHETIC_RECEIPT_MARKER",
    "VerifiedCollectionClosure",
    "aggregate_status_from_segment_counts",
    "apply_signed_coverage_transition",
    "build_collection_receipt",
    "build_coverage_transition_request",
    "build_surgical_reagg_detail",
    "compute_raw_digest",
    "compare_exact_coverage_inventory",
    "coverage_gaps",
    "coverage_summary",
    "coverage_transition_availability",
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
    "require_verified_collection_closure",
    "refresh_coverage_ledger",
    "sync_dataset_coverage_from_segments",
    "verify_exact_coverage_complete",
]
__version__ = "0.1.0"
