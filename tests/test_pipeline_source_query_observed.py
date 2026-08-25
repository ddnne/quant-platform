"""source_query observed_items come from actual raw counts, never expected.

Empty fetches must not mint Coverage COMPLETE. expected_empty is not
COMPLETE without a trusted EXPECTED_EMPTY_WITH_EVIDENCE receipt.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import pytest

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
    with pytest.raises(ValueError, match="zero-row SUCCESS"):
        emit_catalog_job_receipt(
            store,
            job=job,
            when="2026-08-11T00:00:00+09:00",
            raw_bytes=b"[]",
            rows=[],
            structured_records=[],
            authority=SignedReceiptAuthority(
                signing_key=receipt_ed25519_keys.signing_key
            ),
        )
    rows = read_collection_receipts(store.path, dataset="markets_calendar")
    store.close()
    assert rows == []
