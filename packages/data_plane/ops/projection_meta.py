"""Shared Ops projection status / metadata (atomic generation, honest age).

States:
  FRESH
  DEGRADED_REFRESH_FAILED
  DEGRADED_MIXED_GENERATION
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
from uuid import uuid4

PROJECTION_VERSION = "ops_projection/v3"
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
    generation_id: str | None = None,
    producer_commit_sha: str | None = None,
    contract_digest: str | None = None,
    registry_digest: str | None = None,
    request_now: datetime | None = None,
    table_generations: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build unified projection metadata.

    Age is request_now - generated_at (never a frozen zero).
    FRESH requires refresh_status == "success" (never skipped/null/failed).
    Mixed table generations force DEGRADED_MIXED_GENERATION (never FRESH).
    """
    path = Path(db_path)
    generated_at = _now()
    gen_id = generation_id or ("projgen-" + uuid4().hex)

    base = {
        "active_generation": gen_id,
        "producer_commit_sha": producer_commit_sha,
        "contract_digest": contract_digest,
        "registry_digest": registry_digest,
        "projection_version": PROJECTION_VERSION,
        "publisher": publisher,
    }

    if not path.exists():
        return {
            **base,
            "status": "MISSING",
            "generated_at": generated_at,
            "source_generation": None,
            "age_seconds": None,
            "projection_age_seconds": None,
            "last_refresh_attempt_at": last_refresh_attempt_at,
            "last_refresh_status": refresh_status or "missing_db",
            "last_refresh_error": refresh_error or f"db not found: {path}",
            "last_success_at": last_success_at,
            "applied_at": applied_at,
            "detail_json": json.dumps({"reason": "db_missing"}, sort_keys=True),
        }

    conn = sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=ro", uri=True)
    try:
        conn.execute("BEGIN")
        return _build_projection_metadata_from_connection(
            conn,
            generated_at=generated_at,
            max_age_seconds=max_age_seconds,
            refresh_status=refresh_status,
            refresh_error=refresh_error,
            last_refresh_attempt_at=last_refresh_attempt_at,
            last_success_at=last_success_at,
            applied_at=applied_at,
            publisher=publisher,
            generation_id=gen_id,
            producer_commit_sha=producer_commit_sha,
            contract_digest=contract_digest,
            registry_digest=registry_digest,
            request_now=request_now,
            table_generations=table_generations,
        )
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def _build_projection_metadata_from_connection(
    conn: sqlite3.Connection,
    *,
    generated_at: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    refresh_status: str | None = None,
    refresh_error: str | None = None,
    last_refresh_attempt_at: str | None = None,
    last_success_at: str | None = None,
    applied_at: str | None = None,
    publisher: str = "ops.projection_meta",
    generation_id: str,
    producer_commit_sha: str | None = None,
    contract_digest: str | None = None,
    registry_digest: str | None = None,
    request_now: datetime | None = None,
    table_generations: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build metadata inside a caller-owned SQLite read snapshot.

    Unlike :func:`build_projection_metadata`, this function never accepts or
    opens a database path.  The Ops Projection renderer uses it so every source
    query belongs to the same descriptor-bound snapshot.
    """

    if type(conn) is not sqlite3.Connection or not conn.in_transaction:
        raise RuntimeError("projection metadata requires one active SQLite snapshot")
    source_generation = None
    age_seconds = None
    clock = request_now or datetime.now(timezone.utc)
    base = {
        "active_generation": generation_id,
        "producer_commit_sha": producer_commit_sha,
        "contract_digest": contract_digest,
        "registry_digest": registry_digest,
        "projection_version": PROJECTION_VERSION,
        "publisher": publisher,
    }
    try:
        row = conn.execute(
            "SELECT MAX(evaluated_at) FROM dataset_coverage"
        ).fetchone()
        source_generation = row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        source_generation = None

    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if generated_dt.tzinfo is None:
            generated_dt = generated_dt.replace(tzinfo=timezone.utc)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=timezone.utc)
        age_seconds = max(0, int((clock - generated_dt).total_seconds()))
    except (ValueError, TypeError):
        age_seconds = None

    if source_generation:
        status = (
            "FRESH"
            if age_seconds is not None and age_seconds <= max_age_seconds
            else "STALE"
        )
    else:
        status = "FAILED"

    if refresh_status == "failed":
        status = "DEGRADED_REFRESH_FAILED"
    elif status == "FRESH" and refresh_status != "success":
        # Export-only / skipped / clock-rotation is not a successful refresh.
        # Stored D1 CHECK only allows FRESH|STALE|FAILED|UNKNOWN; callers coerce.
        status = "STALE"

    if table_generations:
        gens = {str(v) for v in table_generations.values() if v}
        if len(gens) > 1:
            status = "DEGRADED_MIXED_GENERATION"

    return {
        **base,
        "status": status,
        "generated_at": generated_at,
        "source_generation": source_generation,
        "age_seconds": age_seconds,
        "projection_age_seconds": age_seconds,
        "last_refresh_attempt_at": last_refresh_attempt_at or generated_at,
        "last_refresh_status": refresh_status,
        "last_refresh_error": refresh_error,
        "last_success_at": last_success_at,
        "applied_at": applied_at,
        "detail_json": json.dumps(
            {
                "max_age_seconds": max_age_seconds,
                "refresh_status": refresh_status,
                "active_generation": generation_id,
                "table_generations": table_generations or {},
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
