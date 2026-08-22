"""Research risk-scenario helpers — 研究用・未宣言.

Min set: crash, high_vol, rate_up/down (N/A if unused), liquidity_stress
(N/A if unavailable). Sign-break prefers fail-candidate.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

RISK_SCENARIOS_VERSION: str = "research-risk-scenarios/v1"
RISK_SCENARIOS_LABEL: str = (
    "研究用リスクシナリオ評価・未宣言 "
    "(crash/high_vol/rate/liquidity / READY未接続 / Mass closed)"
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

SCENARIO_CRASH: str = "crash"
SCENARIO_HIGH_VOL: str = "high_vol"
SCENARIO_RATE_UP: str = "rate_up"
SCENARIO_RATE_DOWN: str = "rate_down"
SCENARIO_LIQUIDITY_STRESS: str = "liquidity_stress"

REQUIRED_CORE_SCENARIOS: tuple[str, ...] = (
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
)
OPTIONAL_DATA_DEPENDENT_SCENARIOS: tuple[str, ...] = (
    SCENARIO_RATE_UP,
    SCENARIO_RATE_DOWN,
    SCENARIO_LIQUIDITY_STRESS,
)
MIN_SCENARIO_SET: tuple[str, ...] = (
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
    SCENARIO_RATE_UP,
    SCENARIO_RATE_DOWN,
    SCENARIO_LIQUIDITY_STRESS,
)


def _freeze_fields() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "label": RISK_SCENARIOS_LABEL,
    }


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


def scenario_row(
    scenario_id: str,
    *,
    status: str = "ok",
    gross_signed_mean: float | None = None,
    net_one_way_mean: float | None = None,
    n_active: int | None = None,
    market_return: float | None = None,
    realized_vol: float | None = None,
    not_applicable: bool = False,
    na_reason: str | None = None,
    notes: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one scenario metric row for :func:`evaluate_risk_scenarios`."""
    sid = str(scenario_id).strip()
    st = str(status or "ok").strip().lower()
    if not_applicable:
        st = "not_applicable"
    row: dict[str, Any] = {
        "scenario_id": sid,
        "status": st,
        "gross_signed_mean": _as_float(gross_signed_mean),
        "net_one_way_mean": _as_float(net_one_way_mean),
        "gross_sign": _sign_of(_as_float(gross_signed_mean)),
        "net_sign": _sign_of(_as_float(net_one_way_mean)),
        "n_active": int(n_active) if n_active is not None else None,
        "market_return": _as_float(market_return),
        "realized_vol": _as_float(realized_vol),
        "not_applicable": bool(not_applicable or st == "not_applicable"),
        "na_reason": str(na_reason).strip() if na_reason else None,
        "notes": notes,
    }
    if extra:
        for k, v in extra.items():
            if k not in row:
                row[k] = v
    return row


def default_na_scenario_bundle(
    *,
    rate_data_usable: bool = False,
    liquidity_data_available: bool = False,
    rate_na_reason: str = "rate data not usable in this research plane",
    liquidity_na_reason: str = "liquidity stress data not available",
) -> list[dict[str, Any]]:
    """Wiring bundle: core scenarios pending metrics; data-dependent N/A."""
    rows = [
        scenario_row(
            SCENARIO_CRASH,
            status="pending_metrics",
            notes="crash scenario surface only — supply metrics for completeness",
        ),
        scenario_row(
            SCENARIO_HIGH_VOL,
            status="pending_metrics",
            notes="high_vol scenario surface only — supply metrics for completeness",
        ),
    ]
    if rate_data_usable:
        rows.append(
            scenario_row(
                SCENARIO_RATE_UP,
                status="pending_metrics",
                notes="rate data marked usable — supply rate_up metrics",
            )
        )
        rows.append(
            scenario_row(
                SCENARIO_RATE_DOWN,
                status="pending_metrics",
                notes="rate data marked usable — supply rate_down metrics",
            )
        )
    else:
        rows.append(
            scenario_row(
                SCENARIO_RATE_UP,
                not_applicable=True,
                na_reason=rate_na_reason,
            )
        )
        rows.append(
            scenario_row(
                SCENARIO_RATE_DOWN,
                not_applicable=True,
                na_reason=rate_na_reason,
            )
        )
    if liquidity_data_available:
        rows.append(
            scenario_row(
                SCENARIO_LIQUIDITY_STRESS,
                status="pending_metrics",
                notes="liquidity data marked available — supply metrics",
            )
        )
    else:
        rows.append(
            scenario_row(
                SCENARIO_LIQUIDITY_STRESS,
                not_applicable=True,
                na_reason=liquidity_na_reason,
            )
        )
    return rows


def evaluate_risk_scenarios(
    scenario_rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    baseline_majority_sign: int | None = None,
    baseline_net_majority_sign: int | None = None,
    rate_data_usable: bool = False,
    liquidity_data_available: bool = False,
    prefer_fail_on_sign_break: bool = True,
    allow_scenario_weakness_disclosure: bool = True,
    scenario_weakness_disclosed: bool = False,
    scenario_weakness_notes: str | None = None,
    signal_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate min risk-scenario set. passed ≠ READY / candidate."""
    rows_in = [dict(r) for r in (scenario_rows or [])]
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows_in:
        sid = str(r.get("scenario_id") or "").strip()
        if not sid:
            continue
        if r.get("not_applicable") or str(r.get("status") or "").lower() in (
            "not_applicable",
            "n/a",
            "na",
        ):
            r["not_applicable"] = True
            r["status"] = "not_applicable"
        g = _as_float(r.get("gross_signed_mean"))
        n = _as_float(r.get("net_one_way_mean"))
        r["gross_signed_mean"] = g
        r["net_one_way_mean"] = n
        r["gross_sign"] = _sign_of(g)
        r["net_sign"] = _sign_of(n)
        by_id[sid] = r

    reasons: list[str] = []
    details: dict[str, Any] = {}
    missing_required: list[str] = []

    def _coverage(sid: str, *, required: bool, allow_na: bool) -> dict[str, Any]:
        row = by_id.get(sid)
        if row is None:
            if required:
                missing_required.append(sid)
            return {
                "scenario_id": sid,
                "present": False,
                "status": "missing",
                "passed": False if required else True,
                "not_applicable": False,
            }
        na = bool(row.get("not_applicable"))
        st = str(row.get("status") or "ok").lower()
        has_metric = row.get("gross_signed_mean") is not None or row.get(
            "net_one_way_mean"
        ) is not None
        if na:
            if allow_na:
                ok = bool(row.get("na_reason"))
                if not ok:
                    reasons.append(f"{sid}: not_applicable without na_reason")
                return {
                    "scenario_id": sid,
                    "present": True,
                    "status": "not_applicable",
                    "passed": ok,
                    "not_applicable": True,
                    "na_reason": row.get("na_reason"),
                }
            reasons.append(
                f"{sid}: marked not_applicable but data is marked usable/available"
            )
            return {
                "scenario_id": sid,
                "present": True,
                "status": "not_applicable_invalid",
                "passed": False,
                "not_applicable": True,
            }
        if st in ("pending_metrics", "pending", "wiring_only"):
            missing_required.append(sid)
            return {
                "scenario_id": sid,
                "present": True,
                "status": st,
                "passed": False,
                "not_applicable": False,
                "note": "metrics not supplied",
            }
        if not has_metric:
            missing_required.append(sid)
            return {
                "scenario_id": sid,
                "present": True,
                "status": "no_metrics",
                "passed": False,
                "not_applicable": False,
            }
        return {
            "scenario_id": sid,
            "present": True,
            "status": st or "ok",
            "passed": True,
            "not_applicable": False,
            "gross_sign": row.get("gross_sign"),
            "net_sign": row.get("net_sign"),
            "gross_signed_mean": row.get("gross_signed_mean"),
            "net_one_way_mean": row.get("net_one_way_mean"),
        }

    for sid in REQUIRED_CORE_SCENARIOS:
        details[sid] = _coverage(sid, required=True, allow_na=False)

    for sid in (SCENARIO_RATE_UP, SCENARIO_RATE_DOWN):
        details[sid] = _coverage(
            sid, required=True, allow_na=not rate_data_usable
        )

    details[SCENARIO_LIQUIDITY_STRESS] = _coverage(
        SCENARIO_LIQUIDITY_STRESS,
        required=True,
        allow_na=not liquidity_data_available,
    )

    coverage_ok = all(
        bool(details[sid].get("passed")) for sid in MIN_SCENARIO_SET if sid in details
    ) and not missing_required

    if missing_required:
        reasons.append(
            "missing_or_pending_scenarios: " + ", ".join(sorted(set(missing_required)))
        )

    sign_breaks: list[dict[str, Any]] = []
    for sid in REQUIRED_CORE_SCENARIOS:
        row = by_id.get(sid)
        cov = details.get(sid) or {}
        if not row or cov.get("not_applicable") or not cov.get("passed"):
            continue
        g_sign = row.get("gross_sign")
        n_sign = row.get("net_sign")
        break_info: dict[str, Any] = {"scenario_id": sid}
        broken = False
        if (
            baseline_majority_sign is not None
            and g_sign is not None
            and g_sign != 0
            and int(baseline_majority_sign) != 0
            and int(g_sign) == -int(baseline_majority_sign)
        ):
            broken = True
            break_info["gross_sign_flip_vs_baseline"] = True
            break_info["baseline_majority_sign"] = int(baseline_majority_sign)
            break_info["scenario_gross_sign"] = int(g_sign)
        if (
            baseline_net_majority_sign is not None
            and n_sign is not None
            and n_sign != 0
            and int(baseline_net_majority_sign) != 0
            and int(n_sign) == -int(baseline_net_majority_sign)
        ):
            broken = True
            break_info["net_sign_flip_vs_baseline"] = True
            break_info["baseline_net_majority_sign"] = int(baseline_net_majority_sign)
            break_info["scenario_net_sign"] = int(n_sign)
        if broken:
            sign_breaks.append(break_info)

    stability_broken = len(sign_breaks) > 0
    if stability_broken:
        reasons.append(
            "scenario_sign_stability_broken: "
            + ", ".join(b["scenario_id"] for b in sign_breaks)
        )

    research_candidate_allowed = True
    if not coverage_ok:
        research_candidate_allowed = False
        reasons.append("incomplete_scenario_coverage → not research_candidate")
    if stability_broken:
        if prefer_fail_on_sign_break:
            research_candidate_allowed = False
            reasons.append(
                "prefer_fail_on_sign_break: stability break → not research_candidate"
            )
        elif allow_scenario_weakness_disclosure and scenario_weakness_disclosed:
            research_candidate_allowed = True
            reasons.append(
                "scenario_weakness_disclosed (allowed only when prefer_fail=False)"
            )
        else:
            research_candidate_allowed = False
            reasons.append(
                "stability break without scenario_weakness_disclosed "
                "→ not research_candidate"
            )

    passed = bool(coverage_ok and not (stability_broken and prefer_fail_on_sign_break))
    if (
        coverage_ok
        and stability_broken
        and not prefer_fail_on_sign_break
        and scenario_weakness_disclosed
    ):
        passed = True

    if passed and not reasons:
        reasons.append("min risk-scenario set covered; no undisclosed stability break")

    out: dict[str, Any] = {
        "version": RISK_SCENARIOS_VERSION,
        "label": RISK_SCENARIOS_LABEL,
        "signal_id": signal_id,
        "passed": passed,
        "coverage_ok": bool(coverage_ok),
        "stability_broken": bool(stability_broken),
        "sign_breaks": sign_breaks,
        "research_candidate_allowed": bool(research_candidate_allowed),
        "prefer_fail_on_sign_break": bool(prefer_fail_on_sign_break),
        "scenario_weakness_disclosed": bool(scenario_weakness_disclosed),
        "scenario_weakness_notes": (
            str(scenario_weakness_notes).strip() if scenario_weakness_notes else None
        ),
        "rate_data_usable": bool(rate_data_usable),
        "liquidity_data_available": bool(liquidity_data_available),
        "baseline_majority_sign": baseline_majority_sign,
        "baseline_net_majority_sign": baseline_net_majority_sign,
        "scenarios": details,
        "scenario_rows": list(by_id.values()),
        "missing_required": sorted(set(missing_required)),
        "reasons": reasons,
        "min_scenario_set": list(MIN_SCENARIO_SET),
        "note": (
            "Research risk-scenario result only. Incomplete or sign-break "
            "(prefer fail) blocks research_candidate."
        ),
    }
    out.update(_freeze_fields())
    return out


__all__ = [
    "MIN_SCENARIO_SET",
    "OPTIONAL_DATA_DEPENDENT_SCENARIOS",
    "REQUIRED_CORE_SCENARIOS",
    "RISK_SCENARIOS_LABEL",
    "RISK_SCENARIOS_VERSION",
    "SCENARIO_CRASH",
    "SCENARIO_HIGH_VOL",
    "SCENARIO_LIQUIDITY_STRESS",
    "SCENARIO_RATE_DOWN",
    "SCENARIO_RATE_UP",
    "default_na_scenario_bundle",
    "evaluate_risk_scenarios",
    "scenario_row",
]
