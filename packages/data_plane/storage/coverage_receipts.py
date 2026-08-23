"""Coverage receipt evidence builders: digests and collection receipts.

COMPLETE eligibility stays in ``coverage_ledger`` (policy).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from storage.coverage_ledger import CollectionReceipt, RequiredCoverageSegment


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_raw_digest(raw: bytes) -> str:
    """SHA-256 over the verbatim persisted source bytes (``sha256:`` + hex)."""
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError(
            "raw must be bytes (the verbatim persisted source bytes), "
            f"got {type(raw).__name__}"
        )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_collection_receipt(
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
) -> CollectionReceipt:
    """Build a receipt with a real SHA-256 over ``raw``; never fakes COMPLETE."""
    from storage.coverage_ledger import CollectionReceipt

    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError("receipt status must be SUCCESS or FAILED")
    structured = int(structured_row_count)
    raw_rows = int(raw_row_count) if raw_row_count is not None else structured
    digests: dict[str, Any] = {
        "raw": compute_raw_digest(raw),
        # Default is NOT trusted. COMPLETE needs verified Ed25519, not issuer strings.
        "eligibility": "RECOVERED_RAW_ONLY",
    }
    if extra_digests:
        digests.update(dict(extra_digests))
        # Strip bare TRUSTED claims that lack signature material.
        if digests.get("eligibility") == "TRUSTED_COLLECTION":
            has_sig = (
                isinstance(digests.get("signature"), str)
                and str(digests.get("signature")).startswith("ed25519:")
                and isinstance(digests.get("signed_body_b64"), str)
                and isinstance(digests.get("issuer_key_id"), str)
            )
            if not has_sig:
                digests["eligibility"] = "RECOVERED_RAW_ONLY"
                digests.setdefault(
                    "trust_note",
                    "TRUSTED_COLLECTION requires Ed25519 signature fields",
                )

    return CollectionReceipt(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=required.expected_scope,
        expected_items=required.expected_items,
        observed_items=int(observed_items),
        raw_page_count=1 if raw else 0,
        raw_row_count=raw_rows,
        structured_row_count=structured,
        pagination_exhausted=bool(pagination_exhausted),
        digests=digests,
        run_id=int(run_id),
        status=status,
        error=error,
        checked_at=checked_at or _now(),
    )


# Offline-fixture sentinel; never write to a production database.
SYNTHETIC_RECEIPT_MARKER = {
    "synthetic": True,
    "origin": "offline-test-fixture",
}


def build_synthetic_complete_receipt(
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    observed_items: int | None = None,
    checked_at: str | None = None,
) -> CollectionReceipt:
    """Offline-fixture COMPLETE-shaped receipt. Never write to production."""
    from storage.coverage_ledger import CollectionReceipt

    expected = required.expected_items
    if observed_items is None:
        observed_items = 0 if expected == 0 else 1
    digests: dict[str, Any] = {
        # Placeholder digest + TRUSTED so fixtures can exercise COMPLETE; production must not.
        "raw": "sha256:" + "0" * 64,
        "eligibility": "TRUSTED_COLLECTION",
        **SYNTHETIC_RECEIPT_MARKER,
    }
    items = int(observed_items)
    return CollectionReceipt(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=required.expected_scope,
        expected_items=expected,
        observed_items=items,
        raw_page_count=1,
        raw_row_count=items,
        structured_row_count=items,
        pagination_exhausted=True,
        digests=digests,
        run_id=int(run_id),
        status="SUCCESS",
        error=None,
        checked_at=checked_at or _now(),
    )


__all__ = [
    "SYNTHETIC_RECEIPT_MARKER",
    "build_collection_receipt",
    "build_synthetic_complete_receipt",
    "compute_raw_digest",
]
