"""Research robustness gate (W62 / w0815bc) — 研究用・未宣言.

Purpose
-------
Prevent treating a single short tip-window win as an actionable signal.
The gate is a **research checklist helper**: it returns pass/fail + reasons.
It does **not** mint READY, arm Mass, or authorize orders.

Hard constraints
----------------
* Mass = NO-GO · Phase7 = OFF · READY not declared
* Gate pass ≠ operational GO (enforced by constants + tests)
* No look-ahead, no densify, no edge/significance claim

Gate criteria (research-only, non-forcing)
------------------------------------------
A signal hypothesis **passes the research robustness gate** only if **all** of:

1. **multi_period**: at least ``min_periods`` (default 2) non-skipped periods
   with a comparable metric row.
2. **sign_majority**: among periods with enough active rows
   (``min_active_per_period``), a strict majority share the same
   ``gross_signed_mean`` sign (+ or −), and that common sign is not null.
3. **not_catastrophic**: no majority-period has ``|gross_signed_mean|`` above
   ``catastrophic_abs`` (default 0.05 = 5% / day — regime explosion flag).
4. **net_sign_majority** (W64 · cost-aware; default on): majority share the
   same sign of ``net_one_way = gross − one_way_cost`` (default 10bp).
   Gross-only soft PASS is no longer enough when cost gate is on.
5. **wf_not_full_flip** (optional, when walk-forward provided): train and test
   ``gross_signed_mean`` must not be opposite non-zero signs (full flip).

Failing any criterion → ``passed=False`` with explicit reasons.
Even on pass: ``ready_declared=False``, ``operational_go=False``,
``mass_research="NO-GO"``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

GATE_VERSION: str = "research-robustness-gate/v2"
GATE_LABEL: str = "研究用頑健性ゲート・未宣言 (合格≠運用GO / READY未接続 / コスト込み)"

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

DEFAULT_MIN_PERIODS: int = 2
DEFAULT_MIN_ACTIVE_PER_PERIOD: int = 20
DEFAULT_CATASTROPHIC_ABS: float = 0.05
DEFAULT_ONE_WAY_COST_BP: float = 10.0
DEFAULT_ONE_WAY_COST: float = DEFAULT_ONE_WAY_COST_BP / 10_000.0  # 0.001
DEFAULT_ROUND_TRIP_COST: float = DEFAULT_ONE_WAY_COST * 2.0  # 0.002


def research_net_one_way(
    gross_signed_mean: float | None,
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
) -> float | None:
    """Research-only: net = gross_signed_mean − one_way_cost (per active).

    Matches the research cost field convention in single_shot (仮定に依存).
    Round-trip would subtract ``2 * one_way_cost``. Not operational GO.
    """
    g = _as_float(gross_signed_mean)
    if g is None:
        return None
    return float(g) - float(one_way_cost)


def annotate_period_rows_with_cost(
    period_rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
) -> list[dict[str, Any]]:
    """Copy period rows adding net_one_way / net_round_trip fields."""
    out: list[dict[str, Any]] = []
    for raw in period_rows:
        row = dict(raw)
        gross = _as_float(
            row.get("gross_signed_mean_active")
            if row.get("gross_signed_mean_active") is not None
            else row.get("gross_signed_mean")
        )
        # Prefer precomputed net if present (from batch_summary).
        net_ow = _as_float(row.get("net_one_way_mean_active"))
        if net_ow is None:
            net_ow = research_net_one_way(gross, one_way_cost=one_way_cost)
        net_rt = _as_float(row.get("net_round_trip_mean_active"))
        if net_rt is None and gross is not None:
            net_rt = float(gross) - 2.0 * float(one_way_cost)
        row["gross_signed_mean_active"] = gross
        row["net_one_way_mean_active"] = net_ow
        row["net_round_trip_mean_active"] = net_rt
        row["one_way_cost"] = float(one_way_cost)
        row["one_way_cost_bp"] = float(one_way_cost) * 10_000.0
        row["cost_formula"] = "net_one_way = gross_signed_mean_active - one_way_cost"
        out.append(row)
    return out


def _as_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _sign_of(x: float | None) -> int | None:
    if x is None:
        return None
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
    }


def research_robustness_gate_document() -> dict[str, Any]:
    """Public document for the research robustness gate."""
    return {
        "version": GATE_VERSION,
        "label": GATE_LABEL,
        "defaults": {
            "min_periods": DEFAULT_MIN_PERIODS,
            "min_active_per_period": DEFAULT_MIN_ACTIVE_PER_PERIOD,
            "catastrophic_abs": DEFAULT_CATASTROPHIC_ABS,
            "one_way_cost": DEFAULT_ONE_WAY_COST,
            "require_net_sign_majority": True,
        },
        **_freeze(),
        "note": (
            "Research checklist only (v2 adds cost-after net sign majority). "
            "Pass does not mint READY, arm Mass, authorize orders, or claim "
            "edge/significance. Fail is a valid research outcome."
        ),
    }


def evaluate_research_robustness_gate(
    period_rows: Sequence[Mapping[str, Any]],
    *,
    signal_id: str | None = None,
    walk_forward: Mapping[str, Any] | None = None,
    min_periods: int = DEFAULT_MIN_PERIODS,
    min_active_per_period: int = DEFAULT_MIN_ACTIVE_PER_PERIOD,
    catastrophic_abs: float = DEFAULT_CATASTROPHIC_ABS,
    require_wf_check: bool = False,
    one_way_cost: float | None = DEFAULT_ONE_WAY_COST,
    require_net_sign_majority: bool = True,
) -> dict[str, Any]:
    """Evaluate multi-period (+ optional WF + cost) metrics against the gate.

    Each ``period_rows`` item should include at least:

    * ``period_id``
    * ``status`` optional (``ok`` / ``skipped`` / ``error``); skipped/error ignored
    * ``gross_signed_mean_active`` or ``gross_signed_mean``
    * ``n_active_positions`` optional (defaults to ``non_null``)
    * optional ``net_one_way_mean_active`` (else derived as gross − one_way_cost)

    ``require_net_sign_majority`` (default True, W64): cost-after sign majority
    is required for overall pass. Set False for gross-only legacy checks.

    Returns a dict with ``passed: bool``, ``reasons: list[str]``, criterion
    detail, and freeze flags always closed for READY/Mass/GO.
    """
    reasons: list[str] = []
    details: dict[str, Any] = {}
    cost = float(one_way_cost) if one_way_cost is not None else None

    annotated = annotate_period_rows_with_cost(
        period_rows,
        one_way_cost=cost if cost is not None else DEFAULT_ONE_WAY_COST,
    )

    eligible: list[dict[str, Any]] = []
    for row in annotated:
        st = str(row.get("status") or "ok").lower()
        if st in ("skipped", "error", "skip"):
            continue
        gross = _as_float(
            row.get("gross_signed_mean_active")
            if row.get("gross_signed_mean_active") is not None
            else row.get("gross_signed_mean")
        )
        n_active = row.get("n_active_positions")
        if n_active is None:
            n_active = row.get("non_null")
        try:
            n_act_i = int(n_active) if n_active is not None else 0
        except (TypeError, ValueError):
            n_act_i = 0
        if n_act_i < int(min_active_per_period):
            continue
        if gross is None:
            continue
        net_ow = _as_float(row.get("net_one_way_mean_active"))
        if net_ow is None and cost is not None:
            net_ow = research_net_one_way(gross, one_way_cost=cost)
        eligible.append(
            {
                "period_id": row.get("period_id"),
                "gross_signed_mean": gross,
                "net_one_way_mean": net_ow,
                "sign": _sign_of(gross),
                "net_sign": _sign_of(net_ow),
                "n_active_positions": n_act_i,
                "mean_R_plus": _as_float(row.get("mean_R_plus")),
                "mean_R_minus": _as_float(row.get("mean_R_minus")),
                "non_null_rate": _as_float(row.get("non_null_rate")),
            }
        )

    # Criterion 1: multi_period
    n_elig = len(eligible)
    multi_ok = n_elig >= int(min_periods)
    details["multi_period"] = {
        "passed": multi_ok,
        "n_eligible": n_elig,
        "min_periods": int(min_periods),
        "eligible_period_ids": [e.get("period_id") for e in eligible],
    }
    if not multi_ok:
        reasons.append(
            f"multi_period: only {n_elig} eligible period(s) "
            f"(need >= {min_periods})"
        )

    # Criterion 2: sign_majority
    sign_ok = False
    majority_sign: int | None = None
    if n_elig > 0:
        counts = {1: 0, -1: 0, 0: 0}
        for e in eligible:
            s = e.get("sign")
            if s in counts:
                counts[s] += 1  # type: ignore[index]
        # strict majority among non-zero if any non-zero, else zeros
        pos, neg, zero = counts[1], counts[-1], counts[0]
        if pos > n_elig / 2:
            majority_sign = 1
            sign_ok = True
        elif neg > n_elig / 2:
            majority_sign = -1
            sign_ok = True
        else:
            sign_ok = False
            reasons.append(
                f"sign_majority: no strict majority sign "
                f"(+={pos}, -={neg}, 0={zero}, n={n_elig})"
            )
    else:
        reasons.append("sign_majority: no eligible periods")
    details["sign_majority"] = {
        "passed": sign_ok,
        "majority_sign": majority_sign,
        "per_period": [
            {"period_id": e.get("period_id"), "sign": e.get("sign"),
             "gross": e.get("gross_signed_mean")}
            for e in eligible
        ],
    }

    # Criterion 3: not_catastrophic
    cat_hits = [
        e
        for e in eligible
        if abs(float(e["gross_signed_mean"])) > float(catastrophic_abs)
    ]
    cat_ok = len(cat_hits) == 0
    details["not_catastrophic"] = {
        "passed": cat_ok,
        "threshold": float(catastrophic_abs),
        "hits": [
            {"period_id": e.get("period_id"), "gross": e.get("gross_signed_mean")}
            for e in cat_hits
        ],
    }
    if not cat_ok:
        reasons.append(
            f"not_catastrophic: {len(cat_hits)} period(s) exceed "
            f"|gross|>{catastrophic_abs}"
        )

    # Criterion 4 (W64): cost-after net sign majority
    net_ok = True
    net_majority: int | None = None
    if require_net_sign_majority:
        if n_elig == 0:
            net_ok = False
            reasons.append("net_sign_majority: no eligible periods")
            net_counts = {1: 0, -1: 0, 0: 0}
        else:
            net_counts = {1: 0, -1: 0, 0: 0}
            for e in eligible:
                ns = e.get("net_sign")
                if ns in net_counts:
                    net_counts[ns] += 1  # type: ignore[index]
            npos, nneg, nzero = net_counts[1], net_counts[-1], net_counts[0]
            if npos > n_elig / 2:
                net_majority = 1
                net_ok = True
            elif nneg > n_elig / 2:
                net_majority = -1
                net_ok = True
            else:
                net_ok = False
                reasons.append(
                    f"net_sign_majority: no strict majority net sign after "
                    f"one_way_cost={cost} "
                    f"(+={npos}, -={nneg}, 0={nzero}, n={n_elig})"
                )
        details["net_sign_majority"] = {
            "passed": net_ok,
            "required": True,
            "majority_net_sign": net_majority,
            "one_way_cost": cost,
            "one_way_cost_bp": (
                float(cost) * 10_000.0 if cost is not None else None
            ),
            "formula": "net_one_way = gross_signed_mean - one_way_cost",
            "per_period": [
                {
                    "period_id": e.get("period_id"),
                    "gross": e.get("gross_signed_mean"),
                    "net_one_way": e.get("net_one_way_mean"),
                    "gross_sign": e.get("sign"),
                    "net_sign": e.get("net_sign"),
                }
                for e in eligible
            ],
            "label": "仮定に依存・研究用・運用GOではない",
        }
    else:
        details["net_sign_majority"] = {
            "passed": True,
            "required": False,
            "skipped": True,
            "note": "require_net_sign_majority=False (gross-only mode)",
        }

    # Criterion 5: optional WF full-flip check
    wf_ok = True
    wf_detail: dict[str, Any] = {"applied": False, "passed": True}
    if walk_forward is not None:
        train_g = _as_float(
            walk_forward.get("train_gross_signed_mean")
            if walk_forward.get("train_gross_signed_mean") is not None
            else (walk_forward.get("train") or {}).get("gross_signed_mean_active")
        )
        test_g = _as_float(
            walk_forward.get("test_gross_signed_mean")
            if walk_forward.get("test_gross_signed_mean") is not None
            else (walk_forward.get("test") or {}).get("gross_signed_mean_active")
        )
        ts, xs = _sign_of(train_g), _sign_of(test_g)
        flipped = (
            ts is not None
            and xs is not None
            and ts != 0
            and xs != 0
            and ts == -xs
        )
        wf_ok = not flipped
        wf_detail = {
            "applied": True,
            "passed": wf_ok,
            "train_gross": train_g,
            "test_gross": test_g,
            "train_sign": ts,
            "test_sign": xs,
            "full_flip": flipped,
        }
        if require_wf_check and not wf_ok:
            reasons.append(
                "wf_not_full_flip: train/test gross signs fully reverse"
            )
        elif flipped and not require_wf_check:
            # advisory reason only — does not force fail unless require_wf_check
            wf_detail["advisory"] = (
                "train/test full sign flip observed (reference; not hard fail)"
            )
    elif require_wf_check:
        wf_ok = False
        reasons.append("wf_not_full_flip: walk_forward required but missing")
        wf_detail = {"applied": False, "passed": False, "missing": True}
    details["wf_not_full_flip"] = wf_detail

    # Gross-only soft pass (for comparison tables; not overall pass when cost on)
    gross_only_ok = multi_ok and sign_ok and cat_ok
    hard_ok = gross_only_ok
    if require_net_sign_majority:
        hard_ok = hard_ok and net_ok
    if require_wf_check:
        hard_ok = hard_ok and wf_ok

    passed = bool(hard_ok)
    if passed:
        reasons.append("all required research gate criteria met")
    elif gross_only_ok and require_net_sign_majority and not net_ok:
        reasons.append(
            "gross_sign_majority alone is insufficient when cost gate is on"
        )
    # Freeze: never connect to READY/Mass even on pass
    return {
        "version": GATE_VERSION,
        "label": GATE_LABEL,
        "signal_id": signal_id,
        "passed": passed,
        "gross_only_passed": bool(gross_only_ok),
        "cost_aware_passed": bool(
            gross_only_ok and net_ok if require_net_sign_majority else gross_only_ok
        ),
        "reasons": reasons,
        "criteria": details,
        "cost_assumption": {
            "one_way_cost": cost,
            "one_way_cost_bp": (
                float(cost) * 10_000.0 if cost is not None else None
            ),
            "require_net_sign_majority": bool(require_net_sign_majority),
            "label": "仮定に依存・研究用・運用GOではない",
        },
        "annotated_period_rows": annotated,
        "n_period_rows_in": len(list(period_rows)),
        "n_eligible_periods": n_elig,
        **_freeze(),
        "note": (
            "Research robustness gate result only (v2 cost-aware). "
            "passed=True does NOT mean READY, Mass GO, or operational GO."
        ),
    }


def period_rows_from_cross_table(
    cross_table: Sequence[Mapping[str, Any]],
    *,
    signal_id: str,
) -> list[dict[str, Any]]:
    """Filter cross_period_compare_table rows for one signal_id."""
    out: list[dict[str, Any]] = []
    for raw in cross_table:
        if str(raw.get("signal_id") or "") != str(signal_id):
            continue
        out.append(
            {
                "period_id": raw.get("period_id"),
                "status": "ok",
                "gross_signed_mean_active": raw.get("gross_signed_mean_active"),
                "net_one_way_mean_active": raw.get("net_one_way_mean_active"),
                "net_round_trip_mean_active": raw.get(
                    "net_round_trip_mean_active"
                ),
                "n_active_positions": raw.get("n_active_positions"),
                "non_null": raw.get("non_null"),
                "non_null_rate": raw.get("non_null_rate"),
                "mean_R_plus": raw.get("mean_R_plus"),
                "mean_R_minus": raw.get("mean_R_minus"),
            }
        )
    return out


def walk_forward_gross_from_compare(
    train_compare: Sequence[Mapping[str, Any]] | None,
    test_compare: Sequence[Mapping[str, Any]] | None,
    *,
    signal_id: str,
) -> dict[str, Any]:
    """Extract train/test gross for one signal from WF compare tables."""

    def _pick(rows: Sequence[Mapping[str, Any]] | None) -> float | None:
        if not rows:
            return None
        for r in rows:
            if str(r.get("signal_id") or "") == str(signal_id):
                return _as_float(r.get("gross_signed_mean_active"))
        return None

    return {
        "train_gross_signed_mean": _pick(train_compare),
        "test_gross_signed_mean": _pick(test_compare),
    }


__all__ = [
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "DEFAULT_CATASTROPHIC_ABS",
    "DEFAULT_MIN_ACTIVE_PER_PERIOD",
    "DEFAULT_MIN_PERIODS",
    "DEFAULT_ONE_WAY_COST",
    "DEFAULT_ONE_WAY_COST_BP",
    "DEFAULT_ROUND_TRIP_COST",
    "EDGE_CLAIMED",
    "GATE_LABEL",
    "GATE_VERSION",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PHASE7",
    "READY_DECLARED",
    "SIGNIFICANCE_CLAIMED",
    "annotate_period_rows_with_cost",
    "evaluate_research_robustness_gate",
    "period_rows_from_cross_table",
    "research_net_one_way",
    "research_robustness_gate_document",
    "walk_forward_gross_from_compare",
]
