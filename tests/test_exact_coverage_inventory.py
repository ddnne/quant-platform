"""Exact V3 inventory is independent of the mutable Coverage ledger."""

from __future__ import annotations

import json

import pytest

from data_contracts.coverage import coverage_contract_for, coverage_policy_binding
from paper_runtime.snapshot_coverage_proof import (
    _coverage_proof,
    persist_coverage_proof,
    require_persisted_coverage_proof,
)
from storage.coverage_ledger import (
    CoverageInventoryAuthorityUnavailable,
    compare_exact_coverage_inventory,
    record_collection_receipt,
    record_required_segments,
)
from storage.sqlite_store import SqliteStore
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)


_EXACT_FIVE = tuple(sorted((
    "equities_bars_daily",
    "equities_master",
    "fins_summary",
    "indices_bars_daily_topix",
    "markets_calendar",
)))
_CUTOFF = "2026-08-26"
_BUILD_ID = "build-exact-five-inventory"
_CHECKED_AT = "2026-08-26T00:00:00+00:00"


def test_exact_five_canonical_inventory_counts_are_frozen(tmp_path) -> None:
    store = SqliteStore(tmp_path / "inventory-counts.sqlite")
    inventory = compare_exact_coverage_inventory(
        store._conn,  # noqa: SLF001
        _EXACT_FIVE,
        target_end=_CUTOFF,
    )
    assert {
        dataset: len(inventory.segments_for(dataset))
        for dataset in _EXACT_FIVE
    } == {
        "equities_bars_daily": 220,
        "equities_master": 220,
        "fins_summary": 218,
        "indices_bars_daily_topix": 220,
        "markets_calendar": 224,
    }
    assert len(inventory.expected_identities) == 1_102
    assert len(inventory.missing) == 1_102
    store.close()


@pytest.mark.parametrize(
    "dataset",
    (
        "equities_bars_daily_am",
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
    ),
    ids=("tip", "archive-index", "source-time-series"),
)
def test_discovery_inventory_without_transition_authority_fails_closed(
    dataset: str,
    tmp_path,
) -> None:
    store = SqliteStore(tmp_path / f"authority-{dataset}.sqlite")
    with pytest.raises(
        CoverageInventoryAuthorityUnavailable,
        match="inventory authority unavailable",
    ):
        compare_exact_coverage_inventory(
            store._conn,  # noqa: SLF001
            (dataset,),
            target_end=_CUTOFF,
        )
    store.close()


def test_exact_five_complete_inventory_mints_and_reopens_v2_proof(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    store = SqliteStore(tmp_path / "exact-five.sqlite")
    conn = store._conn  # noqa: SLF001
    authority = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    planned = compare_exact_coverage_inventory(
        conn,
        _EXACT_FIVE,
        target_end=_CUTOFF,
    )
    expected_by_dataset = {
        dataset: planned.segments_for(dataset) for dataset in _EXACT_FIVE
    }
    selected_runs: list[tuple[int, str, str, str, str]] = []
    next_run = 1
    for dataset, segments in expected_by_dataset.items():
        record_required_segments(conn, segments)
        for segment in segments:
            raw_record = {"segment": segment.segment_id, "value": 1}
            evidence = _reconcile_collection_evidence(
                required=segment,
                run_id=next_run,
                raw_pages=[json.dumps({"data": [raw_record]}).encode("utf-8")],
                raw_records=[raw_record],
                structured_records=[raw_record],
                checked_at=_CHECKED_AT,
                source_request={
                    "from": segment.segment_start,
                    "to": segment.segment_end,
                },
            )
            receipt = authority.issue(evidence)
            record_collection_receipt(conn, receipt)
            selected_runs.append((
                next_run,
                segment.source,
                segment.dataset,
                segment.segment_id,
                coverage_policy_binding(dataset)["policy_version"],
            ))
            next_run += 1
    conn.executemany(
        "UPDATE coverage_segments SET status='COMPLETE',receipt_run_id=? "
        "WHERE source=? AND dataset=? AND segment_id=? AND policy_version=?",
        selected_runs,
    )
    coverage_rows = []
    for dataset, segments in expected_by_dataset.items():
        policy = coverage_contract_for(dataset)
        conn.execute(
            """
            INSERT INTO dataset_coverage (
                dataset,status,policy_version,collection_scope,
                history_target_start,history_target_end_rule,coverage_mode,
                expected_frequency,universe_rule,raw_retention_required,
                structured_reconciliation_required,governance_tier,
                observed_start,observed_end,row_count,source_run_id,
                evaluated_at,detail_json
            ) VALUES (?, 'COMPLETE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                dataset,
                policy.policy_version,
                policy.collection_scope,
                policy.history_target_start,
                policy.history_target_end_rule,
                policy.coverage_mode,
                policy.expected_frequency,
                policy.universe_rule,
                int(policy.raw_retention_required),
                int(policy.structured_reconciliation_required),
                policy.governance_tier,
                segments[0].segment_start,
                segments[-1].segment_end,
                len(segments),
                next_run - 1,
                _CHECKED_AT,
            ),
        )
        coverage_rows.append({
            "dataset": dataset,
            "policy_version": policy.policy_version,
            "status": "COMPLETE",
        })
    conn.execute("CREATE TABLE ingestion_change_log(change_seq INTEGER NOT NULL)")
    conn.execute("INSERT INTO ingestion_change_log VALUES (1102)")
    conn.execute(
        "INSERT INTO sync_change_state(feed,last_applied_change_seq,updated_at) "
        "VALUES ('jquants_records',1102,?)",
        (_CHECKED_AT,),
    )
    conn.execute(
        """
        INSERT INTO snapshot_publications (
            build_id,state,staging_path,contract_version,
            coverage_policy_version,quality_policy_version,created_at
        ) VALUES (?, 'VALIDATING', ?, 'test-contract/v1',
                  'collection-coverage/v3', 'test-quality/v1', ?)
        """,
        (_BUILD_ID, str(store.path), _CHECKED_AT),
    )
    conn.execute(
        """
        INSERT INTO local_snapshot_policy (
            singleton,require_manifest,snapshot_ready,publication_state,
            active_build_id
        ) VALUES (1,1,0,'VALIDATING',?)
        ON CONFLICT(singleton) DO UPDATE SET
            require_manifest=1,snapshot_ready=0,
            publication_state='VALIDATING',active_build_id=excluded.active_build_id
        """,
        (_BUILD_ID,),
    )
    conn.execute(
        """
        INSERT INTO snapshot_quality_results (
            build_id,status,policy_version,evaluated_at,summary_json,results_json
        ) VALUES (?, 'PASS', 'test-quality/v1', ?, '{}', '[]')
        """,
        (_BUILD_ID, _CHECKED_AT),
    )
    conn.commit()

    proof = _coverage_proof(
        conn,
        _EXACT_FIVE,
        coverage_rows,
        publication_cutoff=_CUTOFF,
    )
    assert proof["format"] == "coverage-proof/v2"
    assert proof["inventory_format"] == "coverage-required-inventory/v1"
    assert proof["segment_count"] == proof["receipt_count"] == 1_102
    proof_id = persist_coverage_proof(
        conn,
        _EXACT_FIVE,
        build_id=_BUILD_ID,
    )
    reopened = require_persisted_coverage_proof(
        conn,
        _EXACT_FIVE,
        proof_id,
        build_id=_BUILD_ID,
    )
    assert reopened.proof == proof
    assert reopened.publication_cutoff == _CUTOFF
    store.close()
