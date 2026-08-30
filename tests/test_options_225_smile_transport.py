"""Focused invariants for Nikkei 225 SVI smile transport diagnostics."""

from __future__ import annotations

import math
from datetime import date

import pytest

from research.options_225_smile_features import (
    OPTIONS_225_SMILE_FEATURE_VERSION,
    OPTIONS_225_SMILE_SURFACE_SCOPE,
    SVIParameters,
    svi_first_derivative,
    svi_second_derivative,
    svi_total_variance,
)
from research.options_225_smile_transport import (
    STICKY_MONEYNESS,
    STICKY_STRIKE,
    build_options_225_smile_transport_rows,
    build_daily_svi_smile_transport_features,
    build_svi_smile_transport_rows,
    svi_potential_minimum,
)
from research.options_225_vol_series import DATASET_ID


def _scale_surface(
    parameters: SVIParameters, scale: float, *, m: float | None = None
) -> SVIParameters:
    return SVIParameters(
        a=parameters.a * scale,
        b=parameters.b * scale,
        rho=parameters.rho,
        m=parameters.m if m is None else m,
        sigma=parameters.sigma,
    )


def _slice(
    *,
    observation_date: str,
    expiry: str,
    under_px: float,
    parameters: SVIParameters,
    cm: str | None = None,
    band: tuple[float, float] = (-0.30, 0.30),
    surface_scope: str = OPTIONS_225_SMILE_SURFACE_SCOPE,
) -> dict:
    dte = (date.fromisoformat(expiry) - date.fromisoformat(observation_date)).days
    return {
        "date": observation_date,
        "expiry": expiry,
        "cm": cm or expiry[:7],
        "dte_days": dte,
        "maturity_years": dte / 365.0,
        "under_px": under_px,
        "fit_success": True,
        "fit_reason": "ok",
        "svi_parameters": parameters.as_dict(),
        "fit_log_moneyness_min": band[0],
        "fit_log_moneyness_max": band[1],
        "surface_scope": surface_scope,
        "source_dataset_id": DATASET_ID,
        "version": OPTIONS_225_SMILE_FEATURE_VERSION,
        "moneyness_proxy": "under_px_not_forward",
        "k_definition": "ln(strike/under_px)",
        "forward_adjustment_applied": False,
    }


def _rows_by_model(rows: list[dict]) -> dict[str, dict]:
    return {str(row["transport_model"]): row for row in rows}


def _candidates(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {
        (str(row["transport_model"]), str(row["signal_family"])): row
        for row in rows
    }


def test_analytic_potential_minimum_matches_numerical_derivatives_and_grid() -> None:
    parameters = SVIParameters(a=0.007, b=0.044, rho=-0.38, m=0.017, sigma=0.13)
    minimum = svi_potential_minimum(parameters)
    expected_k = parameters.m - (
        parameters.rho * parameters.sigma / math.sqrt(1.0 - parameters.rho**2)
    )
    expected_w = parameters.a + (
        parameters.b * parameters.sigma * math.sqrt(1.0 - parameters.rho**2)
    )

    assert minimum.log_moneyness == pytest.approx(expected_k, abs=1e-15)
    assert minimum.total_variance == pytest.approx(expected_w, abs=1e-15)
    assert minimum.first_derivative == pytest.approx(0.0, abs=1e-15)
    assert svi_first_derivative(minimum.log_moneyness, parameters) == pytest.approx(
        0.0, abs=1e-15
    )

    h = 1.0e-5
    w_left = svi_total_variance(minimum.log_moneyness - h, parameters)
    w_mid = svi_total_variance(minimum.log_moneyness, parameters)
    w_right = svi_total_variance(minimum.log_moneyness + h, parameters)
    numerical_first = (w_right - w_left) / (2.0 * h)
    numerical_second = (w_right - 2.0 * w_mid + w_left) / (h * h)
    assert numerical_first == pytest.approx(0.0, abs=1e-10)
    assert minimum.curvature == pytest.approx(numerical_second, rel=2e-6)
    assert minimum.curvature == pytest.approx(
        svi_second_derivative(minimum.log_moneyness, parameters), rel=1e-14
    )
    sampled = [
        svi_total_variance(-0.30 + i * 0.0001, parameters) for i in range(6001)
    ]
    assert w_mid <= min(sampled) + 1.0e-10


def test_invalid_raw_svi_has_no_potential_minimum() -> None:
    with pytest.raises(ValueError, match="b>0"):
        svi_potential_minimum(
            SVIParameters(a=0.01, b=-0.02, rho=0.0, m=0.0, sigma=0.1)
        )
    with pytest.raises(ValueError, match="positive"):
        svi_potential_minimum(
            SVIParameters(a=-1.0, b=0.02, rho=0.0, m=0.0, sigma=0.1)
        )


def test_exact_sticky_moneyness_surface_has_zero_sm_transport_errors() -> None:
    previous_date = "2024-01-08"
    current_date = "2024-01-09"
    expiry = "2024-03-15"
    previous_under = 40_000.0
    current_under = 40_800.0
    previous = SVIParameters(a=0.008, b=0.038, rho=-0.31, m=0.02, sigma=0.15)
    previous_t = (date.fromisoformat(expiry) - date.fromisoformat(previous_date)).days / 365.0
    current_t = (date.fromisoformat(expiry) - date.fromisoformat(current_date)).days / 365.0
    current = _scale_surface(previous, current_t / previous_t)
    rows = build_svi_smile_transport_rows(
        [
            _slice(
                observation_date=previous_date,
                expiry=expiry,
                under_px=previous_under,
                parameters=previous,
            ),
            _slice(
                observation_date=current_date,
                expiry=expiry,
                under_px=current_under,
                parameters=current,
            ),
        ]
    )
    by_model = _rows_by_model(rows)
    sticky_moneyness = by_model[STICKY_MONEYNESS]
    sticky_strike = by_model[STICKY_STRIKE]

    assert sticky_moneyness["downside_transport_success"] is True
    assert sticky_moneyness["downside_smile_surprise"] == pytest.approx(0.0, abs=1e-14)
    assert sticky_moneyness["potential_minimum_transport_success"] is True
    assert sticky_moneyness["minimum_location_error_log_moneyness"] == pytest.approx(
        0.0, abs=1e-15
    )
    assert sticky_moneyness["minimum_iv_actual_over_predicted_minus_one"] == pytest.approx(
        0.0, abs=1e-14
    )
    assert sticky_moneyness["potential_depth_surprise"] == pytest.approx(0.0, abs=1e-14)
    assert abs(float(sticky_strike["minimum_location_error_log_moneyness"])) > 0.01


def test_exact_sticky_strike_surface_uses_shifted_coordinate_and_minimum() -> None:
    previous_date = "2024-01-08"
    current_date = "2024-01-09"
    expiry = "2024-03-15"
    previous_under = 40_000.0
    current_under = 40_800.0
    proxy_return = math.log(current_under / previous_under)
    previous = SVIParameters(a=0.008, b=0.038, rho=-0.31, m=0.02, sigma=0.15)
    previous_t = (date.fromisoformat(expiry) - date.fromisoformat(previous_date)).days / 365.0
    current_t = (date.fromisoformat(expiry) - date.fromisoformat(current_date)).days / 365.0
    current = _scale_surface(
        previous, current_t / previous_t, m=previous.m - proxy_return
    )
    rows = build_svi_smile_transport_rows(
        [
            _slice(
                observation_date=previous_date,
                expiry=expiry,
                under_px=previous_under,
                parameters=previous,
            ),
            _slice(
                observation_date=current_date,
                expiry=expiry,
                under_px=current_under,
                parameters=current,
            ),
        ]
    )
    by_model = _rows_by_model(rows)
    sticky_strike = by_model[STICKY_STRIKE]
    sticky_moneyness = by_model[STICKY_MONEYNESS]
    previous_min = svi_potential_minimum(previous).log_moneyness

    assert sticky_strike["previous_source_atm_proxy_log_moneyness"] == pytest.approx(
        proxy_return
    )
    assert sticky_strike["predicted_minimum_proxy_log_moneyness"] == pytest.approx(
        previous_min - proxy_return
    )
    assert sticky_strike["downside_smile_surprise"] == pytest.approx(0.0, abs=1e-14)
    assert sticky_strike["minimum_location_error_log_moneyness"] == pytest.approx(
        0.0, abs=1e-15
    )
    assert sticky_strike["minimum_strike_actual_over_predicted_minus_one"] == pytest.approx(
        0.0, abs=1e-15
    )
    assert sticky_moneyness["minimum_location_error_log_moneyness"] == pytest.approx(
        -proxy_return, abs=1e-15
    )


def test_daily_rows_expose_zero_term_surprise_for_exact_model() -> None:
    previous_date = "2024-01-08"
    current_date = "2024-01-09"
    expiries = ("2024-02-16", "2024-03-15")
    previous_under = 40_000.0
    current_under = 40_400.0
    slices: list[dict] = []
    for index, expiry in enumerate(expiries):
        previous = SVIParameters(
            a=0.007 + index * 0.003,
            b=0.034 + index * 0.004,
            rho=-0.35 + index * 0.08,
            m=0.01 + index * 0.005,
            sigma=0.14 + index * 0.03,
        )
        previous_t = (
            date.fromisoformat(expiry) - date.fromisoformat(previous_date)
        ).days / 365.0
        current_t = (
            date.fromisoformat(expiry) - date.fromisoformat(current_date)
        ).days / 365.0
        slices.extend(
            [
                _slice(
                    observation_date=previous_date,
                    expiry=expiry,
                    under_px=previous_under,
                    parameters=previous,
                ),
                _slice(
                    observation_date=current_date,
                    expiry=expiry,
                    under_px=current_under,
                    parameters=_scale_surface(previous, current_t / previous_t),
                ),
            ]
        )

    pair_rows = build_svi_smile_transport_rows(slices)
    daily_rows = build_daily_svi_smile_transport_features(slices)
    assert len(daily_rows) == 4
    assert len({row["candidate_id"] for row in daily_rows}) == 4
    daily = _candidates(daily_rows)
    downside = daily[(STICKY_MONEYNESS, "downside_smile_term_surprise")]
    potential = daily[(STICKY_MONEYNESS, "potential_minimum_transport")]
    assert downside["front_expiry"] == expiries[0]
    assert downside["next_expiry"] == expiries[1]
    assert downside["candidate_success"] is True
    assert downside["candidate_value"] == pytest.approx(
        0.0, abs=1e-14
    )
    assert potential["candidate_success"] is True
    assert potential["candidate_value"] == pytest.approx(
        0.0, abs=1e-15
    )
    assert potential["potential_depth_term_success"] is True
    assert potential["signal_cutoff"] == "D_close"
    assert potential["execution_intent"] == "D_plus_1_or_later"
    assert potential["coordinate_definition"] == "k=ln(strike/UnderPx_proxy)"
    assert potential["under_px_is_trusted_forward"] is False
    assert potential["trusted_forward_available"] is False
    assert potential["forward_relative_minimum_log_moneyness"] is None
    assert potential["forward_relative_minimum_strike_ratio_minus_one"] is None
    assert potential["forward_relative_reason"] == "trusted_forward_unavailable"
    assert potential["research_status"] == "DRAFT_DIAGNOSTIC_ONLY"
    assert potential["pairing_rule"] == "adjacent_observation_dates_exact_same_expiry"

    sticky_strike_pairs = {
        int(row["maturity_rank"]): row
        for row in pair_rows
        if row["transport_model"] == STICKY_STRIKE
    }
    front = sticky_strike_pairs[1]
    nxt = sticky_strike_pairs[2]
    actual_term_ratio = (
        float(front["current_downside_iv_over_atm_minus_one"]) + 1.0
    ) / (float(nxt["current_downside_iv_over_atm_minus_one"]) + 1.0)
    predicted_term_ratio = (
        float(front["predicted_downside_iv_over_atm_minus_one"]) + 1.0
    ) / (float(nxt["predicted_downside_iv_over_atm_minus_one"]) + 1.0)
    sticky_strike_downside = daily[
        (STICKY_STRIKE, "downside_smile_term_surprise")
    ]
    assert sticky_strike_downside["actual_downside_smile_term_ratio"] == pytest.approx(
        actual_term_ratio
    )
    assert sticky_strike_downside[
        "predicted_downside_smile_term_ratio"
    ] == pytest.approx(predicted_term_ratio)
    assert sticky_strike_downside["candidate_value"] == pytest.approx(
        actual_term_ratio / predicted_term_ratio - 1.0
    )

    proxy_return = math.log(current_under / previous_under)
    sticky_strike_potential = daily[
        (STICKY_STRIKE, "potential_minimum_transport")
    ]
    assert sticky_strike_potential[
        "potential_minimum_mean_absolute_error"
    ] == pytest.approx(abs(proxy_return))
    assert sticky_strike_potential[
        "potential_minimum_term_inconsistency"
    ] == pytest.approx(0.0, abs=1e-15)
    assert sticky_strike_potential["candidate_value"] == pytest.approx(
        abs(proxy_return)
    )
    assert sticky_strike_potential["candidate_value"] >= 0.0


def test_expiry_roll_pairs_exact_contract_and_never_substitutes_rank() -> None:
    parameters = SVIParameters(a=0.009, b=0.04, rho=-0.3, m=0.01, sigma=0.15)
    previous_date = "2024-01-11"
    current_date = "2024-01-12"
    expired_front = "2024-01-19"
    surviving_next = "2024-02-16"
    new_next = "2024-03-15"
    slices = [
        _slice(
            observation_date=previous_date,
            expiry=expired_front,
            under_px=40_000.0,
            parameters=parameters,
            cm="previous-front",
        ),
        _slice(
            observation_date=previous_date,
            expiry=surviving_next,
            under_px=40_000.0,
            parameters=parameters,
            cm="previous-next",
        ),
        _slice(
            observation_date=current_date,
            expiry=surviving_next,
            under_px=40_000.0,
            parameters=parameters,
            cm="current-front",
        ),
        _slice(
            observation_date=current_date,
            expiry=new_next,
            under_px=40_000.0,
            parameters=parameters,
            cm="current-next",
        ),
    ]
    pair_rows = build_svi_smile_transport_rows(slices)
    sticky_moneyness = [
        row for row in pair_rows if row["transport_model"] == STICKY_MONEYNESS
    ]

    assert sticky_moneyness[0]["expiry"] == surviving_next
    assert sticky_moneyness[0]["previous_cm"] == "previous-next"
    assert sticky_moneyness[0]["downside_transport_success"] is True
    assert sticky_moneyness[1]["expiry"] == new_next
    assert sticky_moneyness[1]["previous_cm"] is None
    assert (
        sticky_moneyness[1]["downside_transport_reason"]
        == "previous_exact_expiry_unavailable"
    )
    assert all(row["expiry_rank_substitution_applied"] is False for row in pair_rows)
    daily = _candidates(build_daily_svi_smile_transport_features(slices))
    assert (
        daily[(STICKY_MONEYNESS, "downside_smile_term_surprise")][
            "candidate_success"
        ]
        is False
    )


def test_duplicate_current_expiry_keeps_its_rank_as_an_explicit_failure() -> None:
    parameters = SVIParameters(a=0.009, b=0.04, rho=-0.3, m=0.01, sigma=0.15)
    previous_date = "2024-01-08"
    current_date = "2024-01-09"
    front_expiry = "2024-02-16"
    next_expiry = "2024-03-15"
    previous_front = _slice(
        observation_date=previous_date,
        expiry=front_expiry,
        under_px=40_000.0,
        parameters=parameters,
    )
    current_front = _slice(
        observation_date=current_date,
        expiry=front_expiry,
        under_px=40_000.0,
        parameters=parameters,
    )
    duplicate_front = {**current_front, "cm": "duplicate-front"}
    rows = build_svi_smile_transport_rows(
        [
            previous_front,
            _slice(
                observation_date=previous_date,
                expiry=next_expiry,
                under_px=40_000.0,
                parameters=parameters,
            ),
            current_front,
            duplicate_front,
            _slice(
                observation_date=current_date,
                expiry=next_expiry,
                under_px=40_000.0,
                parameters=parameters,
            ),
        ]
    )
    sticky_moneyness = [
        row for row in rows if row["transport_model"] == STICKY_MONEYNESS
    ]
    assert [row["maturity_rank"] for row in sticky_moneyness] == [1, 2]
    assert sticky_moneyness[0]["expiry"] == front_expiry
    assert (
        sticky_moneyness[0]["downside_transport_reason"]
        == "current_exact_expiry_ambiguous"
    )
    assert sticky_moneyness[1]["expiry"] == next_expiry
    assert sticky_moneyness[1]["downside_transport_success"] is True


def test_slice_date_dte_and_maturity_contracts_fail_closed() -> None:
    parameters = SVIParameters(a=0.009, b=0.04, rho=-0.3, m=0.01, sigma=0.15)
    prior = _slice(
        observation_date="2024-01-08",
        expiry="2024-03-15",
        under_px=40_000.0,
        parameters=parameters,
    )
    current = _slice(
        observation_date="2024-01-09",
        expiry="2024-03-15",
        under_px=40_000.0,
        parameters=parameters,
    )
    dte_mismatch = {**current, "dte_days": int(current["dte_days"]) + 1}
    maturity_mismatch = {**current, "maturity_years": 0.5}

    dte_rows = build_svi_smile_transport_rows([prior, dte_mismatch])
    maturity_rows = build_svi_smile_transport_rows([prior, maturity_mismatch])
    assert all(
        row["downside_transport_reason"] == "current_dte_contract_mismatch"
        for row in dte_rows
    )
    assert all(
        row["downside_transport_reason"] == "current_maturity_contract_mismatch"
        for row in maturity_rows
    )

    next_expiry = "2024-04-19"
    missing_front_dte = {**current, "dte_days": None}
    ranked_rows = build_svi_smile_transport_rows(
        [
            prior,
            _slice(
                observation_date="2024-01-08",
                expiry=next_expiry,
                under_px=40_000.0,
                parameters=parameters,
            ),
            missing_front_dte,
            _slice(
                observation_date="2024-01-09",
                expiry=next_expiry,
                under_px=40_000.0,
                parameters=parameters,
            ),
        ]
    )
    sticky_moneyness = [
        row for row in ranked_rows if row["transport_model"] == STICKY_MONEYNESS
    ]
    assert [row["maturity_rank"] for row in sticky_moneyness] == [1, 2]
    assert sticky_moneyness[0]["expiry"] == "2024-03-15"
    assert (
        sticky_moneyness[0]["downside_transport_reason"]
        == "current_date_contract_invalid"
    )
    assert sticky_moneyness[1]["expiry"] == next_expiry
    assert sticky_moneyness[1]["downside_transport_success"] is True


def test_raw_wrapper_requires_nikkei_225_dataset_provenance() -> None:
    with pytest.raises(TypeError, match="dataset_id"):
        build_options_225_smile_transport_rows([])  # type: ignore[call-arg]
    with pytest.raises(ValueError, match=DATASET_ID):
        build_options_225_smile_transport_rows(
            [], dataset_id="derivatives_bars_daily_single_stock_options"
        )
    assert build_options_225_smile_transport_rows([], dataset_id=DATASET_ID) == []


def test_future_surface_mutation_cannot_change_prior_signal_rows() -> None:
    parameters = SVIParameters(a=0.009, b=0.04, rho=-0.3, m=0.01, sigma=0.15)
    expiry = "2024-03-15"
    past = [
        _slice(
            observation_date="2024-01-08",
            expiry=expiry,
            under_px=40_000.0,
            parameters=parameters,
        ),
        _slice(
            observation_date="2024-01-09",
            expiry=expiry,
            under_px=40_100.0,
            parameters=parameters,
        ),
    ]
    before = build_svi_smile_transport_rows(past)
    future = _slice(
        observation_date="2024-01-10",
        expiry=expiry,
        under_px=90_000.0,
        parameters=SVIParameters(a=0.4, b=0.7, rho=0.8, m=-0.2, sigma=0.3),
    )
    after = [
        row
        for row in build_svi_smile_transport_rows([*past, future])
        if row["date"] == "2024-01-09"
    ]
    assert after == before


def test_out_of_band_values_are_null_instead_of_extrapolated() -> None:
    parameters = SVIParameters(a=0.009, b=0.04, rho=-0.2, m=0.0, sigma=0.12)
    rows = build_svi_smile_transport_rows(
        [
            _slice(
                observation_date="2024-01-08",
                expiry="2024-03-15",
                under_px=40_000.0,
                parameters=parameters,
                band=(-0.12, 0.12),
            ),
            _slice(
                observation_date="2024-01-09",
                expiry="2024-03-15",
                under_px=52_000.0,
                parameters=parameters,
                band=(-0.12, 0.12),
            ),
        ]
    )
    by_model = _rows_by_model(rows)
    sticky_strike = by_model[STICKY_STRIKE]
    sticky_moneyness = by_model[STICKY_MONEYNESS]

    assert sticky_strike["downside_transport_success"] is False
    assert sticky_strike["downside_transport_reason"] == "source_coordinate_out_of_fit_band"
    assert sticky_strike["predicted_downside_iv_decimal"] is None
    assert sticky_strike["downside_smile_surprise"] is None
    assert sticky_strike["extrapolation_applied"] is False
    assert sticky_moneyness["downside_transport_success"] is True


def test_out_of_band_minimum_and_single_stock_scope_fail_closed() -> None:
    outside_minimum = SVIParameters(
        a=0.01, b=0.04, rho=0.0, m=0.22, sigma=0.12
    )
    prior = _slice(
        observation_date="2024-01-08",
        expiry="2024-03-15",
        under_px=40_000.0,
        parameters=outside_minimum,
        band=(-0.15, 0.15),
    )
    current = _slice(
        observation_date="2024-01-09",
        expiry="2024-03-15",
        under_px=40_000.0,
        parameters=outside_minimum,
        band=(-0.15, 0.15),
    )
    rows = build_svi_smile_transport_rows([prior, current])
    assert all(row["potential_minimum_transport_success"] is False for row in rows)
    assert all(
        row["potential_minimum_transport_reason"]
        == "current_analytic_minimum_out_of_fit_band"
        for row in rows
    )
    assert all(row["current_minimum_proxy_log_moneyness"] is None for row in rows)

    single_stock_prior = {**prior, "surface_scope": "single_stock_options", "code": "7203"}
    single_stock_current = {
        **current,
        "surface_scope": "single_stock_options",
        "code": "7203",
    }
    denied = build_svi_smile_transport_rows(
        [single_stock_prior, single_stock_current]
    )
    assert all(row["downside_transport_success"] is False for row in denied)
    assert all(
        row["downside_transport_reason"] == "current_surface_scope_denied"
        for row in denied
    )
    assert all(row["single_stock_iv_used"] is False for row in denied)


def test_forward_relative_fields_stay_null_without_trusted_forward() -> None:
    parameters = SVIParameters(a=0.009, b=0.04, rho=-0.3, m=0.01, sigma=0.15)
    rows = build_svi_smile_transport_rows(
        [
            _slice(
                observation_date="2024-01-08",
                expiry="2024-03-15",
                under_px=40_000.0,
                parameters=parameters,
            ),
            _slice(
                observation_date="2024-01-09",
                expiry="2024-03-15",
                under_px=40_100.0,
                parameters=parameters,
            ),
        ]
    )
    assert rows
    for row in rows:
        assert row["coordinate_definition"] == "k=ln(strike/UnderPx_proxy)"
        assert row["under_px_is_trusted_forward"] is False
        assert row["trusted_forward_available"] is False
        assert row["forward_relative_minimum_log_moneyness"] is None
        assert row["forward_relative_minimum_strike_ratio_minus_one"] is None
        assert row["forward_relative_reason"] == "trusted_forward_unavailable"
