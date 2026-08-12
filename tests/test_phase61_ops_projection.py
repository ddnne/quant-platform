from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3

from storage.sqlite_store import SqliteStore

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "export_ops_projection", _ROOT / "scripts/export_ops_projection.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)



def _ensure_projection_generation_columns(conn):
    """Align test remote DB with migration 0004_projection_generation.sql."""
    cols = (
        ("dataset_coverage", "projection_generation_id TEXT"),
        ("coverage_segments", "projection_generation_id TEXT"),
        ("ops_ready_snapshots", "projection_generation_id TEXT"),
        ("ops_snapshot_quality", "projection_generation_id TEXT"),
        ("ops_b0_status", "projection_generation_id TEXT"),
        ("ops_projection_metadata", "projection_generation_id TEXT"),
    )
    for table, coldef in cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        except Exception:
            pass  # table may not exist yet or column already present
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ops_projection_generation (
            generation_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source_db_digest TEXT,
            generated_at TEXT NOT NULL,
            producer_commit_sha TEXT,
            contract_digest TEXT,
            registry_digest TEXT,
            coverage_policy_version TEXT,
            activated_at TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ops_projection_active (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            generation_id TEXT NOT NULL,
            activated_at TEXT NOT NULL
        )"""
    )
    conn.commit()


def test_projection_sql_populates_remote_jsda_coverage_without_paths(tmp_path):
    local_path = tmp_path / "local.sqlite"
    store = SqliteStore(local_path)
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
            "jsda_otc_bond_reference_prices", "PARTIAL",
            "collection-coverage/v2", "jsda", "2002-08-02", "current",
            "official_archive_index_reconciled", "official_archive_day",
            "official_index", 1, 1, "governed", "2002-08-02",
            "2002-08-02", 1, 7, "2026-08-11T00:00:00Z", "{}",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO snapshot_quality_results
           (build_id,status,policy_version,evaluated_at,summary_json,results_json)
           VALUES (?,?,?,?,?,?)""",
        (
            "build-jsda", "PASS", "b0+phase35-daily+coverage/v2",
            "2026-08-11T00:02:00Z", '{"failed":0}', "[]",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jsda", "jsda_otc_bond_reference_prices", "2002-08",
            "collection-coverage/v2", "2002-08-02", "2002-08-30", "{}",
            1, "PARTIAL", 7, "2026-08-11T00:00:00Z", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    sql = _MODULE.render_projection_sql(local_path)
    assert str(tmp_path) not in sql

    remote = sqlite3.connect(":memory:")
    _mig = _ROOT / "platform/workers/quant-ops-mcp/migrations"
    for _name in (
        "0002_ops_projection.sql",
        "0003_endpoint_inventory_sla.sql",
        "0004_projection_generation.sql",
        "0005_endpoint_inventory_morning_session.sql",
    ):
        remote.executescript((_mig / _name).read_text(encoding="utf-8"))
    _ensure_projection_generation_columns(remote)
    remote.executescript(sql)
    row = remote.execute(
        "SELECT dataset,status FROM dataset_coverage"
    ).fetchone()
    assert row == ("jsda_otc_bond_reference_prices", "PARTIAL")
    assert remote.execute("SELECT COUNT(*) FROM coverage_segments").fetchone()[0] == 1
    assert remote.execute(
        "SELECT status,source_build_id FROM ops_b0_status"
    ).fetchone() == ("PASS", "build-jsda")
    inv_count = remote.execute("SELECT COUNT(*) FROM endpoint_inventory").fetchone()[0]
    assert inv_count >= 26
    remote.close()
