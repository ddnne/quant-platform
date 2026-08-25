from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from scripts.export_ops_projection import render_projection_bundle
from storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "platform/workers/quant-ops-mcp/migrations/projection/0001_ops_projection.sql"


def _seed_jsda(path: Path) -> None:
    store = SqliteStore(path)
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO dataset_coverage
           (dataset,status,policy_version,collection_scope,
            history_target_start,history_target_end_rule,coverage_mode,
            expected_frequency,universe_rule,raw_retention_required,
            structured_reconciliation_required,governance_tier,
            observed_start,observed_end,row_count,source_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jsda_otc_bond_reference_prices", "PARTIAL", "collection-coverage/v3",
            "jsda", "2002-08-02", "current",
            "official_archive_index_reconciled", "official_archive_day",
            "official_index", 1, 1, "governed", "2002-08-02", "2026-08-22",
            5886, 7, "2026-08-25T00:00:00Z", "{}",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jsda", "jsda_otc_bond_reference_prices", "2002-08-02",
            "collection-coverage/v3", "2002-08-02", "2002-08-02", "{}", 1,
            "PARTIAL", 7, "2026-08-25T00:00:00Z", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()


def test_projection_populates_dedicated_jsda_read_model_without_local_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "local.sqlite"
    _seed_jsda(source)
    bundle = render_projection_bundle(
        source,
        generation_id="projgen-jsda",
        producer_commit_sha="c" * 40,
    )
    assert str(tmp_path) not in bundle.sql
    target = sqlite3.connect(":memory:")
    target.executescript(MIGRATION.read_text(encoding="utf-8"))
    target.executescript(bundle.sql)
    assert target.execute(
        "SELECT dataset,status,policy_version FROM dataset_coverage "
        "WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == (
        "jsda_otc_bond_reference_prices",
        "PARTIAL",
        "collection-coverage/v3",
    )
    assert target.execute(
        "SELECT status FROM ops_b0_status WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == ("UNKNOWN",)
    assert target.execute(
        "SELECT status,snapshot_id FROM ops_ready_state "
        "WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == ("NOT_READY", None)
    assert target.execute(
        "SELECT inventory_status,research_eligible,historical_start "
        "FROM endpoint_inventory WHERE projection_generation_id=? "
        "AND dataset_id='equities_bars_minute'",
        (bundle.generation_id,),
    ).fetchone() == ("UNVERIFIED_ENDPOINT", 0, None)
    payload = json.loads(
        target.execute(
            "SELECT payload_json FROM ops_storage_plane_status "
            "WHERE projection_generation_id=?",
            (bundle.generation_id,),
        ).fetchone()[0]
    )
    assert payload["hot_window"]["status"] == "NOT_PROJECTED"
    assert payload["hot_window"]["cutoff"] is None
    target.close()
