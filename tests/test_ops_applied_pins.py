"""Cursor projection invariants for the dedicated Ops read model."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.export_ops_projection import render_projection_bundle, sync_dataset_state
from storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_MIGRATION = (
    ROOT
    / "platform/workers/quant-ops-mcp/migrations/projection/0001_ops_projection.sql"
)


def _source_db(path: Path, *, applied: int | None) -> None:
    store = SqliteStore(path)
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO dataset_coverage
           (dataset,status,policy_version,collection_scope,
            history_target_start,history_target_end_rule,coverage_mode,
            expected_frequency,universe_rule,raw_retention_required,
            structured_reconciliation_required,governance_tier,
            observed_start,observed_end,row_count,source_run_id,evaluated_at,
            detail_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "markets_calendar", "PARTIAL", "collection-coverage/v3", "jquants",
            "2008-01-01", "current", "official", "daily", "all", 1, 1,
            "governed", "2008-01-01", "2008-01-01", 1, 1,
            "2026-08-25T00:00:00Z", "{}",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jquants", "markets_calendar", "2008-01",
            "collection-coverage/v3", "2008-01-01", "2008-01-31", "{}", 1,
            "PARTIAL", 1, "2026-08-25T00:00:00Z", "{}",
        ),
    )
    if applied is not None:
        store._conn.execute(  # noqa: SLF001
            """INSERT INTO sync_change_state
               (feed,last_applied_change_seq,updated_at) VALUES (?,?,?)
               ON CONFLICT(feed) DO UPDATE SET
                 last_applied_change_seq=excluded.last_applied_change_seq,
                 updated_at=excluded.updated_at""",
            ("jquants_records", applied, "2026-08-25T00:02:00Z"),
        )
    store._conn.commit()  # noqa: SLF001
    store.close()


def _target() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(PROJECTION_MIGRATION.read_text(encoding="utf-8"))
    return conn


def test_null_applied_cursor_is_never_current() -> None:
    for exported in (None, 0, 10):
        for lag in (None, 0, 1):
            assert sync_dataset_state(
                exported=exported,
                applied=None,
                lag=lag,
                change_log_rows=1,
            ) != "CURRENT"


def test_equal_non_null_cursors_are_current() -> None:
    assert sync_dataset_state(
        exported=10, applied=10, lag=0, change_log_rows=1
    ) == "CURRENT"
    assert sync_dataset_state(
        exported=0, applied=0, lag=0, change_log_rows=1
    ) == "CURRENT"


def test_source_export_applied_cursors_are_projected_without_coercion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.sqlite"
    _source_db(path, applied=42)
    bundle = render_projection_bundle(
        path,
        generation_id="projgen-cursors",
        producer_commit_sha="a" * 40,
        source_cursor=42,
        export_cursor=42,
    )
    target = _target()
    target.executescript(bundle.sql)
    assert target.execute(
        "SELECT latest_source_change_seq,exported_cursor,applied_cursor "
        "FROM ops_sync_feed WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == (42, 42, 42)
    assert target.execute(
        "SELECT source_cursor,export_cursor,applied_cursor "
        "FROM ops_projection_metadata WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == (42, 42, 42)
    target.close()


def test_missing_applied_cursor_projects_sql_null_not_zero(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite"
    _source_db(path, applied=None)
    bundle = render_projection_bundle(
        path,
        generation_id="projgen-unpinned",
        producer_commit_sha="b" * 40,
        source_cursor=10,
        export_cursor=10,
    )
    target = _target()
    target.executescript(bundle.sql)
    assert target.execute(
        "SELECT applied_cursor FROM ops_sync_feed WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == (None,)
    target.close()
