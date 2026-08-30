from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
import urllib.error
import urllib.parse
from datetime import date, timedelta
from email.message import Message
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
from test_personal_base_sleeve_am_pm import DATES as AM_DATES
from test_personal_base_sleeve_am_pm import _build as _build_am_sleeve
from test_personal_base_sleeve_am_pm import _quality as _am_quality

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
        },
        terminal_uploader=lambda *args, **kwargs: None,
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


def test_am_pm_job_spec_uses_distinct_prefix_and_rejects_legacy_identity() -> None:
    job_id = "overlay-am-pm"
    prefix = f"research/personal/index-vol-overlay-2023-am-pm/job={job_id}"
    body = {
        "base_job_id": "base-am-pm",
        "cohort_id": overlay.AM_PM_COHORT_ID,
        "input_manifest_digest": "sha256:" + "b" * 64,
        "input_manifest_key": f"{prefix}/input-manifest.json",
        "job_id": job_id,
        "manifest_key": f"{prefix}/manifest.json",
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": overlay.AM_PM_RUNNER_VERSION,
        "svi_job_id": "svi-am-pm",
    }
    provisional = overlay.PersonalIndexVolOverlay2023JobSpec(**body)
    body["request_digest"] = provisional.derived_request_digest()
    spec = overlay.PersonalIndexVolOverlay2023JobSpec.from_document(body)
    assert spec.is_am_pm_overlay is True
    assert spec.is_smile_transport is False
    assert spec.r2_prefix == "research/personal/index-vol-overlay-2023-am-pm"
    with pytest.raises(overlay.OverlayJobInputError, match="identity"):
        overlay.PersonalIndexVolOverlay2023JobSpec.from_document(
            {**body, "runner_version": overlay.RUNNER_VERSION}
        )
    smile_body = {
        **body,
        "cohort_id": overlay.AM_PM_SMILE_TRANSPORT_COHORT_ID,
        "runner_version": overlay.AM_PM_SMILE_TRANSPORT_RUNNER_VERSION,
        "input_manifest_key": (
            f"research/personal/index-smile-transport-2023-am-pm/job={job_id}/"
            "input-manifest.json"
        ),
        "manifest_key": (
            f"research/personal/index-smile-transport-2023-am-pm/job={job_id}/"
            "manifest.json"
        ),
    }
    smile_body["request_digest"] = overlay.PersonalIndexVolOverlay2023JobSpec(
        **smile_body
    ).derived_request_digest()
    smile = overlay.PersonalIndexVolOverlay2023JobSpec.from_document(smile_body)
    assert smile.is_am_pm_smile_transport is True
    assert smile.r2_prefix == "research/personal/index-smile-transport-2023-am-pm"


def test_am_pm_base_sleeve_rejects_next_close_artifact() -> None:
    next_close = _base_sleeve_document(_job("a" * 64))
    with pytest.raises(RuntimeError, match="old next-close"):
        overlay.validate_am_pm_base_sleeve_artifact(next_close)
    fixture = {
        "schema_version": "personal-base-sleeve-source-am-pm/v1",
        "strategy": {
            "strategy_id": "personal_sector_balanced_four_factor_v1_ls_am_pm",
            "strategy_spec_digest": "sha256:" + "c" * 64,
        },
        "cohort": {
            "cohort_id": "sector-relative-ls-am-pm-v1",
            "cohort_digest": "sha256:" + "d" * 64,
        },
        "source_run": {"execution_mode": "am_pm"},
        "daily_path": [
            {"date": "2023-01-04", "am_nav": 100.0, "pm_nav": 100.1},
            {"date": "2023-01-05", "am_nav": 101.0, "pm_nav": 101.2},
        ],
    }
    with pytest.raises(RuntimeError):
        overlay.validate_am_pm_base_sleeve_artifact(fixture)
    document = _build_am_sleeve()
    overlay.validate_am_pm_base_sleeve_artifact(document)
    with pytest.raises(RuntimeError, match="old next-close"):
        overlay.validate_am_pm_base_sleeve_artifact(next_close)


def test_am_pm_observations_keep_native_option_dates_and_etf_ma() -> None:
    dates = list(AM_DATES)
    base = _build_am_sleeve()
    etf = {day: (1000.0 + index, 1001.0 + index) for index, day in enumerate(dates)}
    closes = {day: 2000.0 + index for index, day in enumerate(dates)}
    features = {day: {"date": day, **_feature()} for day in dates}
    features[dates[2]] = {**features[dates[2]], "observed_atm_iv_decimal": 0.40}
    rows = overlay.build_am_pm_observations(
        session_dates=dates,
        base_artifact=base,
        etf_ma=etf,
        topix_closes=closes,
        base_vol_percent={day: 20.0 for day in dates},
        feature_rows=features,
    )
    assert not hasattr(rows[2].signal, "n225_atm_iv")
    assert rows[1].lagged_features is not None
    assert rows[2].lagged_features is not None
    assert rows[2].lagged_features.n225_atm_iv == pytest.approx(0.40)
    assert rows[1].lagged_features.n225_atm_iv == pytest.approx(0.25)
    assert rows[2].lagged_features.source_session_date == dates[2]
    assert rows[2].lagged_features.feature_available_at == (
        f"{dates[2]}T15:00:00+09:00"
    )
    assert rows[2].lagged_features.prior_source_session_date == dates[1]
    assert rows[2].lagged_features.prior_feature_available_at == (
        f"{dates[1]}T15:00:00+09:00"
    )
    assert rows[2].signal.topix_etf_13060_madjc == pytest.approx(1002.0)
    assert rows[2].signal.signal_available_at == f"{dates[2]}T12:30:00+09:00"
    assert rows[2].fill_outcome.fill_available_at == f"{dates[2]}T15:00:00+09:00"
    assert rows[2].signal.base_sleeve_am_nav == pytest.approx(1_012_000.0)
    assert rows[2].fill_outcome.base_sleeve_pm_nav == pytest.approx(1_020_000.0)
    missing_a = dict(etf)
    missing_a[dates[2]] = (1002.0, None)
    optional_a = overlay.build_am_pm_observations(
        session_dates=dates,
        base_artifact=base,
        etf_ma=missing_a,
        topix_closes=closes,
        base_vol_percent={day: 20.0 for day in dates},
        feature_rows=features,
    )
    assert optional_a[2].signal.topix_etf_13060_madjc == pytest.approx(1002.0)
    assert optional_a[2].fill_outcome.topix_etf_13060_aadjc is None
    remapped = overlay.remap_smile_transport_features_for_am_pm(
        [
            {
                "candidate_id": "n225_sticky_strike_downside_smile_term_surprise_v1",
                "date": dates[1],
            }
        ]
    )
    assert remapped[0]["candidate_id"] == (
        "n225_sticky_strike_downside_smile_term_surprise_am_pm_v1"
    )
    assert remapped[0]["source_candidate_id"] == (
        "n225_sticky_strike_downside_smile_term_surprise_v1"
    )


def test_am_pm_consumer_rejects_non_comparable_and_fixture_artifacts() -> None:
    document = _build_am_sleeve()
    overlay.validate_am_pm_base_sleeve_artifact(document)
    non_comparable = _build_am_sleeve(
        [
            {"date": AM_DATES[0], "equity": 1_000_000.0, "signal_equity": 1_000_000.0},
            {"date": AM_DATES[1], "equity": 1_050_000.0, "signal_equity": None},
            {"date": AM_DATES[2], "equity": 1_080_000.0, "signal_equity": 1_060_000.0},
        ],
        quality=_am_quality(skipped=(AM_DATES[1],)),
    )
    with pytest.raises(RuntimeError, match="comparable"):
        overlay.validate_am_pm_base_sleeve_artifact(non_comparable)
    fixture = {
        "schema_version": "personal-base-sleeve-source-am-pm/v1",
        "strategy": {
            "strategy_id": "personal_sector_balanced_four_factor_v1_ls_am_pm",
            "strategy_spec_digest": "sha256:" + "c" * 64,
        },
        "cohort": {
            "cohort_id": "sector-relative-ls-am-pm-v1",
            "cohort_digest": "sha256:" + "d" * 64,
        },
        "source_run": {"execution_mode": "am_signal_pm_close"},
        "daily_path": [{"date": AM_DATES[0], "am_nav": 100.0, "pm_nav": 100.1}],
    }
    with pytest.raises(RuntimeError):
        overlay.validate_am_pm_base_sleeve_artifact(fixture)


def _am_family_spec(*, job_id: str, smile: bool = False):
    prefix = (
        overlay.AM_PM_SMILE_TRANSPORT_R2_PREFIX
        if smile
        else overlay.AM_PM_R2_PREFIX
    )
    body = {
        "base_job_id": "base-am",
        "cohort_id": (
            overlay.AM_PM_SMILE_TRANSPORT_COHORT_ID
            if smile
            else overlay.AM_PM_COHORT_ID
        ),
        "input_manifest_digest": "sha256:" + "b" * 64,
        "input_manifest_key": f"{prefix}/job={job_id}/input-manifest.json",
        "job_id": job_id,
        "manifest_key": f"{prefix}/job={job_id}/manifest.json",
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": (
            overlay.AM_PM_SMILE_TRANSPORT_RUNNER_VERSION
            if smile
            else overlay.AM_PM_RUNNER_VERSION
        ),
        "svi_job_id": "svi-am",
    }
    body["request_digest"] = overlay.PersonalIndexVolOverlay2023JobSpec(
        **body
    ).derived_request_digest()
    return overlay.PersonalIndexVolOverlay2023JobSpec.from_document(body)


def test_timeout_terminal_uses_am_overlay_and_smile_schemas() -> None:
    manager = service.JobManager(
        lambda spec: {},
        terminal_uploader=lambda *args, **kwargs: None,
        max_job_seconds=30,
    )
    overlay_spec = _am_family_spec(job_id="am-overlay-timeout")
    smile_spec = _am_family_spec(job_id="am-smile-timeout", smile=True)
    overlay_terminal = manager._timeout_terminal(overlay_spec)
    smile_terminal = manager._timeout_terminal(smile_spec)
    assert overlay_terminal["schema_version"] == overlay.AM_PM_MANIFEST_SCHEMA
    assert overlay_terminal["runner_version"] == overlay.AM_PM_RUNNER_VERSION
    assert smile_terminal["schema_version"] == overlay.AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA
    assert smile_terminal["runner_version"] == overlay.AM_PM_SMILE_TRANSPORT_RUNNER_VERSION
    assert overlay_terminal["schema_version"] != overlay.MANIFEST_SCHEMA
    assert smile_terminal["schema_version"] != overlay.SMILE_TRANSPORT_MANIFEST_SCHEMA


class _UrlResponse(io.BytesIO):
    def __init__(self, status: int, body: bytes):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _ProductionOverlayR2:
    def __init__(self, spec) -> None:
        self.spec = spec
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
            if raw is None:
                raise urllib.error.HTTPError(
                    url, 404, "not found", Message(), io.BytesIO(b"")
                )
            parsed = json.loads(raw)
            required = {
                "x-personal-job-id",
                "x-personal-request-digest",
                "x-personal-runner-version",
                "x-personal-job-kind",
                "x-personal-cohort-id",
            }
            personal = {name for name in headers if name.startswith("x-personal-")}
            expected_schema = (
                overlay.AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA
                if self.spec.is_am_pm_smile_transport
                else overlay.AM_PM_MANIFEST_SCHEMA
            )
            if (
                personal != required
                or headers.get("x-personal-job-id") != parsed.get("job_id")
                or headers.get("x-personal-request-digest")
                != parsed.get("request_digest")
                or headers.get("x-personal-runner-version")
                != parsed.get("runner_version")
                or headers.get("x-personal-job-kind") != "overlay"
                or headers.get("x-personal-cohort-id") != parsed.get("cohort_id")
                or parsed.get("schema_version") != expected_schema
                or key != self.spec.manifest_key
            ):
                raise urllib.error.HTTPError(
                    url, 403, "denied", Message(), io.BytesIO(b"")
                )
            return _UrlResponse(200, raw)
        raise AssertionError(method)


@pytest.mark.parametrize("smile", (False, True))
def test_am_family_conflict_get_verifies_identity_and_shuts_down(
    monkeypatch, smile: bool
) -> None:
    spec = _am_family_spec(
        job_id="am-smile-term" if smile else "am-overlay-term",
        smile=smile,
    )
    fake = _ProductionOverlayR2(spec)
    existing = service.JobManager(
        lambda item: {},
        terminal_uploader=lambda *args, **kwargs: None,
        max_job_seconds=30,
    )._timeout_terminal(spec)
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


@pytest.mark.parametrize("smile", (False, True))
def test_am_family_wrong_schema_or_digest_shuts_down_fail_closed(
    monkeypatch, smile: bool
) -> None:
    spec = _am_family_spec(
        job_id="am-smile-deny" if smile else "am-overlay-deny",
        smile=smile,
    )
    fake = _ProductionOverlayR2(spec)
    existing = service.JobManager(
        lambda item: {},
        terminal_uploader=lambda *args, **kwargs: None,
        max_job_seconds=30,
    )._timeout_terminal(spec)
    existing["schema_version"] = overlay.MANIFEST_SCHEMA
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


@pytest.mark.parametrize("smile", (False, True))
def test_am_family_failed_upload_then_terminal_get_404_retries(
    monkeypatch, smile: bool
) -> None:
    spec = _am_family_spec(
        job_id="am-smile-missing" if smile else "am-overlay-missing",
        smile=smile,
    )
    fake = _ProductionOverlayR2(spec)

    def urlopen(request, timeout=None):
        del timeout
        url = request.full_url
        method = request.get_method()
        if method == "PUT":
            fake.puts += 1
            raise urllib.error.HTTPError(
                url, 503, "unavailable", Message(), io.BytesIO(b"")
            )
        return fake.urlopen(request)

    monkeypatch.setattr(service.urllib.request, "urlopen", urlopen)
    terminal = threading.Event()
    manager = service.JobManager(
        lambda item: (_ for _ in ()).throw(RuntimeError("runner failed")),
        on_terminal=terminal.set,
        retry_schedule=(0.05, 0.05),
        max_job_seconds=30,
    )
    manager.submit(spec)
    assert not terminal.wait(0.2)
    assert fake.puts >= 2
    assert fake.gets >= 1
    assert manager._shutdown_notified is False
    assert manager.status(spec.job_id)["status"] == "FAILED"
