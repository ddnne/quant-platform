"""Cheap, control-plane-based identifiers for local SQLite data snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


DATA_SNAPSHOT_FORMAT = "paper-data-snapshot/v1"

_WATERMARK_COLUMNS = (
    "dataset",
    "last_event_date",
    "last_ingested_at",
)
_VALIDATION_LATEST_COLUMNS = (
    "id",
    "run_id",
    "dataset",
    "started_at",
    "finished_at",
    "status",
    "rows_seen",
    "rows_inserted",
    "rows_revisions",
    "available_at_min",
    "available_at_max",
)
_VALIDATION_SUM_COLUMNS = (
    "rows_seen",
    "rows_inserted",
    "rows_revisions",
)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _stable_value(value: Any) -> Any:
    """Return a JSON-safe value without losing SQLite storage-class identity."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"float": repr(value)}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return {"type": type(value).__name__, "repr": repr(value)}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    quoted = _quote_identifier(table)
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({quoted})")
    }


def _schema_state(conn: sqlite3.Connection) -> dict[str, Any]:
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
    definitions = [
        {
            "type": str(row["type"]),
            "name": str(row["name"]),
            "table": str(row["tbl_name"]),
            "sql": None if row["sql"] is None else str(row["sql"]),
        }
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "ORDER BY type, name, tbl_name"
        )
    ]
    return {
        "user_version": user_version,
        "schema_version": schema_version,
        "definitions": definitions,
    }


def _watermark_state(
    conn: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    if "ingestion_watermarks" not in tables:
        return []
    available = _table_columns(conn, "ingestion_watermarks")
    if "dataset" not in available:
        return []
    selected = [column for column in _WATERMARK_COLUMNS if column in available]
    if not ({"last_event_date", "last_ingested_at"} & set(selected)):
        return []
    projection = ", ".join(_quote_identifier(column) for column in selected)
    rows = conn.execute(
        f"SELECT {projection} FROM ingestion_watermarks ORDER BY dataset"
    )
    return [
        {column: _stable_value(row[column]) for column in selected}
        for row in rows
    ]


def _validation_state(
    conn: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    if "ingestion_validation" not in tables:
        return []
    available = _table_columns(conn, "ingestion_validation")
    if "dataset" not in available:
        return []

    dataset_sql = _quote_identifier("dataset")
    sums = [column for column in _VALIDATION_SUM_COLUMNS if column in available]
    aggregate_parts = ["COUNT(*) AS row_count"]
    aggregate_parts.extend(
        f"COALESCE(SUM({_quote_identifier(column)}), 0) AS "
        f"{_quote_identifier('sum_' + column)}"
        for column in sums
    )
    for column in ("id", "started_at", "finished_at"):
        if column in available:
            aggregate_parts.append(
                f"MAX({_quote_identifier(column)}) AS "
                f"{_quote_identifier('max_' + column)}"
            )
    aggregate_sql = ", ".join(aggregate_parts)
    aggregates: dict[Any, dict[str, Any]] = {}
    for row in conn.execute(
        f"SELECT {dataset_sql} AS dataset, {aggregate_sql} "
        "FROM ingestion_validation GROUP BY dataset ORDER BY dataset"
    ):
        dataset = row["dataset"]
        aggregates[dataset] = {
            key: _stable_value(row[key])
            for key in row.keys()
            if key != "dataset"
        }

    if "status" in available:
        for row in conn.execute(
            "SELECT dataset, status, COUNT(*) AS status_count "
            "FROM ingestion_validation "
            "GROUP BY dataset, status ORDER BY dataset, status"
        ):
            status_counts = aggregates[row["dataset"]].setdefault(
                "status_counts", []
            )
            status_counts.append(
                {
                    "status": _stable_value(row["status"]),
                    "count": int(row["status_count"]),
                }
            )

    latest_columns = [
        column for column in _VALIDATION_LATEST_COLUMNS if column in available
    ]
    order_columns = [
        column
        for column in ("finished_at", "started_at", "id")
        if column in available
    ]
    if latest_columns and order_columns:
        projection = ", ".join(
            _quote_identifier(column) for column in latest_columns
        )
        ordering = ", ".join(
            f"{_quote_identifier(column)} DESC" for column in order_columns
        )
        latest_sql = (
            f"SELECT {projection} FROM ("
            f"SELECT {projection}, ROW_NUMBER() OVER ("
            f"PARTITION BY {dataset_sql} ORDER BY {ordering}"
            ") AS snapshot_rank FROM ingestion_validation"
            ") WHERE snapshot_rank = 1 ORDER BY dataset"
        )
        for row in conn.execute(latest_sql):
            aggregates[row["dataset"]]["latest"] = {
                column: _stable_value(row[column]) for column in latest_columns
            }

    return [
        {
            "dataset": _stable_value(dataset),
            **aggregate,
        }
        for dataset, aggregate in sorted(
            aggregates.items(), key=lambda item: str(item[0])
        )
    ]


def _fact_table_state(
    conn: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    """Summarize PIT fact tables only for the no-watermark fallback path."""
    summaries: list[dict[str, Any]] = []
    for table in sorted(tables):
        if table.startswith("sqlite_") or table.startswith("ingestion_"):
            continue
        if "ingested_at" not in _table_columns(conn, table):
            continue
        quoted = _quote_identifier(table)
        row = conn.execute(
            f"SELECT COUNT(*) AS row_count, "
            f"MAX({_quote_identifier('ingested_at')}) AS max_ingested_at "
            f"FROM {quoted}"
        ).fetchone()
        summaries.append(
            {
                "table": table,
                "row_count": int(row["row_count"]),
                "max_ingested_at": _stable_value(row["max_ingested_at"]),
            }
        )
    return summaries


def _main_file_state(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def data_snapshot_id(db_path: str | Path) -> str:
    """Return a lightweight logical identifier for a local data snapshot.

    Watermarks and validation summaries are the authoritative fast path.  A
    database without usable watermark rows falls back to fact-table counts,
    maximum ingestion timestamps, and weak main-file metadata.  No database
    payload or SQLite file is read byte-for-byte.
    """
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"paper database does not exist: {path}")

    conn = _connect_readonly(path)
    try:
        conn.execute("BEGIN")
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        watermarks = _watermark_state(conn, tables)
        state: dict[str, Any] = {
            "format": DATA_SNAPSHOT_FORMAT,
            "schema": _schema_state(conn),
            "watermarks": watermarks,
            "validation": _validation_state(conn, tables),
        }
        if not watermarks:
            state["fallback"] = {
                "fact_tables": _fact_table_state(conn, tables),
                "main_file": _main_file_state(path),
            }
    finally:
        conn.close()

    canonical = json.dumps(
        state,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


__all__ = ["DATA_SNAPSHOT_FORMAT", "data_snapshot_id"]
