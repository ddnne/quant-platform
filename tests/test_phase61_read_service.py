"""Focused boundaries for the shared Ops/Research read service."""

from __future__ import annotations

import sqlite3

from data_access import QuantDataAccess, QuantReadDomainService
from mcp_servers.quant_data.server import QuantDataMCPServer


def _current_control_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ingestion_run_log (
            id INTEGER PRIMARY KEY, ran_at TEXT, source TEXT, runtime TEXT,
            status TEXT, detail TEXT
        );
        CREATE TABLE dataset_coverage (
            dataset TEXT PRIMARY KEY, status TEXT, governance_tier TEXT
        );
        CREATE TABLE coverage_segments (
            dataset TEXT, segment_id TEXT, segment_start TEXT, status TEXT
        );
        CREATE TABLE ingestion_validation (
            id INTEGER PRIMARY KEY, run_id INTEGER, dataset TEXT, status TEXT,
            rows_seen INTEGER, rows_inserted INTEGER, rows_revisions INTEGER,
            detail TEXT, finished_at TEXT
        );
        CREATE TABLE raw_retention_manifests (
            dataset TEXT, run_id INTEGER, manifest_key TEXT, page_count INTEGER,
            row_count INTEGER, raw_bytes INTEGER, data_digest TEXT,
            completeness TEXT, created_at TEXT
        );
        CREATE TABLE ingestion_watermarks (
            dataset TEXT, last_event_date TEXT, last_ingested_at TEXT,
            last_export_cursor INTEGER
        );
        CREATE TABLE ingestion_change_log (change_seq INTEGER);

        INSERT INTO ingestion_run_log VALUES
            (7, '2026-08-11T00:00:00Z', 'jquants', 'worker', 'pass', 'ok');
        INSERT INTO dataset_coverage VALUES
            ('equities_bars_daily', 'PARTIAL', 'governed'),
            ('jsda_otc_bond_reference_prices', 'PARTIAL', 'governed');
        INSERT INTO coverage_segments VALUES
            ('equities_bars_daily', '2025-01', '2025-01-01', 'COMPLETE'),
            ('equities_bars_daily', '2025-02', '2025-02-01', 'PARTIAL');
        INSERT INTO ingestion_validation VALUES
            (1, 7, 'equities_bars_daily', 'pass', 3, 3, 0, 'ok',
             '2026-08-11T00:01:00Z');
        INSERT INTO raw_retention_manifests VALUES
            ('equities_bars_daily', 7, 'raw/manifest.json', 1, 3, 100,
             'sha256:abc', 'COMPLETE', '2026-08-11T00:00:00Z');
        INSERT INTO ingestion_watermarks VALUES
            ('equities_bars_daily', '2025-02-28',
             '2026-08-11T00:00:00Z', 41);
        INSERT INTO ingestion_change_log VALUES (41);
        """
    )
    conn.commit()
    conn.close()


def test_ops_current_reads_are_bounded_labeled_and_not_ready(tmp_path):
    db_path = tmp_path / "current.sqlite"
    _current_control_db(db_path)
    service = QuantReadDomainService(QuantDataAccess(), ops_db_path=db_path)

    coverage = service.call_tool(
        "dataset_coverage", {"dataset": "equities_bars_daily"}
    )
    assert coverage["plane"] == "ops_current"
    assert coverage["mutable"] is True
    assert coverage["coverage"]["status"] == "PARTIAL"

    jsda = service.call_tool(
        "dataset_coverage", {"dataset": "jsda_otc_bond_reference_prices"}
    )
    assert jsda["coverage"]["status"] == "PARTIAL"
    assert any(
        row["dataset"] == "jsda_otc_bond_reference_prices"
        for row in service.call_tool("coverage_gaps")["gaps"]
    )

    segments = service.call_tool(
        "coverage_segments",
        {"dataset": "equities_bars_daily", "limit": 1},
    )
    assert len(segments["segments"]) == 1
    assert segments["limit"] == 1

    sync = service.call_tool("sync_status")
    assert sync["latest_change_seq"] == 41


def test_missing_ops_coverage_is_unknown_and_lists_every_governed_gap(tmp_path):
    service = QuantReadDomainService(
        QuantDataAccess(), ops_db_path=tmp_path / "absent.sqlite"
    )

    one = service.call_tool(
        "dataset_coverage", {"dataset": "jsda_tokyo_repo_rates"}
    )
    assert one["status"] == "UNKNOWN"
    assert one["coverage"] is None

    result = service.call_tool("coverage_gaps")
    assert result["status"] == "UNKNOWN"
    assert len(result["gaps"]) == result["governed_dataset_count"]
    assert any(
        row["dataset"] == "jsda_otc_bond_reference_prices"
        for row in result["gaps"]
    )


def test_research_calls_are_delegated_and_labeled_immutable():
    class StubResearch:
        def query_dataset(self, **arguments):
            return {"rows": [], "request": arguments}

    service = QuantReadDomainService(StubResearch())
    result = service.call_tool(
        "query_dataset",
        {"dataset": "equities_bars_daily", "as_of": "2025-01-01"},
    )

    assert result["plane"] == "research_ready"
    assert result["mutable"] is False
    assert result["request"]["as_of"] == "2025-01-01"


def test_local_mcp_dispatches_through_shared_service(tmp_path):
    db_path = tmp_path / "current.sqlite"
    _current_control_db(db_path)
    service = QuantReadDomainService(QuantDataAccess(), ops_db_path=db_path)
    server = QuantDataMCPServer(service=service)

    names = {tool["name"] for tool in server.list_tools()}
    assert {
        "ops_status", "coverage_segments", "snapshot_quality",
        "query_dataset", "trace_provenance",
    } <= names
    result = server.call_tool("ingestion_last_run")
    assert result["plane"] == "ops_current"
    assert result["run"]["id"] == 7

    forbidden = {
        "sql", "r2_browse", "secrets", "shell", "fetch_url",
        "ingest_trigger", "delete", "publish", "feature_approve", "broker",
    }
    assert not (forbidden & names)
