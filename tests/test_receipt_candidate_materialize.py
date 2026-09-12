"""Signed receipt-candidate materializer: identities, catalog ownership, clocks."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import threading
from functools import partial
from pathlib import Path

import pytest
import urllib.request

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
    from receipt_candidate_job import RECEIPT_CANDIDATE_FORMAT
    from test_cloud_personal_research_container import service

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
    from receipt_candidate_job import RECEIPT_CANDIDATE_FORMAT, ReceiptCandidateJobSpec
    from test_cloud_personal_research_container import (
        _cancel_held_retries_after_worker,
        _job_manager,
        _join_manager_worker,
        service,
    )

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
    from receipt_candidate_job import (
        RECEIPT_CANDIDATE_MAX_REQUEST_BYTES,
        RECEIPT_CANDIDATE_MAX_SEGMENTS,
        ReceiptCandidateJobSpec,
        execute_receipt_candidate_job,
    )
    from test_cloud_personal_research_container import service

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
    assert len(
        json.dumps(terminal, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ) < 64 * 1024
