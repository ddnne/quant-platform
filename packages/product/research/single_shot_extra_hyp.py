"""S4/S5 extra-hyp multi-day compare (Mass OFF / READY not declared).

:func:`execute_extra_hyp_signals_compare` lives here. Cost attach /
:func:`execute_multiday_multisignal_compare` stay in
:mod:`research.single_shot_compare`. Public names are re-exported from
:mod:`research.single_shot_compare` and :mod:`research.single_shot_job`.

Fail-closed: COMPLETE 21 only, permanent DEFER 5 hard-reject, Mass OFF,
READY not declared. No densify, no orders. Outputs remain
**小サンプル / 研究用・未宣言** (no significance / no edge claim).
Cost label: **仮定に依存・研究用・運用GOではない**.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    DEFAULT_SHORT_RATIO_SECTION,
    EXTRA_HYP_DATASETS,
    EXTRA_HYP_FEATURE_IDS,
    SIGNAL_ID_MARGIN_CHANGE,
    SIGNAL_ID_SHORT_RATIO_DELTA,
    compute_margin_sign_from_feature_observations,
    compute_short_delta_from_feature_observations,
    extra_hyp_definitions,
)
from research.freezes import (
    MASS_RESEARCH as MASS_RESEARCH_STATUS,
    PHASE7 as PHASE7_STATUS,
    READY_DECLARED,
)
from research.single_shot_compare import (
    RESEARCH_COST_LABEL,
    RESEARCH_ONE_WAY_COST,
    _compare_row_from_signal_body,
    _summarize_one_signal_batch,
    attach_research_cost_fields,
    summarize_research_cost,
)
from research.single_shot_eval import (
    MultidaySignalEval,
    NEXTDAY_LOOKAHEAD_POLICY,
    NEXTDAY_RESEARCH_LABEL,
    _cap_as_of_days,
    _nextday_setup,
    attach_next_day_returns,
    session_close_as_of,
    summarize_nextday_by_sign,
    summarize_signal_day,
)
from research.single_shot_job import (
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    RESEARCH_ARTIFACT_BUCKET,
    R2PutFn,
    SingleShotJobError,
    _load_history_feature_rows,
    _now_utc,
    _put_research_json,
    _require_job_window,
    _select_codes,
    assert_mass_and_phase7_off,
    design_artifact_paths,
    require_complete_21_only,
)
from research.single_shot_tip import compute_tip_candidate_features


def execute_extra_hyp_signals_compare(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815bc-g1-extra-hyp",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 40,
    min_days: int = 10,
    feature_row_limit: int = DEFAULT_FEATURE_ROW_LIMIT,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
    short_ratio_section: str = DEFAULT_SHORT_RATIO_SECTION,
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
) -> MultidaySignalEval:
    """S4/S5 research hypotheses (not S1 rehash) multi-day compare.

    S4: sign(margin_interest_change_1d)
    S5: sign(Δ short_ratio_level) for ``short_ratio_section``, broadcast.

    Empty datasets → honest null signals. Not READY / Mass OFF.
    """
    assert_mass_and_phase7_off()
    start, end, jid = _require_job_window(period_start, period_end, job_id)
    _ = min_days

    dataset_ids = require_complete_21_only(
        EXTRA_HYP_DATASETS, context="extra hyp datasets"
    )
    selected_codes = _select_codes(codes)
    section = str(short_ratio_section).strip() or DEFAULT_SHORT_RATIO_SECTION
    _fids: list[str] = []
    for x in list(EXTRA_HYP_FEATURE_IDS) + ["is_trading_day"]:
        if x not in _fids:
            _fids.append(x)
    feature_ids = tuple(_fids)
    definitions = {
        d["signal_id"]: d for d in extra_hyp_definitions(section=section)
    }

    hist_src, tip_feature_extract = _load_history_feature_rows(
        dataset_ids,
        period_start=start,
        period_end=end,
        codes=selected_codes,
        feature_row_limit=feature_row_limit,
        history_source=history_source,
        d1_execute=d1_execute,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        r2_allow_empty_datasets=r2_allow_empty_datasets
        or (
            "markets_margin_interest",
            "markets_short_ratio",
        ),
        context="extra hyp feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}

    full_trading_days, next_map, close_index = _nextday_setup(
        rows_by_ds, period_start=start, period_end=end
    )
    day_list = _cap_as_of_days(as_of_days, full_trading_days, max_days)
    if not day_list:
        raise SingleShotJobError(
            f"extra hyp compare: no trading days in {start}..{end}"
        )

    paths = design_artifact_paths(jid)
    prefix = str(paths["prefix"])
    batch_key = f"{prefix}/batch_summary.json"
    executed_at = _now_utc()

    signal_day_rows: dict[str, list[list[dict[str, Any]]]] = {
        SIGNAL_ID_MARGIN_CHANGE: [],
        SIGNAL_ID_SHORT_RATIO_DELTA: [],
    }
    day_results: list[dict[str, Any]] = []
    prev_short: float | None = None

    for d in day_list:
        as_of = session_close_as_of(d)
        feature_payload = compute_tip_candidate_features(
            rows_by_ds,
            as_of=as_of,
            feature_ids=feature_ids,
            codes=selected_codes,
            dates=[d],
            sections=[section],
        )
        obs = feature_payload.get("observations") or []
        s4 = compute_margin_sign_from_feature_observations(
            obs, as_of=as_of, codes=selected_codes
        )
        s5 = compute_short_delta_from_feature_observations(
            obs,
            as_of=as_of,
            prev_short_ratio_level=prev_short,
            codes=selected_codes,
            section=section,
        )
        # update prev short from observations
        for o in obs:
            if str(o.get("feature_id") or "") == "short_ratio_level" and o.get(
                "value"
            ) is not None:
                try:
                    prev_short = float(o["value"])
                except (TypeError, ValueError):
                    pass
                break

        nxt = next_map.get(d)
        eval_as_of = session_close_as_of(nxt) if nxt else None
        per_signal_day: dict[str, Any] = {}
        for sid, core in (
            (SIGNAL_ID_MARGIN_CHANGE, s4),
            (SIGNAL_ID_SHORT_RATIO_DELTA, s5),
        ):
            aligned = attach_next_day_returns(
                list(core.get("observations") or []),
                signal_date=d,
                next_date=nxt,
                close_index=close_index,
                evaluation_as_of=eval_as_of,
                feature_as_of=as_of,
            )
            costed = attach_research_cost_fields(aligned, one_way_cost=one_way_cost)
            signal_day_rows[sid].append(costed)
            day_summary = summarize_signal_day(
                {**core, "observations": costed}, as_of=as_of
            )
            day_summary["nextday_day_summary"] = summarize_nextday_by_sign(costed)
            day_summary["research_cost_day"] = summarize_research_cost(
                costed, one_way_cost=one_way_cost
            )
            day_summary["observations"] = costed
            day_summary["next_day_date"] = nxt
            day_summary["evaluation_as_of"] = eval_as_of
            day_summary["feature_as_of"] = as_of
            day_summary["definition"] = definitions.get(sid)
            per_signal_day[sid] = day_summary

        day_results.append(
            {
                "date": d,
                "as_of": as_of,
                "signals": per_signal_day,
                "codes": list(selected_codes),
                "label": NEXTDAY_RESEARCH_LABEL,
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
            }
        )

    by_signal: dict[str, Any] = {}
    for sid in (SIGNAL_ID_MARGIN_CHANGE, SIGNAL_ID_SHORT_RATIO_DELTA):
        by_signal[sid] = _summarize_one_signal_batch(
            signal_day_rows[sid],
            signal_id=sid,
            definition=definitions.get(sid) or {},
            one_way_cost=one_way_cost,
        )

    compare_rows = [
        _compare_row_from_signal_body(sid, by_signal[sid])
        for sid in (SIGNAL_ID_MARGIN_CHANGE, SIGNAL_ID_SHORT_RATIO_DELTA)
    ]

    batch_summary: dict[str, Any] = {
        "version": "extra-hyp-multisignal-nextday-batch/v1",
        "job_id": jid,
        "pipeline": "extra_hyp_signals_compare",
        "signal_ids": [SIGNAL_ID_MARGIN_CHANGE, SIGNAL_ID_SHORT_RATIO_DELTA],
        "definitions": extra_hyp_definitions(section=section),
        "feature_ids": list(feature_ids),
        "short_ratio_section": section,
        "dataset_ids": list(dataset_ids),
        "period_start": start,
        "period_end": end,
        "codes": list(selected_codes),
        "n_codes": len(selected_codes),
        "n_days": len(day_results),
        "as_of_days": [d.get("date") for d in day_results],
        "history_source": hist_src,
        "tip_plane": (
            tip_feature_extract.get("plane")
            if hist_src == "r2"
            else "D1_hot_tip"
        ),
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "by_signal": by_signal,
        "compare_table": compare_rows,
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": RESEARCH_ARTIFACT_BUCKET,
            "prefix": prefix,
            "batch_summary_r2_key": batch_key,
        },
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "order_execution": False,
        "local_sot": False,
        "densify": False,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "significance_claimed": False,
        "edge_claimed": False,
        "operational_go": False,
        "not_s1_rehash": True,
        "note": (
            "S4/S5 research hypotheses (margin change / short ratio Δ). "
            "小サンプル / 研究用・未宣言. Not READY. No Mass. No densify invent."
        ),
    }

    puts: list[dict[str, Any]] = []

    def _put(key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _put_research_json(
            key,
            payload,
            r2_put=r2_put,
            wrangler=wrangler,
            wrangler_config=wrangler_config,
            dry_run=dry_run,
            staging_dir=staging_dir,
        )

    puts.append(_put(batch_key, batch_summary))
    if write_per_day_artifacts:
        for d in day_results:
            date_s = str(d.get("date") or "")[:10]
            day_key = f"{prefix}/days/date={date_s}/signals.json"
            puts.append(_put(day_key, d))

    return MultidaySignalEval(
        job_id=jid,
        n_days=len(day_results),
        as_of_days=tuple(str(d.get("date")) for d in day_results),
        codes=tuple(selected_codes),
        batch_summary_r2_key=batch_key,
        batch_summary=batch_summary,
        day_results=tuple(day_results),
        r2_puts=tuple(puts),
        dry_run=bool(dry_run),
        mass_research=MASS_RESEARCH_STATUS,
        phase7=PHASE7_STATUS,
        ready_declared=READY_DECLARED,
        local_sot=False,
        attach_nextday_returns=True,
        version="extra-hyp-multisignal-nextday-eval/v1",
    )


__all__ = [
    "execute_extra_hyp_signals_compare",
]
