"""Signed receipt-candidate materializer: identities, catalog ownership, clocks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ingestion.jquants.normalize import normalize_generic
from ops.receipt_candidate_materialize import (
    ReceiptCandidateMaterializeError,
    configure_receipt_candidate_limits,
    materialize_receipt_segment,
)
from ops.receipt_product import (
    PRODUCT_ARTIFACT_FIELDS,
    canonical_product_artifact_bytes,
    catalog_owned_product_row_digests,
    measure_owned_product_artifact_body,
    product_artifact_digest,
)
from storage.coverage_ledger import RequiredCoverageSegment
from storage.sqlite_store import SqliteStore
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    reconcile_test_evidence,
)

CHECKED_AT = "2026-08-25T00:00:00+00:00"
OPERATION_ID = "sha256:" + "ab" * 32


def _bar_rows() -> list[dict[str, str]]:
    return normalize_generic(
        [
            {
                "Code": "1301",
                "Date": "2023-01-04",
                "Open": 10.0,
                "High": 11.0,
                "Low": 9.0,
                "Close": 10.0,
                "Volume": 100.0,
                "AdjC": 10.0,
                "MC": 9.5,
                "MAdjC": 9.5,
                "AAdjC": 10.0,
            }
        ],
        dataset="equities_bars_daily",
        ingested_at="2023-01-04T16:00:00+09:00",
        available_at="2023-01-04T16:00:00+09:00",
    )


def _write_collection(path: Path) -> tuple[str, str]:
    body = {
        "schema_version": "jquants-acquisition-collection/v2",
        "capture_mode": "LIVE_SERVICE_BINDING_RESPONSE",
        "initial_request": {"dataset": "equities_bars_daily"},
        "official_calendar_evidence": {
            "raw_path": "x",
            "source_path": "x",
            "raw_size": 1,
            "raw_digest": "sha256:" + "0" * 64,
            "calendar_query_digest": "sha256:" + "0" * 64,
            "business_dates_digest": "sha256:" + "0" * 64,
            "binding_digest": "sha256:" + "0" * 64,
            "business_dates": [],
        },
        "pages": [
            {
                "raw_path": "p",
                "raw_size": 1,
                "raw_digest": "sha256:" + "a" * 64,
                "response_status": 200,
                "headers": {},
                "metadata": {},
            }
        ],
    }
    digest_body = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    collection_digest = "sha256:" + hashlib.sha256(digest_body).hexdigest()
    body["collection_digest"] = collection_digest
    payload = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    path.write_bytes(payload)
    return "sha256:" + hashlib.sha256(payload).hexdigest(), collection_digest


def _signed_bundle(tmp_path: Path, receipt_ed25519_keys, *, raw_bytes_delta: int = 0):
    rows = _bar_rows()
    product_bytes = canonical_product_artifact_bytes(rows)
    product_path = tmp_path / "product.jsonl"
    product_path.write_bytes(product_bytes)
    raw_path = tmp_path / "raw.json"
    file_digest, collection_digest = _write_collection(raw_path)
    raw_page = b'{"data":[{"Code":"1301","Date":"2023-01-04"}]}'
    required = RequiredCoverageSegment(
        source="jquants",
        dataset="equities_bars_daily",
        segment_id="2023-01",
        segment_start="2023-01-01",
        segment_end="2023-01-31",
        expected_scope={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "expected_item_unit": "source_event",
        },
        expected_items=1,
    )
    evidence = reconcile_test_evidence(
        required=required,
        run_id=1,
        raw_pages=[raw_page],
        raw_records=[{"Code": "1301", "Date": "2023-01-04"}],
        structured_records=rows,
        checked_at=CHECKED_AT,
        structured_digest=product_artifact_digest(rows),
        extra_evidence={
            "acquisition_collection_manifest_file_digest": file_digest,
            "acquisition_collection_digest": collection_digest,
        },
        include_master_calendar_digests=False,
        product_artifact_bytes=product_bytes,
    )
    receipt = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    ).issue(evidence)
    claims = evidence.claims
    extras = claims["extra_digests"]
    descriptor = {
        "source": receipt.source,
        "dataset": receipt.dataset,
        "segment_id": receipt.segment_id,
        "operation_id": OPERATION_ID,
        "receipt_digest": receipt.digests["body_digest"],
        "signed_receipt": dict(receipt.digests),
        "product": {
            "artifact_key": claims["artifact_key"],
            "artifact_digest": claims["structured_digest"],
            "byte_count": claims["artifact_byte_count"],
            "row_count": claims["structured_count"],
            "manifest_key": claims["manifest_key"],
            "manifest_digest": extras["product_manifest_digest"],
            "raw_manifest_key": claims["raw_manifest_key"],
            "raw_manifest_digest": claims["raw_manifest_digest"],
            "raw_page_count": claims["raw_page_count"],
            "raw_row_count": claims["raw_count"],
            "raw_bytes": claims["raw_byte_count"] + raw_bytes_delta,
            "committed_at": claims["checked_at"],
        },
    }
    return rows, product_path, raw_path, descriptor, receipt


def test_same_clock_distinct_version_is_not_overwritten(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "clocks.sqlite")
    row = {
        field: value
        for field, value in zip(
            PRODUCT_ARTIFACT_FIELDS,
            [
                "jquants",
                "equities_bars_daily",
                '{"Code":"1301","Date":"2023-01-04"}',
                "2023-01-04T00:00:00+09:00",
                "2023-01-04T16:00:00+09:00",
                "2023-01-04T16:00:00+09:00",
                "{\"Close\":1}",
                "{}",
            ],
        )
    }
    store.apply_exact_product_mirror("jquants_records", [row], commit=True)
    changed = dict(row)
    changed["payload"] = "{\"Close\":2}"
    with pytest.raises(ValueError, match="version identity would be overwritten"):
        store.apply_exact_product_mirror("jquants_records", [changed], commit=True)
    stored = store.fetch_all("jquants_records")
    assert stored[0]["payload"] == row["payload"]
    store.close()


def test_descriptor_raw_bytes_plus_one_rejects_before_persistence(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    _rows, product_path, raw_path, descriptor, _receipt = _signed_bundle(
        tmp_path, receipt_ed25519_keys, raw_bytes_delta=1
    )
    store = SqliteStore(tmp_path / "reject.sqlite")
    configure_receipt_candidate_limits(store, max_database_bytes=5 * 1024 * 1024)
    with pytest.raises(ReceiptCandidateMaterializeError, match="raw_bytes"):
        materialize_receipt_segment(
            store,
            environment="production",
            descriptor=descriptor,
            product_path=product_path,
            raw_path=raw_path,
            calendar_path=None,
            max_database_bytes=5 * 1024 * 1024,
        )
    assert store.count("jquants_records") == 0
    assert store.count("receipt_product_materializations") == 0
    store.close()


def test_genuine_descriptor_persists_text_artifact_and_catalog_detects_corruption(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    rows, product_path, raw_path, descriptor, _receipt = _signed_bundle(
        tmp_path, receipt_ed25519_keys
    )
    store = SqliteStore(tmp_path / "ok.sqlite")
    configure_receipt_candidate_limits(store, max_database_bytes=5 * 1024 * 1024)
    result = materialize_receipt_segment(
        store,
        environment="production",
        descriptor=descriptor,
        product_path=product_path,
        raw_path=raw_path,
        calendar_path=None,
        max_database_bytes=5 * 1024 * 1024,
    )
    store._conn.commit()  # noqa: SLF001
    assert result["dataset"] == "equities_bars_daily"
    stored = store.fetch_all("jquants_records")
    assert len(stored) == 1
    assert stored[0]["available_at"] == rows[0]["available_at"]
    assert stored[0]["ingested_at"] == rows[0]["ingested_at"]
    body = store._conn.execute(  # noqa: SLF001
        "SELECT typeof(artifact_body), artifact_body FROM "
        "receipt_product_materializations"
    ).fetchone()
    assert body[0] == "text"
    assert type(body[1]) is str
    assert body[1].encode("utf-8") == product_path.read_bytes()
    store._conn.execute(  # noqa: SLF001
        "UPDATE jquants_records SET payload='{\"poison\":true}'"
    )
    owned = catalog_owned_product_row_digests(
        store._conn,  # noqa: SLF001
        source="jquants",
        dataset="equities_bars_daily",
        segment_start="2023-01-01",
        segment_end="2023-01-31",
        observed_through=CHECKED_AT,
        tables=("jquants_records", "jquants_records_revisions"),
    )
    with product_path.open("rb") as handle:
        with pytest.raises(ValueError, match="not materialized on the owner connection"):
            measure_owned_product_artifact_body(handle, owned_digests=owned)
    store.close()
