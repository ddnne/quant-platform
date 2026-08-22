"""Occurrence-rate and production-candidate bars for class signals.

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .research_freezes import MASS_RESEARCH, PHASE7
from .class_signals import (
    DEFAULT_HOLD_DAYS,
    DEFAULT_MAX_YEAR_POS_NET_SHARE,
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_ECONOMIC_NET,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
    DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
    DEFAULT_TRADING_DAYS_PER_YEAR,
)


def economic_net_meaningful(
    net_values: Sequence[float | None],
    *,
    min_mean_net: float = DEFAULT_MIN_ECONOMIC_NET,
    require_positive_majority: bool = True,
) -> dict[str, Any]:
    """Research bar: net residual after costs must be economically meaningful.

    Weak consistent-negative (or tiny residual << cost) is **not** candidate.
    """
    vals = [float(v) for v in net_values if v is not None]
    if not vals:
        return {
            "meaningful": False,
            "reason": "no_net_values",
            "min_mean_net": float(min_mean_net),
            "require_positive_majority": bool(require_positive_majority),
        }
    n_pos = sum(1 for v in vals if v > 0)
    n_neg = sum(1 for v in vals if v < 0)
    mean_net = sum(vals) / float(len(vals))
    majority_pos = n_pos > n_neg
    majority_neg = n_neg > n_pos
    if require_positive_majority and not majority_pos:
        return {
            "meaningful": False,
            "reason": (
                "net_majority_not_positive"
                if majority_neg
                else "net_majority_tied_or_flat"
            ),
            "mean_net": mean_net,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "n": len(vals),
            "min_mean_net": float(min_mean_net),
            "weak_consistent_negative": bool(majority_neg and mean_net < 0),
        }
    if mean_net < float(min_mean_net):
        return {
            "meaningful": False,
            "reason": "mean_net_below_economic_threshold",
            "mean_net": mean_net,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "n": len(vals),
            "min_mean_net": float(min_mean_net),
        }
    return {
        "meaningful": True,
        "reason": "positive_majority_and_mean_net_above_threshold",
        "mean_net": mean_net,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n": len(vals),
        "min_mean_net": float(min_mean_net),
    }


def occurrence_rate_multiday(
    *,
    n_active: int | None,
    n_code_days: int | None,
    n_trading_days: int | None = None,
    n_codes: int | None = None,
    hold_days: int = DEFAULT_HOLD_DAYS,
    min_activation_rate: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
) -> dict[str, Any]:
    """Activation rate for multi_day_hold: ``n_active / n_code_days`` (not count)."""
    n_a = int(n_active or 0)
    n_cd = int(n_code_days or 0)
    n_td = int(n_trading_days or 0)
    n_c = int(n_codes or 0)
    rate = (float(n_a) / float(n_cd)) if n_cd > 0 else None
    expected = 1.0 / float(max(int(hold_days), 1))
    sufficient = bool(rate is not None and rate >= float(min_activation_rate))
    return {
        "kind": "occurrence_rate_multiday",
        "n_active": n_a,
        "n_code_days": n_cd if n_cd > 0 else None,
        "n_trading_days": n_td if n_td > 0 else None,
        "n_codes": n_c if n_c > 0 else None,
        "activation_rate": rate,
        "expected_activation_rate": expected,
        "min_activation_rate": float(min_activation_rate),
        "sufficient": sufficient,
        "reject_on_count_alone": False,
        "reason": (
            "activation_rate_ok"
            if sufficient
            else (
                "activation_rate_below_min"
                if rate is not None
                else "no_code_days_for_rate"
            )
        ),
    }


def occurrence_rate_event_post(
    *,
    n_events: int | None,
    n_scored: int | None = None,
    n_trading_days: int | None = None,
    n_codes: int | None = None,
    n_code_days: int | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    min_events_per_code_year: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    min_events_per_trading_day: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
) -> dict[str, Any]:
    """Event_post occurrence rate (per trading day / annualized per code, not count)."""
    n_ev = int(n_events or 0)
    n_sc = int(n_scored if n_scored is not None else n_ev)
    n_td = int(n_trading_days or 0)
    n_c = int(n_codes or 0)
    n_cd = int(n_code_days or 0)
    if n_cd <= 0 and n_td > 0 and n_c > 0:
        n_cd = n_td * n_c

    per_td = (float(n_sc) / float(n_td)) if n_td > 0 else None
    per_cd = (float(n_sc) / float(n_cd)) if n_cd > 0 else None
    per_code_year = None
    if n_c > 0 and n_td > 0:
        # annualize from window length
        years_frac = float(n_td) / float(max(int(trading_days_per_year), 1))
        if years_frac > 0:
            per_code_year = (float(n_sc) / float(n_c)) / years_frac

    rate_ok_td = bool(
        per_td is not None and per_td >= float(min_events_per_trading_day)
    )
    rate_ok_year = bool(
        per_code_year is not None
        and per_code_year >= float(min_events_per_code_year)
    )
    # either panel intensity or annualized per-code rate is enough
    sufficient = bool(rate_ok_td or rate_ok_year)
    if per_td is None and per_code_year is None:
        sufficient = False
        reason = "no_days_or_codes_for_rate"
    elif sufficient:
        reason = "occurrence_rate_ok"
    else:
        reason = "occurrence_rate_below_min"

    return {
        "kind": "occurrence_rate_event_post",
        "n_events": n_ev,
        "n_scored": n_sc,
        "n_trading_days": n_td if n_td > 0 else None,
        "n_codes": n_c if n_c > 0 else None,
        "n_code_days": n_cd if n_cd > 0 else None,
        "events_per_trading_day": per_td,
        "events_per_code_day": per_cd,
        "events_per_code_year_annualized": per_code_year,
        "min_events_per_trading_day": float(min_events_per_trading_day),
        "min_events_per_code_year": float(min_events_per_code_year),
        "rate_ok_trading_day": rate_ok_td,
        "rate_ok_code_year": rate_ok_year,
        "sufficient": sufficient,
        "reject_on_count_alone": False,
        "reason": reason,
    }


def multi_year_skew_check(
    net_by_period: Mapping[str, float | None] | Sequence[tuple[str, float | None]],
    *,
    max_pos_share: float = DEFAULT_MAX_YEAR_POS_NET_SHARE,
) -> dict[str, Any]:
    """Detect extreme single-year dominance of positive net mass."""
    if isinstance(net_by_period, Mapping):
        items = [(str(k), v) for k, v in net_by_period.items()]
    else:
        items = [(str(k), v) for k, v in net_by_period]
    pos = [(k, float(v)) for k, v in items if v is not None and float(v) > 0]
    pos_sum = sum(v for _, v in pos)
    if pos_sum <= 0:
        return {
            "ok": False,
            "reason": "no_positive_net_years",
            "max_pos_share": float(max_pos_share),
            "shares": {},
            "dominant_period": None,
            "dominant_share": None,
        }
    shares = {k: float(v) / pos_sum for k, v in pos}
    dom_k, dom_s = max(shares.items(), key=lambda kv: kv[1])
    ok = bool(dom_s <= float(max_pos_share))
    return {
        "ok": ok,
        "reason": "no_extreme_skew" if ok else "extreme_single_year_skew",
        "max_pos_share": float(max_pos_share),
        "shares": shares,
        "dominant_period": dom_k,
        "dominant_share": dom_s,
        "n_positive_years": len(pos),
        "pos_net_sum": pos_sum,
    }


def production_candidate_bar(
    *,
    checklist_complete: bool,
    gate_passed: bool,
    risk_ok: bool,
    economic_net_ok: bool,
    occurrence_ok: bool,
    multi_year_ok: bool,
    skew_ok: bool,
    n_ok_periods: int,
    min_years: int = DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
    economic_net: Mapping[str, Any] | None = None,
    occurrence: Mapping[str, Any] | None = None,
    skew: Mapping[str, Any] | None = None,
    stats_ok: bool = True,
    stats: Mapping[str, Any] | None = None,
    stats_bar: Mapping[str, Any] | None = None,
    require_stats: bool = True,
) -> dict[str, Any]:
    """Production research_candidate bar (still not READY / Mass / GO).

    Checklist, gate, risk, economic net, occurrence rate, multi-year, and
    stats (|t|, Sharpe, period win-rate) must all pass when required.
    """
    years_ok = bool(multi_year_ok and int(n_ok_periods) >= int(min_years))
    stats_required_ok = bool(stats_ok) if require_stats else True
    all_ok = bool(
        checklist_complete
        and gate_passed
        and risk_ok
        and economic_net_ok
        and occurrence_ok
        and years_ok
        and skew_ok
        and stats_required_ok
    )
    fails: list[str] = []
    if not checklist_complete:
        fails.append("checklist_incomplete")
    if not gate_passed:
        fails.append("gate_failed")
    if not risk_ok:
        fails.append("risk_catastrophic_or_blocked")
    if not economic_net_ok:
        fails.append("economic_net_not_meaningful")
    if not occurrence_ok:
        fails.append("occurrence_rate_insufficient")
    if not years_ok:
        fails.append("multi_year_coverage_insufficient")
    if not skew_ok:
        fails.append("extreme_multi_year_skew")
    if require_stats and not stats_ok:
        fails.append("stats_bar_failed")

    w80_core_ok = bool(
        checklist_complete
        and gate_passed
        and risk_ok
        and economic_net_ok
        and occurrence_ok
        and years_ok
        and skew_ok
    )
    noisy = bool((stats_bar or {}).get("noisy")) if stats_bar else False

    if all_ok:
        verdict = "research_candidate"
        yes_no = "yes"
    elif (
        gate_passed
        and risk_ok
        and economic_net_ok
        and (
            not occurrence_ok
            or not years_ok
            or not skew_ok
            or not checklist_complete
            or (require_stats and not stats_ok)
        )
    ):
        # gate+econ ok but production rate/year/checklist/stats incomplete
        if require_stats and not stats_ok and w80_core_ok:
            verdict = (
                "discussion_only_noisy_stats"
                if noisy
                else "discussion_only_stats_bar"
            )
        else:
            verdict = "discussion_only"
        yes_no = "no_discussion_only"
    elif gate_passed and risk_ok and not economic_net_ok:
        verdict = "not_candidate_economic_net_not_meaningful"
        yes_no = "no"
    else:
        verdict = "not_candidate"
        yes_no = "no"

    return {
        "research_candidate": bool(all_ok),
        "research_candidate_allowed": bool(
            gate_passed and risk_ok and economic_net_ok
        ),
        "candidate_yes_no": yes_no,
        "verdict": verdict,
        "production_criteria": {
            "checklist_complete": bool(checklist_complete),
            "gate_passed": bool(gate_passed),
            "risk_ok": bool(risk_ok),
            "economic_net_ok": bool(economic_net_ok),
            "occurrence_ok": bool(occurrence_ok),
            "multi_year_ok": bool(years_ok),
            "skew_ok": bool(skew_ok),
            "stats_ok": bool(stats_required_ok),
            "stats_required": bool(require_stats),
            "n_ok_periods": int(n_ok_periods),
            "min_years": int(min_years),
            "all_ok": all_ok,
            "w80_core_ok": w80_core_ok,
            "fails": fails,
        },
        "economic_net": dict(economic_net) if economic_net else None,
        "occurrence": dict(occurrence) if occurrence else None,
        "skew": dict(skew) if skew else None,
        "stats": dict(stats) if stats else None,
        "stats_bar": dict(stats_bar) if stats_bar else None,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
    }

