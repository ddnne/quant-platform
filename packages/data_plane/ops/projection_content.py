"""Canonical content addressing for immutable Ops Projection payload rows."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Mapping


PROJECTED_CONTENT_TABLES = (
    "collection_sla_status",
    "coverage_segments",
    "dataset_coverage",
    "endpoint_inventory",
    "ingestion_run_log",
    "ingestion_validation",
    "ingestion_watermarks",
    "ops_alerts",
    "ops_b0_status",
    "ops_projection_metadata",
    "ops_ready_snapshots",
    "ops_ready_state",
    "ops_snapshot_quality",
    "ops_storage_plane_status",
    "ops_sync_feed",
    "raw_retention_manifests",
)


def canonical_content_bytes(value: Any) -> bytes:
    """Match the Worker canonicalizer: sorted keys, UTF-8, no whitespace."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def projection_content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_content_bytes(value)).hexdigest()


def _storage_value(value: Any) -> Any:
    """Normalize values to SQLite/D1's JSON-visible storage representation."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if (
            not math.isfinite(value)
            or not value.is_integer()
            or not (-(2**63) <= value < 2**63)
        ):
            raise ValueError(
                "Ops Projection payloads do not permit non-integral REAL values"
            )
        return int(value)
    if isinstance(value, Mapping):
        return {str(key): _storage_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_storage_value(item) for item in value]
    return value


def _canonical_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [
        {str(key): _storage_value(value) for key, value in row.items()}
        for row in rows
    ]
    return sorted(normalized, key=canonical_content_bytes)


def build_projection_content_manifest(
    table_rows: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Address every projected row and bind the complete table membership."""

    if set(table_rows) != set(PROJECTED_CONTENT_TABLES):
        missing = sorted(set(PROJECTED_CONTENT_TABLES) - set(table_rows))
        extra = sorted(set(table_rows) - set(PROJECTED_CONTENT_TABLES))
        raise ValueError(
            f"Ops Projection content table drift: missing={missing}, extra={extra}"
        )
    manifest: dict[str, dict[str, Any]] = {}
    for table in PROJECTED_CONTENT_TABLES:
        rows = _canonical_rows(table_rows[table])
        manifest[table] = {
            "row_count": len(rows),
            "content_digest": projection_content_digest({"rows": rows}),
        }
    return manifest, projection_content_digest({"tables": manifest})


__all__ = [
    "PROJECTED_CONTENT_TABLES",
    "build_projection_content_manifest",
    "canonical_content_bytes",
    "projection_content_digest",
]
