"""Signed receipt-candidate materializer: identities, catalog ownership, clocks."""

from __future__ import annotations

import calendar
import gzip
import hashlib
import io
import json
import sqlite3
import threading
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
    declared_coverage_segments,
    record_collection_receipt,
)
from storage.sqlite_store import SqliteStore
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    reconcile_test_evidence,
)

CHECKED_AT = "2026-08-25T00:00:00+00:00"
OPERATION_ID = "sha256:" + "ab" * 32


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


def _signed_bundle(
    tmp_path: Path,
    receipt_ed25519_keys,
    *,
    raw_bytes_delta: int = 0,
    segment_id: str = "2023-01",
    run_id: int = 1,
    operation_id: str = OPERATION_ID,
    bar_date: str = "2023-01-04",
):
    rows = _bar_rows(bar_date)
    product_bytes = canonical_product_artifact_bytes(rows)
    product_path = tmp_path / f"product-{segment_id}.jsonl"
    product_path.write_bytes(product_bytes)
    raw_path = tmp_path / f"raw-{segment_id}.json"
    file_digest, collection_digest = _write_collection(raw_path)
    year, month, _day = bar_date.split("-")
    last_day = calendar.monthrange(int(year), int(month))[1]
    segment_start = f"{year}-{month}-01"
    segment_end = f"{year}-{month}-{last_day:02d}"
    raw_page = json.dumps(
        {"data": [{"Code": "1301", "Date": bar_date}]},
        separators=(",", ":"),
    ).encode()
    required = RequiredCoverageSegment(
        source="jquants",
        dataset="equities_bars_daily",
        segment_id=segment_id,
        segment_start=segment_start,
        segment_end=segment_end,
        expected_scope={
            "period_start": segment_start,
            "period_end": segment_end,
            "expected_item_unit": "source_event",
        },
        expected_items=1,
    )
    evidence = reconcile_test_evidence(
        required=required,
        run_id=run_id,
        raw_pages=[raw_page],
        raw_records=[{"Code": "1301", "Date": bar_date}],
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
        "operation_id": operation_id,
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
    conn = store._conn  # noqa: SLF001
    operation_id = str(
        conn.execute(
            "SELECT operation_id FROM receipt_product_materializations"
        ).fetchone()[0]
    )
    with product_path.open("rb") as handle:
        file_measure = measure_product_artifact_jsonl(handle)
    with open_stored_product_artifact(conn, operation_id) as first:
        first_measure = measure_product_artifact_jsonl(first)
    with open_stored_product_artifact(conn, operation_id) as second:
        second_measure = measure_product_artifact_jsonl(second)
    assert first_measure == second_measure == file_measure
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
            rows = [
                self.descriptors[(item["dataset"], item["segment_id"])]
                for item in payload["segments"]
            ]
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
        headers = {
            "x-quant-resource": resource,
            "x-quant-receipt-digest": payload["receipt_digest"],
        }
        return _Http(self.blobs[resource], headers, 200)


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


def _worker_document(job_id: str, segments: list[dict[str, str]]) -> dict[str, object]:
    from execution.exact_four_binding import controlled_pilot_v1_contract
    from test_cloud_personal_research_container import service
    from receipt_candidate_job import RECEIPT_CANDIDATE_FORMAT

    contract = controlled_pilot_v1_contract()
    digest_body = {
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "format": RECEIPT_CANDIDATE_FORMAT,
        "job_id": job_id,
        "profile_digest": contract["profile_digest"],
        "profile_id": contract["profile_id"],
        "runner_version": service.RUNNER_VERSION,
        "segments": segments,
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


def test_http_job_and_execute_publish_compact_completed_terminal(
    tmp_path: Path, receipt_ed25519_keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_cloud_personal_research_container import (
        _cancel_held_retries_after_worker,
        _job_manager,
        _join_manager_worker,
        service,
    )
    from paper_runtime.ready_publication import canonical_digest
    from receipt_candidate_job import RECEIPT_CANDIDATE_FORMAT, ReceiptCandidateJobSpec

    _rows, product_path, raw_path, descriptor, _receipt = _signed_bundle(
        tmp_path, receipt_ed25519_keys
    )
    selector = {
        "dataset": descriptor["dataset"],
        "segment_id": descriptor["segment_id"],
    }
    document = _worker_document("cand-exec-1", [selector])
    spec = ReceiptCandidateJobSpec.from_document(document)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    transport = _ReceiptTransport(
        {(selector["dataset"], selector["segment_id"]): descriptor},
        {
            "product_artifact": product_path.read_bytes(),
            "raw_collection_manifest": raw_path.read_bytes(),
        },
        uploads,
    )
    monkeypatch.setattr(urllib.request, "urlopen", transport.urlopen)
    stored: dict[str, dict] = {}
    published = threading.Event()

    def publish(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        stored[key] = json.loads(data)

    work = tmp_path / "work"
    work.mkdir()
    manager = _job_manager(
        partial(service.default_runner, work_root=work),
        terminal_uploader=publish,
        terminal_reader=lambda item: stored.get(item.manifest_key),
        on_terminal=published.set,
        max_job_seconds=30,
    )
    encoded = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    worker = None
    try:
        posted = _posted(
            path="/v1/materialize-receipt-candidate",
            body=encoded,
            manager=manager,
        )
        assert posted.status == 202
        queued = json.loads(posted.wfile.getvalue().decode("utf-8"))["job"]
        assert queued is not None
        assert queued["job_kind"] == "receipt-candidate"
        assert "cohort_id" not in queued
        assert published.wait(5)
        worker = _join_manager_worker(manager)
        terminal = stored[spec.manifest_key]
        assert manager.status(spec.job_id)["status"] == "COMPLETED"
        assert terminal["status"] == "COMPLETED"
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
        assert terminal["segment_count"] == 1
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
    finally:
        _cancel_held_retries_after_worker(manager, worker)
        if manager._watchdog is not None:
            manager._watchdog.cancel()


def test_execute_512_selectors_keeps_compact_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from execution.exact_four_binding import controlled_pilot_v1_contract
    from test_cloud_personal_research_container import service
    from receipt_candidate_job import (
        RECEIPT_CANDIDATE_MAX_REQUEST_BYTES,
        RECEIPT_CANDIDATE_MAX_SEGMENTS,
        ReceiptCandidateJobSpec,
        execute_receipt_candidate_job,
    )

    datasets = sorted(str(item) for item in controlled_pilot_v1_contract()["dataset_ids"])
    segments: list[dict[str, str]] = []
    descriptors: dict[tuple[str, str], dict] = {}
    for index in range(RECEIPT_CANDIDATE_MAX_SEGMENTS):
        month = index // len(datasets)
        year = 2000 + month // 12
        month_number = 1 + month % 12
        selector = {
            "dataset": datasets[index % len(datasets)],
            "segment_id": f"{year:04d}-{month_number:02d}",
        }
        digest = "sha256:" + hashlib.sha256(str(index).encode()).hexdigest()
        segments.append(selector)
        descriptors[(selector["dataset"], selector["segment_id"])] = {
            **selector,
            "operation_id": digest,
            "receipt_digest": digest,
        }
    segments.sort(key=lambda item: (item["dataset"], item["segment_id"]))
    document = _worker_document("cand-512", segments)
    encoded = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert service.MAX_REQUEST_BYTES < len(encoded) <= RECEIPT_CANDIDATE_MAX_REQUEST_BYTES
    transport = _ReceiptTransport(
        descriptors,
        {
            "product_artifact": b"x",
            "raw_collection_manifest": b"y",
            "official_calendar_raw": b"z",
        },
        tmp_path,
    )

    def _skip_materialize(store, **kwargs):
        del store
        item = kwargs["descriptor"]
        return {
            "dataset": item["dataset"],
            "segment_id": item["segment_id"],
            "receipt_digest": item["receipt_digest"],
        }

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
    assert terminal["segment_count"] == RECEIPT_CANDIDATE_MAX_SEGMENTS
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


def test_execute_pass_streams_closed_sqlite_before_gzip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_runtime.ready_publication import canonical_digest
    from receipt_candidate_job import ReceiptCandidateJobSpec, execute_receipt_candidate_job

    selector = {"dataset": "equities_bars_daily", "segment_id": "2023-01"}
    spec = ReceiptCandidateJobSpec.from_document(
        _worker_document("cand-phys-1", [selector])
    )
    digest = "sha256:" + "1" * 64
    transport = _ReceiptTransport(
        {
            (selector["dataset"], selector["segment_id"]): {
                **selector,
                "receipt_digest": digest,
                "operation_id": digest,
            }
        },
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
    assert "equities_bars_daily/2022-10" in str(
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
        lookback_start="2022-12-24",
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
