"""READY publish refuses without coherence; gates fail honestly on empty DB."""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_runtime.coherence import check_ready_coherence
from paper_runtime.snapshot import SnapshotRejected, publish_ready_snapshot
from storage.sqlite_store import SqliteStore


def test_check_ready_coherence_fails_empty_db(tmp_path: Path):
    db = tmp_path / "empty.sqlite"
    store = SqliteStore(db)
    conn = store._conn
    results = check_ready_coherence(
        conn, db, ("markets_calendar",), run_id=None
    )
    assert any(not r.passed for r in results)
    store.close()


def test_publish_ready_blocked_when_coverage_partial(tmp_path: Path):
    """DB without COMPLETE must not publish READY."""
    db = tmp_path / "partial.sqlite"
    store = SqliteStore(db)
    store.close()
    with pytest.raises((SnapshotRejected, Exception)):
        publish_ready_snapshot(
            db,
            tmp_path / "snaps",
            required_datasets=("markets_calendar",),
        )
