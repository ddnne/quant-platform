"""Nikkei 225 SVI potential-well and one-session smile transport features.

This module is a research-only, pure-Python feature core.  It compares the
same listed expiry between the previous and current observed sessions under
two symmetric hypotheses:

``sticky_moneyness``
    The prior implied-volatility smile keeps the same
    ``k = ln(strike / UnderPx)`` coordinate.

``sticky_strike``
    The prior implied-volatility smile keeps the same absolute strike.  A
    current coordinate ``k`` is therefore evaluated at
    ``k + ln(UnderPx[D] / UnderPx[D-1])`` on the prior surface.

``UnderPx`` is only the disclosed coordinate proxy used by the existing SVI
fit.  It is not called a forward.  Forward-relative outputs remain explicitly
unavailable until a trusted forward is supplied by a future data contract.

All signal rows are measured at the current close and are intended only for
execution on D+1 or later.  There is no fill-forward, expiry-rank substitution,
or extrapolation outside either fitted log-moneyness band.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from typing import Any, Iterable, Mapping, Sequence

from research.options_225_smile_features import (
    OPTIONS_225_SMILE_SURFACE_SCOPE,
    SVIParameters,
    SmileFitConfig,
    build_options_225_smile_slices,
    svi_first_derivative,
    svi_second_derivative,
    svi_total_variance,
)
from research.options_225_vol_series import DATASET_ID

OPTIONS_225_SMILE_TRANSPORT_VERSION = "research-options-225-smile-transport/v1"
STICKY_STRIKE = "sticky_strike"
STICKY_MONEYNESS = "sticky_moneyness"
SMILE_TRANSPORT_MODELS = (STICKY_STRIKE, STICKY_MONEYNESS)
TRUSTED_FORWARD_UNAVAILABLE = "trusted_forward_unavailable"


@dataclass(frozen=True)
class SVIPotentialMinimum:
    """Analytic minimum of a valid raw-SVI total-variance curve."""

    log_moneyness: float
    total_variance: float
    first_derivative: float
    curvature: float


def svi_potential_minimum(parameters: SVIParameters) -> SVIPotentialMinimum:
    """Return the unique finite minimum of a convex raw-SVI curve.

    For ``b > 0``, ``sigma > 0`` and ``abs(rho) < 1``, solving ``w'(k)=0``
    gives

    ``k_min = m - rho*sigma/sqrt(1-rho**2)``.
    """

    if (
        not all(math.isfinite(float(value)) for value in parameters.as_dict().values())
        or parameters.b <= 0.0
        or parameters.sigma <= 0.0
        or abs(parameters.rho) >= 1.0
    ):
        raise ValueError("raw SVI potential minimum requires b>0, sigma>0, abs(rho)<1")
    one_minus_rho_sq = 1.0 - parameters.rho * parameters.rho
    k_min = parameters.m - (
        parameters.rho * parameters.sigma / math.sqrt(one_minus_rho_sq)
    )
    minimum = parameters.a + (
        parameters.b * parameters.sigma * math.sqrt(one_minus_rho_sq)
    )
    if not math.isfinite(minimum) or minimum <= 0.0:
        raise ValueError("raw SVI potential minimum is not positive")
    return SVIPotentialMinimum(
        log_moneyness=k_min,
        total_variance=minimum,
        first_derivative=svi_first_derivative(k_min, parameters),
        curvature=svi_second_derivative(k_min, parameters),
    )


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parameters(row: Mapping[str, Any]) -> SVIParameters | None:
    raw = row.get("svi_parameters")
    if not isinstance(raw, Mapping):
        return None
    values = [_finite_float(raw.get(name)) for name in ("a", "b", "rho", "m", "sigma")]
    if any(value is None for value in values):
        return None
    return SVIParameters(*[float(value) for value in values if value is not None])


def _fit_band(row: Mapping[str, Any]) -> tuple[float, float] | None:
    lower = _finite_float(row.get("fit_log_moneyness_min"))
    upper = _finite_float(row.get("fit_log_moneyness_max"))
    if lower is None or upper is None or lower >= upper:
        return None
    return lower, upper


def _slice_issue(row: Mapping[str, Any], *, side: str) -> str | None:
    if row.get("surface_scope") != OPTIONS_225_SMILE_SURFACE_SCOPE:
        return f"{side}_surface_scope_denied"
    if row.get("source_dataset_id") != DATASET_ID:
        return f"{side}_source_dataset_denied"
    if row.get("fit_success") is not True:
        return f"{side}_fit_{row.get('fit_reason') or 'unavailable'}"
    if _parameters(row) is None:
        return f"{side}_parameters_unavailable"
    maturity = _finite_float(row.get("maturity_years"))
    under_px = _finite_float(row.get("under_px"))
    try:
        observation_date = _date.fromisoformat(str(row.get("date") or ""))
        expiry = _date.fromisoformat(str(row.get("expiry") or ""))
        disclosed_dte = int(row.get("dte_days"))
    except (TypeError, ValueError):
        return f"{side}_date_contract_invalid"
    derived_dte = (expiry - observation_date).days
    if disclosed_dte != derived_dte or derived_dte <= 0:
        return f"{side}_dte_contract_mismatch"
    if maturity is None or maturity <= 0.0:
        return f"{side}_maturity_unavailable"
    if not math.isclose(maturity, derived_dte / 365.0, rel_tol=0.0, abs_tol=1.0e-12):
        return f"{side}_maturity_contract_mismatch"
    if under_px is None or under_px <= 0.0:
        return f"{side}_under_px_proxy_unavailable"
    if _fit_band(row) is None:
        return f"{side}_fit_band_unavailable"
    return None


def _iv_at(row: Mapping[str, Any], k: float) -> tuple[float | None, str]:
    parameters = _parameters(row)
    maturity = _finite_float(row.get("maturity_years"))
    band = _fit_band(row)
    if parameters is None or maturity is None or maturity <= 0.0 or band is None:
        return None, "surface_unavailable"
    if not math.isfinite(k) or k < band[0] or k > band[1]:
        return None, "source_coordinate_out_of_fit_band"
    total_variance = svi_total_variance(k, parameters)
    if not math.isfinite(total_variance) or total_variance <= 0.0:
        return None, "non_positive_total_variance"
    return math.sqrt(total_variance / maturity), "ok"


def _potential_well(row: Mapping[str, Any]) -> dict[str, Any]:
    empty = {
        "success": False,
        "reason": "surface_unavailable",
        "minimum_proxy_log_moneyness": None,
        "minimum_strike_over_under_px_minus_one": None,
        "minimum_iv_decimal": None,
        "minimum_total_variance": None,
        "minimum_curvature": None,
        "minimum_normalized_curvature": None,
        "minimum_iv_over_atm_minus_one": None,
        "atm_iv_over_minimum_minus_one": None,
        "atm_potential_slope": None,
    }
    parameters = _parameters(row)
    maturity = _finite_float(row.get("maturity_years"))
    band = _fit_band(row)
    if parameters is None or maturity is None or maturity <= 0.0 or band is None:
        return empty
    try:
        minimum = svi_potential_minimum(parameters)
    except ValueError as exc:
        return {**empty, "reason": str(exc)}
    if not band[0] <= minimum.log_moneyness <= band[1]:
        return {**empty, "reason": "analytic_minimum_out_of_fit_band"}
    atm_iv, atm_reason = _iv_at(row, 0.0)
    if atm_iv is None:
        return {**empty, "reason": f"atm_{atm_reason}"}
    minimum_iv = math.sqrt(minimum.total_variance / maturity)
    return {
        "success": True,
        "reason": "ok",
        "minimum_proxy_log_moneyness": minimum.log_moneyness,
        "minimum_strike_over_under_px_minus_one": math.expm1(minimum.log_moneyness),
        "minimum_iv_decimal": minimum_iv,
        "minimum_total_variance": minimum.total_variance,
        "minimum_curvature": minimum.curvature,
        "minimum_normalized_curvature": minimum.curvature / minimum.total_variance,
        "minimum_iv_over_atm_minus_one": minimum_iv / atm_iv - 1.0,
        "atm_iv_over_minimum_minus_one": atm_iv / minimum_iv - 1.0,
        "atm_potential_slope": svi_first_derivative(0.0, parameters),
    }


_TRANSPORT_VALUE_FIELDS = (
    "current_downside_iv_decimal",
    "predicted_downside_iv_decimal",
    "current_atm_iv_decimal",
    "predicted_atm_iv_decimal",
    "current_downside_iv_over_atm_minus_one",
    "predicted_downside_iv_over_atm_minus_one",
    "downside_smile_surprise",
    "downside_iv_actual_over_predicted_minus_one",
    "current_minimum_proxy_log_moneyness",
    "previous_minimum_proxy_log_moneyness",
    "predicted_minimum_proxy_log_moneyness",
    "minimum_location_error_log_moneyness",
    "minimum_strike_actual_over_predicted_minus_one",
    "current_minimum_iv_decimal",
    "predicted_minimum_iv_decimal",
    "minimum_iv_actual_over_predicted_minus_one",
    "current_minimum_iv_over_atm_minus_one",
    "predicted_minimum_iv_over_atm_minus_one",
    "potential_depth_surprise",
    "current_minimum_normalized_curvature",
    "previous_minimum_normalized_curvature",
    "minimum_normalized_curvature_ratio_minus_one",
)


def _base_transport_row(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    previous_date: str,
    maturity_rank: int,
    model: str,
    target: float,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": str(current.get("date") or ""),
        "previous_observation_date": previous_date,
        "expiry": current.get("expiry"),
        "current_cm": current.get("cm"),
        "previous_cm": previous.get("cm") if previous is not None else None,
        "current_dte_days": current.get("dte_days"),
        "previous_dte_days": previous.get("dte_days") if previous is not None else None,
        "maturity_rank": maturity_rank,
        "transport_model": model,
        "target_downside_proxy_log_moneyness": -target,
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
        "pairing_rule": "adjacent_observation_dates_exact_same_expiry",
        "signal_cutoff": "D_close",
        "execution_intent": "D_plus_1_or_later",
        "research_status": "DRAFT_DIAGNOSTIC_ONLY",
        "ffill_applied": False,
        "expiry_rank_substitution_applied": False,
        "extrapolation_applied": False,
        "downside_transport_success": False,
        "downside_transport_reason": "not_evaluated",
        "potential_minimum_transport_success": False,
        "potential_minimum_transport_reason": "not_evaluated",
        "potential_depth_reason": "not_evaluated",
    }
    row.update({field: None for field in _TRANSPORT_VALUE_FIELDS})
    return row


def _transport_pair(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    previous_date: str,
    maturity_rank: int,
    model: str,
    target: float,
    forced_reason: str | None = None,
) -> dict[str, Any]:
    row = _base_transport_row(
        current,
        previous,
        previous_date=previous_date,
        maturity_rank=maturity_rank,
        model=model,
        target=target,
    )
    if forced_reason is not None:
        row["downside_transport_reason"] = forced_reason
        row["potential_minimum_transport_reason"] = forced_reason
        row["potential_depth_reason"] = forced_reason
        return row
    if previous is None:
        reason = "previous_exact_expiry_unavailable"
        row["downside_transport_reason"] = reason
        row["potential_minimum_transport_reason"] = reason
        row["potential_depth_reason"] = reason
        return row
    current_issue = _slice_issue(current, side="current")
    previous_issue = _slice_issue(previous, side="previous")
    if current_issue is not None or previous_issue is not None:
        reason = current_issue or previous_issue or "surface_unavailable"
        row["downside_transport_reason"] = reason
        row["potential_minimum_transport_reason"] = reason
        row["potential_depth_reason"] = reason
        return row

    current_under_px = float(current["under_px"])
    previous_under_px = float(previous["under_px"])
    proxy_log_return = math.log(current_under_px / previous_under_px)
    row["under_px_proxy_log_return"] = proxy_log_return
    current_downside_k = -target
    if model == STICKY_MONEYNESS:
        previous_downside_k = current_downside_k
        previous_atm_k = 0.0
    elif model == STICKY_STRIKE:
        previous_downside_k = current_downside_k + proxy_log_return
        previous_atm_k = proxy_log_return
    else:  # pragma: no cover - guarded by the public closed model loop
        raise ValueError("unsupported smile transport model")
    row["previous_source_downside_proxy_log_moneyness"] = previous_downside_k
    row["previous_source_atm_proxy_log_moneyness"] = previous_atm_k

    current_downside_iv, current_downside_reason = _iv_at(current, current_downside_k)
    current_atm_iv, current_atm_reason = _iv_at(current, 0.0)
    predicted_downside_iv, predicted_downside_reason = _iv_at(
        previous, previous_downside_k
    )
    predicted_atm_iv, predicted_atm_reason = _iv_at(previous, previous_atm_k)
    downside_values = (
        current_downside_iv,
        current_atm_iv,
        predicted_downside_iv,
        predicted_atm_iv,
    )
    if all(value is not None and value > 0.0 for value in downside_values):
        actual_ratio = float(current_downside_iv) / float(current_atm_iv) - 1.0
        predicted_ratio = float(predicted_downside_iv) / float(predicted_atm_iv) - 1.0
        row.update(
            {
                "downside_transport_success": True,
                "downside_transport_reason": "ok",
                "current_downside_iv_decimal": current_downside_iv,
                "predicted_downside_iv_decimal": predicted_downside_iv,
                "current_atm_iv_decimal": current_atm_iv,
                "predicted_atm_iv_decimal": predicted_atm_iv,
                "current_downside_iv_over_atm_minus_one": actual_ratio,
                "predicted_downside_iv_over_atm_minus_one": predicted_ratio,
                "downside_smile_surprise": actual_ratio - predicted_ratio,
                "downside_iv_actual_over_predicted_minus_one": (
                    float(current_downside_iv) / float(predicted_downside_iv) - 1.0
                ),
            }
        )
    else:
        reasons = (
            current_downside_reason,
            current_atm_reason,
            predicted_downside_reason,
            predicted_atm_reason,
        )
        row["downside_transport_reason"] = next(
            reason for reason in reasons if reason != "ok"
        )

    current_well = _potential_well(current)
    previous_well = _potential_well(previous)
    if not current_well["success"] or not previous_well["success"]:
        reason = (
            f"current_{current_well['reason']}"
            if not current_well["success"]
            else f"previous_{previous_well['reason']}"
        )
        row["potential_minimum_transport_reason"] = reason
        row["potential_depth_reason"] = reason
        return row

    current_min_k = float(current_well["minimum_proxy_log_moneyness"])
    previous_min_k = float(previous_well["minimum_proxy_log_moneyness"])
    predicted_min_k = (
        previous_min_k
        if model == STICKY_MONEYNESS
        else previous_min_k - proxy_log_return
    )
    current_band = _fit_band(current)
    assert current_band is not None
    if not current_band[0] <= predicted_min_k <= current_band[1]:
        row["potential_minimum_transport_reason"] = (
            "predicted_minimum_out_of_current_fit_band"
        )
        row["potential_depth_reason"] = "predicted_minimum_out_of_current_fit_band"
        return row

    location_error = current_min_k - predicted_min_k
    current_min_iv = float(current_well["minimum_iv_decimal"])
    previous_min_iv = float(previous_well["minimum_iv_decimal"])
    current_curvature = float(current_well["minimum_normalized_curvature"])
    previous_curvature = float(previous_well["minimum_normalized_curvature"])
    row.update(
        {
            "potential_minimum_transport_success": True,
            "potential_minimum_transport_reason": "ok",
            "current_minimum_proxy_log_moneyness": current_min_k,
            "previous_minimum_proxy_log_moneyness": previous_min_k,
            "predicted_minimum_proxy_log_moneyness": predicted_min_k,
            "minimum_location_error_log_moneyness": location_error,
            "minimum_strike_actual_over_predicted_minus_one": math.expm1(
                location_error
            ),
            "current_minimum_iv_decimal": current_min_iv,
            "predicted_minimum_iv_decimal": previous_min_iv,
            "minimum_iv_actual_over_predicted_minus_one": (
                current_min_iv / previous_min_iv - 1.0
            ),
            "current_minimum_iv_over_atm_minus_one": current_well[
                "minimum_iv_over_atm_minus_one"
            ],
            "current_minimum_normalized_curvature": current_curvature,
            "previous_minimum_normalized_curvature": previous_curvature,
            "minimum_normalized_curvature_ratio_minus_one": (
                current_curvature / previous_curvature - 1.0
            ),
        }
    )
    if predicted_atm_iv is None or predicted_atm_iv <= 0.0:
        row["potential_depth_reason"] = predicted_atm_reason
    else:
        predicted_depth = previous_min_iv / predicted_atm_iv - 1.0
        current_depth = float(current_well["minimum_iv_over_atm_minus_one"])
        row.update(
            {
                "potential_depth_reason": "ok",
                "predicted_minimum_iv_over_atm_minus_one": predicted_depth,
                "potential_depth_surprise": current_depth - predicted_depth,
            }
        )
    return row


def build_svi_smile_transport_rows(
    slices: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    config: SmileFitConfig | None = None,
) -> list[dict[str, Any]]:
    """Pair adjacent observed dates by exact expiry and emit both models."""

    cfg = config or SmileFitConfig()
    by_date: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for raw in slices:
        date = str(raw.get("date") or "")
        expiry = str(raw.get("expiry") or "")
        if date and expiry:
            by_date[date][expiry].append(raw)
    dates = sorted(by_date)
    output: list[dict[str, Any]] = []
    for previous_date, current_date in zip(dates, dates[1:]):
        current_groups: list[tuple[int, str, list[Mapping[str, Any]]]] = []
        for expiry, group in by_date[current_date].items():
            try:
                dte = (
                    _date.fromisoformat(expiry)
                    - _date.fromisoformat(current_date)
                ).days
            except ValueError:
                continue
            if cfg.min_dte_days <= dte <= cfg.max_dte_days:
                current_groups.append((dte, expiry, group))
        current_groups.sort(key=lambda item: (item[0], item[1]))
        for rank, (_, expiry, current_group) in enumerate(current_groups, start=1):
            current = current_group[0]
            previous_group = by_date[previous_date].get(expiry, [])
            previous = previous_group[0] if len(previous_group) == 1 else None
            forced_reason = None
            if len(current_group) != 1:
                forced_reason = "current_exact_expiry_ambiguous"
            elif len(previous_group) > 1:
                forced_reason = "previous_exact_expiry_ambiguous"
            for model in SMILE_TRANSPORT_MODELS:
                output.append(
                    _transport_pair(
                        current,
                        previous,
                        previous_date=previous_date,
                        maturity_rank=rank,
                        model=model,
                        target=cfg.target_abs_log_moneyness,
                        forced_reason=forced_reason,
                    )
                )
    return output


def build_daily_svi_smile_transport_features(
    slices: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    config: SmileFitConfig | None = None,
) -> list[dict[str, Any]]:
    """Emit exactly four D-close candidate rows per date (2 models x 2 families)."""

    pair_rows = build_svi_smile_transport_rows(slices, config=config)
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        grouped[
            (
                str(row["date"]),
                str(row["previous_observation_date"]),
                str(row["transport_model"]),
            )
        ].append(row)
    output: list[dict[str, Any]] = []
    for (date, previous_date, model), rows in sorted(grouped.items()):
        ranked = {int(row["maturity_rank"]): row for row in rows}
        front = ranked.get(1)
        nxt = ranked.get(2)
        row: dict[str, Any] = {
            "date": date,
            "previous_observation_date": previous_date,
            "transport_model": model,
            "front_expiry": front.get("expiry") if front else None,
            "next_expiry": nxt.get("expiry") if nxt else None,
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
            "downside_smile_term_success": False,
            "downside_smile_term_reason": "front_or_next_unavailable",
            "front_downside_smile_surprise": None,
            "next_downside_smile_surprise": None,
            "downside_smile_term_surprise": None,
            "actual_downside_smile_term_ratio": None,
            "predicted_downside_smile_term_ratio": None,
            "downside_smile_term_ratio_surprise_minus_one": None,
            "potential_minimum_transport_success": False,
            "potential_minimum_transport_reason": "front_or_next_unavailable",
            "front_minimum_location_error_log_moneyness": None,
            "next_minimum_location_error_log_moneyness": None,
            "potential_minimum_location_term_spread": None,
            "potential_minimum_mean_absolute_error": None,
            "potential_minimum_term_inconsistency": None,
            "potential_minimum_mismatch_severity": None,
            "potential_depth_term_success": False,
            "potential_depth_term_reason": "front_or_next_unavailable",
            "potential_depth_term_surprise": None,
        }
        if front is not None and nxt is not None:
            if (
                front.get("downside_transport_success") is True
                and nxt.get("downside_transport_success") is True
            ):
                front_surprise = float(front["downside_smile_surprise"])
                next_surprise = float(nxt["downside_smile_surprise"])
                front_actual_ratio = (
                    float(front["current_downside_iv_over_atm_minus_one"]) + 1.0
                )
                next_actual_ratio = (
                    float(nxt["current_downside_iv_over_atm_minus_one"]) + 1.0
                )
                front_predicted_ratio = (
                    float(front["predicted_downside_iv_over_atm_minus_one"])
                    + 1.0
                )
                next_predicted_ratio = (
                    float(nxt["predicted_downside_iv_over_atm_minus_one"])
                    + 1.0
                )
                actual_term_ratio = front_actual_ratio / next_actual_ratio
                predicted_term_ratio = front_predicted_ratio / next_predicted_ratio
                row.update(
                    {
                        "downside_smile_term_success": True,
                        "downside_smile_term_reason": "ok",
                        "front_downside_smile_surprise": front_surprise,
                        "next_downside_smile_surprise": next_surprise,
                        "downside_smile_term_surprise": (
                            front_surprise - next_surprise
                        ),
                        "actual_downside_smile_term_ratio": actual_term_ratio,
                        "predicted_downside_smile_term_ratio": predicted_term_ratio,
                        "downside_smile_term_ratio_surprise_minus_one": (
                            actual_term_ratio / predicted_term_ratio - 1.0
                        ),
                    }
                )
            else:
                row["downside_smile_term_reason"] = (
                    f"front:{front.get('downside_transport_reason')};"
                    f"next:{nxt.get('downside_transport_reason')}"
                )
            if (
                front.get("potential_minimum_transport_success") is True
                and nxt.get("potential_minimum_transport_success") is True
            ):
                front_error = float(front["minimum_location_error_log_moneyness"])
                next_error = float(nxt["minimum_location_error_log_moneyness"])
                mean_absolute_error = (abs(front_error) + abs(next_error)) / 2.0
                term_inconsistency = abs(next_error - front_error)
                front_depth = front.get("potential_depth_surprise")
                next_depth = nxt.get("potential_depth_surprise")
                row.update(
                    {
                        "potential_minimum_transport_success": True,
                        "potential_minimum_transport_reason": "ok",
                        "front_minimum_location_error_log_moneyness": front_error,
                        "next_minimum_location_error_log_moneyness": next_error,
                        "potential_minimum_location_term_spread": (
                            front_error - next_error
                        ),
                        "potential_minimum_mean_absolute_error": mean_absolute_error,
                        "potential_minimum_term_inconsistency": term_inconsistency,
                        "potential_minimum_mismatch_severity": (
                            mean_absolute_error + term_inconsistency
                        ),
                        "potential_depth_term_surprise": (
                            float(front_depth) - float(next_depth)
                            if front_depth is not None and next_depth is not None
                            else None
                        ),
                    }
                )
                if front_depth is not None and next_depth is not None:
                    row["potential_depth_term_success"] = True
                    row["potential_depth_term_reason"] = "ok"
                else:
                    row["potential_depth_term_reason"] = (
                        f"front:{front.get('potential_depth_reason')};"
                        f"next:{nxt.get('potential_depth_reason')}"
                    )
            else:
                row["potential_minimum_transport_reason"] = (
                    f"front:{front.get('potential_minimum_transport_reason')};"
                    f"next:{nxt.get('potential_minimum_transport_reason')}"
                )
                row["potential_depth_term_reason"] = (
                    f"front:{front.get('potential_depth_reason')};"
                    f"next:{nxt.get('potential_depth_reason')}"
                )
        for family, value_field, success_field, reason_field, unit in (
            (
                "downside_smile_term_surprise",
                "downside_smile_term_ratio_surprise_minus_one",
                "downside_smile_term_success",
                "downside_smile_term_reason",
                "term_ratio_actual_over_predicted_minus_one",
            ),
            (
                "potential_minimum_transport",
                "potential_minimum_mismatch_severity",
                "potential_minimum_transport_success",
                "potential_minimum_transport_reason",
                "nonnegative_proxy_log_moneyness_mismatch",
            ),
        ):
            candidate = dict(row)
            candidate.update(
                {
                    "signal_family": family,
                    "candidate_id": f"n225_{model}_{family}_v1",
                    "candidate_value": row[value_field],
                    "candidate_value_unit": unit,
                    "candidate_success": row[success_field],
                    "candidate_reason": row[reason_field],
                }
            )
            output.append(candidate)
    return output


def build_options_225_smile_transport_rows(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    dataset_id: str,
    config: SmileFitConfig | None = None,
) -> list[dict[str, Any]]:
    """Build canonical exact-expiry transport rows from raw Nikkei 225 options."""

    if dataset_id != DATASET_ID:
        raise ValueError(f"dataset_id must be {DATASET_ID}")
    cfg = config or SmileFitConfig()
    return build_svi_smile_transport_rows(
        build_options_225_smile_slices(rows, dataset_id=dataset_id, config=cfg),
        config=cfg,
    )


def build_daily_options_225_smile_transport_features(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    dataset_id: str,
    config: SmileFitConfig | None = None,
) -> list[dict[str, Any]]:
    """Build D-close/D+1 term candidate features from raw Nikkei 225 options."""

    if dataset_id != DATASET_ID:
        raise ValueError(f"dataset_id must be {DATASET_ID}")
    cfg = config or SmileFitConfig()
    return build_daily_svi_smile_transport_features(
        build_options_225_smile_slices(rows, dataset_id=dataset_id, config=cfg),
        config=cfg,
    )


__all__ = [
    "OPTIONS_225_SMILE_TRANSPORT_VERSION",
    "STICKY_STRIKE",
    "STICKY_MONEYNESS",
    "SMILE_TRANSPORT_MODELS",
    "TRUSTED_FORWARD_UNAVAILABLE",
    "SVIPotentialMinimum",
    "svi_potential_minimum",
    "build_svi_smile_transport_rows",
    "build_daily_svi_smile_transport_features",
    "build_options_225_smile_transport_rows",
    "build_daily_options_225_smile_transport_features",
]
