"""Strong invariants for the read-only Quant Data Access foundation."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from _coreseed import write_snapshot_observation_clock
from data_access import QuantDataAccess, QuantDataConfig
from mcp_servers.quant_data.server import QuantDataMCPServer
from storage.sqlite_store import SqliteStore


EXPECTED_TOOLS = {
    "list_datasets", "describe_dataset",
    "coverage_summary", "dataset_coverage", "coverage_gaps",
    "latest_ready_snapshot", "describe_snapshot", "diff_snapshots",
    "quality_summary", "quality_failures",
    "query_dataset", "get_series",
    "compute_feature", "compute_features",
    "raw_manifest", "trace_provenance",
}
EXPECTED_OPS_TOOLS = {
    "ops_status", "ingestion_last_run", "dataset_coverage", "coverage_gaps",
    "coverage_segments", "backfill_status", "validation_summary", "b0_status",
    "latest_ready_snapshot", "snapshot_quality", "raw_retention_status",
    "sync_status", "storage_plane_status",
}


def test_mcp_surface_is_domain_read_only_and_pit_calls_require_as_of():
    server = QuantDataMCPServer()
    tools = server.list_tools()
    by_name = {tool["name"]: tool for tool in tools}

    assert EXPECTED_TOOLS <= set(by_name)
    assert EXPECTED_OPS_TOOLS <= set(by_name)
    assert not ({
        "sql", "ingest_trigger", "publish", "approve", "delete", "shell",
        "fetch_url", "broker",
    } & set(by_name))
    for name in ("query_dataset", "get_series", "compute_feature", "compute_features", "trace_provenance"):
        assert "as_of" in by_name[name]["inputSchema"]["required"]
    datasets = server.call_tool("list_datasets")
    assert datasets["plane"] == "research_ready"
    assert datasets["mutable"] is False
    assert len(datasets["datasets"]) >= 23


def test_ops_coverage_tool_descriptions_echo_stored_policy_not_frozen_v2():
    server = QuantDataMCPServer()
    by_name = {tool["name"]: tool["description"] for tool in server.list_tools()}
    for name in ("dataset_coverage", "coverage_gaps", "coverage_segments"):
        assert "policy_version as stored on the generation" in by_name[name]
        assert "Coverage V2" not in by_name[name]


def test_query_dataset_uses_ready_snapshot_and_filters_future_facts(
    synced_cf_d1_db, monkeypatch
):
    with SqliteStore(synced_cf_d1_db.db) as store:
        write_snapshot_observation_clock(
            store, "2025-04-04T15:30:00+09:00"
        )
    access = QuantDataAccess(
        QuantDataConfig(
            snapshot_dir=synced_cf_d1_db.db.parent,
            default_page_size=2,
            max_rows=10,
        )
    )
    ready = SimpleNamespace(
        snapshot_id="sha256:" + "1" * 64,
        db_path=synced_cf_d1_db.db,
        manifest={"state": "READY", "source_run": {"id": 7}},
    )
    monkeypatch.setattr(
        access,
        "_pinned_snapshot",
        lambda _snapshot_id=None: nullcontext(ready),
    )

    first = access.query_dataset(
        dataset="equities_bars_daily",
        as_of="2025-04-03T15:30:00+09:00",
        code="8697",
        start="2025-04-01",
        end="2025-04-04",
    )
    assert [row["payload"]["Date"] for row in first["rows"]] == [
        "2025-04-01", "2025-04-02"
    ]
    assert first["next_page_token"]
    second = access.query_dataset(
        dataset="equities_bars_daily",
        as_of="2025-04-03T15:30:00+09:00",
        code="8697",
        start="2025-04-01",
        end="2025-04-04",
        page_token=first["next_page_token"],
    )
    assert [row["payload"]["Date"] for row in second["rows"]] == ["2025-04-03"]

    with pytest.raises(ValueError, match="page_token"):
        access.query_dataset(
            dataset="equities_bars_daily",
            as_of="2025-04-03T15:30:00+09:00",
            code="7203",
            start="2025-04-01",
            end="2025-04-04",
            page_token=first["next_page_token"],
        )
