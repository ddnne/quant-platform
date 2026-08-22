"""Sign-side selection: evaluate original and inverted after costs.

Prefer the positive-mean side with non-zero evidence (t is a guideline).
original net = gross − c; inverted net = −gross − c. Research helper only.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from features.class_signals import DEFAULT_MIN_ECONOMIC_NET as DEFAULT_MIN_MEAN_NET
from features.research_freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    S1_S5_UNREJECT,
    SIGNIFICANCE_CLAIMED,
    SIMPLE_DAILY_SIGN,
)
from research.stats_metrics import (
    period_stats_report,
    sample_mean,
    t_stat_vs_zero,
)

SIGN_SELECTION_VERSION: str = "research-sign-selection/v1"
SIGN_SELECTION_WAVE: str = "W86 / w0816u"

SIGN_ORIGINAL: int = 1
SIGN_INVERTED: int = -1

DEFAULT_NEAR_ZERO_ABS_NET: float = 0.0005  # 5bp absolute mean
DEFAULT_T_GUIDELINE: float = 1.0


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
        "simple_daily_sign": SIMPLE_DAILY_SIGN,
        "s1_s5_unreject": S1_S5_UNREJECT,
    }


def _finite(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def invert_period_net(
    *,
    gross: float | None = None,
    net: float | None = None,
    amortized_cost: float | None = None,
) -> float | None:
    """Inverted-side net after the same amortized cost (−gross − c)."""
    g = _finite(gross)
    n = _finite(net)
    c = _finite(amortized_cost)
    if g is not None and c is not None:
        return float(-g - c)
    if g is not None and n is not None:
        # c = g − n
        return float(-g - (g - n))
    if n is not None and c is not None:
        return float(-n - 2.0 * c)
    return None


def _side_pack(
    nets: Sequence[float | None],
    *,
    hold_days: int | None,
    sign: int,
    label: str,
) -> dict[str, Any]:
    vals = [_finite(v) for v in nets]
    clean = [v for v in vals if v is not None]
    stats = period_stats_report(clean, hold_days=hold_days)
    tpack = t_stat_vs_zero(clean)
    mean_net = sample_mean(clean)
    n_pos = sum(1 for v in clean if v is not None and v > 0)
    n_neg = sum(1 for v in clean if v is not None and v < 0)
    return {
        "sign": int(sign),
        "label": label,
        "n_periods": len(clean),
        "mean_net": mean_net,
        "mean_net_bp": None if mean_net is None else float(mean_net) * 10_000.0,
        "t_stat": tpack.get("t_stat"),
        "sharpe": stats.get("sharpe"),
        "win_rate": stats.get("win_rate"),
        "n_pos": n_pos,
        "n_neg": n_neg,
    }


def _nonzero_evidence(
    side: Mapping[str, Any],
    *,
    near_zero_abs: float,
    t_guideline: float,
) -> dict[str, Any]:
    """Soft non-zero evidence: |mean| above floor and/or |t| ≥ guideline."""
    mean_net = _finite(side.get("mean_net"))
    t = _finite(side.get("t_stat"))
    abs_mean = None if mean_net is None else abs(mean_net)
    abs_t = None if t is None else abs(t)

    mean_ok = bool(abs_mean is not None and abs_mean >= float(near_zero_abs))
    t_ok = bool(abs_t is not None and abs_t >= float(t_guideline))
    has_evidence = bool(
        mean_ok
        or (t_ok and mean_net is not None and abs_mean is not None and abs_mean > 0.0)
    )
    near_zero = bool(
        mean_net is None
        or abs_mean is None
        or abs_mean < float(near_zero_abs)
    )
    return {
        "has_nonzero_evidence": has_evidence,
        "near_zero": near_zero,
    }


def evaluate_sign_both_sides(
    *,
    period_grosses: Sequence[float | None] | None = None,
    period_nets: Sequence[float | None] | None = None,
    amortized_costs: Sequence[float | None] | float | None = None,
    period_ids: Sequence[str] | None = None,
    hold_days: int | None = None,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS_NET,
    t_guideline: float = DEFAULT_T_GUIDELINE,
) -> dict[str, Any]:
    """Evaluate original and inverted sides after costs (no choice yet)."""
    grosses = list(period_grosses) if period_grosses is not None else None
    nets_in = list(period_nets) if period_nets is not None else None

    n = 0
    if grosses is not None:
        n = len(grosses)
    elif nets_in is not None:
        n = len(nets_in)
    if n == 0:
        empty = _side_pack([], hold_days=hold_days, sign=1, label="original")
        empty_i = _side_pack([], hold_days=hold_days, sign=-1, label="inverted")
        out = {
            "version": SIGN_SELECTION_VERSION,
            "original": empty,
            "inverted": empty_i,
            "evidence_original": _nonzero_evidence(
                empty, near_zero_abs=near_zero_abs, t_guideline=t_guideline
            ),
            "evidence_inverted": _nonzero_evidence(
                empty_i, near_zero_abs=near_zero_abs, t_guideline=t_guideline
            ),
            "reason": "no_periods",
            **_freeze(),
        }
        return out

    # Normalize costs
    if isinstance(amortized_costs, (int, float)):
        costs: list[float | None] = [float(amortized_costs)] * n
    elif amortized_costs is None:
        costs = [None] * n
    else:
        costs = list(amortized_costs)
        if len(costs) < n:
            costs = costs + [None] * (n - len(costs))

    orig_nets: list[float | None] = []
    inv_nets: list[float | None] = []

    for i in range(n):
        g = _finite(grosses[i]) if grosses is not None else None
        n_i = _finite(nets_in[i]) if nets_in is not None else None
        c = _finite(costs[i]) if i < len(costs) else None
        if c is None and g is not None and n_i is not None:
            c = g - n_i
        if n_i is None and g is not None and c is not None:
            n_i = g - c
        if g is None and n_i is not None and c is not None:
            g = n_i + c
        orig_nets.append(n_i)
        inv_nets.append(
            invert_period_net(gross=g, net=n_i, amortized_cost=c)
        )

    original = _side_pack(
        orig_nets, hold_days=hold_days, sign=SIGN_ORIGINAL, label="original"
    )
    inverted = _side_pack(
        inv_nets, hold_days=hold_days, sign=SIGN_INVERTED, label="inverted"
    )
    ev_o = _nonzero_evidence(
        original, near_zero_abs=near_zero_abs, t_guideline=t_guideline
    )
    ev_i = _nonzero_evidence(
        inverted, near_zero_abs=near_zero_abs, t_guideline=t_guideline
    )
    return {
        "version": SIGN_SELECTION_VERSION,
        "original": original,
        "inverted": inverted,
        "evidence_original": ev_o,
        "evidence_inverted": ev_i,
        **_freeze(),
    }


def choose_sign(
    both: Mapping[str, Any],
    *,
    min_mean_net: float = DEFAULT_MIN_MEAN_NET,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS_NET,
    t_guideline: float = DEFAULT_T_GUIDELINE,
    paper_mean_negative: bool = False,
    min_abs_t_hard: float | None = None,
) -> dict[str, Any]:
    """Choose original or inverted: positive mean + non-zero evidence."""
    original = dict(both.get("original") or {})
    inverted = dict(both.get("inverted") or {})
    ev_o = dict(
        both.get("evidence_original")
        or _nonzero_evidence(
            original, near_zero_abs=near_zero_abs, t_guideline=t_guideline
        )
    )
    ev_i = dict(
        both.get("evidence_inverted")
        or _nonzero_evidence(
            inverted, near_zero_abs=near_zero_abs, t_guideline=t_guideline
        )
    )

    def _eligible(side: Mapping[str, Any], ev: Mapping[str, Any]) -> dict[str, Any]:
        mean_net = _finite(side.get("mean_net"))
        t = _finite(side.get("t_stat"))
        positive = bool(mean_net is not None and mean_net > 0.0)
        econ_ok = bool(mean_net is not None and mean_net >= float(min_mean_net))
        evidence = bool(ev.get("has_nonzero_evidence"))
        hard_t_ok = True
        if min_abs_t_hard is not None:
            hard_t_ok = bool(t is not None and abs(t) >= float(min_abs_t_hard))
        ok = bool(positive and evidence and hard_t_ok)
        return {
            "eligible": ok,
            "positive_mean": positive,
            "economic_floor_ok": econ_ok,
            "nonzero_evidence": evidence,
            "hard_t_ok": hard_t_ok,
            "mean_net": mean_net,
            "t_stat": t,
        }

    elig_o = _eligible(original, ev_o)
    elig_i = _eligible(inverted, ev_i)

    reasons: list[str] = []
    chosen: int | None = None
    decision: str

    if paper_mean_negative:
        reasons.append("paper_mean_negative → evaluate flip first")
        o_mean = _finite(original.get("mean_net"))
        if elig_i["eligible"] and (
            o_mean is None or o_mean <= 0.0 or not elig_o["eligible"]
        ):
            chosen = SIGN_INVERTED
            reasons.append(
                "inverted eligible with positive mean + non-zero evidence "
                "(paper-negative flip preference)"
            )

    if chosen is None:
        if elig_o["eligible"] and elig_i["eligible"]:
            mo = float(elig_o["mean_net"] or 0.0)
            mi = float(elig_i["mean_net"] or 0.0)
            if mi > mo + 1e-15:
                chosen = SIGN_INVERTED
                reasons.append(
                    f"both eligible; inverted mean_net {mi:.6g} > original {mo:.6g}"
                )
            elif mo > mi + 1e-15:
                chosen = SIGN_ORIGINAL
                reasons.append(
                    f"both eligible; original mean_net {mo:.6g} > inverted {mi:.6g}"
                )
            else:
                to = abs(float(elig_o["t_stat"] or 0.0))
                ti = abs(float(elig_i["t_stat"] or 0.0))
                if ti > to:
                    chosen = SIGN_INVERTED
                    reasons.append("mean tie; inverted higher |t|")
                else:
                    chosen = SIGN_ORIGINAL
                    reasons.append("mean tie; original higher or equal |t|")
        elif elig_o["eligible"]:
            chosen = SIGN_ORIGINAL
            reasons.append("only original eligible (positive mean + evidence)")
        elif elig_i["eligible"]:
            chosen = SIGN_INVERTED
            reasons.append("only inverted eligible (positive mean + evidence)")
        else:
            chosen = None
            both_near = bool(ev_o.get("near_zero") and ev_i.get("near_zero"))
            both_neg = bool(
                (_finite(original.get("mean_net")) or 0.0) <= 0.0
                and (_finite(inverted.get("mean_net")) or 0.0) <= 0.0
            )
            if both_near:
                decision = "reject_near_zero_both_sides"
                reasons.append(
                    "both sides near-zero after cost → reject/explore_demote"
                )
            elif both_neg:
                decision = "reject_both_non_positive"
                reasons.append(
                    "neither side has positive mean with non-zero evidence"
                )
            else:
                decision = "reject_no_eligible_side"
                reasons.append(
                    "no side with positive mean + non-zero evidence "
                    "(t is guideline only)"
                )
            out = {
                "version": SIGN_SELECTION_VERSION,
                "chosen_sign": None,
                "chosen_label": None,
                "decision": decision,
                "verdict": "reject_or_explore_demote",
                "original": original,
                "inverted": inverted,
                "reasons": reasons,
                "policy": {
                    "t_is_guideline_not_hard": True,
                },
                **_freeze(),
            }
            return out

    label = "original" if chosen == SIGN_ORIGINAL else "inverted"
    chosen_side = original if chosen == SIGN_ORIGINAL else inverted
    elig = elig_o if chosen == SIGN_ORIGINAL else elig_i
    decision = "keep_original" if chosen == SIGN_ORIGINAL else "flip_to_inverted"
    if not elig.get("economic_floor_ok"):
        reasons.append(
            "chosen mean below economic floor "
            f"({float(min_mean_net)*1e4:.1f}bp) — weak; not hard RC alone"
        )
        verdict = "weak_keep_or_explore"
    else:
        verdict = "selected"

    return {
        "version": SIGN_SELECTION_VERSION,
        "chosen_sign": int(chosen),
        "chosen_label": label,
        "decision": decision,
        "verdict": verdict,
        "chosen_mean_net_bp": chosen_side.get("mean_net_bp"),
        "chosen_t_stat": chosen_side.get("t_stat"),
        "chosen_sharpe": chosen_side.get("sharpe"),
        "original": original,
        "inverted": inverted,
        "reasons": reasons,
        "policy": {
            "t_is_guideline_not_hard": True,
        },
        **_freeze(),
    }


def evaluate_and_choose_sign(
    *,
    period_grosses: Sequence[float | None] | None = None,
    period_nets: Sequence[float | None] | None = None,
    amortized_costs: Sequence[float | None] | float | None = None,
    period_ids: Sequence[str] | None = None,
    hold_days: int | None = None,
    min_mean_net: float = DEFAULT_MIN_MEAN_NET,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS_NET,
    t_guideline: float = DEFAULT_T_GUIDELINE,
    paper_mean_negative: bool = False,
    min_abs_t_hard: float | None = None,
) -> dict[str, Any]:
    """Convenience: evaluate both sides then choose."""
    both = evaluate_sign_both_sides(
        period_grosses=period_grosses,
        period_nets=period_nets,
        amortized_costs=amortized_costs,
        period_ids=period_ids,
        hold_days=hold_days,
        near_zero_abs=near_zero_abs,
        t_guideline=t_guideline,
    )
    choice = choose_sign(
        both,
        min_mean_net=min_mean_net,
        near_zero_abs=near_zero_abs,
        t_guideline=t_guideline,
        paper_mean_negative=paper_mean_negative,
        min_abs_t_hard=min_abs_t_hard,
    )
    return dict(choice)


def sign_selection_from_period_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    hold_days: int | None = None,
    min_mean_net: float = DEFAULT_MIN_MEAN_NET,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS_NET,
    t_guideline: float = DEFAULT_T_GUIDELINE,
    paper_mean_negative: bool = False,
    min_abs_t_hard: float | None = None,
    gross_key: str = "gross_signed_mean_active",
    net_key: str = "net_one_way_mean_active",
    cost_key: str = "amortized_one_way_cost",
    status_key: str = "status",
    period_id_key: str = "period_id",
) -> dict[str, Any]:
    """Apply sign selection to class_hyp-style period rows (status==ok)."""
    ok = [
        r
        for r in rows
        if (status_key is None or r.get(status_key) == "ok")
        and (
            r.get(net_key) is not None
            or r.get(gross_key) is not None
        )
    ]
    grosses = [r.get(gross_key) for r in ok]
    nets = [r.get(net_key) for r in ok]
    costs = [r.get(cost_key) for r in ok]
    pids = [str(r.get(period_id_key) or r.get("year") or f"p{i}") for i, r in enumerate(ok)]
    if all(c is None for c in costs):
        costs_arg: Sequence[float | None] | None = None
    else:
        costs_arg = costs
    return evaluate_and_choose_sign(
        period_grosses=grosses,
        period_nets=nets,
        amortized_costs=costs_arg,
        period_ids=pids,
        hold_days=hold_days,
        min_mean_net=min_mean_net,
        near_zero_abs=near_zero_abs,
        t_guideline=t_guideline,
        paper_mean_negative=paper_mean_negative,
        min_abs_t_hard=min_abs_t_hard,
    )


__all__ = [
    "DEFAULT_MIN_MEAN_NET",
    "DEFAULT_NEAR_ZERO_ABS_NET",
    "DEFAULT_T_GUIDELINE",
    "SIGN_INVERTED",
    "SIGN_ORIGINAL",
    "SIGN_SELECTION_VERSION",
    "SIGN_SELECTION_WAVE",
    "choose_sign",
    "evaluate_and_choose_sign",
    "evaluate_sign_both_sides",
    "invert_period_net",
    "sign_selection_from_period_rows",
]
