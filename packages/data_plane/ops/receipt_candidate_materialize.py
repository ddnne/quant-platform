"""Data-plane owner for exact signed receipt-candidate materialization.

Container owns transport and job lifecycle. This module owns the SQLite
transaction, exact CURRENT+REVISION apply, raw/calendar binding, and
full-segment evidence close. It does not mint COMPLETE or READY.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ops.receipt_product import (
    PRODUCT_ARTIFACT_FIELDS,
    _iter_canonical_artifact_rows,
    catalog_owned_product_row_digests,
    measure_owned_product_artifact_body,
    verify_full_segment_product_materialization,
)
from storage.coverage_ledger_io import record_collection_receipt
from storage.receipt_crypto import PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS
from storage.sqlite_store import SqliteStore
from storage.verified_receipt import (
    collection_receipt_from_signed_envelope,
    require_verified_collection_closure,
)

APPLY_BATCH_ROWS = 256
_COLLECTION_KEYS = frozenset(
    {
        "schema_version",
        "capture_mode",
        "initial_request",
        "official_calendar_evidence",
        "pages",
        "collection_digest",
    }
)
_CALENDAR_EVIDENCE_KEYS = frozenset(
    {
        "raw_path",
        "source_path",
        "raw_size",
        "raw_digest",
        "calendar_query_digest",
        "business_dates_digest",
        "binding_digest",
        "business_dates",
    }
)


class ReceiptCandidateMaterializeError(ValueError):
    """Signed candidate evidence does not close."""


def _sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _ensure_authority_operation_id(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(ingestion_run_log)")
    }
    if "authority_operation_id" not in columns:
        conn.execute(
            "ALTER TABLE ingestion_run_log ADD COLUMN authority_operation_id TEXT"
        )


def persist_official_calendar_raw(
    conn: sqlite3.Connection, *, body: bytes, expected_digest: str
) -> None:
    """Persist one calendar BLOB only after the signed digest matches."""
    if type(body) is not bytes or not body:
        raise ReceiptCandidateMaterializeError(
            "official calendar raw body must be exact bytes"
        )
    digest = _sha256_bytes(body)
    if digest != expected_digest:
        raise ReceiptCandidateMaterializeError(
            "official calendar raw body digest does not match the signed closure"
        )
    conn.execute(
        "INSERT INTO official_calendar_raw (raw_body_digest, body) VALUES (?, ?) "
        "ON CONFLICT(raw_body_digest) DO NOTHING",
        (digest, body),
    )
    stored = conn.execute(
        "SELECT body FROM official_calendar_raw WHERE raw_body_digest=?",
        (digest,),
    ).fetchone()
    if stored is None or bytes(stored[0]) != body:
        raise ReceiptCandidateMaterializeError(
            "official calendar raw body was not retained"
        )


def _parse_collection_document(raw_bytes: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptCandidateMaterializeError(
            "raw collection manifest is not JSON"
        ) from exc
    if type(document) is not dict or set(document) != _COLLECTION_KEYS:
        raise ReceiptCandidateMaterializeError(
            "raw collection manifest fields are not closed"
        )
    return document


def _bind_raw_collection(
    closure: Any, *, raw_bytes: bytes, extras: Mapping[str, Any]
) -> dict[str, Any]:
    file_digest = extras.get("acquisition_collection_manifest_file_digest")
    collection_digest = extras.get("acquisition_collection_digest")
    if _sha256_bytes(raw_bytes) != file_digest:
        raise ReceiptCandidateMaterializeError(
            "raw collection file digest does not match the signed closure"
        )
    document = _parse_collection_document(raw_bytes)
    if document.get("collection_digest") != collection_digest:
        raise ReceiptCandidateMaterializeError(
            "raw collection digest does not match the signed closure"
        )
    pages = document.get("pages")
    if type(pages) is not list or not pages:
        raise ReceiptCandidateMaterializeError("raw collection pages are missing")
    return document


def configure_receipt_candidate_limits(
    store: SqliteStore, *, max_database_bytes: int
) -> None:
    """Pin sqlite page budget and required run-log columns before segment DML."""
    if type(max_database_bytes) is not int or max_database_bytes < 1:
        raise ReceiptCandidateMaterializeError("max_database_bytes is invalid")
    conn = store._conn  # noqa: SLF001
    _ensure_authority_operation_id(conn)
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    if page_size < 1:
        raise ReceiptCandidateMaterializeError("sqlite page size is invalid")
    conn.execute(f"PRAGMA max_page_count={max(1, max_database_bytes // page_size)}")


def commit_receipt_candidate(store: SqliteStore) -> None:
    store._conn.commit()  # noqa: SLF001


def rollback_receipt_candidate(store: SqliteStore) -> None:
    store._conn.rollback()  # noqa: SLF001


def _guard_database_bytes(store: SqliteStore, *, max_database_bytes: int) -> None:
    path = Path(store.path)
    used = sum(
        candidate.stat().st_size if candidate.exists() else 0
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
    )
    if used > max_database_bytes:
        raise ReceiptCandidateMaterializeError(
            "receipt candidate sqlite exceeds the builder cap"
        )


def _bind_descriptor_identities(closure: Any, descriptor: Mapping[str, Any]) -> str:
    product_meta = descriptor.get("product")
    if type(product_meta) is not dict:
        raise ReceiptCandidateMaterializeError("product descriptor is missing")
    extras = closure.extra_digests
    operation_id = descriptor.get("operation_id")
    if type(operation_id) is not str or not operation_id:
        raise ReceiptCandidateMaterializeError("operation_id is missing")
    expected = {
        "source": closure.source,
        "dataset": closure.dataset,
        "segment_id": closure.segment_id,
        "receipt_digest": closure.receipt_digest,
        "artifact_key": closure.artifact_key,
        "artifact_digest": closure.structured_digest,
        "byte_count": closure.artifact_byte_count,
        "row_count": closure.structured_row_count,
        "manifest_key": closure.manifest_key,
        "manifest_digest": extras["product_manifest_digest"],
        "raw_manifest_key": closure.raw_manifest_key,
        "raw_manifest_digest": closure.raw_manifest_digest,
        "raw_page_count": closure.raw_page_count,
        "raw_row_count": closure.raw_row_count,
        "raw_bytes": closure.raw_byte_count,
    }
    observed = {
        "source": descriptor.get("source"),
        "dataset": descriptor.get("dataset"),
        "segment_id": descriptor.get("segment_id"),
        "receipt_digest": descriptor.get("receipt_digest"),
        "artifact_key": product_meta.get("artifact_key"),
        "artifact_digest": product_meta.get("artifact_digest"),
        "byte_count": product_meta.get("byte_count"),
        "row_count": product_meta.get("row_count"),
        "manifest_key": product_meta.get("manifest_key"),
        "manifest_digest": product_meta.get("manifest_digest"),
        "raw_manifest_key": product_meta.get("raw_manifest_key"),
        "raw_manifest_digest": product_meta.get("raw_manifest_digest"),
        "raw_page_count": product_meta.get("raw_page_count"),
        "raw_row_count": product_meta.get("raw_row_count"),
        "raw_bytes": product_meta.get("raw_bytes"),
    }
    if extras.get("product_artifact_digest") not in {
        None,
        closure.structured_digest,
    }:
        raise ReceiptCandidateMaterializeError(
            "product artifact digest extra does not match the signed closure"
        )
    mismatched = [name for name, value in expected.items() if observed.get(name) != value]
    if mismatched:
        raise ReceiptCandidateMaterializeError(
            "descriptor identities do not match the signed closure: "
            + ",".join(mismatched)
        )
    return operation_id


def _apply_product_file(
    store: SqliteStore,
    product_path: Path,
    *,
    max_database_bytes: int,
) -> None:
    batch: list[dict[str, str]] = []
    with product_path.open("rb") as handle:
        for _raw_line, row in _iter_canonical_artifact_rows(handle):
            batch.append({field: row[field] for field in PRODUCT_ARTIFACT_FIELDS})
            if len(batch) >= APPLY_BATCH_ROWS:
                store.apply_exact_product_mirror(
                    "jquants_records", batch, commit=False
                )
                batch.clear()
                _guard_database_bytes(store, max_database_bytes=max_database_bytes)
        if batch:
            store.apply_exact_product_mirror("jquants_records", batch, commit=False)
            _guard_database_bytes(store, max_database_bytes=max_database_bytes)


def _store_artifact_text(
    conn: sqlite3.Connection,
    *,
    operation_id: str,
    product_path: Path,
    byte_count: int,
) -> None:
    with product_path.open("rb") as handle:
        payload = handle.read(byte_count + 1)
    if len(payload) != byte_count:
        raise ReceiptCandidateMaterializeError(
            "product artifact spool size does not match the signed byte count"
        )
    conn.execute(
        "UPDATE receipt_product_materializations SET artifact_body=? "
        "WHERE operation_id=?",
        (payload.decode("utf-8"), operation_id),
    )


def materialize_receipt_segment(
    store: SqliteStore,
    *,
    environment: str,
    descriptor: Mapping[str, Any],
    product_path: Path,
    raw_path: Path,
    calendar_path: Path | None,
    max_database_bytes: int,
) -> dict[str, Any]:
    """Apply one current-coverage described segment as exact signed evidence.

    Describe metadata freezes current coverage references only. Historic
    receipt generations are not reconstructed. This path does not mint READY
    or GO.
    """
    if environment not in PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS:
        raise ReceiptCandidateMaterializeError("environment is not pinned")
    if type(descriptor) is not dict:
        raise ReceiptCandidateMaterializeError("segment descriptor must be an object")
    conn = store._conn  # noqa: SLF001 — data-plane transaction owner
    try:
        receipt = collection_receipt_from_signed_envelope(
            descriptor.get("signed_receipt")
        )
        closure = require_verified_collection_closure(
            receipt,
            expected_environment=environment,
            expected_authority_instance_digest=(
                PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[environment]
            ),
        )
        operation_id = _bind_descriptor_identities(closure, descriptor)
        extras = closure.extra_digests
        raw_bytes = raw_path.read_bytes()
        document = _bind_raw_collection(closure, raw_bytes=raw_bytes, extras=extras)
        product_size = product_path.stat().st_size
        if product_size != closure.artifact_byte_count:
            raise ReceiptCandidateMaterializeError(
                "product spool size does not match the signed artifact byte count"
            )
        if product_size > max_database_bytes:
            raise ReceiptCandidateMaterializeError(
                "receipt candidate sqlite exceeds the builder cap"
            )
        calendar_digest = extras.get("official_calendar_raw_body_digest")
        calendar_body: bytes | None = None
        if descriptor.get("dataset") == "equities_master":
            if calendar_path is None or type(calendar_digest) is not str:
                raise ReceiptCandidateMaterializeError(
                    "equities_master requires official calendar raw bytes"
                )
            evidence = document.get("official_calendar_evidence")
            if type(evidence) is not dict or set(evidence) != _CALENDAR_EVIDENCE_KEYS:
                raise ReceiptCandidateMaterializeError(
                    "official calendar evidence fields are not closed"
                )
            calendar_body = calendar_path.read_bytes()
            if (
                evidence.get("raw_digest") != calendar_digest
                or extras.get("official_calendar_query_digest")
                != evidence.get("calendar_query_digest")
                or extras.get("official_business_dates_digest")
                != evidence.get("business_dates_digest")
                or extras.get("official_calendar_binding_digest")
                != evidence.get("binding_digest")
            ):
                raise ReceiptCandidateMaterializeError(
                    "official calendar evidence does not match the signed closure"
                )
        elif calendar_path is not None:
            raise ReceiptCandidateMaterializeError("official calendar is master-only")
        _apply_product_file(
            store,
            product_path,
            max_database_bytes=max_database_bytes,
        )
        if calendar_body is not None:
            persist_official_calendar_raw(
                conn, body=calendar_body, expected_digest=str(calendar_digest)
            )
        record_collection_receipt(conn, receipt)
        conn.execute(
            "INSERT INTO ingestion_run_log "
            "(id, ran_at, source, runtime, status, detail, authority_operation_id) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "ran_at=excluded.ran_at, source=excluded.source, runtime=excluded.runtime, "
            "status=excluded.status, detail=excluded.detail, "
            "authority_operation_id=excluded.authority_operation_id",
            (
                closure.run_id,
                receipt.checked_at,
                closure.source,
                "receipt-evidence-authority",
                "SUCCESS",
                "{}",
                operation_id,
            ),
        )
        conn.execute(
            "INSERT INTO raw_retention_manifests "
            "(dataset, run_id, manifest_key, page_count, row_count, raw_bytes, "
            "data_digest, completeness, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(dataset, run_id) DO UPDATE SET "
            "manifest_key=excluded.manifest_key, page_count=excluded.page_count, "
            "row_count=excluded.row_count, raw_bytes=excluded.raw_bytes, "
            "data_digest=excluded.data_digest, completeness=excluded.completeness, "
            "created_at=excluded.created_at",
            (
                closure.dataset,
                closure.run_id,
                closure.raw_manifest_key,
                len(document["pages"]),
                closure.raw_row_count,
                closure.raw_byte_count,
                closure.raw_manifest_digest,
                "COMPLETE",
                receipt.checked_at,
            ),
        )
        conn.execute(
            "INSERT INTO receipt_product_materializations ("
            "operation_id, run_id, source, dataset, segment_id, artifact_key, "
            "artifact_digest, artifact_body, row_count, byte_count, manifest_key, "
            "manifest_digest, raw_manifest_key, raw_manifest_digest, raw_page_count, "
            "raw_row_count, raw_bytes, committed_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(operation_id) DO UPDATE SET "
            "run_id=excluded.run_id, source=excluded.source, dataset=excluded.dataset, "
            "segment_id=excluded.segment_id, artifact_key=excluded.artifact_key, "
            "artifact_digest=excluded.artifact_digest, artifact_body=excluded.artifact_body, "
            "row_count=excluded.row_count, byte_count=excluded.byte_count, "
            "manifest_key=excluded.manifest_key, manifest_digest=excluded.manifest_digest, "
            "raw_manifest_key=excluded.raw_manifest_key, "
            "raw_manifest_digest=excluded.raw_manifest_digest, "
            "raw_page_count=excluded.raw_page_count, raw_row_count=excluded.raw_row_count, "
            "raw_bytes=excluded.raw_bytes, committed_at=excluded.committed_at",
            (
                operation_id,
                closure.run_id,
                closure.source,
                closure.dataset,
                closure.segment_id,
                closure.artifact_key,
                closure.structured_digest,
                "",
                closure.structured_row_count,
                closure.artifact_byte_count,
                closure.manifest_key,
                extras["product_manifest_digest"],
                closure.raw_manifest_key,
                closure.raw_manifest_digest,
                closure.raw_page_count,
                closure.raw_row_count,
                closure.raw_byte_count,
                descriptor.get("product", {}).get("committed_at"),
            ),
        )
        _store_artifact_text(
            conn,
            operation_id=operation_id,
            product_path=product_path,
            byte_count=closure.artifact_byte_count,
        )
        owned = catalog_owned_product_row_digests(
            conn,
            source=closure.source,
            dataset=closure.dataset,
            segment_start=closure.segment_start,
            segment_end=closure.segment_end,
            observed_through=closure.checked_at,
            tables=("jquants_records", "jquants_records_revisions"),
        )
        with product_path.open("rb") as artifact:
            observed_count, observed_digest, observed_bytes, _owned_rows = (
                measure_owned_product_artifact_body(
                    artifact, owned_digests=owned
                )
            )
        product_row = conn.execute(
            "SELECT operation_id,run_id,source,dataset,segment_id,"
            "artifact_key,artifact_digest,row_count,"
            "byte_count,manifest_key,manifest_digest,raw_manifest_key,"
            "raw_manifest_digest,raw_page_count,raw_row_count,"
            "raw_bytes,committed_at FROM receipt_product_materializations "
            "WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        run_row = conn.execute(
            "SELECT id,source,runtime,status,authority_operation_id "
            "FROM ingestion_run_log WHERE id=?",
            (closure.run_id,),
        ).fetchone()
        raw_row = conn.execute(
            "SELECT dataset,run_id,manifest_key,page_count,row_count,"
            "raw_bytes,data_digest FROM raw_retention_manifests "
            "WHERE dataset=? AND run_id=?",
            (closure.dataset, closure.run_id),
        ).fetchone()
        with product_path.open("rb") as artifact:
            verify_full_segment_product_materialization(
                closure,
                product=dict(product_row),
                run=dict(run_row),
                raw_manifest=dict(raw_row),
                observed_count=observed_count,
                observed_digest=observed_digest,
                observed_bytes=observed_bytes,
                artifact=artifact,
            )
        _guard_database_bytes(store, max_database_bytes=max_database_bytes)
        return {
            "dataset": closure.dataset,
            "segment_id": closure.segment_id,
            "run_id": closure.run_id,
            "receipt_digest": closure.receipt_digest,
            "row_count": observed_count,
            "byte_count": observed_bytes,
        }
    except Exception:
        conn.rollback()
        raise
