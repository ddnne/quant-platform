"""Focused invariants for the fixed 2023 smile-transport overlay cohort."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import pytest

from research.options_225_smile_features import OPTIONS_225_SMILE_SURFACE_SCOPE
from research.options_225_smile_transport import STICKY_MONEYNESS, STICKY_STRIKE
from research.options_225_vol_series import DATASET_ID
from research.personal_index_vol_overlay import (
    BETA_MIN_RETURNS,
    COMMON_VALID_MIN_CALENDAR_MONTHS,
    COMMON_VALID_MIN_SIGNAL_DAYS,
    IndexVolOverlayObservation,
    OVERLAY_CANDIDATES,
    SMILE_TRANSPORT_CANDIDATE_IDS,
    SMILE_TRANSPORT_CANDIDATES,
    build_prepared_panel_manifest,
    downside_smile_term_gross_scale,
    evaluate_index_smile_transport_overlays,
    evaluate_index_vol_overlays,
    potential_minimum_gross_scale,
    smile_transport_core_digest,
)


def _dates(count: int, *, start: date = date(2023, 1, 4)) -> list[str]:
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _observations(dates: Sequence[str], *, beta: float = 1.25) -> list[IndexVolOverlayObservation]:
    proxy_returns = [0.0] + [
        (0.001 + (index % 5) * 0.0001) * (1.0 if index % 2 else -1.0)
        for index in range(1, len(dates))
    ]
    closes = [100.0]
    for proxy_return in proxy_returns[1:]:
        closes.append(closes[-1] * (1.0 + proxy_return))
    return [
        IndexVolOverlayObservation(
            date=day,
            available_at=f"{day}T23:59:59+09:00",
            base_sleeve_return=beta * proxy_returns[index],
            topix_cash_close=closes[index],
            n225_base_vol=None,
            n225_atm_iv=None,
            topix_realized_vol_20=None,
            n225_front_atm_iv=None,
            n225_next_atm_iv=None,
            n225_front_downside_wing_iv=None,
            n225_next_downside_wing_iv=None,
        )
        for index, day in enumerate(dates)
    ]


def _row(
    *,
    day: str,
    previous: str,
    candidate_id: str,
    model: str,
    family: str,
    success: bool,
    value: float | None,
    front_expiry: str | None = "2024-03-08",
    next_expiry: str | None = "2024-04-12",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "date": day,
        "previous_observation_date": previous,
        "transport_model": model,
        "signal_family": family,
        "candidate_id": candidate_id,
        "candidate_success": success,
        "candidate_reason": "ok" if success else "synthetic_invalid",
        "candidate_value": value,
        "front_expiry": front_expiry if success else None,
        "next_expiry": next_expiry if success else None,
        "surface_scope": OPTIONS_225_SMILE_SURFACE_SCOPE,
        "source_dataset_id": DATASET_ID,
        "single_stock_iv_used": False,
        "ffill_applied": False,
        "expiry_rank_substitution_applied": False,
        "extrapolation_applied": False,
    }
    if extra:
        payload.update(extra)
    return payload


def _features(
    dates: Sequence[str],
    *,
    successful: set[str] | None = None,
    q_value: float = 0.0,
    mismatch: float = 0.0,
    mutate: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identity = {
        "n225_sticky_strike_downside_smile_term_surprise_v1": (
            STICKY_STRIKE,
            "downside_smile_term_surprise",
            q_value,
        ),
        "n225_sticky_moneyness_downside_smile_term_surprise_v1": (
            STICKY_MONEYNESS,
            "downside_smile_term_surprise",
            q_value,
        ),
        "n225_sticky_strike_potential_minimum_transport_v1": (
            STICKY_STRIKE,
            "potential_minimum_transport",
            mismatch,
        ),
        "n225_sticky_moneyness_potential_minimum_transport_v1": (
            STICKY_MONEYNESS,
            "potential_minimum_transport",
            mismatch,
        ),
    }
    for index, day in enumerate(dates):
        if index == 0:
            continue
        ok = successful is None or day in successful
        for candidate_id, (model, family, value) in identity.items():
            extra = dict((mutate or {}).get((day, candidate_id), {}))
            rows.append(
                _row(
                    day=day,
                    previous=dates[index - 1],
                    candidate_id=candidate_id,
                    model=model,
                    family=family,
                    success=ok,
                    value=value if ok else None,
                    extra=extra,
                )
            )
    return rows


def _evaluate(
    rows: Sequence[IndexVolOverlayObservation],
    features: Sequence[Mapping[str, Any]],
    *,
    signal_start: str,
    signal_end: str | None = None,
) -> dict[str, Any]:
    dates = [row.date for row in rows]
    return evaluate_index_smile_transport_overlays(
        rows,
        features,
        manifest=build_prepared_panel_manifest(
            rows,
            authoritative_session_dates=dates,
            snapshot_digest="sha256:" + "1" * 64,
            base_report_digest="sha256:" + "2" * 64,
        ),
        authoritative_session_dates=dates,
        signal_start=signal_start,
        signal_end=signal_end,
        core_digest=smile_transport_core_digest(),
    )


def _by_id(report: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(
        candidate
        for candidate in report["candidates"]
        if candidate["candidate_id"] == candidate_id
    )


def _month_days(dates: Sequence[str], month: str, count: int) -> list[str]:
    chosen = [day for day in dates if day.startswith(month)]
    return chosen[:count]


def test_exact_four_identity_keeps_sticky_models_as_separate_candidates() -> None:
    assert SMILE_TRANSPORT_CANDIDATE_IDS == (
        "n225_sticky_strike_downside_smile_term_surprise_v1",
        "n225_sticky_moneyness_downside_smile_term_surprise_v1",
        "n225_sticky_strike_potential_minimum_transport_v1",
        "n225_sticky_moneyness_potential_minimum_transport_v1",
    )
    assert len(set(SMILE_TRANSPORT_CANDIDATE_IDS)) == 4
    assert [item.candidate_id for item in OVERLAY_CANDIDATES] != list(
        SMILE_TRANSPORT_CANDIDATE_IDS
    )
    kinds = [item.feature_kind for item in SMILE_TRANSPORT_CANDIDATES]
    assert kinds.count("sticky_strike_downside_smile_term_surprise") == 1
    assert kinds.count("sticky_moneyness_downside_smile_term_surprise") == 1
    assert kinds.count("sticky_strike_potential_minimum_transport") == 1
    assert kinds.count("sticky_moneyness_potential_minimum_transport") == 1


def test_fixed_exposure_formulas_and_clipping() -> None:
    assert downside_smile_term_gross_scale(0.0) == pytest.approx(1.0)
    assert downside_smile_term_gross_scale(1.0) == pytest.approx(0.5)
    assert downside_smile_term_gross_scale(3.0) == pytest.approx(0.5)
    assert downside_smile_term_gross_scale(-0.5) == pytest.approx(1.0)
    assert downside_smile_term_gross_scale(-1.0) is None
    assert potential_minimum_gross_scale(0.0) == pytest.approx(1.0)
    assert potential_minimum_gross_scale(0.10) == pytest.approx(0.5)
    assert potential_minimum_gross_scale(0.30) == pytest.approx(0.5)
    assert potential_minimum_gross_scale(-0.01) is None


def _gated_panel(*, valid_months: Sequence[str], per_month: int) -> tuple[list[IndexVolOverlayObservation], list[dict[str, Any]], list[str], set[str]]:
    dates = _dates(220)
    rows = _observations(dates)
    signal_dates = dates[BETA_MIN_RETURNS : len(dates) - 2]
    chosen: list[str] = []
    for month in valid_months:
        chosen.extend(_month_days(signal_dates, month, per_month))
    features = _features(dates, successful=set(chosen), q_value=1.0, mismatch=0.10)
    return rows, features, dates, set(chosen)


def test_thirty_nine_days_three_months_reject_and_metrics_stay_null() -> None:
    rows, features, dates, chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05"),
        per_month=13,
    )
    assert len(chosen) == 39
    report = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    gate = report["common_validity_gate"]
    assert gate["passed"] is False
    assert gate["common_valid_signal_days"] == 39
    assert gate["common_valid_calendar_months"] == 3
    assert report["status"] == "NOT_EVALUATED"
    for candidate in report["candidates"]:
        assert candidate["status"] == "NOT_EVALUATED"
        assert candidate["performance"] is None
        assert candidate["daily_path"] == []
        assert candidate["reason"] == "common_validity_gate_failed"
    assert report["diagnostic_control"]["performance"] is None
    assert report["candidate_policy"]["selection"] == "NOT_PERFORMED"


def test_forty_days_four_months_accept() -> None:
    rows, features, dates, chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    assert len(chosen) == 40
    report = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    gate = report["common_validity_gate"]
    assert gate["passed"] is True
    assert gate["common_valid_signal_days"] == 40
    assert gate["common_valid_calendar_months"] == 4
    assert report["status"] == "EVALUATED"
    assert report["candidate_policy"]["evaluated_count"] == 4
    assert report["candidate_policy"]["post_result_selection"] == "NOT_PERFORMED"
    ids = [candidate["candidate_id"] for candidate in report["candidates"]]
    assert ids == list(SMILE_TRANSPORT_CANDIDATE_IDS)
    for candidate in report["candidates"]:
        assert candidate["status"] == "EVALUATED"
        assert candidate["performance"] is not None
        assert candidate["performance"]["schema_version"] == "personal-performance/v1"
        path = candidate["daily_path"]
        valid_points = [row for row in path if row["common_valid"]]
        assert len(valid_points) == 40
        assert valid_points[0]["gross_scale"] == pytest.approx(0.5)
        assert valid_points[0]["topix_hedge_weight"] == pytest.approx(
            -0.5 * valid_points[0]["estimated_beta"]
        )


def test_beta_62_reject_and_beta_63_accept() -> None:
    dates = _dates(120)
    rows = _observations(dates)
    successful = set(dates[BETA_MIN_RETURNS : BETA_MIN_RETURNS + 50])
    features = _features(dates, successful=successful)
    report = _evaluate(
        rows,
        features,
        signal_start=dates[62],
        signal_end=dates[80],
    )
    excluded = {row["date"]: row["reasons"] for row in report["common_validity_gate"]["excluded"]}
    assert dates[62] in excluded
    assert any("beta_min_63_pairs" in reason for reason in excluded[dates[62]])
    assert dates[63] in report["common_validity_gate"]["common_valid_dates"]
    assert COMMON_VALID_MIN_SIGNAL_DAYS == 40
    assert COMMON_VALID_MIN_CALENDAR_MONTHS == 4


def test_future_mutation_cannot_change_prior_signals_or_beta() -> None:
    rows, features, dates, chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    signal = sorted(chosen)[5]
    original = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    signal_index = dates.index(signal)
    mutated_rows = list(rows)
    mutated_rows[signal_index + 1] = replace(
        mutated_rows[signal_index + 1],
        topix_cash_close=mutated_rows[signal_index + 1].topix_cash_close * 1.25,
    )
    mutated_rows[signal_index + 2] = replace(
        mutated_rows[signal_index + 2],
        topix_cash_close=mutated_rows[signal_index + 2].topix_cash_close / 1.25,
        base_sleeve_return=-0.02,
    )
    mutated_features = _features(
        dates,
        successful=chosen,
        q_value=1.0,
        mismatch=0.10,
        mutate={
            (dates[signal_index + 1], SMILE_TRANSPORT_CANDIDATE_IDS[0]): {
                "candidate_value": 99.0
            }
        },
    )
    changed = _evaluate(
        mutated_rows,
        mutated_features,
        signal_start=dates[BETA_MIN_RETURNS],
    )
    for candidate_id in SMILE_TRANSPORT_CANDIDATE_IDS:
        before = next(
            row
            for row in _by_id(original, candidate_id)["daily_path"]
            if row["signal_date"] == signal
        )
        after = next(
            row
            for row in _by_id(changed, candidate_id)["daily_path"]
            if row["signal_date"] == signal
        )
        for field in (
            "feature_ratio_x",
            "gross_scale",
            "estimated_beta",
            "beta_observations",
            "beta_window_last_return_date",
            "topix_hedge_weight",
        ):
            if isinstance(before[field], float):
                assert after[field] == pytest.approx(before[field])
            else:
                assert after[field] == before[field]
        assert after["net_return"] != pytest.approx(before["net_return"])


def test_d_to_d_plus_1_fill_to_d_plus_2_first_pnl_wall() -> None:
    rows, features, dates, chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    report = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    first_valid = report["common_validity_gate"]["common_valid_dates"][0]
    index = dates.index(first_valid)
    path = next(
        row
        for row in _by_id(report, SMILE_TRANSPORT_CANDIDATE_IDS[0])["daily_path"]
        if row["signal_date"] == first_valid
    )
    assert path["signal_date"] == dates[index]
    assert path["rebalance_date"] == dates[index + 1]
    assert path["pnl_date"] == dates[index + 2]
    assert path["date"] == dates[index + 2]
    assert path["beta_window_last_return_date"] == dates[index]


def test_one_common_invalid_date_flattens_all_four_and_closes_prior() -> None:
    rows, features, dates, chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    ordered = sorted(chosen)
    hole = ordered[8]
    chosen.remove(hole)
    # Keep 40 valid days after punching the hole.
    extra = [
        day
        for day in dates[BETA_MIN_RETURNS : len(dates) - 2]
        if day.startswith("2023-07") and day not in chosen
    ][0]
    chosen.add(extra)
    features = _features(dates, successful=chosen, q_value=1.0, mismatch=0.10)
    report = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    assert report["common_validity_gate"]["passed"] is True
    assert hole in {
        row["date"] for row in report["common_validity_gate"]["excluded"]
    }
    hole_index = dates.index(hole)
    prior = dates[hole_index - 1]
    for candidate_id in SMILE_TRANSPORT_CANDIDATE_IDS:
        path = {
            row["signal_date"]: row
            for row in _by_id(report, candidate_id)["daily_path"]
        }
        assert path[prior]["flatten_applied"] is False
        assert path[prior]["gross_scale"] == pytest.approx(0.5)
        assert path[hole]["flatten_applied"] is True
        assert path[hole]["gross_scale"] == 0.0
        assert path[hole]["topix_hedge_weight"] == 0.0
        assert path[hole]["pre_rebalance_sleeve_notional"] == pytest.approx(
            path[prior]["post_return_sleeve_notional"]
        )
        assert path[hole]["target_sleeve_notional"] == pytest.approx(0.0)
        assert path[hole]["target_topix_proxy_notional"] == pytest.approx(0.0)
        assert path[hole]["sleeve_trade_notional"] == pytest.approx(
            -path[hole]["pre_rebalance_sleeve_notional"]
        )


def test_official_calendar_adjacency_and_no_expiry_substitution() -> None:
    rows, features, dates, chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    skipped = sorted(chosen)[3]
    skipped_index = dates.index(skipped)
    features = _features(
        dates,
        successful=chosen,
        q_value=1.0,
        mismatch=0.10,
        mutate={
            (skipped, SMILE_TRANSPORT_CANDIDATE_IDS[0]): {
                "previous_observation_date": dates[skipped_index - 2],
            },
            (sorted(chosen)[4], SMILE_TRANSPORT_CANDIDATE_IDS[1]): {
                "expiry_rank_substitution_applied": True,
                "next_expiry": "2024-06-14",
            },
        },
    )
    report = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    excluded = {row["date"]: row["reasons"] for row in report["common_validity_gate"]["excluded"]}
    assert skipped in excluded
    assert any("official_predecessor" in reason for reason in excluded[skipped])
    substituted = sorted(chosen)[4]
    assert substituted in excluded
    assert any("expiry_rank_substitution" in reason for reason in excluded[substituted])


def test_single_stock_iv_provenance_is_rejected() -> None:
    dates = _dates(80)
    rows = _observations(dates)
    features = _features(dates, successful=set(dates[BETA_MIN_RETURNS:]))
    features[0]["surface_scope"] = "single_stock_options"
    features[0]["source_dataset_id"] = "equities_options_iv"
    with pytest.raises(ValueError, match="single-stock"):
        _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])


def test_existing_overlay_cohort_is_unchanged() -> None:
    dates = _dates(150)
    rows = [
        replace(
            row,
            n225_base_vol=0.20,
            n225_atm_iv=0.20,
            topix_realized_vol_20=0.10,
            n225_front_atm_iv=0.30,
            n225_next_atm_iv=0.20,
            n225_front_downside_wing_iv=0.40,
            n225_next_downside_wing_iv=0.20,
            available_at=f"{row.date}T16:00:00+09:00",
        )
        for row in _observations(dates)
    ]
    report = evaluate_index_vol_overlays(
        rows,
        manifest=build_prepared_panel_manifest(
            rows,
            authoritative_session_dates=dates,
            snapshot_digest="sha256:" + "3" * 64,
            base_report_digest="sha256:" + "4" * 64,
        ),
        authoritative_session_dates=dates,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    assert report["schema_version"] == "personal-index-vol-overlay/v1"
    assert [candidate["candidate_id"] for candidate in report["candidates"]] == [
        item.candidate_id for item in OVERLAY_CANDIDATES
    ]
    assert "n225_sticky_strike_downside_smile_term_surprise_v1" not in [
        candidate["candidate_id"] for candidate in report["candidates"]
    ]


def test_physical_potential_language_is_non_causal() -> None:
    rows, features, dates, _chosen = _gated_panel(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    report = _evaluate(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    assert report["physical_potential"] == {"metaphor_only": True, "causal_claim": False}
    potential = _by_id(report, "n225_sticky_strike_potential_minimum_transport_v1")
    downside = _by_id(report, "n225_sticky_strike_downside_smile_term_surprise_v1")
    assert potential["physical_potential"]["metaphor_only"] is True
    assert potential["physical_potential"]["causal_claim"] is False
    assert potential["physical_potential"]["applies_to_physical_potential_language"] is True
    assert downside["physical_potential"]["applies_to_physical_potential_language"] is False
    assert smile_transport_core_digest().startswith("sha256:")
