"""Yearly windows, standard-research-eval checklist, and re-exports.

``design_yearly_eval_windows`` + checklist v2 + ``run_standard_research_eval``.
S1: :mod:`research.eval_harness_s1`. Extra-hyp: :mod:`research.eval_harness_extra_hyp`.
Public names stay re-exported here and from :mod:`research.eval_harness`.
W56 next-day — not candidate daily-path SoT. Mass/READY/GO closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
)
from research.eval_harness import (
    EvalHarnessError,
    _closed_flags,
    _selected_codes,
    assert_harness_closed,
)
from research.eval_loaders import load_repo_rows_from_sqlite
from research.eval_universe import DEFAULT_SQLITE
from research.freezes import MASS_RESEARCH, PHASE7, READY_DECLARED
from research.robustness_gate import (
    DEFAULT_ONE_WAY_COST,
    evaluate_research_robustness_gate,
)
from research.single_shot_job import (
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    MultidaySignalEval,
    NEXTDAY_RESEARCH_LABEL,
    R2PutFn,
)

# Multi-year eval (year-split · not READY / not Mass).
MULTI_YEAR_VERSION: str = "research-multi-year-eval/v1"
MULTI_YEAR_LABEL: str = (
    "小サンプル / 研究用・複数年評価・未宣言 "
    "(年分割・fail-one-year-ok・pass≠READY/Mass)"
)

# Fixed 30-code TSE probe. Not EVAL_UNIVERSE_POOL / not a head-N fill.
DEFAULT_MULTIYEAR_CODES: tuple[str, ...] = (
    "13010", "72030", "67580", "99840", "83060",
    "68610", "65010", "40630", "80350", "94320",
    "45020", "63670", "60980", "79740", "69810",
    "45680", "80010", "80020", "80580", "94330",
    "29140", "33820", "46610", "49010", "51080",
    "54010", "57130", "62730", "63010", "65030",
)

DEFAULT_MULTIYEAR_YEARS: tuple[int, ...] = (2015, 2017, 2019, 2021, 2023, 2025)

# Margin JSONL gap years (empty_allowed; never invent). Inventory starts ~2013.
_MARGIN_GAP_YEARS: frozenset[int] = frozenset({2024})


def design_yearly_eval_windows(
    years: Sequence[int] | None = None,
    *,
    window: str = "q4",
    max_days: int = 80,
    min_days: int = 40,
    codes: Sequence[str] | None = None,
    inventory_notes: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Yearly (or half-year) windows. Gaps recorded; no invent.

    ``window``: ``q4`` (default), ``h1``, ``h2``, ``full``.
    """
    assert_harness_closed()
    yrs = (
        [int(y) for y in years]
        if years is not None
        else list(DEFAULT_MULTIYEAR_YEARS)
    )
    if not yrs:
        raise EvalHarnessError("design_yearly_eval_windows requires >=1 year")
    w = str(window).strip().lower()
    spans = {
        "q4": ("09-01", "12-29"),
        "h1": ("01-06", "06-30"),
        "h2": ("07-01", "12-29"),
        "full": ("01-06", "12-29"),
    }
    if w not in spans:
        raise EvalHarnessError(
            f"window must be one of {sorted(spans)}, got {window!r}"
        )
    start_md, end_md = spans[w]
    selected = _selected_codes(codes, DEFAULT_MULTIYEAR_CODES)
    margin_gaps = set(
        (inventory_notes or {}).get("markets_margin_interest", {}).get("gap_years")
        or _MARGIN_GAP_YEARS
    )
    out: list[dict[str, Any]] = []
    for y in yrs:
        period_start = f"{int(y)}-{start_md}"
        period_end = f"{int(y)}-{end_md}"
        margin_gap = int(y) in margin_gaps or int(y) < 2013
        s4_ok = not margin_gap
        coverage = {
            "margin_interest": {
                "jsonl_gap": margin_gap,
                "s4_eligible": s4_ok,
                "handling": (
                    "empty_allowed / skip S4" if margin_gap else "jsonl when mirrored"
                ),
            },
        }
        item: dict[str, Any] = {
            "period_id": f"y{int(y)}_{w}",
            "year": int(y),
            "window": w,
            "period_start": period_start,
            "period_end": period_end,
            "max_days": int(max_days),
            "min_days": int(min_days),
            "codes": list(selected),
            "history_source": "r2",
            "coverage_notes": coverage,
            "s4_eligible": s4_ok,
            "r2_allow_empty_datasets": (
                ["markets_margin_interest"] if not s4_ok else []
            ),
        }
        if int(y) < 2008 or int(y) > 2026:
            item["skip_reason"] = (
                f"year {y} outside equities_bars_daily inventory 2008-2026"
            )
            item["status_hint"] = "skipped"
        out.append(item)
    return out


def _year_period_error_row(
    period: Mapping[str, Any], *, error: str
) -> dict[str, Any]:
    return {
        "period_id": period.get("period_id"),
        "year": period.get("year"),
        "status": "error",
        "period_start": period.get("period_start"),
        "period_end": period.get("period_end"),
        "error": error,
        "compare_table": None,
        "coverage_notes": period.get("coverage_notes"),
        "s4_eligible": period.get("s4_eligible"),
    }


def _resolve_year_periods(
    periods: Sequence[Mapping[str, Any]] | None,
    years: Sequence[int] | None,
    *,
    max_days: int,
    min_days: int,
    codes: Sequence[str] | None,
    empty_msg: str,
) -> list[dict[str, Any]]:
    if periods is None:
        period_list = design_yearly_eval_windows(
            years, max_days=max_days, min_days=min_days, codes=codes
        )
    else:
        period_list = [dict(p) for p in periods]
    if not period_list:
        raise EvalHarnessError(empty_msg)
    return period_list


def _period_history(
    p: Mapping[str, Any],
    *,
    history_source: str,
    feature_row_limit: int,
    write_per_day_artifacts: bool,
    dry_run: bool,
    d1_execute: D1ExecuteFn | None,
    r2_put: R2PutFn | None,
    staging_dir: str | Path | None,
    wrangler: str | Path | None,
    wrangler_config: str | Path | None,
    r2_get: Callable[[str, str], bytes] | None,
    r2_bucket: str,
) -> dict[str, Any]:
    return {
        "as_of_days": p.get("as_of_days"),
        "feature_row_limit": feature_row_limit,
        "write_per_day_artifacts": write_per_day_artifacts,
        "dry_run": dry_run,
        "d1_execute": d1_execute,
        "r2_put": r2_put,
        "staging_dir": staging_dir,
        "wrangler": wrangler,
        "wrangler_config": wrangler_config,
        "history_source": str(p.get("history_source") or history_source),
        "r2_object_keys_by_dataset": p.get("r2_object_keys_by_dataset"),
        "r2_local_paths_by_dataset": p.get("r2_local_paths_by_dataset"),
        "r2_raw_lines_by_dataset": p.get("r2_raw_lines_by_dataset"),
        "r2_get": r2_get,
        "r2_bucket": r2_bucket,
    }


def _ok_year_row(
    p: Mapping[str, Any],
    *,
    pid: str,
    start: str,
    end: str,
    ex: MultidaySignalEval,
    history_source: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    bs = ex.batch_summary or {}
    return {
        "period_id": pid,
        "year": p.get("year"),
        "status": "ok",
        "period_start": start,
        "period_end": end,
        "n_days": ex.n_days,
        "n_codes": len(ex.codes),
        "codes": list(ex.codes),
        "as_of_days": list(ex.as_of_days),
        "history_source": bs.get("history_source") or history_source,
        "batch_summary_r2_key": ex.batch_summary_r2_key,
        "coverage_notes": p.get("coverage_notes"),
        "s4_eligible": p.get("s4_eligible"),
        "label": NEXTDAY_RESEARCH_LABEL,
        **extra,
    }


def _pack_multi_year(
    *,
    job_id_prefix: str,
    period_list: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    one_way_cost: float,
    require_net_sign_majority: bool,
    history_source: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "version": MULTI_YEAR_VERSION,
        "job_id_prefix": job_id_prefix,
        "label": MULTI_YEAR_LABEL,
        "history_source_default": history_source,
        "n_years_requested": len(period_list),
        "n_years_ok": sum(1 for r in results if r.get("status") == "ok"),
        "n_years_skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "n_years_error": sum(1 for r in results if r.get("status") == "error"),
        "years": list(results),
        "cost_assumption": {
            "one_way_cost": float(one_way_cost),
            "one_way_cost_bp": float(one_way_cost) * 10_000.0,
            "require_net_sign_majority": bool(require_net_sign_majority),
            "label": "仮定に依存・研究用・運用GOではない",
        },
        **extra,
        **_closed_flags(year_split=True, fail_one_year_safe=True),
    }


def multi_year_availability_table(
    periods: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compact availability table from designed yearly periods + run results."""
    rows: list[dict[str, Any]] = []
    for p in periods:
        cov = p.get("coverage_notes") if isinstance(p.get("coverage_notes"), Mapping) else {}
        margin = cov.get("margin_interest") if isinstance(cov, Mapping) else {}
        rows.append(
            {
                "period_id": p.get("period_id"),
                "year": p.get("year"),
                "period_start": p.get("period_start"),
                "period_end": p.get("period_end"),
                "status": p.get("status") or p.get("status_hint") or "designed",
                "skip_reason": p.get("skip_reason"),
                "s4_eligible": (
                    p.get("s4_eligible")
                    if p.get("s4_eligible") is not None
                    else (margin or {}).get("s4_eligible")
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Standard research eval checklist entry (W66 v1 · W77 / w0816k v2)
# ---------------------------------------------------------------------------

CHECKLIST_VERSION: str = "standard-research-eval-checklist/v2"
CHECKLIST_VERSION_V1: str = "standard-research-eval-checklist/v1"
STANDARD_EVAL_DAILY_PATH_DD_PROOF: str = (
    "docs/proof/w0819c_w100_daily_path_dd_gate_20260819.md"
)
COST_MODEL_PREFER_REPO_LINKED: bool = True
COST_MODEL_REQUIRE_REPO_LINKED: bool = False
COST_MODEL_PREFER_LIQUIDITY_LINKED: bool = True
COST_MODEL_REQUIRE_LIQUIDITY_LINKED: bool = False
STANDARD_EVAL_MODES: tuple[str, ...] = (
    "wiring_only",
    "s1_rejected_baseline",
    "s4_rejected_baseline",
    "class_hyp_offline",
)

# Checklist v2 required item ids (order is documentation-stable).
CHECKLIST_V2_REQUIRED: tuple[str, ...] = (
    "multi_year_or_non_overlapping_long_periods",
    "cost_assumption_default_10bp_one_way",
    "leverage_short_cost_assumptions",
    "robustness_gate_v2_with_cost",
    "explicit_data_gap_disclosure",
    "risk_scenario_evaluation",
    "daily_path_dd",
    "pass_does_not_connect_ready_mass_go",
)
CHECKLIST_V2_NEAR_REQUIRED: tuple[str, ...] = (
    "holding_turnover_metrics",  # near-required for high-frequency hyps
)
CHECKLIST_V2_INSUFFICIENT: tuple[str, ...] = (
    "short_window_only",
    "gross_only_without_cost_gate",
    "skipped_checklist",
    "incomplete_leverage_short_costs",
    "incomplete_risk_scenarios",
    "scenario_sign_break_undisclosed",
    "period_net_dd_only_pass",
    "period_net_dd_zero_daily_unmeasured",
)


def standard_research_eval_checklist_document() -> dict[str, Any]:
    """Public document for the standard research evaluation checklist (v2)."""
    from research.cost_models import COST_MODELS_VERSION, COST_MODELS_WAVE

    return {
        "version": CHECKLIST_VERSION,
        "prior_version": CHECKLIST_VERSION_V1,
        "daily_path_dd_proof": STANDARD_EVAL_DAILY_PATH_DD_PROOF,
        "required": list(CHECKLIST_V2_REQUIRED),
        "near_required": list(CHECKLIST_V2_NEAR_REQUIRED),
        "recommended": [
            "holding_turnover_metrics",
            "repo_linked_cost_model",
            "liquidity_linked_cost_model",
        ],
        "insufficient": list(CHECKLIST_V2_INSUFFICIENT),
        "cost_models_surface": {
            "version": COST_MODELS_VERSION,
            "wave": COST_MODELS_WAVE,
        },
        "cost_model_defaults": {
            "prefer_repo_linked": COST_MODEL_PREFER_REPO_LINKED,
            "require_repo_linked": COST_MODEL_REQUIRE_REPO_LINKED,
            "prefer_liquidity_linked": COST_MODEL_PREFER_LIQUIDITY_LINKED,
            "require_liquidity_linked": COST_MODEL_REQUIRE_LIQUIDITY_LINKED,
        },
        "daily_path_dd_surface": {"period_net_dd_only_pass_forbidden": True},
        "default_entry": "run_standard_research_eval",
        "research_candidate": False,
        "incomplete_checklist_blocks_research_candidate": True,
        **_closed_flags(),
    }


def evaluate_checklist_v2_completeness(
    *,
    multi_year_present: bool,
    cost_assumption_present: bool,
    leverage_short_complete: bool,
    robustness_gate_present: bool,
    data_gap_disclosed: bool,
    risk_scenarios_passed: bool,
    risk_scenarios_candidate_allowed: bool,
    freeze_closed: bool,
    holding_present: bool = False,
    high_frequency_hyp: bool = False,
    require_holding_for_hf: bool = True,
    checklist_skipped: bool = False,
    daily_path_dd_complete: bool = False,
    period_net_dd_only: bool = False,
    period_net_dd_zero_daily_unmeasured: bool = False,
) -> dict[str, Any]:
    """Incomplete → not candidate. Complete still does not auto-promote."""
    hf_req = bool(high_frequency_hyp and require_holding_for_hf)
    flags: list[tuple[str, bool, bool]] = [
        ("multi_year_or_non_overlapping_long_periods", bool(multi_year_present), bool(multi_year_present)),
        ("cost_assumption_default_10bp_one_way", bool(cost_assumption_present), bool(cost_assumption_present)),
        ("leverage_short_cost_assumptions", bool(leverage_short_complete), bool(leverage_short_complete)),
        ("robustness_gate_v2_with_cost", bool(robustness_gate_present), bool(robustness_gate_present)),
        ("explicit_data_gap_disclosure", bool(data_gap_disclosed), bool(data_gap_disclosed)),
        (
            "risk_scenario_evaluation",
            bool(risk_scenarios_passed),
            bool(risk_scenarios_passed) and bool(risk_scenarios_candidate_allowed),
        ),
        (
            "daily_path_dd",
            bool(daily_path_dd_complete),
            bool(daily_path_dd_complete) and not bool(period_net_dd_only),
        ),
        ("pass_does_not_connect_ready_mass_go", bool(freeze_closed), bool(freeze_closed)),
    ]
    items: dict[str, Any] = {
        k: {"required": True, "present": present, "passed": passed}
        for k, present, passed in flags
    }
    items["risk_scenario_evaluation"].update(
        scenario_passed=bool(risk_scenarios_passed),
        scenario_candidate_allowed=bool(risk_scenarios_candidate_allowed),
    )
    items["daily_path_dd"].update(
        period_net_dd_only_pass_forbidden=True,
        period_net_dd_only=bool(period_net_dd_only),
        period_net_dd_zero_daily_unmeasured=bool(period_net_dd_zero_daily_unmeasured),
    )
    items["holding_turnover_metrics"] = {
        "required": hf_req,
        "near_required": True,
        "present": bool(holding_present),
        "passed": bool(holding_present) if hf_req else True,
        "high_frequency_hyp": bool(high_frequency_hyp),
    }
    missing = [k for k, v in items.items() if v.get("required") and not v.get("passed")]
    if checklist_skipped:
        missing = list(dict.fromkeys([*missing, "checklist_skipped"]))
    complete = not missing and not checklist_skipped
    return {
        "version": CHECKLIST_VERSION,
        "complete": bool(complete),
        "research_candidate_allowed": bool(complete),
        "missing_required": missing,
        "items": items,
        "period_net_dd_only": bool(period_net_dd_only),
        "period_net_dd_zero_daily_unmeasured": bool(
            period_net_dd_zero_daily_unmeasured
        ),
        **_closed_flags(),
    }


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
        is_research_baseline_rejected,
        rejected_baseline_catalog,
    )
    from research.cost_models import (
        build_leverage_short_cost_assumption,
        default_long_only_unlevered_cost_assumption,
        load_repo_rate_series,
        load_repo_rate_series_from_rows,
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

    # Cost assumption (default 10bp one-way; change needs reason).
    default_cost = float(DEFAULT_ONE_WAY_COST)
    cost = float(one_way_cost)
    cost_bp = cost * 10_000.0
    if abs(cost - default_cost) > 1e-15 and not (
        cost_change_reason and str(cost_change_reason).strip()
    ):
        raise EvalHarnessError(
            "changing one_way_cost from default 10bp requires cost_change_reason"
        )
    cost_assumption: dict[str, Any] = {
        "one_way_cost": cost,
        "one_way_cost_bp": cost_bp,
        "round_trip_cost": cost * 2.0,
        "round_trip_cost_bp": cost_bp * 2.0,
        "require_net_sign_majority": bool(require_net_sign_majority),
        "default_one_way_cost": default_cost,
        "default_one_way_cost_bp": default_cost * 10_000.0,
        "changed_from_default": abs(cost - default_cost) > 1e-15,
        "change_reason": (
            str(cost_change_reason).strip() if cost_change_reason else None
        ),
        "label": "仮定に依存・研究用・運用GOではない",
    }
    steps.append("cost_assumption")

    # Normalize optional repo series (mapping / rows / prebuilt). Gaps disclosed.
    repo_series_norm: dict[str, Any] | None = None
    if repo_rate_series is not None:
        repo_series_norm = load_repo_rate_series(
            repo_rate_series,
            required_dates=repo_required_dates,
        )

    # Leverage / short related costs (checklist v2 required).
    # W78: prefer date-matched jsda_tokyo_repo_rates when series supplied.
    if leverage_short_cost_assumption is not None:
        lev_short = {**dict(leverage_short_cost_assumption), **_closed_flags()}
        if "assumptions_complete" not in lev_short:
            lev_short["assumptions_complete"] = bool(
                lev_short.get("assumptions_disclosed", False)
            )
        # Attach normalized series for disclosure when caller omitted it.
        if repo_series_norm is not None and not lev_short.get("repo_rate"):
            from research.cost_models import mean_repo_rate_pct

            m = mean_repo_rate_pct(
                repo_series_norm,
                dates=repo_required_dates,
            )
            lev_short["repo_rate"] = {
                "preferred": bool(prefer_repo_linked),
                "series_supplied": True,
                "series_usable": int(m.get("n_obs") or 0) > 0,
                "series": repo_series_norm,
                "mean_rate_pct": m.get("mean_rate_pct"),
                "mean_annual_bp": m.get("mean_annual_bp"),
                "n_obs": int(m.get("n_obs") or 0),
                "gap_dates": list(repo_series_norm.get("gap_dates") or []),
                "n_gaps": int(repo_series_norm.get("n_gaps") or 0),
                "ffill_applied": False,
                "invent_fill": False,
            }
    else:
        style = str(position_style or "long_only_unlevered").strip().lower()
        if (
            style == "long_only_unlevered"
            and float(gross_leverage) <= 1.0 + 1e-12
            and not uses_short
            and not uses_leverage
        ):
            lev_short = default_long_only_unlevered_cost_assumption(
                one_way_cost=cost,
                cost_change_reason=cost_change_reason,
                repo_rate_series=repo_series_norm,
                liquidity_proxy=liquidity_proxy,
                liquidity_bars=liquidity_bars,
                liquidity_bucket=liquidity_bucket,
                liquidity_adv_jpy=liquidity_adv_jpy,
                is_topix=is_topix,
                scale_category=scale_category,
                prefer_liquidity_linked=bool(prefer_liquidity_linked),
            )
        else:
            lev_short = build_leverage_short_cost_assumption(
                position_style=style,
                gross_leverage=float(gross_leverage),
                short_fraction=float(short_fraction),
                one_way_cost=cost,
                short_borrow_annual_bp=short_borrow_annual_bp,
                financing_annual_bp=financing_annual_bp,
                cost_change_reason=cost_change_reason,
                short_borrow_change_reason=short_borrow_change_reason,
                financing_change_reason=financing_change_reason,
                uses_short=uses_short,
                uses_leverage=uses_leverage,
                repo_rate_series=repo_series_norm,
                prefer_repo_linked=bool(prefer_repo_linked),
                short_borrow_spread_bp=short_borrow_spread_bp,
                short_borrow_sensitivity=short_borrow_sensitivity,
                borrow_proxy_annual_bp=borrow_proxy_annual_bp,
                required_dates=repo_required_dates,
                liquidity_proxy=liquidity_proxy,
                liquidity_bars=liquidity_bars,
                liquidity_bucket=liquidity_bucket,
                liquidity_adv_jpy=liquidity_adv_jpy,
                is_topix=is_topix,
                scale_category=scale_category,
                prefer_liquidity_linked=bool(prefer_liquidity_linked),
                require_liquidity_linked=bool(require_liquidity_linked),
                liquidity_required_dates=liquidity_required_dates,
            )
    steps.append("leverage_short_cost_assumptions")

    # Optional hard prefer: require_repo_linked blocks completeness only when
    # leverage or short is in use and series is missing/unusable.
    repo_req = bool(require_repo_linked)
    uses_ls = bool(lev_short.get("uses_short") or lev_short.get("uses_leverage"))
    repo_ok = bool(lev_short.get("repo_linked")) or not uses_ls
    if repo_req and uses_ls and not repo_ok:
        lev_short = dict(lev_short)
        lev_short["assumptions_complete"] = False
        missing = list(lev_short.get("missing_disclosure") or [])
        if "repo_rate_series" not in missing:
            missing.append("repo_rate_series")
        lev_short["missing_disclosure"] = missing
        lev_short["require_repo_linked"] = True
        lev_short["repo_linked_requirement_failed"] = True

    # Optional hard prefer: require_liquidity_linked blocks when gap.
    liq_req = bool(require_liquidity_linked)
    liq_block = lev_short.get("liquidity") or {}
    # For require we need non-gap liquidity (modulation applied or bucket known).
    liq_gap = bool(liq_block.get("is_gap", True)) if liq_block else True
    if liq_req and liq_gap:
        lev_short = dict(lev_short)
        lev_short["assumptions_complete"] = False
        missing = list(lev_short.get("missing_disclosure") or [])
        if "liquidity_proxy" not in missing:
            missing.append("liquidity_proxy")
        lev_short["missing_disclosure"] = missing
        lev_short["require_liquidity_linked"] = True
        lev_short["liquidity_linked_requirement_failed"] = True

    # Mirror base tx fields into cost_assumption for v1-compat readers.
    cost_assumption["leverage_short"] = {
        "position_style": lev_short.get("position_style"),
        "assumptions_complete": lev_short.get("assumptions_complete"),
        "uses_short": lev_short.get("uses_short"),
        "uses_leverage": lev_short.get("uses_leverage"),
        "short_borrow_daily": (lev_short.get("short_borrow") or {}).get("daily_cost"),
        "financing_daily": (lev_short.get("leverage_financing") or {}).get(
            "daily_cost"
        ),
        "repo_linked": lev_short.get("repo_linked"),
        "prefer_repo_linked": bool(prefer_repo_linked),
        "require_repo_linked": repo_req,
        "liquidity_linked": lev_short.get("liquidity_linked"),
        "prefer_liquidity_linked": bool(prefer_liquidity_linked),
        "require_liquidity_linked": liq_req,
        "liquidity_bucket": (lev_short.get("liquidity") or {}).get("bucket"),
        "short_rate_source": (lev_short.get("short_borrow") or {}).get(
            "rate_source"
        ),
        "financing_rate_source": (lev_short.get("leverage_financing") or {}).get(
            "rate_source"
        ),
    }
    cost_assumption["repo_rate"] = lev_short.get("repo_rate")
    cost_assumption["liquidity"] = lev_short.get("liquidity")

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

    # Baseline catalog awareness (rejected demos only).
    catalog = rejected_baseline_catalog()
    baseline_demo: dict[str, Any] = {
        "mode": mode_s,
        "catalog_version": catalog.get("version"),
        "rejected_signal_ids": list(catalog.get("signal_ids") or []),
        "research_status_value": RESEARCH_STATUS_REJECTED,
        "new_signals_registered": False,
    }
    steps.append("baseline_catalog_check")

    multi_year_result: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    class_hyp_bundle: dict[str, Any] | None = None
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

    if mode_s == "class_hyp_offline":
        # W78–W79: class hyps offline multi-year (event/flow/fund + holds).
        # Does not touch S1–S5 catalog. Never auto-promotes candidate.
        from research.offline.multiyear import run_class_hyp_multi_year_eval

        class_hyp_bundle = run_class_hyp_multi_year_eval(
            designed if periods is not None else None,
            codes=codes,
            one_way_cost=cost,
            max_days=max_days,
            min_periods_gate=min_periods_gate,
            min_active_per_period=min_active_per_period,
            apply_robustness_gate=apply_robustness_gate,
        )
        multi_year_result = class_hyp_bundle
        md_block = class_hyp_bundle.get("multi_day_hold") or {}
        gate = md_block.get("robustness_gate")
        baseline_demo["signal_id"] = md_block.get("signal_id")
        baseline_demo["hypothesis_class"] = "multi_day_hold"
        baseline_demo["class_signals"] = True
        baseline_demo["new_signals_registered"] = True
        baseline_demo["candidate_summary"] = class_hyp_bundle.get(
            "candidate_summary"
        )
        if include_holding and md_block.get("holding") is not None:
            holding_records = None
        steps.append("class_hyp_offline_multi_year")
        if apply_robustness_gate:
            steps.append("robustness_gate_v2")
        if scenario_rows is None:
            risk_from_md = md_block.get("risk_scenarios")
            risk_from_macro = (class_hyp_bundle.get("macro_conditioned") or {}).get(
                "risk_scenarios"
            )
            if isinstance(risk_from_md, Mapping) and risk_from_md.get("scenario_rows"):
                scenario_rows = list(risk_from_md.get("scenario_rows") or [])
            elif isinstance(risk_from_macro, Mapping) and risk_from_macro.get(
                "scenario_rows"
            ):
                scenario_rows = list(risk_from_macro.get("scenario_rows") or [])
        if not rate_data_usable:
            rate_data_usable = True
        if repo_series_norm is None and class_hyp_bundle.get("repo_load"):
            try:
                _rows = load_repo_rows_from_sqlite(DEFAULT_SQLITE)
                if _rows:
                    repo_series_norm = load_repo_rate_series_from_rows(_rows)
            except Exception:  # noqa: BLE001 — non-fatal disclosure path
                pass
    elif mode_s == "wiring_only" or (
        dry_run and not executable and period_rows_for_gate is None
    ):
        # Validate wiring without heavy R2.
        steps.append("wiring_only_no_heavy_r2")
        gate_signal_id = DEFAULT_SIGNAL_ID
        if mode_s == "s1_rejected_baseline":
            gate_signal_id = DEFAULT_SIGNAL_ID
            baseline_demo["signal_id"] = DEFAULT_SIGNAL_ID
            baseline_demo["hyp_id"] = "S1"
            baseline_demo["still_rejected"] = is_research_baseline_rejected(
                DEFAULT_SIGNAL_ID
            )
        elif mode_s == "s4_rejected_baseline":
            gate_signal_id = "c21_margin_change_sign"
            baseline_demo["signal_id"] = gate_signal_id
            baseline_demo["hyp_id"] = "S4"
            baseline_demo["still_rejected"] = is_research_baseline_rejected(
                gate_signal_id
            )
        if period_rows_for_gate is not None and apply_robustness_gate:
            gate = evaluate_research_robustness_gate(
                period_rows_for_gate,
                signal_id=gate_signal_id,
                min_periods=min_periods_gate,
                min_active_per_period=min_active_per_period,
                one_way_cost=cost,
                require_net_sign_majority=require_net_sign_majority,
            )
            steps.append("robustness_gate_v2")
        elif apply_robustness_gate:
            gate = {
                **_closed_flags(),
                "passed": False,
                "reasons": ["wiring_only_no_period_metrics"],
                "signal_id": gate_signal_id,
            }
            steps.append("robustness_gate_v2_surface")
        multi_year_result = {
            "status": "wiring_only",
            "n_years_designed": len(designed),
        }
    elif mode_s == "s1_rejected_baseline":
        if not is_research_baseline_rejected(DEFAULT_SIGNAL_ID):
            raise EvalHarnessError(
                "s1_rejected_baseline requires catalog rejection of "
                f"{DEFAULT_SIGNAL_ID}"
            )
        from research.eval_harness_s1 import run_multi_year_s1_eval

        multi_year_result = run_multi_year_s1_eval(
            designed,
            years=None,
            job_id_prefix=job_id_prefix,
            codes=codes,
            max_days=max_days,
            min_days=min_days,
            feature_row_limit=feature_row_limit,
            volume_change_abs_min=volume_change_abs_min,
            write_per_day_artifacts=write_per_day_artifacts,
            dry_run=dry_run,
            d1_execute=d1_execute,
            r2_put=r2_put,
            staging_dir=staging_dir,
            wrangler=wrangler,
            wrangler_config=wrangler_config,
            history_source=history_source,
            r2_get=r2_get,
            r2_bucket=r2_bucket,
            apply_robustness_gate=apply_robustness_gate,
            min_periods_gate=min_periods_gate,
            min_active_per_period=min_active_per_period,
            one_way_cost=cost,
            require_net_sign_majority=require_net_sign_majority,
        )
        gate = multi_year_result.get("robustness_gate")
        steps.append("multi_year_s1_rejected_baseline")
        steps.append("robustness_gate_v2")
        baseline_demo["signal_id"] = DEFAULT_SIGNAL_ID
        baseline_demo["hyp_id"] = "S1"
        baseline_demo["still_rejected"] = is_research_baseline_rejected(
            DEFAULT_SIGNAL_ID
        )
    elif mode_s == "s4_rejected_baseline":
        s4_id = "c21_margin_change_sign"
        if not is_research_baseline_rejected(s4_id):
            raise EvalHarnessError(
                f"s4_rejected_baseline requires catalog rejection of {s4_id}"
            )
        from research.eval_harness_extra_hyp import run_multi_year_extra_hyp_eval

        want = list(signal_ids) if signal_ids is not None else [s4_id]
        multi_year_result = run_multi_year_extra_hyp_eval(
            designed,
            years=None,
            job_id_prefix=job_id_prefix,
            codes=codes,
            max_days=max_days,
            min_days=min_days,
            feature_row_limit=feature_row_limit,
            one_way_cost=cost,
            write_per_day_artifacts=write_per_day_artifacts,
            dry_run=dry_run,
            d1_execute=d1_execute,
            r2_put=r2_put,
            staging_dir=staging_dir,
            wrangler=wrangler,
            wrangler_config=wrangler_config,
            history_source=history_source,
            r2_get=r2_get,
            r2_bucket=r2_bucket,
            apply_robustness_gate=apply_robustness_gate,
            min_periods_gate=min_periods_gate,
            min_active_per_period=min_active_per_period,
            signal_ids=want,
            require_net_sign_majority=require_net_sign_majority,
        )
        gates = multi_year_result.get("robustness_gates") or {}
        # Prefer primary S4 gate when present.
        if s4_id in gates:
            gate = gates[s4_id]
        elif gates:
            gate = next(iter(gates.values()))
        else:
            gate = None
        steps.append("multi_year_s4_rejected_baseline")
        steps.append("robustness_gate_v2")
        baseline_demo["signal_id"] = s4_id
        baseline_demo["hyp_id"] = "S4"
        baseline_demo["still_rejected"] = is_research_baseline_rejected(s4_id)
        baseline_demo["signal_ids"] = want

    # Optional period_rows_for_gate override after multi-year (or alone).
    if period_rows_for_gate is not None and mode_s != "wiring_only":
        if apply_robustness_gate:
            sid = (
                (baseline_demo.get("signal_id") or DEFAULT_SIGNAL_ID)
                if baseline_demo.get("signal_id")
                else DEFAULT_SIGNAL_ID
            )
            gate = evaluate_research_robustness_gate(
                period_rows_for_gate,
                signal_id=str(sid),
                min_periods=min_periods_gate,
                min_active_per_period=min_active_per_period,
                one_way_cost=cost,
                require_net_sign_majority=require_net_sign_majority,
            )
            if "robustness_gate_v2" not in steps:
                steps.append("robustness_gate_v2")

    # Holding / turnover (near-required for high-frequency hyps in v2).
    holding: dict[str, Any] | None = None
    holding_metrics_done = False
    if include_holding:
        precomputed_holding = None
        if class_hyp_bundle is not None:
            precomputed_holding = (class_hyp_bundle.get("multi_day_hold") or {}).get(
                "holding"
            )
        if holding_records is not None:
            holding = holding_metrics_report(
                holding_records,
                one_way_cost=cost,
            )
            steps.append("holding_turnover_metrics")
            holding_metrics_done = True
        elif isinstance(precomputed_holding, Mapping):
            holding = dict(precomputed_holding)
            steps.append("holding_turnover_metrics")
            holding_metrics_done = True
        else:
            holding = {"status": "annotation_only", **_closed_flags()}
            steps.append("holding_turnover_annotation")
            holding_metrics_done = False

    # Risk scenario evaluation (checklist v2 required).
    gate_signal_id_for_scen = str(
        baseline_demo.get("signal_id") or DEFAULT_SIGNAL_ID
    )
    # Pull baseline signs from gate when not supplied.
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
        # Wiring default: core pending + rate/liquidity N/A disclosure.
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

    # W100: daily_path_DD is mandatory. period_net_DD alone cannot pass.
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
    steps.append("daily_path_dd")

    # Pass does NOT connect READY / Mass / GO (always restate).
    steps.append("freeze_ready_mass_phase7_closed")

    gate_passed = bool(gate.get("passed")) if isinstance(gate, Mapping) else False

    # Completeness: incomplete checklist cannot become research_candidate.
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

    # Hard rule: harness never auto-promotes; incomplete forces False.
    research_candidate = False
    research_candidate_allowed = bool(
        completeness.get("research_candidate_allowed")
    )
    if not completeness.get("complete"):
        research_candidate = False
        research_candidate_allowed = False

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


# Alias for discoverability.
standard_research_eval_checklist_run = run_standard_research_eval

# S1 / extra-hyp live in sibling modules; lazy so checklist-first loads bind.
_S1_EXTRA_EXPORTS: frozenset[str] = frozenset(
    {
        "run_multi_year_extra_hyp_eval",
        "run_multi_year_s1_eval",
    }
)


def __getattr__(name: str):
    if name == "run_multi_year_s1_eval":
        from research.eval_harness_s1 import run_multi_year_s1_eval as _fn

        return _fn
    if name == "run_multi_year_extra_hyp_eval":
        from research.eval_harness_extra_hyp import run_multi_year_extra_hyp_eval as _fn

        return _fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _S1_EXTRA_EXPORTS | set(__all__))


__all__ = [
    "CHECKLIST_VERSION",
    "CHECKLIST_VERSION_V1",
    "CHECKLIST_V2_INSUFFICIENT",
    "CHECKLIST_V2_NEAR_REQUIRED",
    "CHECKLIST_V2_REQUIRED",
    "COST_MODEL_PREFER_LIQUIDITY_LINKED",
    "COST_MODEL_PREFER_REPO_LINKED",
    "COST_MODEL_REQUIRE_LIQUIDITY_LINKED",
    "COST_MODEL_REQUIRE_REPO_LINKED",
    "DEFAULT_MULTIYEAR_CODES",
    "DEFAULT_MULTIYEAR_YEARS",
    "MULTI_YEAR_LABEL",
    "MULTI_YEAR_VERSION",
    "STANDARD_EVAL_DAILY_PATH_DD_PROOF",
    "STANDARD_EVAL_MODES",
    "design_yearly_eval_windows",
    "evaluate_checklist_v2_completeness",
    "multi_year_availability_table",
    "run_multi_year_extra_hyp_eval",
    "run_multi_year_s1_eval",
    "run_standard_research_eval",
    "standard_research_eval_checklist_document",
    "standard_research_eval_checklist_run",
]
