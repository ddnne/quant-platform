"""JQ collection receipts through the governed reconciliation service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ingestion.runtime_authority import (
    _GovernedCollectionContext,
    _GovernedReceiptService,
)
from storage.coverage_ledger import CollectionReceipt, RequiredCoverageSegment
from storage.sqlite_store import SqliteStore


def require_governed_receipt_service(
    service: _GovernedReceiptService | None = None,
) -> _GovernedReceiptService:
    """Open/verify the reconciliation capability before fact mutation.

    The returned object contains no receipt private key. Production issuance
    remains unavailable until the separate evidence authority is provisioned.
    """
    if service is None:
        raise TypeError(
            "GovernedReceiptService is required; implicit issue is removed"
        )
    if not isinstance(service, _GovernedReceiptService):
        raise TypeError("service must be the governed ingestion receipt capability")
    return service


def emit_segment_receipt(
    store: SqliteStore,
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    persisted_collection,
    service: _GovernedReceiptService,
    collection_context: _GovernedCollectionContext,
    source_request: Mapping[str, Any] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
) -> CollectionReceipt:
    """Re-read persisted raw/facts and request one signed SUCCESS closure."""
    service = require_governed_receipt_service(service)
    return service.record_persisted_success(
        store,
        required=required,
        run_id=run_id,
        jquants_collection=persisted_collection,
        collection_context=collection_context,
        source_request=source_request,
        extra_evidence=extra_evidence,
    )


__all__ = ["emit_segment_receipt", "require_governed_receipt_service"]
