from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
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
from research.personal_base_sleeve import (
    EXPECTED_BASE_COHORT_DIGEST,
    EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
)
from research.personal_index_vol_overlay import canonical_trading_calendar_digest

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


def _job(
    sha: str,
    job_id: str = "exact-four-test",
    *,
    compressed: bool = False,
):
    body = {
        "cohort_digest": COHORT_DIGEST,
        "cohort_id": "diverse-core-v1",
        "job_id": job_id,
        "period_end": "2026-08-27",
        "period_start": "2022-04-19",
        "runner_version": service.RUNNER_VERSION,
        "snapshot_key": (
            f"research/personal/snapshots/sha256={sha}.sqlite"
            + (".gz" if compressed else "")
        ),
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


class _SnapshotResponse(io.BytesIO):
    status = 200

    def __init__(
        self,
        payload: bytes,
        declared_length: int | None = None,
        *,
        include_length: bool = True,
    ) -> None:
        super().__init__(payload)
        self.headers = (
            {
                "content-length": str(
                    len(payload) if declared_length is None else declared_length
                )
            }
            if include_length
            else {}
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _snapshot_transport(destination: Path) -> Path:
    return destination.with_name(f"{destination.name}.transport.gz")


def _assert_snapshot_files_absent(destination: Path) -> None:
    assert not destination.exists()
    assert not _snapshot_transport(destination).exists()


def _uploader(records: list[tuple[str, bytes, str]]):
    def upload(key, data, *, spec, content_digest):
        del spec
        body = data.read_bytes() if isinstance(data, Path) else bytes(data)
        records.append((key, body, content_digest))

    return upload


def _runner_summary(
    spec,
    *,
    evaluated_count: int = 4,
    hold_count: int = 1,
    unexpected_errors: int = 0,
) -> dict[str, object]:
    return {
        "cohort_id": spec.cohort_id,
        "cohort_digest": spec.cohort_digest,
        "universe_id": spec.universe_id,
        "universe_rule_digest": spec.universe_rule_digest,
        "report_id": "sha256:" + "1" * 64,
        "snapshot_id": "sha256:" + "2" * 64,
        "logical_data_snapshot_id": "sha256:" + "3" * 64,
        "report_json": "/missing/report.json",
        "report_markdown": "/missing/report.md",
        "candidate_count": 4,
        "evaluated_count": evaluated_count,
        "hold_count": hold_count,
        "unexpected_errors": unexpected_errors,
        "base_sleeve_artifact": None,
        "non_candidate_source_backtest_count": 0,
        "model_calls": 0,
        "estimated_ai_cost_usd": 0.0,
        "go": False,
        "ready_snapshot_declared": False,
        "live_orders_enabled": False,
        "automatic_promotion": False,
    }


def _base_sleeve_document(spec) -> dict[str, object]:
    source_dates = (spec.period_start, "2024-01-04", spec.period_end)
    return {
        "schema_version": "personal-base-sleeve-source/v1",
        "role": "INDEX_VOL_OVERLAY_BASE_SOURCE",
        "ranking_role": "NON_CANDIDATE_NOT_RANKED",
        "candidate_count_contribution": 0,
        "strategy": {
            "strategy_id": "personal_sector_balanced_four_factor_v1_ls",
            "strategy_spec_version": "1.0.0",
            "strategy_spec_digest": EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
            "dependency_closure_digest": "sha256:" + "6" * 64,
        },
        "cohort": {
            "cohort_id": "sector-relative-ls-v1",
            "cohort_digest": EXPECTED_BASE_COHORT_DIGEST,
        },
        "universe": {
            "universe_id": "topix_all",
            "universe_rule_digest": spec.universe_rule_digest,
            "resolved_membership_digest": "sha256:" + "7" * 64,
        },
        "snapshot": {
            "snapshot_id": "sha256:" + "2" * 64,
            "logical_data_snapshot_id": "sha256:" + "3" * 64,
        },
        "source_run": {
            "experiment_id": "base-source-experiment",
            "run_id": "base-source-run",
            "period": {"start": spec.period_start, "end": spec.period_end},
            "execution_mode": "next_close",
            "starting_capital": 1_000_000.0,
            "stock_one_way_cost_bps": 10.0,
            "short_financing_annual_rate": 0.03,
            "short_financing_trace_digest": "sha256:" + "8" * 64,
            "source_session_count": len(source_dates),
            "source_session_dates_digest": canonical_trading_calendar_digest(
                source_dates
            ),
            "paper_artifact": "paper/base.json",
            "risk_artifact": "risk/base.json",
            "terminal_positions": "NOT_FORCE_LIQUIDATED_BY_SOURCE_RUN",
        },
        "return_semantics": (
            "NET_AFTER_STOCK_EXECUTION_COSTS_AND_SHORT_FINANCING"
        ),
        "base_nav_semantics": "CONTINUOUS_PRE_EXISTING_INVESTABLE_NAV",
        "source_slice_wrapper_cost_semantics": (
            "EXCLUDES_NAV_WRAPPER_ENTRY_AND_LIQUIDATION"
        ),
        "wrapper_entry_cost_applied_to_source": False,
        "wrapper_liquidation_cost_applied_to_source": False,
        "daily_path": [
            {
                "date": source_dates[0],
                "equity": 999_000.0,
                "base_sleeve_return": -0.001,
            },
            {
                "date": source_dates[1],
                "equity": 1_000_000.0,
                "base_sleeve_return": 1_000_000.0 / 999_000.0 - 1.0,
            },
            {
                "date": source_dates[2],
                "equity": 1_001_000.0,
                "base_sleeve_return": 1_001_000.0 / 1_000_000.0 - 1.0,
            },
        ],
        "performance": {"schema_version": "personal-performance/v1"},
        "lifecycle": "DRAFT",
        "ready_snapshot_declared": False,
        "go": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
    }


def _write_base_sleeve_output(output: Path, spec) -> dict[str, object]:
    (output / "reports").mkdir(parents=True)
    (output / "paper").mkdir()
    (output / "risk").mkdir()
    (output / "base-sleeve").mkdir()
    (output / "reports" / "report.json").write_text('{"ok":true}')
    (output / "reports" / "report.md").write_text("# report")
    (output / "paper" / "base.json").write_text('{"paper":true}')
    (output / "risk" / "base.json").write_text('{"risk":true}')
    artifact_bytes = json.dumps(
        _base_sleeve_document(spec),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    archive_member = f"base-sleeve/{artifact_sha}.json"
    artifact_path = output / archive_member
    artifact_path.write_bytes(artifact_bytes)
    summary = _runner_summary(spec)
    summary.update(
        {
            "report_json": str(output / "reports" / "report.json"),
            "report_markdown": str(output / "reports" / "report.md"),
            "base_sleeve_artifact": {
                "schema_version": "personal-base-sleeve-reference/v1",
                "artifact_schema_version": "personal-base-sleeve-source/v1",
                "path": str(artifact_path),
                "archive_member": archive_member,
                "sha256": f"sha256:{artifact_sha}",
                "strategy_id": "personal_sector_balanced_four_factor_v1_ls",
                "cohort_id": "sector-relative-ls-v1",
                "universe_id": "topix_all",
                "role": "INDEX_VOL_OVERLAY_BASE_SOURCE",
                "ranking_role": "NON_CANDIDATE_NOT_RANKED",
                "candidate_count_contribution": 0,
            },
            "non_candidate_source_backtest_count": 1,
        }
    )
    return summary


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


def test_gzip_snapshot_download_expands_to_raw_digest_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"SQLite format 3\x00" + b"bounded-personal-snapshot" * 100
    packed = gzip.compress(raw, compresslevel=6, mtime=0)
    sha = hashlib.sha256(raw).hexdigest()
    spec = _job(sha, compressed=True)
    requests = []

    def open_snapshot(request, **_kwargs):
        requests.append(request)
        return _SnapshotResponse(packed)

    monkeypatch.setattr(service.urllib.request, "urlopen", open_snapshot)
    destination = tmp_path / "source.sqlite"

    service.download_snapshot(spec, destination)

    assert destination.read_bytes() == raw
    assert not _snapshot_transport(destination).exists()
    assert requests[0].full_url.endswith(f"sha256={sha}.sqlite.gz")
    assert requests[0].get_header("Accept") == "application/gzip"


def test_raw_snapshot_download_remains_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"SQLite format 3\x00" + b"raw-transport"
    sha = hashlib.sha256(raw).hexdigest()
    spec = _job(sha)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _SnapshotResponse(raw),
    )
    destination = tmp_path / "source.sqlite"

    service.download_snapshot(spec, destination)

    assert destination.read_bytes() == raw
    assert not _snapshot_transport(destination).exists()


def test_gzip_snapshot_download_requires_exact_transport_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"SQLite format 3\x00" + b"x" * 128
    packed = gzip.compress(raw, mtime=0)
    spec = _job(hashlib.sha256(raw).hexdigest(), compressed=True)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _SnapshotResponse(
            packed,
            declared_length=len(packed) + 1,
        ),
    )

    destination = tmp_path / "source.sqlite"
    with pytest.raises(RuntimeError, match="content length mismatch"):
        service.download_snapshot(spec, destination)

    _assert_snapshot_files_absent(destination)


@pytest.mark.parametrize(
    ("response", "error"),
    (
        (_SnapshotResponse(b"gzip", include_length=False), "content length"),
        (_SnapshotResponse(b"gzip", declared_length=3), "declared size bound"),
    ),
)
def test_gzip_snapshot_download_rejects_missing_or_short_transport_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: _SnapshotResponse,
    error: str,
) -> None:
    spec = _job("a" * 64, compressed=True)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    destination = tmp_path / "source.sqlite"
    with pytest.raises(RuntimeError, match=error):
        service.download_snapshot(spec, destination)

    _assert_snapshot_files_absent(destination)


@pytest.mark.parametrize(
    "corrupt",
    (
        b"not-a-gzip-stream",
        gzip.compress(b"SQLite format 3\x00" + b"truncated", mtime=0)[:-4],
    ),
)
def test_gzip_snapshot_download_rejects_corrupt_stream_and_removes_both_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt: bytes,
) -> None:
    spec = _job("a" * 64, compressed=True)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _SnapshotResponse(corrupt),
    )

    destination = tmp_path / "source.sqlite"
    with pytest.raises(RuntimeError, match="gzip stream is invalid"):
        service.download_snapshot(spec, destination)

    _assert_snapshot_files_absent(destination)


@pytest.mark.parametrize(("expanded_size", "fails"), ((1024, False), (1025, True)))
def test_gzip_snapshot_download_enforces_exact_raw_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expanded_size: int,
    fails: bool,
) -> None:
    raw = b"z" * expanded_size
    packed = gzip.compress(raw, mtime=0)
    spec = _job(hashlib.sha256(raw).hexdigest(), compressed=True)
    monkeypatch.setattr(service, "MAX_SNAPSHOT_BYTES", 1024)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _SnapshotResponse(packed),
    )

    destination = tmp_path / "source.sqlite"
    if fails:
        with pytest.raises(RuntimeError, match="expanded snapshot exceeds"):
            service.download_snapshot(spec, destination)
        _assert_snapshot_files_absent(destination)
    else:
        service.download_snapshot(spec, destination)
        assert destination.read_bytes() == raw
        assert not _snapshot_transport(destination).exists()


def test_gzip_snapshot_download_rejects_raw_sha_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"SQLite format 3\x00" + b"different"
    packed = gzip.compress(raw, mtime=0)
    spec = _job("a" * 64, compressed=True)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _SnapshotResponse(packed),
    )

    destination = tmp_path / "source.sqlite"
    with pytest.raises(RuntimeError, match="snapshot sha256 mismatch"):
        service.download_snapshot(spec, destination)

    _assert_snapshot_files_absent(destination)


def test_gzip_snapshot_download_rejects_empty_raw_and_cleans_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packed = gzip.compress(b"", mtime=0)
    spec = _job(hashlib.sha256(b"").hexdigest(), compressed=True)
    monkeypatch.setattr(
        service.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _SnapshotResponse(packed),
    )

    destination = tmp_path / "source.sqlite"
    with pytest.raises(RuntimeError, match="expanded snapshot is empty"):
        service.download_snapshot(spec, destination)

    _assert_snapshot_files_absent(destination)


@pytest.mark.parametrize(
    "preexisting_name", ("source.sqlite", "source.sqlite.transport.gz")
)
def test_snapshot_download_never_removes_preexisting_files(
    tmp_path: Path,
    preexisting_name: str,
) -> None:
    protected = tmp_path / preexisting_name
    protected.write_bytes(b"owned-by-caller")
    destination = tmp_path / "source.sqlite"
    spec = _job("a" * 64, compressed=True)

    with pytest.raises(RuntimeError, match="destination already exists"):
        service.download_snapshot(spec, destination)

    assert protected.read_bytes() == b"owned-by-caller"


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
(out / 'reports' / 'report.md').write_text('# report')
(out / 'snapshots' / 'generated.sqlite').write_bytes(b'large-copy')
(out / 'snapshots' / 'generated.manifest.json').write_text('{\"snapshot\":true}')
print(json.dumps({
  'cohort_id': sys.argv[sys.argv.index('--cohort') + 1],
  'cohort_digest': 'sha256:ea37baf3423e5d84e61d4c80c59bdfe8184342dd3dee28646bd339cd45085a84',
  'universe_id': sys.argv[sys.argv.index('--universe') + 1],
  'universe_rule_digest': 'sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048',
  'report_id': 'sha256:' + '1' * 64,
  'report_json': str(out / 'reports' / 'report.json'),
  'report_markdown': str(out / 'reports' / 'report.md'),
  'snapshot_id': 'sha256:' + '2' * 64,
  'logical_data_snapshot_id': 'sha256:' + '3' * 64,
  'candidate_count': 4,
  'evaluated_count': 4,
  'hold_count': 0,
  'unexpected_errors': 0,
  'base_sleeve_artifact': None,
  'non_candidate_source_backtest_count': 0,
  'model_calls': 0,
  'estimated_ai_cost_usd': 0.0,
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
    assert manifest["evaluated_count"] == 4
    assert manifest["hold_count"] == 0
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


def test_base_sleeve_reference_is_independent_of_candidate_evaluation_count(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _redigest(
        replace(
            _job(sha, job_id="base-sleeve-independent"),
            cohort_id="sector-relative-ls-v1",
            cohort_digest=LONG_SHORT_COHORT_DIGEST,
        )
    )
    output = tmp_path / "output"
    summary = _write_base_sleeve_output(output, spec)
    summary["evaluated_count"] = 1

    reference = service._validated_base_sleeve_reference(
        summary,
        spec=spec,
        output_root=output,
    )

    assert reference is not None
    assert reference["candidate_count_contribution"] == 0


def test_evaluated_long_short_result_requires_base_sleeve_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _redigest(
        replace(
            _job(sha, job_id="base-sleeve-required"),
            cohort_id="sector-relative-ls-v1",
            cohort_digest=LONG_SHORT_COHORT_DIGEST,
        )
    )
    output = tmp_path / "output"
    output.mkdir()
    evaluated = _runner_summary(spec, evaluated_count=4, hold_count=0)

    with pytest.raises(RuntimeError, match="requires a base sleeve source"):
        service._validated_base_sleeve_reference(
            evaluated,
            spec=spec,
            output_root=output,
        )

    no_analysis = _runner_summary(spec, evaluated_count=0, hold_count=0)
    assert (
        service._validated_base_sleeve_reference(
            no_analysis,
            spec=spec,
            output_root=output,
        )
        is None
    )


def test_long_short_archive_validates_and_preserves_non_candidate_base_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _redigest(
        replace(
            _job(sha, job_id="base-sleeve-source"),
            cohort_id="sector-relative-ls-v1",
            cohort_digest=LONG_SHORT_COHORT_DIGEST,
        )
    )

    def completed_source_run(args, **_kwargs):
        output = Path(args[args.index("--output") + 1])
        summary = _write_base_sleeve_output(output, spec)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(summary, sort_keys=True) + "\n",
            stderr="",
        )

    monkeypatch.setattr(service.subprocess, "run", completed_source_run)
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

    assert manifest["status"] == "COMPLETED"
    assert manifest["candidate_count"] == 4
    assert manifest["non_candidate_source_backtest_count"] == 1
    assert "path" not in manifest["base_sleeve_artifact"]
    archive_path = tmp_path / "base-sleeve-result.tar.gz"
    archive_path.write_bytes(uploads[0][1])
    with tarfile.open(archive_path, "r:gz") as archive:
        base_members = [
            name for name in archive.getnames() if name.startswith("base-sleeve/")
        ]
        assert len(base_members) == 1
        runner_summary_file = archive.extractfile("runner-summary.json")
        assert runner_summary_file is not None
        runner_summary = json.load(runner_summary_file)
    assert runner_summary["candidate_count"] == 4
    assert runner_summary["non_candidate_source_backtest_count"] == 1
    assert runner_summary["base_sleeve_artifact"]["archive_member"] == (
        base_members[0]
    )
    assert "path" not in runner_summary["base_sleeve_artifact"]
    assert not tuple(work.iterdir())


def test_exit_two_with_no_evaluated_candidates_archives_completed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    script = tmp_path / "no_analysis.py"
    summary = _runner_summary(spec, evaluated_count=0, hold_count=0)
    script.write_text(
        "\n".join(
            (
                "import json",
                "import pathlib",
                "import sys",
                "out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])",
                "(out / 'reports').mkdir(parents=True)",
                "(out / 'reports' / 'no-analysis.json').write_text('{\"status\":\"NO_ANALYSIS\"}')",
                "(out / 'reports' / 'no-analysis.md').write_text('# no analysis')",
                f"summary = {summary!r}",
                "summary['report_json'] = str(out / 'reports' / 'no-analysis.json')",
                "summary['report_markdown'] = str(out / 'reports' / 'no-analysis.md')",
                "print(json.dumps(summary, sort_keys=True))",
                "raise SystemExit(2)",
            )
        )
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
    assert manifest["evaluated_count"] == 0
    assert manifest["hold_count"] == 0
    assert manifest["unexpected_errors"] == 0
    assert [key for key, _, _ in uploads] == [spec.result_key, spec.manifest_key]
    archive_path = tmp_path / "captured-no-analysis.tar.gz"
    archive_path.write_bytes(uploads[0][1])
    with tarfile.open(archive_path, "r:gz") as archive:
        assert "reports/no-analysis.json" in archive.getnames()
        runner_summary_file = archive.extractfile("runner-summary.json")
        assert runner_summary_file is not None
        runner_summary = json.load(runner_summary_file)
    assert runner_summary["evaluated_count"] == 0
    assert runner_summary["unexpected_errors"] == 0
    assert not tuple(work.iterdir())


@pytest.mark.parametrize(
    ("returncode", "summary_changes", "stdout", "error"),
    (
        (2, {}, "{\n", "result document is invalid"),
        (2, {}, "", "emitted no result document"),
        (0, {"evaluated_count": 0, "hold_count": 0}, None, "contract mismatch"),
        (0, {"evaluated_count": 1, "hold_count": 0}, None, "fixed personal policy"),
        (2, {"evaluated_count": 4, "hold_count": 0}, None, "contract mismatch"),
        (
            2,
            {"evaluated_count": 0, "hold_count": 0, "unexpected_errors": 1},
            None,
            "fixed personal policy",
        ),
        (1, {"evaluated_count": 0, "hold_count": 0}, None, "exited 1"),
        (3, {"evaluated_count": 0, "hold_count": 0}, None, "exited 3"),
    ),
)
def test_runner_exit_and_summary_contract_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    summary_changes: dict[str, int],
    stdout: str | None,
    error: str,
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    summary = {**_runner_summary(spec), **summary_changes}
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=returncode,
            stdout=(json.dumps(summary) + "\n" if stdout is None else stdout),
            stderr="bounded diagnostic",
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
    assert error in manifest["error"]
    assert [key for key, _, _ in uploads] == [spec.manifest_key]
    assert not tuple(work.iterdir())


def test_completed_summary_requires_report_artifacts_inside_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)

    def missing_report_artifacts(args, **_kwargs):
        output = Path(args[args.index("--output") + 1])
        summary = _runner_summary(
            spec,
            evaluated_count=0,
            hold_count=0,
        )
        summary["report_json"] = str(output / "reports" / "missing.json")
        summary["report_markdown"] = str(output / "reports" / "missing.md")
        return SimpleNamespace(
            returncode=2,
            stdout=json.dumps(summary) + "\n",
            stderr="",
        )

    monkeypatch.setattr(service.subprocess, "run", missing_report_artifacts)
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
    assert "report_json artifact is invalid" in manifest["error"]
    assert [key for key, _, _ in uploads] == [spec.manifest_key]
    assert not tuple(work.iterdir())


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("go", True),
        ("ready_snapshot_declared", True),
        ("candidate_count", 4.0),
        ("model_calls", False),
        ("estimated_ai_cost_usd", False),
        ("report_id", "not-a-digest"),
        ("snapshot_id", "not-a-digest"),
        ("logical_data_snapshot_id", "not-a-digest"),
    ),
)
def test_runner_summary_must_remain_within_fixed_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    summary = _runner_summary(spec)
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
