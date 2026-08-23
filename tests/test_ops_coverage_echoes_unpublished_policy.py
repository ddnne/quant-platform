"""Ops coverage echoes unpublished stored policy_version, not frozen V2."""

from __future__ import annotations

import sqlite3

from data_access import QuantDataAccess, QuantReadDomainService

UNPUBLISHED_POLICY = "collection-coverage/v3-unpublished"


def test_ops_coverage_echoes_unpublished_policy_version_not_frozen_v2(tmp_path):
    db_path = tmp_path / "current.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE dataset_coverage (
            dataset TEXT PRIMARY KEY, status TEXT, policy_version TEXT,
            governance_tier TEXT
        );
        CREATE TABLE coverage_segments (
            dataset TEXT, segment_id TEXT, segment_start TEXT, status TEXT,
            policy_version TEXT
        );
        INSERT INTO dataset_coverage VALUES
            ('equities_bars_daily', 'PARTIAL',
             'collection-coverage/v3-unpublished', 'governed');
        INSERT INTO coverage_segments VALUES
            ('equities_bars_daily', '2025-01', '2025-01-01', 'PARTIAL',
             'collection-coverage/v3-unpublished');
        """
    )
    conn.commit()
    conn.close()
    service = QuantReadDomainService(QuantDataAccess(), ops_db_path=db_path)

    coverage = service.call_tool(
        "dataset_coverage", {"dataset": "equities_bars_daily"}
    )
    assert coverage["status"] == "PARTIAL"
    assert coverage["coverage"]["status"] == "PARTIAL"
    assert coverage["coverage"]["policy_version"] == UNPUBLISHED_POLICY
    coverage_text = str(coverage)
    assert "collection-coverage/v2" not in coverage_text
    assert "Coverage V2" not in coverage_text
    assert "COMPLETE" not in coverage_text
    assert "READY" not in coverage_text
    assert "FRESH" not in coverage_text
    assert coverage["status"] not in {"COMPLETE", "READY", "GO", "FRESH"}

    gaps = service.call_tool("coverage_gaps")
    by_dataset = {row["dataset"]: row for row in gaps["gaps"]}
    bars = by_dataset["equities_bars_daily"]
    assert bars["status"] == "PARTIAL"
    assert bars["policy_version"] == UNPUBLISHED_POLICY
    assert "collection-coverage/v2" not in str(bars)
    assert "Coverage V2" not in str(bars)
    assert bars["status"] not in {"COMPLETE", "READY", "GO", "FRESH"}

    missing = by_dataset["jsda_otc_bond_reference_prices"]
    assert missing["status"] == "UNKNOWN"
    assert missing["reason"] == "Coverage projection has not been populated"
    assert "Coverage V2" not in missing["reason"]
    assert missing.get("policy_version") in (None, "")
    for dataset, row in by_dataset.items():
        if dataset == "equities_bars_daily":
            continue
        assert row["status"] == "UNKNOWN"
        assert "Coverage V2" not in row["reason"]

    segments = service.call_tool(
        "coverage_segments", {"dataset": "equities_bars_daily"}
    )
    assert segments["segments"][0]["status"] == "PARTIAL"
    assert segments["segments"][0]["policy_version"] == UNPUBLISHED_POLICY
    assert "collection-coverage/v2" not in str(segments)
    assert "Coverage V2" not in str(segments)
