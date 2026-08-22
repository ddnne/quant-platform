"""Standard research eval runner (W56 next-day; not candidate SoT).

``run_standard_research_eval``. Public imports stay on
:mod:`research.eval_harness` / :mod:`research.eval_harness_multiyear`.
Checklist: :mod:`research.eval_harness_checklist`. Mass/READY/GO closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
)
from research.eval_harness import EvalHarnessError, _closed_flags, assert_harness_closed
from research.eval_harness_checklist import (
    CHECKLIST_VERSION,
    CHECKLIST_VERSION_V1,
    STANDARD_EVAL_DAILY_PATH_DD_PROOF,
    STANDARD_EVAL_MODES,
    evaluate_checklist_v2_completeness,
)
from research.eval_harness_multiyear import (
    design_yearly_eval_windows,
    multi_year_availability_table,
)
from research.eval_harness_standard_costs import build_standard_eval_costs
from research.eval_harness_standard_modes import run_standard_eval_mode
from research.freezes import MASS_RESEARCH, PHASE7, READY_DECLARED
from research.robustness_gate import (
    DEFAULT_ONE_WAY_COST,
    evaluate_research_robustness_gate,
)
from research.single_shot_job import (
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    R2PutFn,
)


def run_standard_research_eval(
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    years: Sequence[int] | None = None,
    mode: str = "wiring_only",
    job_id_prefix: str = "eval-harness-std",
    codes: Sequence[str] | None = None,
    max_days: int = 80,
    min_days: int = 40,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    cost_change_reason: str | None = None,
    require_net_sign_majority: bool = True,
    apply_robustness_gate: bool = True,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    write_per_day_artifacts: bool = False,
    dry_run: bool = True,
    data_gap_notes: Any = None,
    include_holding: bool = True,
    holding_records: Sequence[Mapping[str, Any]] | None = None,
    period_rows_for_gate: Sequence[Mapping[str, Any]] | None = None,
    signal_ids: Sequence[str] | None = None,
    # --- checklist v2: leverage / short costs ---
    position_style: str = "long_only_unlevered",
    gross_leverage: float = 1.0,
    short_fraction: float = 0.0,
    short_borrow_annual_bp: float | None = None,
    financing_annual_bp: float | None = None,
    short_borrow_change_reason: str | None = None,
    financing_change_reason: str | None = None,
    uses_short: bool | None = None,
    uses_leverage: bool | None = None,
    leverage_short_cost_assumption: Mapping[str, Any] | None = None,
    # --- W78 / w0816m: prefer date-matched jsda_tokyo_repo_rates ---
    repo_rate_series: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    prefer_repo_linked: bool = True,
    require_repo_linked: bool = False,
    short_borrow_spread_bp: float | None = None,
    short_borrow_sensitivity: str | None = None,
    borrow_proxy_annual_bp: float | None = None,
    repo_required_dates: Sequence[Any] | None = None,
    # --- W79 / w0816n: liquidity-linked tx / short-spread modulation ---
    liquidity_proxy: Mapping[str, Any] | float | None = None,
    liquidity_bars: Sequence[Mapping[str, Any]] | None = None,
    liquidity_bucket: str | None = None,
    liquidity_adv_jpy: float | None = None,
    is_topix: bool | None = None,
    scale_category: str | None = None,
    prefer_liquidity_linked: bool = True,
    require_liquidity_linked: bool = False,
    liquidity_required_dates: Sequence[Any] | None = None,
    # --- checklist v2: risk scenarios ---
    scenario_rows: Sequence[Mapping[str, Any]] | None = None,
    rate_data_usable: bool = False,
    liquidity_data_available: bool = False,
    prefer_fail_on_sign_break: bool = True,
    scenario_weakness_disclosed: bool = False,
    scenario_weakness_notes: str | None = None,
    baseline_majority_sign: int | None = None,
    baseline_net_majority_sign: int | None = None,
    # --- holding near-required for HF ---
    high_frequency_hyp: bool = False,
    require_holding_for_hf: bool = True,
    # --- W100 / w0819c: daily_path_DD mandatory ---
    daily_path_dd: float | Mapping[str, Any] | None = None,
    dd_duration: int | None = None,
    recovered: bool | None = None,
    recovery_days: int | None = None,
    total_ret_net: float | None = None,
    period_net_dd: float | None = None,
    daily_path_pack: Mapping[str, Any] | None = None,
    daily_equities: Sequence[float] | None = None,
    daily_dates: Sequence[str] | None = None,
    daily_path_method: str | None = None,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "r2",
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> dict[str, Any]:
    """Standard research eval checklist v2. Incomplete → not candidate. Freeze closed.

    Modes: ``wiring_only``, ``s1_rejected_baseline``, ``s4_rejected_baseline``,
    ``class_hyp_offline``. Does not invent signals or auto-promote.
    """
    from research.baseline_catalog import (
        RESEARCH_STATUS_REJECTED,
        rejected_baseline_catalog,
    )
    from research.holding_metrics import holding_metrics_report
    from research.risk_scenarios import (
        default_na_scenario_bundle,
        evaluate_risk_scenarios,
    )
    from research.stats_metrics import evaluate_daily_path_dd_gate

    assert_harness_closed()
    mode_s = str(mode or "wiring_only").strip().lower()
    if mode_s not in STANDARD_EVAL_MODES:
        raise EvalHarnessError(
            f"run_standard_research_eval mode must be one of "
            f"{list(STANDARD_EVAL_MODES)}, got {mode!r}"
        )

    steps: list[str] = ["assert_harness_closed"]
    cost, cost_assumption, lev_short, repo_series_norm = build_standard_eval_costs(
        locals()
    )
    steps.extend(["cost_assumption", "leverage_short_cost_assumptions"])

    if periods is None:
        designed = design_yearly_eval_windows(
            years, max_days=max_days, min_days=min_days, codes=codes
        )
    else:
        designed = [dict(p) for p in periods]
    steps.append("multi_year_or_long_period_design")
    availability = multi_year_availability_table(designed)
    gap_notes: Any = (
        data_gap_notes
        if data_gap_notes is not None
        else {
            "n_periods": len(designed),
            "skipped": [p.get("period_id") for p in designed if p.get("skip_reason")],
        }
    )
    steps.append("data_gap_disclosure")

    catalog = rejected_baseline_catalog()
    baseline_demo: dict[str, Any] = {
        "mode": mode_s,
        "catalog_version": catalog.get("version"),
        "rejected_signal_ids": list(catalog.get("signal_ids") or []),
        "research_status_value": RESEARCH_STATUS_REJECTED,
        "new_signals_registered": False,
    }
    steps.append("baseline_catalog_check")

    executable = any(
        not p.get("skip_reason")
        and str(p.get("period_start") or "").strip()
        and str(p.get("period_end") or "").strip()
        and (
            p.get("r2_raw_lines_by_dataset")
            or p.get("r2_object_keys_by_dataset")
            or p.get("r2_local_paths_by_dataset")
            or d1_execute is not None
            or history_source == "d1_tip"
        )
        for p in designed
    )
    mode_out = run_standard_eval_mode(
        {
            "mode_s": mode_s,
            "designed": designed,
            "periods_given": periods is not None,
            "dry_run": dry_run,
            "executable": executable,
            "period_rows_for_gate": period_rows_for_gate,
            "codes": codes,
            "cost": cost,
            "max_days": max_days,
            "min_days": min_days,
            "min_periods_gate": min_periods_gate,
            "min_active_per_period": min_active_per_period,
            "apply_robustness_gate": apply_robustness_gate,
            "require_net_sign_majority": require_net_sign_majority,
            "include_holding": include_holding,
            "holding_records": holding_records,
            "scenario_rows": scenario_rows,
            "rate_data_usable": rate_data_usable,
            "repo_series_norm": repo_series_norm,
            "baseline_demo": baseline_demo,
            "job_id_prefix": job_id_prefix,
            "feature_row_limit": feature_row_limit,
            "volume_change_abs_min": volume_change_abs_min,
            "write_per_day_artifacts": write_per_day_artifacts,
            "d1_execute": d1_execute,
            "r2_put": r2_put,
            "staging_dir": staging_dir,
            "wrangler": wrangler,
            "wrangler_config": wrangler_config,
            "history_source": history_source,
            "r2_get": r2_get,
            "r2_bucket": r2_bucket,
            "signal_ids": signal_ids,
        }
    )
    steps.extend(mode_out["steps"])
    multi_year_result = mode_out["multi_year"]
    class_hyp_bundle = mode_out["class_hyp"]
    gate = mode_out["gate"]
    holding_records = mode_out["holding_records"]
    scenario_rows = mode_out["scenario_rows"]
    rate_data_usable = mode_out["rate_data_usable"]
    repo_series_norm = mode_out["repo_series_norm"]

    if period_rows_for_gate is not None and mode_s != "wiring_only":
        if apply_robustness_gate:
            sid = str(baseline_demo.get("signal_id") or DEFAULT_SIGNAL_ID)
            gate = evaluate_research_robustness_gate(
                period_rows_for_gate,
                signal_id=sid,
                min_periods=min_periods_gate,
                min_active_per_period=min_active_per_period,
                one_way_cost=cost,
                require_net_sign_majority=require_net_sign_majority,
            )
            if "robustness_gate_v2" not in steps:
                steps.append("robustness_gate_v2")

    holding: dict[str, Any] | None = None
    holding_metrics_done = False
    if include_holding:
        precomputed_holding = None
        if class_hyp_bundle is not None:
            precomputed_holding = (class_hyp_bundle.get("multi_day_hold") or {}).get(
                "holding"
            )
        if holding_records is not None:
            holding = holding_metrics_report(holding_records, one_way_cost=cost)
            steps.append("holding_turnover_metrics")
            holding_metrics_done = True
        elif isinstance(precomputed_holding, Mapping):
            holding = dict(precomputed_holding)
            steps.append("holding_turnover_metrics")
            holding_metrics_done = True
        else:
            holding = {"status": "annotation_only", **_closed_flags()}
            steps.append("holding_turnover_annotation")

    gate_signal_id_for_scen = str(
        baseline_demo.get("signal_id") or DEFAULT_SIGNAL_ID
    )
    b_maj = baseline_majority_sign
    b_net = baseline_net_majority_sign
    if isinstance(gate, Mapping):
        crit = gate.get("criteria") or {}
        if b_maj is None:
            b_maj = (crit.get("sign_majority") or {}).get("majority_sign")
        if b_net is None:
            b_net = (crit.get("net_sign_majority") or {}).get("majority_net_sign")

    if scenario_rows is not None:
        scen_input = list(scenario_rows)
    else:
        scen_input = default_na_scenario_bundle(
            rate_data_usable=rate_data_usable,
            liquidity_data_available=liquidity_data_available,
        )
    risk_scen = evaluate_risk_scenarios(
        scen_input,
        baseline_majority_sign=b_maj,
        baseline_net_majority_sign=b_net,
        rate_data_usable=rate_data_usable,
        liquidity_data_available=liquidity_data_available,
        prefer_fail_on_sign_break=prefer_fail_on_sign_break,
        scenario_weakness_disclosed=scenario_weakness_disclosed,
        scenario_weakness_notes=scenario_weakness_notes,
        signal_id=gate_signal_id_for_scen,
    )
    steps.append("risk_scenario_evaluation")

    daily_path = evaluate_daily_path_dd_gate(
        daily_path_dd=daily_path_dd,
        dd_duration=dd_duration,
        recovered=recovered,
        recovery_days=recovery_days,
        total_ret_net=total_ret_net,
        period_net_dd=period_net_dd,
        daily_path_pack=daily_path_pack,
        equities=daily_equities,
        dates=daily_dates,
        method=daily_path_method,
    )
    steps.extend(["daily_path_dd", "freeze_ready_mass_phase7_closed"])

    gate_passed = bool(gate.get("passed")) if isinstance(gate, Mapping) else False
    multi_year_present = bool(designed) and (
        multi_year_result is not None
        or any(
            str(p.get("period_start") or "").strip()
            and str(p.get("period_end") or "").strip()
            for p in designed
        )
    )
    freeze_closed = (
        MASS_RESEARCH == "NO-GO"
        and PHASE7 == "OFF"
        and READY_DECLARED is False
    )
    completeness = evaluate_checklist_v2_completeness(
        multi_year_present=multi_year_present,
        cost_assumption_present=True,
        leverage_short_complete=bool(lev_short.get("assumptions_complete")),
        robustness_gate_present=gate is not None,
        data_gap_disclosed=gap_notes is not None,
        risk_scenarios_passed=bool(risk_scen.get("passed")),
        risk_scenarios_candidate_allowed=bool(
            risk_scen.get("research_candidate_allowed")
        ),
        freeze_closed=freeze_closed,
        holding_present=holding_metrics_done,
        high_frequency_hyp=bool(high_frequency_hyp),
        require_holding_for_hf=bool(require_holding_for_hf),
        checklist_skipped=False,
        daily_path_dd_complete=bool(daily_path.get("complete")),
        period_net_dd_only=bool(daily_path.get("period_net_dd_only")),
        period_net_dd_zero_daily_unmeasured=bool(
            daily_path.get("period_net_dd_zero_daily_unmeasured")
        ),
    )
    steps.append("checklist_v2_completeness")

    # Incomplete forces False; harness never auto-promotes.
    research_candidate = False
    research_candidate_allowed = bool(completeness.get("complete"))

    return {
        "checklist_version": CHECKLIST_VERSION,
        "version": CHECKLIST_VERSION,
        "prior_checklist_version": CHECKLIST_VERSION_V1,
        "daily_path_dd_proof": STANDARD_EVAL_DAILY_PATH_DD_PROOF,
        "mode": mode_s,
        "dry_run": bool(dry_run),
        "job_id_prefix": job_id_prefix,
        "steps_completed": list(steps),
        "designed_periods": designed,
        "availability": availability,
        "multi_year": multi_year_result,
        "class_hyp": class_hyp_bundle,
        "robustness_gate": gate,
        "cost_assumption": cost_assumption,
        "leverage_short_costs": lev_short,
        "repo_rate_series": repo_series_norm,
        "prefer_repo_linked": bool(prefer_repo_linked),
        "require_repo_linked": bool(require_repo_linked),
        "prefer_liquidity_linked": bool(prefer_liquidity_linked),
        "require_liquidity_linked": bool(require_liquidity_linked),
        "liquidity": lev_short.get("liquidity"),
        "risk_scenarios": risk_scen,
        "daily_path_dd": daily_path,
        "checklist_completeness": completeness,
        "data_gap_notes": gap_notes,
        "holding": holding,
        "baseline_demo": baseline_demo,
        "new_signals_registered": bool(
            class_hyp_bundle is not None
            or bool(baseline_demo.get("new_signals_registered"))
        ),
        "research_candidate": research_candidate,
        "research_candidate_allowed": research_candidate_allowed,
        "checklist_complete": bool(completeness.get("complete")),
        "checklist_skipped": False,
        "gate_passed": gate_passed,
        "gate_pass_implies_ready": False,
        "gate_pass_implies_mass": False,
        "gate_pass_implies_research_candidate": False,
        "short_window_only_sufficient": False,
        "high_frequency_hyp": bool(high_frequency_hyp),
        **_closed_flags(),
    }


standard_research_eval_checklist_run = run_standard_research_eval

__all__ = [
    "run_standard_research_eval",
    "standard_research_eval_checklist_run",
]
