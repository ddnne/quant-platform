"""Coverage ledger persistence I/O: receipts, required inventory, and writes.

Evaluate / COMPLETE policy stays in ``coverage_ledger``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from urllib.parse import quote

from data_contracts.coverage import (
    COVERAGE_STATUSES,
    coverage_policy_binding,
)

if TYPE_CHECKING:
    from storage.coverage_ledger import CollectionReceipt, RequiredCoverageSegment


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    uri = "file:" + quote(str(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def record_collection_receipt(
    conn: sqlite3.Connection, receipt: CollectionReceipt
) -> None:
    """Upsert one run-scoped receipt; caller owns the transaction."""
    if receipt.status not in {"SUCCESS", "FAILED"}:
        raise ValueError("receipt status must be SUCCESS or FAILED")
    counts = (
        receipt.observed_items,
        receipt.raw_page_count,
        receipt.raw_row_count,
        receipt.structured_row_count,
    )
    if any(value < 0 for value in counts):
        raise ValueError("receipt counts must be non-negative")
    columns = (
        "source", "dataset", "segment_id", "segment_start", "segment_end",
        "expected_scope", "expected_items", "observed_items", "raw_page_count",
        "raw_row_count", "structured_row_count", "pagination_exhausted",
        "digests_json", "run_id", "status", "error", "checked_at",
    )
    values = (
        receipt.source, receipt.dataset, receipt.segment_id,
        receipt.segment_start, receipt.segment_end,
        _canonical_json(dict(receipt.expected_scope)), receipt.expected_items,
        receipt.observed_items, receipt.raw_page_count, receipt.raw_row_count,
        receipt.structured_row_count, int(receipt.pagination_exhausted),
        _canonical_json(dict(receipt.digests)), receipt.run_id, receipt.status,
        receipt.error, receipt.checked_at,
    )
    conn.execute(
        "INSERT INTO collection_receipts (" + ",".join(columns) + ") VALUES ("
        + ",".join("?" for _ in columns) + ") "
        "ON CONFLICT(source,dataset,segment_id,run_id) DO UPDATE SET "
        + ",".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column not in {"source", "dataset", "segment_id", "run_id"}
        ),
        values,
    )


def record_required_segments(
    conn: sqlite3.Connection,
    required_segments: Sequence[RequiredCoverageSegment],
    *,
    policy_version: str | None = None,
) -> None:
    """Persist source-planned requirements under each effective policy row."""
    evaluated_at = _now()
    columns = (
        "source", "dataset", "segment_id", "policy_version",
        "segment_start", "segment_end", "expected_scope", "expected_items",
        "status", "receipt_run_id", "evaluated_at", "detail_json",
    )
    sql = (
        "INSERT INTO coverage_segments (" + ",".join(columns) + ") VALUES ("
        + ",".join("?" for _ in columns) + ") "
        "ON CONFLICT(source,dataset,segment_id,policy_version) DO UPDATE SET "
        + ",".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column not in {"source", "dataset", "segment_id", "policy_version"}
        )
    )
    rows = []
    for segment in required_segments:
        if segment.expected_items is not None and segment.expected_items < 0:
            raise ValueError("expected segment items must be non-negative")
        effective_policy_version = (
            policy_version
            if policy_version is not None
            else coverage_policy_binding(segment.dataset)["policy_version"]
        )
        rows.append((
            segment.source, segment.dataset, segment.segment_id,
            effective_policy_version,
            segment.segment_start, segment.segment_end,
            _canonical_json(dict(segment.expected_scope)), segment.expected_items,
            "UNKNOWN", None, evaluated_at,
            _canonical_json({"reason": "required segment planned"}),
        ))
    conn.executemany(sql, rows)


def read_dataset_coverage(
    db_path: str | Path, *, dataset: str | None = None
) -> list[dict[str, Any]]:
    """Read ledger rows through a forced read-only connection."""
    conn = _connect_readonly(db_path)
    try:
        if dataset is None:
            cursor = conn.execute("SELECT * FROM dataset_coverage ORDER BY dataset")
        else:
            cursor = conn.execute(
                "SELECT * FROM dataset_coverage WHERE dataset=?", (dataset,)
            )
        return [dict(row) for row in cursor]
    finally:
        conn.close()


def read_collection_receipts(
    db_path: str | Path,
    *,
    dataset: str | None = None,
    segment_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read run-scoped receipt evidence through a forced read-only connection."""
    conn = _connect_readonly(db_path)
    try:
        clauses: list[str] = []
        values: list[str] = []
        if dataset is not None:
            clauses.append("dataset=?")
            values.append(dataset)
        if segment_id is not None:
            clauses.append("segment_id=?")
            values.append(segment_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cursor = conn.execute(
            "SELECT * FROM collection_receipts" + where
            + " ORDER BY dataset, segment_start, checked_at, run_id",
            values,
        )
        return [dict(row) for row in cursor]
    finally:
        conn.close()


def read_coverage_segments(
    db_path: str | Path,
    *,
    dataset: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Read the independently planned V2 inventory and evaluated status."""
    if status is not None and status not in COVERAGE_STATUSES:
        raise ValueError(f"unknown coverage status: {status!r}")
    conn = _connect_readonly(db_path)
    try:
        clauses: list[str] = []
        values: list[Any] = []
        if dataset is not None:
            clauses.append("dataset=?")
            values.append(dataset)
            clauses.append("policy_version=?")
            values.append(coverage_policy_binding(dataset)["policy_version"])
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cursor = conn.execute(
            "SELECT * FROM coverage_segments" + where
            + " ORDER BY dataset, segment_start, segment_id",
            values,
        )
        rows = [dict(row) for row in cursor]
        if dataset is not None:
            return rows
        return [
            row
            for row in rows
            if row["policy_version"]
            == coverage_policy_binding(str(row["dataset"]))["policy_version"]
        ]
    finally:
        conn.close()


_DATASET_COVERAGE_COLUMNS = (
    "dataset", "status", "policy_version", "collection_scope",
    "history_target_start", "history_target_end_rule", "coverage_mode",
    "expected_frequency", "universe_rule", "raw_retention_required",
    "structured_reconciliation_required", "governance_tier",
    "observed_start", "observed_end", "row_count", "source_run_id",
    "evaluated_at", "detail_json",
)
_BOOL_COVERAGE_COLUMNS = {
    "raw_retention_required",
    "structured_reconciliation_required",
}
_SEGMENT_WRITE_COLUMNS = (
    "source", "dataset", "segment_id", "policy_version",
    "segment_start", "segment_end", "expected_scope", "expected_items",
    "status", "receipt_run_id", "evaluated_at", "detail_json",
)
_SQL_PRIMITIVE_TYPES = frozenset({str, int, float, bytes, bool, type(None)})


def _freeze_sql_value(value: Any, *, field: str) -> Any:
    """Reject adapter-confused subclasses and return one immutable scalar."""
    if type(value) not in _SQL_PRIMITIVE_TYPES:
        raise TypeError(f"{field} must be an exact built-in SQLite scalar")
    return value


def _freeze_mapping_row(
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> tuple[Any, ...]:
    """Read each untrusted Mapping field exactly once before policy checks."""
    return tuple(
        _freeze_sql_value(row[column], field=column) for column in columns
    )


def _require_plain_string(value: Any, *, field: str) -> str:
    frozen = _freeze_sql_value(value, field=field)
    if type(frozen) is not str:
        raise TypeError(f"{field} must be an exact built-in string")
    return frozen


def persist_refreshed_coverage(
    conn: sqlite3.Connection,
    *,
    delete_keys: Sequence[tuple[str, str, str]],
    segment_rows: Sequence[Mapping[str, Any]],
    coverage_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Atomically replace evaluated segments and upsert dataset_coverage.

    Aggregate COMPLETE is intentionally not an input to this generic writer.
    Existing verified COMPLETE rows use the status-preserving helpers below;
    future first transitions belong to the separate C10 authority.
    """
    frozen_delete_keys = tuple(
        tuple(
            _require_plain_string(value, field="delete_key") for value in key
        )
        for key in delete_keys
    )
    if any(len(key) != 3 for key in frozen_delete_keys):
        raise ValueError("Coverage delete keys must contain exactly three fields")
    frozen_segment_rows = tuple(
        _freeze_mapping_row(row, _SEGMENT_WRITE_COLUMNS) for row in segment_rows
    )
    frozen_coverage_rows = tuple(
        _freeze_mapping_row(row, _DATASET_COVERAGE_COLUMNS)
        for row in coverage_rows
    )
    status_index = _DATASET_COVERAGE_COLUMNS.index("status")
    if any(
        values[status_index] == "COMPLETE"
        for values in frozen_coverage_rows
    ):
        raise ValueError(
            "generic Coverage persistence cannot write aggregate COMPLETE"
        )
    segment_sql = (
        "INSERT INTO coverage_segments (" + ",".join(_SEGMENT_WRITE_COLUMNS)
        + ") VALUES (" + ",".join("?" for _ in _SEGMENT_WRITE_COLUMNS) + ")"
    )
    coverage_sql = (
        "INSERT INTO dataset_coverage (" + ",".join(_DATASET_COVERAGE_COLUMNS)
        + ") VALUES (" + ",".join("?" for _ in _DATASET_COVERAGE_COLUMNS)
        + ") ON CONFLICT(dataset) DO UPDATE SET "
        + ",".join(
            f"{column}=excluded.{column}"
            for column in _DATASET_COVERAGE_COLUMNS
            if column != "dataset"
        )
    )
    owns_transaction = not conn.in_transaction
    try:
        if owns_transaction:
            conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "DELETE FROM coverage_segments "
            "WHERE source=? AND dataset=? AND policy_version=?",
            frozen_delete_keys,
        )
        conn.executemany(
            segment_sql,
            frozen_segment_rows,
        )
        conn.executemany(
            coverage_sql,
            [
                tuple(
                    int(value) if column in _BOOL_COVERAGE_COLUMNS else value
                    for column, value in zip(
                        _DATASET_COVERAGE_COLUMNS,
                        values,
                        strict=True,
                    )
                )
                for values in frozen_coverage_rows
            ],
        )
        if owns_transaction:
            conn.commit()
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


def update_dataset_coverage_row(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    status: str,
    detail_json: str,
    evaluated_at: str,
) -> None:
    """Update one non-COMPLETE aggregate; never mint COMPLETE."""
    dataset = _require_plain_string(dataset, field="dataset")
    status = _require_plain_string(status, field="status")
    detail_json = _require_plain_string(detail_json, field="detail_json")
    evaluated_at = _require_plain_string(evaluated_at, field="evaluated_at")
    if status == "COMPLETE":
        raise ValueError(
            "generic Coverage update cannot write aggregate COMPLETE"
        )
    conn.execute(
        """
        UPDATE dataset_coverage
        SET status=?, detail_json=?, evaluated_at=?
        WHERE dataset=?
        """,
        (status, detail_json, evaluated_at, dataset),
    )


def preserve_existing_complete_coverage_row(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
) -> None:
    """Refresh metadata without changing an existing current-policy COMPLETE."""
    values = _freeze_mapping_row(row, _DATASET_COVERAGE_COLUMNS)
    frozen = dict(zip(_DATASET_COVERAGE_COLUMNS, values, strict=True))
    if frozen["status"] != "COMPLETE":
        raise ValueError("status-preserving Coverage update requires COMPLETE")
    columns = tuple(
        column for column in _DATASET_COVERAGE_COLUMNS
        if column not in {"dataset", "status", "policy_version"}
    )
    cursor = conn.execute(
        "UPDATE dataset_coverage SET "
        + ",".join(f"{column}=?" for column in columns)
        + " WHERE dataset=? AND status='COMPLETE' AND policy_version=?",
        (
            *(
                int(frozen[column]) if column in _BOOL_COVERAGE_COLUMNS
                else frozen[column]
                for column in columns
            ),
            frozen["dataset"],
            frozen["policy_version"],
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(
            "verified COMPLETE aggregate disappeared or changed policy"
        )


def update_existing_complete_coverage_evidence(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    policy_version: str,
    detail_json: str,
    evaluated_at: str,
) -> None:
    """Update evidence fields while preserving an existing COMPLETE status."""
    dataset = _require_plain_string(dataset, field="dataset")
    policy_version = _require_plain_string(
        policy_version,
        field="policy_version",
    )
    detail_json = _require_plain_string(detail_json, field="detail_json")
    evaluated_at = _require_plain_string(evaluated_at, field="evaluated_at")
    cursor = conn.execute(
        "UPDATE dataset_coverage SET detail_json=?,evaluated_at=? "
        "WHERE dataset=? AND status='COMPLETE' AND policy_version=?",
        (detail_json, evaluated_at, dataset, policy_version),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(
            "verified COMPLETE aggregate disappeared or changed policy"
        )


__all__ = [
    "persist_refreshed_coverage",
    "read_collection_receipts",
    "read_coverage_segments",
    "read_dataset_coverage",
    "record_collection_receipt",
    "record_required_segments",
    "preserve_existing_complete_coverage_row",
    "update_existing_complete_coverage_evidence",
    "update_dataset_coverage_row",
]
