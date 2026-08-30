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
    AM_PM_BASE_PRODUCER_UNAVAILABLE,
    AM_PM_BASE_SLEEVE_ID,
    AM_PM_CONTROL_ID,
    AmPmBaseProducerUnavailable,
    AmPmFillOutcomeEvidence,
    AmPmLaggedFeatureEvidence,
    AmPmSignalEvidence,
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
    OVERLAY_CANDIDATES,
    PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA,
    PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA,
    PERSONAL_INDEX_VOL_OVERLAY_SCHEMA,
    PreparedIndexVolOverlayAmPmPanelManifest,
    PreparedIndexVolOverlayPanelManifest,
    SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS,
    SMILE_TRANSPORT_CANDIDATE_IDS,
    TOPIX_ETF_CODE,
    am_pm_base_producer_unavailable_reason,
    am_pm_fixture_base_definition,
    am_pm_temporal_contract_digest,
    am_pm_verified_base_binding,
    build_prepared_am_pm_panel_manifest,
    build_prepared_panel_manifest,
    canonical_am_pm_lagged_feature_evidence_digest,
    canonical_am_pm_signal_evidence_digest,
    evaluate_index_smile_transport_overlays_am_pm,
    evaluate_index_vol_overlays,
    evaluate_index_vol_overlays_am_pm,
    smile_transport_core_digest,
)


AM_PM_SPEC = "sha256:" + "c" * 64
AM_PM_COHORT = "sha256:" + "d" * 64
AM_PM_FIXTURE = am_pm_fixture_base_definition(
    strategy_spec_digest=AM_PM_SPEC,
    cohort_digest=AM_PM_COHORT,
)


def _dates(count: int, *, start: date = date(2023, 1, 4)) -> list[str]:
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _session(
    day: str,
    *,
    am_nav: float | None,
    pm_nav: float | None,
    etf_m: float | None,
    etf_a: float | None,
    cash: float,
    signal_at: str = "12:30:00+09:00",
    fill_at: str = "15:00:00+09:00",
    previous: str | None = None,
    n225_base_vol: float | None = 20.0,
    n225_atm_iv: float | None = 20.0,
    topix_realized_vol_20: float | None = 10.0,
    n225_front_atm_iv: float | None = 30.0,
    n225_next_atm_iv: float | None = 20.0,
    n225_front_downside_wing_iv: float | None = 40.0,
    n225_next_downside_wing_iv: float | None = 20.0,
    include_fill: bool = True,
) -> IndexVolOverlayAmPmObservation:
    fill = None
    if include_fill:
        fill = AmPmFillOutcomeEvidence(
            date=day,
            fill_available_at=f"{day}T{fill_at}",
            outcome_available_at=f"{day}T{fill_at}",
            base_sleeve_pm_nav=pm_nav,
            topix_etf_13060_aadjc=etf_a,
        )
    return IndexVolOverlayAmPmObservation(
        date=day,
        signal=AmPmSignalEvidence(
            date=day,
            signal_available_at=f"{day}T{signal_at}",
            base_sleeve_am_nav=am_nav,
            topix_etf_13060_madjc=etf_m,
        ),
        lagged_features=AmPmLaggedFeatureEvidence(
            source_session_date=day,
            feature_available_at=f"{day}T15:00:00+09:00",
            prior_source_session_date=previous,
            prior_feature_available_at=(
                f"{previous}T15:00:00+09:00" if previous else None
            ),
            topix_cash_close=cash,
            n225_cash_close=cash * 20.0,
            n225_base_vol=n225_base_vol,
            n225_atm_iv=n225_atm_iv,
            topix_realized_vol_20=topix_realized_vol_20,
            n225_front_atm_iv=n225_front_atm_iv,
            n225_next_atm_iv=n225_next_atm_iv,
            n225_front_downside_wing_iv=n225_front_downside_wing_iv,
            n225_next_downside_wing_iv=n225_next_downside_wing_iv,
            svi_equivalent_atm_term_ratio=1.45,
            svi_equivalent_downside_smile_term_ratio=1.90,
        ),
        fill_outcome=fill,
    )


def _am_pm_rows(
    dates: Sequence[str],
    *,
    beta: float = 4.0,
    signal_at: str = "12:30:00+09:00",
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
    return [
        _session(
            day,
            am_nav=am_nav[index],
            pm_nav=pm_nav[index],
            etf_m=etf_m[index],
            etf_a=etf_a[index],
            cash=cash[index],
            signal_at=signal_at,
            previous=dates[index - 1] if index else None,
        )
        for index, day in enumerate(dates)
    ]


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
        fixture_definition=AM_PM_FIXTURE,
    )


def _evaluate_overlay(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    **kwargs: Any,
) -> dict[str, Any]:
    dates = [row.date for row in rows]
    with am_pm_verified_base_binding(AM_PM_FIXTURE):
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


def _replace_signal(
    row: IndexVolOverlayAmPmObservation, **changes: Any
) -> IndexVolOverlayAmPmObservation:
    return replace(row, signal=replace(row.signal, **changes))


def _replace_lagged(
    row: IndexVolOverlayAmPmObservation, **changes: Any
) -> IndexVolOverlayAmPmObservation:
    if row.lagged_features is None:
        raise AssertionError("lagged feature evidence is required")
    return replace(row, lagged_features=replace(row.lagged_features, **changes))


def _replace_fill(
    row: IndexVolOverlayAmPmObservation, **changes: Any
) -> IndexVolOverlayAmPmObservation:
    if row.fill_outcome is None:
        return replace(row, fill_outcome=None)
    return replace(row, fill_outcome=replace(row.fill_outcome, **changes))


def _drop_fill(
    rows: Sequence[IndexVolOverlayAmPmObservation], index: int
) -> list[IndexVolOverlayAmPmObservation]:
    copied = list(rows)
    copied[index] = replace(copied[index], fill_outcome=None)
    return copied


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
    with am_pm_verified_base_binding(AM_PM_FIXTURE):
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
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    report = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    assert report["schema_version"] == PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA
    assert report["prepared_panel_provenance"]["signal_evidence_digest"]
    assert report["prepared_panel_provenance"]["lagged_feature_evidence_digest"]
    assert report["prepared_panel_provenance"]["fill_outcome_evidence_digest"]
    assert report["prepared_panel_provenance"]["signal_evidence_digest"] != (
        report["prepared_panel_provenance"]["fill_outcome_evidence_digest"]
    )
    assert report["prepared_panel_provenance"]["signal_evidence_digest"] != (
        report["prepared_panel_provenance"]["lagged_feature_evidence_digest"]
    )
    assert report["candidate_policy"]["selection"] == "NOT_PERFORMED"
    assert report["hedge_proxy"]["code"] == TOPIX_ETF_CODE
    assert report["cash_index"]["never_fills"] is True
    assert report["cash_index"]["executable_fill_claim"] is False
    assert report["cash_index"]["feeds_beta_or_rv_normalization"] is True
    assert N225_ETF_CODE == "13210"


def test_missing_definition_and_legacy_digest_fail_for_the_same_reason() -> None:
    dates = _dates(8)
    rows = _am_pm_rows(dates)
    assert am_pm_base_producer_unavailable_reason() == AM_PM_BASE_PRODUCER_UNAVAILABLE
    with pytest.raises(AmPmBaseProducerUnavailable, match=AM_PM_BASE_PRODUCER_UNAVAILABLE):
        build_prepared_am_pm_panel_manifest(
            rows,
            authoritative_session_dates=dates,
            snapshot_digest="sha256:" + "3" * 64,
            base_report_digest="sha256:" + "4" * 64,
            strategy_spec_digest=AM_PM_SPEC,
            cohort_digest=AM_PM_COHORT,
        )
    with pytest.raises(AmPmBaseProducerUnavailable, match=AM_PM_BASE_PRODUCER_UNAVAILABLE):
        build_prepared_am_pm_panel_manifest(
            rows,
            authoritative_session_dates=dates,
            snapshot_digest="sha256:" + "3" * 64,
            base_report_digest="sha256:" + "4" * 64,
            strategy_spec_digest=EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
            cohort_digest=EXPECTED_BASE_COHORT_DIGEST,
            fixture_definition=am_pm_fixture_base_definition(
                strategy_spec_digest=EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
                cohort_digest=EXPECTED_BASE_COHORT_DIGEST,
            ),
        )
    manifest = build_prepared_am_pm_panel_manifest(
        rows,
        authoritative_session_dates=dates,
        snapshot_digest="sha256:" + "3" * 64,
        base_report_digest="sha256:" + "4" * 64,
        strategy_spec_digest=AM_PM_SPEC,
        cohort_digest=AM_PM_COHORT,
        fixture_definition=AM_PM_FIXTURE,
    )
    assert manifest.strategy_spec_digest == AM_PM_SPEC
    assert manifest.cohort_digest == AM_PM_COHORT


def test_am_pm_rejects_old_next_close_panel() -> None:
    dates = _dates(8)
    rows = _am_pm_rows(dates)
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


def test_madjc_share_sizing_does_not_match_a_sized_notional() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    rows[130] = _replace_signal(rows[130], base_sleeve_am_nav=200.0)
    rows[130] = _replace_fill(rows[130], base_sleeve_pm_nav=50.0)
    report = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    path = _by_id(report, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0]
    gross = path["gross_scale"]
    m_price = 200.0
    a_price = 50.0
    target_dollar = gross * 1_000_000.0
    expected_units = target_dollar / m_price
    assert path["sleeve_sizing_price"] == pytest.approx(m_price)
    assert path["sleeve_fill_price"] == pytest.approx(a_price)
    assert path["target_sleeve_units"] == pytest.approx(expected_units)
    assert path["sleeve_fill_notional"] == pytest.approx(expected_units * a_price)
    assert path["sleeve_fill_notional"] != pytest.approx(target_dollar)
    a_sized_units = target_dollar / a_price
    assert path["target_sleeve_units"] != pytest.approx(a_sized_units)
    assert path["gross_pnl"] == pytest.approx(
        expected_units
        * (rows[131].fill_outcome.base_sleeve_pm_nav - a_price)
        + path["target_etf_13060_units"]
        * (
            rows[131].fill_outcome.topix_etf_13060_aadjc
            - rows[130].fill_outcome.topix_etf_13060_aadjc
        )
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
    mutated_d_option[130] = _replace_lagged(
        mutated_d_option[130],
        n225_front_atm_iv=999.0,
        n225_next_atm_iv=1.0,
        n225_base_vol=999.0,
        n225_atm_iv=999.0,
        n225_front_downside_wing_iv=999.0,
        n225_next_downside_wing_iv=1.0,
        topix_cash_close=mutated_d_option[130].lagged_features.topix_cash_close * 8.0,
        n225_cash_close=1.0,
    )
    mutated_d_option[130] = _replace_fill(
        mutated_d_option[130],
        base_sleeve_pm_nav=mutated_d_option[130].fill_outcome.base_sleeve_pm_nav * 1.05,
        topix_etf_13060_aadjc=mutated_d_option[130].fill_outcome.topix_etf_13060_aadjc
        * 1.05,
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
            "target_sleeve_units",
        ):
            if isinstance(before[field], float):
                assert after[field] == pytest.approx(before[field])
            else:
                assert after[field] == before[field]
        assert after["net_return"] != pytest.approx(before["net_return"])

    mutated_d_minus_1 = list(rows)
    mutated_d_minus_1[129] = _replace_lagged(
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

    mutated_madjc = list(rows)
    mutated_madjc[130] = _replace_signal(
        mutated_madjc[130],
        base_sleeve_am_nav=mutated_madjc[130].signal.base_sleeve_am_nav * 1.25,
        topix_etf_13060_madjc=mutated_madjc[130].signal.topix_etf_13060_madjc * 0.8,
    )
    after_am = _evaluate_overlay(
        mutated_madjc, signal_start=dates[130], signal_end=dates[130]
    )
    assert _by_id(after_am, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "estimated_beta"
    ] != pytest.approx(first["estimated_beta"])
    assert _by_id(after_am, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "target_sleeve_units"
    ] != pytest.approx(first["target_sleeve_units"])


def test_missing_d_a_does_not_change_morning_units_or_future_rebalance_date() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    original = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[131])
    original_first = _by_id(original, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][0]
    original_second = _by_id(original, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][1]
    missing_a = list(rows)
    missing_a[130] = replace(missing_a[130], fill_outcome=None)
    changed = _evaluate_overlay(
        missing_a, signal_start=dates[130], signal_end=dates[131]
    )
    first = _by_id(changed, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][0]
    second = _by_id(changed, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][1]
    assert first["target_sleeve_units"] == pytest.approx(
        original_first["target_sleeve_units"]
    )
    assert first["gross_scale"] == pytest.approx(original_first["gross_scale"])
    assert first["topix_hedge_weight"] == pytest.approx(
        original_first["topix_hedge_weight"]
    )
    assert first["no_fill"] is True
    assert first["stale_mark"] is False
    assert first["delta_sleeve_units"] == pytest.approx(0.0)
    assert first["carried_sleeve_units"] == pytest.approx(0.0)
    assert second["rebalance_date"] == original_second["rebalance_date"]
    assert second["signal_date"] == dates[131]
    candidate = _by_id(changed, OVERLAY_AM_PM_CANDIDATE_IDS[0])
    assert candidate["status"] == "NOT_EVALUATED"
    audit = candidate["execution_audit"]
    assert audit["comparable"] is False
    assert any(
        item["reason"] == "d_afternoon_unavailable_no_fill"
        for item in audit["no_fill_intervals"]
    )


def test_aadjc_changes_fill_pnl_only_and_first_pnl_is_d_pm() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    original = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    path = _by_id(original, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][0]
    assert path["pnl_date"] == dates[131]
    mutated = list(rows)
    mutated[131] = _replace_fill(
        mutated[131],
        base_sleeve_pm_nav=mutated[131].fill_outcome.base_sleeve_pm_nav * 1.5,
        topix_etf_13060_aadjc=mutated[131].fill_outcome.topix_etf_13060_aadjc * 0.5,
    )
    changed = _evaluate_overlay(mutated, signal_start=dates[130], signal_end=dates[130])
    after = _by_id(changed, OVERLAY_AM_PM_CANDIDATE_IDS[0])["daily_path"][0]
    assert after["feature_ratio_x"] == pytest.approx(path["feature_ratio_x"])
    assert after["target_sleeve_units"] == pytest.approx(path["target_sleeve_units"])
    assert after["gross_scale"] == pytest.approx(path["gross_scale"])
    assert after["net_return"] != pytest.approx(path["net_return"])


def test_missing_morning_or_prior_session_fails_decision() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    rows[130] = _replace_signal(rows[130], base_sleeve_am_nav=None)
    report = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    assert report["status"] == "NOT_EVALUATED"
    assert all(candidate["daily_path"] == [] for candidate in report["candidates"])
    restored = _am_pm_rows(dates)
    restored[129] = _replace_signal(restored[129], topix_etf_13060_madjc=None)
    prior = _evaluate_overlay(restored, signal_start=dates[130], signal_end=dates[130])
    assert prior["status"] == "NOT_EVALUATED"


def test_candidates_and_control_share_calendar_and_etf_costs() -> None:
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
        for trade in candidate["trades"]:
            if trade["side"].startswith("topix_etf_13060"):
                assert trade["instrument_code"] == "13060"
            assert "topix_cash" not in trade["side"]
            assert trade["cost"] == pytest.approx(
                abs(trade["notional"]) * ONE_WAY_COST_RATE
            )


def test_no_single_stock_iv_and_no_cash_index_executable_claim() -> None:
    dates = _dates(150)
    report = _evaluate_overlay(
        _am_pm_rows(dates), signal_start=dates[130], signal_end=dates[130]
    )
    assert report["base_sleeve"]["single_stock_option_iv"] == (
        "EXCLUDED_FROM_INPUT_SURFACE"
    )
    assert report["hedge_proxy"]["code"] == "13060"
    assert report["cash_index"]["never_fills"] is True


def test_signal_evidence_rejects_future_timestamp() -> None:
    dates = _dates(8)
    with pytest.raises(ValueError, match="12:30"):
        AmPmSignalEvidence(
            date=dates[0],
            signal_available_at=f"{dates[0]}T23:59:59+09:00",
            base_sleeve_am_nav=100.0,
            topix_etf_13060_madjc=1000.0,
        )


def test_fill_outcome_rejects_morning_timestamp() -> None:
    dates = _dates(8)
    with pytest.raises(ValueError, match="morning timestamp"):
        AmPmFillOutcomeEvidence(
            date=dates[0],
            fill_available_at=f"{dates[0]}T12:30:00+09:00",
            outcome_available_at=f"{dates[0]}T12:30:00+09:00",
            base_sleeve_pm_nav=100.0,
            topix_etf_13060_aadjc=1000.0,
        )


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
    mutated = _transport_features(
        dates,
        successful={dates[dates.index(day) - 1] for day in chosen},
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
    assert after["target_sleeve_units"] == pytest.approx(path["target_sleeve_units"])
    pair_end = dates[dates.index(signal) - 1]
    lagged = _transport_features(
        dates,
        successful={dates[dates.index(day) - 1] for day in chosen},
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


def test_smile_transport_single_stock_iv_is_rejected() -> None:
    dates = _dates(80)
    rows = _am_pm_rows(dates)
    features = _transport_features(dates, successful=set(dates[BETA_MIN_RETURNS:]))
    features[0]["surface_scope"] = "single_stock_options"
    features[0]["source_dataset_id"] = "equities_options_iv"
    with pytest.raises(ValueError, match="single-stock"):
        _evaluate_transport(rows, features, signal_start=dates[BETA_MIN_RETURNS])


def _april_smile_gate():
    return _gated_transport(
        valid_months=("2023-04", "2023-05", "2023-06", "2023-07"),
        per_month=10,
    )


def test_ordinary_missing_first_d_fill_is_non_comparable_while_flat() -> None:
    dates = _dates(150)
    report = _evaluate_overlay(
        _drop_fill(_am_pm_rows(dates), 130),
        signal_start=dates[130],
        signal_end=dates[130],
    )
    assert report["status"] == "NOT_EVALUATED"
    for candidate_id in OVERLAY_AM_PM_CANDIDATE_IDS:
        candidate = _by_id(report, candidate_id)
        path = candidate["daily_path"][0]
        assert candidate["status"] == "NOT_EVALUATED"
        assert path["no_fill"] is True
        assert path["stale_mark"] is False
        assert path["intended_delta_sleeve_units"] != pytest.approx(0.0)
        assert path["delta_sleeve_units"] == pytest.approx(0.0)
        assert candidate["execution_audit"]["comparable"] is False
        assert any(
            item["signal_date"] == dates[130]
            for item in candidate["execution_audit"]["no_fill_intervals"]
        )
    control = report["diagnostic_control"]
    assert control["status"] == "NOT_EVALUATED"
    assert control["execution_audit"]["comparable"] is False


def test_ordinary_missing_d_fill_with_held_delta_is_non_comparable() -> None:
    dates = _dates(150)
    report = _evaluate_overlay(
        _drop_fill(_am_pm_rows(dates), 131),
        signal_start=dates[130],
        signal_end=dates[132],
    )
    candidate = _by_id(report, OVERLAY_AM_PM_CANDIDATE_IDS[0])
    first, second, _third = candidate["daily_path"]
    assert first["no_fill"] is False
    assert first["carried_sleeve_units"] != pytest.approx(0.0)
    assert second["no_fill"] is True
    assert second["carried_sleeve_units"] == pytest.approx(first["carried_sleeve_units"])
    assert candidate["status"] == "NOT_EVALUATED"
    audit = candidate["execution_audit"]
    assert audit["comparable"] is False
    assert any(item["signal_date"] == dates[131] for item in audit["no_fill_intervals"])
    assert any(item["date"] == dates[131] for item in audit["stale_marks"])


def test_ordinary_exact_zero_delta_does_not_invent_unfilled_order() -> None:
    dates = _dates(150)
    report = _evaluate_overlay(
        _drop_fill(_am_pm_rows(dates), 131),
        signal_start=dates[130],
        signal_end=dates[131],
    )
    control = report["diagnostic_control"]
    first, second = control["daily_path"]
    assert first["no_fill"] is False
    assert first["carried_sleeve_units"] != pytest.approx(0.0)
    assert second["intended_delta_sleeve_units"] == pytest.approx(0.0)
    assert second["intended_delta_etf_13060_units"] == pytest.approx(0.0)
    assert second["no_fill"] is True
    audit = control["execution_audit"]
    assert not any(item["signal_date"] == dates[131] for item in audit["no_fill_intervals"])
    assert any(item["date"] == dates[131] for item in audit["stale_marks"])


def test_smile_missing_first_intended_fill_is_non_comparable_while_flat() -> None:
    rows, features, dates, chosen = _april_smile_gate()
    first_valid = min(chosen)
    report = _evaluate_transport(
        _drop_fill(rows, dates.index(first_valid)),
        features,
        signal_start=dates[BETA_MIN_RETURNS],
    )
    candidate = _by_id(report, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])
    path = next(
        row
        for row in candidate["daily_path"]
        if row["signal_date"] == first_valid
    )
    assert candidate["status"] == "NOT_EVALUATED"
    assert path["no_fill"] is True
    assert path["stale_mark"] is False
    assert path["intended_delta_sleeve_units"] != pytest.approx(0.0)
    assert candidate["execution_audit"]["comparable"] is False
    assert any(
        item["signal_date"] == first_valid
        for item in candidate["execution_audit"]["no_fill_intervals"]
    )


def test_smile_missing_d_fill_with_held_delta_is_non_comparable() -> None:
    rows, features, dates, chosen = _april_smile_gate()
    first_valid, second_valid = sorted(chosen)[:2]
    report = _evaluate_transport(
        _drop_fill(rows, dates.index(second_valid)),
        features,
        signal_start=dates[BETA_MIN_RETURNS],
    )
    candidate = _by_id(report, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])
    first = next(
        row
        for row in candidate["daily_path"]
        if row["signal_date"] == first_valid
    )
    second = next(
        row
        for row in candidate["daily_path"]
        if row["signal_date"] == second_valid
    )
    assert first["no_fill"] is False
    assert first["carried_sleeve_units"] != pytest.approx(0.0)
    assert second["no_fill"] is True
    assert second["carried_sleeve_units"] == pytest.approx(first["carried_sleeve_units"])
    assert candidate["status"] == "NOT_EVALUATED"
    audit = candidate["execution_audit"]
    assert audit["comparable"] is False
    assert any(item["date"] == second_valid for item in audit["stale_marks"])
    assert any(item["signal_date"] == second_valid for item in audit["no_fill_intervals"])


def test_smile_exact_zero_delta_does_not_invent_unfilled_order() -> None:
    rows, features, dates, chosen = _april_smile_gate()
    flatten_day = dates[BETA_MIN_RETURNS]
    assert flatten_day not in chosen
    report = _evaluate_transport(
        _drop_fill(rows, dates.index(flatten_day)),
        features,
        signal_start=dates[BETA_MIN_RETURNS],
    )
    candidate = _by_id(report, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])
    path = next(
        row
        for row in candidate["daily_path"]
        if row["signal_date"] == flatten_day
    )
    assert path["flatten_applied"] is True
    assert path["intended_delta_sleeve_units"] == pytest.approx(0.0)
    assert path["intended_delta_etf_13060_units"] == pytest.approx(0.0)
    assert path["no_fill"] is True
    assert not any(
        item["signal_date"] == flatten_day
        for item in candidate["execution_audit"]["no_fill_intervals"]
    )


def test_same_d_close_cannot_enter_d_morning_signal_evidence() -> None:
    dates = _dates(8)
    with pytest.raises(TypeError):
        AmPmSignalEvidence(
            date=dates[1],
            signal_available_at=f"{dates[1]}T12:30:00+09:00",
            base_sleeve_am_nav=100.0,
            topix_etf_13060_madjc=1000.0,
            n225_atm_iv=0.40,
        )
    with pytest.raises(ValueError, match="D-morning 12:30"):
        AmPmLaggedFeatureEvidence(
            source_session_date=dates[1],
            feature_available_at=f"{dates[1]}T12:30:00+09:00",
            n225_atm_iv=0.40,
        )
    with pytest.raises(ValueError, match="source session date"):
        AmPmLaggedFeatureEvidence(
            source_session_date=dates[1],
            feature_available_at=f"{dates[2]}T15:00:00+09:00",
            n225_atm_iv=0.40,
        )
    row = _am_pm_rows(dates)[1]
    assert row.lagged_features is not None
    with pytest.raises(ValueError, match="source_session_date must match"):
        replace(
            row,
            lagged_features=replace(
                row.lagged_features,
                source_session_date=dates[0],
                feature_available_at=f"{dates[0]}T15:00:00+09:00",
                prior_source_session_date=None,
                prior_feature_available_at=None,
            ),
        )


def test_lagged_close_digest_is_independent_of_morning_signal() -> None:
    dates = _dates(150)
    rows = _am_pm_rows(dates)
    original_signal = canonical_am_pm_signal_evidence_digest(rows)
    original_lagged = canonical_am_pm_lagged_feature_evidence_digest(rows)
    mutated_d = list(rows)
    mutated_d[130] = _replace_lagged(
        mutated_d[130], n225_atm_iv=999.0, n225_base_vol=999.0
    )
    assert canonical_am_pm_signal_evidence_digest(mutated_d) == original_signal
    assert canonical_am_pm_lagged_feature_evidence_digest(mutated_d) != original_lagged
    original = _evaluate_overlay(rows, signal_start=dates[130], signal_end=dates[130])
    after_d = _evaluate_overlay(
        mutated_d, signal_start=dates[130], signal_end=dates[130]
    )
    assert _by_id(after_d, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "feature_ratio_x"
    ] == pytest.approx(
        _by_id(original, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
            "feature_ratio_x"
        ]
    )
    mutated_d_minus_1 = list(rows)
    mutated_d_minus_1[129] = _replace_lagged(
        mutated_d_minus_1[129], n225_front_atm_iv=10.0, n225_next_atm_iv=20.0
    )
    after_lag = _evaluate_overlay(
        mutated_d_minus_1, signal_start=dates[130], signal_end=dates[130]
    )
    assert _by_id(after_lag, OVERLAY_AM_PM_CANDIDATE_IDS[2])["daily_path"][0][
        "feature_ratio_x"
    ] == pytest.approx(0.5)
    assert canonical_am_pm_lagged_feature_evidence_digest(mutated_d_minus_1) != (
        original_lagged
    )


def test_smile_lagged_pair_carries_honest_d_minus_2_and_d_minus_1() -> None:
    rows, features, dates, chosen = _april_smile_gate()
    signal = sorted(chosen)[5]
    index = dates.index(signal)
    lagged = rows[index - 1].lagged_features
    assert lagged is not None
    assert lagged.source_session_date == dates[index - 1]
    assert lagged.feature_available_at == f"{dates[index - 1]}T15:00:00+09:00"
    assert lagged.prior_source_session_date == dates[index - 2]
    assert lagged.prior_feature_available_at == f"{dates[index - 2]}T15:00:00+09:00"
    assert rows[index].signal.signal_available_at == f"{signal}T12:30:00+09:00"
    assert rows[index].lagged_features is not None
    assert rows[index].lagged_features.feature_available_at == (
        f"{signal}T15:00:00+09:00"
    )
    original = _evaluate_transport(rows, features, signal_start=dates[BETA_MIN_RETURNS])
    path = next(
        row
        for row in _by_id(original, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])["daily_path"]
        if row["signal_date"] == signal
    )
    mutated = list(rows)
    mutated[index] = _replace_lagged(mutated[index], n225_front_atm_iv=999.0)
    changed = _evaluate_transport(
        mutated, features, signal_start=dates[BETA_MIN_RETURNS]
    )
    after = next(
        row
        for row in _by_id(changed, SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS[0])["daily_path"]
        if row["signal_date"] == signal
    )
    assert after["feature_ratio_x"] == pytest.approx(path["feature_ratio_x"])
    assert after["target_sleeve_units"] == pytest.approx(path["target_sleeve_units"])
    assert canonical_am_pm_signal_evidence_digest(mutated) == (
        canonical_am_pm_signal_evidence_digest(rows)
    )


def test_am_pm_evaluation_requires_verified_producer_binding() -> None:
    dates = _dates(8)
    rows = _am_pm_rows(dates)
    manifest = _am_pm_manifest(rows)
    with pytest.raises(AmPmBaseProducerUnavailable, match=AM_PM_BASE_PRODUCER_UNAVAILABLE):
        evaluate_index_vol_overlays_am_pm(
            rows,
            manifest=manifest,
            authoritative_session_dates=dates,
            signal_start=dates[3],
            signal_end=dates[3],
        )
    payload = dict(
        strategy_spec_digest=AM_PM_SPEC,
        cohort_digest=AM_PM_COHORT,
        snapshot_digest="sha256:" + "3" * 64,
        base_report_digest="sha256:" + "4" * 64,
        trading_calendar_digest="sha256:" + "5" * 64,
        prepared_panel_digest="sha256:" + "6" * 64,
        signal_evidence_digest="sha256:" + "7" * 64,
        lagged_feature_evidence_digest="sha256:" + "8" * 64,
        fill_outcome_evidence_digest="sha256:" + "9" * 64,
        temporal_contract_digest=am_pm_temporal_contract_digest(),
        proxy_mapping_digest="sha256:" + "a" * 64,
        session_date_start=dates[0],
        session_date_end=dates[-1],
        session_count=len(dates),
    )
    with pytest.raises(AmPmBaseProducerUnavailable, match=AM_PM_BASE_PRODUCER_UNAVAILABLE):
        PreparedIndexVolOverlayAmPmPanelManifest(**payload)
    with am_pm_verified_base_binding(AM_PM_FIXTURE):
        with pytest.raises(AmPmBaseProducerUnavailable, match=AM_PM_BASE_PRODUCER_UNAVAILABLE):
            PreparedIndexVolOverlayAmPmPanelManifest(
                **{
                    **payload,
                    "strategy_spec_digest": "sha256:" + "e" * 64,
                    "cohort_digest": "sha256:" + "f" * 64,
                }
            )


def test_daily_path_net_return_matches_consecutive_equity_ratio() -> None:
    dates = _dates(150)
    report = _evaluate_overlay(
        _am_pm_rows(dates), signal_start=dates[130], signal_end=dates[132]
    )
    starting = 1_000_000.0
    for item in [*report["candidates"], report["diagnostic_control"]]:
        previous = starting
        assert item["daily_path"]
        for row in item["daily_path"]:
            assert row["net_return"] == pytest.approx(row["equity"] / previous - 1.0)
            previous = row["equity"]
    rows, features, dates_s, _chosen = _april_smile_gate()
    smile = _evaluate_transport(rows, features, signal_start=dates_s[BETA_MIN_RETURNS])
    for item in [*smile["candidates"], smile["diagnostic_control"]]:
        if not item["daily_path"]:
            continue
        previous = starting
        for row in item["daily_path"]:
            assert row["net_return"] == pytest.approx(row["equity"] / previous - 1.0)
            previous = row["equity"]


def test_fill_outcome_rejects_outcome_before_fill() -> None:
    dates = _dates(8)
    with pytest.raises(ValueError, match="must not precede"):
        AmPmFillOutcomeEvidence(
            date=dates[0],
            fill_available_at=f"{dates[0]}T16:00:00+09:00",
            outcome_available_at=f"{dates[0]}T15:00:00+09:00",
            base_sleeve_pm_nav=100.0,
            topix_etf_13060_aadjc=1000.0,
        )
    equal = AmPmFillOutcomeEvidence(
        date=dates[0],
        fill_available_at=f"{dates[0]}T15:00:00+09:00",
        outcome_available_at=f"{dates[0]}T15:00:00+09:00",
        base_sleeve_pm_nav=100.0,
        topix_etf_13060_aadjc=1000.0,
    )
    assert equal.outcome_available_at == equal.fill_available_at
