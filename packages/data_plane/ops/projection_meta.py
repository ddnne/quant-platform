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
    Mixed table generations force DEGRADED_MIXED_GENERATION (never FRESH).
    """
    path = Path(db_path)
    generated_at = _now()
    gen_id = generation_id or ("projgen-" + uuid4().hex)
    source_generation = None
    age_seconds = None
    status = "MISSING"
    clock = request_now or datetime.now(timezone.utc)

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
        try:
            row = conn.execute(
                "SELECT MAX(evaluated_at) FROM dataset_coverage"
            ).fetchone()
            source_generation = row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            source_generation = None
    finally:
        conn.close()

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
                "active_generation": gen_id,
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
