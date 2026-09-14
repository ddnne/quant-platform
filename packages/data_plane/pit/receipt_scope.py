"""Detached collection-receipt rows for READY and receipt-candidate proof.

Owns the SELECT/PRAGMA text. Callers still pass the transactional connection;
publication policy stays in paper_runtime.
"""

from __future__ import annotations

import sqlite3
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from pit.errors import PitError


_CATALOG_REQUIRED = {
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
    "raw_payload",
}
_RECEIPT_REQUIRED = {
    "source",
    "dataset",
    "segment_id",
    "segment_start",
    "segment_end",
    "expected_scope",
    "expected_items",
    "observed_items",
    "raw_page_count",
    "raw_row_count",
    "structured_row_count",
    "pagination_exhausted",
    "digests_json",
    "run_id",
    "status",
    "error",
    "checked_at",
}
_PRODUCT_REQUIRED = {
    "operation_id",
    "run_id",
    "source",
    "dataset",
    "segment_id",
    "artifact_key",
    "artifact_digest",
    "artifact_body",
    "row_count",
    "byte_count",
    "manifest_key",
    "manifest_digest",
    "raw_manifest_key",
    "raw_manifest_digest",
    "raw_page_count",
    "raw_row_count",
    "raw_bytes",
    "committed_at",
}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _detached_row(row: Any) -> Mapping[str, Any]:
    return MappingProxyType(dict(row))


def load_collection_receipt_scope(
    conn: sqlite3.Connection,
    datasets: Sequence[str],
) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
]:
    columns = _table_columns(conn, "jquants_records")
    if not _CATALOG_REQUIRED <= columns:
        raise PitError(
            "PIT dependency scope requires canonical jquants_records columns"
        )
    revision_columns = _table_columns(conn, "jquants_records_revisions")
    if not _CATALOG_REQUIRED <= revision_columns:
        raise PitError(
            "PIT dependency scope requires canonical "
            "jquants_records_revisions columns"
        )
    placeholders = ",".join("?" for _ in datasets)
    if not _RECEIPT_REQUIRED <= _table_columns(conn, "collection_receipts"):
        raise PitError(
            "PIT dependency scope requires signed collection receipt columns"
        )
    if not _PRODUCT_REQUIRED <= _table_columns(
        conn, "receipt_product_materializations"
    ):
        raise PitError(
            "PIT dependency scope requires receipt product materializations"
        )
    if "authority_operation_id" not in _table_columns(conn, "ingestion_run_log"):
        raise PitError(
            "PIT dependency scope requires authority-bound ingestion runs"
        )
    collection_receipts = tuple(
        _detached_row(row)
        for row in conn.execute(
            "SELECT * FROM collection_receipts WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) ORDER BY checked_at,run_id",
            tuple(datasets),
        )
    )
    run_ids = tuple(
        dict.fromkeys(
            int(row["run_id"])
            for row in collection_receipts
            if row.get("run_id") is not None
        )
    )
    if not run_ids:
        return collection_receipts, (), (), ()
    run_placeholders = ",".join("?" for _ in run_ids)
    bound = tuple(datasets) + run_ids
    product_materializations = tuple(
        _detached_row(row)
        for row in conn.execute(
            "SELECT operation_id,run_id,source,dataset,segment_id,"
            "artifact_key,artifact_digest,row_count,"
            "byte_count,manifest_key,manifest_digest,raw_manifest_key,"
            "raw_manifest_digest,raw_page_count,raw_row_count,"
            "raw_bytes,committed_at FROM receipt_product_materializations "
            "WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) "
            f"AND run_id IN ({run_placeholders})",
            bound,
        )
    )
    ingestion_runs = tuple(
        _detached_row(row)
        for row in conn.execute(
            "SELECT id,source,runtime,status,authority_operation_id "
            f"FROM ingestion_run_log WHERE id IN ({run_placeholders})",
            run_ids,
        )
    )
    raw_retention_manifests = tuple(
        _detached_row(row)
        for row in conn.execute(
            "SELECT dataset,run_id,manifest_key,page_count,row_count,"
            "raw_bytes,data_digest FROM raw_retention_manifests "
            f"WHERE dataset IN ({placeholders}) "
            f"AND run_id IN ({run_placeholders})",
            bound,
        )
    )
    return (
        collection_receipts,
        product_materializations,
        ingestion_runs,
        raw_retention_manifests,
    )
