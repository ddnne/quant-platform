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


__all__ = [
    "APPROVED_SIGNAL_LEGS",
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "CONNECTED_TO_MASS_RESEARCH_LOOP",
    "DEFAULT_EVAL_CODES",
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
    "WALK_FORWARD_VERSION",
    "EvalHarnessError",
    "SingleShotJobError",
    "assert_harness_closed",
    "assert_mass_and_phase7_off",
    "attach_next_day_returns",
    "build_equity_close_index",
    "design_artifact_paths",
    "discover_tip_trading_days",
    "execute_multiday_nextday_return_eval",
    "execute_multiday_signal_eval",
    "freeze_status",
    "harness_freeze_status",
    "next_trading_day_map",
    "require_approved_signal_legs",
    "require_complete_21_only",
    "require_harness_datasets",
    "run_full_pipeline",
    "run_multi_period_multisignal_compare",
    "run_multiday_signal_eval",
    "run_multisignal_compare",
    "run_nextday_return_eval",
    "run_research_walk_forward_multisignal",
    "session_close_as_of",
    "signal_definition",
    "split_asof_days_walk_forward",
    "summarize_nextday_by_sign",
    "summarize_signal_day",
]
