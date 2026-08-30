from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from research.personal_index_vol_overlay import (
    build_prepared_panel_manifest,
    evaluate_index_vol_overlays,
)

from test_cloud_personal_research_container import (
    _base_sleeve_document,
    _job,
    service,
)

import personal_index_vol_overlay_2023_job as overlay


def _dates(count: int) -> list[str]:
    start = date(2023, 1, 4)
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _feature() -> dict[str, float]:
    return {
        "observed_atm_iv_decimal": 0.25,
        "observed_atm_short_over_next_minus_one": 0.25,
        "observed_left_iv_decimal": 0.30,
        "observed_rr_over_atm": -0.20,
        "observed_bf_over_atm": 0.10,
        "observed_rr_over_atm_short_minus_next": -0.10,
        "observed_bf_over_atm_short_minus_next": 0.0,
        "svi_atm_short_over_next_minus_one": 0.10,
        "svi_rr_over_atm": -0.20,
        "svi_bf_over_atm": 0.10,
        "svi_rr_over_atm_short_minus_next": -0.10,
        "svi_bf_over_atm_short_minus_next": 0.0,
    }


def _sources(dates: list[str], *, missing_feature: str | None = None):
    topix = 2_000.0
    closes: dict[str, float] = {}
    base_rows: list[dict[str, Any]] = []
    features: dict[str, dict[str, Any]] = {}
    for index, day in enumerate(dates):
        topix_return = ((index % 7) - 3) * 0.001
        topix *= 1.0 + topix_return
        closes[day] = topix
        base_rows.append(
            {"date": day, "base_sleeve_return": 0.0005 + 0.8 * topix_return}
        )
        if day != missing_feature:
            features[day] = {"date": day, **_feature()}
    return (
        {"daily_path": base_rows},
        closes,
        {day: 20.0 for day in dates},
        features,
    )


def test_adapter_converts_percent_basevol_but_preserves_decimal_iv_and_rv() -> None:
    dates = _dates(25)
    base, closes, base_vol, features = _sources(dates)
    observations = overlay.build_observations(
        session_dates=dates,
        base_artifact=base,
        topix_closes=closes,
        base_vol_percent=base_vol,
        feature_rows=features,
    )
    row = observations[20]
    assert row.n225_base_vol == pytest.approx(0.20)
    assert row.n225_atm_iv == pytest.approx(0.25)
    assert row.n225_front_atm_iv == pytest.approx(0.25)
    assert row.n225_next_atm_iv == pytest.approx(0.20)
    assert row.n225_front_downside_wing_iv == pytest.approx(0.30)
    assert row.n225_next_downside_wing_iv == pytest.approx(0.23)
    assert row.topix_realized_vol_20 is not None
    assert 0.0 < row.topix_realized_vol_20 < 1.0
    assert row.available_at == f"{dates[20]}T23:59:59+09:00"


def test_pit_calendar_is_independent_and_one_removed_row_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = _dates(148)
    calls: list[dict[str, Any]] = []

    def calendar(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            rows=[{"date": day, "holiday_division": "1"} for day in dates]
        )

    monkeypatch.setattr(overlay.pit, "get_market_calendar", calendar)
    authoritative = overlay._calendar_dates(Path("immutable.sqlite"))
    assert authoritative == dates
    assert calls == [
        {
            "as_of": "2023-10-13T23:59:59+09:00",
            "from_date": "2023-01-04",
            "to_date": "2023-10-13",
            "db_path": Path("immutable.sqlite"),
        }
    ]
    assert overlay.require_exact_calendar(dates, dates, dates) == dates
    with pytest.raises(RuntimeError, match="exactly match"):
        overlay.require_exact_calendar(dates, dates[:64] + dates[65:], dates)
    with pytest.raises(RuntimeError, match="exactly match"):
        overlay.require_exact_calendar(dates[:-1], dates[:-1], dates[:-1])


def test_complete_193_session_window_evaluates_all_four_candidates() -> None:
    dates = _dates(193)
    base, closes, base_vol, features = _sources(dates)
    observations = overlay.build_observations(
        session_dates=dates,
        base_artifact=base,
        topix_closes=closes,
        base_vol_percent=base_vol,
        feature_rows=features,
    )
    manifest = build_prepared_panel_manifest(
        observations,
        authoritative_session_dates=dates,
        snapshot_digest="sha256:" + "1" * 64,
        base_report_digest="sha256:" + "2" * 64,
    )
    report = evaluate_index_vol_overlays(
        observations,
        manifest=manifest,
        authoritative_session_dates=dates,
        signal_start=dates[145],
        signal_end=dates[-3],
    )
    assert report["status"] == "EVALUATED"
    assert report["candidate_policy"]["evaluated_count"] == 4
    assert [row["status"] for row in report["candidates"]] == [
        "EVALUATED",
        "EVALUATED",
        "EVALUATED",
        "EVALUATED",
    ]


def test_base_daily_path_missing_rv_warmup_date_is_rejected() -> None:
    dates = _dates(193)
    base, closes, base_vol, features = _sources(dates)
    base["daily_path"].insert(
        0, {"date": "2022-12-30", "base_sleeve_return": 0.0}
    )
    base["daily_path"].append(
        {"date": "2023-10-14", "base_sleeve_return": 0.0}
    )
    assert len(
        overlay.build_observations(
            session_dates=dates,
            base_artifact=base,
            topix_closes=closes,
            base_vol_percent=base_vol,
            feature_rows=features,
        )
    ) == 193
    del base["daily_path"][21]
    with pytest.raises(RuntimeError, match="exactly match authoritative dates"):
        overlay.build_observations(
            session_dates=dates,
            base_artifact=base,
            topix_closes=closes,
            base_vol_percent=base_vol,
            feature_rows=features,
        )


def test_missing_svi_feature_row_becomes_not_evaluated_without_forward_fill() -> None:
    dates = _dates(140)
    missing_day = dates[130]
    base, closes, base_vol, features = _sources(
        dates, missing_feature=missing_day
    )
    observations = overlay.build_observations(
        session_dates=dates,
        base_artifact=base,
        topix_closes=closes,
        base_vol_percent=base_vol,
        feature_rows=features,
    )
    manifest = build_prepared_panel_manifest(
        observations,
        authoritative_session_dates=dates,
        snapshot_digest="sha256:" + "1" * 64,
        base_report_digest="sha256:" + "2" * 64,
    )
    report = evaluate_index_vol_overlays(
        observations,
        manifest=manifest,
        authoritative_session_dates=dates,
        signal_start=missing_day,
        signal_end=missing_day,
    )
    candidates = {row["candidate_id"]: row for row in report["candidates"]}
    for candidate_id in (
        "n225_atmiv_over_topix_rv20_normalized_126_v1",
        "n225_observed_front_over_next_atm_v1",
        "n225_observed_downside_smile_front_over_next_v1",
    ):
        assert candidates[candidate_id]["status"] == "NOT_EVALUATED"
        assert candidates[candidate_id]["performance"] is None
        assert candidates[candidate_id]["daily_path"] == []
    assert candidates["n225_basevol_10_over_60_defensive_v1"]["status"] == (
        "EVALUATED"
    )


def test_archive_reader_rejects_inconsistent_continuous_nav(tmp_path: Path) -> None:
    document = _base_sleeve_document(_job("a" * 64))
    document["daily_path"][1]["equity"] *= 2
    raw = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    member = f"base-sleeve/{digest[7:]}.json"
    archive_path = tmp_path / "base.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    with pytest.raises(ValueError, match="NAV and return are inconsistent"):
        overlay.load_base_sleeve_from_archive(
            archive_path,
            {"archive_member": member, "sha256": digest},
        )


def test_container_job_spec_is_closed_and_uses_existing_job_manager() -> None:
    job_id = "overlay-manager"
    prefix = f"research/personal/index-vol-overlay-2023/job={job_id}"
    body = {
        "base_job_id": "base-manager",
        "cohort_id": overlay.COHORT_ID,
        "input_manifest_digest": "sha256:" + "b" * 64,
        "input_manifest_key": f"{prefix}/input-manifest.json",
        "job_id": job_id,
        "manifest_key": f"{prefix}/manifest.json",
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": overlay.RUNNER_VERSION,
        "svi_job_id": "svi-manager",
    }
    provisional = overlay.PersonalIndexVolOverlay2023JobSpec(**body)
    body["request_digest"] = provisional.derived_request_digest()
    spec = overlay.PersonalIndexVolOverlay2023JobSpec.from_document(body)
    assert spec.job_id == job_id
    with pytest.raises(overlay.OverlayJobInputError, match="fields are closed"):
        overlay.PersonalIndexVolOverlay2023JobSpec.from_document(
            {**body, "ready": True}
        )
    manager = service.JobManager(
        lambda accepted: {
            "job_id": accepted.job_id,
            "cohort_id": accepted.cohort_id,
            "cohort_digest": accepted.cohort_digest,
            "request_digest": accepted.request_digest,
            "status": "COMPLETED",
            "go": False,
        }
    )
    assert manager.submit(spec)["status"] == "QUEUED"


def test_smile_transport_job_spec_is_separately_versioned() -> None:
    job_id = "smile-manager"
    prefix = f"research/personal/index-smile-transport-2023/job={job_id}"
    body = {
        "base_job_id": "base-manager",
        "cohort_id": overlay.SMILE_TRANSPORT_COHORT_ID,
        "input_manifest_digest": "sha256:" + "b" * 64,
        "input_manifest_key": f"{prefix}/input-manifest.json",
        "job_id": job_id,
        "manifest_key": f"{prefix}/manifest.json",
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": overlay.SMILE_TRANSPORT_RUNNER_VERSION,
        "svi_job_id": "svi-manager",
    }
    provisional = overlay.PersonalIndexVolOverlay2023JobSpec(**body)
    body["request_digest"] = provisional.derived_request_digest()
    spec = overlay.PersonalIndexVolOverlay2023JobSpec.from_document(body)
    assert spec.is_smile_transport is True
    assert spec.r2_prefix == "research/personal/index-smile-transport-2023"
    with pytest.raises(overlay.OverlayJobInputError, match="identity"):
        overlay.PersonalIndexVolOverlay2023JobSpec.from_document(
            {**body, "runner_version": overlay.RUNNER_VERSION}
        )
    overlay_prefix = f"research/personal/index-vol-overlay-2023/job={job_id}"
    with pytest.raises(overlay.OverlayJobInputError, match="input manifest key"):
        overlay.PersonalIndexVolOverlay2023JobSpec.from_document(
            {
                **body,
                "input_manifest_key": f"{overlay_prefix}/input-manifest.json",
                "manifest_key": f"{overlay_prefix}/manifest.json",
            }
        )


def test_each_official_raw_day_is_parsed_once_not_once_per_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def load_one(_spec, entry, *, opener):
        calls.append(str(entry["date"]))
        return [{"date": entry["date"], "surface_scope": "nikkei_225_index_options_only"}], {
            "source_rows": 1
        }

    slices_by_day: list[str] = []

    def build_slices(rows, *, dataset_id):
        day = str(rows[0]["date"])
        slices_by_day.append(day)
        return [
            {
                "date": day,
                "expiry": "2023-03-10",
                "cm": "2023-03",
                "dte_days": 30,
                "maturity_years": 30 / 365.0,
                "under_px": 40_000.0,
                "fit_success": True,
                "fit_reason": "ok",
                "svi_parameters": {
                    "a": 0.01,
                    "b": 0.04,
                    "rho": -0.2,
                    "m": 0.0,
                    "sigma": 0.12,
                },
                "fit_log_moneyness_min": -0.2,
                "fit_log_moneyness_max": 0.2,
                "surface_scope": "nikkei_225_index_options_only",
                "source_dataset_id": "derivatives_bars_daily_options_225",
            }
        ]

    monkeypatch.setattr(overlay, "load_one_options_day", load_one)
    monkeypatch.setattr(overlay, "build_options_225_smile_slices", build_slices)
    spec = overlay.PersonalIndexVolOverlay2023JobSpec(
        base_job_id="base",
        cohort_id=overlay.SMILE_TRANSPORT_COHORT_ID,
        input_manifest_digest="sha256:" + "a" * 64,
        input_manifest_key="research/personal/index-smile-transport-2023/job=x/input-manifest.json",
        job_id="x",
        manifest_key="research/personal/index-smile-transport-2023/job=x/manifest.json",
        request_digest="sha256:" + "b" * 64,
        runner_version=overlay.SMILE_TRANSPORT_RUNNER_VERSION,
        svi_job_id="svi",
    )
    days = [
        {"date": "2023-01-04", "objects": [{"key": "a"}]},
        {"date": "2023-01-05", "objects": [{"key": "b"}]},
        {"date": "2023-01-06", "objects": [{"key": "c"}]},
    ]
    slices, audit = overlay._parse_official_options_days_once(
        spec,
        spec,  # type: ignore[arg-type]
        {"days": days},
        opener=lambda _spec, _key: None,
    )
    assert calls == ["2023-01-04", "2023-01-05", "2023-01-06"]
    assert slices_by_day == calls
    assert len(slices) == 3
    assert [row["fitted_slices_retained"] for row in audit] == [1, 1, 1]


def test_bounded_fitted_slice_rejects_single_stock_and_drops_failed_fits() -> None:
    failed = {
        "fit_success": False,
        "surface_scope": "nikkei_225_index_options_only",
        "source_dataset_id": "derivatives_bars_daily_options_225",
    }
    assert overlay.bounded_fitted_svi_slice(failed) is None
    with pytest.raises(RuntimeError, match="single-stock"):
        overlay.bounded_fitted_svi_slice(
            {
                "fit_success": True,
                "surface_scope": "single_stock_options",
                "source_dataset_id": "derivatives_bars_daily_options_225",
                "svi_parameters": {"a": 0.01},
            }
        )
