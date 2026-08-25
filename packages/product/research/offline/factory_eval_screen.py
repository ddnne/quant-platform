"""Factory eval screen policy (period-net auto-reject; not GO / READY).

``screen_strategy_result`` and SCREEN_* reject reasons. Live period eval
stays in ``research.offline.factory_eval``. Unique/combo generation_enabled
stays False.
"""

from __future__ import annotations

from typing import Any, Mapping

DEFAULT_NEAR_ZERO_ABS: float = 0.0005
DEFAULT_MIN_ACTIVATION: float = 0.01
SCREEN_NEAR_ZERO: str = "near_zero_after_cost"
SCREEN_POST_COST_COLLAPSE: str = "post_cost_collapse"
SCREEN_DATA_MISSING: str = "data_missing"
SCREEN_EVAL_ERROR: str = "eval_error"
SCREEN_NO_PERIODS: str = "no_ok_periods"
SCREEN_LOW_ACTIVATION: str = "low_activation"
SCREEN_BOTH_SIGNS_FAIL: str = "both_signs_near_zero_or_nonpositive"
SCREEN_INFLATED_T_LOW_VARIANCE: str = "inflated_t_low_variance"


def screen_strategy_result(
    result: Mapping[str, Any],
    *,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS,
    min_activation: float = DEFAULT_MIN_ACTIVATION,
) -> dict[str, Any]:
    """Auto-reject near-zero / data missing / post-cost collapse / both-sign fail."""
    reasons: list[str] = []
    n_ok = int(result.get("n_periods_ok") or 0)
    if n_ok <= 0:
        reasons.append(SCREEN_NO_PERIODS)
    period_rows = list(result.get("period_rows") or [])
    if any(r.get("status") == "data_missing" for r in period_rows) and n_ok == 0:
        reasons.append(SCREEN_DATA_MISSING)
    if result.get("errors"):
        if n_ok == 0:
            reasons.append(SCREEN_EVAL_ERROR)

    mean_gross = result.get("mean_gross")
    mean_net = result.get("mean_net")
    if mean_gross is not None and mean_net is not None:
        try:
            g, n = float(mean_gross), float(mean_net)
            if abs(g) >= near_zero_abs and abs(n) < near_zero_abs:
                reasons.append(SCREEN_POST_COST_COLLAPSE)
            if g > near_zero_abs and n < -near_zero_abs and (g - n) > abs(g):
                if SCREEN_POST_COST_COLLAPSE not in reasons:
                    reasons.append(SCREEN_POST_COST_COLLAPSE)
        except (TypeError, ValueError):
            pass

    if mean_net is not None:
        try:
            if abs(float(mean_net)) < near_zero_abs:
                reasons.append(SCREEN_NEAR_ZERO)
        except (TypeError, ValueError):
            pass
    else:
        if n_ok > 0:
            reasons.append(SCREEN_NEAR_ZERO)

    ss = dict(result.get("sign_selection") or {})
    if ss.get("decision") in {"reject", "explore_demote"} or ss.get("chosen_sign") is None:
        if n_ok > 0:
            reasons.append(SCREEN_BOTH_SIGNS_FAIL)

    act = result.get("mean_activation")
    if act is not None:
        try:
            if float(act) < float(min_activation) and n_ok > 0:
                reasons.append(SCREEN_LOW_ACTIVATION)
        except (TypeError, ValueError):
            pass

    t_reason = str(result.get("t_stat_reason") or "")
    if t_reason == "low_variance_artifact" or result.get("low_variance_artifact"):
        reasons.append(SCREEN_INFLATED_T_LOW_VARIANCE)
    elif n_ok >= 2:
        try:
            from research.stats_metrics import (
                LOW_VARIANCE_REASON,
                has_pairwise_low_variance_artifact,
                t_stat_vs_zero,
            )

            nets = [
                r.get("net_one_way_mean_active")
                for r in period_rows
                if r.get("status") == "ok"
            ]
            full = t_stat_vs_zero(nets)
            if full.get("reason") == LOW_VARIANCE_REASON or has_pairwise_low_variance_artifact(
                nets
            ):
                reasons.append(SCREEN_INFLATED_T_LOW_VARIANCE)
        except Exception:
            pass

    uniq = list(dict.fromkeys(reasons))
    survived = len(uniq) == 0 and n_ok > 0
    return {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id"),
        "survived": survived,
        "reject_reasons": uniq,
        "mean_net": mean_net,
        "mean_gross": mean_gross,
        "t_stat": result.get("t_stat"),
        "sharpe_period": result.get("sharpe_period"),
        "chosen_sign": result.get("chosen_sign"),
        "mean_activation": act,
        "n_periods_ok": n_ok,
    }


__all__ = [
    "DEFAULT_MIN_ACTIVATION",
    "DEFAULT_NEAR_ZERO_ABS",
    "SCREEN_BOTH_SIGNS_FAIL",
    "SCREEN_DATA_MISSING",
    "SCREEN_EVAL_ERROR",
    "SCREEN_INFLATED_T_LOW_VARIANCE",
    "SCREEN_LOW_ACTIVATION",
    "SCREEN_NEAR_ZERO",
    "SCREEN_NO_PERIODS",
    "SCREEN_POST_COST_COLLAPSE",
    "screen_strategy_result",
]
