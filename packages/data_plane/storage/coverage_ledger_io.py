"""Coverage ledger persistence I/O: receipts, required inventory, and reads.

Evaluate / COMPLETE policy stays in ``coverage_ledger``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any, Sequence
from urllib.parse import quote

from data_contracts.coverage import COVERAGE_STATUSES, POLICY_VERSION

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
    policy_version: str = POLICY_VERSION,
) -> None:
    """Persist source-planned requirements independently of any receipt."""
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
        rows.append((
            segment.source, segment.dataset, segment.segment_id, policy_version,
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
        clauses = ["policy_version=?"]
        values: list[Any] = [POLICY_VERSION]
        if dataset is not None:
            clauses.append("dataset=?")
            values.append(dataset)
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        cursor = conn.execute(
            "SELECT * FROM coverage_segments WHERE " + " AND ".join(clauses)
            + " ORDER BY dataset, segment_start, segment_id",
            values,
        )
        return [dict(row) for row in cursor]
    finally:
        conn.close()


__all__ = [
    "read_collection_receipts",
    "read_coverage_segments",
    "read_dataset_coverage",
    "record_collection_receipt",
    "record_required_segments",
]
