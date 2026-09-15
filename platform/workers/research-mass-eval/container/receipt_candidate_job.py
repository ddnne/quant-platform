"""Receipt-candidate Container job: describe batches, spool, exact materialize."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ops.receipt_candidate_materialize import (
    ReceiptCandidateMaterializeError,
    commit_receipt_candidate,
    configure_receipt_candidate_limits,
    materialize_receipt_segment,
    rollback_receipt_candidate,
)
from receipt_product_byte_client import (
    DESCRIBE_BATCH_SEGMENTS,
    OFFICIAL_CALENDAR_MAX_BYTES,
    RAW_MANIFEST_MAX_BYTES,
    ReceiptProductTransportError,
    describe_receipt_product_input,
    spool_receipt_product_bytes,
)
from storage.sqlite_store import SqliteStore

RECEIPT_CANDIDATE_FORMAT = "receipt-candidate/v1"
RECEIPT_CANDIDATE_MAX_SEGMENTS = 512
RECEIPT_CANDIDATE_MAX_REQUEST_BYTES = 64 * 1024
# R2 single-object PUT ceiling: 5 GiB minus 5 MiB (Cloudflare R2 limits footnote 4).
RECEIPT_CANDIDATE_RAW_PUT_MAX_BYTES = (5 * 1024 * 1024 * 1024) - (5 * 1024 * 1024)
# Matches CREATE_ONLY_COMPARE_MAX_BYTES in platform/workers/research-mass-eval/src/http.ts.
RECEIPT_CANDIDATE_SCOPE_SIDECAR_MAX_BYTES = 256 * 1024
_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReceiptCandidateJobInputError(ValueError):
    """The Worker supplied a non-closed receipt-candidate job document."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _closed_pins() -> dict[str, Any]:
    from execution.exact_four_binding import controlled_pilot_v1_contract

    contract = controlled_pilot_v1_contract()
    datasets = contract["dataset_ids"]
    if type(datasets) is not list or not datasets:
        raise ReceiptCandidateJobInputError("profile datasets are missing")
    return {
        "profile_id": contract["profile_id"],
        "profile_digest": contract["profile_digest"],
        "dependency_closure_digest": contract["dependency_closure_digest"],
        "datasets": frozenset(str(item) for item in datasets),
    }


def compiled_candidate_selectors() -> tuple[dict[str, str], ...]:
    """Collection months implied by the pinned exact-four period."""

    from execution.exact_four_binding import controlled_pilot_v1_contract
    from storage.coverage_ledger import compiled_period_collection_segments

    contract = controlled_pilot_v1_contract()
    plans = contract["plans"]
    if type(plans) is not list or not plans:
        raise ReceiptCandidateJobInputError("profile period is missing")
    period_start = plans[0]["period_start"]
    period_end = plans[0]["period_end"]
    if type(period_start) is not str or type(period_end) is not str:
        raise ReceiptCandidateJobInputError("profile period is missing")
    if any(
        item.get("period_start") != period_start or item.get("period_end") != period_end
        for item in plans
        if type(item) is dict
    ):
        raise ReceiptCandidateJobInputError("profile period is missing")
    datasets = tuple(str(item) for item in contract["dataset_ids"])
    planned = compiled_period_collection_segments(
        datasets,
        period_start=period_start,
        period_end=period_end,
    )
    selectors = tuple(
        {"dataset": item.dataset, "segment_id": item.segment_id} for item in planned
    )
    if not 1 <= len(selectors) <= RECEIPT_CANDIDATE_MAX_SEGMENTS:
        raise ReceiptCandidateJobInputError("segments out of range")
    return selectors


@dataclass(frozen=True, slots=True)
class ReceiptCandidateJobSpec:
    job_id: str
    request_digest: str
    manifest_key: str
    runner_version: str
    environment: str
    format: str
    max_database_bytes: int
    deployment_id: str
    profile_id: str
    profile_digest: str
    dependency_closure_digest: str
    segments: tuple[dict[str, str], ...]

    @classmethod
    def from_document(cls, document: Any) -> "ReceiptCandidateJobSpec":
        if not isinstance(document, dict):
            raise ReceiptCandidateJobInputError("receipt candidate job must be a JSON object")
        required = {
            "deployment_id",
            "dependency_closure_digest",
            "environment",
            "format",
            "job_id",
            "manifest_key",
            "max_database_bytes",
            "profile_digest",
            "profile_id",
            "request_digest",
            "runner_version",
        }
        if set(document) != required:
            raise ReceiptCandidateJobInputError("receipt candidate job fields are closed")
        max_bytes = document["max_database_bytes"]
        from personal_research_service import (
            RUNNER_VERSION,
            SNAPSHOT_MAX_DATABASE_BYTES,
        )

        if type(max_bytes) is not int or max_bytes != SNAPSHOT_MAX_DATABASE_BYTES:
            raise ReceiptCandidateJobInputError("max_database_bytes is invalid")
        string_fields = required - {"max_database_bytes"}
        if not all(isinstance(document[field], str) for field in string_fields):
            raise ReceiptCandidateJobInputError("receipt candidate string fields are closed")
        pins = _closed_pins()
        spec = cls(
            job_id=document["job_id"],
            request_digest=document["request_digest"],
            manifest_key=document["manifest_key"],
            runner_version=document["runner_version"],
            environment=document["environment"],
            format=document["format"],
            max_database_bytes=max_bytes,
            deployment_id=document["deployment_id"],
            profile_id=document["profile_id"],
            profile_digest=document["profile_digest"],
            dependency_closure_digest=document["dependency_closure_digest"],
            segments=compiled_candidate_selectors(),
        )
        if spec.runner_version != RUNNER_VERSION:
            raise ReceiptCandidateJobInputError("runner version mismatch")
        spec.validate(pins=pins)
        return spec

    def validate(self, *, pins: Mapping[str, Any] | None = None) -> None:
        from storage.receipt_crypto import PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS

        closed = pins or _closed_pins()
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise ReceiptCandidateJobInputError("job_id is invalid")
        if self.environment not in PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS:
            raise ReceiptCandidateJobInputError("environment is invalid")
        if self.format != RECEIPT_CANDIDATE_FORMAT:
            raise ReceiptCandidateJobInputError("receipt candidate format mismatch")
        if self.manifest_key != (
            f"research/receipt-candidates/job={self.job_id}/manifest.json"
        ):
            raise ReceiptCandidateJobInputError("manifest key mismatch")
        if (
            self.profile_id != closed["profile_id"]
            or self.profile_digest != closed["profile_digest"]
            or self.dependency_closure_digest != closed["dependency_closure_digest"]
        ):
            raise ReceiptCandidateJobInputError("profile pin mismatch")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise ReceiptCandidateJobInputError("request_digest is invalid")
        if self.request_digest != self.derived_request_digest():
            raise ReceiptCandidateJobInputError("request_digest mismatch")

    def derived_request_digest(self) -> str:
        body = {
            "dependency_closure_digest": self.dependency_closure_digest,
            "format": self.format,
            "job_id": self.job_id,
            "profile_digest": self.profile_digest,
            "profile_id": self.profile_id,
            "runner_version": self.runner_version,
        }
        return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _manifest_base(spec: ReceiptCandidateJobSpec, *, started_at: str, finished_at: str) -> dict[str, Any]:
    from personal_research_service import RUNNER_VERSION

    return {
        "version": RUNNER_VERSION,
        "format": RECEIPT_CANDIDATE_FORMAT,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "started_at": started_at,
        "finished_at": finished_at,
        "runner_version": RUNNER_VERSION,
        "deployment_id": spec.deployment_id,
        "environment": spec.environment,
        "profile_id": spec.profile_id,
        "profile_digest": spec.profile_digest,
        "dependency_closure_digest": spec.dependency_closure_digest,
        "pending_ready": True,
        "ready": False,
        "ready_snapshot_declared": False,
        "go": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "completeness_claim": "NONE",
        "controlled_live_eligibility": "FORBIDDEN",
    }


def candidate_failure_terminal(
    spec: ReceiptCandidateJobSpec,
    *,
    started_at: str,
    finished_at: str,
    error: str,
) -> dict[str, Any]:
    """FAILED terminal reuses the closed base; no object keys."""
    return {
        **_manifest_base(spec, started_at=started_at, finished_at=finished_at),
        "status": "FAILED",
        "error": error,
    }


def _materialization_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    closed = [
        {
            "dataset": item["dataset"],
            "receipt_digest": item["receipt_digest"],
            "segment_id": item["segment_id"],
        }
        for item in rows
    ]
    closed.sort(key=lambda item: (item["dataset"], item["segment_id"]))
    return "sha256:" + hashlib.sha256(
        _canonical_bytes({"segments": closed})
    ).hexdigest()


def _scope_manifest_fields(scope: Mapping[str, Any]) -> dict[str, Any]:
    kind = scope.get("compiled_scope_kind")
    if type(kind) is not str or not kind:
        kind = "receipt-candidate-scope-diagnostic/v1"
    quality: dict[str, Any] = {}
    digest = scope.get("snapshot_quality_digest")
    payload = scope.get("snapshot_quality")
    if type(digest) is str and digest and isinstance(payload, Mapping):
        quality = {
            "snapshot_quality_kind": scope.get("snapshot_quality_kind"),
            "snapshot_quality_digest": digest,
            "snapshot_quality": dict(payload),
            "snapshot_b0_status": scope.get("snapshot_b0_status"),
            "snapshot_b4_status": scope.get("snapshot_b4_status"),
            "snapshot_c8_status": scope.get("snapshot_c8_status"),
            "b0_proof_digest": scope.get("b0_proof_digest"),
            "b4_proof_digest": scope.get("b4_proof_digest"),
            "validation_proof_digest": scope.get("validation_proof_digest"),
        }
    if scope.get("compiled_scope_status") == "PASS":
        return {
            "compiled_scope_status": "PASS",
            "compiled_scope_kind": kind,
            "observation_policy": scope["observation_policy"],
            "observation_checked_at": scope["observation_checked_at"],
            "compiled_scope_proof_digest": scope["compiled_scope_proof_digest"],
            "compiled_scope_physical_digest": scope["physical_db_digest"],
            "receipt_source_kind": scope["receipt_source"]["kind"],
            "receipt_runset_digest": scope["receipt_source"][
                "receipt_runset_digest"
            ],
            "receipt_native_manifest_digest": scope[
                "receipt_native_manifest_digest"
            ],
            "receipt_native_manifest": scope["receipt_native_manifest"],
            **quality,
        }
    fields: dict[str, Any] = {
        "compiled_scope_status": "FAIL",
        "compiled_scope_kind": kind,
        **quality,
    }
    error = scope.get("compiled_scope_error")
    if type(error) is str and error:
        fields["compiled_scope_error"] = error
    return fields


def _remaining_budget(limit: int, *paths: Path) -> int:
    used = 0
    for path in paths:
        if path.exists():
            used += path.stat().st_size
            wal = Path(str(path) + "-wal")
            shm = Path(str(path) + "-shm")
            if wal.exists():
                used += wal.stat().st_size
            if shm.exists():
                used += shm.stat().st_size
    if used >= limit:
        raise ReceiptCandidateMaterializeError(
            "receipt candidate sqlite exceeds the builder cap"
        )
    return limit - used


def execute_receipt_candidate_job(
    spec: ReceiptCandidateJobSpec,
    *,
    work_root: Path,
    uploader: Callable[..., None],
    opener: Any | None = None,
    deadline: Any | None = None,
) -> dict[str, Any]:
    from pit.cooperative_deadline import check_deadline
    from personal_research_service import _gzip_file, _now, _safe_detail, _sha256_file
    from storage.receipt_crypto import PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS

    del deadline
    check_deadline()
    if uploader is None:
        raise RuntimeError("receipt candidate requires immutable artifact uploader")
    if spec.environment not in PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS:
        raise ReceiptCandidateJobInputError("environment is invalid")
    transport = urllib.request if opener is None else opener
    started_at = _now()
    job_root = Path(
        tempfile.mkdtemp(prefix=f"receipt-candidate-{spec.job_id}-", dir=work_root)
    )
    store: SqliteStore | None = None
    try:
        try:
            database = job_root / "receipt-candidate.sqlite"
            store = SqliteStore(database)
            configure_receipt_candidate_limits(
                store, max_database_bytes=spec.max_database_bytes
            )
            materialized: list[dict[str, Any]] = []
            remaining_selectors = list(spec.segments)
            while remaining_selectors:
                batch = remaining_selectors[:DESCRIBE_BATCH_SEGMENTS]
                remaining_selectors = remaining_selectors[DESCRIBE_BATCH_SEGMENTS:]
                described = describe_receipt_product_input(
                    profile_id=spec.profile_id,
                    profile_digest=spec.profile_digest,
                    dependency_closure_digest=spec.dependency_closure_digest,
                    segments=batch,
                    opener=transport,
                )
                if described.get("environment") != spec.environment:
                    raise ReceiptCandidateMaterializeError(
                        "described environment does not match worker capability"
                    )
                rows = described.get("segments")
                if type(rows) is not list or len(rows) != len(batch):
                    raise ReceiptCandidateMaterializeError("described selectors drifted")
                wanted = {(item["dataset"], item["segment_id"]) for item in batch}
                got = {
                    (str(item.get("dataset")), str(item.get("segment_id")))
                    for item in rows
                    if type(item) is dict
                }
                if wanted != got:
                    raise ReceiptCandidateMaterializeError("described selectors drifted")
                for item in rows:
                    check_deadline()
                    dataset = str(item["dataset"])
                    segment_id = str(item["segment_id"])
                    operation_id = str(item["operation_id"])
                    receipt_digest = str(item["receipt_digest"])
                    product_path = job_root / f"product-{dataset}-{segment_id}.jsonl"
                    raw_path = job_root / f"raw-{dataset}-{segment_id}.json"
                    calendar_path = None
                    left = _remaining_budget(spec.max_database_bytes, database)
                    spool_receipt_product_bytes(
                        destination=product_path,
                        profile_id=spec.profile_id,
                        profile_digest=spec.profile_digest,
                        dependency_closure_digest=spec.dependency_closure_digest,
                        dataset=dataset,
                        segment_id=segment_id,
                        operation_id=operation_id,
                        receipt_digest=receipt_digest,
                        resource="product_artifact",
                        max_bytes=left,
                        opener=transport,
                    )
                    left = _remaining_budget(
                        spec.max_database_bytes, database, product_path
                    )
                    spool_receipt_product_bytes(
                        destination=raw_path,
                        profile_id=spec.profile_id,
                        profile_digest=spec.profile_digest,
                        dependency_closure_digest=spec.dependency_closure_digest,
                        dataset=dataset,
                        segment_id=segment_id,
                        operation_id=operation_id,
                        receipt_digest=receipt_digest,
                        resource="raw_collection_manifest",
                        max_bytes=min(RAW_MANIFEST_MAX_BYTES, left),
                        opener=transport,
                    )
                    if dataset == "equities_master":
                        calendar_path = job_root / f"calendar-{segment_id}.json"
                        left = _remaining_budget(
                            spec.max_database_bytes,
                            database,
                            product_path,
                            raw_path,
                        )
                        spool_receipt_product_bytes(
                            destination=calendar_path,
                            profile_id=spec.profile_id,
                            profile_digest=spec.profile_digest,
                            dependency_closure_digest=spec.dependency_closure_digest,
                            dataset=dataset,
                            segment_id=segment_id,
                            operation_id=operation_id,
                            receipt_digest=receipt_digest,
                            resource="official_calendar_raw",
                            max_bytes=min(OFFICIAL_CALENDAR_MAX_BYTES, left),
                            opener=transport,
                        )
                    materialized.append(
                        materialize_receipt_segment(
                            store,
                            environment=spec.environment,
                            descriptor=item,
                            product_path=product_path,
                            raw_path=raw_path,
                            calendar_path=calendar_path,
                            max_database_bytes=spec.max_database_bytes,
                        )
                    )
                    product_path.unlink(missing_ok=True)
                    raw_path.unlink(missing_ok=True)
                    if calendar_path is not None:
                        calendar_path.unlink(missing_ok=True)
            commit_receipt_candidate(store)
            from paper_runtime.ready_publication import (
                canonical_digest,
                canonical_json_bytes,
                verify_committed_receipt_candidate_scope,
            )
            from research.ready_manifest import load_exact_four_pilot_ready_binding

            binding = load_exact_four_pilot_ready_binding()
            if (
                binding.profile_id != spec.profile_id
                or binding.profile_digest != spec.profile_digest
                or binding.closure_set_digest != spec.dependency_closure_digest
            ):
                raise ReceiptCandidateJobInputError("profile pin mismatch")
            scope = verify_committed_receipt_candidate_scope(
                store,
                binding=binding,
                environment=spec.environment,
                allowed_segments=frozenset(
                    (item["dataset"], item["segment_id"]) for item in spec.segments
                ),
            )
            store.close()
            store = None
            wal = Path(str(database) + "-wal")
            if wal.exists() and wal.stat().st_size != 0:
                raise ReceiptCandidateMaterializeError(
                    "receipt candidate sqlite has a live WAL"
                )
            raw_bytes = database.stat().st_size
            if raw_bytes > spec.max_database_bytes:
                raise ReceiptCandidateMaterializeError(
                    "receipt candidate sqlite exceeds the builder cap"
                )
            raw_digest = "sha256:" + _sha256_file(database)
            if (
                scope.get("compiled_scope_status") == "PASS"
                and scope.get("physical_db_digest") != raw_digest
            ):
                raise ReceiptCandidateMaterializeError(
                    "receipt candidate sqlite digest drifted"
                )
            sqlite_key = (
                f"research/receipt-candidates/sha256={raw_digest[7:]}.sqlite"
            )
            sidecar_key = None
            if scope.get("compiled_scope_status") == "PASS":
                if raw_bytes > RECEIPT_CANDIDATE_RAW_PUT_MAX_BYTES:
                    raise ReceiptCandidateMaterializeError(
                        "receipt candidate sqlite exceeds the raw R2 object put cap"
                    )
                evidence_body = scope.pop("_receipt_scope_evidence_body", None)
                if type(evidence_body) is not dict:
                    raise ReceiptCandidateMaterializeError(
                        "receipt candidate PASS is missing scope evidence"
                    )
                sidecar_bytes = canonical_json_bytes(evidence_body)
                if len(sidecar_bytes) > RECEIPT_CANDIDATE_SCOPE_SIDECAR_MAX_BYTES:
                    raise ReceiptCandidateMaterializeError(
                        "receipt candidate scope evidence exceeds the sidecar cap"
                    )
                sidecar_digest = canonical_digest(evidence_body)
                if sidecar_digest != scope.get("compiled_scope_proof_digest"):
                    raise ReceiptCandidateMaterializeError(
                        "receipt candidate scope evidence digest drifted"
                    )
                sidecar_key = (
                    "research/receipt-candidates/"
                    f"sha256={sidecar_digest[7:]}.pit-dependency-scope.json"
                )
                uploader(
                    sidecar_key,
                    sidecar_bytes,
                    spec=spec,
                    content_digest=sidecar_digest,
                    extra_headers={
                        "content-type": "application/json; charset=utf-8",
                        "x-personal-raw-sha256": raw_digest,
                    },
                )
                uploader(
                    sqlite_key,
                    database,
                    spec=spec,
                    content_digest=raw_digest,
                    extra_headers={
                        "content-type": "application/vnd.sqlite3",
                        "x-personal-raw-sha256": raw_digest,
                    },
                )
            gzip_path = job_root / "receipt-candidate.sqlite.gz"
            _gzip_file(database, gzip_path)
            gzip_digest = "sha256:" + _sha256_file(gzip_path)
            gzip_key = (
                f"research/receipt-candidates/sha256={raw_digest[7:]}.sqlite.gz"
            )
            uploader(
                gzip_key,
                gzip_path,
                spec=spec,
                content_digest=gzip_digest,
                extra_headers={"x-personal-raw-sha256": raw_digest},
            )
            manifest = {
                **_manifest_base(spec, started_at=started_at, finished_at=_now()),
                "status": "COMPLETED",
                "segment_count": len(materialized),
                "materialization_digest": _materialization_digest(materialized),
                "raw_bytes": raw_bytes,
                "raw_sha256": raw_digest,
                "gzip_sha256": gzip_digest,
                "snapshot_key": gzip_key,
                **_scope_manifest_fields(scope),
            }
            if scope.get("compiled_scope_status") == "PASS":
                manifest["physical_key"] = sqlite_key
                if sidecar_key is not None:
                    manifest["dependency_scope_key"] = sidecar_key
        except Exception as error:
            if store is not None:
                rollback_receipt_candidate(store)
            manifest = candidate_failure_terminal(
                spec,
                started_at=started_at,
                finished_at=_now(),
                error=_safe_detail(error),
            )
        return manifest
    finally:
        if store is not None:
            store.close()
        shutil.rmtree(job_root, ignore_errors=True)
