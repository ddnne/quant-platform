"""READY publish refuses without coherence; gates fail honestly on empty DB."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from paper_runtime.coherence import check_ready_coherence
from paper_runtime.ready_policy import (
    ReadyEvidenceBundle,
    ReadyEvidenceItem,
    ReadyPublicationPolicy,
)
from paper_runtime.snapshot import SnapshotRejected, _publish_ready_snapshot
from storage.sqlite_store import SqliteStore


def test_bundle_pass_fail():
    b = ReadyEvidenceBundle(
        items=[
            ReadyEvidenceItem("a", True),
            ReadyEvidenceItem("b", False, reason="x"),
        ]
    )
    assert not b.passed
    assert len(b.failures()) == 1


def test_policy_constructs():
    assert ReadyPublicationPolicy() is not None


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
        _publish_ready_snapshot(
            db,
            tmp_path / "snaps",
            required_datasets=("markets_calendar",),
        )


def test_populated_natural_keys_do_not_replace_migration_authority(
    tmp_path: Path,
) -> None:
    db = tmp_path / "natural-key-without-ledger.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE jquants_records (natural_key TEXT)")
    conn.execute("INSERT INTO jquants_records VALUES ('already-populated')")
    results = check_ready_coherence(conn, db, ("markets_calendar",))
    gate = next(
        item for item in results if item.gate_name == "natural_key_migration_ready"
    )
    assert gate.passed is False
    assert gate.reason == "No natural key migration evidence found"
    conn.close()
