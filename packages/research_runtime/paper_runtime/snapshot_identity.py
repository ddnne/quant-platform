"""Logical SQLite snapshot identity without READY publication machinery.

This module is deliberately limited to reading one SQLite database and
deriving its existing logical data identity.  The personal paper path uses it
without importing READY publication, attestation, or snapshot-store code.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote


DATA_SNAPSHOT_FORMAT = "paper-data-snapshot/v1"
RESEARCH_SNAPSHOT_MANIFEST_FORMAT = "research-snapshot-manifest/v2"

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


def _connect_readonly(
    path: Path, *, immutable: bool = False
) -> sqlite3.Connection:
    # A mutable current database may have committed rows only in its WAL.
    query = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    uri = "file:" + quote(str(path.resolve())) + query
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"float": repr(value)}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return {"type": type(value).__name__, "repr": repr(value)}


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    quoted = _quote_identifier(table)
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({quoted})")
    }


def _schema_state(connection: sqlite3.Connection) -> dict[str, Any]:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
    definitions = [
        {
            "type": str(row["type"]),
            "name": str(row["name"]),
            "table": str(row["tbl_name"]),
            "sql": None if row["sql"] is None else str(row["sql"]),
        }
        for row in connection.execute(
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
    connection: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    if "ingestion_watermarks" not in tables:
        return []
    available = _table_columns(connection, "ingestion_watermarks")
    if "dataset" not in available:
        return []
    selected = [column for column in _WATERMARK_COLUMNS if column in available]
    if not ({"last_event_date", "last_ingested_at"} & set(selected)):
        return []
    projection = ", ".join(_quote_identifier(column) for column in selected)
    rows = connection.execute(
        f"SELECT {projection} FROM ingestion_watermarks ORDER BY dataset"
    )
    return [
        {column: _stable_value(row[column]) for column in selected}
        for row in rows
    ]


def _validation_state(
    connection: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    if "ingestion_validation" not in tables:
        return []
    available = _table_columns(connection, "ingestion_validation")
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
    for row in connection.execute(
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
        for row in connection.execute(
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
        for row in connection.execute(latest_sql):
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
    connection: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    """Return PIT fact-table summaries for databases without watermarks."""
    summaries: list[dict[str, Any]] = []
    for table in sorted(tables):
        if table.startswith("sqlite_") or table.startswith("ingestion_"):
            continue
        if "ingested_at" not in _table_columns(connection, table):
            continue
        quoted = _quote_identifier(table)
        row = connection.execute(
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
    metadata = path.stat()
    return {"size": int(metadata.st_size), "mtime_ns": int(metadata.st_mtime_ns)}


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _research_manifest_id(manifest: dict[str, Any]) -> str:
    identity = dict(manifest)
    identity.pop("snapshot_id", None)
    identity.pop("artifact", None)
    identity.pop("created_at", None)
    identity.pop("committed_at", None)
    identity.pop("manifest_digest", None)
    identity.pop("ready_manifest", None)
    ready_evidence = identity.get("ready_evidence")
    if isinstance(ready_evidence, Mapping):
        stable_evidence = dict(ready_evidence)
        stable_items: list[Any] = []
        for raw_item in ready_evidence.get("items", []):
            if not isinstance(raw_item, Mapping):
                stable_items.append(raw_item)
                continue
            item = dict(raw_item)
            detail = item.get("detail")
            if isinstance(detail, Mapping):
                stable_detail = dict(detail)
                stable_detail.pop("evaluated_at", None)
                item["detail"] = stable_detail
            stable_items.append(item)
        stable_evidence["items"] = stable_items
        identity["ready_evidence"] = stable_evidence
    return _canonical_digest(identity)


def _research_manifest_digest(manifest: dict[str, Any]) -> str:
    document = dict(manifest)
    document.pop("manifest_digest", None)
    return _canonical_digest(document)


def _manifest_snapshot_state(
    connection: sqlite3.Connection, tables: set[str]
) -> dict[str, Any] | None:
    if not {"local_snapshot_policy", "local_snapshot_manifests"} <= tables:
        return None
    policy = connection.execute(
        "SELECT require_manifest, snapshot_ready, last_error "
        "FROM local_snapshot_policy WHERE singleton = 1"
    ).fetchone()
    if policy is None or not bool(policy["require_manifest"]):
        return None
    if not bool(policy["snapshot_ready"]):
        detail = str(policy["last_error"] or "sync is incomplete")
        raise RuntimeError(
            "local paper snapshot is not committed and validated: " + detail
        )
    row = connection.execute(
        "SELECT snapshot_id, format, manifest_json FROM local_snapshot_manifests "
        "ORDER BY committed_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("local paper snapshot policy requires a manifest")
    try:
        manifest = json.loads(row["manifest_json"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("latest local snapshot manifest is invalid JSON") from exc
    if row["format"] == RESEARCH_SNAPSHOT_MANIFEST_FORMAT:
        expected_id = _research_manifest_id(manifest)
        if manifest.get("manifest_digest") != _research_manifest_digest(manifest):
            raise RuntimeError("latest local snapshot full-manifest checksum mismatch")
        # READY-only coverage verification stays outside the personal import path.
        from paper_runtime.snapshot_coverage_proof import _verify_coverage_manifest

        _verify_coverage_manifest(connection, manifest)
    else:
        expected_id = _canonical_digest(manifest)
    if expected_id != row["snapshot_id"]:
        raise RuntimeError("latest local snapshot manifest checksum mismatch")
    if manifest.get("state", "READY") != "READY":
        raise RuntimeError("latest local snapshot manifest is not READY")
    current_watermarks = _watermark_state(connection, tables)
    expected = manifest.get("dataset_watermarks")
    if isinstance(manifest.get("ready_manifest"), Mapping):
        required = manifest.get("required_datasets")
        if not isinstance(required, list):
            raise RuntimeError("profile-bound snapshot datasets are malformed")
        required_set = set(required)
        current_watermarks = [
            row
            for row in current_watermarks
            if row.get("dataset") in required_set
        ]
    if current_watermarks != expected:
        raise RuntimeError(
            "local ingestion watermarks no longer match the committed snapshot"
        )
    return {
        "format": DATA_SNAPSHOT_FORMAT,
        "manifest_id": row["snapshot_id"],
        "manifest": manifest,
        "watermarks": current_watermarks,
    }


def _data_snapshot_id(db_path: str | Path, *, immutable: bool) -> str:
    """Return a logical id with an explicit mutable/immutable read contract."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"paper database does not exist: {path}")

    connection = _connect_readonly(path, immutable=immutable)
    try:
        return _data_snapshot_id_from_open_connection(
            connection,
            main_file_state=_main_file_state(path),
        )
    finally:
        connection.close()


def _data_snapshot_id_from_open_connection(
    connection: sqlite3.Connection,
    *,
    main_file_state: Mapping[str, int] | None = None,
) -> str:
    """Derive identity from an already descriptor-pinned SQLite connection."""
    connection.execute("BEGIN")
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        )
    }
    manifest_state = _manifest_snapshot_state(connection, tables)
    if manifest_state is not None:
        return str(manifest_state["manifest_id"])
    watermarks = _watermark_state(connection, tables)
    state: dict[str, Any] = {
        "format": DATA_SNAPSHOT_FORMAT,
        "schema": _schema_state(connection),
        "watermarks": watermarks,
        "validation": _validation_state(connection, tables),
    }
    if not watermarks:
        if main_file_state is None:
            raise RuntimeError(
                "descriptor-pinned snapshot identity has no main-file state"
            )
        state["fallback"] = {
            "fact_tables": _fact_table_state(connection, tables),
            "main_file": dict(main_file_state),
        }
    return _canonical_digest(state)


def data_snapshot_id(db_path: str | Path) -> str:
    """Logical id for a current database, including committed WAL state."""
    return _data_snapshot_id(db_path, immutable=False)


def _immutable_data_snapshot_id(db_path: str | Path) -> str:
    """Logical id for a checkpointed content-addressed snapshot artifact."""
    return _data_snapshot_id(db_path, immutable=True)


__all__ = ["DATA_SNAPSHOT_FORMAT", "data_snapshot_id"]
