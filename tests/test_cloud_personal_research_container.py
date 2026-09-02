from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import multiprocessing
import os
import signal
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
from core.result import BacktestResult
from personal_history_compact_support import (
    insert_compact_bar,
    insert_compact_master,
    install_compact_schema,
    stamp_compact_manifest,
)
from research.factor_cohorts import (
    AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT,
    PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID,
    get_research_cohort,
    is_am_pm_factor_cohort,
    personal_specs_for_cohort,
)
from research.personal_base_sleeve import (
    AM_PM_BASE_SLEEVE_ID,
    EXPECTED_BASE_COHORT_DIGEST,
    EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
    PERSONAL_BASE_SLEEVE_AM_PM_ARTIFACT_SCHEMA,
    PERSONAL_BASE_SLEEVE_RANKING_ROLE,
    PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
    PERSONAL_BASE_SLEEVE_ROLE,
    build_personal_base_sleeve_am_pm_artifact,
)
from test_personal_base_sleeve_am_pm import _build as _build_am_sleeve
from research.personal_universe import (
    personal_research_universe_decision_cutoff,
    personal_research_universe_rule_digest,
    personal_universe_selector,
)
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from strategies.paper import Lifecycle, PaperRunResult

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

PROCESS_CONTEXT = multiprocessing.get_context("fork")


def _job_manager(runner, **kwargs):
    return service.JobManager(runner, process_context=PROCESS_CONTEXT, **kwargs)


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
    "sha256:0c9fc5cba93c68cbfec3951a56f09949674c1a01cb4d4d4cf406082c01033c10"
)
LONG_SHORT_COHORT_DIGEST = (
    "sha256:6e4de725046c0b0e55416891d83580b9acb753c00a2beecfd3a26ee0c87a74f9"
)
AM_LONG_SHORT_COHORT_DIGEST = (
    "sha256:9d4135b9b78ad16d071f8a0b26a88b29d315c4d53eace3cb7600aaccf450b73c"
)
AM_EXECUTION_CONTRACT_DIGEST = (
    "sha256:5fc214947a8fdde7005561820a9bf4b3c301154535b4dc37cff09e9d801bddac"
)


def _job(
    sha: str,
    job_id: str = "exact-four-test",
    *,
    compressed: bool = False,
    cohort_id: str = "diverse-core-am-pm-v1",
    universe_id: str = "topix_all",
    cohort_digest: str | None = None,
    universe_rule_digest: str | None = None,
):
    body = {
        "cohort_digest": cohort_digest
        or str(get_research_cohort(cohort_id).to_dict()["cohort_digest"]),
        "cohort_id": cohort_id,
        "job_id": job_id,
        "period_end": "2026-08-27",
        "period_start": "2022-04-19",
        "runner_version": service.RUNNER_VERSION,
        "snapshot_key": (
            f"research/personal/snapshots/sha256={sha}.sqlite"
            + (".gz" if compressed else "")
        ),
        "snapshot_sha256": sha,
        "universe_id": universe_id,
        "universe_rule_digest": universe_rule_digest
        or personal_research_universe_rule_digest(
            universe_id, am_pm=is_am_pm_factor_cohort(cohort_id)
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


def _manager_completed_result(spec) -> dict:
    now = service._now()
    return {
        **service._manifest_base(spec, started_at=now, finished_at=now),
        "status": "COMPLETED",
    }


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
    summary: dict[str, object] = {
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
    if is_am_pm_factor_cohort(spec.cohort_id):
        summary.update(
            {
                "execution_mode": "am_signal_pm_close",
                "execution_contract_digest": AM_EXECUTION_CONTRACT_DIGEST,
            }
        )
    return summary


def _artifact(member: str):
    return SimpleNamespace(archive_member=member)


def _direct_run_from_summary(
    summary: dict[str, object],
    output: Path,
    *,
    exit_code: int = 0,
):
    reports = output / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    if not (reports / "report.json").exists():
        (reports / "report.json").write_text('{"ok":true}', encoding="utf-8")
    if not (reports / "report.md").exists():
        (reports / "report.md").write_text("# report", encoding="utf-8")
    snapshots = output / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    (snapshots / "generated.sqlite").write_bytes(b"large-copy")
    (snapshots / "generated.manifest.json").write_text(
        '{"snapshot":true}', encoding="utf-8"
    )
    return SimpleNamespace(
        report_id=summary["report_id"],
        report_json=_artifact("reports/report.json"),
        report_markdown=_artifact("reports/report.md"),
        snapshot=SimpleNamespace(
            snapshot_id=summary["snapshot_id"],
            logical_data_snapshot_id=summary["logical_data_snapshot_id"],
        ),
        candidate_count=summary["candidate_count"],
        evaluated_count=summary["evaluated_count"],
        hold_count=summary["hold_count"],
        unexpected_errors=summary["unexpected_errors"],
        cohort_id=summary["cohort_id"],
        cohort_digest=summary["cohort_digest"],
        universe_id=summary["universe_id"],
        universe_rule_digest=summary["universe_rule_digest"],
        execution_mode=summary.get(
            "execution_mode",
            service._personal_cohort_identity(str(summary["cohort_id"]))[
                "execution_mode"
            ],
        ),
        execution_contract_digest=summary.get(
            "execution_contract_digest",
            service._personal_cohort_identity(str(summary["cohort_id"])).get(
                "execution_contract_digest"
            ),
        ),
        base_sleeve_artifact=summary.get("base_sleeve_artifact"),
        non_candidate_source_backtest_count=summary.get(
            "non_candidate_source_backtest_count", 0
        ),
        go=summary.get("go", False),
        ready_snapshot_declared=summary.get("ready_snapshot_declared", False),
        live_orders_enabled=summary.get("live_orders_enabled", False),
        automatic_promotion=summary.get("automatic_promotion", False),
        model_calls=summary.get("model_calls", 0),
        estimated_ai_cost_usd=summary.get("estimated_ai_cost_usd", 0.0),
        exit_code=exit_code,
    )


def _base_sleeve_document(spec) -> dict[str, object]:
    source_dates = (spec.period_start, "2024-01-04", spec.period_end)
    quality = {
        "comparable": True,
        "selection_eligible": True,
        "comparison_eligible": True,
        "incomplete_valuation": False,
        "skipped_decision_count": 0,
        "incomplete_valuation_count": 0,
        "unfilled_order_count": 0,
        "skipped_decision_dates": [],
        "incomplete_valuation_dates": [],
        "missing_fill_dates": [],
        "non_comparable_session_dates": [],
        "incomplete_valuation_codes": [],
        "missing_fill_codes": [],
        "held_missing_morning_adjustment_close": [],
        "held_missing_afternoon_adjustment_close": [],
        "missing_afternoon_adjustment_close_unfilled": [],
    }
    strategy = next(
        candidate
        for candidate in personal_specs_for_cohort(
            PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID,
            universe_id="topix_all",
        )
        if candidate.strategy_id == AM_PM_BASE_SLEEVE_ID
    )
    result = PaperRunResult(
        experiment_id="base-source-experiment",
        run_id="base-source-run",
        lifecycle=Lifecycle.DRAFT,
        backtest=BacktestResult(
            equity_curve=[
                {"date": day, "signal_equity": nav, "equity": nav}
                for day, nav in zip(
                    source_dates,
                    (999_000.0, 1_000_000.0, 1_001_000.0),
                    strict=True,
                )
            ],
            trades=[],
            metrics={"comparable": True},
            metadata={
                "execution_mode": "am_signal_pm_close",
                "session_view_digest": service._personal_cohort_identity(
                    spec.cohort_id
                )["session_view_digest"],
                "data_quality": quality,
            },
        ),
        reproducibility={
            "execution_mode": "am_signal_pm_close",
            "period": {"start": spec.period_start, "end": spec.period_end},
            "starting_capital": 1_000_000.0,
            "strategy_id": AM_PM_BASE_SLEEVE_ID,
            "resolved_universe_digest": "sha256:" + "7" * 64,
        },
    )
    return build_personal_base_sleeve_am_pm_artifact(
        result=result,
        evidence={
            "cost_bps": 10.0,
            "execution_mode": "am_signal_pm_close",
            "execution_contract": dict(AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT),
            "short_financing": {
                "annual_rate": 0.03,
                "baseline": True,
                "modelled_assumption": True,
                "borrow_evidence": False,
                "trace_digest": "sha256:" + "8" * 64,
            },
            "paper_artifact": "paper/base.json",
            "risk_artifact": "risk/base.json",
            "performance": {"schema_version": "personal-performance/v1"},
        },
        spec=strategy,
        dependency_closure_digest="sha256:" + "6" * 64,
        cohort_digest=spec.cohort_digest,
        universe_id="topix_all",
        universe_rule_digest=spec.universe_rule_digest,
        resolved_membership_digest="sha256:" + "7" * 64,
        snapshot_id="sha256:" + "2" * 64,
        logical_data_snapshot_id="sha256:" + "3" * 64,
        source_period=(spec.period_start, spec.period_end),
        source_session_dates=source_dates,
    )


def _write_base_sleeve_output(output: Path, spec) -> dict[str, object]:
    (output / "reports").mkdir(parents=True)
    (output / "paper").mkdir()
    (output / "risk").mkdir()
    (output / "base-sleeve").mkdir()
    (output / "reports" / "report.json").write_text('{"ok":true}')
    (output / "reports" / "report.md").write_text("# report")
    (output / "paper" / "base.json").write_text('{"paper":true}')
    (output / "risk" / "base.json").write_text('{"risk":true}')
    artifact_document = _base_sleeve_document(spec)
    artifact_bytes = json.dumps(
        artifact_document,
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
                "artifact_schema_version": artifact_document["schema_version"],
                "path": str(artifact_path),
                "archive_member": archive_member,
                "sha256": f"sha256:{artifact_sha}",
                "strategy_id": artifact_document["strategy"]["strategy_id"],
                "cohort_id": spec.cohort_id,
                "universe_id": "topix_all",
                "role": "INDEX_VOL_OVERLAY_BASE_SOURCE",
                "ranking_role": "NON_CANDIDATE_NOT_RANKED",
                "candidate_count_contribution": 0,
            },
            "non_candidate_source_backtest_count": 1,
        }
    )
    return summary


def _write_am_pm_base_sleeve_output(output: Path, spec) -> dict[str, object]:
    (output / "reports").mkdir(parents=True, exist_ok=True)
    (output / "paper").mkdir(exist_ok=True)
    (output / "risk").mkdir(exist_ok=True)
    (output / "base-sleeve").mkdir(exist_ok=True)
    (output / "reports" / "report.json").write_text('{"ok":true}')
    (output / "reports" / "report.md").write_text("# report")
    (output / "paper" / "base.json").write_text('{"paper":true}')
    (output / "risk" / "base.json").write_text('{"risk":true}')
    summary = _runner_summary(spec)
    document = _build_am_sleeve()
    document["universe"]["universe_rule_digest"] = spec.universe_rule_digest
    document["snapshot"]["snapshot_id"] = summary["snapshot_id"]
    document["snapshot"]["logical_data_snapshot_id"] = summary[
        "logical_data_snapshot_id"
    ]
    artifact_bytes = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    archive_member = f"base-sleeve/{artifact_sha}.json"
    artifact_path = output / archive_member
    artifact_path.write_bytes(artifact_bytes)
    summary.update(
        {
            "report_json": str(output / "reports" / "report.json"),
            "report_markdown": str(output / "reports" / "report.md"),
            "base_sleeve_artifact": {
                "schema_version": PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
                "artifact_schema_version": PERSONAL_BASE_SLEEVE_AM_PM_ARTIFACT_SCHEMA,
                "path": str(artifact_path),
                "archive_member": archive_member,
                "sha256": f"sha256:{artifact_sha}",
                "strategy_id": AM_PM_BASE_SLEEVE_ID,
                "cohort_id": spec.cohort_id,
                "universe_id": "topix_all",
                "role": PERSONAL_BASE_SLEEVE_ROLE,
                "ranking_role": PERSONAL_BASE_SLEEVE_RANKING_ROLE,
                "candidate_count_contribution": 0,
            },
            "non_candidate_source_backtest_count": 1,
            "execution_mode": "am_signal_pm_close",
            "execution_contract_digest": AM_EXECUTION_CONTRACT_DIGEST,
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
        downloader=wrong_snapshot,
        uploader=_uploader(uploads),
    )

    assert manifest["status"] == "FAILED"
    assert "sha256 mismatch" in manifest["error"]
    assert [key for key, _, _ in uploads] == [spec.manifest_key]
    assert not tuple(work.iterdir())


def test_snapshot_capacity_splits_transport_from_expanded_database() -> None:
    assert service.MAX_SNAPSHOT_BYTES == 4 * 1024 * 1024 * 1024
    assert service.SNAPSHOT_MAX_DATABASE_BYTES == 5 * 1024 * 1024 * 1024


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
    monkeypatch.setattr(service, "SNAPSHOT_MAX_DATABASE_BYTES", 1024)
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
    work = tmp_path / "work"
    work.mkdir()
    writes: list[str] = []
    ticks = {"t": 0.0}

    def clock() -> float:
        return ticks["t"]

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    def stepped_run(self, request):
        from pit.cooperative_deadline import DeadlineExceeded, install_deadline

        del self
        with install_deadline(request.deadline):
            request.data_view.write_artifact(
                category="reports", suffix="txt", payload=b"before"
            )
            writes.append("before")
            ticks["t"] = 10.0
            try:
                request.data_view.write_artifact(
                    category="reports", suffix="txt", payload=b"after"
                )
                writes.append("after")
            except DeadlineExceeded:
                pass
            raise DeadlineExceeded("personal research deadline cancelled")

    monkeypatch.setattr(
        "research.personal_service.PersonalResearchService.run", stepped_run
    )
    monkeypatch.setenv("QP_REPO_ROOT", str(tmp_path))
    from pit.cooperative_deadline import CooperativeDeadline

    deadline = CooperativeDeadline(deadline_monotonic=5.0, clock=clock)
    manifest = service.execute_job(
        spec,
        work_root=work,
        timeout_seconds=0.01,
        downloader=copy_snapshot,
        uploader=_uploader([]),
        deadline=deadline,
        clock=clock,
    )

    assert manifest["status"] == "FAILED"
    assert "limit" in manifest["error"]
    assert writes == ["before"]
    assert not tuple(work.iterdir())


def test_default_timeout_keeps_room_for_durable_terminal_evidence() -> None:
    assert service.DEFAULT_TIMEOUT_SECONDS == 165 * 60
    assert service.MAX_JOB_LIFETIME_SECONDS == 180 * 60
    assert service.DEFAULT_TIMEOUT_SECONDS < service.MAX_JOB_LIFETIME_SECONDS


def test_direct_research_timeout_is_enforced_without_a_child_command() -> None:
    assert not hasattr(service, "_run_research_process")
    with pytest.raises(TypeError, match="command"):
        service.execute_job(  # type: ignore[call-arg]
            _job("a" * 64),
            work_root=Path("/tmp"),
            command=("qp-research",),
        )


def test_default_runner_does_not_read_qp_research_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QP_RESEARCH_COMMAND", "/tmp/should-not-run")
    seen: list[object] = []

    def fake_execute(spec, **kwargs):
        seen.append((spec, kwargs))
        return {"status": "COMPLETED"}

    monkeypatch.setattr(service, "execute_job", fake_execute)
    result = service.default_runner(_job("a" * 64), work_root=Path("/tmp"))
    assert result["status"] == "COMPLETED"
    assert seen
    assert "command" not in seen[0][1]
    assert os.environ.get("QP_RESEARCH_COMMAND") == "/tmp/should-not-run"


def _redigest(spec):
    return replace(spec, request_digest=spec.derived_request_digest())


def test_job_spec_accepts_long_short_on_a_broad_universe() -> None:
    spec = _redigest(
        replace(
            _job("a" * 64),
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
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
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
            universe_id="topix_core30",
        )
    )

    with pytest.raises(service.JobInputError, match="profile mismatch"):
        spec.validate()


def test_python_container_defaults_to_am_diverse_and_allows_am_ids() -> None:
    assert service.DEFAULT_PERSONAL_COHORT_ID == "diverse-core-am-pm-v1"
    for cohort_id in (
        "price-relative-am-pm-v1",
        "fundamental-relative-am-pm-v1",
        "diverse-core-am-pm-v1",
        "compact-market-diverse-am-pm-v1",
        "sector-relative-ls-am-pm-v1",
    ):
        assert cohort_id in service.PERSONAL_EXECUTABLE_COHORT_IDS
    for cohort_id in (
        "diverse-core-v1",
        "sector-relative-ls-v1",
        "compact-market-diverse-v1",
    ):
        assert cohort_id not in service.PERSONAL_EXECUTABLE_COHORT_IDS
        with pytest.raises(service.JobInputError, match="OfflineFixture DRAFT-only"):
            replace(_job("a" * 64), cohort_id=cohort_id).validate()
    am = _job("a" * 64, cohort_id="diverse-core-am-pm-v1")
    am.validate()
    compact = _job(
        "a" * 64,
        cohort_id="compact-market-diverse-am-pm-v1",
        universe_id="topix_core30",
    )
    compact.validate()
    with pytest.raises(service.JobInputError, match="profile mismatch"):
        replace(_job("a" * 64), universe_id="topix_core30").validate()
    with pytest.raises(service.JobInputError, match="profile mismatch"):
        replace(
            _job("a" * 64, cohort_id="sector-relative-ls-am-pm-v1"),
            universe_id="topix_core30",
        ).validate()


def test_production_default_runner_starts_and_quiesces_under_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container_root = str(MODULE_PATH.parent)
    if container_root not in sys.path:
        sys.path.insert(0, container_root)
    spawn_service = importlib.import_module("personal_research_service")
    template = _job("a" * 64, job_id="spawn-default-runner")
    spec = spawn_service.JobSpec(
        **{
            name: getattr(template, name)
            for name in template.__dataclass_fields__
        }
    )
    monkeypatch.setenv("QP_JOB_ROOT", "/etc")
    supervisor = spawn_service._ProcessGroupSupervisor(
        spawn_service.default_runner,
        spec,
        work_root=tmp_path,
    )

    assert supervisor._process_context.get_start_method() == "spawn"
    supervisor.start()
    outcome = supervisor.wait()

    assert outcome.quiescent is True
    assert outcome.result is None
    assert outcome.error is not None
    assert "ephemeral temporary storage" in outcome.error


def test_success_archive_excludes_generated_sqlite_and_manifest_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)

    def fake_success(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        summary = _runner_summary(spec, evaluated_count=4, hold_count=0)
        identity = service._personal_cohort_identity(spec.cohort_id)
        summary["execution_mode"] = identity["execution_mode"]
        summary["execution_contract_digest"] = identity["execution_contract_digest"]
        return _direct_run_from_summary(summary, output)

    monkeypatch.setattr(service, "_run_direct_research", fake_success)
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    monkeypatch.setenv("QP_REPO_ROOT", str(tmp_path))
    manifest = service.execute_job(
        spec,
        work_root=work,
        downloader=copy_snapshot,
        uploader=_uploader(uploads),
    )

    assert manifest["status"] == "COMPLETED"
    assert manifest["candidate_count"] == 4
    assert manifest["evaluated_count"] == 4
    assert manifest["hold_count"] == 0
    assert manifest["cohort_id"] == spec.cohort_id
    assert manifest["cohort_digest"] == spec.cohort_digest
    assert manifest["universe_id"] == "topix_all"
    assert manifest["universe_rule_digest"] == spec.universe_rule_digest
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
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
        )
    )
    output = tmp_path / "output"
    summary = _write_am_pm_base_sleeve_output(output, spec)
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
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
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
            cohort_id="sector-relative-ls-am-pm-v1",
            cohort_digest=AM_LONG_SHORT_COHORT_DIGEST,
        )
    )

    def completed_source_run(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        summary = _write_am_pm_base_sleeve_output(output, spec)
        return _direct_run_from_summary(summary, output)

    monkeypatch.setattr(service, "_run_direct_research", completed_source_run)
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
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
        "universe_rule_digest": personal_research_universe_rule_digest(
            "topix_all", am_pm=True
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
    spec = _job(
        sha,
        job_id="am-base-sleeve",
        cohort_id="sector-relative-ls-am-pm-v1",
    )
    identity = service._personal_cohort_identity(spec.cohort_id)
    assert identity["execution_mode"] == "am_signal_pm_close"
    assert identity["execution_contract_digest"] == AM_EXECUTION_CONTRACT_DIGEST
    assert identity["session_view_digest"].startswith("sha256:")
    output = tmp_path / "output"
    summary = _write_base_sleeve_output(output, spec)
    summary["base_sleeve_artifact"][
        "artifact_schema_version"
    ] = "personal-base-sleeve-source/v1"
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
    spec = _job(
        sha,
        job_id="am-mode-tamper",
        cohort_id="sector-relative-ls-am-pm-v1",
    )

    def completed_source_run(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        summary = _write_base_sleeve_output(output, spec)
        summary["execution_mode"] = "next_close"
        summary["execution_contract_digest"] = "sha256:" + "c" * 64
        return _direct_run_from_summary(summary, output)

    monkeypatch.setattr(service, "_run_direct_research", completed_source_run)
    work = tmp_path / "work"
    work.mkdir()

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
        downloader=copy_snapshot,
        uploader=_uploader([]),
    )
    assert manifest["status"] == "FAILED"
    assert "execution_mode" in manifest["error"]


def _am_cli_summary(spec, output: Path, *, universe_rule_digest: str) -> dict[str, object]:
    (output / "reports").mkdir(parents=True, exist_ok=True)
    report_json = output / "reports" / "report.json"
    report_md = output / "reports" / "report.md"
    report_json.write_text('{"ok":true}', encoding="utf-8")
    report_md.write_text("# report", encoding="utf-8")
    summary = _runner_summary(spec)
    summary["universe_rule_digest"] = universe_rule_digest
    summary["report_json"] = str(report_json)
    summary["report_markdown"] = str(report_md)
    summary["execution_mode"] = "am_signal_pm_close"
    summary["execution_contract_digest"] = AM_EXECUTION_CONTRACT_DIGEST
    return summary


def test_am_topix_all_cli_report_digest_uses_morning_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from cf_platform import personal_offline_cli as personal_cli

    morning = personal_research_universe_rule_digest("topix_all", am_pm=True)
    session = personal_research_universe_rule_digest("topix_all", am_pm=False)
    assert morning != session
    assert personal_research_universe_decision_cutoff(am_pm=True) == "morning_close"
    assert personal_research_universe_decision_cutoff(am_pm=False) == "session_close"
    assert personal_universe_selector(
        "topix_all", decision_cutoff="morning_close"
    ).rule_digest == morning

    database = tmp_path / "input.sqlite"
    database.touch()
    report_json = tmp_path / "cli-report.json"
    report_md = tmp_path / "cli-report.md"
    report_json.write_text("{}", encoding="utf-8")
    report_md.write_text("# report", encoding="utf-8")

    class FakeService:
        def run(self, request):
            cutoff = personal_research_universe_decision_cutoff(
                am_pm=is_am_pm_factor_cohort(request.cohort_id)
            )
            selector = personal_universe_selector(
                request.universe_id, decision_cutoff=cutoff
            )
            return SimpleNamespace(
                report_id="sha256:" + "1" * 64,
                report_json_path=report_json,
                report_markdown_path=report_md,
                snapshot=SimpleNamespace(
                    snapshot_id="sha256:" + "2" * 64,
                    logical_data_snapshot_id="sha256:" + "3" * 64,
                ),
                candidate_count=4,
                evaluated_count=4,
                hold_count=0,
                unexpected_errors=0,
                cohort_id=request.cohort_id,
                cohort_digest=str(
                    get_research_cohort(request.cohort_id).to_dict()["cohort_digest"]
                ),
                universe_id=selector.selector_id,
                universe_rule_digest=selector.rule_digest,
                execution_mode="am_signal_pm_close",
                execution_contract_digest=AM_EXECUTION_CONTRACT_DIGEST,
                base_sleeve_artifact_path=None,
                base_sleeve_artifact_digest=None,
                base_sleeve_archive_member=None,
                base_sleeve_artifact=None,
                non_candidate_source_backtest_count=0,
                exit_code=0,
            )

    monkeypatch.setattr(personal_cli, "PersonalResearchService", FakeService)
    monkeypatch.setenv(personal_cli.LOCAL_MARKET_DATA_ENV, "1")
    code = personal_cli.main(
        [
            "--db",
            str(database),
            "--start",
            "2022-04-19",
            "--end",
            "2026-08-27",
            "--output",
            str(tmp_path),
            "--cohort",
            "diverse-core-am-pm-v1",
            "--universe",
            "topix_all",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["universe_rule_digest"] == morning
    assert payload["universe_id"] == "topix_all"

    spec = _job(
        "a" * 64,
        job_id="am-topix-all-morning",
        cohort_id="diverse-core-am-pm-v1",
    )
    assert spec.universe_rule_digest == morning
    with pytest.raises(
        service.JobInputError, match="universe_rule_digest does not match"
    ):
        _job(
            "a" * 64,
            job_id="am-topix-all-session",
            cohort_id="diverse-core-am-pm-v1",
            universe_rule_digest=session,
        )

    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(
        sha,
        job_id="am-topix-all-run",
        cohort_id="diverse-core-am-pm-v1",
    )

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    def run_matching(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        summary = _am_cli_summary(spec, output, universe_rule_digest=morning)
        return _direct_run_from_summary(summary, output)

    monkeypatch.setattr(service, "_run_direct_research", run_matching)
    work = tmp_path / "work-ok"
    work.mkdir()
    completed = service.execute_job(
        spec,
        work_root=work,
        downloader=copy_snapshot,
        uploader=_uploader([]),
    )
    assert completed["status"] == "COMPLETED"
    assert completed["universe_rule_digest"] == morning

    def run_mismatch(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        summary = _am_cli_summary(spec, output, universe_rule_digest=session)
        return _direct_run_from_summary(summary, output)

    monkeypatch.setattr(service, "_run_direct_research", run_mismatch)
    work_bad = tmp_path / "work-mismatch"
    work_bad.mkdir()
    failed = service.execute_job(
        spec,
        work_root=work_bad,
        downloader=copy_snapshot,
        uploader=_uploader([]),
    )
    assert failed["status"] == "FAILED"
    assert "qp-research violated the fixed personal policy" in failed["error"]

    with pytest.raises(service.JobInputError, match="OfflineFixture DRAFT-only"):
        _job("a" * 64, job_id="legacy-session", cohort_id="diverse-core-v1")
    assert session == personal_research_universe_rule_digest("topix_all", am_pm=False)


def test_exit_two_with_no_evaluated_candidates_archives_completed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)

    def no_analysis(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        reports = output / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "no-analysis.json").write_text(
            '{"status":"NO_ANALYSIS"}', encoding="utf-8"
        )
        (reports / "no-analysis.md").write_text("# no analysis", encoding="utf-8")
        summary = _runner_summary(spec, evaluated_count=0, hold_count=0)
        summary["report_json"] = str(reports / "no-analysis.json")
        summary["report_markdown"] = str(reports / "no-analysis.md")
        run = _direct_run_from_summary(summary, output, exit_code=2)
        run.report_json = _artifact("reports/no-analysis.json")
        run.report_markdown = _artifact("reports/no-analysis.md")
        return run

    monkeypatch.setattr(service, "_run_direct_research", no_analysis)
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
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
    def fake_direct(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        if returncode not in {0, 2}:
            raise RuntimeError(f"qp-research exited {returncode}: bounded diagnostic")
        if stdout == "":
            raise RuntimeError("qp-research emitted no result document")
        if stdout == "{\n":
            raise RuntimeError("qp-research result document is invalid")
        run = _direct_run_from_summary(summary, output, exit_code=returncode)
        return run

    monkeypatch.setattr(service, "_run_direct_research", fake_direct)
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
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

    def failing_candidates(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
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
        run = _direct_run_from_summary(summary, output, exit_code=1)
        run.report_json = _artifact("reports/report.json")
        run.report_markdown = _artifact("reports/report.md")
        return run

    monkeypatch.setattr(service, "_run_direct_research", failing_candidates)
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
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

    def missing_report_artifacts(_spec, *, database, output, timeout_seconds):
        del _spec, database, timeout_seconds
        summary = _runner_summary(
            spec,
            evaluated_count=0,
            hold_count=0,
        )
        run = _direct_run_from_summary(summary, output, exit_code=2)
        run.report_json = _artifact("reports/missing.json")
        run.report_markdown = _artifact("reports/missing.md")
        return run

    monkeypatch.setattr(service, "_run_direct_research", missing_report_artifacts)
    work = tmp_path / "work"
    work.mkdir()
    uploads: list[tuple[str, bytes, str]] = []

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
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
        "_run_direct_research",
        lambda _spec, *, database, output, timeout_seconds: _direct_run_from_summary(
            summary, output
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
    release = PROCESS_CONTEXT.Event()
    entered = PROCESS_CONTEXT.Event()
    terminal = threading.Event()

    def runner(spec):
        entered.set()
        assert release.wait(2)
        return _manager_completed_result(spec)

    manager = _job_manager(
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
    template = _job("a" * 64, "bound-7000")
    identity = {
        "cohort_digest": template.cohort_digest,
        "cohort_id": template.cohort_id,
        "job_id": "bound-7000",
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
        "manifest_key": "research/personal/jobs/job=bound-7000/manifest.json",
        "result_key": "research/personal/jobs/job=bound-7000/result.tar.gz",
        "request_digest": "sha256:" + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }


def test_inclusive_research_period_cap_is_7000_calendar_dates() -> None:
    service.JobSpec.from_document(
        _research_period_document("2007-01-01", "2026-03-01")
    )
    with pytest.raises(service.JobInputError, match="inclusive calendar dates"):
        service.JobSpec.from_document(
            _research_period_document("2007-01-01", "2026-03-02")
        )


def test_watchdog_writes_durable_failed_terminal_before_shutdown() -> None:
    entered = PROCESS_CONTEXT.Event()
    terminal = threading.Event()
    wrote = threading.Event()
    uploads: list[tuple[str, dict]] = []

    def runner(spec):
        entered.set()
        time.sleep(1)
        return _manager_completed_result(spec)

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        uploads.append((key, json.loads(data)))
        wrote.set()

    def on_terminal() -> None:
        assert wrote.is_set()
        terminal.set()

    manager = _job_manager(
        runner,
        on_terminal=on_terminal,
        max_job_seconds=0.05,
        terminal_uploader=uploader,
    )
    spec = _job("a" * 64, "watchdog-r2")
    started = time.monotonic()
    manager.submit(spec)
    assert entered.wait(1)
    assert terminal.wait(3)
    elapsed = time.monotonic() - started
    assert elapsed < 0.5
    assert uploads
    assert uploads[0][0] == spec.manifest_key
    assert uploads[0][1]["status"] == "FAILED"
    assert "absolute Container lifetime" in uploads[0][1]["error"]
    assert manager.status(spec.job_id)["status"] == "FAILED"
    time.sleep(1.1)
    assert manager.status(spec.job_id)["status"] == "FAILED"
    assert all(body.get("status") != "COMPLETED" for _key, body in uploads)


def test_timeout_without_confirmed_supervisor_withholds_terminal() -> None:
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
    manager = _job_manager(
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
    assert manager.status(spec.job_id)["status"] == "STOPPING"


def test_terminal_upload_retries_then_shuts_down() -> None:
    attempts = {"n": 0}
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("R2 upload returned 503")

    manager = _job_manager(
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

    manager = _job_manager(
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

    manager = _job_manager(
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

    manager = _job_manager(
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


def test_failed_terminal_put_and_get_404_retries_without_shutdown(monkeypatch) -> None:
    terminal = threading.Event()

    class _MissingTerminalR2:
        def __init__(self) -> None:
            self.puts = 0
            self.gets = 0

        def urlopen(self, request, timeout=None):
            del timeout
            method = request.get_method()
            url = request.full_url
            if method == "PUT":
                self.puts += 1
                raise urllib.error.HTTPError(
                    url, 503, "unavailable", Message(), io.BytesIO(b"")
                )
            if method == "GET":
                self.gets += 1
                raise urllib.error.HTTPError(
                    url, 404, "not found", Message(), io.BytesIO(b"")
                )
            raise AssertionError(method)

    fake = _MissingTerminalR2()
    monkeypatch.setattr(service.urllib.request, "urlopen", fake.urlopen)
    manager = _job_manager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05, 0.05),
        max_job_seconds=30,
    )
    try:
        manager.submit(_job("a" * 64, "put-fail-get-404"))
        assert not terminal.wait(0.2)
        assert fake.puts >= 1
        assert fake.gets >= 1
        assert manager._shutdown_notified is False
        assert manager._pending_terminal is not None
        assert manager.status("put-fail-get-404")["status"] == "FAILED"
    finally:
        with manager._lock:
            manager._shutdown_notified = True
            retry_timer = manager._retry_timer
            manager._retry_timer = None
            manager._pending_terminal = None
        if retry_timer is not None:
            retry_timer.cancel()
            retry_timer.join(timeout=1)


def test_unavailable_terminal_upload_does_not_shutdown() -> None:
    terminal = threading.Event()

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        raise RuntimeError("R2 upload returned 503")

    manager = _job_manager(
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

    manager = _job_manager(
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

    manager = _job_manager(
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
    assert manager._retry_timer is None
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
    manager = _job_manager(
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
    release = PROCESS_CONTEXT.Event()
    entered = PROCESS_CONTEXT.Event()
    terminal = threading.Event()

    def runner(spec):
        entered.set()
        release.wait(2)
        return _manager_completed_result(spec)

    uploads: list[str] = []

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del data, spec, content_digest, extra_headers
        uploads.append(key)

    manager = _job_manager(
        runner,
        on_terminal=terminal.set,
        max_job_seconds=0.05,
        terminal_uploader=uploader,
    )
    spec = _job("a" * 64, "watchdog-job")
    manager.submit(spec)
    assert entered.wait(1)
    deadline = time.monotonic() + 3
    while not terminal.is_set() and time.monotonic() < deadline:
        assert manager.status(spec.job_id) is not None
        time.sleep(0.005)

    assert terminal.is_set()
    assert manager.status(spec.job_id)["status"] == "FAILED"
    assert "absolute Container lifetime" in manager.status(spec.job_id)["error"]
    with pytest.raises(service.JobBusyError, match="shutting down"):
        manager.submit(_job("b" * 64, "second-job"))


def test_timeout_kills_term_ignoring_group_before_failed_terminal(tmp_path: Path) -> None:
    entered = PROCESS_CONTEXT.Event()
    terminal = threading.Event()
    late_write = tmp_path / "late-authoritative-write"
    supervised_pid = {"value": 0}

    def runner(spec):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        entered.set()
        time.sleep(0.4)
        late_write.write_text("forbidden", encoding="utf-8")
        return _manager_completed_result(spec)

    def uploader(*_args, **_kwargs):
        with pytest.raises(ProcessLookupError):
            os.kill(supervised_pid["value"], 0)

    manager = _job_manager(
        runner,
        on_terminal=terminal.set,
        max_job_seconds=0.05,
        terminal_uploader=uploader,
        process_term_grace_seconds=0.05,
        process_kill_grace_seconds=0.5,
    )
    spec = _job("a" * 64, "term-ignore-timeout")
    manager.submit(spec)
    assert manager._supervisor is not None
    supervised_pid["value"] = manager._supervisor.pid
    assert entered.wait(1)
    assert terminal.wait(2)
    assert manager.status(spec.job_id)["status"] == "FAILED"
    time.sleep(0.45)
    assert not late_write.exists()


def test_root_exit_with_live_grandchild_is_stopped_before_terminal(tmp_path: Path) -> None:
    terminal = threading.Event()
    grandchild_pid = tmp_path / "grandchild.pid"
    late_write = tmp_path / "grandchild-write"

    def runner(spec):
        pid = os.fork()
        if pid == 0:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(0.8)
            late_write.write_text("forbidden", encoding="utf-8")
            os._exit(0)
        grandchild_pid.write_text(str(pid), encoding="ascii")
        return _manager_completed_result(spec)

    manager = _job_manager(
        runner,
        on_terminal=terminal.set,
        terminal_uploader=lambda *_args, **_kwargs: None,
        process_term_grace_seconds=0.2,
        process_kill_grace_seconds=0.5,
    )
    manager.submit(_job("a" * 64, "grandchild-boundary"))
    deadline = time.monotonic() + 1
    while not grandchild_pid.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert grandchild_pid.exists()
    assert not terminal.wait(0.05)
    assert terminal.wait(2)
    pid = int(grandchild_pid.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    time.sleep(0.85)
    assert not late_write.exists()


def test_cancel_uses_the_bounded_group_stop_path() -> None:
    entered = PROCESS_CONTEXT.Event()
    terminal = threading.Event()

    def runner(spec):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        entered.set()
        time.sleep(5)
        return _manager_completed_result(spec)

    manager = _job_manager(
        runner,
        on_terminal=terminal.set,
        terminal_uploader=lambda *_args, **_kwargs: None,
        process_term_grace_seconds=0.05,
        process_kill_grace_seconds=0.5,
    )
    spec = _job("a" * 64, "cancel-boundary")
    manager.submit(spec)
    assert entered.wait(1)
    assert manager.cancel(spec.job_id) is True
    assert terminal.wait(2)
    assert manager.status(spec.job_id)["status"] == "FAILED"
    assert manager.status(spec.job_id)["error"] == "job cancelled"


@pytest.mark.parametrize("mode", ["oversized", "crash"])
def test_supervised_result_payload_and_child_crash_fail_closed(mode: str) -> None:
    terminal = threading.Event()

    def runner(spec):
        if mode == "crash":
            os._exit(23)
        return {**_manager_completed_result(spec), "padding": "x" * (128 * 1024)}

    manager = _job_manager(
        runner,
        on_terminal=terminal.set,
        terminal_uploader=lambda *_args, **_kwargs: None,
    )
    spec = _job("a" * 64, f"child-{mode}")
    manager.submit(spec)
    assert terminal.wait(2)
    result = manager.status(spec.job_id)
    assert result["status"] == "FAILED"
    assert "result" in result["error"]


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
    manager = _job_manager(
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
    manager = _job_manager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05,),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert terminal.wait(1)
    assert manager._shutdown_notified is True
    assert manager._retry_timer is None
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
    manager = _job_manager(
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
    manager = _job_manager(
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
    manager = _job_manager(
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


def _coverage_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    return connection


def _insert_compact_master(
    connection: sqlite3.Connection, *, snapshot_date: str = "2024-01-04"
) -> None:
    insert_compact_master(connection, snapshot_date=snapshot_date)


def _insert_compact_bar(
    connection: sqlite3.Connection,
    *,
    day: str,
    code: str = "1301",
    morning_close: float | None = 100.0,
    afternoon_close: float | None = 100.0,
    morning_turnover: float | None = 5000.0,
    afternoon_turnover: float | None = 5000.0,
    morning_volume: float | None = 500.0,
    afternoon_volume: float | None = 500.0,
) -> None:
    insert_compact_bar(
        connection,
        day=day,
        code=code,
        available_at=f"{day}T15:30:00+09:00",
        ingested_at=f"{day}T16:00:00+09:00",
        morning_adjustment_close=morning_close,
        afternoon_adjustment_close=afternoon_close,
        morning_turnover_value=morning_turnover,
        afternoon_turnover_value=afternoon_turnover,
        morning_adjustment_volume=morning_volume,
        afternoon_adjustment_volume=afternoon_volume,
    )


def _install_exact_compact_v7(connection: sqlite3.Connection) -> None:
    install_compact_schema(connection)


def _install_typed_bars(
    connection: sqlite3.Connection,
    *,
    morning_close: float | None = 100.0,
    afternoon_close: float | None = 101.0,
) -> None:
    connection.execute(
        """
        CREATE TABLE jquants_daily_bars (
            source TEXT,
            code TEXT,
            date TEXT,
            event_time TEXT,
            available_at TEXT,
            ingested_at TEXT,
            close REAL,
            morning_adjustment_close REAL,
            morning_turnover_value REAL,
            morning_adjustment_volume REAL,
            afternoon_adjustment_close REAL,
            afternoon_turnover_value REAL,
            afternoon_adjustment_volume REAL
        )
        """
    )
    connection.execute(
        "INSERT INTO jquants_daily_bars("
        "source,code,date,event_time,available_at,ingested_at,close,"
        "morning_adjustment_close,morning_turnover_value,"
        "morning_adjustment_volume,afternoon_adjustment_close,"
        "afternoon_turnover_value,afternoon_adjustment_volume"
        ") VALUES ('jquants','1001','2024-01-04',"
        "'2024-01-04T15:00:00+09:00','2024-01-04T15:00:00+09:00',"
        "'2024-01-04T16:00:00+09:00',100,?,?,?,?,?,?)",
        (
            morning_close,
            10.0 if morning_close is not None else None,
            1.0 if morning_close is not None else None,
            afternoon_close,
            20.0 if afternoon_close is not None else None,
            2.0 if afternoon_close is not None else None,
        ),
    )


def test_session_coverage_reads_compact_v7_am_pm_counts() -> None:
    connection = _coverage_connection()
    try:
        _install_exact_compact_v7(connection)
        _insert_compact_master(connection)
        _insert_compact_bar(connection, day="2024-01-04")
        _insert_compact_bar(
            connection,
            day="2024-01-05",
            afternoon_close=None,
            afternoon_turnover=None,
            afternoon_volume=None,
        )
        _insert_compact_bar(
            connection,
            day="2024-01-06",
            morning_close=None,
            morning_turnover=None,
            morning_volume=None,
            afternoon_close=None,
            afternoon_turnover=None,
            afternoon_volume=None,
        )
        coverage = service._session_coverage(connection)
    finally:
        connection.close()

    assert coverage["bar_rows"] == 3
    assert coverage["am"] == {
        "morning_adjustment_close_non_null": 2,
        "morning_turnover_value_non_null": 2,
        "morning_adjustment_volume_non_null": 2,
    }
    assert coverage["pm"] == {
        "afternoon_adjustment_close_non_null": 1,
        "afternoon_turnover_value_non_null": 1,
        "afternoon_adjustment_volume_non_null": 1,
    }


def test_session_coverage_fail_closed_state_mapping() -> None:
    invalid = _coverage_connection()
    try:
        stamp_compact_manifest(invalid)
        _install_typed_bars(invalid)
        with pytest.raises(RuntimeError, match="rebuild as personal-draft-history/v8"):
            service._session_coverage(invalid)
    finally:
        invalid.close()

    mixed = _coverage_connection()
    try:
        _install_exact_compact_v7(mixed)
        _insert_compact_master(mixed)
        _insert_compact_bar(mixed, day="2024-01-04")
        _install_typed_bars(mixed)
        with pytest.raises(RuntimeError, match="mix compact"):
            service._session_coverage(mixed)
    finally:
        mixed.close()


def test_session_coverage_keeps_typed_bars_for_v6_manifest_without_compact() -> None:
    connection = _coverage_connection()
    try:
        stamp_compact_manifest(connection, "personal-draft-history/v6")
        _install_typed_bars(
            connection, morning_close=100.0, afternoon_close=None
        )
        coverage = service._session_coverage(connection)
    finally:
        connection.close()

    assert coverage["bar_rows"] == 1
    assert coverage["am"]["morning_adjustment_close_non_null"] == 1
    assert coverage["pm"]["afternoon_adjustment_close_non_null"] == 0


def _snapshot_request_digest(request: dict) -> str:
    body = {
        "format": service.PERSONAL_HISTORY_FORMAT,
        "job_id": request["job_id"],
        "lookback_sessions": request["lookback_sessions"],
        "period_end": request["period_end"],
        "period_start": request["period_start"],
        "runner_version": service.RUNNER_VERSION,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _snapshot_spec(job_id: str) -> service.SnapshotJobSpec:
    request = {
        "job_id": job_id,
        "lookback_sessions": 10,
        "period_end": "2024-12-31",
        "period_start": "2024-01-01",
        "runner_version": service.RUNNER_VERSION,
        "format": service.PERSONAL_HISTORY_FORMAT,
    }
    return service.SnapshotJobSpec.from_document(
        {
            **request,
            "deployment_id": "test-deploy",
            "environment": "production",
            "manifest_key": f"research/personal/snapshot-builds/job={job_id}/manifest.json",
            "max_database_bytes": service.SNAPSHOT_MAX_DATABASE_BYTES,
            "request_digest": _snapshot_request_digest(request),
        }
    )


class _CompactCoverageHydrator:
    def __init__(self, **kwargs):
        self.store = kwargs["store"]
        self.plan = kwargs["plan"]

    def hydrate(self):
        connection = self.store._conn
        _install_exact_compact_v7(connection)
        _insert_compact_master(connection)
        _insert_compact_bar(connection, day="2024-01-04")
        _insert_compact_bar(
            connection,
            day="2024-01-05",
            afternoon_close=None,
            afternoon_turnover=None,
            afternoon_volume=None,
        )
        connection.commit()
        lookback = int(self.plan.lookback_sessions)
        return SimpleNamespace(
            bar_start="2024-01-04",
            segment_counts={"markets_calendar": 1, "equities_master": 1},
            fetched_rows=2,
            written_rows=2,
            actual_lookback_sessions=lookback,
            lookback_truncated=False,
        )


class _InvalidCompactHydrator(_CompactCoverageHydrator):
    def hydrate(self):
        connection = self.store._conn
        stamp_compact_manifest(connection)
        connection.commit()
        return SimpleNamespace(
            bar_start="2024-01-04",
            segment_counts={"markets_calendar": 1, "equities_master": 1},
            fetched_rows=1,
            written_rows=1,
        )


def test_snapshot_build_records_compact_v7_session_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _CompactCoverageHydrator)
    spec = _snapshot_spec("snap-compact-coverage")
    uploads: list[str] = []

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers, data
        uploads.append(key)

    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=lambda _spec: object()
    )
    assert manifest["status"] == "COMPLETED"
    assert manifest["bar_rows"] == 2
    assert manifest["am_field_non_null_coverage"] == {
        "morning_adjustment_close_non_null": 2,
        "morning_turnover_value_non_null": 2,
        "morning_adjustment_volume_non_null": 2,
    }
    assert manifest["pm_field_non_null_coverage"] == {
        "afternoon_adjustment_close_non_null": 1,
        "afternoon_turnover_value_non_null": 1,
        "afternoon_adjustment_volume_non_null": 1,
    }
    assert uploads == [manifest["snapshot_key"], spec.manifest_key]


def test_snapshot_build_fails_closed_on_invalid_compact_marker(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _InvalidCompactHydrator)
    spec = _snapshot_spec("snap-compact-invalid")
    uploads: list[tuple[str, dict]] = []

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = data.read_bytes() if isinstance(data, Path) else bytes(data)
        uploads.append(
            (key, json.loads(body) if key.endswith("manifest.json") else {})
        )

    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=lambda _spec: object()
    )
    assert manifest["status"] == "FAILED"
    assert "rebuild as personal-draft-history/v8" in manifest["error"]
    assert manifest.get("snapshot_key") is None
    assert [key for key, _ in uploads] == [spec.manifest_key]


def _controlled_job_spec(**overrides: object) -> dict[str, object]:
    ready_fixture = json.loads(
        Path(service._CONTRACT_PATH)
        .with_name("controlled_pilot_ready.generated.json")
        .read_text(encoding="utf-8")
    )
    physical = "sha256:" + ("cd" * 32)
    hex_digest = physical[len("sha256:") :]
    universe = "sha256:" + ("ab" * 32)
    spec: dict[str, object] = {
        "identity": "controlled_pilot_v1",
        "format": "controlled-pilot-job-spec/v1",
        "runner_version": service._CONTROLLED_CONTRACT["runner_version"],
        "job_id": "controlled-job-1",
        "idempotency_key": "controlled-job-1",
        "ready_attestation_id": ready_fixture["attestation"]["attestation_id"],
        "ready_manifest_digest": ready_fixture["ready_manifest"]["manifest_digest"],
        "signed_projection_document_digest": ready_fixture["attestation"][
            "signed_projection_document_digest"
        ],
        "session_scope": ready_fixture["controlled_session_scope"],
        "snapshot_id": "sha256:" + ("ab" * 32),
        "immutable_db_digest": physical,
        "snapshot_key": f"research/controlled_pilot/v1/snapshots/sha256={hex_digest}.sqlite",
        "snapshot_size": 16,
        "fill_contract_digest": service.CONTROLLED_FILL_CONTRACT_DIGEST,
        "authorization_digest": "sha256:" + ("11" * 32),
        "request_digest": "sha256:" + ("22" * 32),
        "resolved_universe_digest": universe,
        "universe_rule_digest": EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        "max_gross_weight_ppm": 500_000,
        "manifest_key": "research/controlled_pilot/v1/jobs/controlled-job-1/container-terminal.json",
        "execution_id": "sha256:" + ("33" * 32),
        "profile_digest": service.CONTROLLED_PROFILE_DIGEST,
        "plan_set_digest": service.CONTROLLED_PLAN_SET_DIGEST,
        "dependency_closure_digest": service.CONTROLLED_CLOSURE_DIGEST,
        "exact_four_binding_digest": service.CONTROLLED_BINDING_DIGEST,
    }
    spec.update(overrides)
    return spec


def test_controlled_container_rejects_caller_paths_and_bytes() -> None:
    with pytest.raises(service.JobInputError, match="closed"):
        service.execute_controlled_pilot_container(
            {**_controlled_job_spec(), "db_path": "/tmp/attacker.sqlite"}
        )


def test_controlled_container_deletes_ephemeral_snapshot_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kept: list[Path] = []

    def fail_download(key: str, dest: Path, *, expected_hex: str, expected_size: int) -> str:
        del key, expected_hex, expected_size
        dest.write_bytes(b"sqlite")
        kept.append(dest)
        raise RuntimeError("download failed")

    monkeypatch.setattr(service, "_download_controlled_snapshot", fail_download)
    with pytest.raises(RuntimeError, match="download failed"):
        service.execute_controlled_pilot_container(_controlled_job_spec())
    assert kept
    assert not kept[0].exists()
    assert not kept[0].parent.exists()


def test_controlled_container_runs_canonical_four_with_independent_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.result import BacktestResult
    from strategies.paper import Lifecycle, PaperRunResult

    snapshot = tmp_path / "controlled.sqlite"
    sha = _sqlite(snapshot)
    physical_id = f"sha256:{sha}"
    snapshot_id = "sha256:" + ("ab" * 32)
    calls: list[tuple[str, str]] = []

    def fake_download(key: str, dest: Path, *, expected_hex: str, expected_size: int) -> str:
        del key, expected_size
        dest.write_bytes(snapshot.read_bytes())
        return expected_hex

    def fake_run(strategy: object, config: object) -> PaperRunResult:
        calls.append((type(strategy).__name__, getattr(config, "lifecycle").value))
        experiment_id = "e" * 64
        return PaperRunResult(
            experiment_id=experiment_id,
            run_id=experiment_id,
            lifecycle=Lifecycle.PAPER,
            backtest=BacktestResult(
                equity_curve=[{"date": "2023-01-04", "equity": 1.0}],
                trades=[{"code": "7203"}],
                metrics={
                    "total_return_post_cost": 0.0,
                    "max_drawdown": -0.0,
                    "num_trades": 1,
                },
                metadata={
                    "max_gross_weight_limit": 0.5,
                    "requested_gross_weight": 0.5,
                    "realized_gross_weight": 0.5,
                    "authentic_am_session_evidence": True,
                },
            ),
            reproducibility={
                "data_snapshot_id": snapshot_id,
                "feature_versions": {"momentum_n": "1.0.0"},
                "feature_definition_hashes": {},
                "strategy_definition_hash": "sha256:" + ("cd" * 32),
            },
        )

    class _Universe:
        rule_digest = EXACT_FOUR_UNIVERSE_RULE_DIGEST
        resolved_membership_digest = "sha256:" + ("ab" * 32)
        membership_by_date = {"2023-01-04": ("7203",)}
        membership_proof = "controlled-resolved-universe:" + ("sha256:" + ("ab" * 32))

    handle_events: list[str] = []

    class _Handle:
        def _begin_controlled_batch_reads(self) -> None:
            handle_events.append("begin")

        def logical_snapshot_id(self) -> str:
            return snapshot_id

        def resolve_controlled_universe(self, **_kwargs: object) -> _Universe:
            return _Universe()

        def _end_controlled_batch_reads(self) -> None:
            handle_events.append("end")

        def close(self) -> None:
            handle_events.append("close")

    monkeypatch.setattr(service, "_download_controlled_snapshot", fake_download)
    monkeypatch.setattr(service, "_run_controlled_paper", fake_run)
    monkeypatch.setattr(service, "_mint_controlled_am_view", lambda *_args: _Handle())
    result = service.execute_controlled_pilot_container(
        _controlled_job_spec(
            snapshot_id=snapshot_id,
            immutable_db_digest=physical_id,
            snapshot_key=(
                "research/controlled_pilot/v1/snapshots/sha256="
                + physical_id[len("sha256:") :]
                + ".sqlite"
            ),
            snapshot_size=snapshot.stat().st_size,
        )
    )
    assert result["ok"] is True
    assert result["ephemeral_cleaned"] is True
    assert result["automatic_promotion"] is False
    assert result["live_orders_enabled"] is False
    papers = result["papers"]
    assert len(papers) == 4
    assert {row["lifecycle"] for row in papers} == {"Paper"}
    assert len({row["strategy_spec_hash"] for row in papers}) == 4
    assert len(result["risks"]) == 4
    assert all("audit_id" in row for row in result["risks"])
    assert result["selection"]["decision"] == "HOLD"
    assert result["selection"]["automatic_promotion"] is False
    assert "PROMOTE" not in {
        row["decision"] for row in result["selection"]["decisions"]
    }
    assert result["knowledge"]["digest"].startswith("sha256:")
    assert len(calls) == 4
    assert handle_events == ["begin", "end", "close"]
    assert {lifecycle for _, lifecycle in calls} == {"Paper"}
    assert "Threshold" not in " ".join(name for name, _ in calls)
    assert papers[0]["ordinal"] == 1
    assert papers[0]["plan_id"] == "exp-mdh-hold10-momentum"
    assert papers[0]["semantic_digest"].startswith("sha256:")
    from paper_runtime.canonical_json import canonical_json_digest

    paper_body = dict(papers[0])
    paper_digest = paper_body.pop("semantic_digest")
    assert paper_digest == canonical_json_digest(paper_body)
    assert paper_body["metrics"]["total_return_post_cost"] == 0.0
    assert (
        result["knowledge"]["semantic_child_set_digest"]
        == result["selection"]["semantic_child_set_digest"]
    )
    assert (
        result["knowledge"]["selection_semantic_digest"]
        == result["selection"]["semantic_digest"]
    )
    assert result["knowledge"]["artifact_id"] == result["knowledge"]["digest"]
    assert result["knowledge"]["digest"] == result["knowledge"]["semantic_digest"]


def _controlled_completed_result(item) -> dict:
    return {
        "ok": True,
        "identity": service.CONTROLLED_PILOT_IDENTITY,
        "status": "COMPLETED",
        "job_id": item.job_id,
        "request_digest": item.request_digest,
        "execution_id": item.execution_id,
        "runner_version": item.runner_version,
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "ephemeral_cleaned": True,
        "papers": [{"ordinal": index} for index in range(1, 5)],
        "risks": [{"ordinal": index} for index in range(1, 5)],
        "selection": {"decision": "HOLD"},
        "knowledge": {"kind": "knowledge"},
        "generation": int(service._CONTROLLED_CONTRACT["generation"]),
        "max_parallel": int(service._CONTROLLED_CONTRACT["max_parallel"]),
    }


def _shared_execution_counter():
    return PROCESS_CONTEXT.Value("i", 0)


def _increment_execution_counter(counter) -> None:
    with counter.get_lock():
        counter.value += 1


def test_controlled_job_manager_restart_executes_once() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store: dict[str, bytes] = {}
    executions = _shared_execution_counter()
    done = threading.Event()

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = data if isinstance(data, bytes) else bytes(data)
        if key in store:
            raise service.TerminalReadDenied("create-only")
        store[key] = body

    def reader(item):
        raw = store.get(item.manifest_key)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    def runner(item):
        _increment_execution_counter(executions)
        return _controlled_completed_result(item)

    first = _job_manager(
        runner,
        terminal_uploader=upload,
        terminal_reader=reader,
        on_terminal=done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    first.submit(spec)
    assert done.wait(2.0)
    second_done = threading.Event()
    second = _job_manager(
        runner,
        terminal_uploader=upload,
        terminal_reader=reader,
        on_terminal=second_done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    recovered = second.submit(spec)
    assert executions.value == 1
    assert recovered["status"] == "COMPLETED"
    assert recovered["execution_id"] == spec.execution_id
    assert second_done.is_set() is False



def test_controlled_missing_runner_version_is_rejected() -> None:
    document = _controlled_job_spec()
    document["runner_version"] = ""
    with pytest.raises(service.JobInputError, match="runner_version"):
        service.ControlledPilotJobSpec.from_document(document)
    missing = _controlled_job_spec()
    missing.pop("runner_version")
    with pytest.raises(service.JobInputError, match="closed"):
        service.ControlledPilotJobSpec.from_document(missing)
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    headers = service._terminal_get_headers(spec)
    assert headers["x-personal-runner-version"] == spec.runner_version
    assert spec.runner_version == service._CONTROLLED_CONTRACT["runner_version"]


def test_python_controlled_terminals_match_the_worker_closed_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    monkeypatch.setattr(
        service,
        "execute_controlled_pilot_container",
        lambda _document: {
            key: value
            for key, value in _controlled_completed_result(spec).items()
            if key
            not in {
                "status",
                "job_id",
                "request_digest",
                "execution_id",
                "runner_version",
            }
        },
    )
    completed = service.default_runner(spec)
    assert completed["runner_version"] == spec.runner_version
    closed_completed = {
        **completed,
        "owner_nonce": "owner-nonce-1",
        "fencing_token": 1,
    }
    cross_runtime = json.loads(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "controlled_pilot_python_terminals.json"
        ).read_text(encoding="utf-8")
    )
    assert closed_completed == cross_runtime["completed"]
    assert service._controlled_terminal_matches_spec(spec, closed_completed)

    manager = _job_manager(lambda _spec: {}, max_job_seconds=5)
    timeout = {
        **manager._timeout_terminal(spec),
        "owner_nonce": "owner-nonce-1",
        "fencing_token": 1,
    }
    failure = {
        **manager._failure_terminal(spec, "controlled_execution_failed"),
        "owner_nonce": "owner-nonce-1",
        "fencing_token": 1,
    }
    assert timeout["runner_version"] == spec.runner_version
    assert failure["runner_version"] == spec.runner_version
    assert failure == cross_runtime["failed"]
    assert service._controlled_terminal_matches_spec(spec, timeout)
    assert service._controlled_terminal_matches_spec(spec, failure)
    for malformed in (
        {key: value for key, value in closed_completed.items() if key != "runner_version"},
        {**closed_completed, "runner_version": "evil-runner"},
        {**closed_completed, "fencing_token": "1"},
        {**closed_completed, "extra": True},
    ):
        assert not service._controlled_terminal_matches_spec(spec, malformed)


class _ControlledCasStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.seq = 0

    def upload(self, key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest
        body = data if isinstance(data, bytes) else bytes(data)
        headers = {str(k).lower(): str(v) for k, v in dict(extra_headers or {}).items()}
        with self.lock:
            existing = self.objects.get(key)
            if key.endswith("/container-lease.json"):
                if headers.get("if-none-match") == "*":
                    if existing is not None:
                        raise service.ControlledLeaseConflict("lease exists")
                elif headers.get("if-match"):
                    if existing is None or existing[1] != headers["if-match"]:
                        raise service.ControlledLeaseConflict("lease cas")
                elif existing is not None:
                    raise service.ControlledLeaseConflict("lease precondition")
            elif existing is not None:
                if existing[0] == body:
                    return
                raise service.JobConflictError("digest conflict")
            self.seq += 1
            self.objects[key] = (body, f"etag-{self.seq}")

    def reader(self, item):
        raw = self.objects.get(item.manifest_key)
        if raw is None:
            return None
        return json.loads(raw[0].decode("utf-8"))

    def object_reader(self, spec, key):
        del spec
        raw = self.objects.get(key)
        if raw is None:
            return None, ""
        return json.loads(raw[0].decode("utf-8")), raw[1]


def _controlled_runner(executions, started=None, release=None):
    def runner(item):
        _increment_execution_counter(executions)
        if started is not None:
            started.set()
        if release is not None:
            release.wait(2.0)
        return _controlled_completed_result(item)

    return runner


def test_controlled_crash_before_terminal_takeover_after_lease_expiry() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store = _ControlledCasStore()
    stage = {
        "identity": service.CONTROLLED_PILOT_IDENTITY,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "execution_id": spec.execution_id,
        "runner_version": spec.runner_version,
        "status": "QUEUED",
        "stage": "QUEUED",
    }
    lease = {
        "identity": service.CONTROLLED_PILOT_IDENTITY,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "execution_id": spec.execution_id,
        "runner_version": spec.runner_version,
        "kind": "controlled-pilot",
        "owner_nonce": "deadownerdeadowner",
        "fencing_token": 1,
        "expires_at": 1.0,
        "heartbeat_at": 0.0,
        "status": "CLAIMED",
    }
    store.objects[spec.stage_key] = (
        service._canonical_bytes(stage),
        "etag-stage",
    )
    store.objects[spec.lease_key] = (
        service._canonical_bytes(lease),
        "etag-dead",
    )
    executions = _shared_execution_counter()
    done = threading.Event()
    manager = _job_manager(
        _controlled_runner(executions),
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    accepted = manager.submit(spec)
    assert accepted["status"] in {"QUEUED", "RUNNING", "COMPLETED"}
    assert done.wait(2.0)
    assert executions.value == 1
    claimed, _etag = store.object_reader(spec, spec.lease_key)
    assert claimed["owner_nonce"] != "deadownerdeadowner"
    assert float(claimed["expires_at"]) > 1.0


def test_controlled_two_managers_race_has_at_most_one_executor() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store = _ControlledCasStore()
    executions = _shared_execution_counter()
    started = PROCESS_CONTEXT.Event()
    release = PROCESS_CONTEXT.Event()
    first_done = threading.Event()
    second_done = threading.Event()
    first = _job_manager(
        _controlled_runner(executions, started, release),
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=first_done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    second = _job_manager(
        _controlled_runner(executions, started, release),
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=second_done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    results: list[dict] = []
    errors: list[BaseException] = []
    ready = threading.Barrier(3)

    def run(manager):
        try:
            ready.wait(2.0)
            results.append(manager.submit(spec))
        except BaseException as exc:
            errors.append(exc)
            raise

    threads = [threading.Thread(target=run, args=(first,)), threading.Thread(target=run, args=(second,))]
    for thread in threads:
        thread.start()
    ready.wait(2.0)
    for thread in threads:
        thread.join(2.0)
        assert not thread.is_alive()
    assert errors == []
    assert started.wait(2.0)
    assert executions.value == 1
    release.set()
    assert sum(1 for row in results if row.get("status") in {"QUEUED", "RUNNING", "COMPLETED"}) == 2
    winner_done = first_done.wait(2.0)
    if not winner_done:
        winner_done = second_done.wait(2.0)
    assert winner_done
    assert executions.value == 1
    terminals = [row for row in results if row.get("status") == "COMPLETED"]
    lookups = [row for row in results if row.get("status") == "RUNNING" and row.get("job_id") == spec.job_id]
    assert len(terminals) + len(lookups) >= 1


def _closed_lease(spec, owner, expires_at, fencing_token=1):
    return {
        "identity": service.CONTROLLED_PILOT_IDENTITY,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "execution_id": spec.execution_id,
        "runner_version": spec.runner_version,
        "kind": "controlled-pilot",
        "owner_nonce": owner,
        "fencing_token": fencing_token,
        "expires_at": expires_at,
        "heartbeat_at": expires_at - 1,
        "status": "CLAIMED",
    }


def test_fresh_manager_observes_active_lease_then_claims_after_expiry() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store = _ControlledCasStore()
    now = __import__("time").time()
    store.objects[spec.lease_key] = (
        service._canonical_bytes(_closed_lease(spec, "oldowneroldowner", now + 0.25)),
        "etag-old",
    )
    executions = _shared_execution_counter()
    done = threading.Event()
    manager = _job_manager(
        _controlled_runner(executions),
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
        lease_ttl_seconds=0.4,
    )
    first = manager.submit(spec)
    assert first["status"] == "RUNNING"
    assert executions.value == 0
    assert manager.status(spec.job_id)["status"] == "RUNNING"
    assert done.wait(3.0)
    assert executions.value == 1
    claimed, _ = store.object_reader(spec, spec.lease_key)
    assert claimed["owner_nonce"] != "oldowneroldowner"
    assert claimed["fencing_token"] == 2


def test_crash_before_executor_fresh_manager_takeover() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store = _ControlledCasStore()
    now = __import__("time").time()
    store.objects[spec.lease_key] = (
        service._canonical_bytes(_closed_lease(spec, "crashedcrashedcr", now + 0.2, 3)),
        "etag-crash",
    )
    executions = _shared_execution_counter()
    done = threading.Event()
    manager = _job_manager(
        _controlled_runner(executions),
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
        lease_ttl_seconds=0.3,
    )
    observed = manager.submit(spec)
    assert observed["status"] == "RUNNING"
    assert executions.value == 0
    later = manager.submit(spec)
    assert later["status"] in {"RUNNING", "QUEUED", "COMPLETED"}
    assert done.wait(3.0)
    assert executions.value == 1


def test_heartbeat_cas_loss_fences_old_executor_zero_late_success() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store = _ControlledCasStore()
    executions = _shared_execution_counter()
    authorized = _shared_execution_counter()
    started = PROCESS_CONTEXT.Event()

    def old_runner(item):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        _increment_execution_counter(executions)
        started.set()
        time.sleep(2.0)
        _increment_execution_counter(authorized)
        return _controlled_completed_result(item)

    old_done = threading.Event()
    new_done = threading.Event()
    old = _job_manager(
        old_runner,
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=old_done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
        lease_ttl_seconds=0.3,
        process_term_grace_seconds=0.05,
        process_kill_grace_seconds=0.5,
    )
    new = _job_manager(
        _controlled_runner(executions),
        terminal_uploader=store.upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        on_terminal=new_done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
        lease_ttl_seconds=0.3,
    )
    old.submit(spec)
    assert started.wait(2.0)
    assert old._supervisor is not None
    old_pid = old._supervisor.pid
    assert old_pid is not None
    lease, etag = store.object_reader(spec, spec.lease_key)
    stolen = dict(lease)
    stolen["owner_nonce"] = "newownernewowner"
    stolen["fencing_token"] = int(lease["fencing_token"]) + 1
    stolen["expires_at"] = 1.0
    store.upload(
        spec.lease_key,
        service._canonical_bytes(stolen),
        spec=spec,
        content_digest="sha256:" + __import__("hashlib").sha256(service._canonical_bytes(stolen)).hexdigest(),
        extra_headers={"if-match": etag},
    )
    try:
        old._heartbeat_controlled_lease(spec)
    except Exception:
        pass
    assert old.lease_lost()
    with pytest.raises(ProcessLookupError):
        os.kill(old_pid, 0)
    assert old_done.wait(2.0)
    takeover = new.submit(spec)
    assert takeover["status"] in {"QUEUED", "RUNNING", "COMPLETED"}
    assert new_done.wait(3.0)
    terminals = [json.loads(raw[0]) for key, raw in store.objects.items() if key.endswith("container-terminal.json")]
    successes = [row for row in terminals if row.get("status") == "COMPLETED" and row.get("ok") is True]
    assert len(successes) == 1
    assert successes[0]["owner_nonce"] != lease["owner_nonce"]
    assert authorized.value == 0



def test_delayed_heartbeat_expired_does_not_upload() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    store = _ControlledCasStore()
    now = time.time()
    expired = _closed_lease(spec, "ownerxxxowner", now - 5.0, fencing_token=7)
    store.objects[spec.lease_key] = (service._canonical_bytes(expired), "etag-7")
    puts: list[str] = []
    original_upload = store.upload

    def recording_upload(key, data, *, spec, content_digest, extra_headers=None):
        puts.append(key)
        return original_upload(
            key,
            data,
            spec=spec,
            content_digest=content_digest,
            extra_headers=extra_headers,
        )

    manager = _job_manager(
        _controlled_runner(_shared_execution_counter()),
        terminal_uploader=recording_upload,
        terminal_reader=store.reader,
        object_reader=store.object_reader,
        max_job_seconds=5,
        retry_schedule=(0.01,),
        lease_ttl_seconds=0.4,
    )
    manager._controlled_lease = dict(expired)
    manager._lease_etag = "etag-7"
    before = store.objects[spec.lease_key][0]
    with pytest.raises(service.JobConflictError, match="expired"):
        manager._heartbeat_controlled_lease(spec)
    assert manager.lease_lost()
    assert puts == []
    claimed, etag = store.object_reader(spec, spec.lease_key)
    assert etag == "etag-7"
    assert claimed["fencing_token"] == 7
    assert claimed["expires_at"] == expired["expires_at"]
    assert store.objects[spec.lease_key][0] == before




class _RecordingBytesResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = headers or {"etag": "etag-1", "content-type": "application/json; charset=utf-8"}
        self.read_sizes: list[int] = []

    def read(self, n: int = -1) -> bytes:
        self.read_sizes.append(n)
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _logical_terminal(spec, *, pad: int = 0) -> dict:
    body = {
        **_controlled_completed_result(spec),
        "owner_nonce": "owner-nonce-1",
        "fencing_token": 1,
    }
    if pad:
        body["papers"][0]["pad"] = "x" * pad
    return body


def _embedded_terminal_lease(spec, payload: bytes, owner: str = "owner-nonce-1") -> dict:
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    return {
        "identity": service.CONTROLLED_PILOT_IDENTITY,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "execution_id": spec.execution_id,
        "runner_version": spec.runner_version,
        "kind": "controlled-pilot",
        "owner_nonce": owner,
        "fencing_token": 1,
        "expires_at": 10.0,
        "heartbeat_at": 9.0,
        "status": "TERMINAL",
        "terminal_digest": digest,
        "terminal_status": "COMPLETED",
        "terminal_payload_b64": __import__("base64").b64encode(payload).decode("ascii"),
    }


def _near_max_stored_lease(spec) -> tuple[bytes, bytes]:
    low = 0
    high = service.CONTROLLED_TERMINAL_MAX_BYTES
    best_payload = service._canonical_bytes(_logical_terminal(spec))
    best_stored = service._canonical_bytes(_embedded_terminal_lease(spec, best_payload))
    while low <= high:
        mid = (low + high) // 2
        payload = service._canonical_bytes(_logical_terminal(spec, pad=mid))
        stored = service._canonical_bytes(_embedded_terminal_lease(spec, payload))
        if (
            len(payload) <= service.CONTROLLED_TERMINAL_MAX_BYTES
            and len(stored) <= service.CONTROLLED_LEASE_STORED_MAX_BYTES
        ):
            best_payload, best_stored = payload, stored
            low = mid + 1
        else:
            high = mid - 1
    assert len(best_payload) > 8 * 1024
    assert len(best_payload) <= service.CONTROLLED_TERMINAL_MAX_BYTES
    assert len(best_stored) > service.CONTROLLED_LEASE_MAX_BYTES
    assert len(best_stored) <= service.CONTROLLED_LEASE_STORED_MAX_BYTES
    assert service.CONTROLLED_TERMINAL_MAX_BYTES - len(best_payload) < 64
    return best_payload, best_stored


def test_python_stored_lease_cap_matches_worker_formula() -> None:
    expected = (
        8 * 1024
        + ((64 * 1024 + 2) // 3) * 4
        + 2048
    )
    assert service.CONTROLLED_LEASE_MAX_BYTES == 8 * 1024
    assert service.CONTROLLED_TERMINAL_MAX_BYTES == 64 * 1024
    assert service.CONTROLLED_LEASE_STORED_MAX_BYTES == expected
    assert expected == 97624


def test_near_maximum_embedded_terminal_lease_recovery(monkeypatch) -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    payload, stored = _near_max_stored_lease(spec)
    logical = json.loads(payload.decode("utf-8"))
    responses: dict[str, _RecordingBytesResponse] = {}
    puts: list[str] = []

    def urlopen(request, timeout=None):
        del timeout
        key = urllib.parse.urlparse(request.full_url).path.lstrip("/")
        method = request.get_method()
        if method == "PUT":
            puts.append(key)
            raise AssertionError(f"unexpected PUT {key}")
        if key == spec.lease_key:
            response = _RecordingBytesResponse(stored, headers={"etag": "etag-terminal-lease"})
        elif key == spec.manifest_key:
            response = _RecordingBytesResponse(payload, headers={"etag": "etag-logical"})
        else:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", Message(), io.BytesIO(b""))
        responses[key] = response
        return response

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen)
    parsed, etag = service._get_json_at(spec, spec.lease_key)
    assert etag == "etag-terminal-lease"
    assert parsed is not None
    assert parsed["status"] == "TERMINAL"
    assert parsed["terminal_digest"] == "sha256:" + hashlib.sha256(payload).hexdigest()
    lease_reads = responses[spec.lease_key].read_sizes
    assert lease_reads == [service.CONTROLLED_LEASE_STORED_MAX_BYTES + 1]

    logical_got = service._get_json(spec)
    assert logical_got == logical
    assert responses[spec.manifest_key].read_sizes == [service.CONTROLLED_TERMINAL_MAX_BYTES + 1]

    executions = _shared_execution_counter()
    done = threading.Event()
    store = _ControlledCasStore()
    store.objects[spec.lease_key] = (stored, "etag-terminal-lease")

    def reader(item):
        del item
        return dict(logical)

    manager = _job_manager(
        _controlled_runner(executions),
        terminal_uploader=store.upload,
        terminal_reader=reader,
        object_reader=store.object_reader,
        on_terminal=done.set,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    first = manager.submit(spec)
    assert first["status"] == "COMPLETED"
    assert first["execution_id"] == spec.execution_id
    assert executions.value == 0
    assert done.is_set() is False
    replay = manager.submit(spec)
    assert replay["status"] == "COMPLETED"
    assert executions.value == 0
    claimed, _ = store.object_reader(spec, spec.lease_key)
    assert claimed["status"] == "TERMINAL"
    assert claimed["owner_nonce"] == "owner-nonce-1"
    assert puts == []

    manager._controlled_lease = {
        "owner_nonce": "owner-nonce-1",
        "fencing_token": 1,
    }
    manager._lease_etag = "etag-terminal-lease"
    before = store.objects[spec.lease_key][0]
    try:
        manager._heartbeat_controlled_lease(spec)
        raise AssertionError("heartbeat after terminal must fail closed")
    except service.JobConflictError:
        pass
    assert manager.lease_lost()
    assert store.objects[spec.lease_key][0] == before


def test_oversized_stored_lease_fails_closed(monkeypatch) -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    oversized = b"{" + b"x" * service.CONTROLLED_LEASE_STORED_MAX_BYTES
    assert len(oversized) == service.CONTROLLED_LEASE_STORED_MAX_BYTES + 1
    response = _RecordingBytesResponse(oversized, headers={"etag": "etag-over"})

    def urlopen(request, timeout=None):
        del timeout, request
        return response

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen)
    with pytest.raises(service.TerminalReadDenied, match="exceeds bound"):
        service._get_json_at(spec, spec.lease_key)
    assert response.read_sizes == [service.CONTROLLED_LEASE_STORED_MAX_BYTES + 1]

    huge_logical = b"{" + b"y" * service.CONTROLLED_TERMINAL_MAX_BYTES
    logical_response = _RecordingBytesResponse(huge_logical)

    def urlopen_logical(request, timeout=None):
        del timeout, request
        return logical_response

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen_logical)
    with pytest.raises(service.TerminalReadDenied, match="exceeds bound"):
        service._get_json(spec)
    assert logical_response.read_sizes == [service.CONTROLLED_TERMINAL_MAX_BYTES + 1]


def test_terminal_lease_does_not_takeover_when_logical_terminal_missing() -> None:
    spec = service.ControlledPilotJobSpec.from_document(_controlled_job_spec())
    payload, stored = _near_max_stored_lease(spec)
    del payload
    store = _ControlledCasStore()
    store.objects[spec.lease_key] = (stored, "etag-terminal-lease")
    executions = _shared_execution_counter()
    manager = _job_manager(
        _controlled_runner(executions),
        terminal_uploader=store.upload,
        terminal_reader=lambda item: None,
        object_reader=store.object_reader,
        max_job_seconds=5,
        retry_schedule=(0.01,),
    )
    try:
        observed = manager.submit(spec)
        assert observed["status"] == "RUNNING"
        assert observed.get("lease_observer") is True
        assert executions.value == 0
        claimed, _ = store.object_reader(spec, spec.lease_key)
        assert claimed["status"] == "TERMINAL"
        assert claimed["owner_nonce"] == "owner-nonce-1"
    finally:
        with manager._lock:
            recovery = manager._lease_recovery
            manager._lease_recovery = None
            heartbeat = manager._lease_heartbeat
            manager._lease_heartbeat = None
        if recovery is not None:
            recovery.cancel()
        if heartbeat is not None:
            heartbeat.cancel()
