"""Reusable single-shot research eval harness (Mass OFF / Phase7 OFF / READY OFF).

Pipeline: approved-leg signal → multiday as_of → next_day_return → R2
``batch_summary.json``. Implementation: :mod:`research.single_shot_job`.
Candidate daily-path SoT: :mod:`research.daily_path_eval`.

Multi-year / checklist helpers live in :mod:`research.eval_harness_multiyear`
(S1: :mod:`research.eval_harness_s1`; extra-hyp: :mod:`research.eval_harness_extra_hyp`)
and are re-exported here. This module is W56 next-day, not candidate SoT.

COMPLETE 21 only; permanent DEFER hard-reject; registry-approved legs only
(default: ``topix_relative_1d`` · ``is_trading_day`` · ``volume_change_1d``).
No mass_research import, READY mint, orders, or densify.
Label: **小サンプル / 研究用・未宣言**.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    CANDIDATE_ONLY as SIGNAL_CANDIDATE_ONLY,
    DEFAULT_FEATURE_IDS as APPROVED_SIGNAL_LEGS,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    DEFAULT_VOLUME_SIGN_ABS_MIN,
    FEATURE_STATUS_PINS,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
)
from features.registry import get as get_feature
from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_MASS_RESEARCH_LOOP,
    CONNECTED_TO_READY,
    DENSIFY,
    EDGE_CLAIMED,
    LOCAL_SOT,
    MASS_RESEARCH,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    OPERATIONAL_GO,
    ORDER_EXECUTION,
    PHASE7,
    PHASE7_ENV_ARMING_SWITCHES,
    READY_DECLARED,
    SIGNIFICANCE_CLAIMED,
)
from research.single_shot_job import (
    COMPLETE_21_DATASET_SET,
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    MultidaySignalEval,
    NEXTDAY_RESEARCH_LABEL,
    RESEARCH_ONE_WAY_COST,
    R2PutFn,
    SingleShotJobError,
    assert_mass_and_phase7_off,
    execute_multiday_multisignal_compare,
    execute_multiday_signal_eval,
    freeze_status,
    require_complete_21_only,
)

HARNESS_VERSION: str = "research-eval-harness/v1"
PIPELINE: tuple[str, ...] = (
    "approved_leg_signal",
    "multiday_as_of",
    "next_day_return_eval",
    "r2_batch_summary",
)

HARNESS_SMOKE_CODES: tuple[str, ...] = ("13010", "72030", "67580")
DEFAULT_EVAL_CODES: tuple[str, ...] = HARNESS_SMOKE_CODES


class EvalHarnessError(SingleShotJobError):
    """Invalid eval-harness input (datasets / feature legs / freeze)."""


def _selected_codes(
    codes: Sequence[str] | None,
    default: Sequence[str] = DEFAULT_EVAL_CODES,
) -> list[str]:
    if codes is not None:
        return [str(c).strip() for c in codes if str(c).strip()]
    return list(default)


def _closed_flags(**extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "densify": DENSIFY,
        "local_sot": LOCAL_SOT,
        "order_execution": ORDER_EXECUTION,
    }
    out.update(extra)
    return out


def _skip_year_row(
    p: Mapping[str, Any],
    *,
    pid: str,
    skip_reason: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "period_id": pid,
        "year": p.get("year"),
        "status": "skipped",
        "skip_reason": skip_reason,
        "period_start": p.get("period_start"),
        "period_end": p.get("period_end"),
        "compare_table": None,
        "coverage_notes": p.get("coverage_notes"),
        "s4_eligible": p.get("s4_eligible"),
        **extra,
    }


def require_approved_signal_legs(
    feature_ids: Sequence[str] | None = None,
    *,
    context: str = "eval harness signal legs",
) -> tuple[str, ...]:
    """Ordered feature ids iff every leg is registry-approved. Empty/unknown/not-approved fail closed."""
    if feature_ids is None:
        requested = tuple(APPROVED_SIGNAL_LEGS)
    elif isinstance(feature_ids, str):
        requested = (feature_ids,)
    else:
        requested = tuple(str(x).strip() for x in feature_ids if str(x).strip())

    if not requested:
        raise EvalHarnessError(f"{context}: at least one approved feature leg required")

    out: list[str] = []
    seen: set[str] = set()
    bad_status: list[str] = []
    unknown: list[str] = []
    for fid in requested:
        if fid in seen:
            continue
        seen.add(fid)
        try:
            feat = get_feature(fid)
        except KeyError:
            unknown.append(fid)
            continue
        if str(feat.status) != "approved":
            bad_status.append(f"{fid}={feat.status}")
            continue
        out.append(fid)

    if unknown:
        raise EvalHarnessError(
            f"{context}: unknown feature id(s): {sorted(set(unknown))}"
        )
    if bad_status:
        raise EvalHarnessError(
            f"{context}: feature leg(s) not registry-approved: {bad_status}. "
            "Eval harness admits approved legs only (no candidate/shadow)."
        )
    return tuple(out)


def require_harness_datasets(
    datasets: Sequence[str] | str | None = None,
    *,
    context: str = "eval harness datasets",
) -> tuple[str, ...]:
    """COMPLETE 21 only; permanent DEFER hard-reject. Default: DEFAULT_SIGNAL_DATASETS."""
    if datasets is None:
        datasets = DEFAULT_SIGNAL_DATASETS
    # Permanent DEFER first (shared contract), then COMPLETE-21 allowlist.
    return require_complete_21_only(datasets, context=context)


def harness_freeze_status() -> dict[str, Any]:
    """Return harness + single-shot freeze surface (never arms switches)."""
    return {
        **dict(freeze_status()),
        **_closed_flags(
            harness_version=HARNESS_VERSION,
            pipeline=list(PIPELINE),
            approved_signal_legs=list(APPROVED_SIGNAL_LEGS),
            feature_status_pins=dict(FEATURE_STATUS_PINS),
            default_signal_datasets=list(DEFAULT_SIGNAL_DATASETS),
            default_eval_codes=list(DEFAULT_EVAL_CODES),
            connected_to_mass_research_loop=CONNECTED_TO_MASS_RESEARCH_LOOP,
            label=NEXTDAY_RESEARCH_LABEL,
        ),
    }


def assert_harness_closed() -> Mapping[str, Any]:
    """Hard-check freeze constants for the harness surface."""
    status = assert_mass_and_phase7_off()
    if MASS_RESEARCH != "NO-GO":
        raise RuntimeError(f"harness mass_research must be NO-GO, got {MASS_RESEARCH!r}")
    if PHASE7 != "OFF":
        raise RuntimeError(f"harness phase7 must be OFF, got {PHASE7!r}")
    if READY_DECLARED is not False:
        raise RuntimeError("harness READY_DECLARED must be False")
    if ORDER_EXECUTION is not False:
        raise RuntimeError("harness ORDER_EXECUTION must be False")
    if CONNECTED_TO_MASS_RESEARCH_LOOP is not False:
        raise RuntimeError("harness must not connect to mass research loop")
    if DENSIFY is not False:
        raise RuntimeError("harness densify must remain False")
    if PHASE7_ENV_ARMING_SWITCHES:
        raise RuntimeError("PHASE7 env arming switches must remain empty")
    if MASS_RESEARCH_ENV_ARMING_SWITCHES:
        raise RuntimeError("MASS_RESEARCH env arming switches must remain empty")
    require_approved_signal_legs(context="harness freeze approved legs")
    require_harness_datasets(context="harness freeze default datasets")
    return status


def run_multiday_signal_eval(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "eval-harness-multiday",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 10,
    min_days: int = 5,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
    attach_nextday_returns: bool = False,
    write_per_day_artifacts: bool = True,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "d1_tip",
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None = None,
    r2_get: Any | None = None,
    r2_bucket: str = "quant-structured",
) -> MultidaySignalEval:
    """Multiday approved-leg signal batch → R2 ``batch_summary.json``.

    COMPLETE-21 + approved legs before tip extract. history_source: ``d1_tip``
    or ``r2``. Does not mint READY, arm Mass, execute orders, or densify.
    """
    assert_harness_closed()
    require_approved_signal_legs(context="multiday signal eval legs")
    require_harness_datasets(context="multiday signal eval datasets")
    return execute_multiday_signal_eval(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=_selected_codes(codes),
        as_of_days=as_of_days,
        max_days=max_days,
        min_days=min_days,
        feature_row_limit=feature_row_limit,
        volume_change_abs_min=volume_change_abs_min,
        attach_nextday_returns=attach_nextday_returns,
        write_per_day_artifacts=write_per_day_artifacts,
        dry_run=dry_run,
        d1_execute=d1_execute,
        r2_put=r2_put,
        staging_dir=staging_dir,
        wrangler=wrangler,
        wrangler_config=wrangler_config,
        history_source=history_source,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
    )


def run_nextday_return_eval(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "eval-harness-nextday",
    **kwargs: Any,
) -> MultidaySignalEval:
    """Approved-leg signal → multiday → next-day return → R2. Research only."""
    kwargs.pop("attach_nextday_returns", None)
    return run_multiday_signal_eval(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        attach_nextday_returns=True,
        **kwargs,
    )


run_full_pipeline = run_nextday_return_eval


WALK_FORWARD_VERSION: str = "research-walk-forward/v1"
MULTI_PERIOD_VERSION: str = "research-multi-period-multisignal/v1"
RESEARCH_WALK_FORWARD_LABEL: str = (
    "小サンプル / 研究用ウォークフォワード・未宣言 "
    "(固定シグナル定義・閾値チューニングなし・運用GOではない)"
)


def split_asof_days_walk_forward(
    as_of_days: Sequence[str],
    *,
    train_fraction: float = 0.5,
    min_train_days: int = 5,
    min_test_days: int = 5,
) -> dict[str, Any]:
    """Chronological train/test split. Same fixed defs both folds; no threshold fit."""
    days = sorted({str(d).strip()[:10] for d in as_of_days if str(d).strip()})
    if not days:
        raise EvalHarnessError("walk-forward split requires non-empty as_of_days")
    frac = float(train_fraction)
    if not (0.0 < frac < 1.0):
        raise EvalHarnessError(
            f"train_fraction must be in (0,1), got {train_fraction!r}"
        )
    n = len(days)
    n_train = max(int(min_train_days), int(round(n * frac)))
    if n_train > n - int(min_test_days):
        n_train = max(int(min_train_days), n - int(min_test_days))
    train = days[:n_train]
    test = days[n_train:]
    if len(train) < int(min_train_days) or len(test) < int(min_test_days):
        raise EvalHarnessError(
            "walk-forward split too short after constraints: "
            f"n={n} train={len(train)} test={len(test)} "
            f"min_train={min_train_days} min_test={min_test_days}"
        )
    return {
        "version": WALK_FORWARD_VERSION,
        "label": RESEARCH_WALK_FORWARD_LABEL,
        "train_fraction": frac,
        "n_days_total": n,
        "n_train": len(train),
        "n_test": len(test),
        "train_as_of_days": train,
        "test_as_of_days": test,
        "train_span": [train[0], train[-1]],
        "test_span": [test[0], test[-1]],
        "threshold_tuning": False,
        "signal_definitions_fixed": True,
        **_closed_flags(),
    }


def _compact_compare_rows(batch_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = batch_summary.get("compare_table")
    if isinstance(rows, list):
        return [dict(r) for r in rows]
    return []


def _fold_summary(ex: MultidaySignalEval) -> dict[str, Any]:
    return {
        "n_days": ex.n_days,
        "as_of_days": list(ex.as_of_days),
        "compare_table": _compact_compare_rows(ex.batch_summary),
        "batch_summary_r2_key": ex.batch_summary_r2_key,
    }


def run_research_walk_forward_multisignal(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "eval-harness-wf-multisignal",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 50,
    min_days: int = 20,
    train_fraction: float = 0.5,
    min_train_days: int = 10,
    min_test_days: int = 10,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_sign_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
    write_per_day_artifacts: bool = False,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "r2",
    r2_object_keys_by_dataset: Mapping[str, Sequence[str]] | None = None,
    r2_local_paths_by_dataset: Mapping[str, Sequence[str | Path]] | None = None,
    r2_raw_lines_by_dataset: Mapping[str, Sequence[Any]] | None = None,
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
    r2_allow_empty_datasets: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fixed S1/S2/S3 on chronological train then test. No threshold fit on train."""
    assert_harness_closed()
    jid = str(job_id).strip()
    shared: dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "feature_row_limit": feature_row_limit,
        "volume_sign_abs_min": volume_sign_abs_min,
        "one_way_cost": one_way_cost,
        "write_per_day_artifacts": write_per_day_artifacts,
        "dry_run": dry_run,
        "d1_execute": d1_execute,
        "r2_put": r2_put,
        "staging_dir": staging_dir,
        "wrangler": wrangler,
        "wrangler_config": wrangler_config,
        "history_source": history_source,
        "r2_object_keys_by_dataset": r2_object_keys_by_dataset,
        "r2_local_paths_by_dataset": r2_local_paths_by_dataset,
        "r2_raw_lines_by_dataset": r2_raw_lines_by_dataset,
        "r2_get": r2_get,
        "r2_bucket": r2_bucket,
        "r2_allow_empty_datasets": r2_allow_empty_datasets,
    }
    full = execute_multiday_multisignal_compare(
        job_id=f"{jid}-full",
        codes=codes,
        as_of_days=as_of_days,
        max_days=max_days,
        min_days=min_days,
        **shared,
    )
    split = split_asof_days_walk_forward(
        list(full.as_of_days),
        train_fraction=train_fraction,
        min_train_days=min_train_days,
        min_test_days=min_test_days,
    )
    train_ex = execute_multiday_multisignal_compare(
        job_id=f"{jid}-train",
        codes=list(full.codes),
        as_of_days=split["train_as_of_days"],
        max_days=len(split["train_as_of_days"]),
        min_days=min_train_days,
        **shared,
    )
    test_ex = execute_multiday_multisignal_compare(
        job_id=f"{jid}-test",
        codes=list(full.codes),
        as_of_days=split["test_as_of_days"],
        max_days=len(split["test_as_of_days"]),
        min_days=min_test_days,
        **shared,
    )
    return {
        "version": WALK_FORWARD_VERSION,
        "job_id": jid,
        "label": RESEARCH_WALK_FORWARD_LABEL,
        "history_source": history_source,
        "period_start": str(period_start)[:10],
        "period_end": str(period_end)[:10],
        "codes": list(full.codes),
        "n_codes": len(full.codes),
        "split": split,
        "volume_sign_abs_min": float(volume_sign_abs_min),
        "threshold_tuning": False,
        "full": _fold_summary(full),
        "train": _fold_summary(train_ex),
        "test": _fold_summary(test_ex),
        **_closed_flags(),
    }


def run_multi_period_multisignal_compare(
    periods: Sequence[Mapping[str, Any]],
    *,
    job_id_prefix: str = "eval-harness-mp",
    codes: Sequence[str] | None = None,
    max_days: int = 50,
    min_days: int = 20,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_sign_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
    write_per_day_artifacts: bool = False,
    dry_run: bool = False,
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "r2",
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> dict[str, Any]:
    """Fixed S1/S2/S3 on non-overlapping periods. Skips recorded; never invent."""
    assert_harness_closed()
    if not periods:
        raise EvalHarnessError("multi-period compare requires at least one period")

    results: list[dict[str, Any]] = []
    for i, raw in enumerate(periods):
        p = dict(raw)
        pid = str(p.get("period_id") or f"p{i}").strip()
        skip_reason = p.get("skip_reason")
        if skip_reason:
            results.append(_skip_year_row(p, pid=pid, skip_reason=str(skip_reason)))
            continue
        start = str(p.get("period_start") or "").strip()[:10]
        end = str(p.get("period_end") or "").strip()[:10]
        if not start or not end:
            results.append(
                _skip_year_row(
                    p, pid=pid, skip_reason="missing period_start/period_end"
                )
            )
            continue
        try:
            ex = execute_multiday_multisignal_compare(
                period_start=start,
                period_end=end,
                job_id=f"{job_id_prefix}-{pid}",
                codes=codes,
                as_of_days=p.get("as_of_days"),
                max_days=int(p.get("max_days") or max_days),
                min_days=int(p.get("min_days") or min_days),
                feature_row_limit=feature_row_limit,
                volume_sign_abs_min=volume_sign_abs_min,
                one_way_cost=one_way_cost,
                write_per_day_artifacts=write_per_day_artifacts,
                dry_run=dry_run,
                d1_execute=d1_execute,
                r2_put=r2_put,
                staging_dir=staging_dir,
                wrangler=wrangler,
                wrangler_config=wrangler_config,
                history_source=str(p.get("history_source") or history_source),
                r2_object_keys_by_dataset=p.get("r2_object_keys_by_dataset"),
                r2_local_paths_by_dataset=p.get("r2_local_paths_by_dataset"),
                r2_raw_lines_by_dataset=p.get("r2_raw_lines_by_dataset"),
                r2_get=r2_get,
                r2_bucket=r2_bucket,
                r2_allow_empty_datasets=p.get("r2_allow_empty_datasets"),
            )
            results.append(
                {
                    "period_id": pid,
                    "status": "ok",
                    "period_start": start,
                    "period_end": end,
                    "n_days": ex.n_days,
                    "n_codes": len(ex.codes),
                    "codes": list(ex.codes),
                    "as_of_days": list(ex.as_of_days),
                    "history_source": ex.batch_summary.get("history_source"),
                    "tip_plane": ex.batch_summary.get("tip_plane"),
                    "extracted_row_counts": ex.batch_summary.get(
                        "tip_extracted_row_counts"
                    ),
                    "compare_table": _compact_compare_rows(ex.batch_summary),
                    "batch_summary_r2_key": ex.batch_summary_r2_key,
                    "coverage_notes": p.get("coverage_notes"),
                    "label": NEXTDAY_RESEARCH_LABEL,
                }
            )
        except Exception as exc:  # noqa: BLE001 — research batch: capture per-period
            results.append(
                {
                    "period_id": pid,
                    "status": "error",
                    "period_start": start,
                    "period_end": end,
                    "error": f"{type(exc).__name__}: {exc}",
                    "compare_table": None,
                    "coverage_notes": p.get("coverage_notes"),
                }
            )

    cross: list[dict[str, Any]] = []
    for r in results:
        if r.get("status") != "ok":
            continue
        for row in r.get("compare_table") or []:
            cross.append(
                {
                    "period_id": r["period_id"],
                    "period_start": r.get("period_start"),
                    "period_end": r.get("period_end"),
                    "n_days": r.get("n_days"),
                    "n_codes": r.get("n_codes"),
                    **dict(row),
                }
            )

    return {
        "version": MULTI_PERIOD_VERSION,
        "job_id_prefix": job_id_prefix,
        "label": NEXTDAY_RESEARCH_LABEL,
        "history_source_default": history_source,
        "n_periods_requested": len(periods),
        "n_periods_ok": sum(1 for r in results if r.get("status") == "ok"),
        "n_periods_skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "n_periods_error": sum(1 for r in results if r.get("status") == "error"),
        "periods": results,
        "cross_period_compare_table": cross,
        **_closed_flags(),
    }


# Multi-year / checklist live in research.eval_harness_multiyear (re-exported).
_MULTIYEAR_EXPORTS: tuple[str, ...] = (
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
)
_MULTIYEAR_EXPORT_SET: frozenset[str] = frozenset(_MULTIYEAR_EXPORTS)


def __getattr__(name: str):
    if name in _MULTIYEAR_EXPORT_SET:
        import research.eval_harness_multiyear as _eval_harness_multiyear

        return getattr(_eval_harness_multiyear, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _MULTIYEAR_EXPORT_SET | set(__all__))


__all__ = [
    "APPROVED_SIGNAL_LEGS",
    "COMPLETE_21_DATASET_SET",
    "CONNECTED_TO_MASS_RESEARCH_LOOP",
    "DEFAULT_EVAL_CODES",
    "DEFAULT_SIGNAL_DATASETS",
    "DEFAULT_SIGNAL_ID",
    "EvalHarnessError",
    "HARNESS_SMOKE_CODES",
    "HARNESS_VERSION",
    "MASS_RESEARCH",
    "NEXTDAY_RESEARCH_LABEL",
    "ORDER_EXECUTION",
    "PHASE7",
    "PIPELINE",
    "RESEARCH_WALK_FORWARD_LABEL",
    "SIGNAL_CANDIDATE_ONLY",
    "SingleShotJobError",
    "WALK_FORWARD_VERSION",
    "assert_harness_closed",
    "harness_freeze_status",
    "require_approved_signal_legs",
    "require_harness_datasets",
    "run_full_pipeline",
    "run_multi_period_multisignal_compare",
    "run_multiday_signal_eval",
    "run_nextday_return_eval",
    "run_research_walk_forward_multisignal",
    "split_asof_days_walk_forward",
    *_MULTIYEAR_EXPORTS,
]
