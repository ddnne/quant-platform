"""source_query observed_items come from actual raw counts, never expected.

Empty fetches must not mint Coverage COMPLETE. expected_empty is not
COMPLETE without a trusted EXPECTED_EMPTY_WITH_EVIDENCE receipt.
"""

from __future__ import annotations

import json
import hashlib
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


def test_source_query_empty_fetch_does_not_copy_expected_or_complete(
    tmp_path: Path, receipt_ed25519_keys, monkeypatch
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
    raw_path = tmp_path / "empty.json"
    raw_bytes = b'{"data":[]}'
    from ingestion.common.http import HttpResponse
    from tests.receipt_test_support import open_test_receipt_service

    class _Http:
        name = "test"
        def get(self, url, **_kwargs):
            return HttpResponse(200, {}, raw_bytes, url)

    import ingestion.runtime_authority as runtime

    monkeypatch.setattr(
        runtime, "_utc_now", lambda: "2026-08-11T00:00:00+09:00"
    )
    monkeypatch.setattr(runtime, "_direct_jquants_http", _Http)
    receipt_service = open_test_receipt_service(
        signing_key=receipt_ed25519_keys.signing_key,
        clock=lambda: "2026-08-11T00:00:00+09:00",
    )
    fetch_result = receipt_service.open_jquants_client(
        api_key="test", via_cf_proxy=False
    ).fetch_dataset_evidenced("markets_calendar", **job.params)
    raw_path.write_bytes(raw_bytes)
    raw_path.chmod(0o444)
    manifest_path = tmp_path / "pagination-manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "jquants-pagination-evidence/v1",
        "source": "jquants",
        "dataset": "markets_calendar",
        "base_params": {"from": "2026-08-01", "to": "2026-08-11"},
        "pages": [{
            "index": 0,
            "raw_path": str(raw_path.resolve()),
            "body_digest": "sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
            "request_path": fetch_result.pages[0].request_path,
            "request_params": {"from": "2026-08-01", "to": "2026-08-11"},
            "response_url": "https://api.jquants.com/v2/markets/calendar",
            "response_status": 200,
            "pagination_in": None,
            "pagination_out": None,
        }],
    }, sort_keys=True), encoding="utf-8")
    manifest_path.chmod(0o444)
    persisted_collection = receipt_service.persist_jquants_collection(
        fetch_result=fetch_result,
        raw_paths=(raw_path,),
        manifest_path=manifest_path,
    )
    # v1 persisted pagination evidence is now audit/recovery-only.  The legacy
    # pipeline has no authority-owned transaction/live v2 capture and therefore
    # fails before it can copy expected_items or mint COMPLETE.
    with pytest.raises(TypeError, match="authority-owned ingestion transaction"):
        emit_catalog_job_receipt(
            store,
            job=job,
            collection_context=receipt_service.begin_collection(),
            persisted_collection=persisted_collection,
            receipt_service=receipt_service,
        )
    rows = read_collection_receipts(store.path, dataset="markets_calendar")
    store.close()
    assert rows == []
