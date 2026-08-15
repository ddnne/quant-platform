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
4. **wf_not_full_flip** (optional, when walk-forward provided): train and test
   ``gross_signed_mean`` must not be opposite non-zero signs (full flip).

Failing any criterion → ``passed=False`` with explicit reasons.
Even on pass: ``ready_declared=False``, ``operational_go=False``,
``mass_research="NO-GO"``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

GATE_VERSION: str = "research-robustness-gate/v1"
GATE_LABEL: str = "研究用頑健性ゲート・未宣言 (合格≠運用GO / READY未接続)"

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False
SIGNIFICANCE_CLAIMED: bool = False
EDGE_CLAIMED: bool = False
CONNECTED_TO_READY: bool = False
CONNECTED_TO_MASS: bool = False

DEFAULT_MIN_PERIODS: int = 2
DEFAULT_MIN_ACTIVE_PER_PERIOD: int = 20
DEFAULT_CATASTROPHIC_ABS: float = 0.05


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


def research_robustness_gate_document() -> dict[str, Any]:
    """Public document for the research robustness gate."""
    return {
        "version": GATE_VERSION,
        "label": GATE_LABEL,
        "criteria": {
            "multi_period": {
                "rule": f">= {DEFAULT_MIN_PERIODS} non-skipped periods with metrics",
                "required": True,
            },
            "sign_majority": {
                "rule": (
                    "strict majority of eligible periods share the same "
                    "gross_signed_mean sign (+ or −)"
                ),
                "required": True,
            },
            "not_catastrophic": {
                "rule": (
                    f"no majority-eligible period with "
                    f"|gross_signed_mean| > {DEFAULT_CATASTROPHIC_ABS}"
                ),
                "required": True,
            },
            "wf_not_full_flip": {
                "rule": (
                    "optional: train/test gross_signed_mean must not fully "
                    "reverse non-zero signs"
                ),
                "required": False,
                "when": "walk_forward fold metrics supplied",
            },
        },
        "defaults": {
            "min_periods": DEFAULT_MIN_PERIODS,
            "min_active_per_period": DEFAULT_MIN_ACTIVE_PER_PERIOD,
            "catastrophic_abs": DEFAULT_CATASTROPHIC_ABS,
        },
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "note": (
            "Research checklist only. Pass does not mint READY, arm Mass, "
            "authorize orders, or claim edge/significance. Fail is a valid "
            "research outcome (record and continue)."
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
) -> dict[str, Any]:
    """Evaluate multi-period (+ optional WF) metrics against the research gate.

    Each ``period_rows`` item should include at least:

    * ``period_id``
    * ``status`` optional (``ok`` / ``skipped`` / ``error``); skipped/error ignored
    * ``gross_signed_mean_active`` or ``gross_signed_mean``
    * ``n_active_positions`` optional (defaults to ``non_null``)

    Returns a dict with ``passed: bool``, ``reasons: list[str]``, criterion
    detail, and freeze flags always closed for READY/Mass/GO.
    """
    reasons: list[str] = []
    details: dict[str, Any] = {}

    eligible: list[dict[str, Any]] = []
    for raw in period_rows:
        row = dict(raw)
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
        eligible.append(
            {
                "period_id": row.get("period_id"),
                "gross_signed_mean": gross,
                "sign": _sign_of(gross),
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

    # Criterion 4: optional WF full-flip check
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

    hard_ok = multi_ok and sign_ok and cat_ok
    if require_wf_check:
        hard_ok = hard_ok and wf_ok

    passed = bool(hard_ok)
    if passed:
        reasons.append("all required research gate criteria met")
    # Freeze: never connect to READY/Mass even on pass
    return {
        "version": GATE_VERSION,
        "label": GATE_LABEL,
        "signal_id": signal_id,
        "passed": passed,
        "reasons": reasons,
        "criteria": details,
        "n_period_rows_in": len(list(period_rows)),
        "n_eligible_periods": n_elig,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "note": (
            "Research robustness gate result only. "
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
    "EDGE_CLAIMED",
    "GATE_LABEL",
    "GATE_VERSION",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PHASE7",
    "READY_DECLARED",
    "SIGNIFICANCE_CLAIMED",
    "evaluate_research_robustness_gate",
    "period_rows_from_cross_table",
    "research_robustness_gate_document",
    "walk_forward_gross_from_compare",
]
