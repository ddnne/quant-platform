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
    dates = _dates(128)
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
