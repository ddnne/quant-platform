from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import tarfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "container"
    / "personal_research_service.py"
)
SPEC = importlib.util.spec_from_file_location(
    "cloud_personal_research_service", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
service = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sqlite(path: Path) -> str:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence VALUES ('ok')")
    connection.commit()
    connection.close()
    return _digest(path)


COHORT_DIGEST = (
    "sha256:ea37baf3423e5d84e61d4c80c59bdfe8184342dd3dee28646bd339cd45085a84"
)
LONG_SHORT_COHORT_DIGEST = (
    "sha256:584bbf0052ad1eee6ec31cacdf1298c13c8a59b9eb6928267935fc17e34289be"
)


def _job(sha: str, job_id: str = "exact-four-test"):
    body = {
        "cohort_digest": COHORT_DIGEST,
        "cohort_id": "diverse-core-v1",
        "job_id": job_id,
        "period_end": "2026-08-27",
        "period_start": "2022-04-19",
        "runner_version": service.RUNNER_VERSION,
        "snapshot_key": f"research/personal/snapshots/sha256={sha}.sqlite",
        "snapshot_sha256": sha,
        "universe_id": "topix_all",
        "universe_rule_digest": (
            "sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048"
        ),
    }
    request_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return service.JobSpec.from_document(
        {
            **body,
            "request_digest": request_digest,
            "result_key": f"research/personal/jobs/job={job_id}/result.tar.gz",
            "manifest_key": f"research/personal/jobs/job={job_id}/manifest.json",
        }
    )


def _uploader(records: list[tuple[str, bytes, str]]):
    def upload(key, data, *, spec, content_digest):
        del spec
        body = data.read_bytes() if isinstance(data, Path) else bytes(data)
        records.append((key, body, content_digest))

    return upload


def test_snapshot_digest_mismatch_is_a_durable_failure(tmp_path: Path) -> None:
    expected = "a" * 64
    spec = _job(expected)
    uploads: list[tuple[str, bytes, str]] = []
    work = tmp_path / "work"
    work.mkdir()

    def wrong_snapshot(_spec, destination):
        destination.write_bytes(b"not the governed snapshot")

    manifest = service.execute_job(
        spec,
        work_root=work,
        command=(sys.executable, "unused.py"),
        downloader=wrong_snapshot,
        uploader=_uploader(uploads),
    )

    assert manifest["status"] == "FAILED"
    assert "sha256 mismatch" in manifest["error"]
    assert [key for key, _, _ in uploads] == [spec.manifest_key]
    assert not tuple(work.iterdir())


def test_snapshot_download_rejects_an_oversized_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Response:
        status = 200
        headers = {"content-length": str(service.MAX_SNAPSHOT_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    spec = _job("a" * 64)

    with pytest.raises(RuntimeError, match="content length"):
        service.download_snapshot(spec, tmp_path / "oversized.sqlite")

    assert not (tmp_path / "oversized.sqlite").exists()


def test_runner_timeout_is_failed_and_workspace_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(5)\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    monkeypatch.setenv("QP_REPO_ROOT", str(tmp_path))
    manifest = service.execute_job(
        spec,
        work_root=work,
        command=(sys.executable, str(script)),
        timeout_seconds=0.05,
        downloader=copy_snapshot,
        uploader=_uploader(uploads),
    )

    assert manifest["status"] == "FAILED"
    assert "0.05-second limit" in manifest["error"]
    assert not tuple(work.iterdir())


def test_default_timeout_keeps_room_for_durable_terminal_evidence() -> None:
    assert service.DEFAULT_TIMEOUT_SECONDS == 165 * 60
    assert service.MAX_JOB_LIFETIME_SECONDS == 180 * 60
    assert service.DEFAULT_TIMEOUT_SECONDS < service.MAX_JOB_LIFETIME_SECONDS


def _redigest(spec):
    return replace(spec, request_digest=spec.derived_request_digest())


def test_job_spec_accepts_long_short_on_a_broad_universe() -> None:
    spec = _redigest(
        replace(
            _job("a" * 64),
            cohort_id="sector-relative-ls-v1",
            cohort_digest=LONG_SHORT_COHORT_DIGEST,
        )
    )

    spec.validate()


def test_job_spec_rejects_a_non_personal_cohort() -> None:
    spec = replace(_job("a" * 64), cohort_id="unknown-cohort")

    with pytest.raises(service.JobInputError, match="cohort_id"):
        spec.validate()


def test_job_spec_rejects_an_open_or_prime_only_universe() -> None:
    spec = replace(_job("a" * 64), universe_id="prime")

    with pytest.raises(service.JobInputError, match="universe_id"):
        spec.validate()


def test_job_spec_rejects_a_compact_universe_with_a_sector_cohort() -> None:
    spec = replace(_job("a" * 64), universe_id="topix_core30")

    with pytest.raises(service.JobInputError, match="profile mismatch"):
        spec.validate()


def test_job_spec_rejects_long_short_on_a_compact_universe() -> None:
    spec = _redigest(
        replace(
            _job("a" * 64),
            cohort_id="sector-relative-ls-v1",
            cohort_digest=LONG_SHORT_COHORT_DIGEST,
            universe_id="topix_core30",
        )
    )

    with pytest.raises(service.JobInputError, match="profile mismatch"):
        spec.validate()


def test_success_archive_excludes_generated_sqlite_and_manifest_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    script = tmp_path / "fake_research.py"
    script.write_text(
        """
import json
import pathlib
import sys
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
(out / 'reports').mkdir(parents=True)
(out / 'snapshots').mkdir(parents=True)
(out / 'reports' / 'report.json').write_text('{\"ok\":true}')
(out / 'snapshots' / 'generated.sqlite').write_bytes(b'large-copy')
(out / 'snapshots' / 'generated.manifest.json').write_text('{\"snapshot\":true}')
print(json.dumps({
  'cohort_id': sys.argv[sys.argv.index('--cohort') + 1],
  'cohort_digest': 'sha256:ea37baf3423e5d84e61d4c80c59bdfe8184342dd3dee28646bd339cd45085a84',
  'universe_id': sys.argv[sys.argv.index('--universe') + 1],
  'universe_rule_digest': 'sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048',
  'report_id': 'sha256:' + '1' * 64,
  'snapshot_id': 'sha256:' + '2' * 64,
  'candidate_count': 4,
  'evaluated_count': 4,
  'hold_count': 1,
  'unexpected_errors': 0,
  'model_calls': 0,
  'go': False,
  'ready_snapshot_declared': False,
  'live_orders_enabled': False,
  'automatic_promotion': False,
}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    monkeypatch.setenv("QP_REPO_ROOT", str(tmp_path))
    manifest = service.execute_job(
        spec,
        work_root=work,
        command=(sys.executable, str(script)),
        downloader=copy_snapshot,
        uploader=_uploader(uploads),
    )

    assert manifest["status"] == "COMPLETED"
    assert manifest["candidate_count"] == 4
    assert manifest["cohort_id"] == "diverse-core-v1"
    assert manifest["cohort_digest"] == COHORT_DIGEST
    assert manifest["universe_id"] == "topix_all"
    assert manifest["universe_rule_digest"] == (
        "sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048"
    )
    assert manifest["model_calls"] == 0
    assert manifest["go"] is False
    assert manifest["ready_snapshot_declared"] is False
    assert manifest["automatic_promotion"] is False
    assert [key for key, _, _ in uploads] == [spec.result_key, spec.manifest_key]
    archive_path = tmp_path / "captured.tar.gz"
    archive_path.write_bytes(uploads[0][1])
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
        runner_summary_file = archive.extractfile("runner-summary.json")
        assert runner_summary_file is not None
        runner_summary = json.load(runner_summary_file)
    assert "reports/report.json" in names
    assert "snapshots/generated.manifest.json" in names
    assert all(not name.endswith(".sqlite") for name in names)
    assert runner_summary["go"] is False
    assert runner_summary["ready_snapshot_declared"] is False
    assert not tuple(work.iterdir())


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("go", True),
        ("ready_snapshot_declared", True),
    ),
)
def test_runner_summary_must_remain_no_go_and_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    summary = {
        "cohort_id": spec.cohort_id,
        "cohort_digest": spec.cohort_digest,
        "universe_id": spec.universe_id,
        "universe_rule_digest": spec.universe_rule_digest,
        "candidate_count": 4,
        "model_calls": 0,
        "go": False,
        "ready_snapshot_declared": False,
        "live_orders_enabled": False,
        "automatic_promotion": False,
    }
    summary[field] = invalid_value
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(summary) + "\n",
            stderr="",
        ),
    )
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
        command=(sys.executable, "unused.py"),
        downloader=copy_snapshot,
        uploader=_uploader(uploads),
    )

    assert manifest["status"] == "FAILED"
    assert "fixed personal policy" in manifest["error"]
    assert [key for key, _, _ in uploads] == [spec.manifest_key]
    assert not tuple(work.iterdir())


def test_result_archive_is_byte_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "output"
    (output / "reports").mkdir(parents=True)
    (output / "reports" / "report.json").write_text(
        '{"candidate_count":4}', encoding="utf-8"
    )
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    service.build_result_archive(output, first)
    time.sleep(1.1)
    service.build_result_archive(output, second)

    assert first.read_bytes() == second.read_bytes()


def test_manager_allows_only_one_active_job_and_same_job_is_idempotent() -> None:
    release = threading.Event()
    entered = threading.Event()
    terminal = threading.Event()

    def runner(spec):
        entered.set()
        assert release.wait(2)
        return {
            "job_id": spec.job_id,
            "request_digest": spec.request_digest,
            "status": "COMPLETED",
            "go": False,
        }

    manager = service.JobManager(runner, on_terminal=terminal.set)
    first = _job("a" * 64, "job-one")
    second = _job("b" * 64, "job-two")
    manager.submit(first)
    assert entered.wait(1)
    assert manager.submit(first)["job_id"] == "job-one"
    with pytest.raises(service.JobBusyError):
        manager.submit(second)
    release.set()
    for _ in range(100):
        if manager.status("job-one")["status"] == "COMPLETED":
            break
        time.sleep(0.01)
    assert manager.status("job-one")["status"] == "COMPLETED"
    assert terminal.wait(1)
    with pytest.raises(service.JobBusyError, match="shutting down"):
        manager.submit(second)


def test_absolute_watchdog_is_not_renewed_by_status_polling() -> None:
    release = threading.Event()
    entered = threading.Event()
    terminal = threading.Event()

    def runner(spec):
        entered.set()
        release.wait(2)
        return {
            "job_id": spec.job_id,
            "request_digest": spec.request_digest,
            "status": "COMPLETED",
            "go": False,
        }

    manager = service.JobManager(
        runner,
        on_terminal=terminal.set,
        max_job_seconds=0.05,
    )
    spec = _job("a" * 64, "watchdog-job")
    manager.submit(spec)
    assert entered.wait(1)
    deadline = time.monotonic() + 1
    while not terminal.is_set() and time.monotonic() < deadline:
        assert manager.status(spec.job_id) is not None
        time.sleep(0.005)

    assert terminal.is_set()
    assert manager.status(spec.job_id)["status"] == "FAILED"
    assert "absolute Container lifetime" in manager.status(spec.job_id)["error"]
    with pytest.raises(service.JobBusyError, match="shutting down"):
        manager.submit(_job("b" * 64, "second-job"))
    release.set()
