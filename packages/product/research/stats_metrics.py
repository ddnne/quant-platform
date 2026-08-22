"""Statistical research metrics (t, Sharpe, win rate, payoff, DD, Calmar).

Period t = mean / (s / sqrt(n)) with sample std. Period Sharpe uses
periods_per_year=1. Trade Sharpe annualizes by TRADING_DAYS_PER_YEAR / hold.
Research-only; does not un-reject S1–S5.
"""

from __future__ import annotations

import math
from statistics import mean, pstdev, stdev
from typing import Any, Mapping, Sequence

from features.class_signals import (
    DEFAULT_MIN_ABS_T_STAT,
    DEFAULT_MIN_PERIOD_WIN_RATE,
    DEFAULT_MIN_POSITIVE_PERIODS,
    DEFAULT_MIN_SHARPE_PERIOD,
    DEFAULT_TRADING_DAYS_PER_YEAR,
)
from features.research_freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    SIGNIFICANCE_CLAIMED,
)

STATS_METRICS_VERSION: str = "research-stats-metrics/v1.2"

DEFAULT_MIN_PAYOFF: float | None = None
DEFAULT_MAX_ABS_DRAWDOWN: float | None = None

LOW_VARIANCE_SMALL_N_MAX: int = 3
LOW_VARIANCE_MIN_REL_STD: float = 0.05
LOW_VARIANCE_MAX_ABS_T: float = 12.0
LOW_VARIANCE_REASON: str = "low_variance_artifact"

DAILY_PATH_DD_VERSION: str = "research-daily-path-dd/v1"
DAILY_PATH_DD_REQUIRED_FIELDS: tuple[str, ...] = (
    "daily_path_DD",
    "dd_duration",
    "recovery",
    "total_ret_net",
)
PERIOD_NET_ONLY_METHODS: frozenset[str] = frozenset(
    {
        "period_net_cumsum_proxy",
        "period_net_DD",
        "period_net_dd",
        "period_net",
    }
)
W99_STICKY_DAILY_PATH_DD_REFERENCE: tuple[dict[str, Any], ...] = (
    {
        "window": "w2017_2019",
        "logic_id": "xs_rank_ls_sticky",
        "daily_path_DD": -0.143741,
        "dd_duration": 85,
        "recovery_days": None,
        "recovered": False,
        "total_ret_net": 0.034975,
        "period_net_DD_w98_cf_artifact": 0.0,
    },
    {
        "window": "w2020_2022",
        "logic_id": "xs_rank_ls_sticky",
        "daily_path_DD": -0.037971,
        "dd_duration": 14,
        "recovery_days": 1,
        "recovered": True,
        "total_ret_net": 0.201923,
        "period_net_DD_w98_cf_artifact": 0.0,
    },
    {
        "window": "w2023_2025",
        "logic_id": "xs_rank_ls_sticky",
        "daily_path_DD": -0.108415,
        "dd_duration": 17,
        "recovery_days": 52,
        "recovered": True,
        "total_ret_net": 0.081073,
        "period_net_DD_w98_cf_artifact": 0.0,
    },
)


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
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
    """One-sample t vs 0: ``t = mean / (s / sqrt(n))``. Empty / zero-std → None."""
    vals = _finite_floats(values)
    n = len(vals)
    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "std": None,
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
            "t_stat": None,
            "abs_t_stat": None,
            "reason": "n_lt_2",
        }
    s = float(stdev(vals))
    if s == 0.0:
        return {
            "n": n,
            "mean": m,
            "std": 0.0,
            "t_stat": None,
            "abs_t_stat": None,
            "raw_t_stat": None if m == 0.0 else (math.inf if m > 0 else -math.inf),
            "reason": LOW_VARIANCE_REASON if m != 0.0 else "zero_std",
        }
    se = s / math.sqrt(float(n))
    t = m / se
    if is_low_variance_t_artifact(n=n, mean_net=m, std_net=s, t_stat=t):
        return {
            "n": n,
            "mean": m,
            "std": s,
            "t_stat": None,
            "abs_t_stat": None,
            "raw_t_stat": t,
            "reason": LOW_VARIANCE_REASON,
        }
    return {
        "n": n,
        "mean": m,
        "std": s,
        "t_stat": t,
        "abs_t_stat": abs(t),
        "raw_t_stat": t,
        "reason": "ok",
    }


def sharpe_ratio(
    values: Sequence[float | None],
    *,
    periods_per_year: float = 1.0,
    risk_free: float = 0.0,
    ddof: int = 1,
) -> dict[str, Any]:
    """Sharpe = (mean − rf) / std * sqrt(periods_per_year). Period nets use 1."""
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
        "std": s,
        "sharpe": ann,
        "periods_per_year": ppy,
        "reason": "ok",
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
            "win_rate": None,
            "reason": "no_values",
        }
    n_pos = sum(1 for v in vals if v > 0)
    n_neg = sum(1 for v in vals if v < 0)
    return {
        "n": n,
        "n_pos": n_pos,
        "n_neg": n_neg,
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
    """Peak-to-trough of the series cumulative sum (non-positive)."""
    vals = _finite_floats(values)
    if not vals:
        return {
            "n": 0,
            "max_dd": None,
            "reason": "no_values",
        }
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for v in vals:
        cum += v
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd
    return {
        "n": len(vals),
        "max_dd": float(max_dd),
        "abs_max_dd": abs(float(max_dd)),
        "reason": "ok",
    }


def _scalar_finite(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def equity_path_drawdown(
    equities: Sequence[float],
    dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Max DD / duration / recovery on a level equity curve (post-cost)."""
    if not equities:
        return {
            "n": 0,
            "max_dd": None,
            "abs_max_dd": None,
            "dd_duration_days": None,
            "recovery_days": None,
            "recovered": None,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "total_return": None,
            "method": "daily_equity_level_peak_to_trough",
            "reason": "empty",
        }
    eq = [float(x) for x in equities]
    peak = eq[0]
    peak_i = 0
    max_dd = 0.0
    trough_i = 0
    peak_at_dd = 0
    for i, v in enumerate(eq):
        if v > peak:
            peak = v
            peak_i = i
        if peak > 0:
            dd = v / peak - 1.0
            if dd < max_dd:
                max_dd = dd
                trough_i = i
                peak_at_dd = peak_i

    dd_duration = int(trough_i - peak_at_dd) if max_dd < 0 else 0
    recovery_days: int | None = None
    recovery_i: int | None = None
    recovered = True if max_dd >= 0 else False
    if max_dd < 0:
        peak_level = eq[peak_at_dd]
        recovered = False
        for i in range(trough_i + 1, len(eq)):
            if eq[i] >= peak_level - 1e-15:
                recovery_days = int(i - trough_i)
                recovery_i = i
                recovered = True
                break

    def _d(i: int | None) -> str | None:
        if i is None or dates is None or i < 0 or i >= len(dates):
            return None
        return str(dates[i])[:10]

    total_ret = eq[-1] / eq[0] - 1.0 if eq[0] else None
    return {
        "n": len(eq),
        "max_dd": float(max_dd),
        "abs_max_dd": abs(float(max_dd)),
        "dd_duration_days": dd_duration,
        "recovery_days": recovery_days,
        "recovered": recovered,
        "peak_date": _d(peak_at_dd) if max_dd < 0 else None,
        "trough_date": _d(trough_i) if max_dd < 0 else None,
        "recovery_date": _d(recovery_i),
        "total_return": total_ret,
        "method": "daily_equity_level_peak_to_trough",
        "reason": "ok",
    }


def _pick_first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in mapping and mapping[k] is not None:
            return mapping[k]
    return None


def _as_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def w99_sticky_daily_path_dd_reference() -> dict[str, Any]:
    """Sticky daily DD table — reference example, not a pass/promote."""
    return {
        "logic_id": "xs_rank_ls_sticky",
        "stance": "STABLE_RESEARCH_ONLY",
        "promote_as_main": False,
        "go": False,
        "windows": [dict(r) for r in W99_STICKY_DAILY_PATH_DD_REFERENCE],
    }


def evaluate_daily_path_dd_gate(
    *,
    daily_path_dd: float | Mapping[str, Any] | None = None,
    dd_duration: int | None = None,
    recovered: bool | None = None,
    recovery_days: int | None = None,
    total_ret_net: float | None = None,
    period_net_dd: float | None = None,
    daily_path_pack: Mapping[str, Any] | None = None,
    equities: Sequence[float] | None = None,
    dates: Sequence[str] | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """Mandatory daily-path DD scorecard. Period-net DD cannot pass alone."""
    pack: dict[str, Any] = {}
    if isinstance(daily_path_dd, Mapping):
        pack.update(dict(daily_path_dd))
        daily_path_dd = None
    if daily_path_pack is not None:
        pack.update(dict(daily_path_pack))

    nested = pack.get("drawdown")
    if isinstance(nested, Mapping):
        for k, v in nested.items():
            pack.setdefault(k, v)

    computed: dict[str, Any] | None = None
    if equities:
        computed = equity_path_drawdown(equities, dates)
        pack.setdefault("max_dd", computed.get("max_dd"))
        pack.setdefault("dd_duration_days", computed.get("dd_duration_days"))
        pack.setdefault("recovered", computed.get("recovered"))
        pack.setdefault("recovery_days", computed.get("recovery_days"))
        pack.setdefault("total_return", computed.get("total_return"))
        pack.setdefault("method", computed.get("method"))

    dd_val = _scalar_finite(daily_path_dd)
    if dd_val is None:
        dd_val = _scalar_finite(
            _pick_first(
                pack,
                "daily_path_DD",
                "daily_path_dd",
                "max_dd",
                "max_drawdown",
            )
        )
    dur_val = _as_int(dd_duration)
    if dur_val is None:
        dur_val = _as_int(
            _pick_first(pack, "dd_duration", "dd_duration_days", "dd_dur")
        )
    rec_flag = recovered
    if rec_flag is None:
        rec_raw = _pick_first(pack, "recovered")
        if rec_raw is None and isinstance(pack.get("recovery"), Mapping):
            rec_raw = pack["recovery"].get("recovered")
        if rec_raw is not None:
            rec_flag = bool(rec_raw)
    rec_days = _as_int(recovery_days)
    if rec_days is None:
        rec_src = _pick_first(pack, "recovery_days")
        if rec_src is None and isinstance(pack.get("recovery"), Mapping):
            rec_src = pack["recovery"].get("recovery_days")
        if rec_src is None and not isinstance(pack.get("recovery"), Mapping):
            rec_src = pack.get("recovery")
        rec_days = _as_int(rec_src)
    tot_net = _scalar_finite(total_ret_net)
    if tot_net is None:
        tot_net = _scalar_finite(
            _pick_first(
                pack,
                "total_ret_net",
                "total_return_net",
                "total_return",
            )
        )
    pdd = _scalar_finite(period_net_dd)
    if pdd is None:
        pdd = _scalar_finite(
            _pick_first(
                pack,
                "period_net_DD",
                "period_net_dd",
                "period_net_DD_w98_cf_artifact",
                "period_net_DD_local_proxy",
            )
        )

    method_s = str(
        method
        or pack.get("method")
        or (computed or {}).get("method")
        or ""
    ).strip()
    method_is_period_net = method_s in PERIOD_NET_ONLY_METHODS

    missing: list[str] = []
    if dd_val is None:
        missing.append("daily_path_DD")
    if dur_val is None:
        missing.append("dd_duration")
    if rec_flag is None:
        missing.append("recovery")
    elif rec_flag is True and rec_days is None:
        if dd_val is not None and float(dd_val) < -1e-15:
            missing.append("recovery_days")
    if tot_net is None:
        missing.append("total_ret_net")

    daily_measured = not missing and not method_is_period_net
    period_net_present = pdd is not None or method_is_period_net
    period_net_only = bool(period_net_present and not daily_measured)
    period_net_zero = pdd is not None and abs(float(pdd)) <= 1e-15
    period_net_zero_daily_unmeasured = bool(period_net_zero and not daily_measured)

    fails: list[str] = []
    warnings: list[str] = []
    if method_is_period_net:
        fails.append("period_net_DD_method_is_not_daily_path")
    if not daily_measured:
        fails.append("daily_path_DD_unmeasured")
        if missing:
            fails.append("missing_required: " + ", ".join(missing))
    if period_net_only:
        fails.append("period_net_DD_only_pass_forbidden")
        warnings.append("period_net_DD alone cannot pass; use daily_path_DD.")
    if period_net_zero_daily_unmeasured:
        fails.append("period_net_DD_zero_daily_unmeasured")
        warnings.append("period_net_DD=0 + daily unmeasured is an aggregation artifact.")
    elif period_net_zero and daily_measured:
        warnings.append("period_net_DD=0 is an aggregation artifact, not riskless.")

    complete = bool(daily_measured)
    scorecard = {
        "daily_path_DD": dd_val,
        "dd_duration": dur_val,
        "recovery": {
            "recovered": rec_flag,
            "recovery_days": rec_days,
        },
        "total_ret_net": tot_net,
        "period_net_DD": pdd,
    }
    out: dict[str, Any] = {
        "version": DAILY_PATH_DD_VERSION,
        "measured": bool(daily_measured),
        "complete": complete,
        "passed": complete,
        "daily_path_DD": dd_val,
        "dd_duration": dur_val,
        "recovery": scorecard["recovery"],
        "recovered": rec_flag,
        "recovery_days": rec_days,
        "total_ret_net": tot_net,
        "period_net_DD": pdd,
        "method": method_s or None,
        "period_net_dd_only": period_net_only,
        "period_net_dd_zero_daily_unmeasured": period_net_zero_daily_unmeasured,
        "period_net_dd_only_pass_forbidden": True,
        "missing_required": missing,
        "fails": fails,
        "warnings": warnings,
        "scorecard": scorecard,
    }
    out.update(_freeze())
    return out


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


def period_stats_report(
    period_nets: Sequence[float | None],
    *,
    period_ids: Sequence[str] | None = None,
    hold_days: int | None = None,
) -> dict[str, Any]:
    """Period-net stats pack (t / Sharpe / win rate / payoff / DD)."""
    vals = _finite_floats(period_nets)
    tpack = t_stat_vs_zero(vals)
    sh = sharpe_ratio(vals, periods_per_year=1.0)
    wr = win_rate(vals)
    pay = payoff_ratio(vals)
    dd = max_drawdown(vals)
    calmar = calmar_ratio(tpack.get("mean"), dd.get("max_dd"))
    out: dict[str, Any] = {
        "version": STATS_METRICS_VERSION,
        "n_periods": len(vals),
        "mean_net": tpack.get("mean"),
        "std_net": tpack.get("std"),
        "t_stat": tpack.get("t_stat"),
        "abs_t_stat": tpack.get("abs_t_stat"),
        "sharpe": sh.get("sharpe"),
        "win_rate": wr.get("win_rate"),
        "n_pos": wr.get("n_pos"),
        "n_neg": wr.get("n_neg"),
        "payoff": pay.get("payoff"),
        "max_dd": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "calmar": calmar,
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
    """Trade-level stats on signed hold returns. ppy = trading_days / hold."""
    h = max(int(hold_days), 1)
    am = (float(one_way_cost) / float(h)) if amortize_cost else float(one_way_cost)
    nets: list[float] = []
    for v in _finite_floats(signed_returns):
        nets.append(v - am if amortize_cost or one_way_cost else v)
    if not amortize_cost and float(one_way_cost) == 0.0:
        nets = _finite_floats(signed_returns)

    ppy = float(trading_days_per_year) / float(h)
    tpack = t_stat_vs_zero(nets)
    sh = sharpe_ratio(nets, periods_per_year=ppy)
    wr = win_rate(nets)
    pay = payoff_ratio(nets)
    dd = max_drawdown(nets)
    out: dict[str, Any] = {
        "version": STATS_METRICS_VERSION,
        "hold_days": h,
        "n_trades": len(nets),
        "mean_net": tpack.get("mean"),
        "t_stat": tpack.get("t_stat"),
        "sharpe_ann": sh.get("sharpe"),
        "win_rate": wr.get("win_rate"),
        "payoff": pay.get("payoff"),
        "max_dd": dd.get("max_dd"),
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
    """Evaluate statistical bar against a period_stats_report. All floors must pass."""
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
        "min_abs_t": float(min_abs_t),
        "min_sharpe": float(min_sharpe),
        "min_win_rate": float(min_win_rate),
        "min_positive_periods": int(min_positive_periods),
        "min_payoff": min_payoff,
        "max_abs_dd": max_abs_dd,
    }
    fails: list[str] = []

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
        },
        "fails": fails,
        **_freeze(),
    }


__all__ = [
    "DAILY_PATH_DD_REQUIRED_FIELDS",
    "DAILY_PATH_DD_VERSION",
    "DEFAULT_MAX_ABS_DRAWDOWN",
    "DEFAULT_MIN_ABS_T_STAT",
    "DEFAULT_MIN_PAYOFF",
    "DEFAULT_MIN_PERIOD_WIN_RATE",
    "DEFAULT_MIN_POSITIVE_PERIODS",
    "DEFAULT_MIN_SHARPE_PERIOD",
    "DEFAULT_TRADING_DAYS_PER_YEAR",
    "PERIOD_NET_ONLY_METHODS",
    "STATS_METRICS_VERSION",
    "W99_STICKY_DAILY_PATH_DD_REFERENCE",
    "calmar_ratio",
    "equity_path_drawdown",
    "evaluate_daily_path_dd_gate",
    "max_drawdown",
    "payoff_ratio",
    "period_stats_report",
    "sample_mean",
    "sharpe_ratio",
    "stats_bar_check",
    "is_low_variance_t_artifact",
    "has_pairwise_low_variance_artifact",
    "t_stat_vs_zero",
    "LOW_VARIANCE_REASON",
    "LOW_VARIANCE_MIN_REL_STD",
    "LOW_VARIANCE_MAX_ABS_T",
    "LOW_VARIANCE_SMALL_N_MAX",
    "trade_stats_report",
    "w99_sticky_daily_path_dd_reference",
    "win_rate",
]
