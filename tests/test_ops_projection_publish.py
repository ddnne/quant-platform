"""Tests for ops projection publish automation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3

from ops.projection_meta import build_projection_metadata
from storage.sqlite_store import SqliteStore

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "publish_ops_projection", _ROOT / "scripts/publish_ops_projection.py"
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


def _setup_test_db(tmp_path: Path) -> Path:
    """Create a minimal test DB with required tables."""
    db_path = tmp_path / "test.sqlite"
    store = SqliteStore(db_path)
    # Create minimal required tables
    store._conn.execute(  # noqa: SLF001
        """CREATE TABLE IF NOT EXISTS dataset_coverage (
            dataset TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            collection_scope TEXT NOT NULL,
            history_target_start TEXT NOT NULL,
            history_target_end_rule TEXT NOT NULL,
            coverage_mode TEXT NOT NULL,
            expected_frequency TEXT NOT NULL,
            universe_rule TEXT NOT NULL,
            raw_retention_required INTEGER NOT NULL,
            structured_reconciliation_required INTEGER NOT NULL,
            governance_tier TEXT NOT NULL,
            observed_start TEXT,
            observed_end TEXT,
            row_count INTEGER NOT NULL,
            source_run_id INTEGER,
            evaluated_at TEXT NOT NULL,
            detail_json TEXT NOT NULL
        )"""
    )
    store._conn.execute(  # noqa: SLF001
        """CREATE TABLE IF NOT EXISTS coverage_segments (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            segment_start TEXT NOT NULL,
            segment_end TEXT NOT NULL,
            expected_scope TEXT NOT NULL,
            expected_items INTEGER,
            status TEXT NOT NULL,
            receipt_run_id INTEGER,
            evaluated_at TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            PRIMARY KEY (source, dataset, segment_id, policy_version)
        )"""
    )
    store._conn.execute(  # noqa: SLF001
        """CREATE TABLE IF NOT EXISTS snapshot_quality_results (
            build_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            evaluated_at TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            results_json TEXT NOT NULL
        )"""
    )
    # Insert minimal data
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
            "test_dataset", "COMPLETE",
            "collection-coverage/v2", "test", "2020-01-01", "current",
            "official", "daily", "all", 1, 1, "governed", "2020-01-01",
            "2020-01-01", 1, 1, "2026-08-11T00:00:00Z", "{}",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "test", "test_dataset", "2020-01",
            "collection-coverage/v2", "2020-01-01", "2020-01-31", "{}",
            1, "COMPLETE", 1, "2026-08-11T00:00:00Z", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    return db_path


def test_publish_dry_run_prints_sql_preview_and_metadata(tmp_path, capsys):
    """Test that --dry-run prints SQL preview and metadata without writing files."""
    db_path = _setup_test_db(tmp_path)
    output_dir = tmp_path / "ops"
    output_file = output_dir / "projection.sql"
    meta_file = output_dir / "projection_meta.json"

    # Ensure files don't exist
    assert not output_file.exists()
    assert not meta_file.exists()

    # Run with --dry-run
    import sys
    old_argv = sys.argv
    sys.argv = [
        "publish_ops_projection.py",
        f"--db={db_path}",
        f"--output={output_file}",
        f"--meta-output={meta_file}",
        "--dry-run",
    ]
    try:
        result = _MODULE.main()
        assert result == 0
    finally:
        sys.argv = old_argv

    # Check that files were NOT written
    assert not output_file.exists()
    assert not meta_file.exists()

    # Check stdout output
    captured = capsys.readouterr()
    output = captured.out

    # Should contain SQL preview (first 2000 chars)
    assert "BEGIN TRANSACTION;" in output
    assert "DELETE FROM dataset_coverage;" in output
    # Note: COMMIT may not be in first 2000 chars, so we don't check for it here

    # Should contain metadata JSON
    assert "projection_status" in output
    assert "FRESH" in output
    assert "publisher" in output
    assert "scripts/publish_ops_projection.py" in output


def test_publish_writes_sql_and_metadata_files(tmp_path):
    """Test that normal mode writes SQL and metadata files."""
    db_path = _setup_test_db(tmp_path)
    output_dir = tmp_path / "ops"
    output_file = output_dir / "projection.sql"
    meta_file = output_dir / "projection_meta.json"

    # Run normal mode
    import sys
    old_argv = sys.argv
    sys.argv = [
        "publish_ops_projection.py",
        f"--db={db_path}",
        f"--output={output_file}",
        f"--meta-output={meta_file}",
    ]
    try:
        result = _MODULE.main()
        assert result == 0
    finally:
        sys.argv = old_argv

    # Check that files were written
    assert output_file.exists()
    assert meta_file.exists()

    # Check SQL file content
    sql_content = output_file.read_text(encoding="utf-8")
    assert "BEGIN TRANSACTION;" in sql_content
    assert "DELETE FROM dataset_coverage;" in sql_content
    assert "INSERT INTO dataset_coverage" in sql_content
    assert "COMMIT;" in sql_content

    # Check metadata file content
    meta_content = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta_content["projection_status"] == "FRESH"
    assert "projection_generated_at" in meta_content
    assert meta_content["publisher"] == "scripts/publish_ops_projection.py"
    assert meta_content["local_db"] == str(db_path)
    assert "sql_bytes" in meta_content
    assert meta_content["sql_bytes"] > 0


def test_publish_metadata_includes_expected_fields(tmp_path):
    """Test that published metadata contains all expected fields."""
    db_path = _setup_test_db(tmp_path)
    output_dir = tmp_path / "ops"
    output_file = output_dir / "projection.sql"
    meta_file = output_dir / "projection_meta.json"

    # Run normal mode
    import sys
    old_argv = sys.argv
    sys.argv = [
        "publish_ops_projection.py",
        f"--db={db_path}",
        f"--output={output_file}",
        f"--meta-output={meta_file}",
    ]
    try:
        result = _MODULE.main()
        assert result == 0
    finally:
        sys.argv = old_argv

    # Check metadata fields
    meta_content = json.loads(meta_file.read_text(encoding="utf-8"))
    expected_fields = {
        "projection_status",
        "projection_generated_at",
        "projection_source_generation",
        "local_db",
        "snapshot_dir",
        "sql_bytes",
        "publisher",
    }
    assert expected_fields <= set(meta_content.keys())


def test_export_includes_projection_metadata_with_status_check(tmp_path):
    """Test that exported SQL includes ops_projection_metadata with proper status fields."""
    from scripts.export_ops_projection import render_projection_sql

    db_path = _setup_test_db(tmp_path)

    sql = render_projection_sql(db_path)

    # Check that projection metadata is included
    assert "INSERT INTO ops_projection_metadata" in sql
    assert "generated_at" in sql
    assert "source_generation" in sql
    assert "age_seconds" in sql
    assert "status" in sql

    # Check that it includes valid status values
    assert "FRESH" in sql or "STALE" in sql or "FAILED" in sql or "UNKNOWN" in sql

    # Verify SQL can be executed against schema
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

    # Verify the metadata table has data
    row = remote.execute(
        "SELECT status, projection_version FROM ops_projection_metadata"
    ).fetchone()
    assert row is not None
    status, version = row
    assert status in ("FRESH", "STALE", "FAILED", "UNKNOWN")
    assert version == "ops_projection/v3"


def test_export_includes_endpoint_inventory(tmp_path):
    """Test that exported SQL includes endpoint_inventory table."""
    from scripts.export_ops_projection import render_projection_sql

    db_path = _setup_test_db(tmp_path)

    sql = render_projection_sql(db_path)

    # Check that endpoint inventory is included
    assert "INSERT INTO endpoint_inventory" in sql

    # Verify SQL can be executed against schema
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

    # Verify the endpoint_inventory table has data
    row = remote.execute(
        "SELECT COUNT(*) FROM endpoint_inventory"
    ).fetchone()
    assert row is not None
    count = row[0]
    assert count > 0


def test_export_metadata_age_calculation(tmp_path):
    """Test that projection metadata correctly calculates age and status."""
    from scripts.export_ops_projection import render_projection_sql

    db_path = _setup_test_db(tmp_path)

    # Add a dataset_coverage entry with recent evaluated_at
    store = SqliteStore(db_path)
    store._conn.execute(  # noqa: SLF001
        """UPDATE dataset_coverage SET evaluated_at = ?""",
        ("2026-08-11T00:00:00Z",)
    )
    store._conn.commit()  # noqa: SLF001
    store.close()

    sql = render_projection_sql(db_path)

    # Execute and check metadata
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

    # Get metadata row
    row = remote.execute(
        "SELECT age_seconds, status FROM ops_projection_metadata"
    ).fetchone()
    assert row is not None
    age_seconds, status = row

    # Age should be a number (could be None if source_generation is missing)
    if age_seconds is not None:
        assert isinstance(age_seconds, int)
        assert age_seconds >= 0

    # Status should be valid
    assert status in ("FRESH", "STALE", "FAILED", "UNKNOWN")


def test_missing_db_is_missing(tmp_path: Path):
    meta = build_projection_metadata(tmp_path / "nope.sqlite")
    assert meta["status"] == "MISSING"


def test_failed_refresh_never_fresh(tmp_path: Path):
    db = tmp_path / "empty.sqlite"
    sqlite3.connect(db).close()
    meta = build_projection_metadata(
        db, refresh_status="failed", refresh_error="boom"
    )
    assert meta["status"] == "DEGRADED_REFRESH_FAILED"
    assert meta["last_refresh_error"] == "boom"
