"""Comparable performance metrics for bounded personal paper research.

The paper engine deliberately keeps a small execution metric surface.  This
module is the presentation/analysis layer built from the immutable equity and
trade evidence.  It does not participate in strategy selection gates.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean, median, stdev
from typing import Any


PERSONAL_PERFORMANCE_SCHEMA = "personal-performance/v1"
PERSONAL_FOLD_STABILITY_SCHEMA = "personal-fold-stability/v1"
PERSONAL_PERFORMANCE_DELTA_SCHEMA = "personal-performance-delta/v1"
DEFAULT_PERIODS_PER_YEAR = 252.0


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_returns(values: Sequence[float | None]) -> list[float]:
    return [number for value in values if (number := _finite(value)) is not None]


def _sample_std(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return float(stdev(values))


def _compound(values: Sequence[float]) -> float | None:
    if not values:
        return None
    wealth = 1.0
    for value in values:
        wealth *= 1.0 + value
    return _finite(wealth - 1.0)


def _cagr(
    total_return: float | None,
    sessions: int,
    periods_per_year: float,
) -> float | None:
    if total_return is None or sessions <= 0 or 1.0 + total_return <= 0.0:
        return None
    return _finite((1.0 + total_return) ** (periods_per_year / sessions) - 1.0)


def _sharpe(values: Sequence[float], periods_per_year: float) -> float | None:
    sigma = _sample_std(values)
    if sigma is None or sigma == 0.0:
        return None
    return _finite(mean(values) / sigma * math.sqrt(periods_per_year))


def _sortino(values: Sequence[float], periods_per_year: float) -> float | None:
    if not values:
        return None
    downside = math.sqrt(mean(min(value, 0.0) ** 2 for value in values))
    if downside == 0.0:
        return None
    return _finite(mean(values) / downside * math.sqrt(periods_per_year))


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _tail_risk(values: Sequence[float]) -> tuple[float | None, float | None]:
    threshold = _quantile(values, 0.05)
    if threshold is None:
        return None, None
    tail = [value for value in values if value <= threshold]
    # Report positive loss magnitudes. A distribution whose 5th percentile is
    # positive has zero historical loss at this confidence level.
    value_at_risk = max(0.0, -threshold)
    expected_shortfall = max(0.0, -mean(tail)) if tail else value_at_risk
    return _finite(value_at_risk), _finite(expected_shortfall)


def _drawdown(
    equities: Sequence[float],
) -> tuple[float | None, int | None, int | None, bool | None]:
    if not equities:
        return None, None, None, None
    peak_value = equities[0]
    peak_index = 0
    worst = 0.0
    worst_peak_index = 0
    worst_trough_index = 0
    for index, equity in enumerate(equities[1:], start=1):
        if equity > peak_value:
            peak_value = equity
            peak_index = index
        if peak_value <= 0.0:
            continue
        drawdown = 1.0 - equity / peak_value
        if drawdown > worst:
            worst = drawdown
            worst_peak_index = peak_index
            worst_trough_index = index
    if worst == 0.0:
        return 0.0, 0, 0, True
    recovery: int | None = None
    recovery_level = equities[worst_peak_index]
    for index in range(worst_trough_index + 1, len(equities)):
        if equities[index] >= recovery_level:
            recovery = index - worst_trough_index
            break
    return (
        _finite(worst),
        worst_trough_index - worst_peak_index,
        recovery,
        recovery is not None,
    )


def _return_series_from_equity(
    equity_curve: Sequence[Mapping[str, Any]],
    *,
    starting_capital: float,
) -> tuple[list[float], list[str], list[float], int]:
    previous = _finite(starting_capital)
    if previous is None or previous <= 0.0:
        raise ValueError("starting_capital must be positive and finite")
    returns: list[float] = []
    dates: list[str] = []
    equities = [previous]
    invalid = 0
    for row in equity_curve:
        current = _finite(row.get("equity"))
        if current is None or current <= 0.0:
            invalid += 1
            continue
        value = current / previous - 1.0
        if not math.isfinite(value):
            invalid += 1
            continue
        returns.append(value)
        dates.append(str(row.get("date") or ""))
        equities.append(current)
        previous = current
    return returns, dates, equities, invalid


def _monthly_returns(returns: Sequence[float], dates: Sequence[str]) -> list[float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for day, value in zip(dates, returns, strict=True):
        if len(day) >= 7 and day[4] == "-":
            grouped[day[:7]].append(value)
    return [
        compounded
        for month in sorted(grouped)
        if (compounded := _compound(grouped[month])) is not None
    ]


def _series_metrics(
    returns: Sequence[float | None],
    *,
    periods_per_year: float,
    dates: Sequence[str] | None = None,
    equities: Sequence[float] | None = None,
) -> dict[str, Any]:
    values = _clean_returns(returns)
    sessions = len(values)
    total_return = _compound(values)
    annualized_return = _cagr(total_return, sessions, periods_per_year)
    sigma = _sample_std(values)
    annualized_volatility = (
        None if sigma is None else _finite(sigma * math.sqrt(periods_per_year))
    )
    var_95, cvar_95 = _tail_risk(values)
    if equities is None:
        wealth = 1.0
        reconstructed = [wealth]
        for value in values:
            wealth *= 1.0 + value
            reconstructed.append(wealth)
        equities = reconstructed
    (
        max_drawdown,
        drawdown_duration,
        drawdown_recovery,
        drawdown_recovered,
    ) = _drawdown(equities)
    calmar = (
        None
        if annualized_return is None
        or max_drawdown is None
        or max_drawdown == 0.0
        else _finite(annualized_return / max_drawdown)
    )
    monthly = _monthly_returns(values, dates) if dates is not None else []
    active = [value for value in values if value != 0.0]
    downside_deviation = (
        None
        if not values
        else _finite(
            math.sqrt(mean(min(value, 0.0) ** 2 for value in values))
            * math.sqrt(periods_per_year)
        )
    )
    return {
        "sessions": sessions,
        "active_sessions": len(active),
        "total_return_net": total_return,
        "cagr": annualized_return,
        "annualized_volatility": annualized_volatility,
        "annualized_downside_deviation": downside_deviation,
        "annualized_sharpe": _sharpe(values, periods_per_year),
        "annualized_sortino": _sortino(values, periods_per_year),
        "max_drawdown": max_drawdown,
        "max_drawdown_duration_sessions": drawdown_duration,
        "max_drawdown_recovery_sessions": drawdown_recovery,
        "max_drawdown_recovered": drawdown_recovered,
        "calmar_ratio": calmar,
        "best_day_return": max(values) if values else None,
        "worst_day_return": min(values) if values else None,
        "best_month_return": max(monthly) if monthly else None,
        "worst_month_return": min(monthly) if monthly else None,
        "positive_day_rate": (
            None if not values else sum(value > 0.0 for value in values) / sessions
        ),
        "positive_active_day_rate": (
            None
            if not active
            else sum(value > 0.0 for value in active) / len(active)
        ),
        "flat_day_rate": (
            None if not values else sum(value == 0.0 for value in values) / sessions
        ),
        "positive_month_rate": (
            None
            if not monthly
            else sum(value > 0.0 for value in monthly) / len(monthly)
        ),
        "monthly_observations": len(monthly),
        "daily_value_at_risk_95": var_95,
        "daily_conditional_value_at_risk_95": cvar_95,
    }


def _year_metrics(
    returns: Sequence[float],
    dates: Sequence[str],
    *,
    periods_per_year: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for day, value in zip(dates, returns, strict=True):
        if len(day) >= 4 and day[:4].isdigit():
            grouped[day[:4]].append((day, value))
    rows: list[dict[str, Any]] = []
    for year in sorted(grouped):
        pairs = grouped[year]
        values = [value for _day, value in pairs]
        days = [day for day, _value in pairs]
        metrics = _series_metrics(
            values,
            periods_per_year=periods_per_year,
            dates=days,
        )
        rows.append({"year": int(year), **metrics})
    return rows


def summarize_performance(
    *,
    equity_curve: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    starting_capital: float,
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
) -> dict[str, Any]:
    """Compute JSON-safe performance from one immutable paper result."""

    annualization = _finite(periods_per_year)
    if annualization is None or annualization <= 0.0:
        raise ValueError("periods_per_year must be positive and finite")
    returns, dates, equities, invalid = _return_series_from_equity(
        equity_curve,
        starting_capital=starting_capital,
    )
    summary = _series_metrics(
        returns,
        periods_per_year=annualization,
        dates=dates,
        equities=equities,
    )
    capital = float(starting_capital)
    costs = sum(
        cost
        for trade in trades
        if (cost := _finite(trade.get("cost", 0.0))) is not None
    )
    fill_trades = [
        trade
        for trade in trades
        if str(trade.get("side") or "")
        not in {"short_financing", "leverage_financing"}
    ]
    turnover = sum(
        abs(notional)
        for trade in fill_trades
        if (notional := _finite(trade.get("notional", 0.0))) is not None
    )
    cost_return = costs / capital
    turnover_ratio = turnover / capital
    sessions = int(summary["sessions"])
    net_return = summary["total_return_net"]
    estimated_pre_cost_return = (
        None if net_return is None else _finite(net_return + cost_return)
    )
    return {
        "schema_version": PERSONAL_PERFORMANCE_SCHEMA,
        "periods_per_year": annualization,
        "starting_capital": capital,
        **summary,
        "estimated_total_return_pre_cost_additive": estimated_pre_cost_return,
        "pre_cost_estimate_basis": (
            "net_total_return_plus_cost_over_starting_capital; descriptive "
            "cost-drag estimate, not a counterfactual zero-cost equity path"
        ),
        "cost_amount": _finite(costs),
        "cost_return": _finite(cost_return),
        "turnover_one_way_amount": _finite(turnover),
        "turnover_one_way_ratio": _finite(turnover_ratio),
        "turnover_one_way_annualized_ratio": (
            None
            if sessions == 0
            else _finite(turnover_ratio * annualization / sessions)
        ),
        "fill_count": len(fill_trades),
        "round_trip_trade_metrics": {
            "status": "UNAVAILABLE",
            "trade_win_rate": None,
            "profit_factor": None,
            "reason": (
                "execution evidence records fills, not closed round trips; "
                "fill events must not be labelled winning trades"
            ),
        },
        "invalid_equity_observations": invalid,
        "year_metrics": _year_metrics(
            returns,
            dates,
            periods_per_year=annualization,
        ),
    }


def summarize_validation_performance(
    runs: Sequence[Mapping[str, Any]],
    stitched_returns: Sequence[float | None],
    *,
    stitched_dates: Sequence[str] | None = None,
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
) -> dict[str, Any]:
    """Summarize fold stability and the chronological stitched return path."""

    annualization = _finite(periods_per_year)
    if annualization is None or annualization <= 0.0:
        raise ValueError("periods_per_year must be positive and finite")
    performances = [
        performance
        for run in runs
        if isinstance((performance := run.get("performance")), Mapping)
    ]
    clean_stitched = _clean_returns(stitched_returns)
    dates = (
        list(stitched_dates)
        if stitched_dates is not None and len(stitched_dates) == len(clean_stitched)
        else None
    )
    stitched = {
        "schema_version": PERSONAL_PERFORMANCE_SCHEMA,
        "periods_per_year": annualization,
        "starting_capital": None,
        **_series_metrics(
            clean_stitched,
            periods_per_year=annualization,
            dates=dates,
        ),
    }
    total_cost = sum(
        value
        for performance in performances
        if (value := _finite(performance.get("cost_amount"))) is not None
    )
    total_turnover = sum(
        value
        for performance in performances
        if (value := _finite(performance.get("turnover_one_way_amount"))) is not None
    )
    cost_return = sum(
        value
        for performance in performances
        if (value := _finite(performance.get("cost_return"))) is not None
    )
    turnover_ratio = sum(
        value
        for performance in performances
        if (value := _finite(performance.get("turnover_one_way_ratio"))) is not None
    )
    sessions = int(stitched["sessions"])
    stitched.update(
        {
            "estimated_total_return_pre_cost_additive": (
                None
                if stitched["total_return_net"] is None
                else _finite(stitched["total_return_net"] + cost_return)
            ),
            "pre_cost_estimate_basis": (
                "stitched_net_total_return_plus_sum_of_fold_cost_ratios; "
                "descriptive only"
            ),
            "cost_amount": _finite(total_cost),
            "cost_return": _finite(cost_return),
            "turnover_one_way_amount": _finite(total_turnover),
            "turnover_one_way_ratio": _finite(turnover_ratio),
            "turnover_one_way_annualized_ratio": (
                None
                if sessions == 0
                else _finite(turnover_ratio * annualization / sessions)
            ),
            "fill_count": sum(int(run.get("fills", 0)) for run in runs),
            "invalid_equity_observations": sum(
                int(performance.get("invalid_equity_observations", 0))
                for performance in performances
            ),
            "year_metrics": (
                []
                if dates is None
                else _year_metrics(
                    clean_stitched,
                    dates,
                    periods_per_year=annualization,
                )
            ),
        }
    )
    fold_returns = _clean_returns(
        [performance.get("total_return_net") for performance in performances]
    )
    fold_sharpes = _clean_returns(
        [performance.get("annualized_sharpe") for performance in performances]
    )
    fold_drawdowns = _clean_returns(
        [performance.get("max_drawdown") for performance in performances]
    )
    fold_cagrs = _clean_returns(
        [performance.get("cagr") for performance in performances]
    )
    fold_sortinos = _clean_returns(
        [performance.get("annualized_sortino") for performance in performances]
    )
    fold_calmars = _clean_returns(
        [performance.get("calmar_ratio") for performance in performances]
    )
    return {
        "schema_version": PERSONAL_FOLD_STABILITY_SCHEMA,
        "fold_count": len(runs),
        "evaluated_fold_count": len(performances),
        "positive_folds": sum(value > 0.0 for value in fold_returns),
        "positive_fold_rate": (
            None
            if not fold_returns
            else sum(value > 0.0 for value in fold_returns) / len(fold_returns)
        ),
        "fold_total_return_mean": (
            None if not fold_returns else _finite(mean(fold_returns))
        ),
        "fold_total_return_median": (
            None if not fold_returns else _finite(median(fold_returns))
        ),
        "fold_total_return_std": _sample_std(fold_returns),
        "fold_total_return_best": max(fold_returns) if fold_returns else None,
        "fold_total_return_worst": min(fold_returns) if fold_returns else None,
        "fold_sharpe_mean": (
            None if not fold_sharpes else _finite(mean(fold_sharpes))
        ),
        "fold_sharpe_std": _sample_std(fold_sharpes),
        "fold_sharpe_worst": min(fold_sharpes) if fold_sharpes else None,
        "fold_cagr_mean": None if not fold_cagrs else _finite(mean(fold_cagrs)),
        "fold_cagr_std": _sample_std(fold_cagrs),
        "fold_cagr_worst": min(fold_cagrs) if fold_cagrs else None,
        "fold_sortino_mean": (
            None if not fold_sortinos else _finite(mean(fold_sortinos))
        ),
        "fold_sortino_std": _sample_std(fold_sortinos),
        "fold_sortino_worst": min(fold_sortinos) if fold_sortinos else None,
        "fold_calmar_mean": (
            None if not fold_calmars else _finite(mean(fold_calmars))
        ),
        "fold_calmar_worst": min(fold_calmars) if fold_calmars else None,
        "fold_max_drawdown_mean": (
            None if not fold_drawdowns else _finite(mean(fold_drawdowns))
        ),
        "fold_max_drawdown_worst": max(fold_drawdowns) if fold_drawdowns else None,
        "aggregation_note": (
            "stitched returns preserve fold order but reset capital at each fold; "
            "cost and turnover ratios are sums of fold ratios"
        ),
        "stitched_performance": stitched,
    }


_DELTA_FIELDS = (
    "total_return_net",
    "cagr",
    "annualized_volatility",
    "annualized_sharpe",
    "annualized_sortino",
    "max_drawdown",
    "calmar_ratio",
    "cost_return",
    "turnover_one_way_annualized_ratio",
)


def performance_delta(
    baseline: Mapping[str, Any] | None,
    observed: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return observed-minus-baseline deltas for the comparison surface."""

    if baseline is None or observed is None:
        return None
    values: dict[str, float | None] = {}
    for field in _DELTA_FIELDS:
        left = _finite(baseline.get(field))
        right = _finite(observed.get(field))
        values[field] = None if left is None or right is None else _finite(right - left)
    return {
        "schema_version": PERSONAL_PERFORMANCE_DELTA_SCHEMA,
        "basis": "observed_minus_validation_stitched",
        **values,
    }


__all__ = [
    "DEFAULT_PERIODS_PER_YEAR",
    "PERSONAL_FOLD_STABILITY_SCHEMA",
    "PERSONAL_PERFORMANCE_DELTA_SCHEMA",
    "PERSONAL_PERFORMANCE_SCHEMA",
    "performance_delta",
    "summarize_performance",
    "summarize_validation_performance",
]
