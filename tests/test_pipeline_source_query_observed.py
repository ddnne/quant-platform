"""source_query observed_items come from actual raw counts, never expected.

Empty fetches must not mint Coverage COMPLETE. expected_empty is not
COMPLETE without a trusted EXPECTED_EMPTY_WITH_EVIDENCE receipt.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from data_contracts import coverage_contract_for
from ingestion.pipeline_receipts import (
    count_raw_items,
    emit_catalog_job_receipt,
    observed_items_from_actual,
)
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    evaluate_segment,
    read_collection_receipts,
)
from storage.sqlite_store import SqliteStore
from storage.trusted_receipt import SignedReceiptAuthority


def test_source_query_empty_fetch_does_not_copy_expected_or_complete(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    assert count_raw_items([]) == 0
    assert count_raw_items(b'{"data":[]}') == 0
    assert count_raw_items(b'{"data":[1,2]}') == 2
    assert observed_items_from_actual(unit="source_query", raw_item_count=0) == 0
    assert observed_items_from_actual(unit="source_query", raw_item_count=4) == 1

    store = SqliteStore(tmp_path / "t.sqlite")
    job = SimpleNamespace(
        dataset_id="markets_calendar",
        params={"from": "2026-08-01", "to": "2026-08-11"},
    )
    emit_catalog_job_receipt(
        store,
        job=job,
        when="2026-08-11T00:00:00+09:00",
        raw_bytes=b"[]",
        rows=[],
        structured_row_count=0,
        authority=SignedReceiptAuthority(
            signing_key=receipt_ed25519_keys.signing_key
        ),
    )
    rows = read_collection_receipts(store.path, dataset="markets_calendar")
    store.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "SUCCESS"
    assert int(row["observed_items"]) == 0
    assert int(row["expected_items"]) == 1
    assert int(row["observed_items"]) != int(row["expected_items"])
    assert int(row["raw_row_count"]) == 0

    policy = coverage_contract_for("markets_calendar")
    required = RequiredCoverageSegment(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=json.loads(str(row["expected_scope"])),
        expected_items=int(row["expected_items"]),
    )
    receipt = CollectionReceipt(
        source=required.source,
        dataset=required.dataset,
        segment_id=required.segment_id,
        segment_start=required.segment_start,
        segment_end=required.segment_end,
        expected_scope=required.expected_scope,
        expected_items=required.expected_items,
        observed_items=int(row["observed_items"]),
        raw_page_count=int(row["raw_page_count"]),
        raw_row_count=int(row["raw_row_count"]),
        structured_row_count=int(row["structured_row_count"]),
        pagination_exhausted=bool(row["pagination_exhausted"]),
        digests=json.loads(str(row["digests_json"])),
        run_id=int(row["run_id"]),
        status=str(row["status"]),
        error=row["error"],
        checked_at=str(row["checked_at"]),
    )
    status, detail = evaluate_segment(policy, required, receipt)
    assert status != "COMPLETE"
    assert status == "PARTIAL"
    assert detail["eligibility"] == "RECOVERED_RAW_ONLY"
    assert "valid Ed25519 signature required" in detail["reason"]
