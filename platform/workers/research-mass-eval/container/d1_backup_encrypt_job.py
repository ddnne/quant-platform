"""Container job: restore-validate-encrypt D1 SQL on ephemeral scratch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.encrypt_d1_backup import encrypt_backup, verify_encrypted

D1_BACKUP_ENCRYPT_FORMAT = "d1-backup-encrypt/v1"
QPDBENC2_MAX_FRAMING_BYTES = 8 + 4 + 64 * 1024 + 16
D1_BACKUP_MAX_SQL_BYTES = 4 * 1024 * 1024 * 1024
# Accepted restored sqlite after restore completes. Not a runtime disk cap.
D1_BACKUP_MAX_RESTORED_SQLITE_BYTES = 5 * 1024 * 1024 * 1024
D1_BACKUP_MAX_CIPHERTEXT_BYTES = D1_BACKUP_MAX_SQL_BYTES + QPDBENC2_MAX_FRAMING_BYTES
# standard-4 provisioned disk (image/files share it). Runtime structural bound.
STANDARD_4_PHYSICAL_DISK_BYTES = 20 * 1024 * 1024 * 1024
D1_EXPORT_ORIGIN = "http://d1.export"
_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CHUNK = 1024 * 1024


class D1BackupEncryptJobInputError(ValueError):
    """The Worker supplied a non-closed D1 backup encrypt job document."""


class D1BackupExportNotAuthorized(RuntimeError):
    """No approved D1 export handle is bound to this Container download."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_detail(error: BaseException) -> str:
    text = str(error)
    lowered = text.lower()
    for token in ("http://", "https://", "signed_url", "api_token", "secret", "password"):
        if token in lowered:
            return type(error).__name__
    return text[:240]


@dataclass(frozen=True, slots=True)
class D1BackupEncryptJobSpec:
    job_id: str
    request_digest: str
    manifest_key: str
    runner_version: str
    environment: str
    database_name: str
    database_id: str
    at_bookmark: str
    export_completed_at: str
    download_host: str
    signed_url_sha256: str
    format: str
    max_sql_bytes: int
    deployment_id: str
    release_source_sha: str

    @classmethod
    def from_document(cls, document: Any) -> "D1BackupEncryptJobSpec":
        if not isinstance(document, dict):
            raise D1BackupEncryptJobInputError("d1 backup job must be a JSON object")
        required = {
            "at_bookmark",
            "database_id",
            "database_name",
            "deployment_id",
            "download_host",
            "environment",
            "export_completed_at",
            "format",
            "job_id",
            "manifest_key",
            "max_sql_bytes",
            "release_source_sha",
            "request_digest",
            "runner_version",
            "signed_url_sha256",
        }
        if set(document) != required:
            raise D1BackupEncryptJobInputError("d1 backup job fields are closed")
        max_bytes = document["max_sql_bytes"]
        from personal_research_service import RUNNER_VERSION

        if type(max_bytes) is not int or max_bytes != D1_BACKUP_MAX_SQL_BYTES:
            raise D1BackupEncryptJobInputError("max_sql_bytes is invalid")
        string_fields = required - {"max_sql_bytes"}
        if not all(isinstance(document[field], str) for field in string_fields):
            raise D1BackupEncryptJobInputError("d1 backup string fields are closed")
        spec = cls(
            job_id=document["job_id"],
            request_digest=document["request_digest"],
            manifest_key=document["manifest_key"],
            runner_version=document["runner_version"],
            environment=document["environment"],
            database_name=document["database_name"],
            database_id=document["database_id"],
            at_bookmark=document["at_bookmark"],
            export_completed_at=document["export_completed_at"],
            download_host=document["download_host"],
            signed_url_sha256=document["signed_url_sha256"],
            format=document["format"],
            max_sql_bytes=max_bytes,
            deployment_id=document["deployment_id"],
            release_source_sha=document["release_source_sha"],
        )
        if spec.runner_version != RUNNER_VERSION:
            raise D1BackupEncryptJobInputError("runner version mismatch")
        spec.validate()
        return spec

    def validate(self) -> None:
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise D1BackupEncryptJobInputError("job_id is invalid")
        if self.environment not in {"staging", "production"}:
            raise D1BackupEncryptJobInputError("environment is invalid")
        if self.format != D1_BACKUP_ENCRYPT_FORMAT:
            raise D1BackupEncryptJobInputError("d1 backup format mismatch")
        if self.manifest_key != f"research/d1-backups/job={self.job_id}/manifest.json":
            raise D1BackupEncryptJobInputError("manifest_key is invalid")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise D1BackupEncryptJobInputError("request_digest is invalid")
        if _SHA_RE.fullmatch(self.release_source_sha) is None:
            raise D1BackupEncryptJobInputError("release_source_sha is invalid")


        from scripts.encrypt_d1_backup import _governed_database, _require_utc_timestamp

        governed = _governed_database(self.environment)
        if self.database_name != governed["name"] or self.database_id != governed["id"]:
            raise D1BackupEncryptJobInputError("export identity mismatch")
        if not self.at_bookmark.strip() or not self.download_host.strip():
            raise D1BackupEncryptJobInputError("export identity mismatch")
        _require_utc_timestamp(self.export_completed_at, "export_completed_at")
        if _DIGEST_RE.fullmatch(self.signed_url_sha256) is None:
            raise D1BackupEncryptJobInputError("export identity mismatch")


def spool_d1_export_sql(
    destination: Path,
    spec: D1BackupEncryptJobSpec,
    *,
    opener: Any = urllib.request,
) -> int:
    """Stream SQL through the Worker d1.export host. Never logs the URL."""
    request = urllib.request.Request(
        f"{D1_EXPORT_ORIGIN}/v1/download",
        method="GET",
        headers={
            "x-personal-job-id": spec.job_id,
            "x-personal-request-digest": spec.request_digest,
            "x-personal-job-kind": "d1-backup",
            "x-d1-export-url-sha256": spec.signed_url_sha256,
        },
    )
    try:
        response = opener.urlopen(request, timeout=1800)
    except urllib.error.HTTPError as error:
        if int(error.code) == 409:
            raise D1BackupExportNotAuthorized("export_not_authorized") from error
        raise RuntimeError(f"d1 export download returned {error.code}") from error
    written = 0
    with response, destination.open("xb") as handle:
        while True:
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > spec.max_sql_bytes:
                raise RuntimeError("d1 export exceeds sql byte bound")
            handle.write(chunk)
    if written < 1:
        raise RuntimeError("d1 export download was empty")
    os.chmod(destination, 0o600)
    return written


def fetch_backup_key(destination: Path, spec: D1BackupEncryptJobSpec) -> None:
    request = urllib.request.Request(
        f"{D1_EXPORT_ORIGIN}/v1/key",
        method="GET",
        headers={
            "x-personal-job-id": spec.job_id,
            "x-personal-request-digest": spec.request_digest,
            "x-personal-job-kind": "d1-backup",
            "x-d1-export-url-sha256": spec.signed_url_sha256,
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as error:
        if int(error.code) == 409:
            raise RuntimeError("backup_key_unavailable") from error
        raise RuntimeError(f"backup key download returned {error.code}") from error
    written = 0
    with response, destination.open("xb") as handle:
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            written += len(chunk)
            if written > 32:
                raise RuntimeError("backup_key_unavailable")
            handle.write(chunk)
    if written != 32:
        raise RuntimeError("backup_key_unavailable")
    os.chmod(destination, 0o600)


def failure_terminal(
    spec: D1BackupEncryptJobSpec,
    *,
    started_at: str,
    finished_at: str,
    error: str,
) -> dict[str, Any]:
    return {
        "schema_version": D1_BACKUP_ENCRYPT_FORMAT,
        "status": "FAILED",
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "environment": spec.environment,
        "runner_version": spec.runner_version,
        "deployment_id": spec.deployment_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
        "go": False,
        "eligibility": "BACKUP_ONLY",
    }


def execute_d1_backup_encrypt_job(
    spec: D1BackupEncryptJobSpec,
    *,
    work_root: Path,
    uploader: Callable[..., None],
    spooler: Callable[[Path, D1BackupEncryptJobSpec], int] = spool_d1_export_sql,
) -> dict[str, Any]:
    started_at = _now()
    job_root = Path(tempfile.mkdtemp(prefix=f"d1-backup-{spec.job_id}-", dir=work_root))
    previous_tmpdir = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(job_root)
    try:
        try:
            key_path = Path(os.environ.get("QP_D1_BACKUP_KEY_PATH") or "")
            if not key_path.is_file():
                key_path = job_root / "backup.key"
                fetch_backup_key(key_path, spec)
            sql_path = job_root / "export.sql"
            spooler(sql_path, spec)

            encrypted = job_root / "export.sql.enc"
            observed = encrypt_backup(
                sql_path,
                encrypted,
                key_path,
                environment=spec.environment,
                database_name=spec.database_name,
                database_id=spec.database_id,
                exported_at=spec.export_completed_at,
                release_source_sha=spec.release_source_sha,
                max_restored_sqlite_bytes=D1_BACKUP_MAX_RESTORED_SQLITE_BYTES,
            )
            verified = verify_encrypted(encrypted, key_path)
            if verified["plaintext_digest"] != observed["plaintext_digest"]:
                raise RuntimeError("encrypted backup verification mismatch")
            if int(observed["ciphertext_bytes"]) > D1_BACKUP_MAX_CIPHERTEXT_BYTES:
                raise RuntimeError("encrypted backup exceeds ciphertext byte bound")
            ciphertext_digest = str(observed["ciphertext_digest"])
            hex_digest = ciphertext_digest.removeprefix("sha256:")
            ciphertext_key = f"research/d1-backups/sha256={hex_digest}.sql.enc"
            uploader(
                ciphertext_key,
                encrypted,
                spec=spec,
                content_digest=ciphertext_digest,
                extra_headers={"content-type": "application/octet-stream"},
            )
            manifest = {
                "schema_version": D1_BACKUP_ENCRYPT_FORMAT,
                "status": "COMPLETED",
                "job_id": spec.job_id,
                "request_digest": spec.request_digest,
                "environment": spec.environment,
                "runner_version": spec.runner_version,
                "deployment_id": spec.deployment_id,
                "started_at": started_at,
                "finished_at": _now(),
                "at_bookmark": spec.at_bookmark,
                "export_completed_at": spec.export_completed_at,
                "signed_url_sha256": spec.signed_url_sha256,
                "ciphertext_key": ciphertext_key,
                "ciphertext_sha256": ciphertext_digest,
                "plaintext_bytes": observed["plaintext_bytes"],
                "plaintext_digest": observed["plaintext_digest"],
                "database": observed["database"],
                "restore": observed["restore"],
                "key_id": observed["key_id"],
                "go": False,
                "eligibility": "BACKUP_ONLY",
            }
        except Exception as error:
            manifest = failure_terminal(
                spec,
                started_at=started_at,
                finished_at=_now(),
                error=_safe_detail(error),
            )
        manifest_bytes = _canonical_bytes(manifest)
        uploader(
            spec.manifest_key,
            manifest_bytes,
            spec=spec,
            content_digest="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        )
        return manifest
    finally:
        if previous_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous_tmpdir
        shutil.rmtree(job_root, ignore_errors=True)
