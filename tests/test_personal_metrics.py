"""Comparable metrics for personal paper evidence."""

from __future__ import annotations

import json

import pytest

from research.personal_metrics import (
    PERSONAL_FOLD_STABILITY_SCHEMA,
    PERSONAL_PERFORMANCE_SCHEMA,
    performance_delta,
    summarize_performance,
    summarize_validation_performance,
)


def test_comprehensive_metrics_are_normalized_and_json_finite() -> None:
    performance = summarize_performance(
        starting_capital=100.0,
        equity_curve=[
            {"date": "2024-01-30", "equity": 110.0},
            {"date": "2024-01-31", "equity": 99.0},
            {"date": "2024-02-01", "equity": 108.9},
            {"date": "2024-02-02", "equity": 87.12},
            {"date": "2024-02-05", "equity": 95.832},
        ],
        trades=[
            {"side": "buy", "notional": 100.0, "cost": 1.0},
            {"side": "sell", "notional": -50.0, "cost": 0.5},
            {
                "side": "short_financing",
                "notional": 1_000_000.0,
                "cost": 2.0,
            },
        ],
    )

    assert performance["schema_version"] == PERSONAL_PERFORMANCE_SCHEMA
    assert performance["sessions"] == 5
    assert performance["total_return_net"] == pytest.approx(-0.04168)
    assert performance["estimated_total_return_pre_cost_additive"] == pytest.approx(
        -0.00668
    )
    assert "descriptive" in performance["pre_cost_estimate_basis"]
    assert performance["cost_amount"] == pytest.approx(3.5)
    assert performance["cost_return"] == pytest.approx(0.035)
    assert performance["turnover_one_way_amount"] == pytest.approx(150.0)
    assert performance["turnover_one_way_ratio"] == pytest.approx(1.5)
    assert performance["turnover_one_way_annualized_ratio"] == pytest.approx(75.6)
    assert performance["max_drawdown"] == pytest.approx(0.208)
    assert performance["max_drawdown_duration_sessions"] == 3
    assert performance["max_drawdown_recovery_sessions"] is None
    assert performance["max_drawdown_recovered"] is False
    assert performance["best_day_return"] == pytest.approx(0.1)
    assert performance["worst_day_return"] == pytest.approx(-0.2)
    assert performance["positive_day_rate"] == pytest.approx(0.6)
    assert performance["positive_active_day_rate"] == pytest.approx(0.6)
    assert performance["flat_day_rate"] == pytest.approx(0.0)
    assert performance["positive_month_rate"] == pytest.approx(0.0)
    assert performance["daily_value_at_risk_95"] >= 0.0
    assert performance["daily_conditional_value_at_risk_95"] >= 0.0
    assert performance["year_metrics"][0]["year"] == 2024
    assert performance["round_trip_trade_metrics"]["status"] == "UNAVAILABLE"
    assert performance["round_trip_trade_metrics"]["trade_win_rate"] is None
    json.dumps(performance, allow_nan=False)


def test_drawdown_duration_and_recovery_are_session_counts() -> None:
    performance = summarize_performance(
        starting_capital=100.0,
        equity_curve=[
            {"date": "2024-01-01", "equity": 120.0},
            {"date": "2024-01-02", "equity": 90.0},
            {"date": "2024-01-03", "equity": 120.0},
        ],
        trades=[],
    )

    assert performance["max_drawdown"] == pytest.approx(0.25)
    assert performance["max_drawdown_duration_sessions"] == 1
    assert performance["max_drawdown_recovery_sessions"] == 1
    assert performance["max_drawdown_recovered"] is True


def test_fold_stability_stitches_returns_and_deltas_without_changing_gates() -> None:
    runs = [
        {
            "fills": 3,
            "performance": {
                "total_return_net": 0.10,
                "annualized_sharpe": 1.0,
                "max_drawdown": 0.10,
                "cost_amount": 2.0,
                "cost_return": 0.002,
                "turnover_one_way_amount": 100.0,
                "turnover_one_way_ratio": 0.1,
                "invalid_equity_observations": 0,
            },
        },
        {
            "fills": 4,
            "performance": {
                "total_return_net": -0.05,
                "annualized_sharpe": -0.5,
                "max_drawdown": 0.20,
                "cost_amount": 3.0,
                "cost_return": 0.003,
                "turnover_one_way_amount": 150.0,
                "turnover_one_way_ratio": 0.15,
                "invalid_equity_observations": 0,
            },
        },
    ]

    stability = summarize_validation_performance(
        runs,
        [0.10, -0.05],
        stitched_dates=["2023-12-29", "2024-01-04"],
    )
    stitched = stability["stitched_performance"]

    assert stability["schema_version"] == PERSONAL_FOLD_STABILITY_SCHEMA
    assert stability["fold_count"] == 2
    assert stability["positive_folds"] == 1
    assert stability["positive_fold_rate"] == pytest.approx(0.5)
    assert stability["fold_total_return_worst"] == pytest.approx(-0.05)
    assert stability["fold_max_drawdown_worst"] == pytest.approx(0.20)
    assert stitched["total_return_net"] == pytest.approx(0.045)
    assert stitched["cost_amount"] == pytest.approx(5.0)
    assert stitched["cost_return"] == pytest.approx(0.005)
    assert stitched["turnover_one_way_ratio"] == pytest.approx(0.25)
    assert stitched["fill_count"] == 7
    assert stitched["positive_month_rate"] == pytest.approx(0.5)
    assert [row["year"] for row in stitched["year_metrics"]] == [2023, 2024]

    delta = performance_delta(
        stitched,
        {**stitched, "annualized_sharpe": 0.25, "max_drawdown": 0.30},
    )
    assert delta is not None
    expected_sharpe_delta = (
        None
        if stitched["annualized_sharpe"] is None
        else 0.25 - stitched["annualized_sharpe"]
    )
    assert delta["annualized_sharpe"] == pytest.approx(expected_sharpe_delta)
    assert delta["max_drawdown"] == pytest.approx(
        0.30 - stitched["max_drawdown"]
    )
    json.dumps({"stability": stability, "delta": delta}, allow_nan=False)


def test_degenerate_returns_use_none_instead_of_nan_or_infinity() -> None:
    performance = summarize_performance(
        starting_capital=100.0,
        equity_curve=[
            {"date": "2024-01-01", "equity": 100.0},
            {"date": "2024-01-02", "equity": 100.0},
        ],
        trades=[],
    )

    assert performance["annualized_sharpe"] is None
    assert performance["annualized_sortino"] is None
    assert performance["calmar_ratio"] is None
    assert performance["max_drawdown_recovered"] is True
    assert performance["positive_active_day_rate"] is None
    json.dumps(performance, allow_nan=False)
