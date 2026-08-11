"""Strong invariants for the read-only Quant Data Access foundation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_access import QuantDataAccess, QuantDataConfig
from mcp_servers.quant_data.server import QuantDataMCPServer


EXPECTED_TOOLS = {
    "list_datasets", "describe_dataset",
    "coverage_summary", "dataset_coverage", "coverage_gaps",
    "latest_ready_snapshot", "describe_snapshot", "diff_snapshots",
    "quality_summary", "quality_failures",
    "query_dataset", "get_series",
    "compute_feature", "compute_features",
    "raw_manifest", "trace_provenance",
}


def test_mcp_surface_is_domain_read_only_and_pit_calls_require_as_of():
    server = QuantDataMCPServer()
    tools = server.list_tools()
    by_name = {tool["name"]: tool for tool in tools}

    assert set(by_name) == EXPECTED_TOOLS
    assert not any(
        word in name
        for name in by_name
        for word in ("sql", "ingest", "backfill", "publish", "approve", "delete")
    )
    for name in ("query_dataset", "get_series", "compute_feature", "compute_features", "trace_provenance"):
        assert "as_of" in by_name[name]["inputSchema"]["required"]
    assert len(server.call_tool("list_datasets")["datasets"]) == 23


def test_query_dataset_uses_ready_snapshot_and_filters_future_facts(
    synced_cf_d1_db, monkeypatch
):
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
    monkeypatch.setattr(access, "_snapshot", lambda _snapshot_id=None: ready)

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


def test_worker_retains_every_raw_page_and_scopes_tokens():
    from pathlib import Path

    source = (
        Path(__file__).parents[1]
        / "platform/workers/ingestion-premium/src/index.ts"
    ).read_text(encoding="utf-8")
    assert 'page-${String(page.number).padStart(6, "0")}.json' in source
    assert '`${rawPrefix}/manifest.json`' in source
    assert "data_truncated" not in source
    assert "INGESTION_RUN_TOKEN" in source
    assert "DATA_EXPORT_TOKEN" in source
    assert "INGESTION_PROXY_TOKEN" not in source
