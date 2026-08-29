"""Predeclared Nikkei-225 volatility overlays for one frozen stock sleeve.

This module is deliberately a small, pure-Python research core.  It consumes
daily observations that were prepared elsewhere and neither reads storage nor
selects a strategy after seeing results.  Listed-option volatility is only for
the Nikkei 225.  The stock sleeve may use price-based realised volatility, but
single-stock option IV is not part of this input surface.

Timing is fixed and causal: a signal observed at the close of D is rebalanced
at the close of D+1 and first earns the D+1-to-D+2 close return.  Missing
required observations make that candidate NOT_EVALUATED; values are never
forward-filled.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from statistics import mean, median
from typing import Any, Final, Sequence

from research.personal_metrics import summarize_performance


PERSONAL_INDEX_VOL_OVERLAY_SCHEMA: Final = "personal-index-vol-overlay/v1"
BASE_SLEEVE_ID: Final = "personal_sector_balanced_four_factor_v1_ls"
BASE_UNIVERSE_ID: Final = "topix_all"
TOPIX_PROXY_DATASET: Final = "indices_bars_daily_topix"
ONE_WAY_COST_RATE: Final = 0.001  # 10 bp on sleeve and proxy turnover.
BETA_LOOKBACK_RETURNS: Final = 126
BETA_MIN_RETURNS: Final = 63
MAX_ABS_TOPIX_HEDGE: Final = 1.5


@dataclass(frozen=True, slots=True)
class IndexVolOverlayObservation:
    """One session of strictly index-level volatility and sleeve evidence.

    ``base_sleeve_return`` is the frozen stock sleeve's close-to-close return
    ending on ``date``.  IV fields are index-option observations.  No field can
    carry individual-stock option IV.
    """

    date: str
    base_sleeve_return: float | None
    topix_cash_close: float | None
    n225_base_vol: float | None
    n225_atm_iv: float | None
    topix_realized_vol_20: float | None
    n225_front_atm_iv: float | None
    n225_next_atm_iv: float | None
    n225_front_downside_wing_iv: float | None
    n225_next_downside_wing_iv: float | None
    # SVI equivalents are retained for diagnostics only.  They never enter a
    # signal, candidate ordering, or result selection.
    svi_equivalent_atm_term_ratio: float | None = None
    svi_equivalent_downside_wing_term_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class OverlayCandidate:
    candidate_id: str
    feature_kind: str
    mechanics: str
    thesis: str
    return_source: str


OVERLAY_CANDIDATES: Final[tuple[OverlayCandidate, ...]] = (
    OverlayCandidate(
        candidate_id="n225_basevol_10_over_60_defensive_v1",
        feature_kind="basevol_10_over_60",
        mechanics=(
            "x=mean(N225 BaseVol,10 sessions)/mean(N225 BaseVol,60 sessions); "
            "gross scale g=clip(1/x,0.5,1.0)"
        ),
        thesis="Reduce the frozen stock sleeve when short-run index volatility rises.",
        return_source="Lower drawdown and volatility drag during broad market stress.",
    ),
    OverlayCandidate(
        candidate_id="n225_atmiv_over_topix_rv20_normalized_126_v1",
        feature_kind="atmiv_topix_rv_normalized_126",
        mechanics=(
            "x=(N225 ATM IV/TOPIX RV20)/its inclusive trailing-126-session "
            "median; g=clip(1/x,0.5,1.0)"
        ),
        thesis="Treat unusually rich index IV versus TOPIX realised risk as caution.",
        return_source="Dynamic risk reduction when option-implied stress is elevated.",
    ),
    OverlayCandidate(
        candidate_id="n225_observed_front_over_next_atm_v1",
        feature_kind="observed_atm_term_ratio",
        mechanics="x=observed front ATM IV/next ATM IV; g=clip(1/x,0.5,1.0)",
        thesis="Front-month ATM inversion is a near-term stress signal.",
        return_source="Avoid part of short-horizon market drawdowns during inversion.",
    ),
    OverlayCandidate(
        candidate_id="n225_observed_downside_wing_front_over_next_v1",
        feature_kind="observed_downside_wing_term_ratio",
        mechanics=(
            "x=observed front downside-wing IV/next downside-wing IV; "
            "g=clip(1/x,0.5,1.0)"
        ),
        thesis="Near-term downside-tail demand can warn before ATM volatility does.",
        return_source="Reduce crash exposure when front downside protection is dear.",
    ),
)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0.0 else None


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _validate_observations(
    observations: Sequence[IndexVolOverlayObservation],
) -> None:
    if len(observations) < 3:
        raise ValueError("at least three ordered sessions are required")
    previous: str | None = None
    for row in observations:
        if not isinstance(row, IndexVolOverlayObservation):
            raise TypeError("observations must be IndexVolOverlayObservation values")
        try:
            parsed = date.fromisoformat(row.date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid observation date: {row.date!r}") from exc
        canonical = parsed.isoformat()
        if row.date != canonical:
            raise ValueError(f"observation date must be canonical ISO: {row.date!r}")
        if previous is not None and row.date <= previous:
            raise ValueError("observation dates must be unique and strictly increasing")
        previous = row.date


def _ratio(numerator: Any, denominator: Any) -> float | None:
    left = _positive(numerator)
    right = _positive(denominator)
    if left is None or right is None:
        return None
    value = left / right
    return value if math.isfinite(value) and value > 0.0 else None


def _feature_value(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    index: int,
) -> tuple[float | None, str | None]:
    row = rows[index]
    if candidate.feature_kind == "basevol_10_over_60":
        if index < 59:
            return None, "basevol_60_session_history_unavailable"
        window = [
            _positive(item.n225_base_vol)
            for item in rows[index - 59 : index + 1]
        ]
        if any(value is None for value in window):
            return None, "basevol_required_history_has_missing_row"
        values = [float(value) for value in window if value is not None]
        return _ratio(mean(values[-10:]), mean(values)), None

    if candidate.feature_kind == "atmiv_topix_rv_normalized_126":
        if index < 125:
            return None, "atmiv_topix_rv_126_session_history_unavailable"
        window = [
            _ratio(item.n225_atm_iv, item.topix_realized_vol_20)
            for item in rows[index - 125 : index + 1]
        ]
        if any(value is None for value in window):
            return None, "atmiv_topix_rv_required_history_has_missing_row"
        values = [float(value) for value in window if value is not None]
        return _ratio(values[-1], median(values)), None

    if candidate.feature_kind == "observed_atm_term_ratio":
        value = _ratio(row.n225_front_atm_iv, row.n225_next_atm_iv)
        return value, None if value is not None else "observed_atm_term_row_missing"

    if candidate.feature_kind == "observed_downside_wing_term_ratio":
        value = _ratio(
            row.n225_front_downside_wing_iv,
            row.n225_next_downside_wing_iv,
        )
        return (
            value,
            None
            if value is not None
            else "observed_downside_wing_term_row_missing",
        )
    raise AssertionError(f"unknown frozen candidate feature: {candidate.feature_kind}")


def _topix_return(
    rows: Sequence[IndexVolOverlayObservation],
    start_index: int,
    end_index: int,
) -> float | None:
    before = _positive(rows[start_index].topix_cash_close)
    after = _positive(rows[end_index].topix_cash_close)
    if before is None or after is None:
        return None
    return _finite(after / before - 1.0)


def _estimate_beta(
    rows: Sequence[IndexVolOverlayObservation],
    signal_index: int,
) -> tuple[float, int, str] | None:
    paired: list[tuple[str, float, float]] = []
    for index in range(1, signal_index + 1):
        sleeve_return = _finite(rows[index].base_sleeve_return)
        proxy_return = _topix_return(rows, index - 1, index)
        if sleeve_return is None or proxy_return is None:
            continue
        paired.append((rows[index].date, sleeve_return, proxy_return))
    paired = paired[-BETA_LOOKBACK_RETURNS:]
    if len(paired) < BETA_MIN_RETURNS:
        return None
    sleeve_values = [item[1] for item in paired]
    proxy_values = [item[2] for item in paired]
    sleeve_mean = mean(sleeve_values)
    proxy_mean = mean(proxy_values)
    covariance = sum(
        (sleeve - sleeve_mean) * (proxy - proxy_mean)
        for sleeve, proxy in zip(sleeve_values, proxy_values, strict=True)
    )
    variance = sum((proxy - proxy_mean) ** 2 for proxy in proxy_values)
    if variance <= 1.0e-18:
        return None
    beta = _finite(covariance / variance)
    return None if beta is None else (beta, len(paired), paired[-1][0])


def _missing(date_value: str, reason: str) -> dict[str, str]:
    return {"date": date_value, "reason": reason}


def _plans_for_candidate(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    signal_indices: Sequence[int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    plans: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for signal_index in signal_indices:
        signal_row = rows[signal_index]
        if signal_index + 2 >= len(rows):
            missing.append(_missing(signal_row.date, "d_plus_2_session_unavailable"))
            continue
        x_value, feature_error = _feature_value(candidate, rows, signal_index)
        if x_value is None:
            missing.append(
                _missing(signal_row.date, feature_error or "feature_value_unavailable")
            )
            continue
        beta = _estimate_beta(rows, signal_index)
        if beta is None:
            missing.append(_missing(signal_row.date, "beta_min_63_returns_unavailable"))
            continue
        pnl_index = signal_index + 2
        sleeve_return = _finite(rows[pnl_index].base_sleeve_return)
        proxy_return = _topix_return(rows, signal_index + 1, pnl_index)
        if sleeve_return is None:
            missing.append(_missing(rows[pnl_index].date, "base_sleeve_return_missing"))
            continue
        if proxy_return is None:
            missing.append(_missing(rows[pnl_index].date, "topix_cash_return_missing"))
            continue
        gross_scale = _clip(1.0 / x_value, 0.5, 1.0)
        estimated_beta, beta_observations, beta_last_date = beta
        hedge_weight = _clip(
            -gross_scale * estimated_beta,
            -MAX_ABS_TOPIX_HEDGE,
            MAX_ABS_TOPIX_HEDGE,
        )
        plans.append(
            {
                "signal_date": signal_row.date,
                "rebalance_date": rows[signal_index + 1].date,
                "pnl_date": rows[pnl_index].date,
                "feature_ratio_x": x_value,
                "gross_scale": gross_scale,
                "estimated_beta": estimated_beta,
                "beta_observations": beta_observations,
                "beta_window_last_return_date": beta_last_date,
                "topix_hedge_weight": hedge_weight,
                "base_sleeve_return": sleeve_return,
                "topix_cash_return": proxy_return,
            }
        )
    return plans, missing


def _trade(
    *,
    side: str,
    signal_date: str,
    fill_date: str,
    pnl_date: str,
    turnover_weight: float,
    equity: float,
) -> dict[str, Any] | None:
    if turnover_weight == 0.0:
        return None
    notional = abs(turnover_weight) * equity
    return {
        "side": side,
        "signal_date": signal_date,
        "fill_date": fill_date,
        "pnl_date": pnl_date,
        "notional": notional,
        "cost": notional * ONE_WAY_COST_RATE,
    }


def _evaluate_plans(
    plans: Sequence[dict[str, Any]],
    *,
    starting_capital: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    equity = starting_capital
    previous_gross_scale = 0.0
    previous_hedge_weight = 0.0
    curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for plan_index, plan in enumerate(plans):
        gross_scale = float(plan["gross_scale"])
        hedge_weight = float(plan["topix_hedge_weight"])
        sleeve_turnover = abs(gross_scale - previous_gross_scale)
        proxy_turnover = abs(hedge_weight - previous_hedge_weight)
        opening_equity = equity
        for trade in (
            _trade(
                side="sleeve_rebalance",
                signal_date=str(plan["signal_date"]),
                fill_date=str(plan["rebalance_date"]),
                pnl_date=str(plan["pnl_date"]),
                turnover_weight=sleeve_turnover,
                equity=opening_equity,
            ),
            _trade(
                side="topix_cash_proxy_rebalance",
                signal_date=str(plan["signal_date"]),
                fill_date=str(plan["rebalance_date"]),
                pnl_date=str(plan["pnl_date"]),
                turnover_weight=proxy_turnover,
                equity=opening_equity,
            ),
        ):
            if trade is not None:
                trades.append(trade)
        opening_cost = opening_equity * ONE_WAY_COST_RATE * (
            sleeve_turnover + proxy_turnover
        )
        gross_return = (
            gross_scale * float(plan["base_sleeve_return"])
            + hedge_weight * float(plan["topix_cash_return"])
        )
        equity = opening_equity * (1.0 + gross_return) - opening_cost
        terminal_turnover = 0.0
        terminal_cost = 0.0
        terminal_close = plan_index == len(plans) - 1
        if terminal_close:
            terminal_turnover = abs(gross_scale) + abs(hedge_weight)
            pre_close_equity = equity
            for trade in (
                _trade(
                    side="sleeve_terminal_close",
                    signal_date=str(plan["signal_date"]),
                    fill_date=str(plan["pnl_date"]),
                    pnl_date=str(plan["pnl_date"]),
                    turnover_weight=abs(gross_scale),
                    equity=pre_close_equity,
                ),
                _trade(
                    side="topix_cash_proxy_terminal_close",
                    signal_date=str(plan["signal_date"]),
                    fill_date=str(plan["pnl_date"]),
                    pnl_date=str(plan["pnl_date"]),
                    turnover_weight=abs(hedge_weight),
                    equity=pre_close_equity,
                ),
            ):
                if trade is not None:
                    trades.append(trade)
            terminal_cost = pre_close_equity * ONE_WAY_COST_RATE * terminal_turnover
            equity -= terminal_cost
        if not math.isfinite(equity) or equity <= 0.0:
            raise ValueError("overlay path produced non-positive or non-finite equity")
        net_return = equity / opening_equity - 1.0
        curve.append(
            {
                **plan,
                "gross_return": gross_return,
                "sleeve_turnover_one_way": sleeve_turnover,
                "topix_proxy_turnover_one_way": proxy_turnover,
                "rebalance_cost_amount": opening_cost,
                "terminal_close": terminal_close,
                "terminal_turnover_one_way": terminal_turnover,
                "terminal_close_cost_amount": terminal_cost,
                "net_return": net_return,
                "date": plan["pnl_date"],
                "equity": equity,
            }
        )
        previous_gross_scale = gross_scale
        previous_hedge_weight = hedge_weight
    performance = summarize_performance(
        equity_curve=curve,
        trades=trades,
        starting_capital=starting_capital,
    )
    return curve, trades, performance


def _candidate_result(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    signal_indices: Sequence[int],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    plans, missing = _plans_for_candidate(candidate, rows, signal_indices)
    declaration = asdict(candidate)
    if missing:
        return {
            **declaration,
            "status": "NOT_EVALUATED",
            "reason": "missing_required_row_no_forward_fill",
            "missing_required_rows": missing,
            "daily_path": [],
            "trades": [],
            "performance": None,
        }
    if not plans:
        return {
            **declaration,
            "status": "NOT_EVALUATED",
            "reason": "no_signal_sessions_in_requested_range",
            "missing_required_rows": [],
            "daily_path": [],
            "trades": [],
            "performance": None,
        }
    curve, trades, performance = _evaluate_plans(
        plans,
        starting_capital=starting_capital,
    )
    return {
        **declaration,
        "status": "EVALUATED",
        "reason": None,
        "missing_required_rows": [],
        "daily_path": curve,
        "trades": trades,
        "performance": performance,
    }


def evaluate_index_vol_overlays(
    observations: Sequence[IndexVolOverlayObservation],
    *,
    signal_start: str,
    signal_end: str | None = None,
    starting_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    """Evaluate exactly four predeclared overlays without selecting a winner."""

    _validate_observations(observations)
    try:
        start = date.fromisoformat(signal_start).isoformat()
        end = (
            date.fromisoformat(signal_end).isoformat()
            if signal_end
            else observations[-3].date
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("signal_start/signal_end must be canonical ISO dates") from exc
    if start != signal_start or (signal_end is not None and end != signal_end):
        raise ValueError("signal_start/signal_end must be canonical ISO dates")
    if end is not None and end < start:
        raise ValueError("signal_end must be on or after signal_start")
    capital = _positive(starting_capital)
    if capital is None:
        raise ValueError("starting_capital must be positive and finite")
    signal_indices = [
        index
        for index, row in enumerate(observations)
        if row.date >= start and (end is None or row.date <= end)
    ]
    if not signal_indices:
        raise ValueError("requested signal range has no observations")
    results = [
        _candidate_result(
            candidate,
            observations,
            signal_indices,
            starting_capital=capital,
        )
        for candidate in OVERLAY_CANDIDATES
    ]
    diagnostics = [
        {
            "date": observations[index].date,
            "svi_equivalent_atm_term_ratio": _finite(
                observations[index].svi_equivalent_atm_term_ratio
            ),
            "svi_equivalent_downside_wing_term_ratio": _finite(
                observations[index].svi_equivalent_downside_wing_term_ratio
            ),
        }
        for index in signal_indices
    ]
    evaluated_count = sum(result["status"] == "EVALUATED" for result in results)
    return {
        "schema_version": PERSONAL_INDEX_VOL_OVERLAY_SCHEMA,
        "status": "EVALUATED" if evaluated_count == len(results) else "NOT_EVALUATED",
        "base_sleeve": {
            "strategy_id": BASE_SLEEVE_ID,
            "universe_id": BASE_UNIVERSE_ID,
            "selection_timing": "PREDECLARED_BEFORE_OVERLAY_RESULTS",
            "single_stock_option_iv": "EXCLUDED_FROM_INPUT_SURFACE",
            "stock_price_realized_volatility": "ALLOWED_IN_FROZEN_BASE_SLEEVE",
        },
        "timing": {
            "signal": "D_CLOSE",
            "rebalance": "D_PLUS_1_CLOSE",
            "first_pnl": "D_PLUS_1_CLOSE_TO_D_PLUS_2_CLOSE",
            "terminal_close": True,
        },
        "cost_model": {
            "one_way_basis_points": 10.0,
            "applies_to": ["base_sleeve_turnover", "topix_proxy_turnover"],
        },
        "topix_proxy": {
            "dataset": TOPIX_PROXY_DATASET,
            "label": "TOPIX cash index close-to-close return",
            "role": "NON_EXECUTABLE_HEDGE_APPROXIMATION",
            "etf_fill_claim": False,
            "warning": (
                "This is not an ETF fill or tradable execution claim; later cloud "
                "work must bind an explicit executable proxy before paper execution."
            ),
        },
        "beta_policy": {
            "lookback_returns": BETA_LOOKBACK_RETURNS,
            "minimum_returns": BETA_MIN_RETURNS,
            "hedge_formula": "h=clip(-g*beta,-1.5,1.5)",
        },
        "candidate_policy": {
            "declared_count": len(OVERLAY_CANDIDATES),
            "evaluated_count": evaluated_count,
            "post_result_selection": "NOT_PERFORMED",
            "ranking": None,
            "candidate_order": [item.candidate_id for item in OVERLAY_CANDIDATES],
        },
        "svi_equivalent_diagnostics": {
            "role": "DIAGNOSTIC_ONLY_NOT_RANKED",
            "used_in_signals": False,
            "used_in_performance": False,
            "rows": diagnostics,
        },
        "candidates": results,
    }


__all__ = [
    "BASE_SLEEVE_ID",
    "BASE_UNIVERSE_ID",
    "BETA_LOOKBACK_RETURNS",
    "BETA_MIN_RETURNS",
    "IndexVolOverlayObservation",
    "MAX_ABS_TOPIX_HEDGE",
    "ONE_WAY_COST_RATE",
    "OVERLAY_CANDIDATES",
    "PERSONAL_INDEX_VOL_OVERLAY_SCHEMA",
    "TOPIX_PROXY_DATASET",
    "evaluate_index_vol_overlays",
]
