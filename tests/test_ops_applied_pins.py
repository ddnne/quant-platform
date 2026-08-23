"""Applied-pin projector: emit local sync_change_state without CURRENT-on-null."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3

from storage.sqlite_store import SqliteStore

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EXPORT = _load("export_ops_projection", "scripts/export_ops_projection.py")
_LAG = _load("report_d1_local_sync_lag", "scripts/report_d1_local_sync_lag.py")


def _seed_coverage(store: SqliteStore) -> None:
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
            "markets_calendar", "PARTIAL",
            "collection-coverage/v2", "jquants", "2013-01-01", "current",
            "official", "daily", "all", 1, 1, "governed", "2013-01-01",
            "2013-01-01", 1, 1, "2026-08-11T00:00:00Z", "{}",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jquants", "markets_calendar", "2013-01",
            "collection-coverage/v2", "2013-01-01", "2013-01-31", "{}",
            1, "PARTIAL", 1, "2026-08-11T00:00:00Z", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001


def _apply_ops_migrations(conn: sqlite3.Connection) -> None:
    mig = _ROOT / "platform/workers/quant-ops-mcp/migrations"
    for name in (
        "0002_ops_projection.sql",
        "0003_endpoint_inventory_sla.sql",
        "0004_projection_generation.sql",
        "0005_endpoint_inventory_morning_session.sql",
        "0007_ops_applied_pins.sql",
    ):
        conn.executescript((mig / name).read_text(encoding="utf-8"))


def test_null_applied_never_current():
    for exported in (None, 0, 10, 2859284):
        for lag in (None, 0, 1, 5):
            for n in (0, 1, 367):
                state = _EXPORT.sync_dataset_state(
                    exported=exported, applied=None, lag=lag, change_log_rows=n
                )
                assert state != "CURRENT", (exported, lag, n, state)
                assert _LAG.sync_dataset_state(
                    exported=exported, applied=None, lag=lag, change_log_rows=n
                ) == state


def test_lag_zero_unpinned_is_export_current_apply_unpinned():
    assert (
        _EXPORT.sync_dataset_state(
            exported=10, applied=None, lag=0, change_log_rows=1
        )
        == "EXPORT_CURRENT_APPLY_UNPINNED"
    )


def test_matching_pin_can_be_current():
    assert (
        _EXPORT.sync_dataset_state(
            exported=10, applied=10, lag=0, change_log_rows=1
        )
        == "CURRENT"
    )
    # 0 is a real pin, unlike missing.
    assert (
        _EXPORT.sync_dataset_state(
            exported=0, applied=0, lag=0, change_log_rows=1
        )
        == "CURRENT"
    )


def test_missing_pin_projects_sql_null_not_zero(tmp_path):
    db_path = tmp_path / "local.sqlite"
    store = SqliteStore(db_path)
    _seed_coverage(store)
    store.close()

    sql = _EXPORT.render_projection_sql(db_path, generation_id="projgen-unpinned")
    pin_inserts = [
        line for line in sql.splitlines() if "INSERT INTO ops_applied_pins" in line
    ]
    assert pin_inserts
    assert all("CURRENT" not in line for line in pin_inserts)
    assert "VALUES ('jquants_records',NULL," in sql

    remote = sqlite3.connect(":memory:")
    _apply_ops_migrations(remote)
    remote.executescript(sql)
    row = remote.execute(
        "SELECT last_applied_change_seq, feed FROM ops_applied_pins "
        "WHERE feed = 'jquants_records'"
    ).fetchone()
    assert row is not None
    assert row[0] is None
    assert row[1] == "jquants_records"
    meta = remote.execute(
        "SELECT detail_json FROM ops_projection_metadata"
    ).fetchone()[0]
    assert '"unpinned":true' in meta
    assert '"last_applied_change_seq":null' in meta
    remote.close()


def test_present_pin_is_projected(tmp_path):
    db_path = tmp_path / "local.sqlite"
    store = SqliteStore(db_path)
    _seed_coverage(store)
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO sync_change_state "
        "(feed, last_applied_change_seq, updated_at) VALUES (?, ?, ?)",
        ("jquants_records", 2859284, "2026-08-12T00:00:00Z"),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    sql = _EXPORT.render_projection_sql(db_path, generation_id="projgen-pinned")
    remote = sqlite3.connect(":memory:")
    _apply_ops_migrations(remote)
    remote.executescript(sql)
    row = remote.execute(
        "SELECT last_applied_change_seq FROM ops_applied_pins "
        "WHERE feed = 'jquants_records'"
    ).fetchone()
    assert row == (2859284,)
    meta = remote.execute(
        "SELECT detail_json FROM ops_projection_metadata"
    ).fetchone()[0]
    assert '"unpinned":false' in meta
    assert "2859284" in meta
    remote.close()

    exported = 2859284
    applied = 2859284
    assert (
        _EXPORT.sync_dataset_state(
            exported=exported, applied=applied, lag=0, change_log_rows=1
        )
        == "CURRENT"
    )


def _ensure_watermarks(store: SqliteStore) -> None:
    store._conn.execute(  # noqa: SLF001
        """CREATE TABLE IF NOT EXISTS ingestion_watermarks (
            dataset TEXT PRIMARY KEY,
            last_event_date TEXT,
            last_ingested_at TEXT NOT NULL,
            last_export_cursor INTEGER
        )"""
    )


def test_report_unpinned_is_not_current(tmp_path):
    db_path = tmp_path / "local.sqlite"
    store = SqliteStore(db_path)
    _ensure_watermarks(store)
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_watermarks "
        "(dataset, last_event_date, last_ingested_at, last_export_cursor) "
        "VALUES (?, ?, ?, ?)",
        ("markets_calendar", "2026-08-12", "2026-08-12T00:00:00Z", 10),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    report = _LAG.collect(
        db_path,
        remote_max_seq=10,
        remote_change_log_n=1,
        focus=["markets_calendar"],
    )
    assert report["local"]["last_applied_change_seq"] is None
    assert report["local"]["applied_pin_present"] is False
    assert report["focus"][0]["sync_state"] == "EXPORT_CURRENT_APPLY_UNPINNED"
    assert report["focus"][0]["sync_state"] != "CURRENT"


def test_report_pinned_matching_can_be_current(tmp_path):
    db_path = tmp_path / "local.sqlite"
    store = SqliteStore(db_path)
    _ensure_watermarks(store)
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_watermarks "
        "(dataset, last_event_date, last_ingested_at, last_export_cursor) "
        "VALUES (?, ?, ?, ?)",
        ("markets_calendar", "2026-08-12", "2026-08-12T00:00:00Z", 10),
    )
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO sync_change_state "
        "(feed, last_applied_change_seq, updated_at) VALUES (?, ?, ?)",
        ("jquants_records", 10, "2026-08-12T00:00:00Z"),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    report = _LAG.collect(
        db_path,
        remote_max_seq=10,
        remote_change_log_n=1,
        focus=["markets_calendar"],
    )
    assert report["local"]["applied_pin_present"] is True
    assert report["local"]["last_applied_change_seq"] == 10
    assert report["focus"][0]["sync_state"] == "CURRENT"


def test_migration_0007_creates_nullable_seq():
    conn = sqlite3.connect(":memory:")
    _apply_ops_migrations(conn)
    info = {
        row[1]: row
        for row in conn.execute("PRAGMA table_info(ops_applied_pins)")
    }
    assert "last_applied_change_seq" in info
    # notnull flag is 0 → NULL legal (unpinned).
    assert info["last_applied_change_seq"][3] == 0
    conn.execute(
        "INSERT INTO ops_applied_pins "
        "(feed, last_applied_change_seq, updated_at, projected_at) "
        "VALUES ('jquants_records', NULL, NULL, '2026-08-23T00:00:00Z')"
    )
    conn.commit()
    seq = conn.execute(
        "SELECT last_applied_change_seq FROM ops_applied_pins"
    ).fetchone()[0]
    assert seq is None
    conn.close()
