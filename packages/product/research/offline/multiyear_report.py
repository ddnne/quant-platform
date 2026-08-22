"""Offline multi-year class-hyp reporting (not CF SoT; no GO).

Stats, sign-selection, and candidate summary from stitched period rows.
Gates / cost / risk: ``research.offline.multiyear_report_gates``.
Window stitch / public entry: ``research.offline.multiyear``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    EVENT_POST_ENTRY_MODE,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    economic_net_meaningful,
    multi_year_skew_check,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    production_candidate_bar,
)
from research.cost_models import SHORT_BORROW_SPREAD_SENSITIVITY
from research.holding_metrics import cost_amortization_report
from research.offline.bar_eval_common import _freeze
from research.offline.multiyear_report_gates import (
    apply_ls_short_cost_remeasure,
    class_hyp_cost_assumptions,
    holding_from_period_rows,
    normalize_short_sensitivity,
    risk_from_rows,
    robustness_gate_from_rows,
)
from research.sign_selection import (
    SIGN_INVERTED,
    SIGN_ORIGINAL,
    SIGN_SELECTION_VERSION,
    SIGN_SELECTION_WAVE,
    sign_selection_from_period_rows,
)
from research.stats_metrics import period_stats_report, stats_bar_check

# key, paper_mean_negative, hold_days. Paper-neg flags from W85 multi-window.
_SIGN_FLIP_TARGETS: tuple[tuple[str, bool, int], ...] = (
    ("cross_section_hold_10", True, 10),
    ("cross_section_hold_10_mom3", False, 10),
    ("fundamentals_hold_10", True, 10),
)

_SUMMARY_KEYS: tuple[str, ...] = (
    "multi_day_hold",
    "multi_day_hold_10",
    "event_post",
    "macro_conditioned",
    "cross_section_relative",
    "cross_section_hold_10",
    "cross_section_hold_10_mom3",
    "flow_demand",
    "fundamentals_price",
    "fundamentals_hold_10",
)


def _n_ok(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for r in rows if r.get("status") == "ok")


def _compact(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "holding_records"} for r in rows]


def _econ_from_rows(
    rows: Sequence[Mapping[str, Any]], *, min_economic_net: float
) -> dict[str, Any]:
    nets = [
        r.get("net_one_way_mean_active")
        for r in rows
        if r.get("status") == "ok" and r.get("net_one_way_mean_active") is not None
    ]
    return economic_net_meaningful(
        nets, min_mean_net=float(min_economic_net), require_positive_majority=True
    )


def _aggregate_occurrence_multiday(
    rows: Sequence[Mapping[str, Any]],
    *,
    hold_days: int,
    min_activation_rate_multiday: float,
) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "ok"]
    n_active = sum(int(r.get("n_active_positions") or 0) for r in ok)
    n_cd = sum(int(r.get("n_code_days") or 0) for r in ok)
    n_td = sum(int(r.get("n_trading_days") or 0) for r in ok)
    n_codes = 0
    for r in ok:
        n_codes = max(n_codes, int(r.get("n_codes") or 0))
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_cd,
        n_trading_days=n_td,
        n_codes=n_codes,
        hold_days=hold_days,
        min_activation_rate=float(min_activation_rate_multiday),
    )
    occ["per_period"] = [
        {
            "period_id": r.get("period_id"),
            "occurrence": r.get("occurrence"),
            "n_active": r.get("n_active_positions"),
            "n_code_days": r.get("n_code_days"),
            "n_trading_days": r.get("n_trading_days"),
        }
        for r in ok
    ]
    return occ


def _aggregate_occurrence_event(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_events_per_code_year: float,
    min_events_per_trading_day: float,
) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "ok"]
    n_events = sum(int(r.get("n_events") or 0) for r in ok)
    n_scored = sum(int(r.get("n_active_positions") or 0) for r in ok)
    n_td = sum(int(r.get("n_trading_days") or 0) for r in ok)
    n_cd = sum(int(r.get("n_code_days") or 0) for r in ok)
    n_codes = 0
    for r in ok:
        n_codes = max(n_codes, int(r.get("n_codes") or 0))
    occ = occurrence_rate_event_post(
        n_events=n_events,
        n_scored=n_scored,
        n_trading_days=n_td,
        n_codes=n_codes,
        n_code_days=n_cd,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
        min_events_per_code_year=float(min_events_per_code_year),
        min_events_per_trading_day=float(min_events_per_trading_day),
    )
    occ["per_period"] = [
        {
            "period_id": r.get("period_id"),
            "occurrence": r.get("occurrence"),
            "n_events": r.get("n_events"),
            "n_scored": r.get("n_active_positions"),
            "n_trading_days": r.get("n_trading_days"),
        }
        for r in ok
    ]
    return occ


def _skew_from_rows(
    rows: Sequence[Mapping[str, Any]], *, max_year_pos_net_share: float
) -> dict[str, Any]:
    nets: dict[str, float | None] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        pid_r = str(r.get("period_id") or r.get("year") or "p")
        nets[pid_r] = r.get("net_one_way_mean_active")
    return multi_year_skew_check(nets, max_pos_share=float(max_year_pos_net_share))


def _stats_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    hold_days: int | None,
    min_abs_t_stat: float,
    min_sharpe_period: float,
    min_period_win_rate: float,
    min_positive_periods: int,
) -> dict[str, Any]:
    ok_rows = [
        r
        for r in rows
        if r.get("status") == "ok" and r.get("net_one_way_mean_active") is not None
    ]
    nets = [float(r["net_one_way_mean_active"]) for r in ok_rows]
    pids = [str(r.get("period_id") or r.get("year") or "p") for r in ok_rows]
    stats = period_stats_report(nets, period_ids=pids, hold_days=hold_days)
    trade_rows = []
    for r in ok_rows:
        ts = r.get("trade_stats")
        if isinstance(ts, Mapping):
            trade_rows.append(
                {
                    "period_id": r.get("period_id"),
                    "n_trades": ts.get("n_trades"),
                    "mean_net": ts.get("mean_net"),
                    "t_stat": ts.get("t_stat"),
                    "sharpe_ann": ts.get("sharpe_ann"),
                    "win_rate": ts.get("win_rate"),
                    "payoff": ts.get("payoff"),
                    "max_dd": ts.get("max_dd"),
                }
            )
    if trade_rows:
        stats["per_period_trade_stats"] = trade_rows
    bar = stats_bar_check(
        stats,
        min_abs_t=float(min_abs_t_stat),
        min_sharpe=float(min_sharpe_period),
        min_win_rate=float(min_period_win_rate),
        min_positive_periods=int(min_positive_periods),
    )
    return {"stats": stats, "stats_bar": bar}


def _candidate_verdict(
    gate: dict[str, Any] | None,
    risk: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    *,
    n_ok: int,
    occurrence: Mapping[str, Any] | None,
    hyp_kind: str,
    hold_days_for_occ: int,
    checklist_complete: bool,
    require_stats_bar: bool,
    min_economic_net: float,
    min_activation_rate_multiday: float,
    min_events_per_code_year: float,
    min_events_per_trading_day: float,
    min_years_research_candidate: int,
    max_year_pos_net_share: float,
    min_abs_t_stat: float,
    min_sharpe_period: float,
    min_period_win_rate: float,
    min_positive_periods: int,
) -> dict[str, Any]:
    """W81 production bar: gate + risk + econ + occurrence + skew + stats."""
    gate_pass = bool(gate and gate.get("passed"))
    risk_ok = bool(risk and risk.get("research_candidate_allowed"))
    econ = _econ_from_rows(rows, min_economic_net=min_economic_net)
    econ_ok = bool(econ.get("meaningful"))
    if occurrence is None:
        if hyp_kind == "event_post":
            occurrence = _aggregate_occurrence_event(
                rows,
                min_events_per_code_year=min_events_per_code_year,
                min_events_per_trading_day=min_events_per_trading_day,
            )
        else:
            occurrence = _aggregate_occurrence_multiday(
                rows,
                hold_days=hold_days_for_occ,
                min_activation_rate_multiday=min_activation_rate_multiday,
            )
    occ_ok = bool((occurrence or {}).get("sufficient"))
    skew = _skew_from_rows(rows, max_year_pos_net_share=max_year_pos_net_share)
    skew_ok = bool(skew.get("ok"))
    multi_year_ok = bool(n_ok >= int(min_years_research_candidate))
    stats_pack = _stats_from_rows(
        rows,
        hold_days=hold_days_for_occ,
        min_abs_t_stat=min_abs_t_stat,
        min_sharpe_period=min_sharpe_period,
        min_period_win_rate=min_period_win_rate,
        min_positive_periods=min_positive_periods,
    )
    stats = stats_pack["stats"]
    sbar = stats_pack["stats_bar"]
    stats_ok = bool(sbar.get("stats_ok"))
    bar = production_candidate_bar(
        checklist_complete=bool(checklist_complete),
        gate_passed=gate_pass,
        risk_ok=risk_ok,
        economic_net_ok=econ_ok,
        occurrence_ok=occ_ok,
        multi_year_ok=multi_year_ok,
        skew_ok=skew_ok,
        n_ok_periods=n_ok,
        min_years=int(min_years_research_candidate),
        economic_net=econ,
        occurrence=occurrence,
        skew=skew,
        stats_ok=stats_ok,
        stats=stats,
        stats_bar=sbar,
        require_stats=bool(require_stats_bar),
    )
    return {
        "research_candidate": bool(bar.get("research_candidate")),
        "research_candidate_allowed": bool(bar.get("research_candidate_allowed")),
        "candidate_yes_no": bar.get("candidate_yes_no"),
        "gate_passed": gate_pass,
        "risk_scenarios_ok": risk_ok,
        "economic_net": econ,
        "economic_net_ok": econ_ok,
        "occurrence": dict(occurrence or {}),
        "occurrence_ok": occ_ok,
        "skew": skew,
        "skew_ok": skew_ok,
        "stats": stats,
        "stats_bar": sbar,
        "stats_ok": stats_ok,
        "production_criteria": bar.get("production_criteria"),
        "n_ok_periods": n_ok,
        "verdict": bar.get("verdict"),
        "min_economic_net": float(min_economic_net),
        "min_years_research_candidate": int(min_years_research_candidate),
        "min_abs_t_stat": float(min_abs_t_stat),
        "min_sharpe_period": float(min_sharpe_period),
        "min_period_win_rate": float(min_period_win_rate),
        "min_positive_periods": int(min_positive_periods),
        "note": bar.get("note"),
    }


def _class_block(
    *,
    signal_id: str,
    hyp_class: str,
    rows: list[dict[str, Any]],
    gate: dict[str, Any] | None,
    risk: dict[str, Any] | None,
    floors: Mapping[str, Any],
    cost: dict[str, Any] | None = None,
    holding: dict[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    hyp_kind: str = "generic",
    hold_days_for_occ: int = 5,
) -> dict[str, Any]:
    n_ok = _n_ok(rows)
    cand = _candidate_verdict(
        gate,
        risk,
        rows,
        n_ok=n_ok,
        occurrence=None,
        hyp_kind=hyp_kind,
        hold_days_for_occ=hold_days_for_occ,
        **floors,
    )
    block: dict[str, Any] = {
        "signal_id": signal_id,
        "hypothesis_class": hyp_class,
        "years": _compact(rows),
        "cross_year_table": _compact([r for r in rows if r.get("status") == "ok"]),
        "robustness_gate": gate,
        "cost_assumption": cost,
        "risk_scenarios": risk,
        "candidate": cand,
        "occurrence": cand.get("occurrence"),
    }
    if holding is not None:
        block["holding"] = holding
    if extra:
        block.update(dict(extra))
    return block


def _side_pack(side: Mapping[str, Any], sign: int) -> dict[str, Any]:
    return {
        "sign": sign,
        "mean_net": side.get("mean_net"),
        "mean_net_bp": side.get("mean_net_bp"),
        "t_stat": side.get("t_stat"),
        "sharpe": side.get("sharpe"),
        "win_rate": side.get("win_rate"),
        "n_pos": side.get("n_pos"),
        "n_neg": side.get("n_neg"),
    }


def _apply_sign_selection_to_block(
    block: dict[str, Any], sel: Mapping[str, Any]
) -> dict[str, Any]:
    """Attach W86 sign-selection onto a class block; return compact summary."""
    block["sign_selection"] = sel
    block["chosen_sign"] = sel.get("chosen_sign")
    block["chosen_sign_label"] = sel.get("chosen_label")
    block["sign_selection_decision"] = sel.get("decision")
    chosen = sel.get("chosen_sign")
    if chosen == SIGN_INVERTED:
        block["metrics_after_sign"] = _side_pack(
            sel.get("inverted") or {}, SIGN_INVERTED
        )
    elif chosen == SIGN_ORIGINAL:
        block["metrics_after_sign"] = _side_pack(
            sel.get("original") or {}, SIGN_ORIGINAL
        )
    else:
        block["metrics_after_sign"] = {
            "sign": None,
            "mean_net": None,
            "reason": sel.get("decision"),
        }
    cand_b = block.get("candidate")
    if isinstance(cand_b, dict) and chosen is None:
        cand_b["sign_selection_demote"] = True
        cand_b["research_candidate"] = False
        cand_b["research_candidate_allowed"] = False
        cand_b["candidate_yes_no"] = "no"
        cand_b["verdict"] = "not_candidate_sign_both_sides_fail"
        cand_b["note_sign"] = (
            "W86 both sides fail non-zero / non-positive after cost "
            "→ demote (not Mass/READY path)."
        )
    elif isinstance(cand_b, dict):
        cand_b["chosen_sign"] = chosen
        cand_b["chosen_sign_label"] = sel.get("chosen_label")
        cand_b["sign_selection_decision"] = sel.get("decision")
        if chosen == SIGN_INVERTED:
            inv = sel.get("inverted") or {}
            cand_b["stats_original_side"] = cand_b.get("stats")
            cand_b["stats_chosen_side"] = {
                "mean_net": inv.get("mean_net"),
                "t_stat": inv.get("t_stat"),
                "sharpe": inv.get("sharpe"),
                "win_rate": inv.get("win_rate"),
                "n_pos": inv.get("n_pos"),
                "n_neg": inv.get("n_neg"),
                "sign": SIGN_INVERTED,
            }
    return {
        "chosen_sign": sel.get("chosen_sign"),
        "chosen_label": sel.get("chosen_label"),
        "decision": sel.get("decision"),
        "verdict": sel.get("verdict"),
        "chosen_mean_net_bp": sel.get("chosen_mean_net_bp"),
        "chosen_t_stat": sel.get("chosen_t_stat"),
        "chosen_sharpe": sel.get("chosen_sharpe"),
        "original_mean_net_bp": (sel.get("original") or {}).get("mean_net_bp"),
        "original_t_stat": (sel.get("original") or {}).get("t_stat"),
        "original_sharpe": (sel.get("original") or {}).get("sharpe"),
        "inverted_mean_net_bp": (sel.get("inverted") or {}).get("mean_net_bp"),
        "inverted_t_stat": (sel.get("inverted") or {}).get("t_stat"),
        "inverted_sharpe": (sel.get("inverted") or {}).get("sharpe"),
        "reasons": sel.get("reasons"),
    }


def _candidate_summary_row(
    block: Mapping[str, Any], ss_sum: Mapping[str, Any]
) -> dict[str, Any]:
    cand = block.get("candidate") or {}
    rc = bool(cand.get("research_candidate"))
    stats = cand.get("stats") or {}
    return {
        "signal_id": block.get("signal_id"),
        "gate_passed": cand.get("gate_passed"),
        "economic_net_ok": cand.get("economic_net_ok"),
        "occurrence_ok": cand.get("occurrence_ok"),
        "skew_ok": cand.get("skew_ok"),
        "stats_ok": cand.get("stats_ok"),
        "research_candidate_allowed": cand.get("research_candidate_allowed"),
        "research_candidate": rc,
        "verdict": cand.get("verdict"),
        "candidate_yes_no": cand.get("candidate_yes_no") or "no",
        "mean_net": (cand.get("economic_net") or {}).get("mean_net"),
        "t_stat": stats.get("t_stat"),
        "sharpe": stats.get("sharpe"),
        "win_rate": stats.get("win_rate"),
        "payoff": stats.get("payoff"),
        "max_dd": stats.get("max_dd"),
        "calmar": stats.get("calmar"),
        "n_ok_periods": cand.get("n_ok_periods"),
        "chosen_sign": ss_sum.get("chosen_sign", block.get("chosen_sign")),
        "chosen_sign_label": ss_sum.get("chosen_label", block.get("chosen_sign_label")),
        "sign_selection_decision": ss_sum.get("decision"),
        "mean_net_bp_original": ss_sum.get("original_mean_net_bp"),
        "mean_net_bp_inverted": ss_sum.get("inverted_mean_net_bp"),
        "t_stat_original": ss_sum.get("original_t_stat"),
        "t_stat_inverted": ss_sum.get("inverted_t_stat"),
        "decision": (
            "keep"
            if rc
            else (
                "demote"
                if (
                    (cand.get("production_criteria") or {}).get("w80_core_ok")
                    and not cand.get("stats_ok")
                )
                or cand.get("sign_selection_demote")
                else "not_candidate"
            )
        ),
    }


def assemble_class_hyp_multi_year_report(
    *,
    period_list: Sequence[Mapping[str, Any]],
    selected: Sequence[str],
    h: int,
    macro_mode: str,
    one_way_cost: float,
    prefer_liquidity_linked: bool,
    apply_short_cost_remeasure: bool,
    short_fraction_ls: float,
    short_borrow_sensitivity: str,
    apply_robustness_gate: bool,
    min_periods_gate: int,
    min_active_per_period: int,
    min_economic_net: float,
    min_activation_rate_multiday: float,
    min_events_per_code_year: float,
    min_events_per_trading_day: float,
    min_years_research_candidate: int,
    max_year_pos_net_share: float,
    min_abs_t_stat: float,
    min_sharpe_period: float,
    min_period_win_rate: float,
    min_positive_periods: int,
    require_stats_bar: bool,
    checklist_complete: bool,
    include_cross_section: bool,
    include_cross_section_hold_10: bool,
    include_cross_section_hold_10_mom3: bool,
    include_event_post: bool,
    include_flow_demand: bool,
    include_fundamentals_price: bool,
    include_fundamentals_hold_10: bool,
    include_multi_day_hold_10: bool,
    cross_section_hold_days: int,
    event_hold_days: int,
    flow_hold_days: int,
    fund_hold_days: int,
    xs_mom_n: int,
    xs10_mom_n: int,
    xs10_mom3_n: int,
    xs_long_frac: float,
    xs_short_frac: float,
    fund_mom_n: int,
    fund10_mom_n: int,
    fund_mode_s: str,
    flow_short_confirm: bool,
    results_md: list[dict[str, Any]],
    results_md10: list[dict[str, Any]],
    results_macro: list[dict[str, Any]],
    results_xs: list[dict[str, Any]],
    results_xs10: list[dict[str, Any]],
    results_xs10_mom3: list[dict[str, Any]],
    results_event: list[dict[str, Any]],
    results_flow: list[dict[str, Any]],
    results_fund: list[dict[str, Any]],
    results_fund10: list[dict[str, Any]],
    repo_series: Mapping[str, Any] | None,
    repo_load_note: Mapping[str, Any],
    fins_load_note: Mapping[str, Any],
    short_load_note: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble class-hyp multi-year report from stitched period rows."""
    from research.offline.multiyear import CLASS_HYP_EVAL_VERSION, CLASS_HYP_EVAL_WAVE

    short_frac_ls = float(short_fraction_ls)
    short_sens = normalize_short_sensitivity(short_borrow_sensitivity)
    remapped, short_cost_remeasure_blocks = apply_ls_short_cost_remeasure(
        apply=apply_short_cost_remeasure,
        repo_series=repo_series,
        short_fraction=short_frac_ls,
        short_sens=short_sens,
        targets=(
            ("macro_conditioned", results_macro, h, True),
            (
                "cross_section_relative",
                results_xs,
                int(cross_section_hold_days),
                include_cross_section,
            ),
            (
                "cross_section_hold_10",
                results_xs10,
                10,
                include_cross_section_hold_10 and bool(results_xs10),
            ),
            (
                "cross_section_hold_10_mom3",
                results_xs10_mom3,
                10,
                include_cross_section_hold_10_mom3 and bool(results_xs10_mom3),
            ),
            (
                "fundamentals_price",
                results_fund,
                int(fund_hold_days),
                include_fundamentals_price,
            ),
            (
                "fundamentals_hold_10",
                results_fund10,
                10,
                include_fundamentals_hold_10 and bool(results_fund10),
            ),
        ),
    )
    results_macro = remapped["macro_conditioned"]
    results_xs = remapped["cross_section_relative"]
    results_xs10 = remapped["cross_section_hold_10"]
    results_xs10_mom3 = remapped["cross_section_hold_10_mom3"]
    results_fund = remapped["fundamentals_price"]
    results_fund10 = remapped["fundamentals_hold_10"]

    def _gate(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any] | None:
        return robustness_gate_from_rows(
            rows,
            signal_id,
            apply=apply_robustness_gate,
            min_periods_gate=min_periods_gate,
            min_active_per_period=min_active_per_period,
            one_way_cost=one_way_cost,
        )

    def _risk(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any]:
        return risk_from_rows(rows, signal_id, one_way_cost=one_way_cost)

    gate_md = _gate(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    gate_md10 = (
        _gate(results_md10, SIGNAL_ID_MULTI_DAY_HOLD + "_hold10")
        if include_multi_day_hold_10
        else None
    )
    gate_macro = _gate(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    gate_xs = _gate(results_xs, SIGNAL_ID_CROSS_SECTION) if include_cross_section else None
    gate_xs10 = (
        _gate(results_xs10, SIGNAL_ID_CROSS_SECTION + "_hold10")
        if include_cross_section_hold_10 and results_xs10
        else None
    )
    gate_xs10_mom3 = (
        _gate(results_xs10_mom3, SIGNAL_ID_CROSS_SECTION + "_hold10_mom3")
        if include_cross_section_hold_10_mom3 and results_xs10_mom3
        else None
    )
    gate_event = _gate(results_event, SIGNAL_ID_EVENT_POST) if include_event_post else None
    gate_flow = _gate(results_flow, SIGNAL_ID_FLOW_DEMAND) if include_flow_demand else None
    gate_fund = (
        _gate(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )
    gate_fund10 = (
        _gate(results_fund10, SIGNAL_ID_FUNDAMENTALS_PRICE + "_hold10")
        if include_fundamentals_hold_10 and results_fund10
        else None
    )

    cost_md, cost_ls = class_hyp_cost_assumptions(
        one_way_cost=one_way_cost,
        prefer_liquidity_linked=prefer_liquidity_linked,
        apply_short_cost_remeasure=apply_short_cost_remeasure,
        short_frac_ls=short_frac_ls,
        short_sens=short_sens,
        repo_series=repo_series,
        short_cost_remeasure_blocks=short_cost_remeasure_blocks,
    )
    holding_md = holding_from_period_rows(results_md, one_way_cost=one_way_cost)
    risk_md = _risk(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    risk_macro = _risk(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    risk_xs = _risk(results_xs, SIGNAL_ID_CROSS_SECTION) if include_cross_section else None
    risk_xs10 = (
        _risk(results_xs10, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section_hold_10 and results_xs10
        else None
    )
    risk_xs10_mom3 = (
        _risk(results_xs10_mom3, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section_hold_10_mom3 and results_xs10_mom3
        else None
    )
    risk_event = _risk(results_event, SIGNAL_ID_EVENT_POST) if include_event_post else None
    risk_flow = _risk(results_flow, SIGNAL_ID_FLOW_DEMAND) if include_flow_demand else None
    risk_fund = (
        _risk(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )
    risk_fund10 = (
        _risk(results_fund10, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_hold_10 and results_fund10
        else None
    )

    floors = {
        "checklist_complete": checklist_complete,
        "require_stats_bar": require_stats_bar,
        "min_economic_net": min_economic_net,
        "min_activation_rate_multiday": min_activation_rate_multiday,
        "min_events_per_code_year": min_events_per_code_year,
        "min_events_per_trading_day": min_events_per_trading_day,
        "min_years_research_candidate": min_years_research_candidate,
        "max_year_pos_net_share": max_year_pos_net_share,
        "min_abs_t_stat": min_abs_t_stat,
        "min_sharpe_period": min_sharpe_period,
        "min_period_win_rate": min_period_win_rate,
        "min_positive_periods": min_positive_periods,
    }
    n_ok_md = _n_ok(results_md)
    n_ok_macro = _n_ok(results_macro)

    def _blk(**kw: Any) -> dict[str, Any]:
        return _class_block(floors=floors, **kw)

    out: dict[str, Any] = {
        "version": CLASS_HYP_EVAL_VERSION,
        "wave": CLASS_HYP_EVAL_WAVE,
        "hold_days": h,
        "macro_mode": macro_mode,
        "codes": selected,
        "one_way_cost": float(one_way_cost),
        "one_way_cost_bp": float(one_way_cost) * 10_000.0,
        "prefer_liquidity_linked": bool(prefer_liquidity_linked),
        "apply_short_cost_remeasure": bool(apply_short_cost_remeasure),
        "short_borrow_sensitivity": short_sens,
        "short_fraction_ls": short_frac_ls,
        "short_cost_sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "short_cost_remeasure": short_cost_remeasure_blocks,
        "min_economic_net": float(min_economic_net),
        "min_activation_rate_multiday": float(min_activation_rate_multiday),
        "min_events_per_code_year": float(min_events_per_code_year),
        "min_events_per_trading_day": float(min_events_per_trading_day),
        "min_years_research_candidate": int(min_years_research_candidate),
        "max_year_pos_net_share": float(max_year_pos_net_share),
        "min_abs_t_stat": float(min_abs_t_stat),
        "min_sharpe_period": float(min_sharpe_period),
        "min_period_win_rate": float(min_period_win_rate),
        "min_positive_periods": int(min_positive_periods),
        "require_stats_bar": bool(require_stats_bar),
        "repo_load": repo_load_note,
        "fins_load": fins_load_note,
        "short_load": short_load_note,
        "multi_day_hold": _blk(
            signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
            hyp_class=CLASS_MULTI_DAY_HOLD,
            rows=results_md,
            gate=gate_md,
            risk=risk_md,
            cost=cost_md,
            holding=holding_md,
            hyp_kind="multi_day_hold",
            hold_days_for_occ=h,
            extra={
                "cost_amortization": cost_amortization_report(
                    one_way_cost=one_way_cost
                ),
            },
        ),
        "macro_conditioned": _blk(
            signal_id=SIGNAL_ID_MACRO_CONDITIONED,
            hyp_class=CLASS_MACRO_CONDITIONED,
            rows=results_macro,
            gate=gate_macro,
            risk=risk_macro,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=h,
        ),
        "n_years_requested": len(period_list),
        "n_years_ok_multi_day_hold": n_ok_md,
        "n_years_ok_macro_conditioned": n_ok_macro,
        "history_source": (
            "local_r2_mirror_ndjson (W63 q4 + W64 full) + local_sqlite "
            "(jsda_repo_rates · fins_summary · fins_earnings_date · "
            "margin · short_ratio)"
        ),
        "label": "研究用・複数年クラス仮説評価・W81統計バー再判定・未宣言",
        **_freeze(),
        "note": (
            "W85–W86 class hyp multi-year offline eval. research_candidate=True "
            "only if checklist v2 + gate + risk + economic net + occurrence + "
            "multi-year without extreme skew + stats bar. Sign-selection both "
            "sides after cost. READY/Mass/operational GO never auto-connect."
        ),
    }

    def _put(key: str, include: bool, **kw: Any) -> None:
        if include:
            out[key] = _blk(**kw)

    _put(
        "multi_day_hold_10",
        include_multi_day_hold_10,
        signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
        hyp_class=CLASS_MULTI_DAY_HOLD,
        rows=results_md10,
        gate=gate_md10,
        risk=_risk(results_md10, SIGNAL_ID_MULTI_DAY_HOLD) if results_md10 else None,
        cost=cost_md,
        hyp_kind="multi_day_hold_10",
        hold_days_for_occ=10,
        extra={"variant": "hold_10", "n_ok": _n_ok(results_md10)},
    )
    xs_frac = {
        "long_frac": xs_long_frac,
        "short_frac": xs_short_frac,
    }
    _put(
        "cross_section_relative",
        include_cross_section,
        signal_id=SIGNAL_ID_CROSS_SECTION,
        hyp_class="cross_section_relative",
        rows=results_xs,
        gate=gate_xs,
        risk=risk_xs,
        cost=cost_ls,
        hyp_kind="generic",
        hold_days_for_occ=int(cross_section_hold_days),
        extra={
            "hold_days": int(cross_section_hold_days),
            "momentum_n": xs_mom_n,
            **xs_frac,
        },
    )
    _put(
        "cross_section_hold_10",
        include_cross_section_hold_10 and bool(results_xs10),
        signal_id=SIGNAL_ID_CROSS_SECTION,
        hyp_class="cross_section_relative",
        rows=results_xs10,
        gate=gate_xs10,
        risk=risk_xs10,
        cost=cost_ls,
        hyp_kind="generic",
        hold_days_for_occ=10,
        extra={
            "hold_days": 10,
            "momentum_n": xs10_mom_n,
            "variant": "hold_10",
            "n_ok": _n_ok(results_xs10),
            **xs_frac,
            "note": (
                f"W83 sticky hold=10 momentum_n={xs10_mom_n} (W82 pin). "
                "W86 sign-selection both sides after cost. Not Mass/READY."
            ),
        },
    )
    _put(
        "cross_section_hold_10_mom3",
        include_cross_section_hold_10_mom3 and bool(results_xs10_mom3),
        signal_id=SIGNAL_ID_CROSS_SECTION,
        hyp_class="cross_section_relative",
        rows=results_xs10_mom3,
        gate=gate_xs10_mom3,
        risk=risk_xs10_mom3,
        cost=cost_ls,
        hyp_kind="generic",
        hold_days_for_occ=10,
        extra={
            "hold_days": 10,
            "momentum_n": xs10_mom3_n,
            "variant": "hold_10_mom3",
            "n_ok": _n_ok(results_xs10_mom3),
            "promoted_wave": "W85 / w0816t",
            **xs_frac,
            "note": (
                f"W85 sticky hold=10 momentum_n={xs10_mom3_n}; parallel to "
                "mom=5 pin. W86 sign-selection both sides. Not Mass/READY."
            ),
        },
    )
    _put(
        "event_post",
        include_event_post,
        signal_id=SIGNAL_ID_EVENT_POST,
        hyp_class=CLASS_EVENT_POST,
        rows=results_event,
        gate=gate_event,
        risk=risk_event,
        cost=cost_md,
        hyp_kind="event_post",
        hold_days_for_occ=int(event_hold_days),
        extra={
            "post_hold_days": int(event_hold_days),
            "n_ok": _n_ok(results_event),
            "entry_mode": EVENT_POST_ENTRY_MODE,
            "pit_definition": "W82 DiscDate+DiscTime first non-look-ahead close",
        },
    )
    _put(
        "flow_demand",
        include_flow_demand,
        signal_id=SIGNAL_ID_FLOW_DEMAND,
        hyp_class=CLASS_FLOW_DEMAND,
        rows=results_flow,
        gate=gate_flow,
        risk=risk_flow,
        cost=cost_ls,
        hyp_kind="generic",
        hold_days_for_occ=int(flow_hold_days),
        extra={
            "hold_days": int(flow_hold_days),
            "require_short_confirm": flow_short_confirm,
            "n_ok": _n_ok(results_flow),
        },
    )
    _put(
        "fundamentals_price",
        include_fundamentals_price,
        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
        hyp_class=CLASS_FUNDAMENTALS_PRICE,
        rows=results_fund,
        gate=gate_fund,
        risk=risk_fund,
        cost=cost_ls,
        hyp_kind="generic",
        hold_days_for_occ=int(fund_hold_days),
        extra={
            "hold_days": int(fund_hold_days),
            "momentum_n": fund_mom_n,
            "mode": fund_mode_s,
            "n_ok": _n_ok(results_fund),
        },
    )
    _put(
        "fundamentals_hold_10",
        include_fundamentals_hold_10 and bool(results_fund10),
        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
        hyp_class=CLASS_FUNDAMENTALS_PRICE,
        rows=results_fund10,
        gate=gate_fund10,
        risk=risk_fund10,
        cost=cost_ls,
        hyp_kind="generic",
        hold_days_for_occ=10,
        extra={
            "hold_days": 10,
            "momentum_n": fund10_mom_n,
            "mode": fund_mode_s,
            "variant": "hold_10_mom_matched",
            "n_ok": _n_ok(results_fund10),
            "note": (
                "W83 fund hold=10 mom-matched. W86 sign-selection both sides "
                "after cost (paper-negative → flip-first). Not Mass/READY."
            ),
        },
    )

    sign_selection_blocks: dict[str, Any] = {}
    for skey, paper_neg, hold_ov in _SIGN_FLIP_TARGETS:
        block = out.get(skey)
        if not isinstance(block, dict):
            continue
        rows_ss = list(block.get("years") or block.get("cross_year_table") or [])
        sel = sign_selection_from_period_rows(
            rows_ss,
            hold_days=int(hold_ov),
            min_mean_net=float(min_economic_net),
            paper_mean_negative=bool(paper_neg),
        )
        compact = _apply_sign_selection_to_block(block, sel)
        compact["paper_mean_negative"] = bool(paper_neg)
        sign_selection_blocks[skey] = compact

    out["sign_selection"] = {
        "version": SIGN_SELECTION_VERSION,
        "wave": SIGN_SELECTION_WAVE,
        "blocks": sign_selection_blocks,
        "note": (
            "W86 evaluate both original and inverted after costs; "
            "prefer positive mean net with non-zero evidence (t guideline). "
            "Both fail → reject/explore demote. Not Mass/READY/live."
        ),
    }

    survivors: list[dict[str, Any]] = []
    for skey, _pn, _h in _SIGN_FLIP_TARGETS:
        ss = sign_selection_blocks.get(skey) or {}
        block = out.get(skey)
        if not isinstance(block, Mapping):
            continue
        cand = block.get("candidate") or {}
        chosen = ss.get("chosen_sign")
        if chosen is None:
            continue
        survivors.append(
            {
                "block_key": skey,
                "chosen_sign": chosen,
                "chosen_label": ss.get("chosen_label"),
                "momentum_n": block.get("momentum_n"),
                "hold_days": block.get("hold_days"),
                "research_candidate": bool(cand.get("research_candidate")),
                "mean_net_bp_chosen": ss.get("chosen_mean_net_bp"),
                "t_stat_chosen": ss.get("chosen_t_stat"),
                "sharpe_chosen": ss.get("chosen_sharpe"),
                "decision": ss.get("decision"),
            }
        )

    xs_surv = [s for s in survivors if s["block_key"].startswith("cross_section")]
    fund_surv = [s for s in survivors if s["block_key"].startswith("fundamentals")]
    if len(xs_surv) >= 2:
        xs_default = list(xs_surv)
        mom_compress_note = (
            "both xs mom5 and mom3 survive sign selection → keep both "
            "as parallel default representatives (no over-invest; not merge)"
        )
    elif len(xs_surv) == 1:
        xs_default = list(xs_surv)
        mom_compress_note = (
            f"single xs survivor after sign selection: {xs_surv[0]['block_key']}"
        )
    else:
        xs_default = []
        mom_compress_note = "no xs survivor after sign selection → demote both"

    out["default_path_representatives"] = {
        "wave": SIGN_SELECTION_WAVE,
        "xs_representatives": xs_default,
        "fund_representatives": fund_surv,
        "all_survivors": survivors,
        "mom3_vs_mom5": mom_compress_note,
        "n_default_wired_candidates": len(xs_default) + len(fund_surv),
        "note": (
            "Default representatives after W86 sign selection. "
            "research_candidate on block still requires full production bar; "
            "chosen_sign is recorded for StrategySpec signal_sign wiring. "
            "Not Mass / READY / ops GO / live."
        ),
    }

    summary: dict[str, Any] = {}
    any_research_candidate = False
    for key in _SUMMARY_KEYS:
        block = out.get(key)
        if not isinstance(block, Mapping):
            continue
        row = _candidate_summary_row(block, sign_selection_blocks.get(key) or {})
        if row["research_candidate"]:
            any_research_candidate = True
        summary[key] = row
    out["candidate_summary"] = summary
    out["any_research_candidate"] = any_research_candidate
    return out


__all__ = [
    "assemble_class_hyp_multi_year_report",
    "apply_ls_short_cost_remeasure",
    "class_hyp_cost_assumptions",
    "holding_from_period_rows",
    "normalize_short_sensitivity",
    "risk_from_rows",
    "robustness_gate_from_rows",
]
