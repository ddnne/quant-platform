"""Shared Ops projection status / metadata (single logic for export + publish).

States (honest — failed refresh must never look FRESH):
  FRESH
  DEGRADED_REFRESH_FAILED
  STALE
  MISSING
  FAILED
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

PROJECTION_VERSION = "ops_projection/v2"
DEFAULT_MAX_AGE_SECONDS = 86400


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_projection_metadata(
    db_path: str | Path,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    refresh_status: str | None = None,
    refresh_error: str | None = None,
    last_refresh_attempt_at: str | None = None,
    last_success_at: str | None = None,
    applied_at: str | None = None,
    publisher: str = "ops.projection_meta",
) -> dict[str, Any]:
    """Build unified projection metadata.

    ``refresh_status``: success | failed | skipped | None
    If refresh_status == failed → status DEGRADED_REFRESH_FAILED (even if age is fresh).
    """
    path = Path(db_path)
    generated_at = _now()
    source_generation = None
    age_seconds = None
    status = "MISSING"

    if not path.exists():
        return {
            "status": "MISSING",
            "generated_at": generated_at,
            "source_generation": None,
            "age_seconds": None,
            "last_refresh_attempt_at": last_refresh_attempt_at,
            "last_refresh_status": refresh_status or "missing_db",
            "last_refresh_error": refresh_error or f"db not found: {path}",
            "last_success_at": last_success_at,
            "applied_at": applied_at,
            "projection_version": PROJECTION_VERSION,
            "publisher": publisher,
            "detail_json": json.dumps({"reason": "db_missing"}, sort_keys=True),
        }

    conn = sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=ro", uri=True)
    try:
        try:
            row = conn.execute(
                "SELECT MAX(evaluated_at) FROM dataset_coverage"
            ).fetchone()
            source_generation = row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            source_generation = None
    finally:
        conn.close()

    if source_generation:
        try:
            source_dt = datetime.fromisoformat(source_generation)
            generated_dt = datetime.fromisoformat(generated_at)
            age_seconds = int((generated_dt - source_dt).total_seconds())
            status = "FRESH" if age_seconds <= max_age_seconds else "STALE"
        except (ValueError, TypeError):
            status = "FAILED"
    else:
        status = "FAILED"

    if refresh_status == "failed":
        # Never present a failed refresh as FRESH.
        status = "DEGRADED_REFRESH_FAILED"

    return {
        "status": status,
        "generated_at": generated_at,
        "source_generation": source_generation,
        "age_seconds": age_seconds,
        "last_refresh_attempt_at": last_refresh_attempt_at or generated_at,
        "last_refresh_status": refresh_status,
        "last_refresh_error": refresh_error,
        "last_success_at": last_success_at
        if refresh_status != "failed"
        else last_success_at,
        "applied_at": applied_at,
        "projection_version": PROJECTION_VERSION,
        "publisher": publisher,
        "detail_json": json.dumps(
            {
                "max_age_seconds": max_age_seconds,
                "refresh_status": refresh_status,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "PROJECTION_VERSION",
    "build_projection_metadata",
]
