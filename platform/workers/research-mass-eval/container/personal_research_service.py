#!/usr/bin/env python3
"""Single-job HTTP service for deterministic personal research in a Container."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_CONTAINER_MODULE_DIR = str(Path(__file__).resolve().parent)
if _CONTAINER_MODULE_DIR not in sys.path:
    sys.path.insert(0, _CONTAINER_MODULE_DIR)

from personal_history_source_client import PersonalHistorySourceClient
from personal_svi_2023_job import (
    PersonalSvi2023JobSpec,
    SviJobInputError,
    execute_svi_job,
)
from personal_index_vol_overlay_2023_job import (
    OverlayJobInputError,
    PersonalIndexVolOverlay2023JobSpec,
    execute_overlay_job,
)
from ingestion.personal_history import (
    PERSONAL_COMPLETENESS_CLAIM,
    PERSONAL_CONTROLLED_ELIGIBILITY,
    PERSONAL_HISTORY_FORMAT,
    PERSONAL_HISTORY_SCOPE_DIGEST,
    PERSONAL_HISTORY_SCOPE_ID,
    PERSONAL_HISTORY_SCOPE_VERSION,
    PERSONAL_RESEARCH_STATE,
    PersonalHistoryHydrator,
    assert_personal_history_database,
    build_personal_history_plan,
)
from storage.sqlite_store import SqliteStore
from research.personal_base_sleeve import (
    BASE_COHORT_ID,
    BASE_SLEEVE_ID,
    BASE_UNIVERSE_ID,
    PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA,
    PERSONAL_BASE_SLEEVE_RANKING_ROLE,
    PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
    PERSONAL_BASE_SLEEVE_ROLE,
    validate_personal_base_sleeve_artifact,
)

RUNNER_VERSION = "personal-cloud-runner/v13"
SNAPSHOT_MAX_DATABASE_BYTES = 3_758_096_384
SNAPSHOT_MINIMUM_FREE_BYTES = 256 * 1024 * 1024
R2_ORIGIN = "http://research.r2"
DEFAULT_TIMEOUT_SECONDS = 165 * 60
MAX_JOB_LIFETIME_SECONDS = 180 * 60
MAX_PERIOD_DAYS = 2200
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BASE_SLEEVE_ARTIFACT_BYTES = 16 * 1024 * 1024
_SINGLE_THREAD_NUMERIC_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STRATEGY_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_DIAGNOSTIC_REPORT_BYTES = 8 * 1024 * 1024
MAX_CANDIDATE_DIAGNOSTICS = 4
MAX_ERROR_DETAIL_CHARS = 160
_SNAPSHOT_RE = re.compile(
    r"^research/personal/snapshots/sha256=([0-9a-f]{64})\.sqlite(?:\.gz)?$"
)
DEFAULT_PERSONAL_COHORT_ID = "diverse-core-am-pm-v1"
PERSONAL_EXECUTABLE_COHORT_IDS = frozenset(
    {
        "price-relative-v1",
        "fundamental-relative-v1",
        "diverse-core-v1",
        "compact-market-diverse-v1",
        "sector-relative-ls-v1",
        "price-relative-am-pm-v1",
        "fundamental-relative-am-pm-v1",
        "diverse-core-am-pm-v1",
        "compact-market-diverse-am-pm-v1",
        "sector-relative-ls-am-pm-v1",
    }
)
COMPACT_MARKET_COHORT_IDS = frozenset(
    {"compact-market-diverse-v1", "compact-market-diverse-am-pm-v1"}
)
PERSONAL_EXECUTABLE_UNIVERSE_IDS = frozenset(
    {
        "topix_all",
        "topix_core30",
        "topix_large70",
        "topix_mid400",
        "topix_small1",
        "topix_small2",
        "topix_small",
        "topix100",
        "topix500",
    }
)
COMPACT_MARKET_UNIVERSE_IDS = frozenset(
    {"topix_core30", "topix_large70", "topix100"}
)


class JobInputError(ValueError):
    """The Worker supplied an invalid closed job document."""


class JobConflictError(RuntimeError):
    """A job id was reused with different parameters."""


class JobBusyError(RuntimeError):
    """The one allowed Container job is already running."""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_day(value: Any, label: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise JobInputError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise JobInputError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise JobInputError(f"{label} must be an ISO date")
    return parsed


@dataclass(frozen=True, slots=True)
class JobSpec:
    cohort_id: str
    cohort_digest: str
    universe_id: str
    universe_rule_digest: str
    job_id: str
    snapshot_key: str
    snapshot_sha256: str
    period_start: str
    period_end: str
    request_digest: str
    result_key: str
    manifest_key: str
    runner_version: str

    @classmethod
    def from_document(cls, document: Any) -> "JobSpec":
        if not isinstance(document, dict):
            raise JobInputError("job must be a JSON object")
        fields = {
            "cohort_id",
            "cohort_digest",
            "job_id",
            "manifest_key",
            "period_end",
            "period_start",
            "request_digest",
            "result_key",
            "runner_version",
            "snapshot_key",
            "snapshot_sha256",
            "universe_id",
            "universe_rule_digest",
        }
        if set(document) != fields or not all(
            isinstance(document[field], str) for field in fields
        ):
            raise JobInputError("job fields are closed strings")
        spec = cls(**{field: document[field] for field in fields})
        spec.validate()
        return spec

    def validate(self) -> None:
        if self.cohort_id not in PERSONAL_EXECUTABLE_COHORT_IDS:
            raise JobInputError("cohort_id is not executable by personal research")
        if _DIGEST_RE.fullmatch(self.cohort_digest) is None:
            raise JobInputError("cohort_digest is invalid")
        if self.universe_id not in PERSONAL_EXECUTABLE_UNIVERSE_IDS:
            raise JobInputError("universe_id is not executable by personal research")
        compact_universe = self.universe_id in COMPACT_MARKET_UNIVERSE_IDS
        compact_cohort = self.cohort_id in COMPACT_MARKET_COHORT_IDS
        if compact_universe != compact_cohort:
            raise JobInputError("cohort_id and universe_id profile mismatch")
        if _DIGEST_RE.fullmatch(self.universe_rule_digest) is None:
            raise JobInputError("universe_rule_digest is invalid")
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise JobInputError("job_id is invalid")
        if _SHA_RE.fullmatch(self.snapshot_sha256) is None:
            raise JobInputError("snapshot_sha256 is invalid")
        match = _SNAPSHOT_RE.fullmatch(self.snapshot_key)
        if match is None or match.group(1) != self.snapshot_sha256:
            raise JobInputError("snapshot key does not match its digest")
        start = _parse_day(self.period_start, "period_start")
        end = _parse_day(self.period_end, "period_end")
        span = (end - start).days
        if span <= 0 or span > MAX_PERIOD_DAYS:
            raise JobInputError(f"research period must be 1-{MAX_PERIOD_DAYS} days")
        if self.runner_version != RUNNER_VERSION:
            raise JobInputError("runner version mismatch")
        if self.result_key != (
            f"research/personal/jobs/job={self.job_id}/result.tar.gz"
        ):
            raise JobInputError("result key mismatch")
        if self.manifest_key != (
            f"research/personal/jobs/job={self.job_id}/manifest.json"
        ):
            raise JobInputError("manifest key mismatch")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise JobInputError("request_digest is invalid")
        if self.request_digest != self.derived_request_digest():
            raise JobInputError("request_digest mismatch")

    def derived_request_digest(self) -> str:
        body = {
            "cohort_digest": self.cohort_digest,
            "cohort_id": self.cohort_id,
            "job_id": self.job_id,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "runner_version": self.runner_version,
            "snapshot_key": self.snapshot_key,
            "snapshot_sha256": self.snapshot_sha256,
            "universe_id": self.universe_id,
            "universe_rule_digest": self.universe_rule_digest,
        }
        return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotJobSpec:
    job_id: str
    period_start: str
    period_end: str
    lookback_sessions: int
    request_digest: str
    manifest_key: str
    runner_version: str
    environment: str
    format: str
    max_database_bytes: int
    deployment_id: str

    @classmethod
    def from_document(cls, document: Any) -> "SnapshotJobSpec":
        if not isinstance(document, dict):
            raise JobInputError("snapshot job must be a JSON object")
        required = {
            "deployment_id",
            "environment",
            "format",
            "job_id",
            "lookback_sessions",
            "manifest_key",
            "max_database_bytes",
            "period_end",
            "period_start",
            "request_digest",
            "runner_version",
        }
        if set(document) != required:
            raise JobInputError("snapshot job fields are closed")
        lookback = document["lookback_sessions"]
        max_bytes = document["max_database_bytes"]
        if type(lookback) is not int or not 0 <= lookback <= 252:
            raise JobInputError("lookback_sessions is invalid")
        if type(max_bytes) is not int or max_bytes != SNAPSHOT_MAX_DATABASE_BYTES:
            raise JobInputError("max_database_bytes is invalid")
        string_fields = required - {"lookback_sessions", "max_database_bytes"}
        if not all(isinstance(document[field], str) for field in string_fields):
            raise JobInputError("snapshot job string fields are closed")
        spec = cls(
            job_id=document["job_id"],
            period_start=document["period_start"],
            period_end=document["period_end"],
            lookback_sessions=lookback,
            request_digest=document["request_digest"],
            manifest_key=document["manifest_key"],
            runner_version=document["runner_version"],
            environment=document["environment"],
            format=document["format"],
            max_database_bytes=max_bytes,
            deployment_id=document["deployment_id"],
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise JobInputError("job_id is invalid")
        start = _parse_day(self.period_start, "period_start")
        end = _parse_day(self.period_end, "period_end")
        span = (end - start).days
        if span < 0 or span > MAX_PERIOD_DAYS:
            raise JobInputError(f"snapshot period must be 0-{MAX_PERIOD_DAYS} days")
        if self.runner_version != RUNNER_VERSION:
            raise JobInputError("runner version mismatch")
        if self.environment not in {"production", "staging"}:
            raise JobInputError("environment is invalid")
        if self.format != PERSONAL_HISTORY_FORMAT:
            raise JobInputError("snapshot format mismatch")
        if self.manifest_key != (
            f"research/personal/snapshot-builds/job={self.job_id}/manifest.json"
        ):
            raise JobInputError("manifest key mismatch")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise JobInputError("request_digest is invalid")
        if self.request_digest != self.derived_request_digest():
            raise JobInputError("request_digest mismatch")

    def derived_request_digest(self) -> str:
        body = {
            "format": self.format,
            "job_id": self.job_id,
            "lookback_sessions": self.lookback_sessions,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "runner_version": self.runner_version,
        }
        return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _download_snapshot_transport(spec: JobSpec, destination: Path) -> str:
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{spec.snapshot_key}",
        method="GET",
        headers={
            "accept": (
                "application/gzip"
                if spec.snapshot_key.endswith(".sqlite.gz")
                else "application/vnd.sqlite3"
            )
        },
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError(f"snapshot download returned {response.status}")
        raw_length = response.headers.get("content-length", "")
        if (
            not raw_length.isdigit()
            or not 0 < int(raw_length) <= MAX_SNAPSHOT_BYTES
        ):
            raise RuntimeError("snapshot content length is missing or out of bounds")
        expected_length = int(raw_length)
        received = 0
        created = False
        try:
            with destination.open("xb") as handle:
                created = True
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected_length or received > MAX_SNAPSHOT_BYTES:
                        raise RuntimeError("snapshot exceeded its declared size bound")
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        if received != expected_length:
            destination.unlink(missing_ok=True)
            raise RuntimeError("snapshot content length mismatch")
    return digest.hexdigest()


def _expand_gzip_snapshot(
    transport: Path,
    destination: Path,
    *,
    expected_sha256: str,
) -> None:
    digest = hashlib.sha256()
    expanded = 0
    created = False
    try:
        try:
            with gzip.open(transport, "rb") as compressed:
                with destination.open("xb") as raw:
                    created = True
                    while True:
                        chunk = compressed.read(1024 * 1024)
                        if not chunk:
                            break
                        expanded += len(chunk)
                        if expanded > MAX_SNAPSHOT_BYTES:
                            raise RuntimeError(
                                "expanded snapshot exceeds the fixed size bound"
                            )
                        digest.update(chunk)
                        raw.write(chunk)
        except (EOFError, gzip.BadGzipFile, zlib.error) as error:
            raise RuntimeError("snapshot gzip stream is invalid") from error
        if expanded < 1:
            raise RuntimeError("expanded snapshot is empty")
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError("snapshot sha256 mismatch")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def download_snapshot(spec: JobSpec, destination: Path) -> None:
    compressed = destination.with_name(f"{destination.name}.transport.gz")
    if destination.exists() or compressed.exists():
        raise RuntimeError("snapshot destination already exists")
    complete = False
    compressed_owned = False
    destination_owned = False
    try:
        if spec.snapshot_key.endswith(".sqlite.gz"):
            _download_snapshot_transport(spec, compressed)
            compressed_owned = True
            _expand_gzip_snapshot(
                compressed,
                destination,
                expected_sha256=spec.snapshot_sha256,
            )
            destination_owned = True
        else:
            digest = _download_snapshot_transport(spec, destination)
            destination_owned = True
            if digest != spec.snapshot_sha256:
                raise RuntimeError("snapshot sha256 mismatch")
        complete = True
    finally:
        if compressed_owned:
            compressed.unlink(missing_ok=True)
        if not complete and destination_owned:
            destination.unlink(missing_ok=True)


def verify_sqlite(path: Path) -> None:
    uri = f"file:{path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    finally:
        connection.close()
    if rows != [("ok",)]:
        raise RuntimeError("SQLite quick_check failed")


def _archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def build_result_archive(output_root: Path, destination: Path) -> tuple[int, int]:
    files: list[tuple[Path, Path]] = []
    total_bytes = 0
    for path in sorted(output_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(output_root)
        if path.suffix in {".sqlite", ".sqlite3", ".db"}:
            continue
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_RESULT_BYTES:
            raise RuntimeError("research artifacts exceed the fixed result bound")
        files.append((path, relative))
    if not files:
        raise RuntimeError("research run produced no archival artifacts")
    with destination.open("xb") as raw_archive:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=raw_archive,
            mtime=0,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path, relative in files:
                    archive.add(
                        path,
                        arcname=relative.as_posix(),
                        recursive=False,
                        filter=_archive_filter,
                    )
    result_size = destination.stat().st_size
    if result_size > MAX_RESULT_BYTES:
        destination.unlink(missing_ok=True)
        raise RuntimeError("compressed result exceeds the fixed result bound")
    return len(files), result_size


def _require_output_artifact(
    summary: Mapping[str, Any], field: str, output_root: Path
) -> Path:
    value = summary.get(field)
    if not isinstance(value, str):
        raise RuntimeError(f"qp-research {field} artifact is invalid")
    try:
        resolved = Path(value).resolve(strict=True)
        resolved.relative_to(output_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(f"qp-research {field} artifact is invalid") from error
    if not resolved.is_file():
        raise RuntimeError(f"qp-research {field} artifact is invalid")
    return resolved


def _validated_base_sleeve_reference(
    summary: Mapping[str, Any],
    *,
    spec: JobSpec,
    output_root: Path,
) -> dict[str, Any] | None:
    reference = summary.get("base_sleeve_artifact")
    source_count = summary.get("non_candidate_source_backtest_count")
    expected_profile = (
        spec.cohort_id == BASE_COHORT_ID
        and spec.universe_id == BASE_UNIVERSE_ID
    )
    if type(source_count) is not int or source_count not in {0, 1}:
        raise RuntimeError("qp-research base sleeve source count is invalid")
    if reference is None:
        if source_count != 0:
            raise RuntimeError("qp-research base sleeve reference is missing")
        if expected_profile and summary.get("evaluated_count") != 0:
            raise RuntimeError(
                "qp-research evaluated long-short result requires a base sleeve source"
            )
        return None
    if not expected_profile or source_count != 1:
        raise RuntimeError("qp-research emitted an unexpected base sleeve source")
    expected_fields = {
        "archive_member",
        "artifact_schema_version",
        "candidate_count_contribution",
        "cohort_id",
        "path",
        "ranking_role",
        "role",
        "schema_version",
        "sha256",
        "strategy_id",
        "universe_id",
    }
    if not isinstance(reference, dict) or set(reference) != expected_fields:
        raise RuntimeError("qp-research base sleeve reference is invalid")
    if (
        reference.get("schema_version") != PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA
        or reference.get("artifact_schema_version")
        != PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA
        or reference.get("strategy_id") != BASE_SLEEVE_ID
        or reference.get("cohort_id") != BASE_COHORT_ID
        or reference.get("universe_id") != BASE_UNIVERSE_ID
        or reference.get("role") != PERSONAL_BASE_SLEEVE_ROLE
        or reference.get("ranking_role") != PERSONAL_BASE_SLEEVE_RANKING_ROLE
        or reference.get("candidate_count_contribution") != 0
        or not isinstance(reference.get("sha256"), str)
        or _DIGEST_RE.fullmatch(str(reference["sha256"])) is None
        or not isinstance(reference.get("archive_member"), str)
    ):
        raise RuntimeError("qp-research base sleeve reference is invalid")
    artifact = _require_output_artifact(reference, "path", output_root)
    archive_member = artifact.relative_to(output_root.resolve(strict=True)).as_posix()
    if (
        archive_member != reference["archive_member"]
        or not archive_member.startswith("base-sleeve/")
        or artifact.suffix != ".json"
        or artifact.stem != str(reference["sha256"])[7:]
        or artifact.stat().st_size > MAX_BASE_SLEEVE_ARTIFACT_BYTES
        or "sha256:" + _sha256_file(artifact) != reference["sha256"]
    ):
        raise RuntimeError("qp-research base sleeve artifact digest is invalid")
    try:
        document = json.loads(artifact.read_bytes())
        validate_personal_base_sleeve_artifact(document)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("qp-research base sleeve artifact is invalid") from error
    if (
        not isinstance(document, dict)
        or document.get("cohort", {}).get("cohort_digest") != spec.cohort_digest
        or document.get("universe", {}).get("universe_rule_digest")
        != spec.universe_rule_digest
        or document.get("snapshot", {}).get("logical_data_snapshot_id")
        != summary.get("logical_data_snapshot_id")
    ):
        raise RuntimeError("qp-research base sleeve provenance is invalid")
    source_run = document.get("source_run")
    assert isinstance(source_run, dict)
    for field in ("paper_artifact", "risk_artifact"):
        _require_output_artifact(
            {field: str(output_root / str(source_run[field]))},
            field,
            output_root,
        )
    return {
        key: value
        for key, value in reference.items()
        if key != "path"
    }


def _put(
    key: str,
    data: bytes | Path,
    *,
    spec: Any,
    content_digest: str,
    extra_headers: Mapping[str, str] | None = None,
) -> None:
    if isinstance(data, Path):
        length = data.stat().st_size
        payload: Any = data.open("rb")
    else:
        length = len(data)
        payload = data
    headers = {
        "content-length": str(length),
        "content-type": (
            "application/gzip" if isinstance(data, Path) else "application/json"
        ),
        "x-personal-job-id": spec.job_id,
        "x-personal-request-digest": spec.request_digest,
        "x-content-sha256": content_digest,
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        data=payload,
        method="PUT",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            if response.status not in {HTTPStatus.OK, HTTPStatus.CREATED}:
                raise RuntimeError(f"R2 upload returned {response.status}")
    finally:
        if isinstance(data, Path):
            payload.close()


def _safe_detail(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def _stdout_summary(stdout: str) -> tuple[dict[str, Any] | None, str]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None, "no_summary"
    try:
        parsed = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None, "invalid_summary"
    if not isinstance(parsed, dict):
        return None, "invalid_summary"
    return parsed, "ok"


def _process_crash_message(process: subprocess.CompletedProcess[str]) -> str:
    detail = " ".join((process.stderr or "").split())[-400:]
    return (
        f"qp-research exited {process.returncode}: {detail or 'no diagnostic'}"
    )


def _sanitize_error_detail(value: Any) -> str:
    if not isinstance(value, str):
        return "no detail"
    tokens = [
        token
        for token in value.split()
        if "/" not in token and "\\" not in token
    ]
    cleaned = " ".join(tokens)[:MAX_ERROR_DETAIL_CHARS]
    return cleaned or "no detail"


def _candidate_error_rows(report: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        return []
    rows: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        error = item.get("error")
        if not isinstance(error, Mapping):
            continue
        strategy_id = item.get("strategy_id")
        error_type = error.get("type")
        if (
            not isinstance(strategy_id, str)
            or _STRATEGY_ID_RE.fullmatch(strategy_id) is None
            or not isinstance(error_type, str)
            or _ERROR_TYPE_RE.fullmatch(error_type) is None
        ):
            continue
        rows.append(
            {
                "strategy_id": strategy_id,
                "type": error_type,
                "detail": _sanitize_error_detail(error.get("detail")),
            }
        )
        if len(rows) >= MAX_CANDIDATE_DIAGNOSTICS:
            break
    return rows


def _load_candidate_error_rows(
    summary: Mapping[str, Any], output_root: Path
) -> list[dict[str, str]]:
    try:
        report_path = _require_output_artifact(summary, "report_json", output_root)
        if report_path.stat().st_size > MAX_DIAGNOSTIC_REPORT_BYTES:
            return []
        parsed = json.loads(report_path.read_bytes())
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, dict):
        return []
    return _candidate_error_rows(parsed)


def _candidate_failure_message(
    summary: Mapping[str, Any],
    output_root: Path,
) -> str:
    unexpected = summary.get("unexpected_errors")
    count = unexpected if type(unexpected) is int and unexpected >= 0 else None
    count_text = "unknown" if count is None else str(count)
    rows = _load_candidate_error_rows(summary, output_root)
    if not rows:
        return (
            f"qp-research candidate failures: unexpected_errors={count_text}; "
            "no candidate diagnostic"
        )
    first = rows[0]
    type_counts: dict[str, int] = {}
    for row in rows:
        type_counts[row["type"]] = type_counts.get(row["type"], 0) + 1
    root_type, root_count = max(
        type_counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    return (
        f"qp-research candidate failures: unexpected_errors={count_text}; "
        f"first={first['strategy_id']} {first['type']}: {first['detail']}; "
        f"repeated={root_type}x{root_count}"
    )


def _manifest_base(spec: JobSpec, *, started_at: str, finished_at: str) -> dict[str, Any]:
    return {
        "version": RUNNER_VERSION,
        "job_id": spec.job_id,
        "cohort_id": spec.cohort_id,
        "cohort_digest": spec.cohort_digest,
        "universe_id": spec.universe_id,
        "universe_rule_digest": spec.universe_rule_digest,
        "request_digest": spec.request_digest,
        "snapshot": {
            "key": spec.snapshot_key,
            "sha256": f"sha256:{spec.snapshot_sha256}",
        },
        "period": {"start": spec.period_start, "end": spec.period_end},
        "started_at": started_at,
        "finished_at": finished_at,
        "exact_four": True,
        "draft_only": True,
        "go": False,
        "ready_snapshot_declared": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "model_calls": 0,
        "estimated_ai_cost_usd": 0.0,
    }


def _run_research_process(
    args: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run qp-research in a killable process group, including its four children."""

    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            cmd=error.cmd,
            timeout=error.timeout,
            output=stdout,
            stderr=stderr,
        ) from error
    return subprocess.CompletedProcess(
        args=args,
        returncode=int(process.returncode or 0),
        stdout=stdout,
        stderr=stderr,
    )


def execute_job(
    spec: JobSpec,
    *,
    work_root: Path,
    command: Sequence[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    downloader: Callable[[JobSpec, Path], None] = download_snapshot,
    uploader: Callable[..., None] = _put,
) -> dict[str, Any]:
    started_at = _now()
    job_root = Path(tempfile.mkdtemp(prefix=f"job-{spec.job_id}-", dir=work_root))
    try:
        try:
            database = job_root / "source.sqlite"
            output = job_root / "output"
            output.mkdir()
            downloader(spec, database)
            if _sha256_file(database) != spec.snapshot_sha256:
                raise RuntimeError("snapshot sha256 mismatch after persistence")
            verify_sqlite(database)
            args = [
                *command,
                "--db",
                str(database),
                "--start",
                spec.period_start,
                "--end",
                spec.period_end,
                "--output",
                str(output),
                "--cohort",
                spec.cohort_id,
                "--universe",
                spec.universe_id,
            ]
            process_env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                **_SINGLE_THREAD_NUMERIC_ENV,
            }
            try:
                process = _run_research_process(
                    args,
                    cwd=os.environ.get("QP_REPO_ROOT", "/app"),
                    env=process_env,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                if timeout_seconds % 60 == 0:
                    limit = f"{int(timeout_seconds / 60)}-minute"
                else:
                    limit = f"{timeout_seconds:g}-second"
                raise RuntimeError(
                    f"qp-research exceeded the {limit} limit"
                ) from exc
            summary, summary_status = _stdout_summary(process.stdout or "")
            if summary is None:
                if process.returncode not in {0, 2}:
                    raise RuntimeError(_process_crash_message(process))
                if summary_status == "no_summary":
                    raise RuntimeError("qp-research emitted no result document")
                raise RuntimeError("qp-research result document is invalid")
            if process.returncode not in {0, 1, 2}:
                raise RuntimeError(_process_crash_message(process))
            if process.returncode == 1:
                raise RuntimeError(_candidate_failure_message(summary, output))
            evaluated_count = summary.get("evaluated_count")
            hold_count = summary.get("hold_count")
            unexpected_errors = summary.get("unexpected_errors")
            candidate_count = summary.get("candidate_count")
            model_calls = summary.get("model_calls")
            estimated_ai_cost_usd = summary.get("estimated_ai_cost_usd")
            # The closed CLI either skips all four candidates at preflight or
            # evaluates all four. Per-candidate failures increment
            # unexpected_errors and exit 1, which this boundary rejects.
            if (
                type(candidate_count) is not int
                or candidate_count != 4
                or type(evaluated_count) is not int
                or evaluated_count not in {0, 4}
                or type(hold_count) is not int
                or not 0 <= hold_count <= evaluated_count
                or type(unexpected_errors) is not int
                or unexpected_errors != 0
                or type(model_calls) is not int
                or model_calls != 0
                or type(estimated_ai_cost_usd) not in {int, float}
                or estimated_ai_cost_usd != 0
                or any(
                    not isinstance(summary.get(field), str)
                    or _DIGEST_RE.fullmatch(summary[field]) is None
                    for field in (
                        "report_id",
                        "snapshot_id",
                        "logical_data_snapshot_id",
                    )
                )
                or summary.get("cohort_id") != spec.cohort_id
                or summary.get("cohort_digest") != spec.cohort_digest
                or summary.get("universe_id") != spec.universe_id
                or summary.get("universe_rule_digest")
                != spec.universe_rule_digest
                or summary.get("go") is not False
                or summary.get("ready_snapshot_declared") is not False
                or summary.get("live_orders_enabled") is not False
                or summary.get("automatic_promotion") is not False
            ):
                raise RuntimeError("qp-research violated the fixed personal policy")
            expected_exit_code = 0 if evaluated_count == 4 else 2
            if process.returncode != expected_exit_code:
                raise RuntimeError(
                    "qp-research exit/result contract mismatch: "
                    f"exit={process.returncode}, evaluated_count={evaluated_count}"
                )
            _require_output_artifact(summary, "report_json", output)
            _require_output_artifact(summary, "report_markdown", output)
            base_sleeve_reference = _validated_base_sleeve_reference(
                summary,
                spec=spec,
                output_root=output,
            )
            stable_summary = {
                key: summary.get(key)
                for key in (
                    "cohort_id",
                    "cohort_digest",
                    "universe_id",
                    "universe_rule_digest",
                    "report_id",
                    "snapshot_id",
                    "logical_data_snapshot_id",
                    "candidate_count",
                    "evaluated_count",
                    "hold_count",
                    "unexpected_errors",
                    "model_calls",
                    "estimated_ai_cost_usd",
                    "go",
                    "ready_snapshot_declared",
                    "live_orders_enabled",
                    "automatic_promotion",
                )
            }
            stable_summary["base_sleeve_artifact"] = base_sleeve_reference
            stable_summary["non_candidate_source_backtest_count"] = int(
                base_sleeve_reference is not None
            )
            (output / "runner-summary.json").write_bytes(
                _canonical_bytes(stable_summary)
            )
            archive = job_root / "result.tar.gz"
            archived_files, result_bytes = build_result_archive(output, archive)
            result_digest = "sha256:" + _sha256_file(archive)
            uploader(
                spec.result_key,
                archive,
                spec=spec,
                content_digest=result_digest,
            )
            manifest = {
                **_manifest_base(spec, started_at=started_at, finished_at=_now()),
                "status": "COMPLETED",
                "result_key": spec.result_key,
                "result_sha256": result_digest,
                "result_bytes": result_bytes,
                "archived_file_count": archived_files,
                "report_id": summary.get("report_id"),
                "cohort_digest": summary.get("cohort_digest"),
                "universe_rule_digest": summary.get("universe_rule_digest"),
                "snapshot_id": summary.get("snapshot_id"),
                "candidate_count": 4,
                "evaluated_count": summary.get("evaluated_count"),
                "hold_count": summary.get("hold_count"),
                "unexpected_errors": summary.get("unexpected_errors"),
                "base_sleeve_artifact": base_sleeve_reference,
                "non_candidate_source_backtest_count": int(
                    base_sleeve_reference is not None
                ),
            }
        except Exception as error:
            manifest = {
                **_manifest_base(spec, started_at=started_at, finished_at=_now()),
                "status": "FAILED",
                "error": _safe_detail(error),
            }
        manifest_bytes = _canonical_bytes(manifest)
        manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        uploader(
            spec.manifest_key,
            manifest_bytes,
            spec=spec,
            content_digest=manifest_digest,
        )
        return manifest
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


def _session_coverage(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS bar_rows,
            SUM(morning_adjustment_close IS NOT NULL) AS am_close,
            SUM(morning_turnover_value IS NOT NULL) AS am_turnover,
            SUM(morning_adjustment_volume IS NOT NULL) AS am_volume,
            SUM(afternoon_adjustment_close IS NOT NULL) AS pm_close,
            SUM(afternoon_turnover_value IS NOT NULL) AS pm_turnover,
            SUM(afternoon_adjustment_volume IS NOT NULL) AS pm_volume
        FROM jquants_daily_bars
        WHERE source='jquants'
        """
    ).fetchone()
    total = int(row["bar_rows"] or 0)
    return {
        "bar_rows": total,
        "am": {
            "morning_adjustment_close_non_null": int(row["am_close"] or 0),
            "morning_turnover_value_non_null": int(row["am_turnover"] or 0),
            "morning_adjustment_volume_non_null": int(row["am_volume"] or 0),
        },
        "pm": {
            "afternoon_adjustment_close_non_null": int(row["pm_close"] or 0),
            "afternoon_turnover_value_non_null": int(row["pm_turnover"] or 0),
            "afternoon_adjustment_volume_non_null": int(row["pm_volume"] or 0),
        },
    }


def _gzip_file(source: Path, destination: Path) -> None:
    with destination.open("xb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=raw,
            mtime=0,
        ) as compressed:
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, compressed, 1024 * 1024)


def _snapshot_manifest_base(
    spec: SnapshotJobSpec, *, started_at: str, finished_at: str
) -> dict[str, Any]:
    return {
        "version": RUNNER_VERSION,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "format": PERSONAL_HISTORY_FORMAT,
        "history_scope_id": PERSONAL_HISTORY_SCOPE_ID,
        "history_scope_version": PERSONAL_HISTORY_SCOPE_VERSION,
        "history_scope_digest": PERSONAL_HISTORY_SCOPE_DIGEST,
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "lookback_sessions": spec.lookback_sessions,
        "started_at": started_at,
        "finished_at": finished_at,
        "runner_version": RUNNER_VERSION,
        "deployment_id": spec.deployment_id,
        "research_state": PERSONAL_RESEARCH_STATE,
        "completeness_claim": PERSONAL_COMPLETENESS_CLAIM,
        "controlled_live_eligibility": PERSONAL_CONTROLLED_ELIGIBILITY,
        "go": False,
        "ready_snapshot_declared": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "model_calls": 0,
    }


def execute_snapshot_job(
    spec: SnapshotJobSpec,
    *,
    work_root: Path,
    uploader: Callable[..., None] = _put,
    client_factory: Callable[[SnapshotJobSpec], Any] | None = None,
) -> dict[str, Any]:
    started_at = _now()
    job_root = Path(tempfile.mkdtemp(prefix=f"snapshot-{spec.job_id}-", dir=work_root))
    gzip_key: str | None = None
    try:
        try:
            database = job_root / "personal-history.sqlite"
            assert_personal_history_database(
                database, governed_default=Path("/app/data/structured/ingestion.sqlite")
            )
            plan = build_personal_history_plan(
                period_start=spec.period_start,
                period_end=spec.period_end,
                lookback_sessions=spec.lookback_sessions,
            )
            store = SqliteStore(database)
            client = (client_factory or (
                lambda job: PersonalHistorySourceClient(
                    environment=job.environment,
                    period_end=job.period_end,
                )
            ))(spec)
            hydrator = PersonalHistoryHydrator(
                client=client,
                store=store,
                plan=plan,
                max_database_bytes=spec.max_database_bytes,
                minimum_free_bytes=SNAPSHOT_MINIMUM_FREE_BYTES,
            )
            summary = hydrator.hydrate()
            coverage = _session_coverage(store._conn)
            store._conn.close()
            verify_sqlite(database)
            raw_bytes = database.stat().st_size
            if raw_bytes > spec.max_database_bytes:
                raise RuntimeError("snapshot sqlite exceeds the 3.5 GiB builder cap")
            raw_digest = "sha256:" + _sha256_file(database)
            gzip_path = job_root / "personal-history.sqlite.gz"
            _gzip_file(database, gzip_path)
            gzip_bytes = gzip_path.stat().st_size
            gzip_digest = "sha256:" + _sha256_file(gzip_path)
            gzip_key = (
                "research/personal/snapshots/sha256="
                f"{raw_digest[7:]}.sqlite.gz"
            )
            uploader(
                gzip_key,
                gzip_path,
                spec=spec,
                content_digest=gzip_digest,
                extra_headers={"x-personal-raw-sha256": raw_digest},
            )
            manifest = {
                **_snapshot_manifest_base(
                    spec, started_at=started_at, finished_at=_now()
                ),
                "status": "COMPLETED",
                "data_start": summary.bar_start,
                "calendar_start": plan.calendar_start,
                "calendar_end": spec.period_end,
                "dataset_segment_counts": dict(summary.segment_counts),
                "fetched_rows": summary.fetched_rows,
                "written_rows": summary.written_rows,
                "am_field_non_null_coverage": coverage["am"],
                "pm_field_non_null_coverage": coverage["pm"],
                "bar_rows": coverage["bar_rows"],
                "raw_bytes": raw_bytes,
                "raw_sha256": raw_digest,
                "gzip_bytes": gzip_bytes,
                "gzip_sha256": gzip_digest,
                "snapshot_key": gzip_key,
            }
        except Exception as error:
            manifest = {
                **_snapshot_manifest_base(
                    spec, started_at=started_at, finished_at=_now()
                ),
                "status": "FAILED",
                "error": _safe_detail(error),
            }
        manifest_bytes = _canonical_bytes(manifest)
        manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        uploader(
            spec.manifest_key,
            manifest_bytes,
            spec=spec,
            content_digest=manifest_digest,
        )
        return manifest
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


JobSpecLike = (
    JobSpec
    | SnapshotJobSpec
    | PersonalSvi2023JobSpec
    | PersonalIndexVolOverlay2023JobSpec
)
Runner = Callable[[JobSpecLike], dict[str, Any]]
TerminalCallback = Callable[[], None]


class JobManager:
    def __init__(
        self,
        runner: Runner,
        *,
        on_terminal: TerminalCallback | None = None,
        max_job_seconds: float = MAX_JOB_LIFETIME_SECONDS,
    ) -> None:
        if max_job_seconds <= 0:
            raise ValueError("max_job_seconds must be positive")
        self._runner = runner
        self._on_terminal = on_terminal
        self._max_job_seconds = max_job_seconds
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_job_id: str | None = None
        self._accepting = True
        self._watchdog: threading.Timer | None = None

    def submit(self, spec: JobSpecLike) -> dict[str, Any]:
        with self._lock:
            if not self._accepting:
                raise JobBusyError("container is shutting down")
            existing = self._jobs.get(spec.job_id)
            if existing is not None:
                if existing["request_digest"] != spec.request_digest:
                    raise JobConflictError("job_id was reused with different parameters")
                return dict(existing)
            if self._active_job_id is not None:
                raise JobBusyError(f"job {self._active_job_id} is already active")
            record = {
                "job_id": spec.job_id,
                "request_digest": spec.request_digest,
                "status": "QUEUED",
                "submitted_at": _now(),
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
            }
            if isinstance(spec, SnapshotJobSpec):
                record["job_kind"] = "snapshot-build"
            else:
                record["cohort_id"] = spec.cohort_id
                record["cohort_digest"] = spec.cohort_digest
            if isinstance(spec, JobSpec):
                record["universe_id"] = spec.universe_id
            self._jobs[spec.job_id] = record
            self._active_job_id = spec.job_id
            watchdog = threading.Timer(
                self._max_job_seconds,
                self._expire,
                args=(spec.job_id,),
            )
            watchdog.daemon = True
            self._watchdog = watchdog
            watchdog.start()
            thread = threading.Thread(
                target=self._execute,
                args=(spec,),
                name=f"personal-research-{spec.job_id}",
                daemon=True,
            )
            thread.start()
            return dict(record)

    def _expire(self, job_id: str) -> None:
        with self._lock:
            if self._active_job_id != job_id or not self._accepting:
                return
            record = self._jobs[job_id]
            self._jobs[job_id] = {
                **record,
                "status": "FAILED",
                "error": (
                    "absolute Container lifetime exceeded "
                    f"({self._max_job_seconds:g}s)"
                ),
                "finished_at": _now(),
                "go": False,
            }
            self._accepting = False
        if self._on_terminal is not None:
            self._on_terminal()

    def _execute(self, spec: JobSpecLike) -> None:
        with self._lock:
            if self._active_job_id != spec.job_id or not self._accepting:
                return
            self._jobs[spec.job_id]["status"] = "RUNNING"
            self._jobs[spec.job_id]["started_at"] = _now()
        try:
            result = self._runner(spec)
        except Exception as error:  # upload or service failure after job execution
            result = {
                "job_id": spec.job_id,
                "request_digest": spec.request_digest,
                "status": "FAILED",
                "error": _safe_detail(error),
                "go": False,
            }
            if isinstance(spec, SnapshotJobSpec):
                result["job_kind"] = "snapshot-build"
            else:
                result["cohort_id"] = spec.cohort_id
                result["cohort_digest"] = spec.cohort_digest
            if isinstance(spec, JobSpec):
                result["universe_id"] = spec.universe_id
        with self._lock:
            notify = self._accepting
            if notify:
                self._jobs[spec.job_id] = dict(result)
            self._active_job_id = None
            self._accepting = False
            watchdog = self._watchdog
            self._watchdog = None
            if watchdog is not None:
                watchdog.cancel()
        if notify and self._on_terminal is not None:
            self._on_terminal()

    def status(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            return None if record is None else dict(record)


def default_runner(spec: JobSpecLike) -> dict[str, Any]:
    if isinstance(spec, SnapshotJobSpec):
        work_root = Path(os.environ.get("QP_JOB_ROOT", "/tmp/personal-research"))
        work_root.mkdir(parents=True, exist_ok=True)
        return execute_snapshot_job(spec, work_root=work_root)
    if isinstance(spec, PersonalIndexVolOverlay2023JobSpec):
        return execute_overlay_job(spec)
    if isinstance(spec, PersonalSvi2023JobSpec):
        return execute_svi_job(spec)
    work_root = Path(os.environ.get("QP_JOB_ROOT", "/tmp/personal-research"))
    work_root.mkdir(parents=True, exist_ok=True)
    command = tuple(
        value
        for value in os.environ.get("QP_RESEARCH_COMMAND", "/app/scripts/qp-research").split()
        if value
    )
    if not command:
        raise RuntimeError("QP_RESEARCH_COMMAND is empty")
    return execute_job(spec, work_root=work_root, command=command)


class PersonalResearchHandler(BaseHTTPRequestHandler):
    manager: JobManager
    server_version = "quant-personal-research/1"

    def _json(self, value: Any, status: int) -> None:
        body = _canonical_bytes(value if isinstance(value, dict) else {"value": value})
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/ready":
            self._json({"ok": True, "service": RUNNER_VERSION}, HTTPStatus.OK)
            return
        prefix = "/v1/jobs/"
        if not self.path.startswith(prefix):
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        job_id = self.path[len(prefix) :]
        if _JOB_ID_RE.fullmatch(job_id) is None:
            self._json({"error": "invalid_job_id"}, HTTPStatus.BAD_REQUEST)
            return
        record = self.manager.status(job_id)
        if record is None:
            self._json({"error": "job_not_found", "job_id": job_id}, HTTPStatus.NOT_FOUND)
            return
        self._json({"ok": record.get("status") == "COMPLETED", "job": record}, HTTPStatus.OK)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path not in {
            "/v1/run",
            "/v1/run-svi-2023",
            "/v1/run-index-vol-overlay-2023",
            "/v1/build-snapshot",
        }:
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        raw_length = self.headers.get("content-length", "")
        if not raw_length.isdigit() or not 0 < int(raw_length) <= MAX_REQUEST_BYTES:
            self._json({"error": "invalid_content_length"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            document = json.loads(self.rfile.read(int(raw_length)))
            if self.path == "/v1/run-svi-2023":
                spec = PersonalSvi2023JobSpec.from_document(document)
            elif self.path == "/v1/run-index-vol-overlay-2023":
                spec = PersonalIndexVolOverlay2023JobSpec.from_document(document)
            elif self.path == "/v1/build-snapshot":
                spec = SnapshotJobSpec.from_document(document)
            else:
                spec = JobSpec.from_document(document)
            record = self.manager.submit(spec)
        except (
            json.JSONDecodeError,
            JobInputError,
            SviJobInputError,
            OverlayJobInputError,
        ) as error:
            self._json({"error": "invalid_job", "detail": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except JobConflictError as error:
            self._json({"error": "job_id_conflict", "detail": str(error)}, HTTPStatus.CONFLICT)
            return
        except JobBusyError as error:
            self._json({"error": "container_busy", "detail": str(error)}, HTTPStatus.CONFLICT)
            return
        self._json(
            {
                "ok": True,
                "accepted": True,
                "job": record,
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
            },
            HTTPStatus.ACCEPTED,
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(
            json.dumps(
                {
                    "event": "container_http",
                    "message": format % args,
                    "at": _now(),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), PersonalResearchHandler)
    server.daemon_threads = True
    PersonalResearchHandler.manager = JobManager(
        default_runner,
        on_terminal=server.shutdown,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
