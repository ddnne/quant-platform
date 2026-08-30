"""Causal AM/PM overlay and smile-transport families stay off the D-close replay."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import pytest

from research.options_225_smile_features import OPTIONS_225_SMILE_SURFACE_SCOPE
from research.options_225_smile_transport import (
    OPTIONS_225_SMILE_TRANSPORT_VERSION,
    STICKY_MONEYNESS,
    STICKY_STRIKE,
    TRUSTED_FORWARD_UNAVAILABLE,
)
from research.options_225_vol_series import DATASET_ID
from research.personal_index_vol_overlay import (
    AM_PM_BASE_COHORT_ID,
    AM_PM_BASE_SLEEVE_ID,
    AM_PM_CONTROL_ID,
    BASE_COHORT_ID,
    BASE_SLEEVE_ID,
    BETA_MIN_RETURNS,
    EXPECTED_BASE_COHORT_DIGEST,
    EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
    IndexVolOverlayAmPmObservation,
    IndexVolOverlayObservation,
    N225_ETF_CODE,
    ONE_WAY_COST_RATE,
    OVERLAY_AM_PM_CANDIDATE_IDS,
    OVERLAY_AM_PM_CANDIDATES,
    OVERLAY_CANDIDATES,
    PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA,
    PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA,
    PERSONAL_INDEX_VOL_OVERLAY_SCHEMA,
    PreparedIndexVolOverlayPanelManifest,
    SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS,
    SMILE_TRANSPORT_CANDIDATE_IDS,
    TOPIX_ETF_CODE,
    am_pm_temporal_contract_digest,
    build_prepared_am_pm_panel_manifest,
    build_prepared_panel_manifest,
    evaluate_index_smile_transport_overlays_am_pm,
    evaluate_index_vol_overlays,
    evaluate_index_vol_overlays_am_pm,
    smile_transport_core_digest,
)


AM_PM_SPEC = "sha256:" + "c" * 64
AM_PM_COHORT = "sha256:" + "d" * 64


def _dates(count: int, *, start: date = date(2023, 1, 4)) -> list[str]:
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _am_pm_rows(
    dates: Sequence[str],
    *,
    beta: float = 4.0,
    available_at_hour: str = "12:30:00+09:00",
) -> list[IndexVolOverlayAmPmObservation]:
    am_nav = [100.0]
    pm_nav = [100.2]
    etf_m = [1_000.0]
    etf_a = [1_001.0]
    cash = [2_000.0]
    for index in range(1, len(dates)):
        proxy = (0.001 + (index % 5) * 0.0001) * (1.0 if index % 2 else -1.0)
        etf_m.append(etf_m[-1] * (1.0 + proxy))
        etf_a.append(etf_a[-1] * (1.0 + proxy * 0.98))
        am_nav.append(am_nav[-1] * (1.0 + beta * proxy))
        pm_nav.append(pm_nav[-1] * (1.0 + beta * proxy * 0.97))
        cash.append(cash[-1] * (1.0 + proxy))
    rows = []
    for index, day in enumerate(dates):
        rows.append(
            IndexVolOverlayAmPmObservation(
                date=day,
                available_at=f"{day}T{available_at_hour}",
                base_sleeve_am_nav=am_nav[index],
                base_sleeve_pm_nav=pm_nav[index],
                topix_etf_13060_madjc=etf_m[index],
                topix_etf_13060_aadjc=etf_a[index],
                topix_cash_close=cash[index],
                n225_cash_close=cash[index] * 20.0,
                n225_base_vol=20.0,
                n225_atm_iv=20.0,
                topix_realized_vol_20=10.0,
                n225_front_atm_iv=30.0,
                n225_next_atm_iv=20.0,
                n225_front_downside_wing_iv=40.0,
                n225_next_downside_wing_iv=20.0,
                svi_equivalent_atm_term_ratio=1.45,
                svi_equivalent_downside_smile_term_ratio=1.90,
            )
        )
    return rows


def _am_pm_manifest(
    rows: Sequence[IndexVolOverlayAmPmObservation],
) -> Any:
    dates = [row.date for row in rows]
    return build_prepared_am_pm_panel_manifest(
        rows,
        authoritative_session_dates=dates,
        snapshot_digest="sha256:" + "3" * 64,
        base_report_digest="sha256:" + "4" * 64,
        strategy_spec_digest=AM_PM_SPEC,
        cohort_digest=AM_PM_COHORT,
    )


def _evaluate_overlay(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    **kwargs: Any,
) -> dict[str, Any]:
    dates = [row.date for row in rows]
    return evaluate_index_vol_overlays_am_pm(
        rows,
        manifest=_am_pm_manifest(rows),
        authoritative_session_dates=dates,
        **kwargs,
    )


def _by_id(report: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(
        candidate
        for candidate in report["candidates"]
        if candidate["candidate_id"] == candidate_id
    )


def _transport_row(
    *,
    day: str,
    previous: str,
    candidate_id: str,
    model: str,
    family: str,
    success: bool,
    value: float | None,
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
        "front_expiry": "2024-03-08" if success else None,
        "next_expiry": "2024-04-12" if success else None,
        "version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
        "surface_scope": OPTIONS_225_SMILE_SURFACE_SCOPE,
        "source_dataset_id": DATASET_ID,
        "single_stock_iv_used": False,
        "coordinate_definition": "k=ln(strike/UnderPx_proxy)",
        "under_px_is_trusted_forward": False,
        "trusted_forward_available": False,
        "forward_relative_minimum_log_moneyness": None,
        "forward_relative_minimum_strike_ratio_minus_one": None,
        "forward_relative_reason": TRUSTED_FORWARD_UNAVAILABLE,
        "signal_cutoff": "D_close",
        "execution_intent": "D_plus_1_or_later",
        "research_status": "DRAFT_DIAGNOSTIC_ONLY",
        "pairing_rule": "adjacent_observation_dates_exact_same_expiry",
        "ffill_applied": False,
        "expiry_rank_substitution_applied": False,
        "extrapolation_applied": False,
    }
    if extra:
        payload.update(extra)
    return payload


def _transport_features(
    dates: Sequence[str],
    *,
    successful: set[str] | None = None,
    q_value: float = 0.0,
    mismatch: float = 0.0,
    mutate: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    identity = {
        "n225_sticky_strike_downside_smile_term_surprise_am_pm_v1": (
            STICKY_STRIKE,
            "downside_smile_term_surprise",
            q_value,
        ),
        "n225_sticky_moneyness_downside_smile_term_surprise_am_pm_v1": (
            STICKY_MONEYNESS,
            "downside_smile_term_surprise",
            q_value,
        ),
        "n225_sticky_strike_potential_minimum_transport_am_pm_v1": (
            STICKY_STRIKE,
            "potential_minimum_transport",
            mismatch,
        ),
        "n225_sticky_moneyness_potential_minimum_transport_am_pm_v1": (
            STICKY_MONEYNESS,
            "potential_minimum_transport",
            mismatch,
        ),
    }
    rows: list[dict[str, Any]] = []
    for index, day in enumerate(dates):
        if index == 0:
            continue
        ok = successful is None or day in successful
        for candidate_id, (model, family, value) in identity.items():
            extra = dict((mutate or {}).get((day, candidate_id), {}))
            rows.append(
                _transport_row(
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


def _evaluate_transport(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    features: Sequence[Mapping[str, Any]],
    *,
    signal_start: str,
    signal_end: str | None = None,
) -> dict[str, Any]:
    dates = [row.date for row in rows]
    return evaluate_index_smile_transport_overlays_am_pm(
        rows,
        features,
        manifest=_am_pm_manifest(rows),
        authoritative_session_dates=dates,
        signal_start=signal_start,
        signal_end=signal_end,
        core_digest=smile_transport_core_digest(),
    )


def test_legacy_overlay_serialized_identity_is_unchanged() -> None:
    start = date(2024, 1, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(150)]
    closes = [100.0]
    returns = [0.0]
    for index in range(1, 150):
        proxy = (0.001 + (index % 5) * 0.0001) * (1.0 if index % 2 else -1.0)
        returns.append(4.0 * proxy)
        closes.append(closes[-1] * (1.0 + proxy))
    rows = [
        IndexVolOverlayObservation(
            date=day,
            available_at=f"{day}T16:00:00+09:00",
            base_sleeve_return=returns[index],
            topix_cash_close=closes[index],
            n225_base_vol=20.0,
            n225_atm_iv=20.0,
            topix_realized_vol_20=10.0,
            n225_front_atm_iv=30.0,
            n225_next_atm_iv=20.0,
            n225_front_downside_wing_iv=40.0,
            n225_next_downside_wing_iv=20.0,
        )
        for index, day in enumerate(dates)
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
    assert report["schema_version"] == PERSONAL_INDEX_VOL_OVERLAY_SCHEMA
    assert report["base_sleeve"]["strategy_id"] == BASE_SLEEVE_ID
    assert [candidate["candidate_id"] for candidate in report["candidates"]] == [
        item.candidate_id for item in OVERLAY_CANDIDATES
    ]
    assert report["timing"]["first_pnl"] == "D_PLUS_1_CLOSE_TO_D_PLUS_2_CLOSE"
    assert report["topix_proxy"]["etf_fill_claim"] is False
    assert report["candidate_policy"]["post_result_selection"] == "NOT_PERFORMED"


def test_am_pm_exact_four_ids_and_distinct_schemas() -> None:
    assert AM_PM_BASE_COHORT_ID == "sector-relative-ls-am-pm-v1"
    assert AM_PM_BASE_SLEEVE_ID != BASE_SLEEVE_ID
    assert AM_PM_BASE_COHORT_ID != BASE_COHORT_ID
    assert list(OVERLAY_AM_PM_CANDIDATE_IDS) == [
        "n225_basevol_10_over_60_defensive_am_pm_v1",
        "n225_atmiv_over_topix_rv20_normalized_126_am_pm_v1",
        "n225_observed_front_over_next_atm_am_pm_v1",
        "n225_observed_downside_smile_front_over_next_am_pm_v1",
    ]
    assert list(SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS) == [
        "n225_sticky_strike_downside_smile_term_surprise_am_pm_v1",
        "n225_sticky_moneyness_downside_smile_term_surprise_am_pm_v1",
        "n225_sticky_strike_potential_minimum_transport_am_pm_v1",
        "n225_sticky_moneyness_potential_minimum_transport_am_pm_v1",
    ]
    assert list(OVERLAY_AM_PM_CANDIDATE_IDS) != [
        item.candidate_id for item in OVERLAY_CANDIDATES
    ]
    assert list(SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS) != list(
        SMILE_TRANSPORT_CANDIDATE_IDS
    )
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    report = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    assert report["schema_version"] == PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA
    assert report["schema_version"] != PERSONAL_INDEX_VOL_OVERLAY_SCHEMA
    assert report["prepared_panel_provenance"]["base_cohort_id"] == AM_PM_BASE_COHORT_ID
    assert report["prepared_panel_provenance"]["temporal_contract_digest"] == (
        am_pm_temporal_contract_digest()
    )
    assert report["prepared_panel_provenance"]["cohort_digest"] != (
        EXPECTED_BASE_COHORT_DIGEST
    )
    assert report["prepared_panel_provenance"]["strategy_spec_digest"] != (
        EXPECTED_BASE_STRATEGY_SPEC_DIGEST
    )
    assert report["candidate_policy"]["selection"] == "NOT_PERFORMED"
    assert report["hedge_proxy"]["code"] == TOPIX_ETF_CODE
    assert report["hedge_proxy"]["etf_fill_claim"] is True
    assert report["hedge_proxy"]["tracking_basis_risk"] is True
    assert report["cash_index"]["executable_fill_claim"] is False
    assert report["cash_index"]["role"] == "DIAGNOSTIC_BETA_CONTEXT_ONLY"
    assert N225_ETF_CODE == "13210"


def test_am_pm_rejects_old_next_close_panel_and_legacy_digests() -> None:
    dates = _dates(8)
    rows = _am_pm_rows(dates)
    with pytest.raises(ValueError, match="old next-close strategy_spec_digest"):
        build_prepared_am_pm_panel_manifest(
            rows,
            authoritative_session_dates=dates,
            snapshot_digest="sha256:" + "3" * 64,
            base_report_digest="sha256:" + "4" * 64,
            strategy_spec_digest=EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
            cohort_digest=AM_PM_COHORT,
        )
    with pytest.raises(ValueError, match="old sector-relative-ls-v1"):
        build_prepared_am_pm_panel_manifest(
            rows,
            authoritative_session_dates=dates,
            snapshot_digest="sha256:" + "3" * 64,
            base_report_digest="sha256:" + "4" * 64,
            strategy_spec_digest=AM_PM_SPEC,
            cohort_digest=EXPECTED_BASE_COHORT_DIGEST,
        )
    with pytest.raises(TypeError, match="old next-close prepared panel"):
        evaluate_index_vol_overlays_am_pm(
            rows,
            manifest=PreparedIndexVolOverlayPanelManifest(  # type: ignore[arg-type]
                strategy_spec_digest=EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
                cohort_digest=EXPECTED_BASE_COHORT_DIGEST,
                snapshot_digest="sha256:" + "3" * 64,
                base_report_digest="sha256:" + "4" * 64,
                trading_calendar_digest="sha256:" + "5" * 64,
                prepared_panel_digest="sha256:" + "6" * 64,
                session_date_start=dates[0],
                session_date_end=dates[-1],
                session_count=len(dates),
            ),
            authoritative_session_dates=dates,
            signal_start=dates[3],
            signal_end=dates[3],
        )


def test_ordinary_overlay_d_signal_uses_d_minus_1_options_and_d_madjc() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    original = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    assert original["status"] == "EVALUATED"
    first = _by_id(original, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0]
    assert first["signal_date"] == dates[130]
    assert first["rebalance_date"] == dates[130]
    assert first["pnl_date"] == dates[131]
    assert first["feature_ratio_x"] == pytest.approx(1.5)

    mutated_d_option = list(rows)
    mutated_d_option[130] = replace(
        mutated_d_option[130],
        n225_front_atm_iv=999.0,
        n225_next_atm_iv=1.0,
        n225_base_vol=999.0,
        n225_atm_iv=999.0,
        n225_front_downside_wing_iv=999.0,
        n225_next_downside_wing_iv=1.0,
        topix_cash_close=mutated_d_option[130].topix_cash_close * 8.0,
        n225_cash_close=1.0,
        base_sleeve_pm_nav=mutated_d_option[130].base_sleeve_pm_nav * 3.0,
        topix_etf_13060_aadjc=mutated_d_option[130].topix_etf_13060_aadjc * 3.0,
    )
    after_d = _evaluate_overlay(
        mutated_d_option, signal_start=dates[130], signal_end=dates[130]
    )
    for candidate_id in OVERLAY_AM_PM_CANDIDATE_IDS:
        before = _by_id(original, candidate_id)["daily_path"][0]
        after = _by_id(after_d, candidate_id)["daily_path"][0]
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

    mutated_d_minus_1 = list(rows)
    mutated_d_minus_1[129] = replace(
        mutated_d_minus_1[129],
        n225_front_atm_iv=10.0,
        n225_next_atm_iv=20.0,
    )
    after_lag = _evaluate_overlay(
        mutated_d_minus_1, signal_start=dates[130], signal_end=dates[130]
    )
    assert _by_id(after_lag, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "feature_ratio_x"
    ] == pytest.approx(0.5)
    assert _by_id(after_lag, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "feature_ratio_x"
    ] != pytest.approx(first["feature_ratio_x"])

    mutated_madjc = list(rows)
    mutated_madjc[130] = replace(
        mutated_madjc[130],
        base_sleeve_am_nav=mutated_madjc[130].base_sleeve_am_nav * 1.25,
        topix_etf_13060_madjc=mutated_madjc[130].topix_etf_13060_madjc * 0.8,
    )
    after_am = _evaluate_overlay(
        mutated_madjc, signal_start=dates[130], signal_end=dates[130]
    )
    assert _by_id(after_am, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "estimated_beta"
    ] != pytest.approx(first["estimated_beta"])


def test_aadjc_changes_fill_pnl_only_and_first_pnl_is_d_pm() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    original = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    path = _by_id(original, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][0]
    assert path["pnl_date"] == dates[131]
    assert path["date"] == dates[131]
    mutated = list(rows)
    mutated[131] = replace(
        mutated[131],
        base_sleeve_pm_nav=mutated[131].base_sleeve_pm_nav * 1.5,
        topix_etf_13060_aadjc=mutated[131].topix_etf_13060_aadjc * 0.5,
        base_sleeve_am_nav=mutated[131].base_sleeve_am_nav,
    )
    changed = _evaluate_overlay(mutated, signal_start=dates[130], signal_end=dates[130])
    after = _by_id(changed, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][0]
    assert after["feature_ratio_x"] == pytest.approx(path["feature_ratio_x"])
    assert after["gross_scale"] == pytest.approx(path["gross_scale"])
    assert after["estimated_beta"] == pytest.approx(path["estimated_beta"])
    assert after["net_return"] != pytest.approx(path["net_return"])


def test_missing_m_a_or_prior_session_fails_closed() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    rows[130] = replace(rows[130], base_sleeve_am_nav=None)
    report = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    assert report["status"] == "NOT_EVALUATED"
    assert all(candidate["daily_path"] == [] for candidate in report["candidates"])
    assert all(candidate["performance"] is None for candidate in report["candidates"])
    assert report["diagnostic_control"]["performance"] is None

    restored = _am_pm_rows(dates)
    restored[129] = replace(restored[129], topix_etf_13060_madjc=None)
    prior = _evaluate_overlay(restored, signal_start=dates[130], signal_end=dates[130])
    assert prior["status"] == "NOT_EVALUATED"
    assert all(candidate["daily_path"] == [] for candidate in prior["candidates"])


def test_candidates_and_control_share_calendar_and_costs() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    report = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[131])
    control = report["diagnostic_control"]
    assert control["control_id"] == AM_PM_CONTROL_ID
    calendars = [
        [(row["signal_date"], row["rebalance_date"], row["pnl_date"]) for row in path]
        for path in (
            [candidate["daily_path"] for candidate in report["candidates"]]
            + [control["daily_path"]]
        )
    ]
    assert len({tuple(item) for item in calendars}) == 1
    for candidate in report["candidates"]:
        assert candidate["performance"]["cost_turnover_fill_scope"] == (
            "OVERLAY_INCREMENTAL_ONLY"
        )
        assert candidate["performance"]["cost_amount"] > 0.0
        for trade in candidate["trades"]:
            assert trade["cost"] == pytest.approx(
                abs(trade["notional"]) * ONE_WAY_COST_RATE
            )
    assert control["performance"]["cost_turnover_fill_scope"] == (
        "OVERLAY_INCREMENTAL_ONLY"
    )
    assert report["cost_model"]["one_way_basis_points"] == 10.0
    assert ONE_WAY_COST_RATE == 0.001


def test_no_single_stock_iv_and_no_cash_index_executable_claim() -> None:
    fields = set(IndexVolOverlayAmPmObservation.__dataclass_fields__)
    assert not any("stock" in field and "iv" in field for field in fields)
    dates = _dates(150)
    report = _evaluate_overlay(
        _am_pm_rows(dates), signal_start=dates[130], signal_end=dates[130]
    )
    assert report["base_sleeve"]["single_stock_option_iv"] == (
        "EXCLUDED_FROM_INPUT_SURFACE"
    )
    assert report["hedge_proxy"]["code"] == "13060"
    assert report["cash_index"]["executable_fill_claim"] is False
    assert "indices_bars_daily_topix" in str(report["cash_index"])


def test_late_available_at_is_rejected() -> None:
    dates = _dates(8)
    rows = _am_pm_rows(dates, available_at_hour="23:59:59+09:00")
    with pytest.raises(ValueError, match="12:30"):
        _am_pm_manifest(rows)


def _month_days(dates: Sequence[str], month: str, count: int) -> list[str]:
    chosen = [day for day in dates if day.startswith(month)]
    return chosen[:count]


def _gated_transport(*, valid_months: Sequence[str], per_month: int):
    dates = _dates(220)
    rows = _am_pm_rows(dates, beta=1.25)
    signal_dates = dates[BETA_MIN_RETURNS : len(dates) - 1]
    chosen_signals: list[str] = []
    for month in valid_months:
        chosen_signals.extend(_month_days(signal_dates, month, per_month))
    pair_ends = {dates[dates.index(day) - 1] for day in chosen_signals}
    features = _transport_features(
        dates, successful=pair_ends, q_value=1.0, mismatch=0.10
    )
    return rows, features, dates, set(chosen_signals)


def test_smile_transport_uses_d_minus_2_to_d_minus_1_and_ignores_d_surface() -> None:
    rows, features, dates, chosen = _gated_transport(
        valid_months=("2023-03", "2023-04", "2023-05", "2023-06"),
        per_month=10,
    )
    signal = sorted(chosen)[5]
    original = _evaluate_transport(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    assert original["schema_version"] == PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA
    assert original["status"] == "EVALUATED"
    path = next(
        row
        for row in _by_id(original, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])["daily_path"]
        if row["signal_date"] == signal
    )
    assert path["rebalance_date"] == signal
    assert path["pnl_date"] == dates[dates.index(signal) + 1]
    assert original["common_validity_gate"]["transport_pair"] == (
        "d_minus_2_to_d_minus_1"
    )

    mutated = _transport_features(
        dates,
        successful=chosen,
        q_value=1.0,
        mismatch=0.10,
        mutate={
            (signal, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0]): {"candidate_value": 99.0}
        },
    )
    changed = _evaluate_transport(rows, mutated, signal_start=dates[BETA_MIN_RETURNS])
    after = next(
        row
        for row in _by_id(changed, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])["daily_path"]
        if row["signal_date"] == signal
    )
    assert after["feature_ratio_x"] == pytest.approx(path["feature_ratio_x"])
    assert after["gross_scale"] == pytest.approx(path["gross_scale"])

    pair_end = dates[dates.index(signal) - 1]
    lagged = _transport_features(
        dates,
        successful=chosen,
        q_value=1.0,
        mismatch=0.10,
        mutate={
            (pair_end, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0]): {"candidate_value": 3.0}
        },
    )
    lagged_report = _evaluate_transport(
        rows, lagged, signal_start=dates[BETA_MIN_RETURNS]
    )
    lagged_path = next(
        row
        for row in _by_id(lagged_report, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])[
            "daily_path"
        ]
        if row["signal_date"] == signal
    )
    assert lagged_path["feature_ratio_x"] == pytest.approx(3.0)
    assert lagged_path["feature_ratio_x"] != pytest.approx(path["feature_ratio_x"])


def test_smile_transport_single_stock_iv_is_rejected() -> None:
    dates = _dates(80)
    rows = _am_pm_rows(dates)
    features = _transport_features(dates, successful=set(dates[BETA_MIN_RETURNS:]))
    features[0]["surface_scope"] = "single_stock_options"
    features[0]["source_dataset_id"] = "equities_options_iv"
    with pytest.raises(ValueError, match="single-stock"):
        _evaluate_transport(rows, features, signal_start=dates[BETA_MIN_RETURNS])
