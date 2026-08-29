"""Observed and raw-SVI smile features for Nikkei 225 option chains.

The module is intentionally dependency free and research only.  It fits each
observed ``date x contract-month x expiry`` slice independently, never fills a
missing strike or date, and emits no model-derived features when the fit fails
its numerical or static-arbitrage checks.

J-Quants option IVs are percentages.  They are converted to decimals before
fitting total variance with the raw SVI parameterisation

    w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

where ``k = log(strike / UnderPx)`` and ``T = calendar_days / 365``.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from typing import Any, Iterable, Mapping, Sequence

from research.options_225_vol_series import (
    EM_SETTLE,
    GAP_POLICY,
    IV_FIELDS_AVAILABLE_FROM,
    PC_CALL,
    PC_PUT,
    normalize_options_225_row,
)

OPTIONS_225_SMILE_FEATURE_VERSION = "research-options-225-smile-features/v1"
SVI_PARAMETERISATION = (
    "w(k)=a+b*(rho*(k-m)+sqrt((k-m)^2+sigma^2)); "
    "k=ln(strike/under_px); T=calendar_days/365"
)
OBSERVED_SMILE_CONVENTION = (
    "nearest listed strikes only; no strike interpolation; "
    "RR=(right_iv-left_iv)/atm_iv; "
    "BF=((left_iv+right_iv)/2-atm_iv)/atm_iv"
)


@dataclass(frozen=True)
class SmileFitConfig:
    """Small, explicit acceptance surface for one option-smile fit."""

    min_dte_days: int = 6
    max_dte_days: int = 370
    max_abs_log_moneyness: float = 0.35
    min_iv_percent: float = 1.0
    max_iv_percent: float = 300.0
    min_unique_strikes: int = 7
    min_strikes_each_wing: int = 2
    target_abs_log_moneyness: float = 0.10
    observed_target_tolerance: float = 0.04
    max_fit_rmse_iv_decimal: float = 0.035
    max_fit_error_iv_decimal: float = 0.09
    butterfly_grid_points: int = 121
    butterfly_check_abs_log_moneyness: float = 2.0
    min_total_variance: float = 1.0e-10
    butterfly_tolerance: float = 1.0e-8
    reject_boundary_hits: bool = True

    # Broad but finite raw-SVI parameter bounds.  The optimiser never projects
    # into them: a boundary-seeking solution is diagnosed and rejected.
    a_bounds: tuple[float, float] = (-1.0, 2.0)
    b_bounds: tuple[float, float] = (1.0e-8, 5.0)
    rho_bounds: tuple[float, float] = (-0.999, 0.999)
    m_bounds: tuple[float, float] = (-1.0, 1.0)
    sigma_bounds: tuple[float, float] = (0.002, 2.0)
    boundary_fraction: float = 1.0e-4

    def __post_init__(self) -> None:
        if self.min_dte_days < 1 or self.max_dte_days < self.min_dte_days:
            raise ValueError("invalid DTE range")
        if not (0.0 < self.max_abs_log_moneyness <= 2.0):
            raise ValueError("max_abs_log_moneyness must be in (0, 2]")
        if not (0.0 < self.min_iv_percent < self.max_iv_percent):
            raise ValueError("invalid IV-percent bounds")
        if self.min_unique_strikes < 5:
            raise ValueError("min_unique_strikes must be >= 5")
        if self.min_strikes_each_wing < 1:
            raise ValueError("min_strikes_each_wing must be >= 1")
        if not (0.0 < self.target_abs_log_moneyness < self.max_abs_log_moneyness):
            raise ValueError("target log-moneyness must be inside the fit band")
        if self.observed_target_tolerance <= 0.0:
            raise ValueError("observed_target_tolerance must be positive")
        if self.max_fit_rmse_iv_decimal <= 0.0 or self.max_fit_error_iv_decimal <= 0.0:
            raise ValueError("fit error limits must be positive")
        if self.butterfly_grid_points < 11:
            raise ValueError("butterfly_grid_points must be >= 11")
        if self.butterfly_check_abs_log_moneyness < self.max_abs_log_moneyness:
            raise ValueError("butterfly check band must cover the fit band")
        for name, bounds in (
            ("a", self.a_bounds),
            ("b", self.b_bounds),
            ("rho", self.rho_bounds),
            ("m", self.m_bounds),
            ("sigma", self.sigma_bounds),
        ):
            if len(bounds) != 2 or not bounds[0] < bounds[1]:
                raise ValueError(f"invalid {name} bounds")


@dataclass(frozen=True)
class SVIParameters:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def as_dict(self) -> dict[str, float]:
        return {
            "a": float(self.a),
            "b": float(self.b),
            "rho": float(self.rho),
            "m": float(self.m),
            "sigma": float(self.sigma),
        }


@dataclass(frozen=True)
class SVIFitResult:
    success: bool
    reason: str
    parameters: SVIParameters | None
    objective_total_variance_mse: float | None = None
    rmse_iv_decimal: float | None = None
    max_abs_error_iv_decimal: float | None = None
    min_sampled_total_variance: float | None = None
    min_sampled_butterfly_g: float | None = None
    boundary_hits: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "fit_success": self.success,
            "fit_reason": self.reason,
            "svi_parameters": (
                self.parameters.as_dict() if self.parameters is not None else None
            ),
            "fit_objective_total_variance_mse": self.objective_total_variance_mse,
            "fit_rmse_iv_decimal": self.rmse_iv_decimal,
            "fit_max_abs_error_iv_decimal": self.max_abs_error_iv_decimal,
            "min_sampled_total_variance": self.min_sampled_total_variance,
            "min_sampled_butterfly_g": self.min_sampled_butterfly_g,
            "boundary_hits": list(self.boundary_hits),
        }


@dataclass(frozen=True)
class _Candidate:
    parameters: SVIParameters
    mse: float


def svi_total_variance(k: float, parameters: SVIParameters) -> float:
    """Raw-SVI total variance at log-moneyness ``k``."""
    x = float(k) - parameters.m
    return parameters.a + parameters.b * (
        parameters.rho * x + math.sqrt(x * x + parameters.sigma**2)
    )


def svi_first_derivative(k: float, parameters: SVIParameters) -> float:
    x = float(k) - parameters.m
    root = math.sqrt(x * x + parameters.sigma**2)
    return parameters.b * (parameters.rho + x / root)


def svi_second_derivative(k: float, parameters: SVIParameters) -> float:
    x = float(k) - parameters.m
    return (
        parameters.b
        * parameters.sigma**2
        / ((x * x + parameters.sigma**2) ** 1.5)
    )


def svi_butterfly_g(k: float, parameters: SVIParameters) -> float:
    """Gatheral-Jacquier density diagnostic; non-negative means no butterfly."""
    w = svi_total_variance(k, parameters)
    if not math.isfinite(w) or w <= 0.0:
        return float("-inf")
    wp = svi_first_derivative(k, parameters)
    wpp = svi_second_derivative(k, parameters)
    return (
        (1.0 - (float(k) * wp) / (2.0 * w)) ** 2
        - (wp * wp / 4.0) * (1.0 / w + 0.25)
        + wpp / 2.0
    )


def _solve_3x3(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> tuple[float, float, float] | None:
    aug = [list(map(float, matrix[i])) + [float(rhs[i])] for i in range(3)]
    scale = max((abs(x) for row in aug for x in row[:-1]), default=1.0)
    eps = max(1.0, scale) * 1.0e-13
    for col in range(3):
        pivot = max(range(col, 3), key=lambda i: abs(aug[i][col]))
        if abs(aug[pivot][col]) <= eps:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        divisor = aug[col][col]
        aug[col] = [x / divisor for x in aug[col]]
        for row in range(3):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [
                aug[row][j] - factor * aug[col][j] for j in range(4)
            ]
    result = tuple(aug[i][3] for i in range(3))
    if not all(math.isfinite(x) for x in result):
        return None
    return result  # type: ignore[return-value]


def _inside(value: float, bounds: tuple[float, float]) -> bool:
    return math.isfinite(value) and bounds[0] <= value <= bounds[1]


def _conditional_candidate(
    ks: Sequence[float],
    total_variances: Sequence[float],
    *,
    m: float,
    sigma: float,
    config: SmileFitConfig,
) -> _Candidate | None:
    if not _inside(m, config.m_bounds) or not _inside(sigma, config.sigma_bounds):
        return None
    xs = [k - m for k in ks]
    roots = [math.sqrt(x * x + sigma * sigma) for x in xs]
    n = float(len(ks))
    matrix = (
        (n, sum(xs), sum(roots)),
        (sum(xs), sum(x * x for x in xs), sum(x * q for x, q in zip(xs, roots))),
        (sum(roots), sum(x * q for x, q in zip(xs, roots)), sum(q * q for q in roots)),
    )
    rhs = (
        sum(total_variances),
        sum(x * y for x, y in zip(xs, total_variances)),
        sum(q * y for q, y in zip(roots, total_variances)),
    )
    solved = _solve_3x3(matrix, rhs)
    if solved is None:
        return None
    a, c, b = solved
    if b == 0.0:
        return None
    rho = c / b
    if not all(
        (
            _inside(a, config.a_bounds),
            _inside(b, config.b_bounds),
            _inside(rho, config.rho_bounds),
        )
    ):
        return None
    params = SVIParameters(a=a, b=b, rho=rho, m=m, sigma=sigma)
    predictions = [svi_total_variance(k, params) for k in ks]
    if not all(math.isfinite(w) for w in predictions):
        return None
    mse = sum((actual - fitted) ** 2 for actual, fitted in zip(total_variances, predictions)) / len(ks)
    return _Candidate(params, mse)


def _boundary_hits(parameters: SVIParameters, config: SmileFitConfig) -> tuple[str, ...]:
    hits: list[str] = []
    for name, bounds in (
        ("a", config.a_bounds),
        ("b", config.b_bounds),
        ("rho", config.rho_bounds),
        ("m", config.m_bounds),
        ("sigma", config.sigma_bounds),
    ):
        value = float(getattr(parameters, name))
        margin = (bounds[1] - bounds[0]) * config.boundary_fraction
        if value - bounds[0] <= margin:
            hits.append(f"{name}_lower")
        if bounds[1] - value <= margin:
            hits.append(f"{name}_upper")
    return tuple(hits)


def _linspace(start: float, stop: float, count: int) -> list[float]:
    if count <= 1:
        return [float(start)]
    step = (stop - start) / (count - 1)
    return [start + step * i for i in range(count)]


def _best_candidate(
    ks: Sequence[float],
    total_variances: Sequence[float],
    config: SmileFitConfig,
) -> _Candidate | None:
    k_min, k_max = min(ks), max(ks)
    m_lo = max(config.m_bounds[0], k_min - 0.25)
    m_hi = min(config.m_bounds[1], k_max + 0.25)
    sigma_grid = (
        0.005,
        0.01,
        0.02,
        0.04,
        0.07,
        0.11,
        0.17,
        0.26,
        0.40,
        0.65,
        1.0,
        1.6,
    )
    best: _Candidate | None = None
    for m in _linspace(m_lo, m_hi, 19):
        for sigma in sigma_grid:
            candidate = _conditional_candidate(
                ks, total_variances, m=m, sigma=sigma, config=config
            )
            if candidate is not None and (best is None or candidate.mse < best.mse):
                best = candidate
    if best is None:
        return None

    # Deterministic pattern search over the two non-linear parameters.  For a
    # fixed (m, sigma), (a, b*rho, b) are solved exactly by linear least squares.
    dm = max((m_hi - m_lo) / 12.0, 0.01)
    dlog_sigma = 0.35
    for _ in range(80):
        p = best.parameters
        log_sigma = math.log(p.sigma)
        improved = best
        for m_shift, sigma_shift in (
            (-dm, 0.0),
            (dm, 0.0),
            (0.0, -dlog_sigma),
            (0.0, dlog_sigma),
            (-dm, -dlog_sigma),
            (-dm, dlog_sigma),
            (dm, -dlog_sigma),
            (dm, dlog_sigma),
        ):
            candidate = _conditional_candidate(
                ks,
                total_variances,
                m=p.m + m_shift,
                sigma=math.exp(log_sigma + sigma_shift),
                config=config,
            )
            if candidate is not None and candidate.mse < improved.mse:
                improved = candidate
        if improved is best:
            dm *= 0.5
            dlog_sigma *= 0.5
            if dm < 1.0e-7 and dlog_sigma < 1.0e-7:
                break
        else:
            best = improved
    return best


def fit_raw_svi(
    log_moneyness: Sequence[float],
    iv_decimal: Sequence[float],
    maturity_years: float,
    *,
    config: SmileFitConfig | None = None,
) -> SVIFitResult:
    """Fit and validate one raw-SVI slice without third-party optimisers."""
    cfg = config or SmileFitConfig()
    if len(log_moneyness) != len(iv_decimal):
        return SVIFitResult(False, "length_mismatch", None)
    if len(log_moneyness) < cfg.min_unique_strikes:
        return SVIFitResult(False, "insufficient_unique_strikes", None)
    t = float(maturity_years)
    if not math.isfinite(t) or t <= 0.0:
        return SVIFitResult(False, "invalid_maturity", None)
    observations = sorted(
        (float(k), float(iv)) for k, iv in zip(log_moneyness, iv_decimal)
    )
    if not all(math.isfinite(k) and math.isfinite(iv) and iv > 0.0 for k, iv in observations):
        return SVIFitResult(False, "non_finite_observation", None)
    if len({k for k, _ in observations}) != len(observations):
        return SVIFitResult(False, "duplicate_log_moneyness", None)
    ks = [k for k, _ in observations]
    ivs = [iv for _, iv in observations]
    total_variances = [iv * iv * t for iv in ivs]
    best = _best_candidate(ks, total_variances, cfg)
    if best is None:
        return SVIFitResult(False, "bounded_fit_unavailable", None)

    params = best.parameters
    hits = _boundary_hits(params, cfg)
    grid = _linspace(
        -cfg.butterfly_check_abs_log_moneyness,
        cfg.butterfly_check_abs_log_moneyness,
        cfg.butterfly_grid_points,
    )
    sampled_w = [svi_total_variance(k, params) for k in grid]
    sampled_g = [svi_butterfly_g(k, params) for k in grid]
    min_w = min(sampled_w)
    min_g = min(sampled_g)
    fitted_ivs: list[float] = []
    for k in ks:
        w = svi_total_variance(k, params)
        if not math.isfinite(w) or w <= 0.0:
            return SVIFitResult(
                False,
                "non_positive_fitted_total_variance",
                None,
                best.mse,
                min_sampled_total_variance=min_w,
                min_sampled_butterfly_g=min_g,
                boundary_hits=hits,
            )
        fitted_ivs.append(math.sqrt(w / t))
    errors = [fitted - actual for fitted, actual in zip(fitted_ivs, ivs)]
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    max_error = max(abs(error) for error in errors)

    reason = "ok"
    success = True
    if not all(math.isfinite(x) for x in (*params.as_dict().values(), min_w, min_g, rmse, max_error)):
        reason, success = "non_finite_fit_diagnostic", False
    elif min_w <= cfg.min_total_variance:
        reason, success = "non_positive_sampled_total_variance", False
    elif min_g < -cfg.butterfly_tolerance:
        reason, success = "butterfly_arbitrage", False
    elif rmse > cfg.max_fit_rmse_iv_decimal:
        reason, success = "fit_rmse_exceeded", False
    elif max_error > cfg.max_fit_error_iv_decimal:
        reason, success = "fit_max_error_exceeded", False
    elif hits and cfg.reject_boundary_hits:
        reason, success = "parameter_boundary_hit", False

    return SVIFitResult(
        success=success,
        reason=reason,
        parameters=params if success else None,
        objective_total_variance_mse=best.mse,
        rmse_iv_decimal=rmse,
        max_abs_error_iv_decimal=max_error,
        min_sampled_total_variance=min_w,
        min_sampled_butterfly_g=min_g,
        boundary_hits=hits,
    )


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values))


def _expiry_for_row(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    if row.get("sqd"):
        return str(row["sqd"])[:10], "sqd"
    if row.get("ltd"):
        return str(row["ltd"])[:10], "ltd"
    return None, None


def _dte_days(observation_date: str, expiry: str) -> int | None:
    try:
        return (_date.fromisoformat(expiry) - _date.fromisoformat(observation_date)).days
    except ValueError:
        return None


def _prefer_settlement_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], str]:
    settled = [r for r in rows if r.get("em_mrgn_trg_div") == EM_SETTLE]
    if settled:
        return settled, EM_SETTLE
    blank = [r for r in rows if not r.get("em_mrgn_trg_div")]
    if blank:
        return blank, "blank"
    return list(rows), "all_available"


def _empty_slice(
    *,
    date: str,
    cm: str | None,
    expiry: str,
    expiry_source: str,
    dte_days: int | None,
    reason: str,
    n_input_rows: int,
    settlement_preference: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": date,
        "cm": cm,
        "expiry": expiry,
        "expiry_source": expiry_source,
        "dte_days": dte_days,
        "maturity_years": dte_days / 365.0 if dte_days is not None else None,
        "fit_success": False,
        "fit_reason": reason,
        "n_input_rows": n_input_rows,
        "settlement_preference": settlement_preference,
        "version": OPTIONS_225_SMILE_FEATURE_VERSION,
        "parameterisation": SVI_PARAMETERISATION,
        "gap_policy": GAP_POLICY,
        "ffill_applied": False,
        "interpolation_applied": False,
        "invented_strikes": False,
    }
    if extra:
        row.update(extra)
    return row


def _strike_observations(
    rows: Sequence[Mapping[str, Any]],
    *,
    under_px: float,
    config: SmileFitConfig,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    values: dict[float, dict[str, list[float]]] = defaultdict(
        lambda: {PC_PUT: [], PC_CALL: []}
    )
    n_valid_rows = 0
    for row in rows:
        strike = row.get("strike")
        iv_percent = row.get("iv")
        pc = row.get("pc_div")
        if strike is None or iv_percent is None or pc not in {PC_PUT, PC_CALL}:
            continue
        strike_f = float(strike)
        iv_percent_f = float(iv_percent)
        if (
            not math.isfinite(strike_f)
            or strike_f <= 0.0
            or not math.isfinite(iv_percent_f)
            or not config.min_iv_percent <= iv_percent_f <= config.max_iv_percent
        ):
            continue
        k = math.log(strike_f / under_px)
        if not math.isfinite(k) or abs(k) > config.max_abs_log_moneyness:
            continue
        values[strike_f][str(pc)].append(iv_percent_f / 100.0)
        n_valid_rows += 1

    observations: list[dict[str, Any]] = []
    paired = 0
    for strike in sorted(values):
        put_values = values[strike][PC_PUT]
        call_values = values[strike][PC_CALL]
        put_iv = _median(put_values) if put_values else None
        call_iv = _median(call_values) if call_values else None
        if put_iv is not None and call_iv is not None:
            iv = (put_iv + call_iv) / 2.0
            source = "put_call_median_average"
            paired += 1
        elif put_iv is not None:
            iv, source = put_iv, "put_median_only"
        elif call_iv is not None:
            iv, source = call_iv, "call_median_only"
        else:
            continue
        observations.append(
            {
                "strike": strike,
                "log_moneyness": math.log(strike / under_px),
                "iv_decimal": iv,
                "put_iv_decimal": put_iv,
                "call_iv_decimal": call_iv,
                "iv_source": source,
            }
        )
    return observations, {
        "n_valid_iv_rows": n_valid_rows,
        "n_unique_strikes": len(observations),
        "n_paired_pc_strikes": paired,
        "n_left_strikes": sum(o["log_moneyness"] < 0.0 for o in observations),
        "n_right_strikes": sum(o["log_moneyness"] > 0.0 for o in observations),
    }


def _nearest_observed(
    observations: Sequence[Mapping[str, Any]],
    target: float,
    tolerance: float,
    *,
    side: str | None = None,
) -> Mapping[str, Any] | None:
    eligible = []
    for observation in observations:
        k = float(observation["log_moneyness"])
        if side == "left" and k >= 0.0:
            continue
        if side == "right" and k <= 0.0:
            continue
        if abs(k - target) <= tolerance:
            eligible.append(observation)
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda o: (
            abs(float(o["log_moneyness"]) - target),
            float(o["strike"]),
        ),
    )


def _observed_features(
    observations: Sequence[Mapping[str, Any]], config: SmileFitConfig
) -> dict[str, Any]:
    target = config.target_abs_log_moneyness
    tolerance = config.observed_target_tolerance
    atm = _nearest_observed(observations, 0.0, tolerance)
    left = _nearest_observed(observations, -target, tolerance, side="left")
    right = _nearest_observed(observations, target, tolerance, side="right")
    out: dict[str, Any] = {
        "observed_target_abs_log_moneyness": target,
        "observed_strike_tolerance": tolerance,
        "observed_atm_iv_decimal": None,
        "observed_left_iv_decimal": None,
        "observed_right_iv_decimal": None,
        "observed_atm_log_moneyness": None,
        "observed_left_log_moneyness": None,
        "observed_right_log_moneyness": None,
        "observed_rr_over_atm": None,
        "observed_bf_over_atm": None,
        "observed_feature_success": False,
        "observed_feature_reason": "listed_target_unavailable",
        "observed_convention": OBSERVED_SMILE_CONVENTION,
    }
    if atm is None or left is None or right is None:
        return out
    atm_iv = float(atm["iv_decimal"])
    left_iv = float(left["iv_decimal"])
    right_iv = float(right["iv_decimal"])
    if atm_iv <= 0.0:
        out["observed_feature_reason"] = "non_positive_atm_iv"
        return out
    out.update(
        {
            "observed_atm_iv_decimal": atm_iv,
            "observed_left_iv_decimal": left_iv,
            "observed_right_iv_decimal": right_iv,
            "observed_atm_log_moneyness": float(atm["log_moneyness"]),
            "observed_left_log_moneyness": float(left["log_moneyness"]),
            "observed_right_log_moneyness": float(right["log_moneyness"]),
            "observed_rr_over_atm": (right_iv - left_iv) / atm_iv,
            "observed_bf_over_atm": ((left_iv + right_iv) / 2.0 - atm_iv) / atm_iv,
            "observed_feature_success": True,
            "observed_feature_reason": "ok",
        }
    )
    return out


def _svi_features(
    parameters: SVIParameters,
    maturity_years: float,
    config: SmileFitConfig,
) -> dict[str, float]:
    target = config.target_abs_log_moneyness

    def fitted_iv(k: float) -> float:
        return math.sqrt(svi_total_variance(k, parameters) / maturity_years)

    atm_iv = fitted_iv(0.0)
    left_iv = fitted_iv(-target)
    right_iv = fitted_iv(target)
    left_slope = parameters.b * (1.0 - parameters.rho)
    right_slope = parameters.b * (1.0 + parameters.rho)
    curvature = svi_second_derivative(0.0, parameters)
    atm_variance = svi_total_variance(0.0, parameters)
    return {
        "svi_target_abs_log_moneyness": target,
        "svi_atm_iv_decimal": atm_iv,
        "svi_left_iv_decimal": left_iv,
        "svi_right_iv_decimal": right_iv,
        "svi_log_left_right_slope_ratio": math.log(left_slope / right_slope),
        "svi_atm_normalized_curvature": curvature / atm_variance,
        "svi_rr_over_atm": (right_iv - left_iv) / atm_iv,
        "svi_bf_over_atm": ((left_iv + right_iv) / 2.0 - atm_iv) / atm_iv,
    }


def build_options_225_smile_slices(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    config: SmileFitConfig | None = None,
) -> list[dict[str, Any]]:
    """Build diagnostic rows for every observed date/CM/expiry slice."""
    cfg = config or SmileFitConfig()
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        norm = normalize_options_225_row(raw)
        if norm is not None:
            by_date[str(norm["date"])].append(norm)

    output: list[dict[str, Any]] = []
    for date in sorted(by_date):
        if date < IV_FIELDS_AVAILABLE_FROM:
            continue
        preferred, settlement_rule = _prefer_settlement_rows(by_date[date])
        groups: dict[tuple[str | None, str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for row in preferred:
            expiry, expiry_source = _expiry_for_row(row)
            if expiry is None or expiry_source is None:
                continue
            groups[(row.get("cm"), expiry, expiry_source)].append(row)

        for (cm, expiry, expiry_source), group in sorted(
            groups.items(), key=lambda item: (item[0][1], str(item[0][0] or ""))
        ):
            dte = _dte_days(date, expiry)
            if dte is None or not cfg.min_dte_days <= dte <= cfg.max_dte_days:
                output.append(
                    _empty_slice(
                        date=date,
                        cm=cm,
                        expiry=expiry,
                        expiry_source=expiry_source,
                        dte_days=dte,
                        reason="dte_out_of_bounds",
                        n_input_rows=len(group),
                        settlement_preference=settlement_rule,
                    )
                )
                continue
            unders = [
                float(row["under_px"])
                for row in group
                if row.get("under_px") is not None
                and math.isfinite(float(row["under_px"]))
                and float(row["under_px"]) > 0.0
            ]
            if not unders:
                output.append(
                    _empty_slice(
                        date=date,
                        cm=cm,
                        expiry=expiry,
                        expiry_source=expiry_source,
                        dte_days=dte,
                        reason="missing_positive_under_px",
                        n_input_rows=len(group),
                        settlement_preference=settlement_rule,
                    )
                )
                continue
            under_px = _median(unders)
            observations, counts = _strike_observations(
                group, under_px=under_px, config=cfg
            )
            common = {
                "under_px": under_px,
                **counts,
                "iv_input_unit": "percent",
                "iv_fit_unit": "decimal",
                "k_definition": "ln(strike/under_px)",
                "moneyness_proxy": "under_px_not_forward",
                "forward_adjustment_applied": False,
                "maturity_definition": "calendar_days_to_sqd_else_ltd/365",
            }
            if counts["n_unique_strikes"] < cfg.min_unique_strikes:
                output.append(
                    _empty_slice(
                        date=date,
                        cm=cm,
                        expiry=expiry,
                        expiry_source=expiry_source,
                        dte_days=dte,
                        reason="insufficient_unique_strikes",
                        n_input_rows=len(group),
                        settlement_preference=settlement_rule,
                        extra=common,
                    )
                )
                continue
            if (
                counts["n_left_strikes"] < cfg.min_strikes_each_wing
                or counts["n_right_strikes"] < cfg.min_strikes_each_wing
            ):
                output.append(
                    _empty_slice(
                        date=date,
                        cm=cm,
                        expiry=expiry,
                        expiry_source=expiry_source,
                        dte_days=dte,
                        reason="insufficient_strikes_both_wings",
                        n_input_rows=len(group),
                        settlement_preference=settlement_rule,
                        extra=common,
                    )
                )
                continue

            maturity = dte / 365.0
            fit = fit_raw_svi(
                [float(o["log_moneyness"]) for o in observations],
                [float(o["iv_decimal"]) for o in observations],
                maturity,
                config=cfg,
            )
            result = _empty_slice(
                date=date,
                cm=cm,
                expiry=expiry,
                expiry_source=expiry_source,
                dte_days=dte,
                reason=fit.reason,
                n_input_rows=len(group),
                settlement_preference=settlement_rule,
                extra=common,
            )
            result.update(fit.as_dict())
            result["fit_success"] = fit.success
            result["fit_reason"] = fit.reason
            if fit.success and fit.parameters is not None:
                result.update(_observed_features(observations, cfg))
                result.update(_svi_features(fit.parameters, maturity, cfg))
            output.append(result)
    return output


def _ratio_minus_one(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None:
        return None
    n, d = float(numerator), float(denominator)
    if not math.isfinite(n) or not math.isfinite(d) or d <= 0.0:
        return None
    return n / d - 1.0


def _difference(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    a, b = float(left), float(right)
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    return a - b


def build_daily_options_225_smile_features(
    rows: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    config: SmileFitConfig | None = None,
) -> list[dict[str, Any]]:
    """Select the two shortest valid slices and emit one fail-closed daily row.

    The front slice supplies the direct and SVI smile features.  If a next
    valid expiry exists, positive quantities use ``short / next - 1`` and
    signed RR/BF quantities use ``short - next``.  Failed maturities are never
    substituted into either leg.
    """
    cfg = config or SmileFitConfig()
    slices = build_options_225_smile_slices(rows, config=cfg)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in slices:
        by_date[str(row["date"])].append(row)

    output: list[dict[str, Any]] = []
    for date in sorted(by_date):
        all_slices = sorted(
            by_date[date],
            key=lambda row: (
                int(row["dte_days"]) if row.get("dte_days") is not None else 10**9,
                str(row.get("expiry") or ""),
                str(row.get("cm") or ""),
            ),
        )
        valid = [row for row in all_slices if row.get("fit_success") is True]
        if not valid:
            output.append(
                {
                    "date": date,
                    "fit_success": False,
                    "fit_reason": "no_valid_maturity",
                    "n_maturity_slices": len(all_slices),
                    "n_valid_maturity_slices": 0,
                    "failed_slice_reasons": [
                        str(row.get("fit_reason") or "unknown") for row in all_slices
                    ],
                    "version": OPTIONS_225_SMILE_FEATURE_VERSION,
                    "gap_policy": GAP_POLICY,
                    "ffill_applied": False,
                    "interpolation_applied": False,
                    "invented_strikes": False,
                }
            )
            continue

        front = dict(valid[0])
        front.update(
            {
                "fit_scope": "shortest_valid_maturity",
                "n_maturity_slices": len(all_slices),
                "n_valid_maturity_slices": len(valid),
                "n_failed_maturity_slices": len(all_slices) - len(valid),
                "next_cm": None,
                "next_expiry": None,
                "next_dte_days": None,
                "svi_atm_short_over_next_minus_one": None,
                "svi_curvature_short_over_next_minus_one": None,
                "svi_left_right_slope_ratio_short_over_next_minus_one": None,
                "svi_rr_over_atm_short_minus_next": None,
                "svi_bf_over_atm_short_minus_next": None,
                "observed_atm_short_over_next_minus_one": None,
                "observed_rr_over_atm_short_minus_next": None,
                "observed_bf_over_atm_short_minus_next": None,
            }
        )
        if len(valid) >= 2:
            nxt = valid[1]
            front.update(
                {
                    "next_cm": nxt.get("cm"),
                    "next_expiry": nxt.get("expiry"),
                    "next_dte_days": nxt.get("dte_days"),
                    "svi_atm_short_over_next_minus_one": _ratio_minus_one(
                        front.get("svi_atm_iv_decimal"),
                        nxt.get("svi_atm_iv_decimal"),
                    ),
                    "svi_curvature_short_over_next_minus_one": _ratio_minus_one(
                        front.get("svi_atm_normalized_curvature"),
                        nxt.get("svi_atm_normalized_curvature"),
                    ),
                    "svi_left_right_slope_ratio_short_over_next_minus_one": _ratio_minus_one(
                        math.exp(float(front["svi_log_left_right_slope_ratio"])),
                        math.exp(float(nxt["svi_log_left_right_slope_ratio"])),
                    ),
                    "svi_rr_over_atm_short_minus_next": _difference(
                        front.get("svi_rr_over_atm"), nxt.get("svi_rr_over_atm")
                    ),
                    "svi_bf_over_atm_short_minus_next": _difference(
                        front.get("svi_bf_over_atm"), nxt.get("svi_bf_over_atm")
                    ),
                    "observed_atm_short_over_next_minus_one": _ratio_minus_one(
                        front.get("observed_atm_iv_decimal"),
                        nxt.get("observed_atm_iv_decimal"),
                    ),
                    "observed_rr_over_atm_short_minus_next": _difference(
                        front.get("observed_rr_over_atm"),
                        nxt.get("observed_rr_over_atm"),
                    ),
                    "observed_bf_over_atm_short_minus_next": _difference(
                        front.get("observed_bf_over_atm"),
                        nxt.get("observed_bf_over_atm"),
                    ),
                }
            )
        output.append(front)
    return output


__all__ = [
    "OPTIONS_225_SMILE_FEATURE_VERSION",
    "SVI_PARAMETERISATION",
    "OBSERVED_SMILE_CONVENTION",
    "SmileFitConfig",
    "SVIParameters",
    "SVIFitResult",
    "svi_total_variance",
    "svi_first_derivative",
    "svi_second_derivative",
    "svi_butterfly_g",
    "fit_raw_svi",
    "build_options_225_smile_slices",
    "build_daily_options_225_smile_features",
]
