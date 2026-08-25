"""JSDA governed receipts — persisted reconciliation required for SUCCESS.

Raw recovery (staging parse, FAILED unsigned evidence) is a separate path and
must not auto-COMPLETE. Empty-raw SUCCESS is forbidden.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from ingestion.runtime_authority import (
    GovernedReceiptService,
    open_governed_receipt_service,
)
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    record_collection_receipt,
)


def require_jsda_receipt_service(
    service: GovernedReceiptService | None = None,
) -> GovernedReceiptService:
    """Verify the persisted reconciliation capability before structured write."""
    if service is None:
        return open_governed_receipt_service()
    if not isinstance(service, GovernedReceiptService):
        raise TypeError("service must be GovernedReceiptService")
    return service


def record_governed_receipt(
    store,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    checked_at: str,
    status: str,
    error: Optional[str],
    pagination_exhausted: bool,
    digests: Mapping[str, Any],
    receipt_service: GovernedReceiptService | None = None,
    raw_artifact_paths: Sequence[Path | str] = (),
    raw_records: Sequence[Any] = (),
    structured_table: str = "",
    normalized_records: Sequence[Mapping[str, Any]] = (),
    observed_items: int | None = None,
    raw_page_count: int | None = None,
    raw_row_count: int | None = None,
    structured_row_count: int | None = None,
) -> None:
    """Record governed evidence; only remeasured SUCCESS obtains a signature.

    Loose counts remain available solely for FAILED/recovery audit receipts.
    Supplying them on SUCCESS is rejected so callers cannot smuggle asserted
    values into the signed closure.
    """
    stamped = dict(digests)
    if status == "SUCCESS" and error is None:
        if receipt_service is None:
            raise RuntimeError(
                "GovernedReceiptService is required before governed SUCCESS"
            )
        if any(value is not None for value in (
            observed_items,
            raw_page_count,
            raw_row_count,
            structured_row_count,
        )):
            raise TypeError("SUCCESS receipt counts must be measured, not supplied")
        require_jsda_receipt_service(receipt_service).record_persisted_success(
            store,
            required=required,
            run_id=run_id,
            raw_artifact_paths=raw_artifact_paths,
            raw_records=raw_records,
            structured_table=structured_table,
            normalized_records=normalized_records,
            pagination_exhausted=pagination_exhausted,
            discovery_exhausted=True,
            checked_at=checked_at,
            source_request={
                "source": required.source,
                "dataset": required.dataset,
                "segment_id": required.segment_id,
                "segment_start": required.segment_start,
                "segment_end": required.segment_end,
            },
            extra_evidence=stamped,
        )
        return
    else:
        for signature_field in (
            "signature",
            "signed_body_b64",
            "body_digest",
            "issuer_key_id",
            "issuer_id",
            "issuer_class",
        ):
            stamped.pop(signature_field, None)
        stamped["eligibility"] = "RECOVERED_RAW_ONLY"
        stamped.setdefault("origin", "failed-collection")
        receipt = CollectionReceipt(
            source=required.source,
            dataset=required.dataset,
            segment_id=required.segment_id,
            segment_start=required.segment_start,
            segment_end=required.segment_end,
            expected_scope=required.expected_scope,
            expected_items=required.expected_items,
            observed_items=int(observed_items or 0),
            raw_page_count=int(raw_page_count or len(tuple(raw_artifact_paths))),
            raw_row_count=int(raw_row_count or 0),
            structured_row_count=int(structured_row_count or 0),
            pagination_exhausted=bool(pagination_exhausted),
            digests=stamped,
            run_id=run_id,
            status=status,
            error=error,
            checked_at=checked_at,
        )
    record_collection_receipt(store._conn, receipt)  # noqa: SLF001
    store._conn.commit()  # noqa: SLF001


__all__ = [
    "record_governed_receipt",
    "require_jsda_receipt_service",
]
