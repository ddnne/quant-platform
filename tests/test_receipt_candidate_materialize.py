"""Signed receipt-candidate materializer: identities, catalog ownership, clocks."""

from __future__ import annotations

import calendar
import gzip
import hashlib
import io
import json
import sqlite3
import threading
from dataclasses import asdict
from functools import partial
from pathlib import Path

import pytest
import urllib.request

from ingestion.jquants.normalize import normalize_generic
from ops.receipt_candidate_materialize import (
    ReceiptCandidateMaterializeError,
    commit_receipt_candidate,
    configure_receipt_candidate_limits,
    freeze_receipt_candidate_snapshot,
    hash_receipt_candidate_snapshot,
    materialize_receipt_segment,
    persist_official_calendar_raw,
)
from ops.receipt_product import (
    PRODUCT_ARTIFACT_FIELDS,
    canonical_product_artifact_bytes,
    measure_owned_product_artifact_body,
    measure_product_artifact_jsonl,
    open_stored_product_artifact,
    product_artifact_digest,
)
from core.execution import close_as_of
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    compiled_period_collection_segments,
    coverage_contract_for,
    declared_coverage_segments,
    plan_required_segments,
    record_collection_receipt,
)
from storage.sqlite_store import SqliteStore
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    reconcile_test_evidence,
)

CHECKED_AT = "2026-08-25T00:00:00+00:00"
OPERATION_ID = "sha256:" + "ab" * 32


@pytest.fixture(autouse=True)
def _container_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # These modules live beside the Container entrypoint, not in the wheel.
    # Do not rely on another test module adding this directory during collection.
    monkeypatch.syspath_prepend(str(
        Path(__file__).resolve().parents[1]
        / "platform/workers/research-mass-eval/container"
    ))


def _bar_rows(bar_date: str = "2023-01-04") -> list[dict[str, str]]:
    return normalize_generic(
        [
            {
                "Code": "1301",
                "Date": bar_date,
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
        ingested_at=f"{bar_date}T16:00:00+09:00",
        available_at=f"{bar_date}T16:00:00+09:00",
    )


def _write_collection(
    path: Path,
    *,
    dataset: str = "equities_bars_daily",
    calendar_raw: bytes | None = None,
    calendar_extras: dict[str, str] | None = None,
) -> tuple[str, str]:
    evidence = {
        "raw_path": "x",
        "source_path": "x",
        "raw_size": 1,
        "raw_digest": "sha256:" + "0" * 64,
        "calendar_query_digest": "sha256:" + "0" * 64,
        "business_dates_digest": "sha256:" + "0" * 64,
        "binding_digest": "sha256:" + "0" * 64,
        "business_dates": [],
    }
    if calendar_raw is not None and calendar_extras is not None:
        evidence = {
            "raw_path": "x",
            "source_path": "x",
            "raw_size": len(calendar_raw),
            "raw_digest": calendar_extras["official_calendar_raw_body_digest"],
            "calendar_query_digest": calendar_extras["official_calendar_query_digest"],
            "business_dates_digest": calendar_extras["official_business_dates_digest"],
            "binding_digest": calendar_extras["official_calendar_binding_digest"],
            "business_dates": [],
        }
    body = {
        "schema_version": "jquants-acquisition-collection/v2",
        "capture_mode": "LIVE_SERVICE_BINDING_RESPONSE",
        "initial_request": {"dataset": dataset},
        "official_calendar_evidence": evidence,
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


def _signed_bundle(
    tmp_path: Path,
    receipt_ed25519_keys,
    *,
    raw_bytes_delta: int = 0,
    segment_id: str = "2023-01",
    run_id: int = 1,
    operation_id: str = OPERATION_ID,
    bar_date: str = "2023-01-04",
    dataset: str = "equities_bars_daily",
):
    rows = _bar_rows(bar_date)
    return _signed_dataset_bundle(
        tmp_path,
        receipt_ed25519_keys,
        dataset=dataset,
        segment_id=segment_id,
        source_rows=rows,
        raw_records=[{"Code": "1301", "Date": bar_date}],
        run_id=run_id,
        operation_id=operation_id,
        raw_bytes_delta=raw_bytes_delta,
    )


def _signed_dataset_bundle(
    tmp_path: Path,
    receipt_ed25519_keys,
    *,
    dataset: str,
    segment_id: str,
    source_rows: list,
    raw_records: list,
    run_id: int,
    operation_id: str = OPERATION_ID,
    raw_bytes_delta: int = 0,
    calendar_raw: bytes | None = None,
    calendar_extras: dict[str, str] | None = None,
    required: RequiredCoverageSegment | None = None,
):
    rows = source_rows
    product_bytes = canonical_product_artifact_bytes(rows)
    product_path = tmp_path / f"product-{dataset}-{segment_id}.jsonl"
    product_path.write_bytes(product_bytes)
    raw_path = tmp_path / f"raw-{dataset}-{segment_id}.json"
    file_digest, collection_digest = _write_collection(
        raw_path,
        dataset=dataset,
        calendar_raw=calendar_raw,
        calendar_extras=calendar_extras,
    )
    year, month = segment_id.split("-")
    last_day = calendar.monthrange(int(year), int(month))[1]
    segment_start = f"{year}-{month}-01"
    segment_end = f"{year}-{month}-{last_day:02d}"
    raw_page = json.dumps({"data": raw_records}, separators=(",", ":")).encode()
    extra_evidence = {
        "acquisition_collection_manifest_file_digest": file_digest,
        "acquisition_collection_digest": collection_digest,
    }
    if calendar_extras is not None:
        extra_evidence.update(calendar_extras)
    if required is None:
        planned = plan_required_segments(
            coverage_contract_for(dataset),
            segment_end,
            range_start=segment_start,
        )
        required = next(
            (item for item in planned if item.segment_id == segment_id),
            None,
        )
        if required is None:
            raise AssertionError(f"{dataset}/{segment_id} is not a coverage month")
        required = RequiredCoverageSegment(
            source=required.source,
            dataset=required.dataset,
            segment_id=required.segment_id,
            segment_start=required.segment_start,
            segment_end=required.segment_end,
            expected_scope=dict(required.expected_scope),
            expected_items=len(rows),
        )
    evidence = reconcile_test_evidence(
        required=required,
        run_id=run_id,
        raw_pages=[raw_page],
        raw_records=raw_records,
        structured_records=rows,
        checked_at=CHECKED_AT,
        structured_digest=product_artifact_digest(rows),
        extra_evidence=extra_evidence,
        include_master_calendar_digests=dataset == "equities_master",
        product_artifact_bytes=product_bytes,
    )
    receipt = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    ).issue(evidence)
    claims = evidence.claims
    extras = claims["extra_digests"]
    descriptor = {
        "source": receipt.source,
        "dataset": dataset,
        "segment_id": receipt.segment_id,
        "operation_id": operation_id,
        # Match commitReceipt's full transport identity, not signed-body identity.
        "receipt_digest": "sha256:" + hashlib.sha256(json.dumps(
            asdict(receipt), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest(),
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
        "_product_bytes": product_bytes,
        "_raw_bytes": raw_path.read_bytes(),
        "_calendar_bytes": calendar_raw,
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
    # Cross the parameter chunk boundary and include repeated input keys.
    rows = [row] + [dict(row, natural_key=f"synthetic-{i}") for i in range(200)]
    store.apply_exact_product_mirror("jquants_records", rows, commit=True)
    assert store.apply_exact_product_mirror(
        "jquants_records", rows + rows[:2], commit=True
    ) == 0
    changed = dict(row)
    changed["payload"] = "{\"Close\":2}"
    with pytest.raises(ValueError, match="version identity would be overwritten"):
        store.apply_exact_product_mirror("jquants_records", [changed], commit=True)
    stored = store.fetch_all("jquants_records")
    assert len(stored) == len(rows)
    assert all(item["payload"] == row["payload"] for item in stored)
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


def test_genuine_descriptor_compresses_artifact_and_catalog_detects_corruption(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    rows, product_path, raw_path, descriptor, receipt = _signed_bundle(
        tmp_path, receipt_ed25519_keys
    )
    descriptor["source_cursor"] = {
        "namespace": "receipt_product_publications/v1", "sequence": 7,
    }
    store = SqliteStore(tmp_path / "ok.sqlite")
    configure_receipt_candidate_limits(store, max_database_bytes=5 * 1024 * 1024)
    assert descriptor["receipt_digest"] != receipt.digests["body_digest"]
    with pytest.raises(ReceiptCandidateMaterializeError, match="receipt_digest"):
        materialize_receipt_segment(
            store, environment="production",
            descriptor={**descriptor, "receipt_digest": receipt.digests["body_digest"]},
            product_path=product_path, raw_path=raw_path, calendar_path=None,
            max_database_bytes=5 * 1024 * 1024,
        )
    assert store.count("jquants_records") == 0
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
    assert result["source_cursor"] == descriptor["source_cursor"]
    assert tuple(store._conn.execute(  # noqa: SLF001
        "SELECT namespace,sequence,receipt_digest FROM receipt_candidate_source_cursors"
    ).fetchone()) == (
        "receipt_product_publications/v1", 7, result["receipt_digest"],
    )
    stored = store.fetch_all("jquants_records")
    assert len(stored) == 1
    assert stored[0]["available_at"] == rows[0]["available_at"]
    assert stored[0]["ingested_at"] == rows[0]["ingested_at"]
    conn = store._conn  # noqa: SLF001
    operation_id = str(
        conn.execute(
            "SELECT operation_id FROM receipt_product_materializations"
        ).fetchone()[0]
    )
    with product_path.open("rb") as handle:
        file_measure = measure_product_artifact_jsonl(handle)
    stored_body, signed_bytes = conn.execute(
        "SELECT artifact_body,byte_count FROM receipt_product_materializations "
        "WHERE operation_id=?", (operation_id,),
    ).fetchone()
    assert len(stored_body) < signed_bytes == product_path.stat().st_size
    assert gzip.decompress(stored_body) == product_path.read_bytes()
    with open_stored_product_artifact(conn, operation_id) as first:
        first_measure = measure_product_artifact_jsonl(first)
    with open_stored_product_artifact(conn, operation_id) as second:
        second_measure = measure_product_artifact_jsonl(second)
    assert first_measure == second_measure == file_measure
    conn.execute(
        "UPDATE receipt_product_materializations SET artifact_body=? WHERE operation_id=?",
        (stored_body[:-4], operation_id),
    )
    with pytest.raises(ValueError, match="gzip evidence is corrupt"):
        with open_stored_product_artifact(conn, operation_id) as corrupt:
            measure_product_artifact_jsonl(corrupt)
    conn.execute(
        "UPDATE receipt_product_materializations SET artifact_body=? "
        "WHERE operation_id=?",
        (product_path.read_bytes().decode("utf-8"), operation_id),
    )
    with open_stored_product_artifact(conn, operation_id) as text_body:
        assert measure_product_artifact_jsonl(text_body) == file_measure
    ownership = {
        "conn": store._conn,  # noqa: SLF001
        "source": "jquants",
        "dataset": "equities_bars_daily",
        "segment_start": "2023-01-01",
        "segment_end": "2023-01-31",
        "observed_through": CHECKED_AT,
        "tables": ("jquants_records", "jquants_records_revisions"),
    }
    store._conn.execute("DROP TABLE jquants_records_revisions")  # noqa: SLF001
    with product_path.open("rb") as handle:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            measure_owned_product_artifact_body(handle, **ownership)
    store._conn.execute(  # noqa: SLF001
        "CREATE TABLE jquants_records_revisions AS "
        "SELECT * FROM jquants_records WHERE 0"
    )
    store._conn.execute(  # noqa: SLF001
        "UPDATE jquants_records SET payload='{\"poison\":true}'"
    )
    with product_path.open("rb") as handle:
        with pytest.raises(ValueError, match="not materialized on the owner connection"):
            measure_owned_product_artifact_body(handle, **ownership)
    store.close()


class _Http:
    def __init__(self, body: bytes, headers: dict[str, str], status: int) -> None:
        self._buf = io.BytesIO(body)
        self.headers = headers
        self.status = status
        self.read = self._buf.read

    def __enter__(self) -> "_Http":
        return self

    def __exit__(self, *args: object) -> bool:
        del args
        return False


class _ReceiptTransport:
    def __init__(
        self,
        descriptors: dict[tuple[str, str], dict],
        blobs: dict[str, bytes],
        upload_dir: Path,
    ) -> None:
        self.descriptors = descriptors
        self.blobs = blobs
        self.upload_dir = upload_dir

    def urlopen(self, request: urllib.request.Request, timeout: object = None) -> _Http:
        del timeout
        url = request.full_url
        if request.get_method() == "PUT":
            payload = request.data.read() if hasattr(request.data, "read") else request.data
            gzip_path = self.upload_dir / "candidate.sqlite.gz"
            gzip_path.write_bytes(payload)
            headers = {key.lower(): value for key, value in request.header_items()}
            (self.upload_dir / "put.json").write_text(
                json.dumps(
                    {
                        "url": url,
                        "content_sha256": headers.get("x-content-sha256"),
                        "raw_sha256": headers.get("x-personal-raw-sha256"),
                    }
                ),
                encoding="utf-8",
            )
            return _Http(b'{"ok":true}', {}, 201)
        payload = json.loads(request.data.decode("utf-8"))
        if url.endswith("/v1/describe-receipt-product-input"):
            if "discover" in payload:
                dataset = str(payload["discover"]["dataset"])
                on_or_before = str(payload["discover"]["on_or_before"])
                matches = [
                    key
                    for key in self.descriptors
                    if key[0] == dataset and key[1] <= on_or_before
                ]
                if not matches:
                    missing = json.dumps(
                        {
                            "status": "HOLD",
                            "hold_reason": "MISSING_ROW",
                            "hold_selector": {
                                "dataset": dataset,
                                "segment_id": on_or_before,
                            },
                        }
                    ).encode("utf-8")
                    return _Http(missing, {}, 409)
                latest = max(matches, key=lambda item: item[1])
                raw = dict(self.descriptors[latest])
                raw.pop("_product_bytes", None)
                raw.pop("_raw_bytes", None)
                raw.pop("_calendar_bytes", None)
                rows = [raw]
            else:
                rows = []
                for item in payload["segments"]:
                    key = (item["dataset"], item["segment_id"])
                    if key not in self.descriptors:
                        missing = json.dumps(
                            {
                                "status": "HOLD",
                                "hold_reason": "MISSING_ROW",
                                "hold_selector": {
                                    "dataset": item["dataset"],
                                    "segment_id": item["segment_id"],
                                },
                            }
                        ).encode("utf-8")
                        return _Http(missing, {}, 409)
                    raw = dict(self.descriptors[key])
                    raw.pop("_product_bytes", None)
                    raw.pop("_raw_bytes", None)
                    raw.pop("_calendar_bytes", None)
                    rows.append(raw)
            body = json.dumps(
                {
                    "schema_version": "receipt-product-input-set/v1",
                    "status": "DESCRIBED",
                    "environment": "production",
                    "segments": rows,
                }
            ).encode("utf-8")
            return _Http(body, {}, 200)
        resource = str(payload["resource"])
        dataset = str(payload.get("dataset") or "")
        segment_id = str(payload.get("segment_id") or "")
        descriptor = self.descriptors.get((dataset, segment_id), {})
        if resource == "product_artifact" and descriptor.get("_product_bytes"):
            blob = descriptor["_product_bytes"]
        elif resource == "raw_collection_manifest" and descriptor.get("_raw_bytes"):
            blob = descriptor["_raw_bytes"]
        elif resource == "official_calendar_raw" and descriptor.get("_calendar_bytes"):
            blob = descriptor["_calendar_bytes"]
        else:
            blob = self.blobs[resource]
        headers = {
            "x-quant-resource": resource,
            "x-quant-receipt-digest": payload["receipt_digest"],
        }
        return _Http(blob, headers, 200)


def _posted(*, path: str, body: bytes, manager: object):
    from test_cloud_personal_research_container import service

    handler = object.__new__(service.PersonalResearchHandler)
    handler.path = path
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.headers = {"content-length": str(len(body))}
    handler.request_version = "HTTP/1.0"
    handler.close_connection = False
    handler.manager = manager
    handler.status = 0
    handler.send_response = lambda code, message=None: setattr(handler, "status", code)
    handler.send_header = lambda *args, **kwargs: None
    handler.end_headers = lambda *args, **kwargs: None
    handler.log_message = lambda *args, **kwargs: None
    handler.do_POST()
    return handler


def _worker_document(job_id: str) -> dict[str, object]:
    from test_cloud_personal_research_container import service
    from receipt_candidate_job import RECEIPT_CANDIDATE_FORMAT, _closed_pins

    pins = _closed_pins()
    digest_body = {
        "dependency_closure_digest": pins["dependency_closure_digest"],
        "format": RECEIPT_CANDIDATE_FORMAT,
        "job_id": job_id,
        "profile_digest": pins["profile_digest"],
        "profile_id": pins["profile_id"],
        "runner_version": service.RUNNER_VERSION,
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(
            digest_body, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        **digest_body,
        "deployment_id": "test-deploy",
        "environment": "production",
        "manifest_key": f"research/receipt-candidates/job={job_id}/manifest.json",
        "max_database_bytes": service.SNAPSHOT_MAX_DATABASE_BYTES,
        "request_digest": digest,
    }


def _compiled_descriptor_map() -> dict[tuple[str, str], dict[str, str]]:
    from receipt_candidate_job import compiled_candidate_selectors

    mapped: dict[tuple[str, str], dict[str, str]] = {}
    for selector in compiled_candidate_selectors():
        digest = "sha256:" + hashlib.sha256(
            f"{selector['dataset']}:{selector['segment_id']}".encode()
        ).hexdigest()
        mapped[(selector["dataset"], selector["segment_id"])] = {
            **selector,
            "operation_id": digest,
            "receipt_digest": digest,
        }
    return mapped


def _skip_materialize(store, **kwargs):
    del store
    item = kwargs["descriptor"]
    return {
        "dataset": item["dataset"],
        "segment_id": item["segment_id"],
        "receipt_digest": item["receipt_digest"],
    }


def _patch_mini_period(monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    from tests.test_ready_policy_fail_closed import _mini_exact_scope_binding

    binding = _mini_exact_scope_binding()
    monkeypatch.setattr(
        "research.ready_manifest.load_exact_four_pilot_ready_binding",
        lambda root=None: binding,
    )
    return tuple(str(item) for item in binding.required_datasets)


def _normalize_builder_rows(dataset: str, raw_rows: list[dict]) -> list[dict]:
    structured: list[dict] = []
    if dataset == "equities_bars_daily":
        for row in raw_rows:
            day = str(row["Date"])
            structured.extend(
                normalize_generic(
                    [row], dataset=dataset, ingested_at=close_as_of(day)
                )
            )
    elif dataset == "equities_master":
        for row in raw_rows:
            stamp = "2026-08-24T08:00:00+09:00"
            structured.extend(
                normalize_generic(
                    [row],
                    dataset=dataset,
                    ingested_at=stamp,
                    available_at=stamp,
                )
            )
    elif dataset == "fins_summary":
        for row in raw_rows:
            disc = str(row["DiscDate"])
            structured.extend(
                normalize_generic(
                    [row],
                    dataset=dataset,
                    ingested_at=f"{disc}T08:00:00+09:00",
                )
            )
    elif dataset == "markets_calendar":
        structured.extend(
            normalize_generic(
                raw_rows,
                dataset=dataset,
                ingested_at="2023-01-04T00:00:00+09:00",
            )
        )
    else:
        structured.extend(
            normalize_generic(
                raw_rows,
                dataset=dataset,
                ingested_at="2023-01-06T16:00:00+09:00",
            )
        )
    return structured


def _mini_builder_payloads(
    *,
    code_1332_bar_dates: tuple[str, ...] | None = None,
) -> dict[str, list[dict]]:
    from tests.test_ready_policy_fail_closed import (
        FIRST_DECISION_PRIOR_BAR_DATES,
        _daily_equity_bar,
    )

    calendar_dates = ["2023-01-04", "2023-01-05", "2023-01-06"]
    if code_1332_bar_dates is None:
        code_1332_bar_dates = tuple(
            dict.fromkeys((*FIRST_DECISION_PRIOR_BAR_DATES, *calendar_dates))
        )
    return {
        "markets_calendar": [
            {"Date": day, "HolidayDivision": "1"} for day in calendar_dates
        ],
        "equities_master": [
            {
                "Code": "1332",
                "Date": day,
                "CompanyName": "Prime With Fins",
                "MarketCode": "0111",
            }
            for day in ("2022-10-03", "2023-01-04", "2023-01-05", "2023-01-06")
        ],
        "fins_summary": [
            {
                "Code": "1332",
                "DiscDate": "2022-10-20",
                "DiscTime": "08:00:00",
                "DiscNo": "disc-1332-bps",
                "BPS": 80.0,
                "CurPerEn": "2022-10-20",
            },
            {
                "Code": "1332",
                "DiscDate": "2023-01-03",
                "DiscTime": "08:00:00",
                "DiscNo": "disc-1332",
            },
            {
                "Code": "1332",
                "DiscDate": "2023-01-05",
                "DiscTime": "08:00:00",
                "DiscNo": "disc-1332-eps",
                "EPS": 5.0,
                "CurPerEn": "2023-03-31",
            },
            {
                "Code": "9999",
                "DiscDate": "2022-11-15",
                "DiscTime": "08:00:00",
                "DiscNo": "disc-9999-nov",
                "EPS": 1.0,
            },
            {
                "Code": "9999",
                "DiscDate": "2022-12-15",
                "DiscTime": "08:00:00",
                "DiscNo": "disc-9999-dec",
                "EPS": 1.0,
            },
        ],
        "equities_bars_daily": [
            _daily_equity_bar(
                "1332", day, close=100.0, morning=99.5, volume=1000.0
            )
            for day in code_1332_bar_dates
        ]
        + [
            _daily_equity_bar(
                "9999", "2022-09-15", close=100.0, morning=99.5, volume=1000.0
            ),
            _daily_equity_bar(
                "9999", "2022-10-21", close=100.0, morning=99.5, volume=1000.0
            ),
            _daily_equity_bar(
                "9999", "2022-11-15", close=100.0, morning=99.5, volume=1000.0
            ),
        ],
        "indices_bars_daily_topix": [
            {
                "Date": day,
                "Open": 1900.0,
                "High": 1910.0,
                "Low": 1890.0,
                "Close": 1900.0,
            }
            for day in calendar_dates
        ],
    }


def _mini_builder_descriptors(
    tmp_path: Path,
    receipt_ed25519_keys,
    *,
    payloads: dict[str, list[dict]] | None = None,
) -> dict[tuple[str, str], dict]:
    from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
    from pit.scoped_selection import split_safety_interval_start
    from tests.test_ready_policy_fail_closed import _scope_calendar_extras

    payloads = _mini_builder_payloads() if payloads is None else payloads
    planned = declared_coverage_segments(
        EXACT_FOUR_DATASET_IDS,
        lookback_start="2023-01-04",
        period_start="2023-01-04",
        period_end="2023-01-06",
        selected_event_dates={
            "fins_summary": frozenset(
                {"2022-10-20", "2023-01-03", "2023-01-05"}
            ),
            "equities_master": frozenset(
                {"2022-10-03", "2023-01-04", "2023-01-05", "2023-01-06"}
            ),
            "equities_bars_daily": frozenset({"2022-09-15", "2023-01-05"}),
        },
        bar_split_interval_start=split_safety_interval_start("2022-10-20"),
    )
    descriptors: dict[tuple[str, str], dict] = {}
    for run_id, segment in enumerate(planned, start=1):
        month_rows = [
            row
            for row in payloads[segment.dataset]
            if segment.segment_start
            <= _row_event_day(segment.dataset, row)
            <= segment.segment_end
        ]
        if not month_rows:
            raise AssertionError(
                f"{segment.dataset}/{segment.segment_id} has no fixture rows"
            )
        structured = _normalize_builder_rows(segment.dataset, month_rows)
        calendar_raw = None
        calendar_extras = None
        if segment.dataset == "equities_master":
            calendar_raw = _canonical_month_calendar_raw(
                start=segment.segment_start,
                end=segment.segment_end,
            )
            calendar_extras = _scope_calendar_extras(
                calendar_raw,
                start=segment.segment_start,
                end=segment.segment_end,
            )
        dest = tmp_path / f"{segment.dataset}-{segment.segment_id}"
        dest.mkdir()
        _rows, _product, _raw, descriptor, _receipt = _signed_dataset_bundle(
            dest,
            receipt_ed25519_keys,
            dataset=segment.dataset,
            segment_id=segment.segment_id,
            source_rows=structured,
            raw_records=month_rows,
            run_id=run_id,
            operation_id="sha256:"
            + hashlib.sha256(
                f"{segment.dataset}:{segment.segment_id}".encode()
            ).hexdigest(),
            calendar_raw=calendar_raw,
            calendar_extras=calendar_extras,
            required=segment,
        )
        descriptors[(segment.dataset, segment.segment_id)] = descriptor
    return descriptors


def _row_event_day(dataset: str, row: dict) -> str:
    if dataset == "fins_summary":
        return str(row["DiscDate"])[:10]
    return str(row["Date"])[:10]


def test_http_job_and_execute_publish_compact_completed_terminal(
    tmp_path: Path, receipt_ed25519_keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_runtime.ready_publication import canonical_digest
    from receipt_candidate_job import (
        RECEIPT_CANDIDATE_FORMAT,
        ReceiptCandidateJobSpec,
        compiled_candidate_selectors,
        execute_receipt_candidate_job,
    )

    monkeypatch.setattr(
        "receipt_candidate_job._profile_period",
        lambda: ("2023-01-04", "2023-01-06", ("equities_bars_daily",)),
    )
    descriptors: dict[tuple[str, str], dict] = {}
    _rows, product_path, raw_path, descriptor, _receipt = _signed_bundle(
        tmp_path,
        receipt_ed25519_keys,
        dataset="equities_bars_daily",
        segment_id="2023-01",
    )
    descriptors[("equities_bars_daily", "2023-01")] = descriptor
    product_blob = product_path.read_bytes()
    raw_blob = raw_path.read_bytes()
    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    pred_rows, pred_product, pred_raw, pred_desc, _pred = _signed_bundle(
        pred_dir,
        receipt_ed25519_keys,
        dataset="equities_bars_daily",
        segment_id="2022-09",
        bar_date="2022-09-15",
        run_id=90,
        operation_id="a" * 32,
    )
    del pred_rows
    descriptors[("equities_bars_daily", "2022-09")] = pred_desc
    document = _worker_document("cand-exec-1")
    spec = ReceiptCandidateJobSpec.from_document(document)
    assert ("equities_bars_daily", "2023-01") in {
        (item["dataset"], item["segment_id"])
        for item in compiled_candidate_selectors()
    }
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    transport = _ReceiptTransport(
        descriptors,
        {
            "product_artifact": product_blob or pred_product.read_bytes(),
            "raw_collection_manifest": raw_blob or pred_raw.read_bytes(),
            "official_calendar_raw": b"z",
        },
        uploads,
    )
    stored: dict[str, dict] = {}

    def publish(key, data, *, spec, content_digest, extra_headers=None):
        del spec
        payload = data.read_bytes() if hasattr(data, "read_bytes") else data
        if str(key).endswith(".json"):
            stored[key] = json.loads(payload)
        elif str(key).endswith(".sqlite.gz"):
            gzip_path = uploads / "candidate.sqlite.gz"
            gzip_path.write_bytes(payload)
            (uploads / "put.json").write_text(
                json.dumps(
                    {
                        "url": str(key),
                        "content_sha256": content_digest,
                        "raw_sha256": extra_headers.get("x-personal-raw-sha256")
                        if extra_headers
                        else None,
                    }
                ),
                encoding="utf-8",
            )

    work = tmp_path / "work"
    work.mkdir()
    encoded = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    posted = _posted(
        path="/v1/materialize-receipt-candidate",
        body=encoded,
        manager=type("M", (), {"submit": lambda self, item: {
            "job_id": item.job_id,
            "request_digest": item.request_digest,
            "status": "QUEUED",
            "job_kind": "receipt-candidate",
            "go": False,
        }})(),
    )
    assert posted.status == 202
    terminal = execute_receipt_candidate_job(
        spec, work_root=work, uploader=publish, opener=transport
    )
    assert terminal["status"] == "COMPLETED", terminal.get("error")
    assert terminal["format"] == RECEIPT_CANDIDATE_FORMAT
    assert terminal["pending_ready"] is True
    assert terminal["ready"] is False
    assert terminal["go"] is False
    assert terminal["compiled_scope_status"] == "FAIL"
    assert terminal["compiled_scope_kind"] == (
        "receipt-candidate-scope-diagnostic/v1"
    )
    assert terminal["snapshot_b0_status"] == "FAIL"
    assert canonical_digest(terminal["snapshot_quality"]) == (
        terminal["snapshot_quality_digest"]
    )
    assert "observation_checked_at" not in terminal
    assert "source_generation" not in terminal
    assert "materialized_segments" not in terminal
    assert terminal["segment_count"] >= 1
    gzip_path = uploads / "candidate.sqlite.gz"
    put = json.loads((uploads / "put.json").read_text(encoding="utf-8"))
    gzip_bytes = gzip_path.read_bytes()
    raw_bytes = gzip.decompress(gzip_bytes)
    assert put["url"].endswith(".sqlite.gz")
    assert put["content_sha256"] == "sha256:" + hashlib.sha256(gzip_bytes).hexdigest()
    assert put["raw_sha256"] == "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    assert terminal["gzip_sha256"] == put["content_sha256"]
    assert terminal["raw_sha256"] == put["raw_sha256"]
    assert list(work.glob("receipt-candidate-*")) == []


def test_execute_compiled_selectors_keeps_compact_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_mini_period(monkeypatch)
    from receipt_candidate_job import (
        RECEIPT_CANDIDATE_MAX_REQUEST_BYTES,
        RECEIPT_CANDIDATE_MAX_SEGMENTS,
        ReceiptCandidateJobSpec,
        compiled_candidate_selectors,
        execute_receipt_candidate_job,
    )

    selectors = compiled_candidate_selectors()
    assert 1 <= len(selectors) <= RECEIPT_CANDIDATE_MAX_SEGMENTS
    document = _worker_document("cand-compiled")
    encoded = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert len(encoded) <= RECEIPT_CANDIDATE_MAX_REQUEST_BYTES
    transport = _ReceiptTransport(
        _compiled_descriptor_map(),
        {
            "product_artifact": b"x",
            "raw_collection_manifest": b"y",
            "official_calendar_raw": b"z",
        },
        tmp_path,
    )
    monkeypatch.setattr(
        "receipt_candidate_job.materialize_receipt_segment", _skip_materialize
    )

    class _SyncSubmit:
        terminal: dict | None = None
        spec: object | None = None

        def submit(self, item: object) -> dict[str, object]:
            self.spec = item
            self.terminal = execute_receipt_candidate_job(
                item,
                work_root=tmp_path,
                uploader=lambda *args, **kwargs: None,
                opener=transport,
            )
            return {
                "job_id": item.job_id,
                "request_digest": item.request_digest,
                "status": "QUEUED",
                "job_kind": "receipt-candidate",
                "go": False,
            }

    adapter = _SyncSubmit()
    posted = _posted(
        path="/v1/materialize-receipt-candidate",
        body=encoded,
        manager=adapter,
    )
    assert posted.status == 202
    assert isinstance(adapter.spec, ReceiptCandidateJobSpec)
    terminal = adapter.terminal
    assert terminal is not None
    assert terminal["status"] == "COMPLETED"
    assert terminal["segment_count"] == len(selectors)
    assert "materialized_segments" not in terminal
    assert terminal["ready"] is False
    assert terminal["go"] is False
    assert terminal["compiled_scope_status"] == "FAIL"
    assert terminal["compiled_scope_kind"] == (
        "receipt-candidate-scope-diagnostic/v1"
    )
    assert terminal["snapshot_b0_status"] == "FAIL"
    assert terminal["snapshot_quality_digest"].startswith("sha256:")
    assert "observation_checked_at" not in terminal
    assert "physical_key" not in terminal
    assert "dependency_scope_key" not in terminal
    assert len(
        json.dumps(terminal, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ) < 64 * 1024


def test_compiled_candidate_missing_required_segment_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_mini_period(monkeypatch)
    from receipt_candidate_job import (
        ReceiptCandidateJobSpec,
        execute_receipt_candidate_job,
    )

    mapped = _compiled_descriptor_map()
    mapped.pop(next(iter(mapped)))
    spec = ReceiptCandidateJobSpec.from_document(_worker_document("cand-missing"))
    transport = _ReceiptTransport(
        mapped,
        {
            "product_artifact": b"x",
            "raw_collection_manifest": b"y",
            "official_calendar_raw": b"z",
        },
        tmp_path,
    )
    monkeypatch.setattr(
        "receipt_candidate_job.materialize_receipt_segment", _skip_materialize
    )
    failed = execute_receipt_candidate_job(
        spec, work_root=tmp_path, uploader=lambda *args, **kwargs: None, opener=transport
    )
    assert failed["status"] == "FAILED"
    assert "physical_key" not in failed


def test_execute_pass_streams_closed_sqlite_before_gzip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_runtime.ready_publication import canonical_digest
    from receipt_candidate_job import ReceiptCandidateJobSpec, execute_receipt_candidate_job

    _patch_mini_period(monkeypatch)
    spec = ReceiptCandidateJobSpec.from_document(
        _worker_document("cand-phys-1")
    )
    transport = _ReceiptTransport(
        _compiled_descriptor_map(),
        {
            "product_artifact": b"x",
            "raw_collection_manifest": b"y",
            "official_calendar_raw": b"z",
        },
        tmp_path,
    )
    monkeypatch.setattr(
        "receipt_candidate_job.materialize_receipt_segment",
        lambda store, **kwargs: {
            "dataset": kwargs["descriptor"]["dataset"],
            "segment_id": kwargs["descriptor"]["segment_id"],
            "receipt_digest": kwargs["descriptor"]["receipt_digest"],
        },
    )

    def _pass_scope(store, **kwargs):
        del kwargs
        freeze_receipt_candidate_snapshot(store)
        physical = hash_receipt_candidate_snapshot(store)
        evidence_body = {
            "format": "pit-dependency-scope-proof/v1",
            "status": "PASS",
            "physical_db_digest": physical,
        }
        return {
            "compiled_scope_status": "PASS",
            "compiled_scope_kind": "receipt-candidate-scope-diagnostic/v1",
            "observation_policy": "max_verified_claims_checked_at",
            "observation_checked_at": "2026-08-25T00:00:00+00:00",
            "compiled_scope_proof_digest": canonical_digest(evidence_body),
            "physical_db_digest": physical,
            "receipt_source": {
                "kind": "governed-receipt-candidate",
                "receipt_runset_digest": physical,
            },
            "receipt_native_manifest": {"format": "ready-manifest/v2"},
            "receipt_native_manifest_digest": physical,
            "_receipt_scope_evidence_body": evidence_body,
        }

    monkeypatch.setattr(
        "paper_runtime.ready_publication.verify_committed_receipt_candidate_scope",
        _pass_scope,
    )
    puts: list[dict[str, object]] = []

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del spec
        headers = dict(extra_headers or {})
        puts.append(
            {
                "key": key,
                "digest": content_digest,
                "content_type": headers.get("content-type"),
                "raw": headers.get("x-personal-raw-sha256"),
                "size": data.stat().st_size if isinstance(data, Path) else len(data),
                "payload": data if isinstance(data, (bytes, bytearray)) else None,
            }
        )

    terminal = execute_receipt_candidate_job(
        spec, work_root=tmp_path, uploader=uploader, opener=transport
    )
    assert terminal["status"] == "COMPLETED"
    assert terminal["compiled_scope_status"] == "PASS"
    assert terminal["pending_ready"] is True
    assert terminal["ready"] is False
    assert terminal["go"] is False
    assert [item["key"] for item in puts] == [
        terminal["dependency_scope_key"],
        terminal["physical_key"],
        terminal["snapshot_key"],
    ]
    sidecar = puts[0]
    assert isinstance(sidecar["payload"], (bytes, bytearray))
    uploaded = json.loads(sidecar["payload"])
    assert "proof_digest" not in uploaded
    assert sidecar["digest"] == terminal["compiled_scope_proof_digest"]
    assert (
        "sha256:" + hashlib.sha256(sidecar["payload"]).hexdigest()
        == terminal["compiled_scope_proof_digest"]
    )
    assert uploaded["physical_db_digest"] == terminal["raw_sha256"]
    assert sidecar["raw"] == terminal["raw_sha256"]
    assert sidecar["content_type"] == "application/json; charset=utf-8"
    assert str(terminal["physical_key"]).endswith(".sqlite")
    assert not str(terminal["physical_key"]).endswith(".gz")
    assert puts[1]["digest"] == terminal["raw_sha256"]
    assert puts[1]["content_type"] == "application/vnd.sqlite3"
    assert puts[2]["digest"] == terminal["gzip_sha256"]

    def boom(key, data, *, spec, content_digest, extra_headers=None):
        del data, spec, content_digest, extra_headers
        if str(key).endswith(".pit-dependency-scope.json"):
            raise RuntimeError("R2 upload returned 502")

    failed = execute_receipt_candidate_job(
        spec, work_root=tmp_path, uploader=boom, opener=transport
    )
    assert failed["status"] == "FAILED"
    assert "physical_key" not in failed
    assert "dependency_scope_key" not in failed
    assert "snapshot_key" not in failed


def test_discover_latest_complete_preserves_service_failure_and_rejects_mismatch() -> None:
    from receipt_product_byte_client import (
        ReceiptProductTransportError,
        discover_latest_complete_segment,
    )

    class _Opener:
        def __init__(self, status: int, body: dict) -> None:
            self.status = status
            self.body = body

        def urlopen(self, request, timeout=None):
            del request, timeout
            return _Http(
                json.dumps(self.body).encode("utf-8"),
                {},
                self.status,
            )

    pins = {
        "profile_id": "controlled-pilot/exact-four",
        "profile_digest": "sha256:" + "11" * 32,
        "dependency_closure_digest": "sha256:" + "22" * 32,
        "dataset": "fins_summary",
        "on_or_before": "2022-12",
    }
    none_match = discover_latest_complete_segment(
        **pins,
        opener=_Opener(
            409,
            {
                "status": "HOLD",
                "hold_reason": "MISSING_ROW",
                "hold_selector": {
                    "dataset": "fins_summary",
                    "segment_id": "2022-12",
                },
            },
        ),
    )
    assert none_match is None
    with pytest.raises(ReceiptProductTransportError):
        discover_latest_complete_segment(
            **pins,
            opener=_Opener(500, {"status": "HOLD", "hold_reason": "READ_FAILURE"}),
        )
    with pytest.raises(ReceiptProductTransportError):
        discover_latest_complete_segment(
            **pins,
            opener=_Opener(
                409,
                {
                    "status": "HOLD",
                    "hold_reason": "UNTRUSTED_CHAIN",
                    "hold_selector": {
                        "dataset": "fins_summary",
                        "segment_id": "2022-12",
                    },
                },
            ),
        )
    with pytest.raises(ReceiptProductTransportError):
        discover_latest_complete_segment(
            **pins,
            opener=_Opener(
                200,
                {
                    "schema_version": "receipt-product-input-set/v1",
                    "status": "DESCRIBED",
                    "segments": [
                        {"dataset": "equities_master", "segment_id": "2022-11"}
                    ],
                },
            ),
        )


def test_execute_builder_compiled_scope_pass_and_missing_required_month(
    tmp_path: Path, receipt_ed25519_keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research.ready_manifest import is_sha256_digest
    from receipt_candidate_job import (
        ReceiptCandidateJobSpec,
        execute_receipt_candidate_job,
    )

    _patch_mini_period(monkeypatch)
    descriptors = _mini_builder_descriptors(tmp_path, receipt_ed25519_keys)
    spec = ReceiptCandidateJobSpec.from_document(_worker_document("cand-scope-pass"))
    transport = _ReceiptTransport(
        descriptors,
        {
            "product_artifact": b"x",
            "raw_collection_manifest": b"y",
            "official_calendar_raw": b"z",
        },
        tmp_path,
    )
    puts: list[str] = []

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del data, spec, content_digest, extra_headers
        puts.append(str(key))

    pass_root = tmp_path / "pass"
    pass_root.mkdir()
    proved = execute_receipt_candidate_job(
        spec,
        work_root=pass_root,
        uploader=uploader,
        opener=transport,
    )
    assert proved["status"] == "COMPLETED", proved.get("error")
    assert proved["compiled_scope_status"] == "PASS"
    assert proved["ready"] is False
    assert proved["go"] is False
    body = proved["receipt_native_manifest"]
    assert is_sha256_digest(body["coverage_proof_digest"]), proved.get(
        "coverage_proof_reason"
    )
    assert is_sha256_digest(body["raw_proof_digest"])
    assert is_sha256_digest(body["receipt_proof_digest"])
    assert "coverage_proof_reason" not in proved
    assert ("equities_bars_daily", "2022-09") in descriptors
    assert ("fins_summary", "2022-11") in descriptors
    first_as_of_bars = [
        row["Date"]
        for row in _mini_builder_payloads()["equities_bars_daily"]
        if row["Code"] == "1332" and row["Date"] <= "2023-01-04"
    ]
    assert len(first_as_of_bars) >= 11
    assert any(str(key).endswith(".sqlite") for key in puts)

    missing_map = dict(descriptors)
    missing_map.pop(("fins_summary", "2022-11"))
    missing_spec = ReceiptCandidateJobSpec.from_document(
        _worker_document("cand-scope-missing-month")
    )
    missing_transport = _ReceiptTransport(
        missing_map,
        {
            "product_artifact": b"x",
            "raw_collection_manifest": b"y",
            "official_calendar_raw": b"z",
        },
        tmp_path,
    )
    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    missing = execute_receipt_candidate_job(
        missing_spec,
        work_root=missing_root,
        uploader=lambda *args, **kwargs: None,
        opener=missing_transport,
    )
    assert missing["status"] == "FAILED", missing
    assert "physical_key" not in missing
    assert missing.get("compiled_scope_status") != "PASS"


def test_execute_builder_insufficient_code_history_is_not_compiled_pass(
    tmp_path: Path, receipt_ed25519_keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from receipt_candidate_job import (
        ReceiptCandidateJobSpec,
        execute_receipt_candidate_job,
    )

    _patch_mini_period(monkeypatch)
    descriptors = _mini_builder_descriptors(
        tmp_path,
        receipt_ed25519_keys,
        payloads=_mini_builder_payloads(
            code_1332_bar_dates=(
                "2022-12-15",
                "2023-01-04",
                "2023-01-05",
                "2023-01-06",
            )
        ),
    )
    spec = ReceiptCandidateJobSpec.from_document(
        _worker_document("cand-scope-short-history")
    )
    work = tmp_path / "short"
    work.mkdir()
    terminal = execute_receipt_candidate_job(
        spec,
        work_root=work,
        uploader=lambda *args, **kwargs: None,
        opener=_ReceiptTransport(
            descriptors,
            {
                "product_artifact": b"x",
                "raw_collection_manifest": b"y",
                "official_calendar_raw": b"z",
            },
            tmp_path,
        ),
    )
    assert terminal.get("compiled_scope_status") != "PASS"
    assert "physical_key" not in terminal
    assert terminal["status"] in {"COMPLETED", "FAILED"}


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_committed_candidate_scope_pass_ignores_unsigned_later_receipt(
    tmp_path: Path, receipt_ed25519_keys, environment: str
) -> None:
    from paper_runtime.ready_publication import (
        RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND,
        verify_committed_receipt_candidate_scope,
    )
    from paper_runtime.ready_publication import canonical_digest
    from research.ready_manifest import (
        MISSING,
        READY_MANIFEST_V2_FORMAT,
        ReadyManifest,
        build_receipt_native_ready_manifest,
    )
    from research.universe_contract import ResolvedUniverseMembership
    from tests.test_ready_policy_fail_closed import _seed_exact_pit_scope

    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys, environment=environment
    )
    store = SqliteStore(db_path)
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO collection_receipts ("
        "source,dataset,segment_id,segment_start,segment_end,expected_scope,"
        "expected_items,observed_items,raw_page_count,raw_row_count,"
        "structured_row_count,pagination_exhausted,digests_json,run_id,"
        "status,error,checked_at"
        ") VALUES ("
        "'jquants','equities_bars_daily','unsigned-later',"
        "'2023-01-01','2023-01-31','{}',0,0,0,0,0,1,'{}',999,"
        "'SUCCESS',NULL,'2099-01-01T00:00:00+00:00'"
        ")"
    )
    commit_receipt_candidate(store)
    result = verify_committed_receipt_candidate_scope(
        store,
        binding=binding,
        environment=environment,
    )
    assert result["compiled_scope_status"] == "PASS"
    assert result["compiled_scope_kind"] == RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND
    assert result["observation_policy"] == "max_verified_claims_checked_at"
    assert result["observation_checked_at"] == "2026-08-25T00:00:00+00:00"
    assert result["physical_db_digest"] == hash_receipt_candidate_snapshot(store)
    assert "source_generation" not in result
    assert "exported_at" not in result
    source = result["receipt_source"]
    assert source["kind"] == "governed-receipt-candidate"
    assert source["environment"] == environment
    assert source["physical_digest"] == result["physical_db_digest"]
    assert source["observed_through"] == "2026-08-25T00:00:00+00:00"
    assert source["receipt_runset_digest"].startswith("sha256:")
    assert result["snapshot_b0_status"] == "FAIL"
    assert result["snapshot_b4_status"] == "PASS"
    assert result["snapshot_c8_status"] == "PASS"
    quality = result["snapshot_quality"]
    assert quality["kind"] == "receipt-candidate-snapshot-quality/v1"
    assert quality["physical_digest"] == result["physical_db_digest"]
    assert canonical_digest(quality) == result["snapshot_quality_digest"]
    proof_context = {
        "physical_digest": quality["physical_digest"],
        "profile_digest": quality["profile_digest"],
        "plan_set_digest": quality["plan_set_digest"],
        "dependency_closure_digest": quality["dependency_closure_digest"],
        "receipt_runset_digest": quality["receipt_runset_digest"],
        "period_start": quality["period_start"],
        "period_end": quality["period_end"],
        "observation_policy": quality["observation_policy"],
        "observed_through": quality["observed_through"],
    }
    assert result["b0_proof_digest"] == canonical_digest(
        {**proof_context, "b0": quality["b0"]}
    )
    assert result["b4_proof_digest"] == canonical_digest(
        {**proof_context, "b4": quality["b4"]}
    )
    assert result["validation_proof_digest"] == result["snapshot_quality_digest"]
    evidence_body = result["_receipt_scope_evidence_body"]
    assert "proof_digest" not in evidence_body
    assert evidence_body["format"] == "pit-dependency-scope-proof/v1"
    assert evidence_body["physical_db_digest"] == result["physical_db_digest"]
    assert evidence_body["profile_digest"] == binding.profile_digest
    assert canonical_digest(evidence_body) == result["compiled_scope_proof_digest"]
    first_feature_dependencies = binding.profiles[0].to_dict()[
        "feature_dependencies"
    ]
    first_feature_digests = {
        canonical_digest(dict(item)) for item in first_feature_dependencies
    }
    assert any(
        canonical_digest(dict(item)) not in first_feature_digests
        for item in binding.feature_dependencies
    )
    expected_feature_generation = canonical_digest(
        {
            "profile_digest": binding.profile_digest,
            "feature_dependencies": binding.feature_dependencies,
        }
    )
    expected_catalog_generation = canonical_digest(
        {
            "profile_digest": binding.profile_digest,
            "contract_versions": binding.contract_versions,
            "dataset_ids": binding.required_datasets,
        }
    )
    assert expected_feature_generation != canonical_digest(
        {
            "profile_digest": binding.profile_digest,
            "feature_dependencies": first_feature_dependencies,
        }
    )
    expected_resolved_universe_digest = ResolvedUniverseMembership(
        period_start="2023-01-04",
        period_end="2023-01-06",
        decision_memberships=tuple(
            (day, ("1332",))
            for day in ("2023-01-04", "2023-01-05", "2023-01-06")
        ),
    ).resolved_membership_digest
    observed = result["receipt_native_manifest"]
    assert observed["resolved_universe_digest"] == (
        expected_resolved_universe_digest
    )
    assert observed["feature_generation"] == expected_feature_generation
    assert observed["catalog_generation"] == expected_catalog_generation
    assert observed["coverage_proof_digest"] == MISSING
    assert "equities_bars_daily/2022-09" in str(
        result.get("coverage_proof_reason")
    )
    assert observed["raw_proof_digest"].startswith("sha256:")
    assert observed["receipt_proof_digest"].startswith("sha256:")
    assert observed["raw_proof_digest"] != source["receipt_runset_digest"]
    assert observed["receipt_proof_digest"] != result["compiled_scope_proof_digest"]
    assert hash_receipt_candidate_snapshot(store) == result["physical_db_digest"]
    manifest = build_receipt_native_ready_manifest(
        source,
        binding=binding,
        created_at="MISSING",
        published_at="MISSING",
        b0_proof_digest=result["b0_proof_digest"],
        b4_proof_digest=result["b4_proof_digest"],
        validation_proof_digest=result["validation_proof_digest"],
        resolved_universe_digest=expected_resolved_universe_digest,
        feature_generation=expected_feature_generation,
        catalog_generation=expected_catalog_generation,
        coverage_proof_digest=MISSING,
        raw_proof_digest=observed["raw_proof_digest"],
        receipt_proof_digest=observed["receipt_proof_digest"],
    )
    body = manifest.to_dict()
    assert result["receipt_native_manifest_digest"] == body["manifest_digest"]
    assert result["receipt_native_manifest"] == body
    assert body["format"] == READY_MANIFEST_V2_FORMAT
    assert body["b0_proof_digest"] != MISSING
    assert "source_generation" not in body
    assert ReadyManifest.from_dict(body).to_dict() == body
    store.close()


def test_committed_candidate_scope_rejects_corrupted_backing(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from paper_runtime.ready_publication import (
        verify_committed_receipt_candidate_scope,
    )
    from tests.test_ready_policy_fail_closed import _seed_exact_pit_scope

    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    store = SqliteStore(db_path)
    store._conn.execute(  # noqa: SLF001
        "UPDATE jquants_records SET payload='{\"poison\":true}' "
        "WHERE dataset='equities_bars_daily'"
    )
    commit_receipt_candidate(store)
    result = verify_committed_receipt_candidate_scope(
        store,
        binding=binding,
        environment="production",
    )
    assert result["compiled_scope_status"] == "FAIL"
    assert result.get("compiled_scope_error")
    assert "compiled_scope_proof_digest" not in result
    assert "observation_checked_at" not in result
    assert "receipt_source" not in result
    assert "receipt_native_manifest" not in result
    assert "receipt_native_manifest_digest" not in result
    assert result["snapshot_b0_status"] == "FAIL"
    assert result["snapshot_quality_digest"].startswith("sha256:")
    store.close()


def test_declared_coverage_segments_use_selector_windows_and_full_months() -> None:
    from pit.scoped_selection import split_safety_interval_start

    assert split_safety_interval_start("2022-10-20") == "2022-10-20"
    warmup = declared_coverage_segments(
        ("equities_bars_daily",),
        lookback_start="2022-12-24",
        period_end="2023-01-06",
        selected_event_dates={},
    )
    assert [item.segment_id for item in warmup] == ["2022-12", "2023-01"]
    assert warmup[0].segment_start == "2022-12-01"
    assert warmup[0].segment_end == "2022-12-31"
    assert warmup[1].segment_start == "2023-01-01"
    assert warmup[1].segment_end == "2023-01-31"
    bars = declared_coverage_segments(
        ("equities_bars_daily",),
        lookback_start="2022-12-24",
        period_end="2023-01-06",
        selected_event_dates={},
        bar_split_interval_start="2022-10-20",
    )
    assert [item.segment_id for item in bars] == [
        "2022-10",
        "2022-11",
        "2022-12",
        "2023-01",
    ]
    predecessor_month = declared_coverage_segments(
        ("equities_bars_daily",),
        lookback_start="2022-12-24",
        period_end="2023-01-06",
        selected_event_dates={
            "equities_bars_daily": frozenset({"2022-09-15", "2023-01-05"})
        },
        bar_split_interval_start="2022-10-20",
    )
    assert [item.segment_id for item in predecessor_month] == [
        "2022-09",
        "2022-10",
        "2022-11",
        "2022-12",
        "2023-01",
    ]
    fins = declared_coverage_segments(
        ("fins_summary",),
        lookback_start="2022-12-24",
        period_end="2023-02-14",
        selected_event_dates={"fins_summary": frozenset({"2022-11-15"})},
    )
    assert [item.segment_id for item in fins] == [
        "2022-11",
        "2022-12",
        "2023-01",
        "2023-02",
    ]
    master = declared_coverage_segments(
        ("equities_master",),
        lookback_start="2022-12-24",
        period_end="2023-01-06",
        selected_event_dates={
            "equities_master": frozenset({"2022-10-03", "2023-01-04"})
        },
    )
    assert [item.segment_id for item in master] == ["2022-10", "2023-01"]
    calendar = declared_coverage_segments(
        ("markets_calendar", "indices_bars_daily_topix"),
        lookback_start="2022-12-24",
        period_start="2023-01-04",
        period_end="2023-01-06",
        selected_event_dates={},
    )
    assert [
        item.segment_id
        for item in calendar
        if item.dataset == "markets_calendar"
    ] == ["2023-01"]
    assert [
        item.segment_id
        for item in calendar
        if item.dataset == "indices_bars_daily_topix"
    ] == ["2023-01"]
    compiled = compiled_period_collection_segments(
        ("markets_calendar", "equities_bars_daily"),
        period_start="2023-01-04",
        period_end="2023-10-13",
    )
    assert [
        item.segment_id
        for item in compiled
        if item.dataset == "markets_calendar"
    ] == [
        "2023-01",
        "2023-02",
        "2023-03",
        "2023-04",
        "2023-05",
        "2023-06",
        "2023-07",
        "2023-08",
        "2023-09",
        "2023-10",
    ]


def _canonical_month_calendar_raw(*, start: str, end: str) -> bytes:
    from datetime import date, timedelta

    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    fixture_business_start = date(2022, 10, 3)
    markets_start = date(2022, 12, 6)
    rows = []
    while cursor <= stop:
        holiday = (
            "1"
            if cursor == fixture_business_start or cursor >= markets_start
            else "0"
        )
        rows.append({"Date": cursor.isoformat(), "HolDiv": holiday})
        cursor += timedelta(days=1)
    return json.dumps({"data": rows}, separators=(",", ":")).encode("utf-8")


def _issue_declared_segment(
    store: SqliteStore,
    *,
    authority: _SignedReceiptAuthority,
    segment: RequiredCoverageSegment,
    run_id: int,
    environment: str,
    authority_instance_digest: str,
) -> None:
    from paper_runtime.ready_publication import canonical_digest
    from tests.test_ready_policy_fail_closed import _scope_calendar_extras

    structured = [
        dict(row)
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT * FROM jquants_records "
            "WHERE source='jquants' AND dataset=? "
            "ORDER BY natural_key",
            (segment.dataset,),
        ).fetchall()
        if segment.segment_start <= str(row["event_time"])[:10] <= segment.segment_end
    ]
    if not structured:
        raise AssertionError(
            f"{segment.dataset}/{segment.segment_id} has no catalog rows"
        )
    raw_records = [json.loads(str(row["payload"])) for row in structured]
    raw_page = json.dumps({"data": raw_records}, sort_keys=True).encode("utf-8")
    product_bytes = canonical_product_artifact_bytes(structured)
    extra_evidence = None
    if segment.dataset == "equities_master":
        calendar_raw = _canonical_month_calendar_raw(
            start=segment.segment_start,
            end=segment.segment_end,
        )
        extra_evidence = _scope_calendar_extras(
            calendar_raw,
            start=segment.segment_start,
            end=segment.segment_end,
        )
        persist_official_calendar_raw(
            store._conn,  # noqa: SLF001
            body=calendar_raw,
            expected_digest=extra_evidence["official_calendar_raw_body_digest"],
        )
    evidence = reconcile_test_evidence(
        required=segment,
        run_id=run_id,
        raw_pages=[raw_page],
        raw_records=raw_records,
        structured_records=structured,
        checked_at=CHECKED_AT,
        structured_digest=product_artifact_digest(structured),
        extra_evidence=extra_evidence,
        environment=environment,
        authority_instance_digest=authority_instance_digest,
        include_master_calendar_digests=segment.dataset == "equities_master",
        product_artifact_bytes=product_bytes,
    )
    record_collection_receipt(store._conn, authority.issue(evidence))  # noqa: SLF001
    raw_manifest_digest = str(evidence.claims["raw_manifest_digest"])
    operation_id = canonical_digest(
        {
            "operation": "canonical-month",
            "dataset": segment.dataset,
            "segment_id": segment.segment_id,
        }
    )
    artifact_body = product_bytes.decode("utf-8")
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log "
        "(id,ran_at,source,runtime,status,detail,authority_operation_id) "
        "VALUES (?,?,'jquants','receipt-evidence-authority','SUCCESS','{}',?)",
        (run_id, CHECKED_AT, operation_id),
    )
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO raw_retention_manifests "
        "(dataset,run_id,manifest_key,page_count,row_count,raw_bytes,"
        "data_digest,completeness,created_at) "
        "VALUES (?,?,?,?,?,?,?,'COMPLETE',?)",
        (
            segment.dataset,
            run_id,
            str(evidence.claims["raw_manifest_key"]),
            1,
            len(raw_records),
            len(raw_page),
            raw_manifest_digest,
            CHECKED_AT,
        ),
    )
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO receipt_product_materializations "
        "(operation_id,run_id,source,dataset,segment_id,artifact_key,"
        "artifact_digest,artifact_body,row_count,byte_count,manifest_key,"
        "manifest_digest,raw_manifest_key,raw_manifest_digest,"
        "raw_page_count,raw_row_count,raw_bytes,committed_at) "
        "VALUES (?,?,'jquants',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            operation_id,
            run_id,
            segment.dataset,
            segment.segment_id,
            str(evidence.claims["artifact_key"]),
            product_artifact_digest(structured),
            artifact_body,
            len(structured),
            len(artifact_body.encode("utf-8")),
            str(evidence.claims["manifest_key"]),
            canonical_digest(
                {"artifact_digest": product_artifact_digest(structured)}
            ),
            str(evidence.claims["raw_manifest_key"]),
            raw_manifest_digest,
            1,
            len(raw_records),
            len(raw_page),
            CHECKED_AT,
        ),
    )


def test_committed_candidate_canonical_months_prove_until_unselected_month_removed(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from paper_runtime.ready_publication import (
        verify_committed_receipt_candidate_scope,
    )
    from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
    from pit.scoped_selection import split_safety_interval_start
    from research.ready_manifest import is_sha256_digest
    from storage.receipt_crypto import (
        PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS,
        PRODUCTION_RECEIPT_ENVIRONMENT,
    )
    from tests.test_ready_policy_fail_closed import (
        _daily_equity_bar,
        _seed_exact_pit_scope,
    )

    db_path, binding = _seed_exact_pit_scope(
        tmp_path,
        receipt_ed25519_keys,
        split_predecessor_day="2022-09-15",
    )
    interval_start = split_safety_interval_start("2022-10-20")
    assert interval_start == "2022-10-20"
    planned = declared_coverage_segments(
        EXACT_FOUR_DATASET_IDS,
        lookback_start="2023-01-04",
        period_start="2023-01-04",
        period_end="2023-01-06",
        selected_event_dates={
            "fins_summary": frozenset(
                {"2022-10-20", "2023-01-03", "2023-01-05"}
            ),
            "equities_master": frozenset(
                {"2022-10-03", "2023-01-04", "2023-01-05", "2023-01-06"}
            ),
            "equities_bars_daily": frozenset({"2022-09-15", "2023-01-05"}),
        },
        bar_split_interval_start=interval_start,
    )
    assert [
        item.segment_id
        for item in planned
        if item.dataset == "equities_bars_daily"
    ] == ["2022-09", "2022-10", "2022-11", "2022-12", "2023-01"]
    assert [
        item.segment_id
        for item in planned
        if item.dataset == "markets_calendar"
    ] == ["2023-01"]
    assert [
        item.segment_id
        for item in planned
        if item.dataset == "indices_bars_daily_topix"
    ] == ["2023-01"]
    assert any(
        item.dataset == "fins_summary" and item.segment_id == "2022-11"
        for item in planned
    )
    store = SqliteStore(db_path)
    for day, bar in (
        (
            "2022-10-21",
            _daily_equity_bar(
                "1332", "2022-10-21", close=100.0, morning=99.5, volume=1000.0
            ),
        ),
        (
            "2022-11-15",
            _daily_equity_bar(
                "9999", "2022-11-15", close=100.0, morning=99.5, volume=1000.0
            ),
        ),
        (
            "2022-12-15",
            _daily_equity_bar(
                "1332", "2022-12-15", close=100.0, morning=99.5, volume=1000.0
            ),
        ),
    ):
        store.upsert(
            "jquants_records",
            normalize_generic(
                [bar],
                dataset="equities_bars_daily",
                ingested_at=close_as_of(day),
            ),
        )
    for disc_date, disc_no in (
        ("2022-11-15", "disc-9999-nov"),
        ("2022-12-15", "disc-9999-dec"),
    ):
        store.upsert(
            "jquants_records",
            normalize_generic(
                [
                    {
                        "Code": "9999",
                        "DiscDate": disc_date,
                        "DiscTime": "08:00:00",
                        "DiscNo": disc_no,
                        "EPS": 1.0,
                    }
                ],
                dataset="fins_summary",
                ingested_at=f"{disc_date}T08:00:00+09:00",
            ),
        )
    authority = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    for index, segment in enumerate(planned, start=10):
        _issue_declared_segment(
            store,
            authority=authority,
            segment=segment,
            run_id=index,
            environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            authority_instance_digest=PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[
                "production"
            ],
        )
    commit_receipt_candidate(store)
    proved = verify_committed_receipt_candidate_scope(
        store,
        binding=binding,
        environment="production",
    )
    assert proved["compiled_scope_status"] == "PASS"
    body = proved["receipt_native_manifest"]
    assert is_sha256_digest(body["coverage_proof_digest"]), proved.get(
        "coverage_proof_reason"
    )
    assert is_sha256_digest(body["raw_proof_digest"])
    assert is_sha256_digest(body["receipt_proof_digest"])
    assert body["coverage_proof_digest"] != body["raw_proof_digest"]
    assert "coverage_proof_reason" not in proved
    store._conn.execute(  # noqa: SLF001
        "DELETE FROM collection_receipts "
        "WHERE dataset='fins_summary' AND segment_id='2022-11'"
    )
    commit_receipt_candidate(store)
    missing = verify_committed_receipt_candidate_scope(
        store,
        binding=binding,
        environment="production",
    )
    assert missing["compiled_scope_status"] == "PASS"
    assert missing["receipt_native_manifest"]["coverage_proof_digest"] == "MISSING"
    assert "fins_summary/2022-11" in str(missing.get("coverage_proof_reason"))
    store.close()


def test_two_bar_segments_distinct_run_ids_keep_quality_bytes(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from paper_runtime.ready_publication import (
        verify_committed_receipt_candidate_scope,
    )
    from tests.test_ready_policy_fail_closed import _mini_exact_scope_binding

    first = _signed_bundle(
        tmp_path,
        receipt_ed25519_keys,
        segment_id="2023-01",
        run_id=1,
        operation_id="sha256:" + "ab" * 32,
        bar_date="2023-01-04",
    )
    second = _signed_bundle(
        tmp_path,
        receipt_ed25519_keys,
        segment_id="2023-02",
        run_id=2,
        operation_id="sha256:" + "cd" * 32,
        bar_date="2023-02-01",
    )
    store = SqliteStore(tmp_path / "two-seg.sqlite")
    configure_receipt_candidate_limits(store, max_database_bytes=5 * 1024 * 1024)
    for _rows, product_path, raw_path, descriptor, _receipt in (first, second):
        materialize_receipt_segment(
            store,
            environment="production",
            descriptor=descriptor,
            product_path=product_path,
            raw_path=raw_path,
            calendar_path=None,
            max_database_bytes=5 * 1024 * 1024,
        )
    commit_receipt_candidate(store)
    runs = [
        (str(row["segment_id"]), int(row["run_id"]))
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT segment_id, run_id FROM collection_receipts "
            "WHERE dataset='equities_bars_daily' ORDER BY segment_id"
        )
    ]
    assert runs == [("2023-01", 1), ("2023-02", 2)]
    freeze_receipt_candidate_snapshot(store)
    before = hash_receipt_candidate_snapshot(store)
    result = verify_committed_receipt_candidate_scope(
        store,
        binding=_mini_exact_scope_binding(),
        environment="production",
        allowed_segments=frozenset(
            {("equities_bars_daily", "2023-01"), ("equities_bars_daily", "2023-02")}
        ),
    )
    assert result["physical_db_digest"] == before
    assert result["physical_db_digest"] == hash_receipt_candidate_snapshot(store)
    assert result["snapshot_quality_digest"].startswith("sha256:")
    assert result["snapshot_b0_status"] == "FAIL"
    store.close()


def test_bar_dates_uses_payload_date_then_natural_key_without_invalid_json(
    tmp_path: Path,
) -> None:
    from storage.coverage import _bar_dates

    store = SqliteStore(tmp_path / "bar-dates.sqlite")
    conn = store._conn  # noqa: SLF001
    clock = "2023-01-04T16:00:00+09:00"
    conn.executemany(
        "INSERT INTO jquants_records ("
        "source,dataset,natural_key,event_time,available_at,ingested_at,"
        "payload,raw_payload) VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                "jquants",
                "equities_bars_daily",
                '{"Code":"1301","Date":"ignored"}',
                clock,
                clock,
                clock,
                '{"Code":"1301","Date":"2023-01-04"}',
                "{}",
            ),
            (
                "jquants",
                "equities_bars_daily",
                '{"Code":"1301","Date":"2023-01-05"}',
                clock,
                clock,
                clock,
                '{"Code":"1301","Date":""}',
                "{}",
            ),
            (
                "jquants",
                "equities_bars_daily",
                '{"Code":"1301","Date":"2023-01-06"}',
                clock,
                clock,
                clock,
                "not-json",
                "{}",
            ),
            (
                "jquants",
                "equities_bars_daily",
                "also-not-json",
                clock,
                clock,
                clock,
                "still-not-json",
                "{}",
            ),
        ],
    )
    conn.commit()
    assert _bar_dates(conn) == {"2023-01-04", "2023-01-05", "2023-01-06"}
    assert _bar_dates(
        conn, period_start="2023-01-05", period_end="2023-01-05"
    ) == {"2023-01-05"}
    store.close()


def test_snapshot_quality_future_rows_do_not_mask_missing_pre_cutoff(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from paper_runtime.ready_publication import (
        verify_committed_receipt_candidate_scope,
    )
    from tests.test_ready_policy_fail_closed import _seed_exact_pit_scope

    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    store = SqliteStore(db_path)
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO jquants_records ("
        "source,dataset,natural_key,event_time,available_at,ingested_at,"
        "payload,raw_payload"
        ") SELECT source,dataset,"
        "json_set(natural_key,'$.Date','2023-10-20'),"
        "'2023-10-20T16:00:00+09:00',available_at,ingested_at,"
        "json_set(payload,'$.Date','2023-10-20'),raw_payload "
        "FROM jquants_records WHERE dataset='equities_bars_daily' LIMIT 1"
    )
    commit_receipt_candidate(store)
    freeze_receipt_candidate_snapshot(store)
    before = hash_receipt_candidate_snapshot(store)
    with_future = verify_committed_receipt_candidate_scope(
        store,
        binding=binding,
        environment="production",
    )
    assert with_future["physical_db_digest"] == before
    assert with_future["snapshot_b0_status"] == "FAIL"
    assert with_future["snapshot_b4_status"] == "PASS"
    assert with_future["snapshot_c8_status"] == "PASS"
    bars_c8 = [
        row
        for row in with_future["snapshot_quality"]["c8"]
        if row["dataset"] == "equities_bars_daily"
    ]
    assert len(bars_c8) == 1
    assert str(bars_c8[0]["metrics"]["latest_event_time"]).startswith("2023-01-06")
    store._conn.execute(  # noqa: SLF001
        "DELETE FROM jquants_records WHERE dataset='equities_bars_daily' "
        "AND substr(event_time,1,10)='2023-01-06'"
    )
    commit_receipt_candidate(store)
    freeze_receipt_candidate_snapshot(store)
    after = hash_receipt_candidate_snapshot(store)
    missing = verify_committed_receipt_candidate_scope(
        store,
        binding=binding,
        environment="production",
    )
    assert missing["physical_db_digest"] == after
    assert missing["snapshot_b0_status"] == "FAIL"
    assert missing["snapshot_b4_status"] == "FAIL"
    assert missing["snapshot_c8_status"] == "PASS"
    missing_bars_c8 = [
        row
        for row in missing["snapshot_quality"]["c8"]
        if row["dataset"] == "equities_bars_daily"
    ]
    assert len(missing_bars_c8) == 1
    assert str(missing_bars_c8[0]["metrics"]["latest_event_time"]).startswith(
        "2023-01-05"
    )
    assert "completeness_claim" not in missing
    assert all(
        row["dataset"] != "fins_summary" and row["dataset"] != "equities_master"
        for row in missing["snapshot_quality"]["c8"]
    )
    store.close()
