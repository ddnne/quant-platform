"""Statistical research metrics for class-hyp re-judge (W81 / w0816p).

Pure helpers: t-stat, Sharpe, win rate, payoff, max drawdown, optional
Calmar / IR. Used to **raise the research_candidate bar** beyond mean bp.

Definitions (disclosed)
-----------------------
* **Period-net t-stat**: one-sample t of period mean nets vs 0
  ``t = mean / (s / sqrt(n))`` with sample std (n−1).
* **Period Sharpe**: ``mean(period_net) / std(period_net)``.
  When each period is ~one independent year-window, this is already
  approximately an annualized Sharpe of *period-average* residuals.
  No extra ``sqrt(N)`` factor (that would be t-stat).
* **Trade Sharpe (optional)**: on hold-period signed returns after costs,
  ``(mean / std) * sqrt(TRADING_DAYS_PER_YEAR / hold_days)``.
* **Win rate**: share of observations with value > 0.
* **Payoff**: mean(wins) / |mean(losses)| (None if no losses).
* **Max DD**: peak-to-trough of cumulative sum of the series (fraction).
* **Calmar**: mean / |max_dd| when max_dd < 0 (period-level research).
* **IR**: vs zero benchmark → same as Sharpe on residual series.

Hard constraints
----------------
* Research-only · no READY / Mass / Phase7 / orders
* Does not un-reject S1–S5 · not simple_daily_sign
"""

from __future__ import annotations

import math
from statistics import mean, pstdev, stdev
from typing import Any, Mapping, Sequence

STATS_METRICS_VERSION: str = "research-stats-metrics/v1.1"
STATS_METRICS_WAVE: str = "W95 / w0818e"

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False
SIGNIFICANCE_CLAIMED: bool = False
EDGE_CLAIMED: bool = False

DEFAULT_TRADING_DAYS_PER_YEAR: int = 245

# ---------------------------------------------------------------------------
# W81 statistical production bar (raise beyond mean bp)
# ---------------------------------------------------------------------------
# Period-net t-stat: |t| floor. 1.5 is a research floor (not a p-value claim);
# with n=6 periods, t=1.5 is modest — below 1.0 is clearly noise.
DEFAULT_MIN_ABS_T_STAT: float = 1.5
# Period Sharpe = mean/std of period nets (≈ annual if 1 window ~ 1y).
DEFAULT_MIN_SHARPE_PERIOD: float = 0.50
# Share of periods with net > 0 (sign stability).
DEFAULT_MIN_PERIOD_WIN_RATE: float = 0.60
# Absolute count of positive-net years (alongside win-rate share).
DEFAULT_MIN_POSITIVE_PERIODS: int = 4
# Optional soft floors (documented; fail only when set and violated).
DEFAULT_MIN_PAYOFF: float | None = None  # e.g. 1.0 if enforced
DEFAULT_MAX_ABS_DRAWDOWN: float | None = None  # e.g. 0.03 if enforced

# W95 / w0818e — low-variance / inflated-t artifact gate.
# With tiny n, near-identical period nets make t = m/(s/sqrt(n)) explode
# without economic meaning (W94 fund_value_mom_agree_slow w2017_2019:
# m≈82.8bp, s≈0.76bp → t≈153). Null t and disclose reason.
LOW_VARIANCE_SMALL_N_MAX: int = 3
LOW_VARIANCE_MIN_REL_STD: float = 0.05  # require CV = s/|m| ≥ 5%
LOW_VARIANCE_MAX_ABS_T: float = 12.0
LOW_VARIANCE_REASON: str = "low_variance_artifact"


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "connected_to_ready": False,
        "connected_to_mass": False,
    }


def _finite_floats(values: Sequence[float | None]) -> list[float]:
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def sample_mean(values: Sequence[float | None]) -> float | None:
    vals = _finite_floats(values)
    if not vals:
        return None
    return float(mean(vals))


def sample_std(values: Sequence[float | None], *, ddof: int = 1) -> float | None:
    """Sample (ddof=1) or population (ddof=0) standard deviation."""
    vals = _finite_floats(values)
    n = len(vals)
    if n == 0:
        return None
    if n == 1:
        return 0.0
    if int(ddof) <= 0:
        return float(pstdev(vals))
    return float(stdev(vals))


def is_low_variance_t_artifact(
    *,
    n: int,
    mean_net: float | None,
    std_net: float | None,
    t_stat: float | None,
    min_rel_std: float = LOW_VARIANCE_MIN_REL_STD,
    max_abs_t: float = LOW_VARIANCE_MAX_ABS_T,
    small_n_max: int = LOW_VARIANCE_SMALL_N_MAX,
) -> bool:
    """True when small-n near-identical nets would inflate |t| without meaning."""
    if n < 2 or n > int(small_n_max):
        return False
    if mean_net is None or std_net is None or t_stat is None:
        return False
    if not (math.isfinite(mean_net) and math.isfinite(std_net) and math.isfinite(t_stat)):
        return False
    abs_m = abs(float(mean_net))
    if abs_m <= 0.0:
        return False
    cv = float(std_net) / abs_m
    # Strict: near-identical nets (CV below floor) AND implausibly large |t|.
    # Do not loosen CV to 2× floor — that false-positives mild pairs
    # (e.g. macro_repo_rate_level 2021≈2025 with CV≈9%).
    return bool(cv < float(min_rel_std) and abs(float(t_stat)) > float(max_abs_t))


def has_pairwise_low_variance_artifact(
    values: Sequence[float | None],
) -> bool:
    """True if any 2-period subset trips the low-variance inflated-t gate."""
    vals = _finite_floats(values)
    if len(vals) < 2:
        return False
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            if t_stat_vs_zero([vals[i], vals[j]]).get("reason") == LOW_VARIANCE_REASON:
                return True
    return False


def t_stat_vs_zero(values: Sequence[float | None]) -> dict[str, Any]:
    """One-sample t-stat of values vs 0 (sample std).

    ``t = mean / (s / sqrt(n))``. Empty / zero-std → t None.
    W95: small-n low-variance (near-identical period nets) → t None with
    ``reason=low_variance_artifact`` (raw_t retained for audit).
    """
    vals = _finite_floats(values)
    n = len(vals)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            "se": None,
            "t_stat": None,
            "abs_t_stat": None,
            "reason": "no_values",
        }
    m = float(mean(vals))
    if n == 1:
        return {
            "n": 1,
            "mean": m,
            "std": 0.0,
            "se": None,
            "t_stat": None,
            "abs_t_stat": None,
            "reason": "n_lt_2",
        }
    s = float(stdev(vals))
    if s == 0.0:
        # Exact zero std on n>=2 is the extreme low-variance artifact.
        # Do not emit ±inf into screens / rankings.
        return {
            "n": n,
            "mean": m,
            "std": 0.0,
            "se": 0.0,
            "t_stat": None,
            "abs_t_stat": None,
            "raw_t_stat": None if m == 0.0 else (math.inf if m > 0 else -math.inf),
            "reason": LOW_VARIANCE_REASON if m != 0.0 else "zero_std",
            "cv": 0.0,
        }
    se = s / math.sqrt(float(n))
    t = m / se
    cv = s / abs(m) if m != 0.0 else None
    if is_low_variance_t_artifact(n=n, mean_net=m, std_net=s, t_stat=t):
        return {
            "n": n,
            "mean": m,
            "std": s,
            "se": se,
            "t_stat": None,
            "abs_t_stat": None,
            "raw_t_stat": t,
            "cv": cv,
            "reason": LOW_VARIANCE_REASON,
            "formula": "t = mean / (s / sqrt(n)), sample std ddof=1",
            "gate": {
                "min_rel_std": LOW_VARIANCE_MIN_REL_STD,
                "max_abs_t": LOW_VARIANCE_MAX_ABS_T,
                "small_n_max": LOW_VARIANCE_SMALL_N_MAX,
            },
        }
    return {
        "n": n,
        "mean": m,
        "std": s,
        "se": se,
        "t_stat": t,
        "abs_t_stat": abs(t),
        "raw_t_stat": t,
        "cv": cv,
        "reason": "ok",
        "formula": "t = mean / (s / sqrt(n)), sample std ddof=1",
    }


def sharpe_ratio(
    values: Sequence[float | None],
    *,
    periods_per_year: float = 1.0,
    risk_free: float = 0.0,
    ddof: int = 1,
) -> dict[str, Any]:
    """Sharpe = (mean − rf) / std * sqrt(periods_per_year).

    * Period nets with one year-window per observation → ``periods_per_year=1``
      (no extra annualization).
    * Hold-period trade returns of length H sessions →
      ``periods_per_year = TRADING_DAYS_PER_YEAR / H``.
    """
    vals = _finite_floats(values)
    n = len(vals)
    ppy = float(periods_per_year)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            "sharpe": None,
            "periods_per_year": ppy,
            "reason": "no_values",
        }
    m = float(mean(vals)) - float(risk_free)
    if n == 1:
        return {
            "n": 1,
            "mean": m + float(risk_free),
            "std": 0.0,
            "sharpe": None,
            "periods_per_year": ppy,
            "reason": "n_lt_2",
        }
    s = float(stdev(vals)) if ddof == 1 else float(pstdev(vals))
    if s == 0.0:
        return {
            "n": n,
            "mean": m + float(risk_free),
            "std": 0.0,
            "sharpe": None,
            "periods_per_year": ppy,
            "reason": "zero_std",
        }
    raw = m / s
    ann = raw * math.sqrt(ppy) if ppy > 0 else raw
    return {
        "n": n,
        "mean": m + float(risk_free),
        "excess_mean": m,
        "std": s,
        "sharpe_raw": raw,
        "sharpe": ann,
        "periods_per_year": ppy,
        "risk_free": float(risk_free),
        "reason": "ok",
        "formula": (
            "sharpe = (mean - rf) / std * sqrt(periods_per_year); "
            "period nets use periods_per_year=1"
        ),
    }


def win_rate(values: Sequence[float | None]) -> dict[str, Any]:
    """Share of observations with value > 0 (zeros count as non-win)."""
    vals = _finite_floats(values)
    n = len(vals)
    if n == 0:
        return {
            "n": 0,
            "n_pos": 0,
            "n_neg": 0,
            "n_zero": 0,
            "win_rate": None,
            "reason": "no_values",
        }
    n_pos = sum(1 for v in vals if v > 0)
    n_neg = sum(1 for v in vals if v < 0)
    n_zero = n - n_pos - n_neg
    return {
        "n": n,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n_zero": n_zero,
        "win_rate": float(n_pos) / float(n),
        "reason": "ok",
    }


def payoff_ratio(values: Sequence[float | None]) -> dict[str, Any]:
    """mean(wins) / |mean(losses)|. None if no wins or no losses."""
    vals = _finite_floats(values)
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v < 0]
    if not wins or not losses:
        return {
            "n_wins": len(wins),
            "n_losses": len(losses),
            "mean_win": float(mean(wins)) if wins else None,
            "mean_loss": float(mean(losses)) if losses else None,
            "payoff": None,
            "reason": "missing_wins_or_losses",
        }
    mw = float(mean(wins))
    ml = float(mean(losses))
    payoff = mw / abs(ml) if ml != 0 else None
    return {
        "n_wins": len(wins),
        "n_losses": len(losses),
        "mean_win": mw,
        "mean_loss": ml,
        "payoff": payoff,
        "reason": "ok" if payoff is not None else "zero_mean_loss",
    }


def max_drawdown(values: Sequence[float | None]) -> dict[str, Any]:
    """Max peak-to-trough of cumulative sum of the series.

    Returns ``max_dd`` as a non-positive number (0 if never draws down).
    """
    vals = _finite_floats(values)
    if not vals:
        return {
            "n": 0,
            "max_dd": None,
            "peak_index": None,
            "trough_index": None,
            "reason": "no_values",
        }
    cum = 0.0
    peak = 0.0
    peak_i = -1
    max_dd = 0.0
    trough_i = -1
    peak_at_dd = -1
    for i, v in enumerate(vals):
        cum += v
        if cum > peak:
            peak = cum
            peak_i = i
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd
            trough_i = i
            peak_at_dd = peak_i
    return {
        "n": len(vals),
        "max_dd": float(max_dd),
        "abs_max_dd": abs(float(max_dd)),
        "peak_index": peak_at_dd if trough_i >= 0 else None,
        "trough_index": trough_i if trough_i >= 0 else None,
        "final_cumulative": cum,
        "reason": "ok",
        "note": "DD on cumulative sum of series (period nets or trade nets)",
    }


def calmar_ratio(
    mean_return: float | None,
    max_dd: float | None,
) -> float | None:
    """mean_return / |max_dd| when max_dd < 0; else None."""
    if mean_return is None or max_dd is None:
        return None
    if max_dd >= 0:
        return None
    return float(mean_return) / abs(float(max_dd))


def information_ratio(
    values: Sequence[float | None],
    *,
    benchmark: float = 0.0,
    periods_per_year: float = 1.0,
) -> dict[str, Any]:
    """IR vs constant benchmark (default 0 → same scale as Sharpe)."""
    vals = _finite_floats(values)
    residual = [v - float(benchmark) for v in vals]
    sh = sharpe_ratio(residual, periods_per_year=periods_per_year, risk_free=0.0)
    return {
        "benchmark": float(benchmark),
        "information_ratio": sh.get("sharpe"),
        "n": sh.get("n"),
        "tracking_error": sh.get("std"),
        "excess_mean": sh.get("excess_mean"),
        "periods_per_year": float(periods_per_year),
        "reason": sh.get("reason"),
        "note": "IR vs constant benchmark; benchmark=0 matches period Sharpe",
    }


def period_stats_report(
    period_nets: Sequence[float | None],
    *,
    period_ids: Sequence[str] | None = None,
    hold_days: int | None = None,
) -> dict[str, Any]:
    """Full period-net stats pack for W81 re-judge."""
    vals = _finite_floats(period_nets)
    tpack = t_stat_vs_zero(vals)
    sh = sharpe_ratio(vals, periods_per_year=1.0)
    wr = win_rate(vals)
    pay = payoff_ratio(vals)
    dd = max_drawdown(vals)
    ir = information_ratio(vals, benchmark=0.0, periods_per_year=1.0)
    calmar = calmar_ratio(tpack.get("mean"), dd.get("max_dd"))
    out: dict[str, Any] = {
        "version": STATS_METRICS_VERSION,
        "wave": STATS_METRICS_WAVE,
        "kind": "period_nets",
        "period_ids": list(period_ids) if period_ids is not None else None,
        "period_nets": list(vals),
        "n_periods": len(vals),
        "mean_net": tpack.get("mean"),
        "std_net": tpack.get("std"),
        "t_stat": tpack.get("t_stat"),
        "abs_t_stat": tpack.get("abs_t_stat"),
        "sharpe": sh.get("sharpe"),
        "sharpe_definition": (
            "mean(period_net)/std(period_net); periods_per_year=1 "
            "(each period ~ independent year-window residual)"
        ),
        "win_rate": wr.get("win_rate"),
        "n_pos": wr.get("n_pos"),
        "n_neg": wr.get("n_neg"),
        "payoff": pay.get("payoff"),
        "max_dd": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "calmar": calmar,
        "information_ratio": ir.get("information_ratio"),
        "hold_days": int(hold_days) if hold_days is not None else None,
        "t_detail": tpack,
        "sharpe_detail": sh,
        "win_rate_detail": wr,
        "payoff_detail": pay,
        "max_dd_detail": dd,
        "ir_detail": ir,
    }
    out.update(_freeze())
    return out


def trade_stats_report(
    signed_returns: Sequence[float | None],
    *,
    hold_days: int = 1,
    one_way_cost: float = 0.0,
    amortize_cost: bool = True,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> dict[str, Any]:
    """Trade-level stats on signed hold returns (optional net of amortized cost).

    Annualization: ``periods_per_year = trading_days_per_year / hold_days``.
    """
    h = max(int(hold_days), 1)
    am = (float(one_way_cost) / float(h)) if amortize_cost else float(one_way_cost)
    nets: list[float] = []
    for v in _finite_floats(signed_returns):
        nets.append(v - am if amortize_cost or one_way_cost else v)
    # if not amortize and cost already applied by caller, signed_returns are nets
    if not amortize_cost and float(one_way_cost) == 0.0:
        nets = _finite_floats(signed_returns)

    ppy = float(trading_days_per_year) / float(h)
    tpack = t_stat_vs_zero(nets)
    sh = sharpe_ratio(nets, periods_per_year=ppy)
    wr = win_rate(nets)
    pay = payoff_ratio(nets)
    dd = max_drawdown(nets)
    calmar = calmar_ratio(tpack.get("mean"), dd.get("max_dd"))
    out: dict[str, Any] = {
        "version": STATS_METRICS_VERSION,
        "wave": STATS_METRICS_WAVE,
        "kind": "trade_signed_returns",
        "hold_days": h,
        "one_way_cost": float(one_way_cost),
        "amortized_cost_applied": bool(amortize_cost),
        "amortized_one_way_cost": am if amortize_cost else None,
        "n_trades": len(nets),
        "mean_net": tpack.get("mean"),
        "std_net": tpack.get("std"),
        "t_stat": tpack.get("t_stat"),
        "abs_t_stat": tpack.get("abs_t_stat"),
        "sharpe_ann": sh.get("sharpe"),
        "sharpe_definition": (
            f"(mean/std)*sqrt({trading_days_per_year}/{h}) on hold-period nets"
        ),
        "periods_per_year": ppy,
        "win_rate": wr.get("win_rate"),
        "n_pos": wr.get("n_pos"),
        "n_neg": wr.get("n_neg"),
        "payoff": pay.get("payoff"),
        "max_dd": dd.get("max_dd"),
        "calmar": calmar,
    }
    out.update(_freeze())
    return out


def stats_bar_check(
    stats: Mapping[str, Any],
    *,
    min_abs_t: float = DEFAULT_MIN_ABS_T_STAT,
    min_sharpe: float = DEFAULT_MIN_SHARPE_PERIOD,
    min_win_rate: float = DEFAULT_MIN_PERIOD_WIN_RATE,
    min_positive_periods: int = DEFAULT_MIN_POSITIVE_PERIODS,
    min_payoff: float | None = DEFAULT_MIN_PAYOFF,
    max_abs_dd: float | None = DEFAULT_MAX_ABS_DRAWDOWN,
) -> dict[str, Any]:
    """Evaluate W81 statistical bar against a period_stats_report (or compatible).

    All enforced floors must pass for ``stats_ok=True``.
    """
    t_signed = stats.get("t_stat")
    if t_signed is not None:
        try:
            t_signed = float(t_signed)
        except (TypeError, ValueError):
            t_signed = None
    abs_t = stats.get("abs_t_stat")
    if abs_t is None and t_signed is not None:
        abs_t = abs(float(t_signed))
    sharpe = stats.get("sharpe")
    wr = stats.get("win_rate")
    n_pos = stats.get("n_pos")
    n = stats.get("n_periods") or stats.get("n") or 0
    payoff = stats.get("payoff")
    abs_dd = stats.get("abs_max_dd")
    if abs_dd is None and stats.get("max_dd") is not None:
        try:
            abs_dd = abs(float(stats["max_dd"]))
        except (TypeError, ValueError):
            abs_dd = None

    checks: dict[str, Any] = {
        "min_t_stat_signed": float(min_abs_t),
        "min_abs_t": float(min_abs_t),
        "min_sharpe": float(min_sharpe),
        "min_win_rate": float(min_win_rate),
        "min_positive_periods": int(min_positive_periods),
        "min_payoff": min_payoff,
        "max_abs_dd": max_abs_dd,
    }
    fails: list[str] = []

    # Require *positive* edge: signed t >= floor (not just |t|).
    t_ok = bool(t_signed is not None and float(t_signed) >= float(min_abs_t))
    if not t_ok:
        fails.append("t_stat_below_min")
    sh_ok = bool(sharpe is not None and float(sharpe) >= float(min_sharpe))
    if not sh_ok:
        fails.append("sharpe_below_min")
    wr_ok = bool(wr is not None and float(wr) >= float(min_win_rate))
    if not wr_ok:
        fails.append("period_win_rate_below_min")
    pos_ok = bool(n_pos is not None and int(n_pos) >= int(min_positive_periods))
    if not pos_ok:
        fails.append("positive_periods_below_min")

    payoff_ok = True
    if min_payoff is not None:
        payoff_ok = bool(payoff is not None and float(payoff) >= float(min_payoff))
        if not payoff_ok:
            fails.append("payoff_below_min")

    dd_ok = True
    if max_abs_dd is not None:
        dd_ok = bool(abs_dd is not None and float(abs_dd) <= float(max_abs_dd))
        if not dd_ok:
            fails.append("abs_max_dd_above_max")

    # Noisy heuristic (for demote messaging; not a separate hard gate)
    noisy = bool(
        (t_signed is not None and float(t_signed) < 1.0)
        or (sharpe is not None and float(sharpe) < 0.30)
        or (wr is not None and float(wr) < 0.55)
    )

    stats_ok = bool(t_ok and sh_ok and wr_ok and pos_ok and payoff_ok and dd_ok)
    return {
        "stats_ok": stats_ok,
        "noisy": noisy and not stats_ok,
        "checks": checks,
        "observed": {
            "t_stat": t_signed,
            "abs_t_stat": abs_t,
            "sharpe": sharpe,
            "win_rate": wr,
            "n_pos": n_pos,
            "n_periods": n,
            "payoff": payoff,
            "abs_max_dd": abs_dd,
            "mean_net": stats.get("mean_net"),
            "calmar": stats.get("calmar"),
            "information_ratio": stats.get("information_ratio"),
        },
        "component_ok": {
            "t_stat": t_ok,
            "sharpe": sh_ok,
            "win_rate": wr_ok,
            "positive_periods": pos_ok,
            "payoff": payoff_ok,
            "max_dd": dd_ok,
        },
        "fails": fails,
        "note": (
            "W81 statistical bar: require signed t≥min (positive edge), "
            "Sharpe≥min, period win-rate and positive-year count. "
            "Noisy low t/Sharpe / unstable signs → demote research_candidate. "
            "Not a significance claim / not READY."
        ),
        **_freeze(),
    }


def stats_metrics_document() -> dict[str, Any]:
    """Public document for statistical bar surface."""
    doc = {
        "version": STATS_METRICS_VERSION,
        "wave": STATS_METRICS_WAVE,
        "defaults": {
            "min_abs_t_stat": DEFAULT_MIN_ABS_T_STAT,
            "min_sharpe_period": DEFAULT_MIN_SHARPE_PERIOD,
            "min_period_win_rate": DEFAULT_MIN_PERIOD_WIN_RATE,
            "min_positive_periods": DEFAULT_MIN_POSITIVE_PERIODS,
            "min_payoff": DEFAULT_MIN_PAYOFF,
            "max_abs_drawdown": DEFAULT_MAX_ABS_DRAWDOWN,
            "trading_days_per_year": DEFAULT_TRADING_DAYS_PER_YEAR,
        },
        "definitions": {
            "t_stat": "mean / (s/sqrt(n)) on period nets vs 0, sample std",
            "sharpe_period": "mean/std of period nets (periods_per_year=1)",
            "sharpe_trade": "(mean/std)*sqrt(245/hold_days) on hold nets",
            "win_rate": "share of obs with value > 0",
            "payoff": "mean(wins)/|mean(losses)|",
            "max_dd": "peak-to-trough of cumulative sum",
            "calmar": "mean / |max_dd|",
            "ir": "Sharpe of residual vs constant benchmark (default 0)",
        },
        "note": (
            "W81 raises research_candidate bar beyond mean bp. "
            "Research-only; READY/Mass/Phase7 never auto-connect."
        ),
    }
    doc.update(_freeze())
    return doc


__all__ = [
    "DEFAULT_MAX_ABS_DRAWDOWN",
    "DEFAULT_MIN_ABS_T_STAT",
    "DEFAULT_MIN_PAYOFF",
    "DEFAULT_MIN_PERIOD_WIN_RATE",
    "DEFAULT_MIN_POSITIVE_PERIODS",
    "DEFAULT_MIN_SHARPE_PERIOD",
    "DEFAULT_TRADING_DAYS_PER_YEAR",
    "STATS_METRICS_VERSION",
    "STATS_METRICS_WAVE",
    "calmar_ratio",
    "information_ratio",
    "max_drawdown",
    "payoff_ratio",
    "period_stats_report",
    "sample_mean",
    "sample_std",
    "sharpe_ratio",
    "stats_bar_check",
    "stats_metrics_document",
    "is_low_variance_t_artifact",
    "has_pairwise_low_variance_artifact",
    "t_stat_vs_zero",
    "LOW_VARIANCE_REASON",
    "LOW_VARIANCE_MIN_REL_STD",
    "LOW_VARIANCE_MAX_ABS_T",
    "LOW_VARIANCE_SMALL_N_MAX",
    "trade_stats_report",
    "win_rate",
]
