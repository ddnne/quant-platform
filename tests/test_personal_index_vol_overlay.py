"""Focused invariants for the predeclared index-volatility overlay core."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from research.personal_index_vol_overlay import (
    BASE_SLEEVE_ID,
    BASE_UNIVERSE_ID,
    IndexVolOverlayObservation,
    ONE_WAY_COST_RATE,
    OVERLAY_CANDIDATES,
    evaluate_index_vol_overlays,
)


def _panel(
    count: int = 150,
    *,
    beta: float = 4.0,
) -> tuple[list[IndexVolOverlayObservation], list[str]]:
    start = date(2024, 1, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(count)]
    proxy_returns = [0.0] + [
        (0.001 + (index % 5) * 0.0001) * (1.0 if index % 2 else -1.0)
        for index in range(1, count)
    ]
    closes = [100.0]
    for proxy_return in proxy_returns[1:]:
        closes.append(closes[-1] * (1.0 + proxy_return))
    rows = [
        IndexVolOverlayObservation(
            date=day,
            base_sleeve_return=beta * proxy_returns[index],
            topix_cash_close=closes[index],
            n225_base_vol=20.0,
            n225_atm_iv=20.0,
            topix_realized_vol_20=10.0,
            n225_front_atm_iv=30.0,
            n225_next_atm_iv=20.0,
            n225_front_downside_wing_iv=40.0,
            n225_next_downside_wing_iv=20.0,
            svi_equivalent_atm_term_ratio=1.45,
            svi_equivalent_downside_wing_term_ratio=1.90,
        )
        for index, day in enumerate(dates)
    ]
    return rows, dates


def _by_id(report: dict, candidate_id: str) -> dict:
    return next(
        candidate
        for candidate in report["candidates"]
        if candidate["candidate_id"] == candidate_id
    )


def test_scope_is_frozen_to_one_sleeve_four_index_vol_candidates() -> None:
    rows, dates = _panel()
    report = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    fields = set(IndexVolOverlayObservation.__dataclass_fields__)
    assert not any("stock" in field and "iv" in field for field in fields)
    assert report["base_sleeve"]["strategy_id"] == BASE_SLEEVE_ID
    assert report["base_sleeve"]["universe_id"] == BASE_UNIVERSE_ID
    assert report["base_sleeve"]["single_stock_option_iv"] == (
        "EXCLUDED_FROM_INPUT_SURFACE"
    )
    assert len(OVERLAY_CANDIDATES) == len(report["candidates"]) == 4
    assert report["candidate_policy"]["post_result_selection"] == "NOT_PERFORMED"
    assert report["candidate_policy"]["ranking"] is None
    assert report["candidate_policy"]["candidate_order"] == [
        candidate.candidate_id for candidate in OVERLAY_CANDIDATES
    ]
    assert report["topix_proxy"]["role"] == "NON_EXECUTABLE_HEDGE_APPROXIMATION"
    assert report["topix_proxy"]["etf_fill_claim"] is False


def test_ratio_scale_beta_cap_and_d_dplus1_dplus2_timing() -> None:
    rows, dates = _panel(beta=4.0)
    # A sub-one term ratio must not lever the sleeve above 1.0.
    rows[130] = replace(rows[130], n225_front_atm_iv=10.0)
    report = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    base = _by_id(report, "n225_basevol_10_over_60_defensive_v1")
    atm = _by_id(report, "n225_observed_front_over_next_atm_v1")
    wing = _by_id(report, "n225_observed_downside_wing_front_over_next_v1")

    base_day = base["daily_path"][0]
    assert base_day["feature_ratio_x"] == pytest.approx(1.0)
    assert base_day["gross_scale"] == pytest.approx(1.0)
    assert base_day["estimated_beta"] == pytest.approx(4.0)
    assert base_day["topix_hedge_weight"] == pytest.approx(-1.5)
    assert base_day["signal_date"] == dates[130]
    assert base_day["rebalance_date"] == dates[131]
    assert base_day["pnl_date"] == dates[132]
    assert base_day["beta_window_last_return_date"] == dates[130]

    assert atm["daily_path"][0]["feature_ratio_x"] == pytest.approx(0.5)
    assert atm["daily_path"][0]["gross_scale"] == pytest.approx(1.0)
    assert wing["daily_path"][0]["feature_ratio_x"] == pytest.approx(2.0)
    assert wing["daily_path"][0]["gross_scale"] == pytest.approx(0.5)
    assert all(
        0.5 <= candidate["daily_path"][0]["gross_scale"] <= 1.0
        for candidate in report["candidates"]
    )


def test_ten_basis_point_turnover_and_terminal_close_are_in_performance() -> None:
    rows, dates = _panel(beta=4.0)
    report = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
        starting_capital=1_000_000.0,
    )
    result = _by_id(report, "n225_observed_downside_wing_front_over_next_v1")
    path = result["daily_path"][0]
    performance = result["performance"]

    assert path["sleeve_turnover_one_way"] == pytest.approx(0.5)
    assert path["topix_proxy_turnover_one_way"] == pytest.approx(1.5)
    assert path["rebalance_cost_amount"] == pytest.approx(
        1_000_000.0 * ONE_WAY_COST_RATE * 2.0
    )
    assert path["terminal_close"] is True
    assert path["terminal_turnover_one_way"] == pytest.approx(2.0)
    assert path["terminal_close_cost_amount"] > 0.0
    assert performance["cost_amount"] == pytest.approx(
        path["rebalance_cost_amount"] + path["terminal_close_cost_amount"]
    )
    assert performance["fill_count"] == 4
    assert performance["schema_version"] == "personal-performance/v1"
    # One return observation deliberately preserves undefined dispersion ratios.
    assert performance["annualized_sharpe"] is None
    assert performance["annualized_volatility"] is None
    json.dumps(report, allow_nan=False)


def test_future_mutation_cannot_change_signal_or_beta() -> None:
    rows, dates = _panel(beta=1.25)
    original = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    mutated = list(rows)
    mutated[131] = replace(
        mutated[131],
        topix_cash_close=mutated[131].topix_cash_close * 20.0,
        n225_base_vol=999.0,
        n225_front_atm_iv=999.0,
    )
    mutated[132] = replace(
        mutated[132],
        topix_cash_close=mutated[132].topix_cash_close / 20.0,
        base_sleeve_return=-0.40,
        n225_next_downside_wing_iv=999.0,
    )
    changed = evaluate_index_vol_overlays(
        mutated,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    for candidate_id in [candidate.candidate_id for candidate in OVERLAY_CANDIDATES]:
        before = _by_id(original, candidate_id)["daily_path"][0]
        after = _by_id(changed, candidate_id)["daily_path"][0]
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
    assert _by_id(changed, OVERLAY_CANDIDATES[0].candidate_id)["performance"] != (
        _by_id(original, OVERLAY_CANDIDATES[0].candidate_id)["performance"]
    )


def test_missing_required_observation_is_not_evaluated_and_never_filled() -> None:
    rows, dates = _panel()
    rows[130] = replace(rows[130], n225_front_atm_iv=None)
    report = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    atm = _by_id(report, "n225_observed_front_over_next_atm_v1")

    assert report["status"] == "NOT_EVALUATED"
    assert atm["status"] == "NOT_EVALUATED"
    assert atm["reason"] == "missing_required_row_no_forward_fill"
    assert atm["missing_required_rows"] == [
        {"date": dates[130], "reason": "observed_atm_term_row_missing"}
    ]
    assert atm["daily_path"] == []
    assert atm["performance"] is None
    assert _by_id(report, "n225_observed_downside_wing_front_over_next_v1")[
        "status"
    ] == "EVALUATED"


def test_beta_requires_63_returns_and_uses_at_most_126() -> None:
    rows, dates = _panel()
    too_early = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[62],
        signal_end=dates[62],
    )
    observed = _by_id(too_early, "n225_observed_front_over_next_atm_v1")
    assert observed["status"] == "NOT_EVALUATED"
    assert observed["missing_required_rows"] == [
        {"date": dates[62], "reason": "beta_min_63_returns_unavailable"}
    ]

    enough = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[63],
        signal_end=dates[63],
    )
    observed_day = _by_id(
        enough, "n225_observed_front_over_next_atm_v1"
    )["daily_path"][0]
    assert observed_day["beta_observations"] == 63

    long_window = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    assert _by_id(
        long_window, "n225_observed_front_over_next_atm_v1"
    )["daily_path"][0]["beta_observations"] == 126


def test_svi_equivalents_are_diagnostic_only_and_cannot_change_results() -> None:
    rows, dates = _panel()
    original = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )
    changed_rows = list(rows)
    changed_rows[130] = replace(
        changed_rows[130],
        svi_equivalent_atm_term_ratio=-999.0,
        svi_equivalent_downside_wing_term_ratio=999.0,
    )
    changed = evaluate_index_vol_overlays(
        changed_rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    assert changed["candidates"] == original["candidates"]
    assert changed["candidate_policy"] == original["candidate_policy"]
    diagnostics = changed["svi_equivalent_diagnostics"]
    assert diagnostics["role"] == "DIAGNOSTIC_ONLY_NOT_RANKED"
    assert diagnostics["used_in_signals"] is False
    assert diagnostics["used_in_performance"] is False
    assert diagnostics["rows"][0]["svi_equivalent_atm_term_ratio"] == -999.0


def test_missing_pnl_proxy_row_fails_all_candidates_without_partial_path() -> None:
    rows, dates = _panel()
    rows[132] = replace(rows[132], topix_cash_close=None)
    report = evaluate_index_vol_overlays(
        rows,
        signal_start=dates[130],
        signal_end=dates[130],
    )

    assert all(
        candidate["status"] == "NOT_EVALUATED"
        for candidate in report["candidates"]
    )
    assert all(candidate["performance"] is None for candidate in report["candidates"])
    assert all(candidate["daily_path"] == [] for candidate in report["candidates"])
    assert all(
        candidate["missing_required_rows"] == [
            {"date": dates[132], "reason": "topix_cash_return_missing"}
        ]
        for candidate in report["candidates"]
    )
