"""Persistence I/O for paper data snapshot artifacts.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module copies SQLite, writes JSON sidecars, and persists BUILDING/SYNCED
rows; it does not decide READY.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4


def _atomic_json(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    fd, raw_path = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                payload, handle, ensure_ascii=True, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _copy_sqlite(source: sqlite3.Connection, target_path: Path) -> None:
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
    finally:
        target.close()


def begin_snapshot_sync(conn: sqlite3.Connection, *, started_at: str) -> str:
    """Invalidate research access and enter BUILDING before any write."""
    build_id = "build-" + uuid4().hex
    conn.execute(
        """
        INSERT INTO local_snapshot_policy
            (singleton, require_manifest, snapshot_ready, sync_started_at,
             last_error, publication_state, active_build_id,
             active_snapshot_id)
        VALUES (1, 1, 0, ?, NULL, 'BUILDING', ?, NULL)
        ON CONFLICT(singleton) DO UPDATE SET
            require_manifest = 1,
            snapshot_ready = 0,
            sync_started_at = excluded.sync_started_at,
            last_error = NULL,
            publication_state = 'BUILDING',
            active_build_id = excluded.active_build_id,
            active_snapshot_id = NULL
        """,
        (started_at, build_id),
    )
    conn.commit()
    return build_id


def _persist_building_publication(
    conn: sqlite3.Connection,
    *,
    build_id: str,
    created_at: str,
    staging_path: str,
    contract_version: str,
    coverage_policy_version: str,
    quality_policy_version: str,
) -> None:
    """Write BUILDING rows. Caller owns READY policy."""
    conn.execute(
        """
        INSERT INTO local_snapshot_policy
            (singleton, require_manifest, snapshot_ready, sync_started_at,
             last_error, publication_state, active_build_id,
             active_snapshot_id)
        VALUES (1, 1, 0, ?, NULL, 'BUILDING', ?, NULL)
        ON CONFLICT(singleton) DO UPDATE SET
            require_manifest=1, snapshot_ready=0, last_error=NULL,
            publication_state='BUILDING', active_build_id=excluded.active_build_id,
            active_snapshot_id=NULL
        """,
        (created_at, build_id),
    )
    conn.execute(
        """
        INSERT INTO snapshot_publications
            (build_id, state, staging_path, contract_version,
             coverage_policy_version, quality_policy_version, created_at)
        VALUES (?, 'BUILDING', ?, ?, ?, ?, ?)
        """,
        (
            build_id, staging_path, contract_version,
            coverage_policy_version, quality_policy_version, created_at,
        ),
    )
    conn.commit()


def _persist_synced_publication(conn: sqlite3.Connection, build_id: str) -> None:
    """Mark snapshot_publications SYNCED. Policy table stays with policy helper."""
    conn.execute(
        "UPDATE snapshot_publications SET state='SYNCED' WHERE build_id=?",
        (build_id,),
    )
    conn.commit()


def _persist_synced_policy(conn: sqlite3.Connection) -> None:
    """SYNCED row write for legacy in-place commit. Caller owns the transaction."""
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state='SYNCED' "
        "WHERE singleton=1"
    )
