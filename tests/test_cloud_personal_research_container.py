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
import urllib.error
import urllib.parse
from dataclasses import replace
from email.message import Message
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
AM_LONG_SHORT_COHORT_DIGEST = (
    "sha256:e12e65393985ab8b7cc2b0b922a362a055404777a49fda7250f735d47f0b073b"
)
AM_EXECUTION_CONTRACT_DIGEST = (
    "sha256:5fc214947a8fdde7005561820a9bf4b3c301154535b4dc37cff09e9d801bddac"
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


def test_research_process_timeout_kills_the_entire_new_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class FakeProcess:
        pid = 4321
        returncode = -9

        def communicate(self, timeout=None):
            calls.append(("communicate", timeout))
            if timeout is not None:
                raise service.subprocess.TimeoutExpired(["qp-research"], timeout)
            return "bounded stdout", "bounded stderr"

    def fake_popen(args, **kwargs):
        calls.append(("popen", tuple(args), kwargs))
        return FakeProcess()

    monkeypatch.setattr(service.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        service.os,
        "killpg",
        lambda process_group, used_signal: calls.append(
            ("killpg", process_group, used_signal)
        ),
    )

    with pytest.raises(service.subprocess.TimeoutExpired) as raised:
        service._run_research_process(
            ("qp-research",),
            cwd="/app",
            env={"PYTHONUNBUFFERED": "1"},
            timeout=0.25,
        )

    popen = next(call for call in calls if call[0] == "popen")
    assert popen[2]["start_new_session"] is True
    assert ("killpg", 4321, service.signal.SIGKILL) in calls
    assert ("communicate", None) in calls
    assert raised.value.output == "bounded stdout"
    assert raised.value.stderr == "bounded stderr"


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


def test_python_container_defaults_to_am_diverse_and_allows_am_ids() -> None:
    from research.factor_cohorts import get_research_cohort

    assert service.DEFAULT_PERSONAL_COHORT_ID == "diverse-core-am-pm-v1"
    for cohort_id in (
        "price-relative-am-pm-v1",
        "fundamental-relative-am-pm-v1",
        "diverse-core-am-pm-v1",
        "compact-market-diverse-am-pm-v1",
        "sector-relative-ls-am-pm-v1",
        "diverse-core-v1",
        "sector-relative-ls-v1",
        "compact-market-diverse-v1",
    ):
        assert cohort_id in service.PERSONAL_EXECUTABLE_COHORT_IDS
    am_digest = str(get_research_cohort("diverse-core-am-pm-v1").to_dict()["cohort_digest"])
    compact_digest = str(
        get_research_cohort("compact-market-diverse-am-pm-v1").to_dict()["cohort_digest"]
    )
    am = _redigest(
        replace(
            _job("a" * 64),
            cohort_id="diverse-core-am-pm-v1",
            cohort_digest=am_digest,
        )
    )
    am.validate()
    compact = _redigest(
        replace(
            _job("a" * 64),
            cohort_id="compact-market-diverse-am-pm-v1",
            cohort_digest=compact_digest,
            universe_id="topix_core30",
        )
    )
    compact.validate()
    with pytest.raises(service.JobInputError, match="profile mismatch"):
        replace(_job("a" * 64), universe_id="topix_core30").validate()
    with pytest.raises(service.JobInputError, match="profile mismatch"):
        _redigest(
            replace(
                _job("a" * 64),
                cohort_id="sector-relative-ls-am-pm-v1",
                universe_id="topix_core30",
            )
        ).validate()


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

    def completed_source_run(args, **kwargs):
        assert {
            key: kwargs["env"][key] for key in service._SINGLE_THREAD_NUMERIC_ENV
        } == service._SINGLE_THREAD_NUMERIC_ENV
        output = Path(args[args.index("--output") + 1])
        summary = _write_base_sleeve_output(output, spec)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(summary, sort_keys=True) + "\n",
            stderr="",
        )

    monkeypatch.setattr(service, "_run_research_process", completed_source_run)
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


def test_child_rejects_tampered_am_cohort_digest() -> None:
    sha = "a" * 64
    body = {
        "cohort_digest": "sha256:" + "f" * 64,
        "cohort_id": "sector-relative-ls-am-pm-v1",
        "job_id": "am-tamper",
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
    with pytest.raises(service.JobInputError, match="repository definition"):
        service.JobSpec.from_document(
            {
                **body,
                "request_digest": request_digest,
                "result_key": "research/personal/jobs/job=am-tamper/result.tar.gz",
                "manifest_key": "research/personal/jobs/job=am-tamper/manifest.json",
            }
        )


def test_am_job_binds_repo_mode_and_rejects_legacy_sleeve_reference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _redigest(
        replace(
            _job(sha, job_id="am-base-sleeve"),
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
        )
    )
    identity = service._personal_cohort_identity(spec.cohort_id)
    assert identity["execution_mode"] == "am_signal_pm_close"
    assert identity["execution_contract_digest"] == AM_EXECUTION_CONTRACT_DIGEST
    assert identity["session_view_digest"].startswith("sha256:")
    output = tmp_path / "output"
    summary = _write_base_sleeve_output(output, spec)
    with pytest.raises(RuntimeError, match="base sleeve reference is invalid"):
        service._validated_base_sleeve_reference(
            summary,
            spec=spec,
            output_root=output,
        )


def test_am_execute_job_rejects_tampered_child_execution_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _redigest(
        replace(
            _job(sha, job_id="am-mode-tamper"),
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
        )
    )

    def completed_source_run(args, **kwargs):
        output = Path(args[args.index("--output") + 1])
        summary = _write_base_sleeve_output(output, spec)
        summary["execution_mode"] = "next_close"
        summary["execution_contract_digest"] = "sha256:" + "c" * 64
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(summary, sort_keys=True) + "\n",
            stderr="",
        )

    monkeypatch.setattr(service, "_run_research_process", completed_source_run)
    work = tmp_path / "work"
    work.mkdir()

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
        command=(sys.executable, "unused.py"),
        downloader=copy_snapshot,
        uploader=_uploader([]),
    )
    assert manifest["status"] == "FAILED"
    assert "execution_mode" in manifest["error"]


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
        (1, {"evaluated_count": 0, "hold_count": 0}, "", "exited 1"),
        (1, {"evaluated_count": 0, "hold_count": 0}, "{\n", "exited 1"),
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
        service,
        "_run_research_process",
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


def test_exit1_empty_stderr_preserves_candidate_diagnostic_from_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)
    detail = "candidate process exited nonzero (1)"

    def failing_candidates(args, **_kwargs):
        output = Path(args[args.index("--output") + 1])
        reports = output / "reports"
        reports.mkdir()
        report = {
            "candidates": [
                {
                    "strategy_id": "personal_momentum_topk_hold10",
                    "decision": "SKIPPED",
                    "error": {
                        "type": "RuntimeError",
                        "detail": detail,
                    },
                },
                {
                    "strategy_id": "personal_momentum_topk_hold5",
                    "decision": "SKIPPED",
                    "error": {
                        "type": "RuntimeError",
                        "detail": detail,
                    },
                },
                {
                    "strategy_id": "personal_reversal_topk_hold5",
                    "decision": "SKIPPED",
                    "error": {
                        "type": "RuntimeError",
                        "detail": "/secret/path/db.sqlite " + detail,
                    },
                },
                {
                    "strategy_id": "personal_value_topk_hold10",
                    "decision": "SKIPPED",
                    "error": {
                        "type": "RuntimeError",
                        "detail": detail,
                    },
                },
            ],
            "summary": {"unexpected_errors": 4, "evaluated_count": 0},
        }
        report_json = reports / "report.json"
        report_md = reports / "report.md"
        report_json.write_text(json.dumps(report), encoding="utf-8")
        report_md.write_text("# failed candidates\n", encoding="utf-8")
        summary = _runner_summary(
            spec,
            evaluated_count=0,
            hold_count=0,
            unexpected_errors=4,
        )
        summary["report_json"] = str(report_json)
        summary["report_markdown"] = str(report_md)
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(summary) + "\n",
            stderr="",
        )

    monkeypatch.setattr(service, "_run_research_process", failing_candidates)
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
    assert "go" in manifest and manifest["go"] is False
    assert manifest.get("automatic_promotion") is False
    error = manifest["error"]
    assert "no diagnostic" not in error
    assert "candidate failures" in error
    assert "unexpected_errors=4" in error
    assert "personal_momentum_topk_hold10" in error
    assert "RuntimeError" in error
    assert "exited nonzero (1)" in error
    assert "repeated=RuntimeErrorx4" in error
    assert "/secret/path" not in error
    assert [key for key, _, _ in uploads] == [spec.manifest_key]
    assert spec.result_key not in {key for key, _, _ in uploads}
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

    monkeypatch.setattr(service, "_run_research_process", missing_report_artifacts)
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
        service,
        "_run_research_process",
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

    manager = service.JobManager(
        runner,
        on_terminal=terminal.set,
        terminal_uploader=lambda *args, **kwargs: None,
    )
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


def _research_period_document(period_start: str, period_end: str) -> dict:
    template = _job("a" * 64, "bound-2200")
    identity = {
        "cohort_digest": template.cohort_digest,
        "cohort_id": template.cohort_id,
        "job_id": "bound-2200",
        "period_end": period_end,
        "period_start": period_start,
        "runner_version": service.RUNNER_VERSION,
        "snapshot_key": template.snapshot_key,
        "snapshot_sha256": template.snapshot_sha256,
        "universe_id": template.universe_id,
        "universe_rule_digest": template.universe_rule_digest,
    }
    return {
        **identity,
        "manifest_key": "research/personal/jobs/job=bound-2200/manifest.json",
        "result_key": "research/personal/jobs/job=bound-2200/result.tar.gz",
        "request_digest": "sha256:" + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }


def test_inclusive_research_period_cap_is_2200_calendar_dates() -> None:
    service.JobSpec.from_document(
        _research_period_document("2020-01-01", "2026-01-08")
    )
    with pytest.raises(service.JobInputError, match="inclusive calendar dates"):
        service.JobSpec.from_document(
            _research_period_document("2020-01-01", "2026-01-09")
        )


def test_watchdog_writes_durable_failed_terminal_before_shutdown() -> None:
    entered = threading.Event()
    terminal = threading.Event()
    wrote = threading.Event()
    uploads: list[tuple[str, dict]] = []

    def runner(spec):
        entered.set()
        time.sleep(1)
        return {
            "job_id": spec.job_id,
            "request_digest": spec.request_digest,
            "status": "COMPLETED",
            "go": False,
        }

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        uploads.append((key, json.loads(data)))
        wrote.set()

    def on_terminal() -> None:
        assert wrote.is_set()
        terminal.set()

    manager = service.JobManager(
        runner,
        on_terminal=on_terminal,
        max_job_seconds=0.05,
        terminal_uploader=uploader,
    )
    spec = _job("a" * 64, "watchdog-r2")
    manager.submit(spec)
    assert entered.wait(1)
    assert terminal.wait(1)
    assert uploads
    assert uploads[0][0] == spec.manifest_key
    assert uploads[0][1]["status"] == "FAILED"
    assert "absolute Container lifetime" in uploads[0][1]["error"]
    assert manager.status(spec.job_id)["status"] == "FAILED"


def test_timeout_create_only_does_not_overwrite_completed_terminal() -> None:
    stored: dict[str, dict] = {}

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = json.loads(data)
        if key in stored:
            raise RuntimeError("R2 upload returned 409")
        stored[key] = body

    spec = _job("a" * 64, "race-job")
    stored[spec.manifest_key] = {
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "status": "COMPLETED",
    }
    manager = service.JobManager(
        lambda item: {
            "job_id": item.job_id,
            "request_digest": item.request_digest,
            "status": "COMPLETED",
            "go": False,
        },
        terminal_uploader=uploader,
        terminal_reader=lambda item: stored.get(item.manifest_key),
        max_job_seconds=30,
    )
    manager._jobs[spec.job_id] = {
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "status": "RUNNING",
        "submitted_at": service._now(),
        "go": False,
    }
    manager._specs[spec.job_id] = spec
    manager._active_job_id = spec.job_id
    manager._expire(spec.job_id)
    assert stored[spec.manifest_key]["status"] == "COMPLETED"
    assert manager.status(spec.job_id)["status"] == "FAILED"


def test_terminal_upload_retries_then_shuts_down() -> None:
    attempts = {"n": 0}
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("R2 upload returned 503")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        retry_schedule=(0.01, 0.01),
        max_job_seconds=30,
    )
    try:
        manager.submit(_job("a" * 64, "retry-terminal"))
        assert terminal.wait(1)
        assert attempts["n"] == 3
        assert manager._retry_timer is None
        assert manager._pending_terminal is None
        assert manager._shutdown_notified is True
    finally:
        if manager._retry_timer is not None:
            manager._retry_timer.cancel()


def test_terminal_publication_retries_below_cap_without_shutdown() -> None:
    attempts = {"n": 0}
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        attempts["n"] += 1
        raise RuntimeError("R2 upload returned 429")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        retry_schedule=(0.01,),
        max_job_seconds=30,
    )
    try:
        manager.submit(_job("a" * 64, "retry-below-cap"))
        deadline = time.monotonic() + 0.2
        while attempts["n"] < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert 2 <= attempts["n"] < manager._MAX_TERMINAL_PUT_ATTEMPTS
        assert not terminal.is_set()
        assert manager._shutdown_notified is False
        assert manager._retry_timer is not None
        assert manager._pending_terminal is not None
    finally:
        if manager._retry_timer is not None:
            manager._retry_timer.cancel()
        manager._pending_terminal = None
        manager._shutdown_notified = True


def test_terminal_publication_retry_exhaustion_shuts_down(capsys) -> None:
    attempts = {"n": 0}
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        attempts["n"] += 1
        raise RuntimeError("R2 upload returned 503")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        retry_schedule=(0.001,),
        max_job_seconds=30,
    )
    try:
        manager.submit(_job("a" * 64, "retry-exhausted"))
        assert terminal.wait(1)
        assert attempts["n"] == manager._MAX_TERMINAL_PUT_ATTEMPTS
        assert manager._retry_timer is None
        assert manager._pending_terminal is None
        assert manager._shutdown_notified is True
        events = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("{")
        ]
        exhausted = [
            event
            for event in events
            if event.get("event") == "terminal_publication_retry_exhausted"
        ]
        assert len(exhausted) == 1
        assert exhausted[0]["job_id"] == "retry-exhausted"
        assert exhausted[0]["attempts"] == manager._MAX_TERMINAL_PUT_ATTEMPTS
        assert exhausted[0]["go"] is False
    finally:
        if manager._retry_timer is not None:
            manager._retry_timer.cancel()


def test_terminal_publication_succeeds_on_later_retry_below_cap() -> None:
    attempts = {"n": 0}
    terminal = threading.Event()
    limit = service.JobManager._MAX_TERMINAL_PUT_ATTEMPTS

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        attempts["n"] += 1
        if attempts["n"] < limit:
            raise RuntimeError("R2 upload returned 503")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        retry_schedule=(0.001,),
        max_job_seconds=30,
    )
    try:
        manager.submit(_job("a" * 64, "retry-last-ok"))
        assert terminal.wait(1)
        assert attempts["n"] == limit
        assert manager._retry_timer is None
        assert manager._pending_terminal is None
        assert manager._shutdown_notified is True
    finally:
        if manager._retry_timer is not None:
            manager._retry_timer.cancel()


def test_unavailable_terminal_upload_does_not_shutdown() -> None:
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        raise RuntimeError("R2 upload returned 503")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        retry_schedule=(0.05, 0.05),
        max_job_seconds=30,
    )
    try:
        manager.submit(_job("a" * 64, "no-shutdown"))
        assert not terminal.wait(0.2)
        assert manager.status("no-shutdown")["status"] == "FAILED"
        with pytest.raises(service.JobBusyError):
            manager.submit(_job("b" * 64, "other"))
    finally:
        if manager._retry_timer is not None:
            manager._retry_timer.cancel()
        manager._pending_terminal = None
        manager._shutdown_notified = True


def test_matching_existing_terminal_is_accepted() -> None:
    stored: dict[str, dict] = {}
    terminal = threading.Event()
    spec = _job("a" * 64, "existing-ok")
    stored[spec.manifest_key] = {
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "runner_version": spec.runner_version,
        "cohort_id": spec.cohort_id,
        "universe_id": spec.universe_id,
        "status": "FAILED",
    }

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del data, spec, content_digest, extra_headers
        raise RuntimeError("R2 upload returned 409")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        terminal_reader=lambda item: stored.get(item.manifest_key),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert terminal.wait(1)


def test_conflicting_terminal_shuts_down_fail_closed() -> None:
    stored: dict[str, dict] = {}
    terminal = threading.Event()
    spec = _job("a" * 64, "conflict-term")
    stored[spec.manifest_key] = {
        "job_id": spec.job_id,
        "request_digest": "sha256:" + "c" * 64,
        "runner_version": spec.runner_version,
        "cohort_id": spec.cohort_id,
        "universe_id": spec.universe_id,
        "status": "FAILED",
    }

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del data, spec, content_digest, extra_headers
        raise RuntimeError("R2 upload returned 409")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        terminal_reader=lambda item: stored.get(item.manifest_key),
        retry_schedule=(0.05,),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert terminal.wait(1)
    assert manager._shutdown_notified is True
    assert manager.status(spec.job_id)["status"] == "FAILED"


def test_watchdog_and_normal_race_keeps_one_terminal() -> None:
    stored: dict[str, dict] = {}
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = json.loads(data)
        if key in stored:
            raise RuntimeError("R2 upload returned 409")
        stored[key] = body

    spec = _job("a" * 64, "one-terminal")
    manager = service.JobManager(
        lambda item: {
            "job_id": item.job_id,
            "request_digest": item.request_digest,
            "status": "COMPLETED",
            "go": False,
        },
        on_terminal=terminal.set,
        terminal_uploader=uploader,
        terminal_reader=lambda item: stored.get(item.manifest_key),
        max_job_seconds=0.05,
    )
    manager.submit(spec)
    assert terminal.wait(1)
    assert stored[spec.manifest_key]["status"] in {"COMPLETED", "FAILED"}
    assert list(stored) == [spec.manifest_key]


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

    uploads: list[str] = []

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del data, spec, content_digest, extra_headers
        uploads.append(key)

    manager = service.JobManager(
        runner,
        on_terminal=terminal.set,
        max_job_seconds=0.05,
        terminal_uploader=uploader,
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


class _UrlResponse(io.BytesIO):
    def __init__(self, status: int, body: bytes):
        super().__init__(body)
        self.status = status
        self.headers = {"content-type": "application/json; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _ProductionR2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts = 0
        self.gets = 0

    def urlopen(self, request, timeout=None):
        del timeout
        url = request.full_url
        key = urllib.parse.urlparse(url).path.lstrip("/")
        method = request.get_method()
        headers = {name.lower(): value for name, value in request.header_items()}
        if method == "PUT":
            self.puts += 1
            if key in self.objects:
                raise urllib.error.HTTPError(
                    url, 409, "conflict", Message(), io.BytesIO(b"")
                )
            payload = request.data
            if not isinstance(payload, (bytes, bytearray)):
                payload = payload.read()
            self.objects[key] = bytes(payload)
            return _UrlResponse(201, b'{"ok":true,"created":true}')
        if method == "GET":
            self.gets += 1
            raw = self.objects.get(key)
            if raw is None or not key.endswith("/manifest.json"):
                raise urllib.error.HTTPError(
                    url, 403, "denied", Message(), io.BytesIO(b"")
                )
            parsed = json.loads(raw)
            required = {
                "x-personal-job-id",
                "x-personal-request-digest",
                "x-personal-runner-version",
                "x-personal-job-kind",
                "x-personal-cohort-id",
                "x-personal-universe-id",
            }
            personal = {name for name in headers if name.startswith("x-personal-")}
            if personal != required:
                raise urllib.error.HTTPError(
                    url, 403, "denied", Message(), io.BytesIO(b"")
                )
            if (
                headers.get("x-personal-job-id") != parsed.get("job_id")
                or headers.get("x-personal-request-digest")
                != parsed.get("request_digest")
                or headers.get("x-personal-runner-version")
                != parsed.get("runner_version")
                or headers.get("x-personal-job-kind") != "research"
                or headers.get("x-personal-cohort-id") != parsed.get("cohort_id")
                or headers.get("x-personal-universe-id") != parsed.get("universe_id")
            ):
                raise urllib.error.HTTPError(
                    url, 403, "denied", Message(), io.BytesIO(b"")
                )
            return _UrlResponse(200, raw)
        raise AssertionError(method)


def test_production_conflict_reads_matching_terminal_without_injected_reader(
    monkeypatch,
) -> None:
    fake = _ProductionR2()
    spec = _job("a" * 64, "prod-conflict")
    existing = {
        **service._manifest_base(
            spec, started_at=service._now(), finished_at=service._now()
        ),
        "status": "FAILED",
        "error": "absolute Container lifetime exceeded (0.05s)",
    }
    fake.objects[spec.manifest_key] = service._canonical_bytes(existing)
    monkeypatch.setattr(service.urllib.request, "urlopen", fake.urlopen)
    terminal = threading.Event()
    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.01,),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert terminal.wait(1)
    assert fake.puts >= 1
    assert fake.gets >= 1
    assert manager._shutdown_notified is True


def test_production_mismatched_terminal_shuts_down_fail_closed(monkeypatch) -> None:
    fake = _ProductionR2()
    spec = _job("a" * 64, "prod-mismatch")
    existing = {
        **service._manifest_base(
            spec, started_at=service._now(), finished_at=service._now()
        ),
        "status": "FAILED",
        "error": "other",
        "request_digest": "sha256:" + "c" * 64,
    }
    fake.objects[spec.manifest_key] = service._canonical_bytes(existing)
    monkeypatch.setattr(service.urllib.request, "urlopen", fake.urlopen)
    terminal = threading.Event()
    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05,),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert terminal.wait(1)
    assert manager._shutdown_notified is True
    assert manager.status(spec.job_id)["status"] == "FAILED"


def _put_then_get_404(monkeypatch, *, put_error):
    class _MissingAfterPut:
        def __init__(self) -> None:
            self.puts = 0
            self.gets = 0

        def urlopen(self, request, timeout=None):
            del timeout
            url = request.full_url
            method = request.get_method()
            if method == "PUT":
                self.puts += 1
                raise put_error(url)
            if method == "GET":
                self.gets += 1
                raise urllib.error.HTTPError(
                    url, 404, "not found", Message(), io.BytesIO(b"")
                )
            raise AssertionError(method)

    fake = _MissingAfterPut()
    monkeypatch.setattr(service.urllib.request, "urlopen", fake.urlopen)
    return fake


@pytest.mark.parametrize("status", (400, 403))
def test_deterministic_put_then_terminal_get_404_shuts_down_fail_closed(
    monkeypatch, status: int
) -> None:
    fake = _put_then_get_404(
        monkeypatch,
        put_error=lambda url: urllib.error.HTTPError(
            url, status, "denied", Message(), io.BytesIO(b"")
        ),
    )
    terminal = threading.Event()
    spec = _job("a" * 64, f"denied-put-{status}")
    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05, 0.05),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert terminal.wait(1)
    assert fake.puts == 1
    assert manager._shutdown_notified is True
    assert manager.status(spec.job_id)["status"] == "FAILED"


def test_failed_upload_then_terminal_get_404_retries(monkeypatch) -> None:
    fake = _put_then_get_404(
        monkeypatch,
        put_error=lambda url: urllib.error.HTTPError(
            url, 503, "unavailable", Message(), io.BytesIO(b"")
        ),
    )
    terminal = threading.Event()
    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05, 0.05),
        max_job_seconds=30,
    )
    manager.submit(_job("a" * 64, "missing-after-put"))
    assert not terminal.wait(0.2)
    assert fake.puts >= 2
    assert fake.gets >= 1
    assert manager._shutdown_notified is False
    assert manager.status("missing-after-put")["status"] == "FAILED"
    if manager._retry_timer is not None:
        manager._retry_timer.cancel()


def test_transport_error_then_terminal_get_404_retries(monkeypatch) -> None:
    fake = _put_then_get_404(
        monkeypatch,
        put_error=lambda url: urllib.error.URLError("connection reset"),
    )
    terminal = threading.Event()
    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05, 0.05),
        max_job_seconds=30,
    )
    manager.submit(_job("a" * 64, "transport-after-put"))
    assert not terminal.wait(0.2)
    assert fake.puts >= 2
    assert fake.gets >= 1
    assert manager._shutdown_notified is False
    assert manager.status("transport-after-put")["status"] == "FAILED"
    if manager._retry_timer is not None:
        manager._retry_timer.cancel()


def test_child_put_keeps_http_error_for_deterministic_rejection(
    monkeypatch,
) -> None:
    spec = _job("a" * 64, "child-put-403")

    def urlopen(request, timeout=None):
        del timeout
        raise urllib.error.HTTPError(
            request.full_url, 403, "denied", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError) as caught:
        service._put(
            spec.result_key,
            b"{}",
            spec=spec,
            content_digest="sha256:" + "a" * 64,
        )
    assert caught.value.code == 403
    with pytest.raises(service.TerminalReadDenied, match="terminal PUT denied HTTP 403"):
        service._put(
            spec.manifest_key,
            b"{}",
            spec=spec,
            content_digest="sha256:" + "a" * 64,
        )


def _overlay_spec(job_id: str = "overlay-headers"):
    prefix = f"research/personal/index-vol-overlay-2023/job={job_id}"
    body = {
        "base_job_id": "base-r2",
        "cohort_id": "personal-index-vol-overlay-2023-v1",
        "input_manifest_digest": "sha256:" + "b" * 64,
        "input_manifest_key": f"{prefix}/input-manifest.json",
        "job_id": job_id,
        "manifest_key": f"{prefix}/manifest.json",
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": "personal-index-vol-overlay-cloud-runner/v1",
        "svi_job_id": "svi-r2",
    }
    provisional = service.PersonalIndexVolOverlay2023JobSpec(**body)
    return service.PersonalIndexVolOverlay2023JobSpec.from_document(
        {**body, "request_digest": provisional.derived_request_digest()}
    )


def test_overlay_terminal_put_uses_family_identity_headers(monkeypatch) -> None:
    spec = _overlay_spec()
    seen: dict[str, str] = {}

    def urlopen(request, timeout=None):
        del timeout
        seen.update({name.lower(): value for name, value in request.header_items()})
        return _UrlResponse(201, b'{"ok":true,"created":true}')

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen)
    service._put(
        spec.manifest_key,
        b"{}",
        spec=spec,
        content_digest="sha256:" + "a" * 64,
    )
    assert seen["x-overlay-job-id"] == spec.job_id
    assert seen["x-overlay-input-manifest-key"] == spec.input_manifest_key
    assert seen["x-overlay-input-manifest-digest"] == spec.input_manifest_digest
    assert seen["x-personal-job-id"] == spec.job_id
    assert seen["x-personal-request-digest"] == spec.request_digest
