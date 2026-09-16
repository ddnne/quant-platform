from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
import io
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_encrypt_d1_backup import governed_d1_export

JOB_PATH = (
    ROOT
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "container"
    / "d1_backup_encrypt_job.py"
)
SPEC = importlib.util.spec_from_file_location("d1_backup_encrypt_job", JOB_PATH)
assert SPEC is not None and SPEC.loader is not None
job = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = job
SPEC.loader.exec_module(job)

import scripts.encrypt_d1_backup as backup


@pytest.fixture
def hermetic_sqlite3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "sqlite3-test-cli"
    executable.write_text(
        f"""#!{sys.executable}
import sqlite3
import sys
if len(sys.argv) != 4 or sys.argv[1:3] != ["-batch", "-bail"]:
    raise SystemExit(2)
connection = sqlite3.connect(sys.argv[3])
try:
    connection.executescript(sys.stdin.read())
    connection.commit()
except (OSError, sqlite3.Error):
    connection.close()
    raise SystemExit(1)
connection.close()
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    original_which = backup.shutil.which

    def which(name: str) -> str | None:
        if name == "sqlite3":
            return str(executable)
        return original_which(name)

    monkeypatch.setattr(backup.shutil, "which", which)


def _spec() -> job.D1BackupEncryptJobSpec:
    return job.D1BackupEncryptJobSpec(
        job_id="d1b-test",
        request_digest="sha256:" + "a" * 64,
        manifest_key="research/d1-backups/job=d1b-test/manifest.json",
        runner_version="personal-cloud-runner/v15",
        environment="production",
        database_name="quant-ingest",
        database_id="be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
        at_bookmark="bm-1",
        export_completed_at="2026-09-16T05:00:00Z",
        download_host="acct.r2.cloudflarestorage.com",
        signed_url_sha256="sha256:" + "b" * 64,
        format=job.D1_BACKUP_ENCRYPT_FORMAT,
        max_sql_bytes=job.D1_BACKUP_MAX_SQL_BYTES,
        deployment_id="deploy-1",
        release_source_sha="a" * 40,
    )


def test_accepted_restored_sqlite_is_below_standard_4_physical_disk() -> None:
    assert job.D1_BACKUP_MAX_RESTORED_SQLITE_BYTES == 5 * 1024 * 1024 * 1024
    assert job.STANDARD_4_PHYSICAL_DISK_BYTES == 20 * 1024 * 1024 * 1024
    assert job.D1_BACKUP_MAX_RESTORED_SQLITE_BYTES < job.STANDARD_4_PHYSICAL_DISK_BYTES
    assert not hasattr(job, "D1_BACKUP_MAX_SCRATCH_BYTES")


def test_spool_streams_sql_from_export_origin(tmp_path: Path) -> None:
    body = b"CREATE TABLE t(id INTEGER);\n"

    class _Stream:
        def __init__(self, payload: bytes) -> None:
            self._buf = io.BytesIO(payload)

        def __enter__(self) -> "_Stream":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            return self._buf.read(size)

    class _Opener:
        def urlopen(self, request: urllib.request.Request, timeout: int | None = None) -> _Stream:
            assert request.full_url.endswith("/v1/download")
            assert "X-Amz-Signature" not in request.full_url
            return _Stream(body)

    destination = tmp_path / "export.sql"
    written = job.spool_d1_export_sql(destination, _spec(), opener=_Opener())
    assert written == len(body)
    assert destination.read_bytes() == body


def test_synthetic_sql_restores_encrypts_and_decrypts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermetic_sqlite3: None,
) -> None:
    source = governed_d1_export(tmp_path)
    key_path = tmp_path / "backup.key"
    backup.generate_key(key_path)
    monkeypatch.setenv("QP_D1_BACKUP_KEY_PATH", str(key_path))
    puts: dict[str, bytes] = {}

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        puts[key] = data.read_bytes() if hasattr(data, "read_bytes") else data

    def spooler(destination: Path, spec: job.D1BackupEncryptJobSpec) -> int:
        body = source.read_bytes()
        destination.write_bytes(body)
        return len(body)

    result = job.execute_d1_backup_encrypt_job(
        _spec(),
        work_root=tmp_path,
        uploader=uploader,
        spooler=spooler,
    )
    assert result["status"] == "COMPLETED"
    assert result["go"] is False
    assert result["eligibility"] == "BACKUP_ONLY"
    ciphertext_key = result["ciphertext_key"]
    assert ciphertext_key in puts
    assert _spec().manifest_key in puts
    enc = tmp_path / "roundtrip.sql.enc"
    enc.write_bytes(puts[ciphertext_key])
    verified = backup.verify_encrypted(enc, key_path)
    assert verified["plaintext_digest"] == result["plaintext_digest"]
    assert source.read_bytes()  # fixture file kept; job scratch deleted


def test_bad_schema_fails_before_ciphertext_put(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hermetic_sqlite3: None,
) -> None:
    key_path = tmp_path / "backup.key"
    backup.generate_key(key_path)
    monkeypatch.setenv("QP_D1_BACKUP_KEY_PATH", str(key_path))
    puts: dict[str, bytes] = {}

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        puts[key] = data.read_bytes() if hasattr(data, "read_bytes") else data

    def spooler(destination: Path, spec: job.D1BackupEncryptJobSpec) -> int:
        body = b"CREATE TABLE unrelated (id INTEGER);\n"
        destination.write_bytes(body)
        return len(body)

    result = job.execute_d1_backup_encrypt_job(
        _spec(),
        work_root=tmp_path,
        uploader=uploader,
        spooler=spooler,
    )
    assert result["status"] == "FAILED"
    assert not any(key.endswith(".sql.enc") for key in puts)
    assert _spec().manifest_key in puts


def test_unauthorized_export_does_not_put_ciphertext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "backup.key"
    backup.generate_key(key_path)
    monkeypatch.setenv("QP_D1_BACKUP_KEY_PATH", str(key_path))
    puts: dict[str, bytes] = {}

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        puts[key] = data.read_bytes() if hasattr(data, "read_bytes") else data

    class _Conflict:
        def urlopen(self, request: urllib.request.Request, timeout: int | None = None):
            raise urllib.error.HTTPError(
                "http://d1.export/v1/download",
                409,
                "conflict",
                None,
                None,
            )

    result = job.execute_d1_backup_encrypt_job(
        _spec(),
        work_root=tmp_path,
        uploader=uploader,
        spooler=lambda dest, spec: job.spool_d1_export_sql(dest, spec, opener=_Conflict()),
    )
    assert result["status"] == "FAILED"
    assert result["error"] == "export_not_authorized"
    assert not any(key.endswith(".sql.enc") for key in puts)
