"""Reusable single-shot research eval harness (Mass OFF / Phase7 OFF / READY OFF).

Pipeline: approved-leg signal → multiday as_of → next_day_return → R2
``batch_summary.json``. Implementation: :mod:`research.single_shot_job`.
Candidate daily-path SoT: :mod:`research.daily_path_eval`.

COMPLETE 21 only; permanent DEFER hard-reject; registry-approved legs only
(default: ``topix_relative_1d`` · ``is_trading_day`` · ``volume_change_1d``).
No mass_research import, READY mint, orders, or densify.
Label: **小サンプル / 研究用・未宣言**.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    CANDIDATE_ONLY as SIGNAL_CANDIDATE_ONLY,
    DEFAULT_FEATURE_IDS as APPROVED_SIGNAL_LEGS,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    DEFAULT_VOLUME_SIGN_ABS_MIN,
    FEATURE_STATUS_PINS,
    MULTI_SIGNAL_DATASETS,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
)
from features.registry import get as get_feature
from research.freezes import (
    CONNECTED_TO_MASS_RESEARCH_LOOP,
    DENSIFY,
    LOCAL_SOT,
    MASS_RESEARCH,
    ORDER_EXECUTION,
    PHASE7,
)
from research.robustness_gate import (
    DEFAULT_ONE_WAY_COST,
    annotate_period_rows_with_cost,
    evaluate_research_robustness_gate,
    period_rows_from_cross_table,
    research_robustness_gate_document,
)
from research.single_shot_job import (
    COMPLETE_21_DATASET_SET,
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    MultidaySignalEval,
    NEXTDAY_RESEARCH_LABEL,
    PHASE7_ENV_ARMING_SWITCHES,
    READY_DECLARED,
    RESEARCH_ONE_WAY_COST,
    R2PutFn,
    SingleShotJobError,
    assert_mass_and_phase7_off,
    execute_extra_hyp_signals_compare,
    execute_multiday_multisignal_compare,
    execute_multiday_signal_eval,
    freeze_status,
    require_complete_21_only,
)

# Freeze constants — tests assert these remain closed; do not arm.
HARNESS_VERSION: str = "research-eval-harness/v1"
PIPELINE: tuple[str, ...] = (
    "approved_leg_signal",
    "multiday_as_of",
    "next_day_return_eval",
    "r2_batch_summary",
)

# Smoke 3 names for harness tip batches. Not EVAL_UNIVERSE_POOL.
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
        "ready_declared": False,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
    }
    out.update(extra)
    return out


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
    base = dict(freeze_status())
    base.update(
        {
            "harness_version": HARNESS_VERSION,
            "pipeline": list(PIPELINE),
            "approved_signal_legs": list(APPROVED_SIGNAL_LEGS),
            "feature_status_pins": dict(FEATURE_STATUS_PINS),
            "default_signal_datasets": list(DEFAULT_SIGNAL_DATASETS),
            "default_eval_codes": list(DEFAULT_EVAL_CODES),
            "order_execution": ORDER_EXECUTION,
            "connected_to_mass_research_loop": CONNECTED_TO_MASS_RESEARCH_LOOP,
            "densify": DENSIFY,
            "local_sot": LOCAL_SOT,
            "label": NEXTDAY_RESEARCH_LABEL,
            "significance_claimed": False,
            "edge_claimed": False,
        }
    )
    return base


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
    # Legs must still be approved at call time.
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


# Walk-forward + multi-period compare (not READY / not Mass).
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
    # Keep at least min_test_days on the right when possible.
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
        "note": (
            "Research chronological holdout only. Same fixed definitions on "
            "both folds; thresholds are not fit on train."
        ),
    }


def _compact_compare_rows(batch_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = batch_summary.get("compare_table")
    if isinstance(rows, list):
        return [dict(r) for r in rows]
    return []


def run_multisignal_compare(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "eval-harness-multisignal",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 20,
    min_days: int = 5,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_sign_abs_min: float = DEFAULT_VOLUME_SIGN_ABS_MIN,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
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
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
    r2_allow_empty_datasets: Sequence[str] | None = None,
) -> MultidaySignalEval:
    """S1/S2/S3 multi-signal compare via single_shot (research-only). Freeze closed."""
    assert_harness_closed()
    require_complete_21_only(
        MULTI_SIGNAL_DATASETS, context="harness multisignal datasets"
    )
    return execute_multiday_multisignal_compare(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=_selected_codes(codes),
        as_of_days=as_of_days,
        max_days=max_days,
        min_days=min_days,
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
        history_source=history_source,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        r2_allow_empty_datasets=r2_allow_empty_datasets,
    )


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
        **_closed_flags(local_sot=False),
        "note": (
            "Research walk-forward with fixed signal definitions on both folds. "
            "No threshold search on train."
        ),
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
            results.append(
                {
                    "period_id": pid,
                    "status": "skipped",
                    "skip_reason": str(skip_reason),
                    "period_start": p.get("period_start"),
                    "period_end": p.get("period_end"),
                    "compare_table": None,
                    "coverage_notes": p.get("coverage_notes"),
                }
            )
            continue
        start = str(p.get("period_start") or "").strip()[:10]
        end = str(p.get("period_end") or "").strip()[:10]
        if not start or not end:
            results.append(
                {
                    "period_id": pid,
                    "status": "skipped",
                    "skip_reason": "missing period_start/period_end",
                    "compare_table": None,
                }
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

    # Cross-period compact table (one row per period × signal).
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
        **_closed_flags(local_sot=False),
        "note": (
            "Multi-period fixed-definition multi-signal research compare. "
            "Skips documented when data missing. No densify invent."
        ),
    }


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

# Honest inventory (no densify). topix 2024–2025 → archive; calendar JSONL
# 2026 tip only; margin 2024 empty_allowed.
DATASET_YEAR_INVENTORY_NOTES: Mapping[str, Any] = MappingProxyType(
    {
        "equities_bars_daily": {
            "jsonl_years": "2008-2026 continuous-ish",
            "gap_years": [],
            "fallback": None,
        },
        "indices_bars_daily_topix": {
            "jsonl_years": "2008-2023 + 2026",
            "gap_years": [2024, 2025],
            "fallback": "archive full-history disposable mirror",
        },
        "markets_calendar": {
            "jsonl_years": "2026 tip only",
            "gap_years": list(range(2008, 2026)),
            "fallback": "archive + research PIT repair (calendar_ingest_pollution)",
        },
        "markets_margin_interest": {
            "jsonl_years": "2013-2023 + 2025-2026",
            "gap_years": [2024],
            "fallback": None,
            "note": "empty_allowed for gap years; never invent",
        },
        "markets_short_ratio": {
            "jsonl_years": "2013-2023 + 2026",
            "gap_years": [2024, 2025],
            "fallback": None,
        },
        "fins_summary": {
            "jsonl_years": "2008-2026 monthly-ish sparse",
            "gap_years": [],
            "fallback": None,
        },
    }
)


def design_yearly_eval_windows(
    years: Sequence[int] | None = None,
    *,
    window: str = "q4",
    max_days: int = 80,
    min_days: int = 40,
    codes: Sequence[str] | None = None,
    inventory_notes: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Yearly (or half-year) windows for multi-year eval. Gaps recorded; no invent.

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
    inv = dict(inventory_notes or DATASET_YEAR_INVENTORY_NOTES)
    out: list[dict[str, Any]] = []
    for y in yrs:
        period_start = f"{int(y)}-{start_md}"
        period_end = f"{int(y)}-{end_md}"
        # Honest per-year dataset availability from static inventory notes.
        topix_gap = int(y) in set(inv.get("indices_bars_daily_topix", {}).get("gap_years") or [])
        margin_gap = int(y) in set(
            inv.get("markets_margin_interest", {}).get("gap_years") or []
        )
        margin_pre = int(y) < 2013  # margin inventory starts ~2013
        cal_note = inv.get("markets_calendar", {}).get("fallback") or "archive"
        topix_note = (
            inv.get("indices_bars_daily_topix", {}).get("fallback")
            or "archive"
            if topix_gap
            else "jsonl or archive"
        )
        coverage = {
            "year": int(y),
            "window": w,
            "period_start": period_start,
            "period_end": period_end,
            "bars": {
                "dataset": "equities_bars_daily",
                "inventory": inv.get("equities_bars_daily", {}).get("jsonl_years"),
                "expected": "present (2008-2026 inventory)" if 2008 <= int(y) <= 2026 else "out_of_inventory",
            },
            "topix": {
                "dataset": "indices_bars_daily_topix",
                "jsonl_gap": topix_gap,
                "source": topix_note,
            },
            "calendar": {
                "dataset": "markets_calendar",
                "source": cal_note,
                "pit_repair": "calendar_ingest_pollution (research-only)",
            },
            "margin_interest": {
                "dataset": "markets_margin_interest",
                "jsonl_gap": margin_gap or margin_pre,
                "s4_eligible": not (margin_gap or margin_pre),
                "handling": (
                    "empty_allowed / skip S4"
                    if (margin_gap or margin_pre)
                    else "jsonl when mirrored"
                ),
            },
            "n_codes": len(selected),
            "codes": list(selected),
            "max_days": int(max_days),
            "min_days": int(min_days),
            "no_densify": True,
            "no_invent": True,
        }
        skip_reason = None
        if int(y) < 2008 or int(y) > 2026:
            skip_reason = f"year {y} outside equities_bars_daily inventory 2008-2026"
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
            "s4_eligible": bool(coverage["margin_interest"]["s4_eligible"]),
            "r2_allow_empty_datasets": (
                ["markets_margin_interest"]
                if not coverage["margin_interest"]["s4_eligible"]
                else []
            ),
        }
        if skip_reason:
            item["skip_reason"] = skip_reason
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


def _s1_metrics_from_batch_summary(
    batch_summary: Mapping[str, Any],
    *,
    period_id: str,
    n_days: int,
    n_codes: int,
) -> dict[str, Any]:
    """Extract gate-ready S1 metrics from multiday nextday batch_summary.

    Multisignal compare tables already carry ``gross_signed_mean_active``.
    Single-signal nextday batches expose ``nextday_return.by_sign`` only —
    derive gross signed mean as:

        (n+ * mean_R+ − n− * mean_R−) / (n+ + n−)

    over non-null return counts (research-only; no edge claim).
    """
    bs = dict(batch_summary or {})
    # Prefer compare_table S1 row when present.
    for row in _compact_compare_rows(bs):
        if str(row.get("signal_id") or "") == DEFAULT_SIGNAL_ID:
            out = dict(row)
            out["period_id"] = period_id
            out["n_days"] = n_days
            out["n_codes"] = n_codes
            return out

    nd = bs.get("nextday_return") or bs.get("nextday_summary") or {}
    by_sign = nd.get("by_sign") if isinstance(nd, Mapping) else None
    mean_plus = mean_minus = None
    n_plus = n_minus = 0
    if isinstance(by_sign, Mapping):
        p = by_sign.get("+1") or {}
        m = by_sign.get("-1") or {}
        mean_plus = p.get("mean_next_day_return")
        mean_minus = m.get("mean_next_day_return")
        try:
            n_plus = int(p.get("non_null_return_count") or p.get("count") or 0)
        except (TypeError, ValueError):
            n_plus = 0
        try:
            n_minus = int(m.get("non_null_return_count") or m.get("count") or 0)
        except (TypeError, ValueError):
            n_minus = 0
    gross = None
    n_active = n_plus + n_minus
    if (
        mean_plus is not None
        and mean_minus is not None
        and n_active > 0
    ):
        try:
            gross = (
                float(mean_plus) * n_plus - float(mean_minus) * n_minus
            ) / float(n_active)
        except (TypeError, ValueError, ZeroDivisionError):
            gross = None
    elif mean_plus is not None and n_minus == 0 and n_plus > 0:
        try:
            gross = float(mean_plus)
        except (TypeError, ValueError):
            gross = None
    elif mean_minus is not None and n_plus == 0 and n_minus > 0:
        try:
            gross = -float(mean_minus)
        except (TypeError, ValueError):
            gross = None

    agg = bs.get("aggregate") if isinstance(bs.get("aggregate"), Mapping) else {}
    non_null = agg.get("non_null")
    non_null_rate = agg.get("non_null_rate")
    if non_null is None and isinstance(nd, Mapping):
        so = nd.get("signed_overall") or nd.get("overall") or {}
        if isinstance(so, Mapping):
            non_null = so.get("non_null_return_count")
            non_null_rate = (
                1.0 - float(so["null_return_rate"])
                if so.get("null_return_rate") is not None
                else None
            )

    return {
        "signal_id": DEFAULT_SIGNAL_ID,
        "period_id": period_id,
        "n_days": n_days,
        "n_codes": n_codes,
        "mean_R_plus": mean_plus,
        "mean_R_minus": mean_minus,
        "gross_signed_mean_active": gross,
        "n_active_positions": n_active or non_null,
        "non_null": non_null if non_null is not None else n_active,
        "non_null_rate": non_null_rate,
    }


def run_multi_year_s1_eval(
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    years: Sequence[int] | None = None,
    job_id_prefix: str = "eval-harness-my-s1",
    codes: Sequence[str] | None = None,
    max_days: int = 80,
    min_days: int = 40,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
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
    apply_robustness_gate: bool = True,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    require_net_sign_majority: bool = True,
) -> dict[str, Any]:
    """Year-split S1 eval; fail-one-year safe. Gate pass ≠ READY/Mass."""
    assert_harness_closed()
    require_approved_signal_legs(context="multi-year S1 legs")
    require_harness_datasets(context="multi-year S1 datasets")

    if periods is None:
        period_list = design_yearly_eval_windows(
            years, max_days=max_days, min_days=min_days, codes=codes
        )
    else:
        period_list = [dict(p) for p in periods]
    if not period_list:
        raise EvalHarnessError("multi-year S1 requires at least one period")

    selected_default = _selected_codes(codes, DEFAULT_MULTIYEAR_CODES)

    results: list[dict[str, Any]] = []
    for i, raw in enumerate(period_list):
        p = dict(raw)
        pid = str(p.get("period_id") or f"y{i}").strip()
        skip_reason = p.get("skip_reason")
        if skip_reason:
            results.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "status": "skipped",
                    "skip_reason": str(skip_reason),
                    "period_start": p.get("period_start"),
                    "period_end": p.get("period_end"),
                    "compare_table": None,
                    "s1_row": None,
                    "coverage_notes": p.get("coverage_notes"),
                    "s4_eligible": p.get("s4_eligible"),
                }
            )
            continue
        start = str(p.get("period_start") or "").strip()[:10]
        end = str(p.get("period_end") or "").strip()[:10]
        if not start or not end:
            results.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "status": "skipped",
                    "skip_reason": "missing period_start/period_end",
                    "compare_table": None,
                    "s1_row": None,
                }
            )
            continue
        year_codes = p.get("codes") or selected_default
        try:
            ex = execute_multiday_signal_eval(
                period_start=start,
                period_end=end,
                job_id=f"{job_id_prefix}-{pid}",
                codes=year_codes,
                as_of_days=p.get("as_of_days"),
                max_days=int(p.get("max_days") or max_days),
                min_days=int(p.get("min_days") or min_days),
                feature_row_limit=feature_row_limit,
                volume_change_abs_min=volume_change_abs_min,
                attach_nextday_returns=True,
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
            )
            # Compact S1 metrics from batch_summary (nextday path).
            bs = ex.batch_summary or {}
            s1_row = _s1_metrics_from_batch_summary(
                bs, period_id=pid, n_days=ex.n_days, n_codes=len(ex.codes)
            )
            compare = _compact_compare_rows(bs)
            if compare:
                for row in compare:
                    if str(row.get("signal_id") or "") == DEFAULT_SIGNAL_ID:
                        s1_row = {**s1_row, **dict(row), "period_id": pid}
                        break
            results.append(
                {
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
                    "tip_plane": bs.get("tip_plane"),
                    "extracted_row_counts": bs.get("tip_extracted_row_counts"),
                    "s1_row": s1_row,
                    "compare_table": compare or [s1_row],
                    "batch_summary_r2_key": ex.batch_summary_r2_key,
                    "coverage_notes": p.get("coverage_notes"),
                    "s4_eligible": p.get("s4_eligible"),
                    "label": NEXTDAY_RESEARCH_LABEL,
                }
            )
        except Exception as exc:  # noqa: BLE001 — year isolation
            results.append(
                _year_period_error_row(
                    {**p, "period_id": pid, "period_start": start, "period_end": end},
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    cross: list[dict[str, Any]] = []
    for r in results:
        if r.get("status") != "ok":
            continue
        s1 = r.get("s1_row") or {}
        cross.append(
            {
                "period_id": r["period_id"],
                "year": r.get("year"),
                "period_start": r.get("period_start"),
                "period_end": r.get("period_end"),
                "n_days": r.get("n_days"),
                "n_codes": r.get("n_codes"),
                "signal_id": DEFAULT_SIGNAL_ID,
                "gross_signed_mean_active": s1.get("gross_signed_mean_active"),
                "net_one_way_mean_active": s1.get("net_one_way_mean_active"),
                "mean_R_plus": s1.get("mean_R_plus"),
                "mean_R_minus": s1.get("mean_R_minus"),
                "n_active_positions": s1.get("n_active_positions"),
                "non_null": s1.get("non_null"),
                "non_null_rate": s1.get("non_null_rate"),
            }
        )
    # Annotate cost (research-only 10bp one-way by default).
    cross = annotate_period_rows_with_cost(cross, one_way_cost=one_way_cost)

    gate: dict[str, Any] | None = None
    if apply_robustness_gate:
        period_rows = [
            {
                "period_id": row["period_id"],
                "status": "ok",
                "gross_signed_mean_active": row.get("gross_signed_mean_active"),
                "net_one_way_mean_active": row.get("net_one_way_mean_active"),
                "n_active_positions": row.get("n_active_positions")
                or row.get("non_null"),
                "non_null": row.get("non_null"),
                "non_null_rate": row.get("non_null_rate"),
                "mean_R_plus": row.get("mean_R_plus"),
                "mean_R_minus": row.get("mean_R_minus"),
            }
            for row in cross
            if row.get("gross_signed_mean_active") is not None
        ]
        gate = evaluate_research_robustness_gate(
            period_rows,
            signal_id=DEFAULT_SIGNAL_ID,
            min_periods=min_periods_gate,
            min_active_per_period=min_active_per_period,
            one_way_cost=one_way_cost,
            require_net_sign_majority=require_net_sign_majority,
        )

    return {
        "version": MULTI_YEAR_VERSION,
        "job_id_prefix": job_id_prefix,
        "label": MULTI_YEAR_LABEL,
        "signal_id": DEFAULT_SIGNAL_ID,
        "history_source_default": history_source,
        "n_years_requested": len(period_list),
        "n_years_ok": sum(1 for r in results if r.get("status") == "ok"),
        "n_years_skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "n_years_error": sum(1 for r in results if r.get("status") == "error"),
        "years": results,
        "cross_year_s1_table": cross,
        "robustness_gate": gate,
        "cost_assumption": {
            "one_way_cost": float(one_way_cost),
            "one_way_cost_bp": float(one_way_cost) * 10_000.0,
            "require_net_sign_majority": bool(require_net_sign_majority),
            "label": "仮定に依存・研究用・運用GOではない",
        },
        **_closed_flags(
            local_sot=False,
            year_split=True,
            fail_one_year_safe=True,
        ),
        "note": (
            "Multi-year S1 research eval with independent per-year jobs. "
            "Error/skip on one year does not kill the batch. "
            "pass does NOT mint READY or arm Mass."
        ),
    }


def run_multi_year_extra_hyp_eval(
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    years: Sequence[int] | None = None,
    job_id_prefix: str = "eval-harness-my-s4",
    codes: Sequence[str] | None = None,
    max_days: int = 80,
    min_days: int = 40,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
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
    apply_robustness_gate: bool = True,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    signal_ids: Sequence[str] | None = None,
    require_net_sign_majority: bool = True,
) -> dict[str, Any]:
    """Year-split S4/S5 eval. Gap years skipped honestly — never invent margin."""
    assert_harness_closed()
    if periods is None:
        period_list = design_yearly_eval_windows(
            years, max_days=max_days, min_days=min_days, codes=codes
        )
    else:
        period_list = [dict(p) for p in periods]
    if not period_list:
        raise EvalHarnessError("multi-year extra-hyp requires at least one period")

    selected_default = _selected_codes(codes, DEFAULT_MULTIYEAR_CODES)
    want_signals = (
        {str(s) for s in signal_ids}
        if signal_ids is not None
        else {"c21_margin_change_sign"}
    )

    results: list[dict[str, Any]] = []
    for i, raw in enumerate(period_list):
        p = dict(raw)
        pid = str(p.get("period_id") or f"y{i}").strip()
        skip_reason = p.get("skip_reason")
        s4_ok = p.get("s4_eligible")
        if s4_ok is None:
            # Infer from coverage notes / year.
            y = p.get("year")
            if y is not None and (int(y) == 2024 or int(y) < 2013):
                s4_ok = False
            else:
                s4_ok = True
        if skip_reason:
            results.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "status": "skipped",
                    "skip_reason": str(skip_reason),
                    "compare_table": None,
                    "coverage_notes": p.get("coverage_notes"),
                    "s4_eligible": s4_ok,
                }
            )
            continue
        if not s4_ok:
            results.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "status": "skipped",
                    "skip_reason": (
                        "margin data gap / not s4_eligible "
                        "(inventory empty year; not invented)"
                    ),
                    "period_start": p.get("period_start"),
                    "period_end": p.get("period_end"),
                    "compare_table": None,
                    "coverage_notes": p.get("coverage_notes"),
                    "s4_eligible": False,
                }
            )
            continue
        start = str(p.get("period_start") or "").strip()[:10]
        end = str(p.get("period_end") or "").strip()[:10]
        if not start or not end:
            results.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "status": "skipped",
                    "skip_reason": "missing period_start/period_end",
                    "compare_table": None,
                }
            )
            continue
        year_codes = p.get("codes") or selected_default
        allow_empty = list(p.get("r2_allow_empty_datasets") or [])
        # short_ratio may be empty on some years; keep honest.
        for ds in ("markets_short_ratio",):
            if ds not in allow_empty:
                allow_empty.append(ds)
        try:
            ex = execute_extra_hyp_signals_compare(
                period_start=start,
                period_end=end,
                job_id=f"{job_id_prefix}-{pid}",
                codes=year_codes,
                as_of_days=p.get("as_of_days"),
                max_days=int(p.get("max_days") or max_days),
                min_days=int(p.get("min_days") or min_days),
                feature_row_limit=feature_row_limit,
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
                r2_allow_empty_datasets=allow_empty,
            )
            compare = _compact_compare_rows(ex.batch_summary or {})
            if want_signals:
                compare = [
                    dict(r)
                    for r in compare
                    if str(r.get("signal_id") or "") in want_signals
                ]
            results.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "status": "ok",
                    "period_start": start,
                    "period_end": end,
                    "n_days": ex.n_days,
                    "n_codes": len(ex.codes),
                    "codes": list(ex.codes),
                    "as_of_days": list(ex.as_of_days),
                    "history_source": (ex.batch_summary or {}).get("history_source"),
                    "extracted_row_counts": (ex.batch_summary or {}).get(
                        "tip_extracted_row_counts"
                    ),
                    "compare_table": compare,
                    "batch_summary_r2_key": ex.batch_summary_r2_key,
                    "coverage_notes": p.get("coverage_notes"),
                    "s4_eligible": True,
                    "label": NEXTDAY_RESEARCH_LABEL,
                }
            )
        except Exception as exc:  # noqa: BLE001 — year isolation
            results.append(
                _year_period_error_row(
                    {**p, "period_id": pid, "period_start": start, "period_end": end},
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    cross: list[dict[str, Any]] = []
    for r in results:
        if r.get("status") != "ok":
            continue
        for row in r.get("compare_table") or []:
            cross.append(
                {
                    "period_id": r["period_id"],
                    "year": r.get("year"),
                    "period_start": r.get("period_start"),
                    "period_end": r.get("period_end"),
                    "n_days": r.get("n_days"),
                    "n_codes": r.get("n_codes"),
                    **dict(row),
                }
            )
    cross = annotate_period_rows_with_cost(cross, one_way_cost=one_way_cost)

    gates: dict[str, Any] = {}
    if apply_robustness_gate:
        for sid in sorted(want_signals):
            rows = period_rows_from_cross_table(cross, signal_id=sid)
            gates[sid] = evaluate_research_robustness_gate(
                rows,
                signal_id=sid,
                min_periods=min_periods_gate,
                min_active_per_period=min_active_per_period,
                one_way_cost=one_way_cost,
                require_net_sign_majority=require_net_sign_majority,
            )

    return {
        "version": MULTI_YEAR_VERSION,
        "job_id_prefix": job_id_prefix,
        "label": MULTI_YEAR_LABEL,
        "signal_ids": sorted(want_signals),
        "history_source_default": history_source,
        "n_years_requested": len(period_list),
        "n_years_ok": sum(1 for r in results if r.get("status") == "ok"),
        "n_years_skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "n_years_error": sum(1 for r in results if r.get("status") == "error"),
        "years": results,
        "cross_year_compare_table": cross,
        "robustness_gates": gates,
        "cost_assumption": {
            "one_way_cost": float(one_way_cost),
            "one_way_cost_bp": float(one_way_cost) * 10_000.0,
            "require_net_sign_majority": bool(require_net_sign_majority),
            "label": "仮定に依存・研究用・運用GOではない",
        },
        **_closed_flags(
            local_sot=False,
            year_split=True,
            fail_one_year_safe=True,
        ),
        "note": (
            "Multi-year S4/S5 research eval. Gap years skipped honestly. "
            "Gate pass ≠ READY/Mass."
        ),
    }


def multi_year_availability_table(
    periods: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compact availability table from designed yearly periods + run results."""
    rows: list[dict[str, Any]] = []
    for p in periods:
        cov = p.get("coverage_notes") if isinstance(p.get("coverage_notes"), Mapping) else {}
        margin = cov.get("margin_interest") if isinstance(cov, Mapping) else {}
        topix = cov.get("topix") if isinstance(cov, Mapping) else {}
        rows.append(
            {
                "period_id": p.get("period_id"),
                "year": p.get("year"),
                "period_start": p.get("period_start"),
                "period_end": p.get("period_end"),
                "status": p.get("status") or p.get("status_hint") or "designed",
                "skip_reason": p.get("skip_reason"),
                "error": p.get("error"),
                "bars": (cov.get("bars") or {}).get("expected")
                if isinstance(cov, Mapping)
                else None,
                "topix_jsonl_gap": (topix or {}).get("jsonl_gap"),
                "topix_source": (topix or {}).get("source"),
                "s4_eligible": p.get("s4_eligible")
                if p.get("s4_eligible") is not None
                else (margin or {}).get("s4_eligible"),
                "margin_handling": (margin or {}).get("handling"),
                "n_days": p.get("n_days"),
                "n_codes": p.get("n_codes"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Standard research eval checklist entry (W66 v1 · W77 / w0816k v2)
# ---------------------------------------------------------------------------

CHECKLIST_VERSION: str = "standard-research-eval-checklist/v2"
CHECKLIST_VERSION_V1: str = "standard-research-eval-checklist/v1"
CHECKLIST_WAVE: str = "W77 / w0816k + W100 / w0819c"
CHECKLIST_LABEL: str = (
    "標準研究評価チェックリスト v2・未宣言 "
    "(レバ/空売りコスト + リスクシナリオ + daily_path_DD必須 / "
    "period_net_DD単独合格禁止 / 合格≠research_candidate / "
    "READY未接続 / Mass NO-GO / 運用GOではない)"
)
STANDARD_EVAL_PROOF: str = (
    "docs/proof/w0816k_w77_eval_checklist_v2_20260816.md"
)
STANDARD_EVAL_PROOF_V1: str = (
    "docs/proof/w0815bg_w66_standard_research_eval_checklist_20260815.md"
)
STANDARD_EVAL_DAILY_PATH_DD_PROOF: str = (
    "docs/proof/w0819c_w100_daily_path_dd_gate_20260819.md"
)
# W78 additive: prefer date-matched jsda_tokyo_repo_rates for lev/short costs.
# W79 additive: liquidity-linked tx / short-spread modulation (repo-linked kept).
STANDARD_EVAL_COST_MODEL_PROOF: str = (
    "docs/proof/w0816n_w79_liquidity_linked_cost_20260816.md"
)
STANDARD_EVAL_COST_MODEL_PROOF_REPO_LINKED: str = (
    "docs/proof/w0816m_w78_repo_linked_cost_model_20260816.md"
)
# Defaults for cost-model rate path (prefer repo-linked; fixed bp fallback OK).
COST_MODEL_PREFER_REPO_LINKED: bool = True
COST_MODEL_REQUIRE_REPO_LINKED: bool = False
# W79: prefer liquidity modulation when proxy available; never invent.
COST_MODEL_PREFER_LIQUIDITY_LINKED: bool = True
COST_MODEL_REQUIRE_LIQUIDITY_LINKED: bool = False
# Modes that only re-run existing rejected baselines — never mint new signals.
# class_hyp_offline runs W78–W79 class hyps (not S1–S5 / not simple_daily_sign).
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
    from research.baseline_catalog import (
        RESEARCH_STATUS_REJECTED,
        rejected_baseline_catalog,
    )
    from research.cost_models import cost_models_document
    from research.holding_metrics import holding_metrics_document
    from research.risk_scenarios import risk_scenarios_document
    from research.robustness_gate import research_robustness_gate_document
    from research.stats_metrics import (
        DAILY_PATH_DD_REQUIRED_FIELDS,
        stats_metrics_document,
        w99_sticky_daily_path_dd_reference,
    )

    cat = rejected_baseline_catalog()
    return {
        "version": CHECKLIST_VERSION,
        "prior_version": CHECKLIST_VERSION_V1,
        "wave": CHECKLIST_WAVE,
        "label": CHECKLIST_LABEL,
        "proof": STANDARD_EVAL_PROOF,
        "proof_v1": STANDARD_EVAL_PROOF_V1,
        "daily_path_dd_proof": STANDARD_EVAL_DAILY_PATH_DD_PROOF,
        "cost_model_proof": STANDARD_EVAL_COST_MODEL_PROOF,
        "required": list(CHECKLIST_V2_REQUIRED),
        "near_required": list(CHECKLIST_V2_NEAR_REQUIRED),
        "near_required_note": (
            "holding/turnover is near-required for high-frequency / daily-sign "
            "hyps (prefer hard-require when hyp re-trades frequently)"
        ),
        "recommended": [
            "holding_turnover_metrics",  # kept for v1 compat wording
            "repo_linked_cost_model",  # W78: prefer jsda_tokyo_repo_rates
            "liquidity_linked_cost_model",  # W79: scale tx/short by ADV bucket
        ],
        "insufficient": list(CHECKLIST_V2_INSUFFICIENT),
        "gate": research_robustness_gate_document(),
        "cost_models_surface": cost_models_document(),
        "cost_model_defaults": {
            "prefer_repo_linked": COST_MODEL_PREFER_REPO_LINKED,
            "require_repo_linked": COST_MODEL_REQUIRE_REPO_LINKED,
            "prefer_liquidity_linked": COST_MODEL_PREFER_LIQUIDITY_LINKED,
            "require_liquidity_linked": COST_MODEL_REQUIRE_LIQUIDITY_LINKED,
            "preferred_dataset": "jsda_tokyo_repo_rates",
            "liquidity_dataset": "equities_bars_daily",
            "fixed_bp_fallback_ok": True,
            "liquidity_unmodulated_when_missing_ok": True,
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "note": (
                "W78 / w0816m: leverage financing + short borrow prefer "
                "date-matched Tokyo repo rates. Fixed bp remains a disclosed "
                "fallback when no series is supplied. Gaps never invent-filled. "
                "Not hard-required (require_repo_linked=False). "
                "W79 / w0816n: liquidity (ADV from equities_bars) modulates "
                "one-way tx cost and short spread (combined with low/mid/high "
                "sensitivity). Missing liquidity → mult=1.0 + gap disclose; "
                "never invent. Not hard-required "
                "(require_liquidity_linked=False)."
            ),
        },
        "risk_scenarios_surface": risk_scenarios_document(),
        "holding_surface": holding_metrics_document(),
        "daily_path_dd_surface": {
            "required_fields": list(DAILY_PATH_DD_REQUIRED_FIELDS),
            "period_net_dd_only_pass_forbidden": True,
            "period_net_dd_zero_daily_unmeasured": "incomplete",
            "reference_example": w99_sticky_daily_path_dd_reference(),
            "stats_metrics": stats_metrics_document(),
            "note": (
                "W100 / w0819c: daily_path_DD, dd_duration, recovery "
                "(recovered + days), and total_ret_net (after cost) are "
                "mandatory. Passing on period_net_DD alone is forbidden. "
                "period_net_DD=0 AND daily unmeasured = incomplete. "
                "W99 sticky table is the reference example "
                "(STABLE_RESEARCH_ONLY; promote_as_main/GO=false)."
            ),
        },
        "rejected_baseline_examples": {
            "research_status": RESEARCH_STATUS_REJECTED,
            "signal_ids": list(cat.get("signal_ids") or []),
            "hyp_ids": list(cat.get("hyp_ids") or []),
            "note": (
                "S1–S5 failed this bar (or never completed multi-year cost-aware "
                "eval) and remain research_baseline_rejected — not un-rejected."
            ),
        },
        "default_entry": "run_standard_research_eval",
        "modes": list(STANDARD_EVAL_MODES),
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "research_candidate": False,
        "incomplete_checklist_blocks_research_candidate": True,
        "edge_claimed": False,
        "significance_claimed": False,
        "densify": DENSIFY,
        "note": (
            "Any new hypothesis must pass this checklist (v2) before "
            "research_candidate. Incomplete checklist CANNOT become "
            "research_candidate. Gate pass still does not mint READY, arm Mass, "
            "or claim edge. Short-window-only is insufficient. "
            "Leverage/short costs prefer date-matched jsda_tokyo_repo_rates "
            "(W78); fixed bp is disclosed fallback. "
            "Liquidity modulates tx + short spread when ADV proxy available "
            "(W79); missing liquidity disclosed, never invented. "
            "W100: daily_path_DD / dd_duration / recovery / total_ret_net "
            "are required; period_net_DD alone cannot pass. "
            "This entry does not invent new signals. S1–S5 stay rejected."
        ),
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
    """Evaluate whether checklist v2 items are complete for candidate discussion.

    Incomplete → ``research_candidate_allowed=False`` (hard). Even when complete,
    this helper never sets READY/Mass and never auto-promotes candidate status;
    harness callers still keep ``research_candidate=False``.
    """
    items: dict[str, Any] = {
        "multi_year_or_non_overlapping_long_periods": {
            "required": True,
            "present": bool(multi_year_present),
            "passed": bool(multi_year_present),
        },
        "cost_assumption_default_10bp_one_way": {
            "required": True,
            "present": bool(cost_assumption_present),
            "passed": bool(cost_assumption_present),
        },
        "leverage_short_cost_assumptions": {
            "required": True,
            "present": bool(leverage_short_complete),
            "passed": bool(leverage_short_complete),
        },
        "robustness_gate_v2_with_cost": {
            "required": True,
            "present": bool(robustness_gate_present),
            "passed": bool(robustness_gate_present),
        },
        "explicit_data_gap_disclosure": {
            "required": True,
            "present": bool(data_gap_disclosed),
            "passed": bool(data_gap_disclosed),
        },
        "risk_scenario_evaluation": {
            "required": True,
            "present": bool(risk_scenarios_passed),
            "passed": bool(risk_scenarios_passed)
            and bool(risk_scenarios_candidate_allowed),
            "scenario_passed": bool(risk_scenarios_passed),
            "scenario_candidate_allowed": bool(risk_scenarios_candidate_allowed),
        },
        "daily_path_dd": {
            "required": True,
            "present": bool(daily_path_dd_complete),
            "passed": bool(daily_path_dd_complete) and not bool(period_net_dd_only),
            "period_net_dd_only_pass_forbidden": True,
            "period_net_dd_only": bool(period_net_dd_only),
            "period_net_dd_zero_daily_unmeasured": bool(
                period_net_dd_zero_daily_unmeasured
            ),
            "note": (
                "daily_path_DD / dd_duration / recovery / total_ret_net "
                "required. period_net_DD alone cannot pass. "
                "period_net_DD=0 AND daily unmeasured = incomplete."
            ),
        },
        "pass_does_not_connect_ready_mass_go": {
            "required": True,
            "present": bool(freeze_closed),
            "passed": bool(freeze_closed),
        },
        "holding_turnover_metrics": {
            "required": bool(high_frequency_hyp and require_holding_for_hf),
            "near_required": True,
            "present": bool(holding_present),
            "passed": (
                bool(holding_present)
                if (high_frequency_hyp and require_holding_for_hf)
                else True
            ),
            "high_frequency_hyp": bool(high_frequency_hyp),
        },
    }
    missing = [
        k
        for k, v in items.items()
        if v.get("required") and not v.get("passed")
    ]
    complete = not missing and not checklist_skipped
    research_candidate_allowed = bool(complete)
    if checklist_skipped:
        research_candidate_allowed = False
        missing = list(dict.fromkeys([*missing, "checklist_skipped"]))

    reasons: list[str] = []
    if checklist_skipped:
        reasons.append("checklist_skipped → not research_candidate")
    if missing:
        reasons.append(
            "incomplete_checklist_items: " + ", ".join(missing)
            + " → not research_candidate"
        )
    if period_net_dd_only:
        reasons.append(
            "period_net_DD_only_pass_forbidden → not research_candidate"
        )
    if period_net_dd_zero_daily_unmeasured:
        reasons.append(
            "period_net_DD=0 AND daily unmeasured = incomplete evaluation"
        )
    if complete:
        reasons.append(
            "checklist_v2_complete (still not auto research_candidate; "
            "READY/Mass remain closed)"
        )

    return {
        "version": CHECKLIST_VERSION,
        "complete": bool(complete),
        "research_candidate_allowed": bool(research_candidate_allowed),
        "missing_required": missing,
        "items": items,
        "reasons": reasons,
        "ready_declared": False,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "note": (
            "Incomplete checklist v2 cannot become research_candidate. "
            "Complete still does not auto-promote or connect READY/Mass. "
            "daily_path_DD is required; period_net_DD alone cannot pass."
        ),
        "period_net_dd_only": bool(period_net_dd_only),
        "period_net_dd_zero_daily_unmeasured": bool(
            period_net_dd_zero_daily_unmeasured
        ),
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
    """Standard research evaluation checklist entry (v2 · W77 / w0816k).

    Bundles multi-year window design, base 10bp transaction cost, **explicit
    leverage/short cost assumptions**, cost-aware robustness gate v2, **risk
    scenario evaluation**, **daily_path_DD** (max DD / duration / recovery /
    after-cost total return), optional/near-required holding annotation, and
    mandatory freeze / data-gap disclosure.

    This is the **default entry for future hypotheses**. Short-window-only is
    insufficient for ``research_candidate``. **Incomplete checklist cannot
    become ``research_candidate``.**

    Hard constraints
    ----------------
    * Does **not** invent or register new signals
    * May re-run S1 / S4 paths only as **rejected baseline** dry demos
    * ``research_candidate`` is always **False** here (no auto-promotion)
    * Incomplete checklist → ``research_candidate_allowed=False``
    * Gate pass still leaves READY/Mass/Phase7 closed
    * ``dry_run=True`` (default) validates wiring without heavy R2 when
      ``mode="wiring_only"`` or when no executable periods are supplied

    Modes
    -----
    * ``wiring_only`` — design windows + costs + scenarios surface + freezes
    * ``s1_rejected_baseline`` — call :func:`run_multi_year_s1_eval` (S1 rejected)
    * ``s4_rejected_baseline`` — call :func:`run_multi_year_extra_hyp_eval` (S4)
    * ``class_hyp_offline`` — W78 multi_day_hold + macro_conditioned offline
      multi-year (local bar mirrors + jsda_repo_rates); not S1–S5; never
      auto-promotes research_candidate

    Returns a dict with ``checklist_version``, ``steps_completed``,
    ``robustness_gate``, ``cost_assumption``, ``leverage_short_costs``,
    ``risk_scenarios``, ``checklist_completeness``, ``data_gap_notes``,
    optional ``holding``, and freeze flags always closed.
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
    )
    from research.holding_metrics import (
        cost_amortization_report,
        holding_metrics_document,
        holding_metrics_report,
    )
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
        "formula": "net_one_way = gross_signed_mean_active - one_way_cost",
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
        lev_short = dict(leverage_short_cost_assumption)
        # Ensure freeze fields closed even if caller omitted them.
        lev_short.setdefault("ready_declared", False)
        lev_short.setdefault("operational_go", False)
        lev_short.setdefault("connected_to_ready", False)
        lev_short.setdefault("connected_to_mass", False)
        lev_short.setdefault("mass_research", MASS_RESEARCH)
        lev_short.setdefault("phase7", PHASE7)
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
    cost_assumption["cost_model_proof"] = STANDARD_EVAL_COST_MODEL_PROOF

    # Multi-year / non-overlapping long window design.
    if periods is None:
        designed = design_yearly_eval_windows(
            years, max_days=max_days, min_days=min_days, codes=codes
        )
    else:
        designed = [dict(p) for p in periods]
    steps.append("multi_year_or_long_period_design")
    availability = multi_year_availability_table(designed)

    # Data-gap disclosure (required).
    gap_notes: Any
    if data_gap_notes is not None:
        gap_notes = data_gap_notes
    else:
        gap_notes = {
            "source": "design_yearly_eval_windows.coverage_notes + inventory",
            "inventory": dict(DATASET_YEAR_INVENTORY_NOTES),
            "per_period": [
                {
                    "period_id": p.get("period_id"),
                    "year": p.get("year"),
                    "skip_reason": p.get("skip_reason"),
                    "s4_eligible": p.get("s4_eligible"),
                    "coverage_notes": p.get("coverage_notes"),
                }
                for p in designed
            ],
            "note": (
                "Gaps skipped / empty_allowed — never densify invent. "
                "Caller may override data_gap_notes."
            ),
        }
    steps.append("data_gap_disclosure")

    # Baseline catalog awareness (rejected demos only).
    catalog = rejected_baseline_catalog()
    baseline_demo: dict[str, Any] = {
        "mode": mode_s,
        "catalog_version": catalog.get("version"),
        "rejected_signal_ids": list(catalog.get("signal_ids") or []),
        "research_status_value": RESEARCH_STATUS_REJECTED,
        "new_signals_registered": False,
        "note": (
            "Does not invent signals. S1/S4 modes re-run rejected baselines only."
        ),
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
        baseline_demo["new_signals_registered"] = True  # class signals landed
        baseline_demo["candidate_summary"] = class_hyp_bundle.get(
            "candidate_summary"
        )
        baseline_demo["note"] = (
            "W79 class_hyp_offline: multi_day_hold + event_post + "
            "macro_conditioned + flow_demand + fundamentals_price "
            "(+ cross_section). Not S1–S5. Not simple_daily_sign. "
            "Candidate only if economic net meaningful."
        )
        # Prefer class hyp holding panel when present.
        if include_holding and md_block.get("holding") is not None:
            holding_records = None  # use precomputed below
        steps.append("class_hyp_offline_multi_year")
        if apply_robustness_gate:
            steps.append("robustness_gate_v2")
        # Override scenario_rows from class hyp risk blocks when caller did not supply.
        if scenario_rows is None:
            risk_from_macro = (class_hyp_bundle.get("macro_conditioned") or {}).get(
                "risk_scenarios"
            )
            risk_from_md = md_block.get("risk_scenarios")
            # Prefer multi_day_hold risk block for primary checklist surface.
            if isinstance(risk_from_md, Mapping) and risk_from_md.get(
                "scenario_rows"
            ):
                scenario_rows = list(risk_from_md.get("scenario_rows") or [])
            elif isinstance(risk_from_macro, Mapping) and risk_from_macro.get(
                "scenario_rows"
            ):
                scenario_rows = list(risk_from_macro.get("scenario_rows") or [])
        # Rate data is usable for macro_conditioned path (repo series).
        if not rate_data_usable:
            rate_data_usable = True
        # Feed local repo series into cost model when not already supplied.
        if repo_series_norm is None and class_hyp_bundle.get("repo_load"):
            # Reload from the same SQLite path class_hyp used (disclosure only
            # when series already embedded in cost_assumption of class hyp).
            try:
                from research.eval_loaders import load_repo_rows_from_sqlite
                from research.eval_universe import DEFAULT_SQLITE
                from research.cost_models import load_repo_rate_series_from_rows

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
            # Document-level gate surface (no period metrics → not passed).
            gate = {
                **research_robustness_gate_document(),
                "passed": False,
                "reasons": ["wiring_only_no_period_metrics"],
                "signal_id": gate_signal_id,
                "ready_declared": False,
                "operational_go": False,
                "connected_to_ready": False,
                "connected_to_mass": False,
                "mass_research": MASS_RESEARCH,
                "phase7": PHASE7,
            }
            steps.append("robustness_gate_v2_surface")
        multi_year_result = {
            "status": "wiring_only",
            "n_years_designed": len(designed),
            "periods_designed": [
                {
                    "period_id": p.get("period_id"),
                    "year": p.get("year"),
                    "period_start": p.get("period_start"),
                    "period_end": p.get("period_end"),
                    "skip_reason": p.get("skip_reason"),
                    "s4_eligible": p.get("s4_eligible"),
                }
                for p in designed
            ],
            "availability": availability,
            "note": (
                "No multi-year job executed (wiring_only or dry_run without "
                "executable period fixtures). Short-window-only remains insufficient."
            ),
        }
    elif mode_s == "s1_rejected_baseline":
        if not is_research_baseline_rejected(DEFAULT_SIGNAL_ID):
            raise EvalHarnessError(
                "s1_rejected_baseline requires catalog rejection of "
                f"{DEFAULT_SIGNAL_ID}"
            )
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
            holding = {
                "status": "annotation_only",
                "document": holding_metrics_document(),
                "cost_amortization": cost_amortization_report(one_way_cost=cost),
                "note": (
                    "Near-required holding metrics surface only — no sign panel "
                    "supplied. Pass holding_records for full run-length report. "
                    "High-frequency hyps should supply holding_records."
                ),
            }
            steps.append("holding_turnover_annotation")
            # Annotation alone does not satisfy HF near-required.
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
        "wave": CHECKLIST_WAVE,
        "label": CHECKLIST_LABEL,
        "proof": STANDARD_EVAL_PROOF,
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
        "cost_model_proof": STANDARD_EVAL_COST_MODEL_PROOF,
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
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "densify": DENSIFY,
        "local_sot": LOCAL_SOT,
        "order_execution": ORDER_EXECUTION,
        "note": (
            "Standard research eval checklist v2 (W77 + W100 daily_path_DD). "
            "Default entry for future hyps. Requires leverage/short cost "
            "assumptions + risk scenarios + daily_path_DD / dd_duration / "
            "recovery / total_ret_net. period_net_DD alone cannot pass. "
            "period_net_DD=0 AND daily unmeasured = incomplete. "
            "Incomplete checklist cannot become research_candidate. "
            "Short-window-only is insufficient. Does not invent signals. "
            "Gate pass ≠ research_candidate ≠ READY/Mass/GO. "
            "S1–S5 remain research_baseline_rejected when used as demos."
        ),
    }


# Alias for discoverability.
standard_research_eval_checklist_run = run_standard_research_eval


__all__ = [
    "APPROVED_SIGNAL_LEGS",
    "COMPLETE_21_DATASET_SET",
    "CHECKLIST_LABEL",
    "CHECKLIST_V2_INSUFFICIENT",
    "CHECKLIST_V2_NEAR_REQUIRED",
    "CHECKLIST_V2_REQUIRED",
    "CHECKLIST_VERSION",
    "CHECKLIST_VERSION_V1",
    "CHECKLIST_WAVE",
    "CONNECTED_TO_MASS_RESEARCH_LOOP",
    "COST_MODEL_PREFER_LIQUIDITY_LINKED",
    "COST_MODEL_PREFER_REPO_LINKED",
    "COST_MODEL_REQUIRE_LIQUIDITY_LINKED",
    "COST_MODEL_REQUIRE_REPO_LINKED",
    "DATASET_YEAR_INVENTORY_NOTES",
    "DEFAULT_EVAL_CODES",
    "DEFAULT_MULTIYEAR_CODES",
    "DEFAULT_MULTIYEAR_YEARS",
    "DEFAULT_SIGNAL_DATASETS",
    "DEFAULT_SIGNAL_ID",
    "DEFAULT_VOLUME_CHANGE_ABS_MIN",
    "DENSIFY",
    "EvalHarnessError",
    "FEATURE_STATUS_PINS",
    "HARNESS_SMOKE_CODES",
    "HARNESS_VERSION",
    "LOCAL_SOT",
    "MASS_RESEARCH",
    "MASS_RESEARCH_ENV_ARMING_SWITCHES",
    "MULTI_PERIOD_VERSION",
    "MULTI_SIGNAL_DATASETS",
    "MULTI_YEAR_LABEL",
    "MULTI_YEAR_VERSION",
    "MultidaySignalEval",
    "NEXTDAY_RESEARCH_LABEL",
    "ORDER_EXECUTION",
    "PHASE7",
    "PHASE7_ENV_ARMING_SWITCHES",
    "PIPELINE",
    "READY_DECLARED",
    "RESEARCH_WALK_FORWARD_LABEL",
    "SIGNAL_CANDIDATE_ONLY",
    "STANDARD_EVAL_COST_MODEL_PROOF",
    "STANDARD_EVAL_COST_MODEL_PROOF_REPO_LINKED",
    "STANDARD_EVAL_DAILY_PATH_DD_PROOF",
    "STANDARD_EVAL_MODES",
    "STANDARD_EVAL_PROOF",
    "STANDARD_EVAL_PROOF_V1",
    "SingleShotJobError",
    "WALK_FORWARD_VERSION",
    "assert_harness_closed",
    "assert_mass_and_phase7_off",
    "design_yearly_eval_windows",
    "evaluate_checklist_v2_completeness",
    "evaluate_research_robustness_gate",
    "execute_extra_hyp_signals_compare",
    "execute_multiday_signal_eval",
    "freeze_status",
    "harness_freeze_status",
    "multi_year_availability_table",
    "period_rows_from_cross_table",
    "require_approved_signal_legs",
    "require_complete_21_only",
    "require_harness_datasets",
    "research_robustness_gate_document",
    "run_full_pipeline",
    "run_multi_period_multisignal_compare",
    "run_multi_year_extra_hyp_eval",
    "run_multi_year_s1_eval",
    "run_multiday_signal_eval",
    "run_multisignal_compare",
    "run_nextday_return_eval",
    "run_research_walk_forward_multisignal",
    "run_standard_research_eval",
    "split_asof_days_walk_forward",
    "standard_research_eval_checklist_document",
    "standard_research_eval_checklist_run",
]
