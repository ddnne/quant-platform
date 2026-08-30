"""Focused invariants for observed and raw-SVI Nikkei 225 smile features."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from research.options_225_smile_features import (
    OPTIONS_225_SMILE_FEATURE_VERSION,
    OPTIONS_225_SMILE_SOURCE_DATASET_ID,
    SVIParameters,
    SmileFitConfig,
    build_daily_options_225_smile_features,
    build_options_225_smile_slices,
    fit_raw_svi,
    svi_butterfly_g,
    svi_total_variance,
)


def _chain_from_svi(
    *,
    observation_date: str = "2024-01-10",
    dte_days: int = 65,
    cm: str = "2024-03",
    under_px: float = 40_000.0,
    parameters: SVIParameters = SVIParameters(
        a=0.006, b=0.035, rho=-0.32, m=0.015, sigma=0.14
    ),
    ks: tuple[float, ...] = (
        -0.28,
        -0.23,
        -0.18,
        -0.14,
        -0.10,
        -0.05,
        0.0,
        0.05,
        0.10,
        0.14,
        0.18,
        0.23,
        0.28,
    ),
    iv_scale: float = 1.0,
    settlement: str = "002",
) -> list[dict]:
    expiry = (date.fromisoformat(observation_date) + timedelta(days=dte_days)).isoformat()
    maturity = dte_days / 365.0
    rows: list[dict] = []
    for index, k in enumerate(ks):
        strike = under_px * math.exp(k)
        iv_decimal = math.sqrt(svi_total_variance(k, parameters) / maturity) * iv_scale
        # Equal weighting of the robust put/call medians recovers the smile.
        for pc, offset in (("1", -0.001), ("2", 0.001)):
            rows.append(
                {
                    "Date": observation_date,
                    "Code": f"{cm}-{index}-{pc}",
                    "Strike": strike,
                    "PCDiv": pc,
                    "CM": cm,
                    "LTD": (date.fromisoformat(expiry) - timedelta(days=1)).isoformat(),
                    "SQD": expiry,
                    "UnderPx": under_px,
                    "IV": (iv_decimal + offset * iv_scale) * 100.0,
                    "BaseVol": 20.0,
                    "EmMrgnTrgDiv": settlement,
                    "Vo": 10.0,
                    "OI": 100.0,
                }
            )
    return rows


def test_raw_svi_synthetic_recovery_is_deterministic_and_arbitrage_checked():
    expected = SVIParameters(a=0.006, b=0.035, rho=-0.32, m=0.015, sigma=0.14)
    maturity = 65 / 365.0
    ks = [-0.28, -0.23, -0.18, -0.14, -0.10, -0.05, 0.0, 0.05, 0.10, 0.14, 0.18, 0.23, 0.28]
    ivs = [math.sqrt(svi_total_variance(k, expected) / maturity) for k in ks]

    first = fit_raw_svi(ks, ivs, maturity)
    second = fit_raw_svi(ks, ivs, maturity)

    assert first == second
    assert first.success is True
    assert first.reason == "ok"
    assert first.parameters is not None
    assert first.parameters.a == pytest.approx(expected.a, abs=2e-5)
    assert first.parameters.b == pytest.approx(expected.b, rel=0.01)
    assert first.parameters.rho == pytest.approx(expected.rho, abs=0.01)
    assert first.parameters.m == pytest.approx(expected.m, abs=0.002)
    assert first.parameters.sigma == pytest.approx(expected.sigma, abs=0.004)
    assert first.rmse_iv_decimal is not None
    assert first.rmse_iv_decimal < 1e-5
    assert first.min_sampled_butterfly_g is not None
    assert first.min_sampled_butterfly_g >= 0.0
    assert min(svi_butterfly_g(k, first.parameters) for k in ks) >= 0.0


def test_sparse_and_extreme_slices_fail_closed_without_features():
    sparse = _chain_from_svi(
        observation_date="2024-01-10",
        ks=(-0.15, -0.08, 0.0, 0.08, 0.15),
    )
    extreme = _chain_from_svi(observation_date="2024-01-11")
    for row in extreme:
        row["IV"] = 900.0

    slices = build_options_225_smile_slices(
        sparse + extreme, dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID
    )
    assert len(slices) == 2
    assert {row["fit_reason"] for row in slices} == {"insufficient_unique_strikes"}
    assert all(row["fit_success"] is False for row in slices)
    assert all("svi_rr_over_atm" not in row for row in slices)
    assert all(row["ffill_applied"] is False for row in slices)
    assert all(row["interpolation_applied"] is False for row in slices)

    daily = build_daily_options_225_smile_features(
        sparse + extreme, dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID
    )
    assert [row["date"] for row in daily] == ["2024-01-10", "2024-01-11"]
    assert all(row["fit_reason"] == "insufficient_unique_strikes" for row in daily)
    assert all(row["fit_success"] is False for row in daily)


def test_observed_ratios_survive_rejected_svi_shape() -> None:
    arbitrage_shape = SVIParameters(
        a=0.001, b=0.1, rho=-0.9, m=0.0, sigma=0.02
    )
    slices = build_options_225_smile_slices(
        _chain_from_svi(parameters=arbitrage_shape),
        dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID,
    )

    assert len(slices) == 1
    assert slices[0]["fit_success"] is False
    assert (
        slices[0]["fit_reason"]
        == "spot_proxy_butterfly_shape_violation"
    )
    assert slices[0]["observed_feature_success"] is True
    assert slices[0]["observed_rr_over_atm"] is not None
    assert slices[0]["observed_bf_over_atm"] is not None
    assert "svi_rr_over_atm" not in slices[0]


def test_failed_front_is_not_replaced_by_a_later_valid_maturity() -> None:
    front = _chain_from_svi(
        dte_days=30,
        cm="2024-02",
        ks=(-0.15, -0.08, 0.0, 0.08, 0.15),
    )
    next_rows = _chain_from_svi(dte_days=65, cm="2024-03")
    later = _chain_from_svi(dte_days=120, cm="2024-05")

    daily = build_daily_options_225_smile_features(
        front + next_rows + later,
        dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID,
    )

    assert len(daily) == 1
    assert daily[0]["cm"] == "2024-02"
    assert daily[0]["fit_success"] is False
    assert daily[0]["fit_reason"] == "insufficient_unique_strikes"
    assert daily[0]["next_cm"] == "2024-03"
    assert daily[0]["fit_scope"] == "chronological_front_eligible_maturity"
    assert daily[0]["svi_atm_short_over_next_minus_one"] is None
    assert daily[0]["observed_atm_short_over_next_minus_one"] is not None


def test_exact_but_butterfly_arbitrage_surface_is_rejected():
    parameters = SVIParameters(a=0.001, b=0.1, rho=-0.9, m=0.0, sigma=0.02)
    ks = [-0.30, -0.25, -0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
    maturity = 0.2
    ivs = [math.sqrt(svi_total_variance(k, parameters) / maturity) for k in ks]

    fit = fit_raw_svi(ks, ivs, maturity)

    assert fit.success is False
    assert fit.reason == "spot_proxy_butterfly_shape_violation"
    assert fit.parameters is None
    assert fit.rmse_iv_decimal == pytest.approx(0.0, abs=1e-12)
    assert fit.min_sampled_butterfly_g is not None
    assert fit.min_sampled_butterfly_g < 0.0


def test_normalized_smile_features_are_invariant_to_uniform_iv_scaling():
    base = build_daily_options_225_smile_features(
        _chain_from_svi(), dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID
    )
    scaled = build_daily_options_225_smile_features(
        _chain_from_svi(iv_scale=1.6),
        dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID,
    )
    assert len(base) == len(scaled) == 1
    assert base[0]["fit_success"] is scaled[0]["fit_success"] is True

    invariant_fields = (
        "observed_rr_over_atm",
        "observed_bf_over_atm",
        "svi_log_left_right_slope_ratio",
        "svi_atm_normalized_curvature",
        "svi_rr_over_atm",
        "svi_bf_over_atm",
    )
    for field in invariant_fields:
        assert scaled[0][field] == pytest.approx(base[0][field], abs=2e-6)
    assert scaled[0]["svi_atm_iv_decimal"] == pytest.approx(
        1.6 * base[0]["svi_atm_iv_decimal"], rel=2e-6
    )


def test_real_shaped_two_maturity_fixture_emits_observed_and_term_ratios():
    front_params = SVIParameters(
        a=0.0075, b=0.042, rho=-0.42, m=0.01, sigma=0.16
    )
    next_params = SVIParameters(
        a=0.014, b=0.032, rho=-0.28, m=0.005, sigma=0.20
    )
    real_grid = tuple(
        math.log(strike / 40_000.0)
        for strike in (
            31_000,
            32_000,
            34_000,
            36_000,
            38_000,
            39_000,
            40_000,
            41_000,
            42_000,
            44_000,
            46_000,
            48_000,
            50_000,
        )
    )
    rows = _chain_from_svi(
        dte_days=30,
        cm="2024-02",
        parameters=front_params,
        ks=real_grid,
    ) + _chain_from_svi(
        dte_days=93,
        cm="2024-04",
        parameters=next_params,
        ks=real_grid,
    )
    # A non-settlement quote must not contaminate the preferred settlement set.
    bad = dict(rows[0])
    bad["Code"] = "NON_SETTLEMENT_OUTLIER"
    bad["IV"] = 250.0
    bad["EmMrgnTrgDiv"] = "001"
    rows.append(bad)

    slices = build_options_225_smile_slices(
        rows, dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID
    )
    assert len(slices) == 2
    assert all(row["fit_success"] is True for row in slices)
    assert all(row["settlement_preference"] == "002" for row in slices)
    assert all(row["observed_feature_success"] is True for row in slices)
    assert all(row["n_paired_pc_strikes"] == len(real_grid) for row in slices)

    daily = build_daily_options_225_smile_features(
        rows, dataset_id=OPTIONS_225_SMILE_SOURCE_DATASET_ID
    )
    assert len(daily) == 1
    result = daily[0]
    assert result["version"] == OPTIONS_225_SMILE_FEATURE_VERSION
    assert result["cm"] == "2024-02"
    assert result["next_cm"] == "2024-04"
    assert result["next_dte_days"] == 93
    assert result["n_valid_maturity_slices"] == 2
    assert result["svi_atm_short_over_next_minus_one"] is not None
    assert result["svi_curvature_short_over_next_minus_one"] is not None
    assert result["svi_left_right_slope_ratio_short_over_next_minus_one"] is not None
    assert result["svi_rr_over_atm_short_minus_next"] is not None
    assert result["svi_bf_over_atm_short_minus_next"] is not None
    assert result["observed_atm_short_over_next_minus_one"] is not None
    assert result["moneyness_proxy"] == "under_px_not_forward"
    assert result["forward_adjustment_applied"] is False
    assert result["ffill_applied"] is False
    assert result["interpolation_applied"] is False
    assert result["invented_strikes"] is False


def test_config_rejects_unbounded_or_underspecified_surfaces():
    with pytest.raises(ValueError, match="DTE"):
        SmileFitConfig(min_dte_days=0)
    with pytest.raises(ValueError, match="min_unique_strikes"):
        SmileFitConfig(min_unique_strikes=4)
    with pytest.raises(ValueError, match="target log-moneyness"):
        SmileFitConfig(target_abs_log_moneyness=0.4)


def test_smile_builders_require_explicit_nikkei_225_dataset_provenance():
    with pytest.raises(TypeError, match="dataset_id"):
        build_options_225_smile_slices([])  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="dataset_id"):
        build_daily_options_225_smile_features([])  # type: ignore[call-arg]
    with pytest.raises(ValueError, match=OPTIONS_225_SMILE_SOURCE_DATASET_ID):
        build_options_225_smile_slices(
            [], dataset_id="derivatives_bars_daily_single_stock_options"
        )
