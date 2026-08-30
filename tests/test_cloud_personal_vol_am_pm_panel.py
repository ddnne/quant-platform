from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from test_cloud_personal_research_container import service
import personal_vol_am_pm_panel_job as job


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200):
        super().__init__(data)
        self.headers = {"content-length": str(len(data))}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _sqlite_bytes(*, codes: list[str], dates: list[str], typed: bool = True) -> bytes:
    handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    handle.close()
    path = handle.name
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE personal_history_manifest (singleton INTEGER PRIMARY KEY, format TEXT)"
    )
    connection.execute(
        "INSERT INTO personal_history_manifest VALUES (1, 'personal-draft-history/v4')"
    )
    if typed:
        connection.execute(
            """
            CREATE TABLE jquants_daily_bars (
                source TEXT, code TEXT, date TEXT, close REAL, volume REAL,
                turnover_value REAL, morning_adjustment_close REAL,
                afternoon_adjustment_close REAL, adjustment_close REAL
            )
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE jquants_daily_bars (
                source TEXT, code TEXT, date TEXT, close REAL, volume REAL,
                turnover_value REAL, adjustment_close REAL
            )
            """
        )
    connection.execute(
        """
        CREATE TABLE personal_history_segments (
            dataset TEXT, segment_id TEXT, state TEXT, facts_digest TEXT,
            response_digest TEXT, query_start TEXT, query_end TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO personal_history_segments
        VALUES ('markets_calendar','cal-1','OBSERVED','sha256:aa','sha256:bb','2019-01-01','2025-12-29')
        """
    )
    connection.execute(
        "CREATE TABLE jquants_records (source TEXT, dataset TEXT, event_time TEXT, payload TEXT)"
    )
    for index, day in enumerate(dates):
        connection.execute(
            """
            INSERT INTO jquants_records VALUES ('jquants','markets_calendar',?,?)
            """,
            (
                f"{day}T00:00:00+09:00",
                json.dumps({"Date": day, "HolidayDivision": "1"}),
            ),
        )
        for code in codes:
            morning = 100 + index
            afternoon = 200 + index
            if typed:
                connection.execute(
                    """
                    INSERT INTO jquants_daily_bars
                    VALUES ('jquants',?,?,?,?,?,?,?,?)
                    """,
                    (code, day, afternoon, 1000, 1000 * afternoon, morning, afternoon, afternoon),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO jquants_daily_bars
                    VALUES ('jquants',?,?,?,?,?,?)
                    """,
                    (code, day, afternoon, 1000, 1000 * afternoon, afternoon),
                )
            if day == dates[0]:
                connection.execute(
                    """
                    INSERT INTO jquants_records VALUES ('jquants','fins_summary',?,?)
                    """,
                    (
                        f"{day}T15:00:00+09:00",
                        json.dumps(
                            {
                                "Code": code,
                                "TA": 1,
                                "EqAR": 1,
                                "DiscDate": "2019-03-01",
                            }
                        ),
                    ),
                )
    connection.commit()
    connection.close()
    raw = Path(path).read_bytes()
    Path(path).unlink(missing_ok=True)
    return raw


def _gzip(raw: bytes) -> bytes:
    return gzip.compress(raw)


def _sidecar() -> dict[str, Any]:
    dates = [f"2021-01-{index:02d}" for index in range(4, 20)]
    series = {day: 2.0 for day in dates}
    long = {day: 1.0 for day in dates}
    rolling = {"rv_short_by_date": series, "rv_long_by_date": long, "rv_abs_by_date": series}
    return {
        "bars": {"A": [[day, 10] for day in dates]},
        "calendar": {"dates": dates},
        "opt225_regime": {
            "source": {
                "dataset": job.OPTION_DATASET,
                "version": job.SUPPORTED_OPTION_VERSIONS[-1],
            },
            "basevol": rolling,
            "atm_iv": rolling,
            "skew": rolling,
            "cm_term_ratio": {"rv_abs_by_date": series},
        },
    }


def _snapshot_lock(job_id: str, period_id: str, start: str, end: str, gzip_bytes: bytes, raw: bytes) -> dict[str, Any]:
    raw_digest = _digest(raw)
    gzip_digest = _digest(gzip_bytes)
    hex_raw = raw_digest.split(":", 1)[1]
    snapshot_key = f"research/personal/snapshots/sha256={hex_raw}.sqlite.gz"
    return {
        "job_id": job_id,
        "role": "selection_2019" if period_id == "y2019_selection" else "evaluation_period",
        "period_id": period_id,
        "period_start": start,
        "period_end": end,
        "lookback_sessions": 0 if period_id == "y2019_selection" else 61,
        "format": "personal-draft-history/v4",
        "runner_version": job.RUNNER_VERSION,
        "manifest": {
            "key": f"research/personal/snapshot-builds/job={job_id}/manifest.json",
            "etag": f"man-{job_id}",
            "size": 8,
            "sha256": gzip_digest,
        },
        "snapshot": {
            "key": snapshot_key,
            "etag": f"snap-{job_id}",
            "size": len(gzip_bytes),
            "sha256": gzip_digest,
            "raw_sha256": raw_digest,
            "gzip_sha256": gzip_digest,
        },
    }


def _input_manifest(store: dict[str, bytes], dates: list[str]) -> dict[str, Any]:
    selection_raw = _sqlite_bytes(codes=["13010", "72030"], dates=dates)
    selection_gzip = _gzip(selection_raw)
    selection = _snapshot_lock(
        "snap-2019", "y2019_selection", "2019-01-01", "2019-10-21", selection_gzip, selection_raw
    )
    store[selection["snapshot"]["key"]] = selection_gzip
    periods = {}
    sidecars = {}
    sidecar = _sidecar()
    sidecar_bytes = json.dumps(sidecar).encode()
    for period in job.EVALUATION_PERIODS:
        raw = _sqlite_bytes(codes=["13010", "72030"], dates=dates)
        compressed = _gzip(raw)
        lock = _snapshot_lock(
            f"snap-{period['period_id']}",
            period["period_id"],
            period["period_start"],
            period["period_end"],
            compressed,
            raw,
        )
        store[lock["snapshot"]["key"]] = compressed
        periods[period["period_id"]] = lock
        digest = _digest(sidecar_bytes)
        key = f"research/personal/option-sidecar/objects/{digest}.json"
        store[key] = sidecar_bytes
        sidecars[period["period_id"]] = {
            "period_id": period["period_id"],
            "source_key": key,
            "etag": "side",
            "size": len(sidecar_bytes),
            "sha256": digest,
        }
    return {
        "schema_version": job.INPUT_SCHEMA,
        "producer_id": job.PRODUCER_ID,
        "job_id": "vol-panel-py",
        "cohort_id": job.COHORT_ID,
        "runner_version": job.RUNNER_VERSION,
        "panel_schema": job.PANEL_SCHEMA,
        "required_lookback_sessions": 61,
        "selection": selection,
        "periods": periods,
        "sidecar_producer": {
            "job_id": "sidecar-one",
            "terminal": {
                "key": "research/personal/option-sidecar/job=sidecar-one/manifest.json",
                "etag": "term",
                "size": 8,
                "sha256": _digest(b"term"),
            },
        },
        "option_sidecars": sidecars,
    }


def _spec(manifest: dict[str, Any], input_digest: str) -> job.PersonalVolAmPmPanelJobSpec:
    body = {
        "cohort_id": job.COHORT_ID,
        "input_manifest_digest": input_digest,
        "input_manifest_key": f"research/personal/vol-ratio-am-pm-v1/panel-builds/job={manifest['job_id']}/input-manifest.json",
        "job_id": manifest["job_id"],
        "manifest_key": f"research/personal/vol-ratio-am-pm-v1/panel-builds/job={manifest['job_id']}/manifest.json",
        "producer_id": job.PRODUCER_ID,
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": job.RUNNER_VERSION,
    }
    provisional = job.PersonalVolAmPmPanelJobSpec(**body)
    body["request_digest"] = job._request_digest_from_manifest(provisional, manifest)
    return job.PersonalVolAmPmPanelJobSpec.from_document(body)


def test_vol_panel_job_fields_are_closed() -> None:
    with pytest.raises(job.VolPanelJobInputError):
        job.PersonalVolAmPmPanelJobSpec.from_document(
            {
                "cohort_id": job.COHORT_ID,
                "job_id": "x",
            }
        )


def test_sidecar_extract_is_structural_n225_only() -> None:
    sidecar = _sidecar()
    sidecar["opt225_regime"]["individual_stock_iv_used"] = False
    extracted = job._extract_opt225_regime(sidecar)
    assert extracted["source"]["dataset"] == job.OPTION_DATASET
    assert "bars" not in extracted
    assert "calendar" not in extracted
    with pytest.raises(RuntimeError, match="must be rebuilt"):
        job._extract_opt225_regime({"bars": {"A": [["2021-01-04", 1]]}})
    individual = _sidecar()
    individual["opt225_regime"]["source"]["dataset"] = "equity_option_iv"
    with pytest.raises(RuntimeError, match="must be rebuilt"):
        job._extract_opt225_regime(individual)
    mapped = _sidecar()
    mapped["opt225_regime"]["by_code"] = {"13010": {"2021-01-04": 1.0}}
    with pytest.raises(RuntimeError, match="must be rebuilt"):
        job._extract_opt225_regime(mapped)


def test_sidecar_extract_accepts_thicken_canonical_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research.cf_mass_eval_thicken as thicken
    from research.options_225_vol_series import (
        DATASET_ID,
        OPTIONS_225_VOL_SERIES_VERSION,
    )

    series = {
        "rv_abs_by_date": {"2021-01-04": 20.0},
        "rv_short_by_date": {"2021-01-04": 20.0},
        "rv_long_by_date": {"2021-01-04": 19.0},
        "rv_ratio_by_date": {"2021-01-04": 20.0 / 19.0},
    }
    monkeypatch.setattr(
        thicken,
        "load_opt225_regime_bundle_for_eval",
        lambda: {
            "dataset": DATASET_ID,
            "version": OPTIONS_225_VOL_SERIES_VERSION,
            "basevol": dict(series),
            "atm_iv": dict(series),
            "spread": dict(series),
            "spread_change": dict(series),
            "skew": dict(series),
            "cm_term": dict(series),
            "cm_term_ratio": dict(series),
            "basevol_delta": dict(series),
        },
    )
    attached = thicken.attach_opt225_regime()
    assert "spread" in attached["opt225_regime"]
    assert "rv_ratio_by_date" in attached["opt225_regime"]["basevol"]
    extracted = job._extract_opt225_regime(attached)
    assert extracted["source"] == {
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
    }
    assert set(extracted) == {"source", "basevol", "atm_iv", "skew", "cm_term_ratio"}
    assert set(extracted["basevol"]) == {"rv_short_by_date", "rv_long_by_date"}
    assert "spread" not in extracted
    assert "cm_term" not in extracted
    assert "basevol_delta" not in extracted
    by_code = json.loads(json.dumps(attached))
    by_code["opt225_regime"]["by_code"] = {"13010": {"2021-01-04": 1.0}}
    with pytest.raises(RuntimeError, match="must be rebuilt"):
        job._extract_opt225_regime(by_code)


def test_execute_writes_children_before_terminal_and_recomputes_common_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job, "EVAL_UNIVERSE_POOL", ("13010", "72030"))
    monkeypatch.setattr(job, "UNIVERSE_MIN_BAR_DAYS", 2)
    dates = [f"2019-01-{index:02d}" for index in range(4, 16)] + [
        f"2021-01-{index:02d}" for index in range(4, 16)
    ]
    store: dict[str, bytes] = {}
    manifest = _input_manifest(store, dates)
    input_bytes = _canonical(manifest)
    input_digest = _digest(input_bytes)
    spec = _spec(manifest, input_digest)
    store[spec.input_manifest_key] = input_bytes
    puts: list[str] = []

    def opener(_spec, key):
        return _Response(store[key])

    def uploader(_spec, key, data):
        puts.append(key)
        store[key] = data
        return _digest(data)

    terminal = job.execute_vol_am_pm_panel_job(spec, opener=opener, uploader=uploader)
    assert terminal["status"] == "COMPLETED"
    assert terminal["runner_version"] == "personal-cloud-runner/v13"
    assert puts[-1] == spec.manifest_key
    assert spec.manifest_key not in puts[:-1]
    period = job.EVALUATION_PERIODS[0]["period_id"]
    panel = json.loads(store[terminal["periods"][period]["panel_key"]])
    assert panel["bars"]["13010"][0]["MAdjC"] is not None
    assert panel["bars"]["13010"][0]["AAdjC"] is not None
    assert panel["session_calendar"]["dataset"] == "markets_calendar"
    assert panel["opt225_regime"]["source"]["dataset"] == job.OPTION_DATASET
    assert set(panel["bars"]["13010"][0]) == {"date", "MAdjC", "AAdjC"}
    assert "equity_universe" not in panel
    assert terminal["periods"][period]["panel_key"].endswith(".json")
    assert "stable_key" not in terminal["periods"][period]
    assert "common_valid_key" not in terminal["periods"][period]
    recomputed = job._common_valid_rows(
        panel["session_calendar"]["dates"],
        panel["codes"],
        panel["bars"],
        panel["opt225_regime"],
    )
    assert _digest(_canonical({"rows": recomputed, "schema_version": job.COMMON_VALID_SCHEMA})) == terminal[
        "periods"
    ][period]["common_valid_sha256"]
    assert terminal["membership"]["codes"] == panel["codes"]


def test_missing_typed_ma_columns_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "EVAL_UNIVERSE_POOL", ("13010",))
    monkeypatch.setattr(job, "UNIVERSE_MIN_BAR_DAYS", 2)
    dates = [f"2019-01-{index:02d}" for index in range(4, 16)]
    raw = _sqlite_bytes(codes=["13010"], dates=dates, typed=False)
    compressed = _gzip(raw)
    store: dict[str, bytes] = {}
    manifest = _input_manifest(store, dates)
    for period in job.EVALUATION_PERIODS:
        lock = _snapshot_lock(
            f"snap-{period['period_id']}",
            period["period_id"],
            period["period_start"],
            period["period_end"],
            compressed,
            raw,
        )
        manifest["periods"][period["period_id"]] = lock
        store[lock["snapshot"]["key"]] = compressed
    input_bytes = _canonical(manifest)
    spec = _spec(manifest, _digest(input_bytes))
    store[spec.input_manifest_key] = input_bytes

    def opener(_spec, key):
        return _Response(store[key])

    def uploader(_spec, key, data):
        store[key] = data
        return _digest(data)

    terminal = job.execute_vol_am_pm_panel_job(spec, opener=opener, uploader=uploader)
    assert terminal["status"] == "FAILED"
    assert "typed M/A" in terminal["error"]


def test_job_manager_409_then_verified_get(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = [f"2019-01-{index:02d}" for index in range(4, 8)]
    store: dict[str, bytes] = {}
    manifest = _input_manifest(store, dates)
    input_bytes = _canonical(manifest)
    spec = _spec(manifest, _digest(input_bytes))
    existing = {
        "schema_version": job.MANIFEST_SCHEMA,
        "status": "FAILED",
        "kind": "vol-panel",
        "producer_id": spec.producer_id,
        "job_id": spec.job_id,
        "cohort_id": spec.cohort_id,
        "runner_version": spec.runner_version,
        "request_digest": spec.request_digest,
        "input_manifest_key": spec.input_manifest_key,
        "input_manifest_digest": spec.input_manifest_digest,
        "error": "absolute Container lifetime exceeded (0.05s)",
        "draft_only": True,
        "screening_only": True,
        "ready": False,
        "mass": False,
        "promotion": False,
        "live_orders": False,
        "go": False,
        "not_a_pass": True,
    }
    body = service._canonical_bytes(existing)
    puts = 0
    gets = 0

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del data, extra_headers, content_digest
        nonlocal puts
        puts += 1
        if key == spec.manifest_key:
            raise RuntimeError("R2 upload returned 409")

    def reader(item):
        nonlocal gets
        gets += 1
        assert item.headers()["x-vol-panel-job-id"] == spec.job_id
        return existing

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        terminal_uploader=uploader,
        terminal_reader=reader,
        retry_schedule=(0.01,),
    )
    manager.submit(spec)
    deadline = time.monotonic() + 1
    while manager.status(spec.job_id)["status"] != "FAILED" and time.monotonic() < deadline:
        time.sleep(0.005)
    assert manager.status(spec.job_id)["status"] == "FAILED"
    assert puts >= 1
    assert gets >= 1
    assert body


def test_unlinks_each_snapshot_before_the_next_hydrate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "EVAL_UNIVERSE_POOL", ("13010", "72030"))
    monkeypatch.setattr(job, "UNIVERSE_MIN_BAR_DAYS", 2)
    dates = [f"2019-01-{index:02d}" for index in range(4, 16)] + [
        f"2021-01-{index:02d}" for index in range(4, 16)
    ]
    store: dict[str, bytes] = {}
    manifest = _input_manifest(store, dates)
    input_bytes = _canonical(manifest)
    spec = _spec(manifest, _digest(input_bytes))
    store[spec.input_manifest_key] = input_bytes
    seen: list[tuple[str, list[str]]] = []
    original = job.with_locked_snapshot

    def wrapped(item, lock, work, *, opener, extract):
        leftovers = sorted(path.name for path in work.iterdir() if path.is_file())
        seen.append((str(lock["period_id"]), leftovers))
        return original(item, lock, work, opener=opener, extract=extract)

    monkeypatch.setattr(job, "with_locked_snapshot", wrapped)

    def opener(_spec, key):
        return _Response(store[key])

    def uploader(_spec, key, data):
        store[key] = data
        return _digest(data)

    terminal = job.execute_vol_am_pm_panel_job(spec, opener=opener, uploader=uploader)
    assert terminal["status"] == "COMPLETED"
    assert seen[0][0] == "y2019_selection"
    for _period_id, leftovers in seen[1:]:
        assert leftovers == []


def test_zero_row_member_stays_in_exact_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "EVAL_UNIVERSE_POOL", ("13010", "72030"))
    monkeypatch.setattr(job, "UNIVERSE_MIN_BAR_DAYS", 2)
    dates = [f"2019-01-{index:02d}" for index in range(4, 16)] + [
        f"2021-01-{index:02d}" for index in range(4, 16)
    ]
    store: dict[str, bytes] = {}
    manifest = _input_manifest(store, dates)
    for period in job.EVALUATION_PERIODS:
        raw = _sqlite_bytes(codes=["13010"], dates=dates)
        compressed = _gzip(raw)
        lock = _snapshot_lock(
            f"snap-{period['period_id']}",
            period["period_id"],
            period["period_start"],
            period["period_end"],
            compressed,
            raw,
        )
        manifest["periods"][period["period_id"]] = lock
        store[lock["snapshot"]["key"]] = compressed
    input_bytes = _canonical(manifest)
    spec = _spec(manifest, _digest(input_bytes))
    store[spec.input_manifest_key] = input_bytes

    def opener(_spec, key):
        return _Response(store[key])

    def uploader(_spec, key, data):
        store[key] = data
        return _digest(data)

    terminal = job.execute_vol_am_pm_panel_job(spec, opener=opener, uploader=uploader)
    assert terminal["status"] == "COMPLETED"
    assert terminal["membership"]["codes"] == ["13010", "72030"]
    period = job.EVALUATION_PERIODS[0]["period_id"]
    panel = json.loads(store[terminal["periods"][period]["panel_key"]])
    assert panel["codes"] == ["13010", "72030"]
    assert panel["bars"]["13010"]
    assert panel["bars"]["72030"] == []
    rows = job._common_valid_rows(
        panel["session_calendar"]["dates"],
        panel["codes"],
        panel["bars"],
        panel["opt225_regime"],
    )
    a_only = job._common_valid_rows(
        panel["session_calendar"]["dates"],
        ["13010"],
        {"13010": panel["bars"]["13010"]},
        panel["opt225_regime"],
    )
    assert _digest(_canonical({"rows": rows, "schema_version": job.COMMON_VALID_SCHEMA})) == terminal[
        "periods"
    ][period]["common_valid_sha256"]
    assert _digest(_canonical({"rows": rows, "schema_version": job.COMMON_VALID_SCHEMA})) != _digest(
        _canonical({"rows": a_only, "schema_version": job.COMMON_VALID_SCHEMA})
    )
    assert all(not row["common_valid"] for row in rows)


def test_definitive_terminal_conflict_shuts_the_container_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = [f"2019-01-{index:02d}" for index in range(4, 8)]
    store: dict[str, bytes] = {}
    manifest = _input_manifest(store, dates)
    input_bytes = _canonical(manifest)
    spec = _spec(manifest, _digest(input_bytes))
    shutdown: list[bool] = []

    def uploader(key, data, *, spec, content_digest, extra_headers=None):
        del key, data, spec, content_digest, extra_headers
        raise RuntimeError("R2 upload returned 409")

    def reader(_item):
        raise service.TerminalReadDenied("immutable terminal conflict")

    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        terminal_uploader=uploader,
        terminal_reader=reader,
        retry_schedule=(30.0, 60.0, 120.0),
        on_terminal=lambda: shutdown.append(True),
        max_job_seconds=180 * 60,
    )
    manager.submit(spec)
    deadline = time.monotonic() + 1
    while not shutdown and time.monotonic() < deadline:
        time.sleep(0.005)
    assert shutdown == [True]
    assert manager._retry_timer is None
