"""Offline multi-year class-hyp gates / cost / risk (not CF SoT; no GO).

Robustness gates, short-cost remeasure, cost assumptions, holding, and
risk scenarios. Stats / candidate / sign-selection assembly stays in
``research.offline.multiyear_report``.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import SIGNAL_ID_EVENT_POST
from research.cost_models import (
    REPO_DATASET_ID,
    SHORT_BORROW_SPREAD_SENSITIVITY,
    build_leverage_short_cost_assumption,
    default_long_only_unlevered_cost_assumption,
    mean_repo_rate_pct,
    remeasure_period_rows_with_short_cost,
)
from research.holding_metrics import holding_metrics_report
from research.risk_scenarios import (
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
    SCENARIO_LIQUIDITY_STRESS,
    SCENARIO_RATE_DOWN,
    SCENARIO_RATE_UP,
    evaluate_risk_scenarios,
    scenario_row,
)
from research.robustness_gate import evaluate_research_robustness_gate

_NA_SCENARIOS: tuple[tuple[str, str], ...] = (
    (SCENARIO_CRASH, "no ok periods"),
    (SCENARIO_HIGH_VOL, "no ok periods"),
    (SCENARIO_RATE_UP, "insufficient"),
    (SCENARIO_RATE_DOWN, "insufficient"),
    (SCENARIO_LIQUIDITY_STRESS, "no liq data"),
)


def normalize_short_sensitivity(raw: str | None) -> str:
    sens = str(raw or "mid").strip().lower()
    if sens not in SHORT_BORROW_SPREAD_SENSITIVITY:
        return "mid"
    return sens


def remeasure_ls_rows(
    rows: list[dict[str, Any]],
    *,
    apply: bool,
    repo_series: Mapping[str, Any] | None,
    short_fraction: float,
    hold_days: int,
    default_sensitivity: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Date-matched repo[t]+spread remeasure; gaps never invent-filled."""
    if not apply or not rows:
        return rows, None
    pack = remeasure_period_rows_with_short_cost(
        rows,
        repo_rate_series=repo_series,
        short_fraction=float(short_fraction),
        hold_days=int(hold_days),
        default_sensitivity=default_sensitivity,
        sensitivities=("low", "mid", "high"),
        apply_primary_net=True,
        fallback_mean_repo_when_date_gap=False,
    )
    summary = {
        "summary_by_sensitivity": pack.get("summary_by_sensitivity"),
        "n_short_cost_obs": pack.get("n_short_cost_obs"),
        "n_repo_gaps": pack.get("n_repo_gaps"),
        "default_sensitivity": pack.get("default_sensitivity"),
        "short_fraction": pack.get("short_fraction"),
        "formula": pack.get("formula"),
        "assumptions": pack.get("assumptions"),
        "mean_repo": pack.get("mean_repo"),
    }
    return list(pack.get("period_rows") or rows), summary


def apply_ls_short_cost_remeasure(
    *,
    apply: bool,
    repo_series: Mapping[str, Any] | None,
    short_fraction: float,
    short_sens: str,
    targets: Sequence[tuple[str, list[dict[str, Any]], int, bool]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Remeasure included L-S class rows. ``targets``: key, rows, hold_days, do."""
    out_rows: dict[str, list[dict[str, Any]]] = {}
    blocks: dict[str, Any] = {}
    for key, rows, hold_days, do in targets:
        if apply and do:
            new_rows, pack = remeasure_ls_rows(
                rows,
                apply=True,
                repo_series=repo_series,
                short_fraction=short_fraction,
                hold_days=hold_days,
                default_sensitivity=short_sens,
            )
            out_rows[key] = new_rows
            if pack is not None:
                blocks[key] = pack
        else:
            out_rows[key] = rows
    return out_rows, blocks


def robustness_gate_from_rows(
    rows: list[dict[str, Any]],
    signal_id: str,
    *,
    apply: bool,
    min_periods_gate: int,
    min_active_per_period: int,
    one_way_cost: float,
) -> dict[str, Any] | None:
    if not apply:
        return None
    period_rows = [
        {
            "period_id": r["period_id"],
            "status": "ok",
            "gross_signed_mean_active": r.get("gross_signed_mean_active"),
            "net_one_way_mean_active": r.get("net_one_way_mean_active"),
            "n_active_positions": r.get("n_active_positions") or r.get("non_null"),
            "non_null": r.get("non_null"),
            "non_null_rate": r.get("non_null_rate"),
        }
        for r in rows
        if r.get("status") == "ok" and r.get("gross_signed_mean_active") is not None
    ]
    if not period_rows:
        return {
            "passed": False,
            "signal_id": signal_id,
            "reason": "no_ok_periods_with_gross",
            "research_candidate": False,
        }
    min_active = min_active_per_period
    if signal_id == SIGNAL_ID_EVENT_POST:
        min_active = min(5, min_active_per_period)
    return evaluate_research_robustness_gate(
        period_rows,
        signal_id=signal_id,
        min_periods=min_periods_gate,
        min_active_per_period=min_active,
        one_way_cost=one_way_cost,
        require_net_sign_majority=True,
    )


def class_hyp_cost_assumptions(
    *,
    one_way_cost: float,
    prefer_liquidity_linked: bool,
    apply_short_cost_remeasure: bool,
    short_frac_ls: float,
    short_sens: str,
    repo_series: Mapping[str, Any] | None,
    short_cost_remeasure_blocks: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (long-only cost, L-S cost). Macro uses the L-S pack."""
    cost_md = default_long_only_unlevered_cost_assumption(one_way_cost=one_way_cost)
    cost_md["prefer_liquidity_linked"] = bool(prefer_liquidity_linked)
    cost_md["liquidity_note"] = (
        "Per-period one_way_eff = one_way_base * tx_mult[bucket] from "
        "equities_bars ADV. Missing ADV → mult=1.0 gap disclosed (no invent)."
    )
    cost_ls = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=short_frac_ls,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=repo_series,
        prefer_repo_linked=True,
        short_borrow_sensitivity=short_sens,
    )
    cost_ls["short_cost_remeasure"] = {
        "applied": bool(apply_short_cost_remeasure),
        "default_sensitivity": short_sens,
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "formula": (
            "net = gross - amortized_one_way - "
            "short_borrow_daily(repo[t]+spread)*hold_days"
        ),
        "blocks": short_cost_remeasure_blocks,
        "proof": "docs/proof/w0816t_w85_short_cost_repo_spread_20260817.md",
    }
    if repo_series is not None:
        mean_repo = mean_repo_rate_pct(repo_series)
        cost_ls["repo_linked"] = {
            "preferred": True,
            "dataset": REPO_DATASET_ID,
            "mean_rate_pct": mean_repo.get("mean_rate_pct"),
            "mean_annual_bp": mean_repo.get("mean_annual_bp"),
            "n_obs": mean_repo.get("n_obs"),
            "note": (
                "W85: date-matched repo[t]+spread applied to L-S period nets; "
                "mean disclosed for summary. Gaps never invent-filled."
            ),
        }
    else:
        cost_ls["repo_linked"] = {
            "preferred": True,
            "available": False,
            "fallback": "fixed_bp_placeholder",
        }
    cost_macro = dict(cost_ls)
    cost_macro["short_cost_remeasure"] = dict(cost_ls["short_cost_remeasure"])
    cost_macro["repo_linked"] = dict(cost_ls["repo_linked"])
    return cost_md, cost_macro


def holding_from_period_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float,
) -> dict[str, Any] | None:
    recs: list[dict[str, Any]] = []
    for r in rows:
        if r.get("status") == "ok" and r.get("holding_records"):
            recs.extend(list(r["holding_records"]))
    if not recs:
        return None
    return holding_metrics_report(recs, one_way_cost=one_way_cost)


def scenario_rows_from_period_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float,
) -> list[dict[str, Any]]:
    ok = [
        r
        for r in rows
        if r.get("status") == "ok" and r.get("gross_signed_mean_active") is not None
    ]
    if not ok:
        return [
            scenario_row(sid, not_applicable=True, na_reason=reason)
            for sid, reason in _NA_SCENARIOS
        ]
    grosses = [float(r["gross_signed_mean_active"]) for r in ok]
    nets = [
        float(r["net_one_way_mean_active"])
        if r.get("net_one_way_mean_active") is not None
        else float(r["gross_signed_mean_active"]) - float(one_way_cost)
        for r in ok
    ]
    worst_i = min(range(len(grosses)), key=lambda i: grosses[i])
    vol_i = max(range(len(grosses)), key=lambda i: abs(grosses[i]))
    return [
        scenario_row(
            SCENARIO_CRASH,
            gross_signed_mean=grosses[worst_i],
            net_one_way_mean=nets[worst_i],
        ),
        scenario_row(
            SCENARIO_HIGH_VOL,
            gross_signed_mean=grosses[vol_i],
            net_one_way_mean=nets[vol_i],
        ),
        scenario_row(
            SCENARIO_RATE_UP,
            gross_signed_mean=mean(grosses),
            net_one_way_mean=mean(nets),
            notes="proxy: overall mean (rate_up slice not fully segmented)",
        ),
        scenario_row(
            SCENARIO_RATE_DOWN,
            gross_signed_mean=mean(grosses),
            net_one_way_mean=mean(nets),
            notes="proxy: overall mean (rate_down slice not fully segmented)",
        ),
        scenario_row(
            SCENARIO_LIQUIDITY_STRESS,
            not_applicable=True,
            na_reason="no liquidity stress dataset in this offline path",
        ),
    ]


def risk_from_rows(
    rows: list[dict[str, Any]],
    signal_id: str,
    *,
    one_way_cost: float,
) -> dict[str, Any]:
    return evaluate_risk_scenarios(
        scenario_rows_from_period_rows(rows, one_way_cost=one_way_cost),
        rate_data_usable=True,
        liquidity_data_available=False,
        prefer_fail_on_sign_break=True,
        signal_id=signal_id,
    )


__all__ = [
    "apply_ls_short_cost_remeasure",
    "class_hyp_cost_assumptions",
    "holding_from_period_rows",
    "normalize_short_sensitivity",
    "remeasure_ls_rows",
    "risk_from_rows",
    "robustness_gate_from_rows",
    "scenario_rows_from_period_rows",
]
