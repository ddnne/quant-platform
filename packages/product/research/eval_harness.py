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
from typing import Any, Mapping, Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from features.minimal_signal import (
    CANDIDATE_ONLY as SIGNAL_CANDIDATE_ONLY,
    DEFAULT_FEATURE_IDS as APPROVED_SIGNAL_LEGS,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    FEATURE_STATUS_PINS,
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
    R2PutFn,
    SingleShotJobError,
    assert_mass_and_phase7_off,
    attach_next_day_returns,
    build_equity_close_index,
    design_artifact_paths,
    discover_tip_trading_days,
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
) -> MultidaySignalEval:
    """Multiday approved-leg signal batch → R2 ``batch_summary.json``.

    Guards COMPLETE-21 datasets + approved signal legs before any tip extract.
    Does **not** mint READY, open mass research, execute orders, or densify.
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
) -> MultidaySignalEval:
    """Full pipeline: approved-leg signal → multiday → next-day return → R2.

    Research only (小サンプル / 研究用・未宣言). Feature as_of = T session
    close; return evaluation_as_of = T+1 session close (see
    :data:`NEXTDAY_LOOKAHEAD_POLICY`). No significance / no edge claim.
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
    )


# Preferred alias for the full stable pipeline name used in wave docs.
run_full_pipeline = run_nextday_return_eval


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
    "SIGNAL_CANDIDATE_ONLY",
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
    "run_multiday_signal_eval",
    "run_nextday_return_eval",
    "session_close_as_of",
    "signal_definition",
    "summarize_nextday_by_sign",
    "summarize_signal_day",
]
