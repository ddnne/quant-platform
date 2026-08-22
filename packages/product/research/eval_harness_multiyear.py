"""Yearly eval windows (W56 next-day; not candidate SoT).

``design_yearly_eval_windows``. Checklist: :mod:`research.eval_harness_checklist`.
Standard run: :mod:`research.eval_harness_standard`.
S1: :mod:`research.eval_harness_s1`. Extra-hyp: :mod:`research.eval_harness_extra_hyp`.
Public names stay re-exported here and from :mod:`research.eval_harness`.
Mass/READY/GO closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research.eval_harness import (
    EvalHarnessError,
    _closed_flags,
    _selected_codes,
    assert_harness_closed,
)
from research.eval_harness_checklist import (
    CHECKLIST_VERSION,
    CHECKLIST_VERSION_V1,
    CHECKLIST_V2_INSUFFICIENT,
    CHECKLIST_V2_NEAR_REQUIRED,
    CHECKLIST_V2_REQUIRED,
    COST_MODEL_PREFER_LIQUIDITY_LINKED,
    COST_MODEL_PREFER_REPO_LINKED,
    COST_MODEL_REQUIRE_LIQUIDITY_LINKED,
    COST_MODEL_REQUIRE_REPO_LINKED,
    STANDARD_EVAL_DAILY_PATH_DD_PROOF,
    STANDARD_EVAL_MODES,
    evaluate_checklist_v2_completeness,
    standard_research_eval_checklist_document,
)
from research.single_shot_job import (
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


# S1 / extra-hyp / standard live in sibling modules; lazy so windows-first loads bind.
_LAZY_EXPORTS: frozenset[str] = frozenset(
    {
        "run_multi_year_extra_hyp_eval",
        "run_multi_year_s1_eval",
        "run_standard_research_eval",
        "standard_research_eval_checklist_run",
    }
)


def __getattr__(name: str):
    if name == "run_multi_year_s1_eval":
        from research.eval_harness_s1 import run_multi_year_s1_eval as _fn

        return _fn
    if name == "run_multi_year_extra_hyp_eval":
        from research.eval_harness_extra_hyp import run_multi_year_extra_hyp_eval as _fn

        return _fn
    if name == "run_standard_research_eval":
        from research.eval_harness_standard import run_standard_research_eval as _fn

        return _fn
    if name == "standard_research_eval_checklist_run":
        from research.eval_harness_standard import (
            standard_research_eval_checklist_run as _fn,
        )

        return _fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_EXPORTS | set(__all__))


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
