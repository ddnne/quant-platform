"""Research-only cost attach + multi-signal compare.

:func:`attach_research_cost_fields`, :func:`summarize_research_cost`, and
:func:`execute_multiday_multisignal_compare` live here.
:func:`execute_extra_hyp_signals_compare` lives in
:mod:`research.single_shot_extra_hyp` and is re-exported here. Multiday /
nextday eval stays in :mod:`research.single_shot_eval`. Public names are
re-exported from :mod:`research.single_shot_job`.

Fail-closed: COMPLETE 21 only, permanent DEFER 5 hard-reject, Mass OFF,
READY not declared. No densify, no orders. Outputs remain
**小サンプル / 研究用・未宣言** (no significance / no edge claim).
Cost label: **仮定に依存・研究用・運用GOではない**.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    DEFAULT_VOLUME_SIGN_ABS_MIN,
    MULTI_SIGNAL_DATASETS,
    MULTI_SIGNAL_FEATURE_IDS,
    SIGNAL_ID_TOPIX_DISC,
    SIGNAL_ID_TOPIX_REL,
    SIGNAL_ID_VOLUME_SIGN,
    SIGNAL_VERSION as DEFAULT_SIGNAL_VERSION,
    compute_signal_from_feature_observations,
    compute_topix_disc_from_feature_observations,
    compute_volume_sign_from_feature_observations,
    multi_signal_definitions,
)
from research.freezes import (
    MASS_RESEARCH as MASS_RESEARCH_STATUS,
    PHASE7 as PHASE7_STATUS,
    READY_DECLARED,
    READY_PUBLICATION as READY_PUBLICATION_STATUS,
)
from research.single_shot_eval import (
    MultidaySignalEval,
    NEXTDAY_LOOKAHEAD_POLICY,
    NEXTDAY_RESEARCH_LABEL,
    _cap_as_of_days,
    _median_f,
    _nextday_setup,
    attach_next_day_returns,
    session_close_as_of,
    summarize_nextday_by_sign,
    summarize_signal_day,
)
from research.single_shot_job import (
    D1_DATABASE_NAME,
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

# ---------------------------------------------------------------------------
# Multi-signal compare + research-only cost (W58 / w0815ay_g2 · T4–T8)
# ---------------------------------------------------------------------------

# Research-only cost assumption (not operational GO).
# One-way 10bp = 0.001; round-trip 20bp if both sides traded.
RESEARCH_ONE_WAY_COST_BP: float = 10.0
RESEARCH_ONE_WAY_COST: float = RESEARCH_ONE_WAY_COST_BP / 10_000.0  # 0.001
RESEARCH_ROUND_TRIP_COST: float = RESEARCH_ONE_WAY_COST * 2.0  # 0.002
RESEARCH_COST_LABEL: str = "仮定に依存・研究用・運用GOではない"
RESEARCH_COST_NOTE: str = (
    "Research-only net next-day return assumes a fixed one-way cost of "
    f"{RESEARCH_ONE_WAY_COST_BP:.0f}bp ({RESEARCH_ONE_WAY_COST}) per signed "
    "position. Round-trip equivalent is "
    f"{RESEARCH_ONE_WAY_COST_BP * 2:.0f}bp ({RESEARCH_ROUND_TRIP_COST}) if "
    "both entry and exit are charged. Cost is subtracted from signed PnL "
    "(|position| * cost) and does NOT model capacity, borrow, impact, or "
    "partial fills. 仮定に依存・研究用・運用GOではない — not operational GO, "
    "not READY, not Mass, no significance / edge claim."
)


def signed_position_from_signal(value: Any) -> float | None:
    """Map signal value to research position: +1 / 0 / −1, or None if null."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v == 1.0:
        return 1.0
    if v == -1.0:
        return -1.0
    if v == 0.0:
        return 0.0
    return None


def attach_research_cost_fields(
    aligned_rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
) -> list[dict[str, Any]]:
    """Attach gross/net signed next-day PnL under research cost assumption.

    For each row with non-null signal and non-null next_day_return:

    * position = sign(signal) ∈ {+1, 0, −1}
    * gross_signed_return = position * next_day_return
    * net_signed_return_one_way = gross − |position| * one_way_cost
    * net_signed_return_round_trip = gross − |position| * 2 * one_way_cost

    Null signal or null return → cost fields null. Label:
    **仮定に依存・研究用・運用GOではない**.
    """
    out: list[dict[str, Any]] = []
    rt_cost = float(one_way_cost) * 2.0
    for row in aligned_rows:
        rec = dict(row)
        pos = signed_position_from_signal(row.get("value"))
        ret = row.get("next_day_return")
        rec["research_cost_one_way"] = float(one_way_cost)
        rec["research_cost_round_trip"] = rt_cost
        rec["research_cost_label"] = RESEARCH_COST_LABEL
        if pos is None or ret is None:
            rec["position"] = pos
            rec["gross_signed_return"] = None
            rec["net_signed_return_one_way"] = None
            rec["net_signed_return_round_trip"] = None
            out.append(rec)
            continue
        try:
            r = float(ret)
        except (TypeError, ValueError):
            rec["position"] = pos
            rec["gross_signed_return"] = None
            rec["net_signed_return_one_way"] = None
            rec["net_signed_return_round_trip"] = None
            out.append(rec)
            continue
        gross = float(pos) * r
        abs_pos = abs(float(pos))
        rec["position"] = pos
        rec["gross_signed_return"] = gross
        rec["net_signed_return_one_way"] = gross - abs_pos * float(one_way_cost)
        rec["net_signed_return_round_trip"] = gross - abs_pos * rt_cost
        out.append(rec)
    return out


def summarize_research_cost(
    costed_rows: Sequence[Mapping[str, Any]],
    *,
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
) -> dict[str, Any]:
    """Aggregate gross / net signed PnL under the research cost assumption."""

    def _bucket(field: str) -> dict[str, Any]:
        vals = [
            float(r[field])
            for r in costed_rows
            if r.get(field) is not None and r.get("position") is not None
            and float(r.get("position") or 0) != 0.0
        ]
        # Include flat (0) positions too for "signed overall including flat"
        all_signed = [
            float(r[field])
            for r in costed_rows
            if r.get(field) is not None and r.get("position") is not None
        ]
        n_pos = sum(
            1
            for r in costed_rows
            if r.get("position") is not None and abs(float(r["position"])) > 0
        )
        mean_active = (sum(vals) / len(vals)) if vals else None
        mean_all = (sum(all_signed) / len(all_signed)) if all_signed else None
        med_active = _median_f(vals)
        return {
            "n_active_positions": n_pos,
            "n_with_pnl": len(vals),
            "mean_active": mean_active,
            "median_active": med_active,
            "mean_all_signed_incl_flat": mean_all,
        }

    return {
        "version": "research-cost-summary/v1",
        "label": RESEARCH_COST_LABEL,
        "one_way_cost_bp": one_way_cost * 10_000.0,
        "one_way_cost": float(one_way_cost),
        "round_trip_cost_bp": one_way_cost * 2.0 * 10_000.0,
        "round_trip_cost": float(one_way_cost) * 2.0,
        "gross_signed_return": _bucket("gross_signed_return"),
        "net_signed_return_one_way": _bucket("net_signed_return_one_way"),
        "net_signed_return_round_trip": _bucket("net_signed_return_round_trip"),
        "assumption_note": RESEARCH_COST_NOTE,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "order_execution": False,
        "operational_go": False,
        "significance_claimed": False,
        "edge_claimed": False,
    }


def _summarize_one_signal_batch(
    day_obs_by_signal: Sequence[Sequence[Mapping[str, Any]]],
    *,
    signal_id: str,
    definition: Mapping[str, Any],
    one_way_cost: float = RESEARCH_ONE_WAY_COST,
) -> dict[str, Any]:
    """Aggregate multiday observations for one signal id (nextday + cost)."""
    all_rows: list[Mapping[str, Any]] = []
    for day_rows in day_obs_by_signal:
        all_rows.extend(day_rows)

    total = len(all_rows)
    non_null = sum(1 for r in all_rows if r.get("value") is not None)
    null_n = total - non_null
    long_n = sum(1 for r in all_rows if r.get("value") == 1.0)
    short_n = sum(1 for r in all_rows if r.get("value") == -1.0)
    flat_n = sum(1 for r in all_rows if r.get("value") == 0.0)
    nextday = summarize_nextday_by_sign(all_rows)
    costed = attach_research_cost_fields(all_rows, one_way_cost=one_way_cost)
    cost_summary = summarize_research_cost(costed, one_way_cost=one_way_cost)

    return {
        "signal_id": signal_id,
        "signal_version": DEFAULT_SIGNAL_VERSION,
        "status": "candidate",
        "candidate_only": False,
        "approved_legs_only": True,
        "definition": dict(definition),
        "aggregate": {
            "signal_count": total,
            "non_null": non_null,
            "null": null_n,
            "non_null_rate": (float(non_null) / float(total)) if total else None,
            "sign_distribution": {
                "+1": long_n,
                "0": flat_n,
                "-1": short_n,
                "null": null_n,
            },
        },
        "nextday_return": nextday,
        "research_cost": cost_summary,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "significance_claimed": False,
        "edge_claimed": False,
        "ready_declared": False,
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "order_execution": False,
        "operational_go": False,
    }


def _compare_row_from_signal_body(
    sid: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    """Compact compare-table row from one signal's batch summary body."""
    nd = body.get("nextday_return") or {}
    by_sign = nd.get("by_sign") or {}
    cost = body.get("research_cost") or {}
    agg = body.get("aggregate") or {}
    return {
        "signal_id": sid,
        "signal_count": agg.get("signal_count"),
        "non_null": agg.get("non_null"),
        "non_null_rate": agg.get("non_null_rate"),
        "sign_plus": (agg.get("sign_distribution") or {}).get("+1"),
        "sign_zero": (agg.get("sign_distribution") or {}).get("0"),
        "sign_minus": (agg.get("sign_distribution") or {}).get("-1"),
        "mean_R_plus": (by_sign.get("+1") or {}).get("mean_next_day_return"),
        "median_R_plus": (by_sign.get("+1") or {}).get("median_next_day_return"),
        "mean_R_minus": (by_sign.get("-1") or {}).get("mean_next_day_return"),
        "median_R_minus": (by_sign.get("-1") or {}).get("median_next_day_return"),
        "overall_mean_R": (nd.get("overall") or {}).get("mean_next_day_return"),
        "overall_median_R": (nd.get("overall") or {}).get("median_next_day_return"),
        "null_return_rate": (nd.get("overall") or {}).get("null_return_rate"),
        "gross_signed_mean_active": (
            (cost.get("gross_signed_return") or {}).get("mean_active")
        ),
        "net_one_way_mean_active": (
            (cost.get("net_signed_return_one_way") or {}).get("mean_active")
        ),
        "net_round_trip_mean_active": (
            (cost.get("net_signed_return_round_trip") or {}).get("mean_active")
        ),
        "n_active_positions": (
            (cost.get("gross_signed_return") or {}).get("n_active_positions")
        ),
    }


def execute_multiday_multisignal_compare(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815ay-g2-multisignal",
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
    """Multi-signal compare (approved legs only).

    Signals (all candidate; candidate_only=False; not READY):

    1. ``c21_topix_relative_sign`` — baseline sign(topix_relative_1d)
    2. ``c21_volume_change_sign`` — sign(volume_change_1d) with abs threshold
    3. ``c21_topix_rel_disclosure_filter`` — topix relative + disclosure filter

    Same codes / as_of days / next-day returns across signals. Optional
    research-only net PnL under one-way 10bp cost (仮定に依存・研究用・運用GOではない).

    ``history_source``:
        * ``"d1_tip"`` (default) — CF D1 hot tip extract
        * ``"r2"`` — R2 structured history bridge

    Does **not** connect Mass, mint READY, densify, or execute orders.
    """
    assert_mass_and_phase7_off()
    start, end, jid = _require_job_window(period_start, period_end, job_id)
    _ = min_days

    dataset_ids = require_complete_21_only(
        MULTI_SIGNAL_DATASETS, context="multisignal compare datasets"
    )
    selected_codes = _select_codes(codes)
    feature_ids = tuple(MULTI_SIGNAL_FEATURE_IDS)
    definitions = {
        d["signal_id"]: d
        for d in multi_signal_definitions(volume_sign_abs_min=volume_sign_abs_min)
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
            "fins_summary",
            "markets_margin_interest",
        ),
        context="multisignal feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}
    if codes is None and tip_feature_extract.get("selected_codes"):
        selected_codes = list(tip_feature_extract["selected_codes"])

    full_trading_days, next_map, close_index = _nextday_setup(
        rows_by_ds, period_start=start, period_end=end
    )
    day_list = _cap_as_of_days(as_of_days, full_trading_days, max_days)
    if not day_list:
        raise SingleShotJobError(
            "multisignal compare: no trading days found in tip window "
            f"{start}..{end}"
        )

    paths = design_artifact_paths(jid)
    prefix = str(paths["prefix"])
    batch_key = f"{prefix}/batch_summary.json"
    executed_at = _now_utc()

    # Per-signal accumulation of aligned rows across days.
    signal_day_rows: dict[str, list[list[dict[str, Any]]]] = {
        SIGNAL_ID_TOPIX_REL: [],
        SIGNAL_ID_VOLUME_SIGN: [],
        SIGNAL_ID_TOPIX_DISC: [],
    }
    day_results: list[dict[str, Any]] = []

    for d in day_list:
        as_of = session_close_as_of(d)
        feature_payload = compute_tip_candidate_features(
            rows_by_ds,
            as_of=as_of,
            feature_ids=feature_ids,
            codes=selected_codes,
            dates=[d],
        )
        obs = feature_payload.get("observations") or []

        s1 = compute_signal_from_feature_observations(
            obs,
            as_of=as_of,
            volume_change_abs_min=None,  # baseline: volume gate off
            codes=selected_codes,
        )
        s2 = compute_volume_sign_from_feature_observations(
            obs,
            as_of=as_of,
            volume_change_abs_min=volume_sign_abs_min,
            codes=selected_codes,
        )
        s3 = compute_topix_disc_from_feature_observations(
            obs,
            as_of=as_of,
            codes=selected_codes,
        )

        nxt = next_map.get(d)
        eval_as_of = session_close_as_of(nxt) if nxt else None
        per_signal_day: dict[str, Any] = {}
        for sid, core in (
            (SIGNAL_ID_TOPIX_REL, s1),
            (SIGNAL_ID_VOLUME_SIGN, s2),
            (SIGNAL_ID_TOPIX_DISC, s3),
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
                "feature_as_of": as_of,
                "next_day_date": nxt,
                "evaluation_as_of": eval_as_of,
                "feature_ids": list(feature_ids),
                "feature_tip_input_row_counts": feature_payload.get(
                    "tip_input_row_counts"
                ),
                "codes": list(selected_codes),
                "signals": per_signal_day,
                "attach_nextday_returns": True,
                "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
                "label": NEXTDAY_RESEARCH_LABEL,
                "cost_label": RESEARCH_COST_LABEL,
                "local_sot": False,
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
                "order_execution": False,
            }
        )

    # Per-signal batch summaries.
    by_signal: dict[str, Any] = {}
    for sid in (SIGNAL_ID_TOPIX_REL, SIGNAL_ID_VOLUME_SIGN, SIGNAL_ID_TOPIX_DISC):
        by_signal[sid] = _summarize_one_signal_batch(
            signal_day_rows[sid],
            signal_id=sid,
            definition=definitions.get(sid) or {},
            one_way_cost=one_way_cost,
        )

    compare_rows = [
        _compare_row_from_signal_body(sid, by_signal[sid])
        for sid in (SIGNAL_ID_TOPIX_REL, SIGNAL_ID_VOLUME_SIGN, SIGNAL_ID_TOPIX_DISC)
    ]

    batch_summary: dict[str, Any] = {
        "version": "multiday-multisignal-nextday-batch/v1",
        "job_id": jid,
        "pipeline": "multi_signal_compare",
        "signal_ids": [
            SIGNAL_ID_TOPIX_REL,
            SIGNAL_ID_VOLUME_SIGN,
            SIGNAL_ID_TOPIX_DISC,
        ],
        "definitions": multi_signal_definitions(
            volume_sign_abs_min=volume_sign_abs_min
        ),
        "feature_ids": list(feature_ids),
        "feature_status_pins": {
            "topix_relative_1d": "approved",
            "is_trading_day": "approved",
            "volume_change_1d": "approved",
            "disclosure_flag_fins": "approved",
            "margin_interest_change_1d": "approved",
        },
        "approved_legs_only": True,
        "volume_sign_abs_min": volume_sign_abs_min,
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
        "d1_database": D1_DATABASE_NAME if hist_src == "d1_tip" else None,
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "tip_raw_tip_counts": tip_feature_extract.get("raw_tip_counts")
        or tip_feature_extract.get("raw_envelope_counts"),
        "history_source_channels": tip_feature_extract.get("source_channels"),
        "available_at_repairs": tip_feature_extract.get("available_at_repairs"),
        "by_signal": by_signal,
        "compare_table": compare_rows,
        "research_cost_assumption": {
            "one_way_cost_bp": one_way_cost * 10_000.0,
            "one_way_cost": float(one_way_cost),
            "round_trip_cost_bp": one_way_cost * 2.0 * 10_000.0,
            "round_trip_cost": float(one_way_cost) * 2.0,
            "label": RESEARCH_COST_LABEL,
            "note": RESEARCH_COST_NOTE,
        },
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
        "per_day_compact": [
            {
                "date": d.get("date"),
                "as_of": d.get("as_of"),
                "next_day_date": d.get("next_day_date"),
                "signals": {
                    sid: {
                        "signal_count": (d.get("signals") or {})
                        .get(sid, {})
                        .get("signal_count"),
                        "non_null": (d.get("signals") or {})
                        .get(sid, {})
                        .get("non_null"),
                        "sign_distribution": (d.get("signals") or {})
                        .get(sid, {})
                        .get("sign_distribution"),
                        "nextday_day_summary": (d.get("signals") or {})
                        .get(sid, {})
                        .get("nextday_day_summary"),
                    }
                    for sid in (
                        SIGNAL_ID_TOPIX_REL,
                        SIGNAL_ID_VOLUME_SIGN,
                        SIGNAL_ID_TOPIX_DISC,
                    )
                },
            }
            for d in day_results
        ],
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": RESEARCH_ARTIFACT_BUCKET,
            "prefix": prefix,
            "batch_summary_r2_key": batch_key,
            "per_day_key_template": f"{prefix}/days/date={{date}}/signals.json",
        },
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
        "densify": False,
        "attach_nextday_returns": True,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "significance_claimed": False,
        "edge_claimed": False,
        "operational_go": False,
        "note": (
            "Multi-signal compare via single_shot only "
            f"(history_source={hist_src}). "
            "Three approved-leg research signals on the same universe/period. "
            "Next-day returns + optional research cost (10bp one-way). "
            "小サンプル / 研究用・未宣言 · 仮定に依存・研究用・運用GOではない. "
            "Not READY. Not mass research. No order execution. No densify."
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
            # Drop heavy observation lists from R2 day body size if needed —
            # keep them for research transparency (same as prior waves).
            day_body = {
                "version": "multiday-multisignal-nextday-day/v1",
                "job_id": jid,
                **{k: d[k] for k in d},
                "mass_research": MASS_RESEARCH_STATUS,
                "phase7": PHASE7_STATUS,
                "ready_declared": READY_DECLARED,
                "order_execution": False,
                "local_sot": False,
                "label": NEXTDAY_RESEARCH_LABEL,
                "cost_label": RESEARCH_COST_LABEL,
            }
            puts.append(_put(day_key, day_body))
            d["signals_r2_key"] = day_key

    manifest_key = str(paths["manifest_r2_key"])
    manifest = {
        "version": "multiday-multisignal-nextday-manifest/v1",
        "job_id": jid,
        "bucket": RESEARCH_ARTIFACT_BUCKET,
        "prefix": prefix,
        "keys": {
            "manifest": manifest_key,
            "batch_summary": batch_key,
            **(
                {
                    f"day_{d.get('date')}": d.get("signals_r2_key")
                    for d in day_results
                    if d.get("signals_r2_key")
                }
                if write_per_day_artifacts
                else {}
            ),
        },
        "n_days": len(day_results),
        "n_codes": len(selected_codes),
        "as_of_days": [d.get("date") for d in day_results],
        "codes": list(selected_codes),
        "signal_ids": list(batch_summary["signal_ids"]),
        "compare_table": compare_rows,
        "executed_at_utc": executed_at,
        "dry_run": bool(dry_run),
        "mass_research": MASS_RESEARCH_STATUS,
        "phase7": PHASE7_STATUS,
        "ready_declared": READY_DECLARED,
        "ready_publication": READY_PUBLICATION_STATUS,
        "order_execution": False,
        "local_sot": False,
        "connected_to_mass_research_loop": False,
        "attach_nextday_returns": True,
        "label": NEXTDAY_RESEARCH_LABEL,
        "cost_label": RESEARCH_COST_LABEL,
        "operational_go": False,
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
    }
    puts.append(_put(manifest_key, manifest))
    batch_summary["manifest_r2_key"] = manifest_key

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
        version="multiday-multisignal-nextday-eval/v1",
    )


# Extra-hyp compare lives in research.single_shot_extra_hyp (re-exported).
# Lazy getattr so compare-first and extra-hyp-first loads both bind.
_EXTRA_HYP_EXPORTS: frozenset[str] = frozenset(
    {
        "execute_extra_hyp_signals_compare",
    }
)


def __getattr__(name: str):
    if name in _EXTRA_HYP_EXPORTS:
        import research.single_shot_extra_hyp as _extra_hyp

        return getattr(_extra_hyp, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _EXTRA_HYP_EXPORTS | set(__all__))


__all__ = [
    "RESEARCH_COST_LABEL",
    "RESEARCH_COST_NOTE",
    "RESEARCH_ONE_WAY_COST",
    "RESEARCH_ONE_WAY_COST_BP",
    "RESEARCH_ROUND_TRIP_COST",
    "attach_research_cost_fields",
    "execute_extra_hyp_signals_compare",
    "execute_multiday_multisignal_compare",
    "signed_position_from_signal",
    "summarize_research_cost",
]
