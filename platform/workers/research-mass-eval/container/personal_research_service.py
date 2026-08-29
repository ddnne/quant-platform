#!/usr/bin/env python3
"""Single-job HTTP service for deterministic personal research in a Container."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_CONTAINER_MODULE_DIR = str(Path(__file__).resolve().parent)
if _CONTAINER_MODULE_DIR not in sys.path:
    sys.path.insert(0, _CONTAINER_MODULE_DIR)

from personal_svi_2023_job import (
    PersonalSvi2023JobSpec,
    SviJobInputError,
    execute_svi_job,
)

RUNNER_VERSION = "personal-cloud-runner/v5"
R2_ORIGIN = "http://research.r2"
DEFAULT_TIMEOUT_SECONDS = 165 * 60
MAX_JOB_LIFETIME_SECONDS = 180 * 60
MAX_PERIOD_DAYS = 2200
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SNAPSHOT_RE = re.compile(
    r"^research/personal/snapshots/sha256=([0-9a-f]{64})\.sqlite$"
)
PERSONAL_EXECUTABLE_COHORT_IDS = frozenset(
    {
        "price-relative-v1",
        "fundamental-relative-v1",
        "diverse-core-v1",
        "compact-market-diverse-v1",
        "sector-relative-ls-v1",
    }
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
        compact_cohort = self.cohort_id == "compact-market-diverse-v1"
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


def download_snapshot(spec: JobSpec, destination: Path) -> None:
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{spec.snapshot_key}",
        method="GET",
        headers={"accept": "application/vnd.sqlite3"},
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
        with destination.open("xb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > expected_length or received > MAX_SNAPSHOT_BYTES:
                    raise RuntimeError("snapshot exceeded its declared size bound")
                digest.update(chunk)
                handle.write(chunk)
        if received != expected_length:
            destination.unlink(missing_ok=True)
            raise RuntimeError("snapshot content length mismatch")
    if digest.hexdigest() != spec.snapshot_sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError("snapshot sha256 mismatch")


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


def _put(
    key: str,
    data: bytes | Path,
    *,
    spec: JobSpec,
    content_digest: str,
) -> None:
    if isinstance(data, Path):
        length = data.stat().st_size
        payload: Any = data.open("rb")
    else:
        length = len(data)
        payload = data
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        data=payload,
        method="PUT",
        headers={
            "content-length": str(length),
            "content-type": (
                "application/gzip" if isinstance(data, Path) else "application/json"
            ),
            "x-personal-job-id": spec.job_id,
            "x-personal-request-digest": spec.request_digest,
            "x-content-sha256": content_digest,
        },
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
            try:
                process = subprocess.run(
                    args,
                    cwd=os.environ.get("QP_REPO_ROOT", "/app"),
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                if timeout_seconds % 60 == 0:
                    limit = f"{int(timeout_seconds / 60)}-minute"
                else:
                    limit = f"{timeout_seconds:g}-second"
                raise RuntimeError(
                    f"qp-research exceeded the {limit} limit"
                ) from exc
            if process.returncode != 0:
                detail = " ".join(process.stderr.split())[-500:]
                raise RuntimeError(
                    f"qp-research exited {process.returncode}: "
                    f"{detail or 'no diagnostic'}"
                )
            lines = [line for line in process.stdout.splitlines() if line.strip()]
            if not lines:
                raise RuntimeError("qp-research emitted no result document")
            try:
                summary = json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                raise RuntimeError("qp-research result document is invalid") from exc
            if not isinstance(summary, dict):
                raise RuntimeError("qp-research result document is not an object")
            if (
                summary.get("candidate_count") != 4
                or summary.get("cohort_id") != spec.cohort_id
                or summary.get("cohort_digest") != spec.cohort_digest
                or summary.get("universe_id") != spec.universe_id
                or summary.get("universe_rule_digest")
                != spec.universe_rule_digest
                or summary.get("model_calls") != 0
                or summary.get("go") is not False
                or summary.get("ready_snapshot_declared") is not False
                or summary.get("live_orders_enabled") is not False
                or summary.get("automatic_promotion") is not False
            ):
                raise RuntimeError("qp-research violated the fixed personal policy")
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


JobSpecLike = JobSpec | PersonalSvi2023JobSpec
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
                "cohort_id": spec.cohort_id,
                "cohort_digest": spec.cohort_digest,
                "request_digest": spec.request_digest,
                "status": "QUEUED",
                "submitted_at": _now(),
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
            }
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
                "cohort_id": spec.cohort_id,
                "cohort_digest": spec.cohort_digest,
                "request_digest": spec.request_digest,
                "status": "FAILED",
                "error": _safe_detail(error),
                "go": False,
            }
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
        if self.path not in {"/v1/run", "/v1/run-svi-2023"}:
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        raw_length = self.headers.get("content-length", "")
        if not raw_length.isdigit() or not 0 < int(raw_length) <= MAX_REQUEST_BYTES:
            self._json({"error": "invalid_content_length"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            document = json.loads(self.rfile.read(int(raw_length)))
            spec = (
                PersonalSvi2023JobSpec.from_document(document)
                if self.path == "/v1/run-svi-2023"
                else JobSpec.from_document(document)
            )
            record = self.manager.submit(spec)
        except (json.JSONDecodeError, JobInputError, SviJobInputError) as error:
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
