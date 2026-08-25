"""Trusted ingestion runtime — sole holder of receipt signing keys.

Production callers receive a :class:`GovernedReceiptService`, never the
private-key issuer.  The service commits the structured transaction, rereads
the exact canonical natural keys, rereads immutable raw artifacts, measures
both sides, and only then gives opaque evidence to ``TrustedReceiptIssuer``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.receipt_crypto import canonical_evidence_digest, partition_extra_digests
from storage.trusted_receipt import (
    ReconciledCollectionEvidence,
    SignedReceiptAuthority,
    _make_reconciled_collection_evidence,
    _open_signed_receipt_authority,
)

if TYPE_CHECKING:
    from storage.sqlite_store import SqliteStore

# Run states for governed ingestion (Phase 6.2.3 §2).
RUN_ACQUIRED = "ACQUIRED"
RUN_RAW_STORED = "RAW_STORED"
RUN_STRUCTURED_COMMITTED = "STRUCTURED_COMMITTED"
RUN_RECEIPT_VERIFIED = "RECEIPT_VERIFIED"
RUN_COVERAGE_COMPLETE = "COVERAGE_COMPLETE"
RUN_PARTIAL = "PARTIAL"
RUN_FAILED = "FAILED"


_SERVICE_SEAL = object()


def _open_ingestion_signing_authority(
    *,
    pem: bytes | str | None = None,
    path: Path | None = None,
    key_id: str | None = None,
) -> SignedReceiptAuthority:
    """Private key capability; never returned to ingestion callers."""
    return _open_signed_receipt_authority(pem=pem, path=path, key_id=key_id)


@dataclass(frozen=True)
class GovernedReceiptService:
    """Positive capability for DB/raw reconciliation and receipt persistence."""

    _seal: object
    _issuer: SignedReceiptAuthority

    def __post_init__(self) -> None:
        if self._seal is not _SERVICE_SEAL:
            raise TypeError("GovernedReceiptService must be opened by ingestion runtime")

    def record_persisted_success(
        self,
        store: SqliteStore,
        *,
        required: RequiredCoverageSegment,
        run_id: int,
        raw_artifact_paths: Sequence[Path | str],
        raw_records: Sequence[Any],
        structured_table: str,
        normalized_records: Sequence[Mapping[str, Any]],
        pagination_exhausted: bool,
        discovery_exhausted: bool | None = None,
        checked_at: str | None = None,
        source_request: Mapping[str, Any] | None = None,
        extra_evidence: Mapping[str, Any] | None = None,
    ) -> CollectionReceipt:
        """Commit, independently remeasure persisted state, sign, and record.

        Counts, digests, and exhaustion claims are never parameters.  Raw
        bytes come from read-only persisted artifacts and structured payloads
        come from an exact natural-key re-read after the fact transaction has
        committed.  A signing or reconciliation failure leaves facts present
        but cannot create COMPLETE-eligible evidence.
        """
        from storage.sqlite_store import SqliteStore

        if not isinstance(store, SqliteStore):
            raise TypeError("governed receipt service requires SqliteStore")
        if not isinstance(required, RequiredCoverageSegment):
            raise TypeError("required must be RequiredCoverageSegment")

        candidates = tuple(Path(path).expanduser() for path in raw_artifact_paths)
        if not candidates:
            raise ValueError("persisted raw artifact path is required")
        if any(path.is_symlink() for path in candidates):
            raise ValueError("raw evidence symlinks are not trusted")
        paths = tuple(path.resolve() for path in candidates)
        for path in paths:
            if not path.is_file():
                raise ValueError(f"raw evidence must be a regular persisted file: {path}")
            if path.stat().st_mode & 0o222:
                raise ValueError(f"raw evidence artifact is writable: {path}")

        # The fact mutation becomes externally visible before it can be
        # claimed. A subsequent failure is PARTIAL evidence, never COMPLETE.
        store._conn.commit()  # noqa: SLF001 - service owns this transaction boundary
        raw_pages = tuple(path.read_bytes() for path in paths)
        structured_rows = store.fetch_exact_by_natural_keys(
            structured_table, normalized_records
        )
        for row in structured_rows:
            if str(row.get("source") or "") != required.source:
                raise ValueError("structured source differs from required segment")
            if "dataset" in row and str(row.get("dataset") or "") != required.dataset:
                raise ValueError("structured dataset differs from required segment")
            if "segment_id" in row and str(row.get("segment_id") or "") != required.segment_id:
                raise ValueError("structured row escaped the exact required segment")

        evidence = reconcile_collection_evidence(
            required=required,
            run_id=run_id,
            raw_pages=raw_pages,
            raw_records=raw_records,
            structured_records=structured_rows,
            pagination_exhausted=pagination_exhausted,
            discovery_exhausted=discovery_exhausted,
            checked_at=checked_at,
            source_request=source_request,
            extra_evidence=extra_evidence,
        )
        receipt = self._issuer.issue(evidence)
        try:
            record_collection_receipt(store._conn, receipt)  # noqa: SLF001
            store._conn.commit()  # noqa: SLF001
        except Exception:
            store._conn.rollback()  # noqa: SLF001
            raise
        return receipt


def open_governed_receipt_service(
    *,
    pem: bytes | str | None = None,
    path: Path | None = None,
    key_id: str | None = None,
) -> GovernedReceiptService:
    """Open the only production capability that can persist signed SUCCESS."""
    return GovernedReceiptService(
        _seal=_SERVICE_SEAL,
        _issuer=_open_ingestion_signing_authority(
            pem=pem,
            path=path,
            key_id=key_id,
        ),
    )


def _digest(payload: Any) -> str:
    return canonical_evidence_digest(payload)


def _json_records_from_pages(raw_pages: Sequence[bytes]) -> tuple[Any, ...] | None:
    """Return records decoded from JSON artifacts, or ``None`` for binary raw.

    Returning the records rather than only a count prevents a caller from
    substituting same-sized parsed content while asking the runtime to sign
    the genuine raw artifact digest.
    """
    measured: list[Any] = []
    saw_json = False
    for raw in raw_pages:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            continue
        saw_json = True
        if isinstance(payload, list):
            measured.extend(payload)
            continue
        if isinstance(payload, dict):
            rows = next(
                (
                    payload.get(key)
                    for key in ("data", "rows", "results", "records")
                    if isinstance(payload.get(key), list)
                ),
                None,
            )
            measured.extend(rows or ())
    return tuple(measured) if saw_json else None


def reconcile_collection_evidence(
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    raw_pages: Sequence[bytes],
    raw_records: Sequence[Any],
    structured_records: Sequence[Mapping[str, Any]],
    pagination_exhausted: bool,
    discovery_exhausted: bool | None = None,
    checked_at: str | None = None,
    source_request: Mapping[str, Any] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
) -> ReconciledCollectionEvidence:
    """Measure artifacts and create the only evidence accepted by the signer.

    Counts and digests are derived here from concrete raw pages and normalized
    records.  Callers cannot supply either.  A JSON envelope is also counted
    independently and must agree with ``raw_records``.  Binary source parsers
    supply their parsed record sequence as the measured raw evidence.
    """
    if not isinstance(required, RequiredCoverageSegment):
        raise TypeError("required must be RequiredCoverageSegment")
    pages = tuple(bytes(page) for page in raw_pages)
    if not pages or any(not page for page in pages):
        raise ValueError("reconciled SUCCESS requires non-empty raw pages")
    raw_rows = tuple(raw_records)
    structured_rows = tuple(dict(row) for row in structured_records)
    measured_json = _json_records_from_pages(pages)
    if measured_json is not None and _digest(list(measured_json)) != _digest(
        list(raw_rows)
    ):
        raise ValueError(
            "raw_records do not match content measured from the raw JSON envelope"
        )

    extras = partition_extra_digests(extra_evidence)
    expected_empty = bool(extras.get("EXPECTED_EMPTY_WITH_EVIDENCE"))
    if not raw_rows and not expected_empty:
        raise ValueError(
            "zero-row SUCCESS requires reconciled EXPECTED_EMPTY_WITH_EVIDENCE"
        )
    exhausted = bool(pagination_exhausted)
    discovered = exhausted if discovery_exhausted is None else bool(discovery_exhausted)
    if not exhausted or not discovered:
        raise ValueError("non-exhausted evidence is recovery-only and cannot be signed")

    page_manifest = [
        {"index": index, "digest": _digest(page), "size": len(page)}
        for index, page in enumerate(pages)
    ]
    raw_digest = page_manifest[0]["digest"] if len(page_manifest) == 1 else _digest(
        {"pages": page_manifest}
    )
    raw_manifest_digest = _digest({"pages": page_manifest})
    structured_digest = _digest(list(structured_rows))
    policy = coverage_contract_for(required.dataset)
    if (
        policy.structured_reconciliation_required
        and len(raw_rows) != len(structured_rows)
    ):
        raise ValueError(
            "raw and structured records do not reconcile under dataset policy"
        )
    scope = {
        "coverage_policy_version": policy.policy_version,
        "source": required.source,
        "dataset": required.dataset,
        "segment_id": required.segment_id,
        "segment_start": required.segment_start,
        "segment_end": required.segment_end,
        "expected_scope": dict(required.expected_scope),
        "expected_items": required.expected_items,
    }
    scope_digest = _digest(scope)
    request = dict(source_request or scope)
    source_request_digest = _digest(request)

    unit = str(required.expected_scope.get("expected_item_unit") or "")
    if unit in {
        "source_query",
        "official_archive_file",
        "official_archive_index",
        "official_full_timeseries_file",
        "official_correction_artifact",
    }:
        observed_items = int(bool(raw_rows))
    else:
        observed_items = len(raw_rows)
    checked = checked_at or datetime.now(timezone.utc).isoformat()
    observation = {
        **scope,
        "observed_items": observed_items,
        "raw_page_count": len(page_manifest),
        "raw_count": len(raw_rows),
        "structured_count": len(structured_rows),
        "status": "SUCCESS",
        "error": None,
        "pagination_exhausted": exhausted,
        "discovery_exhausted": discovered,
        "source_request_digest": source_request_digest,
        "raw_manifest_digest": raw_manifest_digest,
        "raw_digest": raw_digest,
        "structured_digest": structured_digest,
        "structured_generation": int(run_id),
        "scope_digest": scope_digest,
        "run_id": int(run_id),
        "checked_at": checked,
        "extra_digests": extras,
    }
    observation_digest = _digest(observation)
    return _make_reconciled_collection_evidence(
        required=required,
        coverage_policy_version=policy.policy_version,
        run_id=run_id,
        observed_items=observed_items,
        raw_page_count=len(page_manifest),
        raw_row_count=len(raw_rows),
        structured_row_count=len(structured_rows),
        pagination_exhausted=exhausted,
        discovery_exhausted=discovered,
        source_request_digest=source_request_digest,
        raw_manifest_digest=raw_manifest_digest,
        raw_digest=raw_digest,
        structured_digest=structured_digest,
        structured_generation=run_id,
        scope_digest=scope_digest,
        observation_digest=observation_digest,
        checked_at=checked,
        extra_digests=extras,
    )


__all__ = [
    "RUN_ACQUIRED",
    "RUN_COVERAGE_COMPLETE",
    "RUN_FAILED",
    "RUN_PARTIAL",
    "RUN_RAW_STORED",
    "RUN_RECEIPT_VERIFIED",
    "RUN_STRUCTURED_COMMITTED",
    "GovernedReceiptService",
    "open_governed_receipt_service",
    "reconcile_collection_evidence",
]
