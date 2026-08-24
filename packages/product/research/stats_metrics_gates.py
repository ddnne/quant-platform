"""Daily-path DD and stats-bar policy. Not live math; not GO.

Period-net DD alone cannot pass. Live t / Sharpe / DD math stays in
``research.stats_metrics``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from features.class_signals import (
    DEFAULT_MIN_ABS_T_STAT,
    DEFAULT_MIN_PERIOD_WIN_RATE,
    DEFAULT_MIN_POSITIVE_PERIODS,
    DEFAULT_MIN_SHARPE_PERIOD,
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

DEFAULT_MIN_PAYOFF: float | None = None
DEFAULT_MAX_ABS_DRAWDOWN: float | None = None


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


def _scalar_finite(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


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
        from research.stats_metrics import equity_path_drawdown

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
    "DEFAULT_MIN_PAYOFF",
    "PERIOD_NET_ONLY_METHODS",
    "evaluate_daily_path_dd_gate",
    "stats_bar_check",
]
