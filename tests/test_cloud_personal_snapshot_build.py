from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ingestion.personal_history import (
    PERSONAL_HISTORY_FORMAT,
    PERSONAL_HISTORY_SCOPE_DIGEST,
)

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
    "cloud_personal_snapshot_service", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
service = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


def _digest(request: dict) -> str:
    body = {
        "format": PERSONAL_HISTORY_FORMAT,
        "job_id": request["job_id"],
        "lookback_sessions": request["lookback_sessions"],
        "period_end": request["period_end"],
        "period_start": request["period_start"],
        "runner_version": service.RUNNER_VERSION,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _spec(job_id: str = "snap-build") -> service.SnapshotJobSpec:
    request = {
        "job_id": job_id,
        "lookback_sessions": 10,
        "period_end": "2024-12-31",
        "period_start": "2024-01-01",
        "runner_version": service.RUNNER_VERSION,
        "format": PERSONAL_HISTORY_FORMAT,
    }
    return service.SnapshotJobSpec.from_document(
        {
            **request,
            "deployment_id": "test-deploy",
            "environment": "production",
            "manifest_key": f"research/personal/snapshot-builds/job={job_id}/manifest.json",
            "max_database_bytes": service.SNAPSHOT_MAX_DATABASE_BYTES,
            "request_digest": _digest(request),
        }
    )


class _FakeHydrator:
    def __init__(self, **kwargs):
        self.store = kwargs["store"]
        self.plan = kwargs["plan"]
        self.max_database_bytes = kwargs["max_database_bytes"]

    def hydrate(self):
        self.store._conn.execute(
            "CREATE TABLE IF NOT EXISTS personal_history_manifest ("
            "singleton INTEGER PRIMARY KEY, format TEXT, status TEXT, "
            "observed_through TEXT, revision_window_calendar_days INTEGER, "
            "revision_coverage TEXT)"
        )
        columns = {
            str(row[1])
            for row in self.store._conn.execute(
                "PRAGMA table_info(personal_history_manifest)"
            )
        }
        if "observed_through" not in columns:
            self.store._conn.execute(
                "ALTER TABLE personal_history_manifest ADD COLUMN observed_through TEXT"
            )
        if "revision_window_calendar_days" not in columns:
            self.store._conn.execute(
                "ALTER TABLE personal_history_manifest "
                "ADD COLUMN revision_window_calendar_days INTEGER"
            )
        if "revision_coverage" not in columns:
            self.store._conn.execute(
                "ALTER TABLE personal_history_manifest ADD COLUMN revision_coverage TEXT"
            )
        updated = self.store._conn.execute(
            "UPDATE personal_history_manifest SET observed_through=?,"
            "revision_window_calendar_days=?,revision_coverage=? WHERE singleton=1",
            ("2024-12-31T16:00:00+09:00", 40, "WINDOW_COMPLETE"),
        )
        if updated.rowcount == 0:
            self.store._conn.execute(
                "INSERT INTO personal_history_manifest("
                "singleton, format, status, observed_through, "
                "revision_window_calendar_days, revision_coverage) "
                "VALUES (1, 'unmanaged-catalog', 'COMPLETE_DRAFT', "
                "'2024-12-31T16:00:00+09:00', 40, 'WINDOW_COMPLETE')"
            )
        self.store._conn.commit()
        lookback = int(self.plan.lookback_sessions)
        return SimpleNamespace(
            bar_start="2024-01-04",
            segment_counts={"markets_calendar": 1, "equities_master": 1},
            fetched_rows=2,
            written_rows=2,
            actual_lookback_sessions=lookback,
            lookback_truncated=False,
        )


def test_inclusive_snapshot_period_cap_is_7000_calendar_dates() -> None:
    accepted = _spec("bound-7000")
    document = {
        "deployment_id": accepted.deployment_id,
        "environment": accepted.environment,
        "format": accepted.format,
        "job_id": "bound-7000",
        "lookback_sessions": accepted.lookback_sessions,
        "manifest_key": "research/personal/snapshot-builds/job=bound-7000/manifest.json",
        "max_database_bytes": accepted.max_database_bytes,
        "period_end": "2026-03-01",
        "period_start": "2007-01-01",
        "runner_version": accepted.runner_version,
    }
    document["request_digest"] = _digest(
        {
            "job_id": document["job_id"],
            "lookback_sessions": document["lookback_sessions"],
            "period_end": document["period_end"],
            "period_start": document["period_start"],
        }
    )
    service.SnapshotJobSpec.from_document(document)
    over = dict(document)
    over["period_end"] = "2026-03-02"
    over["request_digest"] = _digest(
        {
            "job_id": over["job_id"],
            "lookback_sessions": over["lookback_sessions"],
            "period_end": over["period_end"],
            "period_start": over["period_start"],
        }
    )
    with pytest.raises(service.JobInputError, match="inclusive calendar dates"):
        service.SnapshotJobSpec.from_document(over)


def test_snapshot_gzip_and_manifest_last_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _FakeHydrator)
    spec = _spec()
    uploads: list[str] = []

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        uploads.append(key)
        if isinstance(data, Path):
            assert data.exists()

    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=lambda _spec: object()
    )
    assert manifest["status"] == "COMPLETED"
    assert uploads == [
        manifest["snapshot_key"],
        spec.manifest_key,
    ]
    assert manifest["snapshot_key"].endswith(".sqlite.gz")
    assert manifest["raw_sha256"].startswith("sha256:")
    assert manifest["gzip_sha256"].startswith("sha256:")
    assert manifest["raw_sha256"] != manifest["gzip_sha256"]
    assert manifest["data_start"] == "2024-01-04"
    assert manifest["period_start"] == "2024-01-01"
    assert manifest["lookback_sessions"] == spec.lookback_sessions
    assert "requested_lookback_sessions" not in manifest
    assert manifest["actual_lookback_sessions"] == spec.lookback_sessions
    assert manifest["lookback_truncated"] is False


class _TruncatedHydrator(_FakeHydrator):
    def hydrate(self):
        result = super().hydrate()
        result.actual_lookback_sessions = 0
        result.lookback_truncated = True
        return result


def test_snapshot_manifest_records_truncated_lookback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _TruncatedHydrator)
    spec = _spec("snap-lookback-trunc")
    manifest = service.execute_snapshot_job(
        spec,
        work_root=tmp_path,
        uploader=lambda *args, **kwargs: None,
        client_factory=lambda _spec: object(),
    )
    assert manifest["status"] == "COMPLETED"
    assert manifest["period_start"] == spec.period_start
    assert manifest["lookback_sessions"] == spec.lookback_sessions
    assert "requested_lookback_sessions" not in manifest
    assert manifest["actual_lookback_sessions"] == 0
    assert manifest["lookback_truncated"] is True
    assert manifest["research_state"] == "PERSONAL_DRAFT"
    assert manifest["completeness_claim"] == "NONE"
    assert manifest["controlled_live_eligibility"] == "FORBIDDEN"
    assert manifest["history_scope_digest"] == PERSONAL_HISTORY_SCOPE_DIGEST
    assert "api_key" not in json.dumps(manifest).lower()
    assert "secret" not in json.dumps(manifest).lower()


class _MetricsClient:
    def cache_metrics(self):
        return {
            "cache_hits": 4,
            "cache_misses": 1,
            "cache_published": 3,
            "cache_unavailable": 0,
            "live_fetch_calls": 2,
        }

    def close(self):
        return None


def test_snapshot_manifest_includes_cache_metrics_on_completion(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _FakeHydrator)
    spec = _spec("snap-metrics")
    uploads: list[str] = []

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers, data
        uploads.append(key)

    manifest = service.execute_snapshot_job(
        spec,
        work_root=tmp_path,
        uploader=upload,
        client_factory=lambda _spec: _MetricsClient(),
    )
    assert manifest["status"] == "COMPLETED"
    assert manifest["cache_hits"] == 4
    assert manifest["cache_misses"] == 1
    assert manifest["cache_published"] == 3
    assert manifest["cache_unavailable"] == 0
    assert manifest["live_fetch_calls"] == 2
    assert "authorization" not in json.dumps(manifest).lower()


def test_snapshot_manifest_includes_cache_metrics_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    class BoomHydrator(_FakeHydrator):
        def hydrate(self):
            raise RuntimeError("hydrate exploded")

    monkeypatch.setattr(service, "PersonalHistoryHydrator", BoomHydrator)
    spec = _spec("snap-metrics-fail")
    uploads: list[tuple[str, dict]] = []

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = data.read_bytes() if isinstance(data, Path) else bytes(data)
        uploads.append((key, json.loads(body) if key.endswith("manifest.json") else {}))

    manifest = service.execute_snapshot_job(
        spec,
        work_root=tmp_path,
        uploader=upload,
        client_factory=lambda _spec: _MetricsClient(),
    )
    assert manifest["status"] == "FAILED"
    assert manifest["cache_hits"] == 4
    assert manifest["live_fetch_calls"] == 2
    assert uploads[-1][0] == spec.manifest_key
    assert uploads[-1][1]["cache_misses"] == 1
    assert "api_key" not in json.dumps(manifest).lower()


def test_planner_admission_budget_fits_operational_windows_under_five_gib() -> None:
    assert service.MAX_SNAPSHOT_BYTES == 4 * 1024 * 1024 * 1024
    assert service.SNAPSHOT_MAX_DATABASE_BYTES == 5 * 1024 * 1024 * 1024
    six_year = service.build_personal_history_plan(
        period_start="2008-07-07",
        period_end="2014-07-15",
        lookback_sessions=0,
    )
    two_year = service.build_personal_history_plan(
        period_start="2008-07-07",
        period_end="2010-06-30",
        lookback_sessions=252,
    )
    full_compact = service.build_personal_history_plan(
        period_start="2008-01-01",
        period_end="2026-08-31",
        lookback_sessions=252,
    )
    assert six_year.estimated_bytes < service.SNAPSHOT_MAX_DATABASE_BYTES
    assert two_year.estimated_bytes < service.SNAPSHOT_MAX_DATABASE_BYTES
    assert full_compact.estimated_bytes < service.SNAPSHOT_MAX_DATABASE_BYTES


def test_oversized_plan_fails_before_acquisition_without_snapshot_upload(
    tmp_path: Path, monkeypatch
) -> None:
    real_plan = service.build_personal_history_plan
    spec = _spec("snap-plan-oversize")
    store_calls: list[object] = []
    factory_calls: list[object] = []
    hydrator_calls: list[object] = []
    uploads: list[tuple[str, dict]] = []

    def oversized_plan(**kwargs):
        return replace(
            real_plan(**kwargs),
            estimated_bytes=spec.max_database_bytes + 1,
        )

    def tracking_store(*args, **kwargs):
        store_calls.append((args, kwargs))
        raise AssertionError("SqliteStore must not be created")

    class TrackingHydrator(_FakeHydrator):
        def __init__(self, **kwargs):
            hydrator_calls.append(kwargs)
            super().__init__(**kwargs)

    def factory(_spec):
        factory_calls.append(_spec)
        raise AssertionError("client_factory must not be invoked")

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = data.read_bytes() if isinstance(data, Path) else bytes(data)
        uploads.append(
            (key, json.loads(body) if key.endswith("manifest.json") else {"bytes": len(body)})
        )

    monkeypatch.setattr(service, "build_personal_history_plan", oversized_plan)
    monkeypatch.setattr(service, "SqliteStore", tracking_store)
    monkeypatch.setattr(service, "PersonalHistoryHydrator", TrackingHydrator)
    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=factory
    )
    assert manifest["status"] == "FAILED"
    assert store_calls == []
    assert factory_calls == []
    assert hydrator_calls == []
    assert [key for key, _ in uploads] == [spec.manifest_key]
    assert manifest.get("snapshot_key") is None
    assert "snapshot planning allowance exceeds builder cap" in manifest["error"]
    assert "conservative" not in manifest["error"]
    assert f"estimated={spec.max_database_bytes + 1}" in manifest["error"]
    assert f"limit={spec.max_database_bytes}" in manifest["error"]
    assert "api_key" not in json.dumps(manifest).lower()
    assert "secret" not in json.dumps(manifest).lower()


def test_safe_sized_plan_still_reaches_snapshot_execution(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _FakeHydrator)
    spec = _spec("snap-plan-safe")
    factory_calls: list[object] = []
    uploads: list[str] = []

    def factory(_spec):
        factory_calls.append(_spec)
        return object()

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers, data
        uploads.append(key)

    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=factory
    )
    assert factory_calls == [spec]
    assert manifest["status"] == "COMPLETED"
    assert uploads == [manifest["snapshot_key"], spec.manifest_key]


def test_oversized_gzip_fails_locally_before_hash_and_upload(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _FakeHydrator)
    spec = _spec("snap-gzip-oversize")
    uploads: list[str] = []
    hashed: list[str] = []

    def fake_gzip(source: Path, destination: Path) -> None:
        del source
        destination.write_bytes(b"tiny")

    original_stat = Path.stat

    def huge_gzip_stat(self, *args, **kwargs):
        if self.name == "personal-history.sqlite.gz":
            return SimpleNamespace(st_size=service.MAX_SNAPSHOT_BYTES + 1)
        return original_stat(self, *args, **kwargs)

    real_sha256 = service._sha256_file

    def tracking_sha256(path: Path) -> str:
        hashed.append(Path(path).name)
        return real_sha256(path)

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers, data
        uploads.append(key)
        if str(key).endswith(".sqlite.gz"):
            raise AssertionError("gzip snapshot uploader must not be called")

    monkeypatch.setattr(service, "_gzip_file", fake_gzip)
    monkeypatch.setattr(Path, "stat", huge_gzip_stat)
    monkeypatch.setattr(service, "_sha256_file", tracking_sha256)
    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=lambda _spec: object()
    )
    assert manifest["status"] == "FAILED"
    assert "compressed snapshot exceeds 4 GiB transport cap" in manifest["error"]
    assert [key for key in uploads] == [spec.manifest_key]
    assert manifest.get("snapshot_key") is None
    assert "personal-history.sqlite.gz" not in hashed


def test_size_failure_does_not_publish_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _FakeHydrator)
    spec = _spec("snap-oversize")
    uploads: list[tuple[str, dict]] = []

    def upload(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers
        body = data.read_bytes() if isinstance(data, Path) else bytes(data)
        uploads.append((key, json.loads(body) if key.endswith("manifest.json") else {"bytes": len(body)}))

    original_stat = Path.stat

    def huge_stat(self, *args, **kwargs):
        result = original_stat(self, *args, **kwargs)
        if self.name == "personal-history.sqlite":
            return result._replace(st_size=service.SNAPSHOT_MAX_DATABASE_BYTES + 1)
        return result

    monkeypatch.setattr(Path, "stat", huge_stat)
    manifest = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=upload, client_factory=lambda _spec: object()
    )
    assert manifest["status"] == "FAILED"
    assert [key for key, _ in uploads] == [spec.manifest_key]
    assert manifest.get("snapshot_key") is None


def test_crash_before_manifest_retries_without_success_publish(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(service, "PersonalHistoryHydrator", _FakeHydrator)
    spec = _spec("snap-retry")
    attempts: list[list[str]] = []

    def flaky(key, data, *, spec, content_digest, extra_headers=None):
        del spec, content_digest, extra_headers, data
        current = attempts[-1]
        current.append(key)
        if key.endswith("manifest.json") and len(attempts) == 1:
            raise RuntimeError("crash after gzip")

    attempts.append([])
    with pytest.raises(RuntimeError, match="crash after gzip"):
        service.execute_snapshot_job(
            spec, work_root=tmp_path, uploader=flaky, client_factory=lambda _spec: object()
        )
    assert attempts[0] and attempts[0][0].endswith(".sqlite.gz")
    assert not any(key.endswith("manifest.json") and False for key in attempts[0])

    attempts.append([])
    second = service.execute_snapshot_job(
        spec, work_root=tmp_path, uploader=flaky, client_factory=lambda _spec: object()
    )
    assert second["status"] == "COMPLETED"
    assert attempts[1] == [second["snapshot_key"], spec.manifest_key]
