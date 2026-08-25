"""JQ collection receipts through the governed reconciliation service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ingestion.runtime_authority import (
    GovernedReceiptService,
    open_governed_receipt_service,
)
from storage.coverage_ledger import CollectionReceipt, RequiredCoverageSegment
from storage.sqlite_store import SqliteStore


def require_governed_receipt_service(
    service: GovernedReceiptService | None = None,
    *,
    open_if_missing: bool = True,
) -> GovernedReceiptService:
    """Open/verify the reconciliation capability before fact mutation.

    The returned object never exposes its private-key issuer.
    """
    if service is None:
        if not open_if_missing:
            raise TypeError(
                "GovernedReceiptService is required; implicit issue is removed"
            )
        return open_governed_receipt_service()
    if not isinstance(service, GovernedReceiptService):
        raise TypeError("service must be GovernedReceiptService")
    return service


def emit_segment_receipt(
    store: SqliteStore,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    raw_artifact_paths: Sequence[Path | str],
    raw_records: Sequence[Any],
    structured_table: str,
    normalized_records: Sequence[Mapping[str, Any]],
    service: GovernedReceiptService,
    pagination_exhausted: bool = True,
    discovery_exhausted: bool | None = None,
    checked_at: str | None = None,
    source_request: Mapping[str, Any] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
) -> CollectionReceipt:
    """Re-read persisted raw/facts and record one signed SUCCESS closure."""
    service = require_governed_receipt_service(
        service, open_if_missing=False
    )
    return service.record_persisted_success(
        store,
        required=required,
        run_id=run_id,
        raw_artifact_paths=raw_artifact_paths,
        raw_records=raw_records,
        structured_table=structured_table,
        normalized_records=normalized_records,
        pagination_exhausted=pagination_exhausted,
        discovery_exhausted=discovery_exhausted,
        checked_at=checked_at,
        source_request=source_request,
        extra_evidence=extra_evidence,
    )


__all__ = ["emit_segment_receipt", "require_governed_receipt_service"]
