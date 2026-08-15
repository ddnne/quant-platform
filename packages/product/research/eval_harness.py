"""Reusable single-shot research eval harness (Mass OFF / Phase7 OFF / READY OFF).

Stable public pipeline (W56 / w0815aw_g2 · T5):

    signal (approved legs only)
      → multiday as_of batch
      → next_day_return eval
      → R2 ``batch_summary.json``

This module is the **preferred entry** for that pipeline. Implementation lives
in :mod:`research.single_shot_job` (CF D1 tip extract, tip FeatureContext,
signal compute, R2 put); this harness freezes the public surface, input
guards, and freeze constants.

Inputs (T6)
-----------

* residual **COMPLETE 21** dataset ids only
* permanent DEFER ids hard-reject via ``data_contracts.permanent_defer``
* signal feature legs must be registry-**approved**
  (default: ``topix_relative_1d`` · ``is_trading_day`` · ``volume_change_1d``)

Hard constraints (T7)
---------------------

* does **not** import ``agents.mass_research`` / mass loop
* does **not** mint READY / ``VerifiedResearchReadiness``
* does **not** emit order intents / call paper execution
* does **not** densify
* Mass = NO-GO · Phase7 = OFF · READY not declared

Label when next-day returns are attached:
**小サンプル / 研究用・未宣言** (no significance / no edge claim).
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from features.minimal_signal import (
    CANDIDATE_ONLY as SIGNAL_CANDIDATE_ONLY,
    DEFAULT_FEATURE_IDS as APPROVED_SIGNAL_LEGS,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    DEFAULT_VOLUME_SIGN_ABS_MIN,
    FEATURE_STATUS_PINS,
    MULTI_SIGNAL_DATASETS,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
    SIGNAL_VERSION as DEFAULT_SIGNAL_VERSION,
    signal_definition,
)
from features.registry import get as get_feature
from research.robustness_gate import (
    DEFAULT_ONE_WAY_COST,
    annotate_period_rows_with_cost,
    evaluate_research_robustness_gate,
    period_rows_from_cross_table,
    research_robustness_gate_document,
    walk_forward_gross_from_compare,
)
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    COMPLETE_21_DATASET_SET,
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    MASS_RESEARCH_STATUS,
    MultidaySignalEval,
    NEXTDAY_LOOKAHEAD_POLICY,
    NEXTDAY_RESEARCH_LABEL,
    PHASE7_ENV_ARMING_SWITCHES,
    PHASE7_STATUS,
    READY_DECLARED,
    READY_PUBLICATION_STATUS,
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    RESEARCH_ONE_WAY_COST,
    R2PutFn,
    SingleShotJobError,
    assert_mass_and_phase7_off,
    attach_next_day_returns,
    build_equity_close_index,
    design_artifact_paths,
    discover_tip_trading_days,
    execute_extra_hyp_signals_compare,
    execute_multiday_multisignal_compare,
    execute_multiday_nextday_return_eval,
    execute_multiday_signal_eval,
    freeze_status,
    next_trading_day_map,
    require_complete_21_only,
    session_close_as_of,
    summarize_nextday_by_sign,
    summarize_signal_day,
)

# ---------------------------------------------------------------------------
# Freeze constants (T7: tests assert these remain closed — do not arm)
# ---------------------------------------------------------------------------

HARNESS_VERSION: str = "research-eval-harness/v1"
PIPELINE: tuple[str, ...] = (
    "approved_leg_signal",
    "multiday_as_of",
    "next_day_return_eval",
    "r2_batch_summary",
)

# Re-export freeze surface under harness names (same closed values).
MASS_RESEARCH: str = MASS_RESEARCH_STATUS  # "NO-GO"
PHASE7: str = PHASE7_STATUS  # "OFF"
READY_PUBLICATION: str = READY_PUBLICATION_STATUS  # "OFF"
ORDER_EXECUTION: bool = False
CONNECTED_TO_MASS_RESEARCH_LOOP: bool = False
DENSIFY: bool = False
LOCAL_SOT: bool = False

# Default codes for tip multiday / nextday batches (liquid TSE probes).
DEFAULT_EVAL_CODES: tuple[str, ...] = ("13010", "72030", "67580")


class EvalHarnessError(SingleShotJobError):
    """Invalid eval-harness input (datasets / feature legs / freeze)."""


def require_approved_signal_legs(
    feature_ids: Sequence[str] | None = None,
    *,
    context: str = "eval harness signal legs",
) -> tuple[str, ...]:
    """Return ordered feature ids only when every leg is registry-approved.

    Fail-closed when:

    * any id is unknown to the feature registry
    * any id has registry status other than ``approved``
    * the list is empty

    Default legs are the three COMPLETE-21 signal legs used by
    ``c21_topix_relative_sign`` (all approved after W53).
    """
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
    """COMPLETE 21 only; permanent DEFER hard-reject.

    Default = :data:`DEFAULT_SIGNAL_DATASETS` (bars + calendar + topix).
    """
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

    Guards COMPLETE-21 datasets + approved signal legs before any tip extract.
    Does **not** mint READY, open mass research, execute orders, or densify.

    ``history_source``:
        * ``"d1_tip"`` (default) — CF D1 hot tip extract
        * ``"r2"`` — R2 structured history bridge (keys/fixtures required)
    """
    assert_harness_closed()
    require_approved_signal_legs(context="multiday signal eval legs")
    require_harness_datasets(context="multiday signal eval datasets")
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)
    )
    return execute_multiday_signal_eval(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=selected,
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
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 10,
    min_days: int = 5,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    volume_change_abs_min: float | None = DEFAULT_VOLUME_CHANGE_ABS_MIN,
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
    """Full pipeline: approved-leg signal → multiday → next-day return → R2.

    Research only (小サンプル / 研究用・未宣言). Feature as_of = T session
    close; return evaluation_as_of = T+1 session close (see
    :data:`NEXTDAY_LOOKAHEAD_POLICY`). No significance / no edge claim.

    Optional ``history_source="r2"`` uses the R2 FeatureContext bridge
    (see :mod:`research.r2_feature_context`). Default remains D1 tip.
    """
    assert_harness_closed()
    require_approved_signal_legs(context="nextday return eval legs")
    require_harness_datasets(context="nextday return eval datasets")
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)
    )
    return execute_multiday_nextday_return_eval(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=selected,
        as_of_days=as_of_days,
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
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
    )


# Preferred alias for the full stable pipeline name used in wave docs.
run_full_pipeline = run_nextday_return_eval


# ---------------------------------------------------------------------------
# W61 research walk-forward + multi-period compare (not READY / not Mass)
# ---------------------------------------------------------------------------

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
    """Chronological train/test split of as_of days (research-only).

    * No threshold retuning — callers evaluate the **same** fixed signal
      definitions on train and test folds.
    * Not an operational walk-forward; no READY / Mass connection.
    * Fails closed if folds would be shorter than ``min_*_days``.
    """
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
        "ready_declared": False,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "operational_go": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "note": (
            "Research chronological holdout only. Same fixed S1/S2/S3 (or S1) "
            "definitions are evaluated on both folds; thresholds are not fit "
            "on train. Not READY. Not mass research."
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
    """S1/S2/S3 multi-signal compare via single_shot (research-only).

    Freeze closed. Optional ``history_source="r2"`` for long windows.
    """
    assert_harness_closed()
    require_complete_21_only(
        MULTI_SIGNAL_DATASETS, context="harness multisignal datasets"
    )
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)
    )
    return execute_multiday_multisignal_compare(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=selected,
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
    """Research walk-forward: fixed S1/S2/S3 on chronological train then test.

    Thresholds are **not** optimized on train (definition freeze). Both folds
    use the same volume_sign_abs_min. Labels remain 研究用・未宣言.
    """
    assert_harness_closed()
    jid = str(job_id).strip()
    # Full window once to discover as_of grid when caller omits it.
    full = execute_multiday_multisignal_compare(
        period_start=period_start,
        period_end=period_end,
        job_id=f"{jid}-full",
        codes=codes,
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
    day_list = list(full.as_of_days)
    split = split_asof_days_walk_forward(
        day_list,
        train_fraction=train_fraction,
        min_train_days=min_train_days,
        min_test_days=min_test_days,
    )
    train_ex = execute_multiday_multisignal_compare(
        period_start=period_start,
        period_end=period_end,
        job_id=f"{jid}-train",
        codes=list(full.codes),
        as_of_days=split["train_as_of_days"],
        max_days=len(split["train_as_of_days"]),
        min_days=min_train_days,
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
    test_ex = execute_multiday_multisignal_compare(
        period_start=period_start,
        period_end=period_end,
        job_id=f"{jid}-test",
        codes=list(full.codes),
        as_of_days=split["test_as_of_days"],
        max_days=len(split["test_as_of_days"]),
        min_days=min_test_days,
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
        "full": {
            "n_days": full.n_days,
            "as_of_days": list(full.as_of_days),
            "compare_table": _compact_compare_rows(full.batch_summary),
            "batch_summary_r2_key": full.batch_summary_r2_key,
        },
        "train": {
            "n_days": train_ex.n_days,
            "as_of_days": list(train_ex.as_of_days),
            "compare_table": _compact_compare_rows(train_ex.batch_summary),
            "batch_summary_r2_key": train_ex.batch_summary_r2_key,
        },
        "test": {
            "n_days": test_ex.n_days,
            "as_of_days": list(test_ex.as_of_days),
            "compare_table": _compact_compare_rows(test_ex.batch_summary),
            "batch_summary_r2_key": test_ex.batch_summary_r2_key,
        },
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "local_sot": False,
        "note": (
            "Research walk-forward with fixed signal definitions on both folds. "
            "No threshold search on train. Not READY. Not mass. No orders."
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
    """Run fixed S1/S2/S3 on multiple non-overlapping research periods.

    Each period mapping requires ``period_id``, ``period_start``, ``period_end``.
    Optional per-period keys: ``as_of_days``, ``r2_local_paths_by_dataset``,
    ``r2_object_keys_by_dataset``, ``r2_raw_lines_by_dataset``,
    ``r2_allow_empty_datasets``, ``skip_reason`` (when set, period is skipped).

    Gaps / skips are recorded honestly — never invent data.
    """
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
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "local_sot": False,
        "note": (
            "Multi-period fixed-definition multi-signal research compare. "
            "Skips documented when data missing. Not READY. No densify invent."
        ),
    }


# ---------------------------------------------------------------------------
# W63 multi-year research evaluation (year-split · not READY / not Mass)
# ---------------------------------------------------------------------------

MULTI_YEAR_VERSION: str = "research-multi-year-eval/v1"
MULTI_YEAR_LABEL: str = (
    "小サンプル / 研究用・複数年評価・未宣言 "
    "(年分割・fail-one-year-ok・pass≠READY/Mass)"
)

# Fixed liquid TSE probe universe (30 codes) shared with W60/W61 long evals.
# Non-contiguous yearly windows re-use the same codes for fairness.
DEFAULT_MULTIYEAR_CODES: tuple[str, ...] = (
    "13010",
    "72030",
    "67580",
    "99840",
    "83060",
    "68610",
    "65010",
    "40630",
    "80350",
    "94320",
    "45020",
    "63670",
    "60980",
    "79740",
    "69810",
    "45680",
    "80010",
    "80020",
    "80580",
    "94330",
    "29140",
    "33820",
    "46610",
    "49010",
    "51080",
    "54010",
    "57130",
    "62730",
    "63010",
    "65030",
)

# Preferred non-contiguous yearly sample (inventory 2008–2026; gaps OK).
DEFAULT_MULTIYEAR_YEARS: tuple[int, ...] = (2015, 2017, 2019, 2021, 2023, 2025)

# Honest inventory defaults (research plane; do not invent densify fills).
# topix JSONL gap 2024–2025 → archive; calendar tip JSONL 2026 only → archive;
# margin JSONL gap year 2024 empty_allowed.
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
    """Design non-contiguous yearly (or half-year) research eval windows.

    Each returned period dict is ready for :func:`run_multi_year_s1_eval` /
    :func:`run_multi_period_multisignal_compare` (``period_id``,
    ``period_start``, ``period_end``, day bounds, codes, coverage notes).

    ``window``:
        * ``"q4"`` — Sep 1 … Dec 29 of each year (default; ~60–80 sessions)
        * ``"h1"`` — Jan 6 … Jun 30
        * ``"h2"`` — Jul 1 … Dec 29
        * ``"full"`` — Jan 6 … Dec 29 (caller should lower max_days)

    Does **not** invent data. Gaps are recorded under ``coverage_notes``;
    callers may set ``skip_reason`` when a year has no usable bars.
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
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_MULTIYEAR_CODES)
    )
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
    """Year-split S1 (topix_relative_sign) research eval; fail-one-year safe.

    Each year is independent: an exception / skip on one year does **not**
    abort the batch. Results table records ``ok`` / ``skipped`` / ``error``
    per year. Optional robustness gate over ok years (pass ≠ READY/Mass).
    """
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

    selected_default = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_MULTIYEAR_CODES)
    )

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
            ex = execute_multiday_nextday_return_eval(
                period_start=start,
                period_end=end,
                job_id=f"{job_id_prefix}-{pid}",
                codes=year_codes,
                as_of_days=p.get("as_of_days"),
                max_days=int(p.get("max_days") or max_days),
                min_days=int(p.get("min_days") or min_days),
                feature_row_limit=feature_row_limit,
                volume_change_abs_min=volume_change_abs_min,
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
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "local_sot": False,
        "year_split": True,
        "fail_one_year_safe": True,
        "note": (
            "Multi-year S1 research eval with independent per-year jobs. "
            "Error/skip on one year does not kill the batch. "
            "Cost-aware robustness_gate (default). "
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
    """Year-split S4 (margin) / S5 research hyp eval; skip years without data.

    Years with ``s4_eligible=False`` or ``skip_reason`` are recorded as
    skipped (honest empty) — never invent margin rows for gap years (2024).
    """
    assert_harness_closed()
    if periods is None:
        period_list = design_yearly_eval_windows(
            years, max_days=max_days, min_days=min_days, codes=codes
        )
    else:
        period_list = [dict(p) for p in periods]
    if not period_list:
        raise EvalHarnessError("multi-year extra-hyp requires at least one period")

    selected_default = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_MULTIYEAR_CODES)
    )
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
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": False,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "local_sot": False,
        "year_split": True,
        "fail_one_year_safe": True,
        "note": (
            "Multi-year S4/S5 research eval. Gap years skipped honestly "
            "(no densify invent). Cost-aware gate (default). "
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
# Standard research eval checklist entry (W66 / w0815bg)
# ---------------------------------------------------------------------------

CHECKLIST_VERSION: str = "standard-research-eval-checklist/v1"
CHECKLIST_WAVE: str = "W66 / w0815bg"
CHECKLIST_LABEL: str = (
    "標準研究評価チェックリスト・未宣言 "
    "(合格≠research_candidate / READY未接続 / Mass NO-GO / 運用GOではない)"
)
STANDARD_EVAL_PROOF: str = (
    "docs/proof/w0815bg_w66_standard_research_eval_checklist_20260815.md"
)
# Modes that only re-run existing rejected baselines — never mint new signals.
STANDARD_EVAL_MODES: tuple[str, ...] = (
    "wiring_only",
    "s1_rejected_baseline",
    "s4_rejected_baseline",
)


def standard_research_eval_checklist_document() -> dict[str, Any]:
    """Public document for the standard research evaluation checklist."""
    from research.baseline_catalog import (
        RESEARCH_STATUS_REJECTED,
        rejected_baseline_catalog,
    )
    from research.holding_metrics import holding_metrics_document
    from research.robustness_gate import research_robustness_gate_document

    cat = rejected_baseline_catalog()
    return {
        "version": CHECKLIST_VERSION,
        "wave": CHECKLIST_WAVE,
        "label": CHECKLIST_LABEL,
        "proof": STANDARD_EVAL_PROOF,
        "required": [
            "multi_year_or_non_overlapping_long_periods",
            "cost_assumption_default_10bp_one_way",
            "robustness_gate_v2_with_cost",
            "explicit_data_gap_disclosure",
            "pass_does_not_connect_ready_mass_go",
        ],
        "recommended": [
            "holding_turnover_metrics",
        ],
        "insufficient": [
            "short_window_only",
            "gross_only_without_cost_gate",
            "skipped_checklist",
        ],
        "gate": research_robustness_gate_document(),
        "holding_surface": holding_metrics_document(),
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
        "edge_claimed": False,
        "significance_claimed": False,
        "densify": DENSIFY,
        "note": (
            "Any new hypothesis must pass this checklist before research_candidate. "
            "Results that skip the checklist are NOT research_candidate. "
            "Gate pass still does not mint READY, arm Mass, or claim edge. "
            "Short-window-only is insufficient. "
            "This entry does not invent new signals."
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
    d1_execute: D1ExecuteFn | None = None,
    r2_put: R2PutFn | None = None,
    staging_dir: str | Path | None = None,
    wrangler: str | Path | None = None,
    wrangler_config: str | Path | None = None,
    history_source: str = "r2",
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> dict[str, Any]:
    """Standard research evaluation checklist entry (W66).

    Bundles multi-year window design, cost-aware robustness gate v2, optional
    holding annotation, and mandatory freeze / data-gap disclosure.

    This is the **default entry for future hypotheses**. Short-window-only is
    insufficient for ``research_candidate``.

    Hard constraints
    ----------------
    * Does **not** invent or register new signals
    * May re-run S1 / S4 paths only as **rejected baseline** dry demos
    * ``research_candidate`` is always **False** here (no auto-promotion)
    * Gate pass still leaves READY/Mass/Phase7 closed
    * ``dry_run=True`` (default) validates wiring without heavy R2 when
      ``mode="wiring_only"`` or when no executable periods are supplied

    Modes
    -----
    * ``wiring_only`` — design windows + cost + gate surface + freezes (no R2)
    * ``s1_rejected_baseline`` — call :func:`run_multi_year_s1_eval` (S1 catalog rejected)
    * ``s4_rejected_baseline`` — call :func:`run_multi_year_extra_hyp_eval` (S4 rejected)

    Returns a dict with ``checklist_version``, ``steps_completed``,
    ``robustness_gate``, ``cost_assumption``, ``data_gap_notes``, optional
    ``holding``, and freeze flags always closed.
    """
    from research.baseline_catalog import (
        RESEARCH_STATUS_REJECTED,
        is_research_baseline_rejected,
        rejected_baseline_catalog,
    )
    from research.holding_metrics import (
        cost_amortization_report,
        holding_metrics_document,
        holding_metrics_report,
    )

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

    if mode_s == "wiring_only" or (dry_run and not executable and period_rows_for_gate is None):
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
        baseline_demo["still_rejected"] = is_research_baseline_rejected(DEFAULT_SIGNAL_ID)
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

    # Holding / turnover (recommended).
    holding: dict[str, Any] | None = None
    if include_holding:
        if holding_records is not None:
            holding = holding_metrics_report(
                holding_records,
                one_way_cost=cost,
            )
            steps.append("holding_turnover_metrics")
        else:
            holding = {
                "status": "annotation_only",
                "document": holding_metrics_document(),
                "cost_amortization": cost_amortization_report(one_way_cost=cost),
                "note": (
                    "Recommended holding metrics surface only — no sign panel "
                    "supplied. Pass holding_records for full run-length report."
                ),
            }
            steps.append("holding_turnover_annotation")

    # Pass does NOT connect READY / Mass / GO (always restate).
    steps.append("freeze_ready_mass_phase7_closed")

    gate_passed = bool(gate.get("passed")) if isinstance(gate, Mapping) else False

    return {
        "checklist_version": CHECKLIST_VERSION,
        "version": CHECKLIST_VERSION,
        "wave": CHECKLIST_WAVE,
        "label": CHECKLIST_LABEL,
        "proof": STANDARD_EVAL_PROOF,
        "mode": mode_s,
        "dry_run": bool(dry_run),
        "job_id_prefix": job_id_prefix,
        "steps_completed": list(steps),
        "designed_periods": designed,
        "availability": availability,
        "multi_year": multi_year_result,
        "robustness_gate": gate,
        "cost_assumption": cost_assumption,
        "data_gap_notes": gap_notes,
        "holding": holding,
        "baseline_demo": baseline_demo,
        "new_signals_registered": False,
        "research_candidate": False,
        "checklist_skipped": False,
        "gate_passed": gate_passed,
        "gate_pass_implies_ready": False,
        "gate_pass_implies_mass": False,
        "gate_pass_implies_research_candidate": False,
        "short_window_only_sufficient": False,
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
            "Standard research eval checklist (W66). Default entry for future hyps. "
            "Short-window-only is insufficient. Does not invent signals. "
            "Gate pass ≠ research_candidate ≠ READY/Mass/GO. "
            "S1–S5 remain research_baseline_rejected when used as demos."
        ),
    }


# Alias for discoverability.
standard_research_eval_checklist_run = run_standard_research_eval


__all__ = [
    "APPROVED_SIGNAL_LEGS",
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "CHECKLIST_LABEL",
    "CHECKLIST_VERSION",
    "CHECKLIST_WAVE",
    "CONNECTED_TO_MASS_RESEARCH_LOOP",
    "DATASET_YEAR_INVENTORY_NOTES",
    "DEFAULT_EVAL_CODES",
    "DEFAULT_MULTIYEAR_CODES",
    "DEFAULT_MULTIYEAR_YEARS",
    "DEFAULT_SIGNAL_DATASETS",
    "DEFAULT_SIGNAL_ID",
    "DEFAULT_SIGNAL_VERSION",
    "DEFAULT_VOLUME_CHANGE_ABS_MIN",
    "DENSIFY",
    "FEATURE_STATUS_PINS",
    "HARNESS_VERSION",
    "LOCAL_SOT",
    "MASS_RESEARCH",
    "MASS_RESEARCH_ENV_ARMING_SWITCHES",
    "MASS_RESEARCH_STATUS",
    "MULTI_PERIOD_VERSION",
    "MULTI_SIGNAL_DATASETS",
    "MULTI_YEAR_LABEL",
    "MULTI_YEAR_VERSION",
    "MultidaySignalEval",
    "NEXTDAY_LOOKAHEAD_POLICY",
    "NEXTDAY_RESEARCH_LABEL",
    "ORDER_EXECUTION",
    "PERMANENT_DEFER_DATASETS",
    "PHASE7",
    "PHASE7_ENV_ARMING_SWITCHES",
    "PHASE7_STATUS",
    "PIPELINE",
    "PermanentDeferHistoryError",
    "READY_DECLARED",
    "READY_PUBLICATION",
    "READY_PUBLICATION_STATUS",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "RESEARCH_WALK_FORWARD_LABEL",
    "SIGNAL_CANDIDATE_ONLY",
    "STANDARD_EVAL_MODES",
    "STANDARD_EVAL_PROOF",
    "WALK_FORWARD_VERSION",
    "EvalHarnessError",
    "SingleShotJobError",
    "assert_harness_closed",
    "assert_mass_and_phase7_off",
    "attach_next_day_returns",
    "build_equity_close_index",
    "design_artifact_paths",
    "design_yearly_eval_windows",
    "discover_tip_trading_days",
    "execute_multiday_nextday_return_eval",
    "execute_multiday_signal_eval",
    "freeze_status",
    "harness_freeze_status",
    "multi_year_availability_table",
    "next_trading_day_map",
    "require_approved_signal_legs",
    "require_complete_21_only",
    "require_harness_datasets",
    "run_full_pipeline",
    "run_multi_period_multisignal_compare",
    "run_multi_year_extra_hyp_eval",
    "run_multi_year_s1_eval",
    "run_multiday_signal_eval",
    "run_multisignal_compare",
    "run_nextday_return_eval",
    "run_research_walk_forward_multisignal",
    "run_standard_research_eval",
    "session_close_as_of",
    "signal_definition",
    "split_asof_days_walk_forward",
    "standard_research_eval_checklist_document",
    "standard_research_eval_checklist_run",
    "summarize_nextday_by_sign",
    "summarize_signal_day",
    "evaluate_research_robustness_gate",
    "period_rows_from_cross_table",
    "research_robustness_gate_document",
    "walk_forward_gross_from_compare",
    "execute_extra_hyp_signals_compare",
]
