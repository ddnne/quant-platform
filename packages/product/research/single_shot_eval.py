"""Multiday / nextday research eval (Mass OFF / READY not declared).

Cost/compare re-exported from :mod:`research.single_shot_compare`.
Fail-closed COMPLETE-21. No densify, no orders, no significance claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    CANDIDATE_ONLY as SIGNAL_CANDIDATE_ONLY,
    DEFAULT_FEATURE_IDS as DEFAULT_SIGNAL_FEATURE_IDS,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
    SIGNAL_VERSION as DEFAULT_SIGNAL_VERSION,
    compute_signal_from_feature_observations,
    signal_definition,
)
from research.freezes import (
    MASS_RESEARCH as MASS_RESEARCH_STATUS,
    PHASE7 as PHASE7_STATUS,
    READY_DECLARED,
)
from research.single_shot_job import (
    D1_DATABASE_NAME,
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    RESEARCH_ARTIFACT_BUCKET,
    R2PutFn,
    SingleShotJobError,
    _closed_flags,
    _load_history_feature_rows,
    _now_utc,
    _put_research_json,
    _require_job_window,
    _select_codes,
    assert_mass_and_phase7_off,
    design_artifact_paths,
    require_complete_21_only,
)
from research.single_shot_tip import (
    _available_at_ok,
    compute_tip_candidate_features,
    discover_tip_trading_days,
)

# Feature as_of = T close; return uses T+1 close at T+1 evaluation_as_of.
NEXTDAY_RESEARCH_LABEL: str = "小サンプル / 研究用・未宣言"

NEXTDAY_LOOKAHEAD_POLICY: Mapping[str, Any] = MappingProxyType(
    {
        "version": "nextday-lookahead-policy/v1",
        "label": NEXTDAY_RESEARCH_LABEL,
        "feature_as_of": "signal_day_T_session_close",
        "feature_as_of_clock": "T15:30:00+09:00",
        "feature_pit_gate": "available_at <= feature_as_of",
        "return_definition": "close(T+1)/close(T) - 1",
        "evaluation_as_of": "next_trading_day_T1_session_close",
        "evaluation_as_of_clock": "T+1 15:30:00+09:00",
        "return_pit_gate": "available_at(T bar) and available_at(T+1 bar) <= evaluation_as_of",
        "no_feature_lookahead": True,
        "ready_declared": False,
        "mass_research": "NO-GO",
        "significance_claimed": False,
        "edge_claimed": False,
    }
)


@dataclass(frozen=True)
class MultidaySignalEval:
    """Outcome of a multi-as_of tip signal batch (not READY, not mass, no orders)."""

    job_id: str
    n_days: int
    as_of_days: tuple[str, ...]
    codes: tuple[str, ...]
    batch_summary_r2_key: str
    batch_summary: Mapping[str, Any]
    day_results: tuple[Mapping[str, Any], ...]
    r2_puts: tuple[dict[str, Any], ...]
    dry_run: bool
    mass_research: str = MASS_RESEARCH_STATUS
    phase7: str = PHASE7_STATUS
    ready_declared: bool = READY_DECLARED
    local_sot: bool = False
    attach_nextday_returns: bool = False
    version: str = "multiday-signal-eval/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "n_days": self.n_days,
            "as_of_days": list(self.as_of_days),
            "codes": list(self.codes),
            "batch_summary_r2_key": self.batch_summary_r2_key,
            "batch_summary": dict(self.batch_summary),
            "day_results": [dict(d) for d in self.day_results],
            "r2_puts": list(self.r2_puts),
            "dry_run": self.dry_run,
            **_closed_flags(
                mass_research=self.mass_research,
                phase7=self.phase7,
                ready_declared=self.ready_declared,
                local_sot=self.local_sot,
                connected_to_mass_research_loop=False,
                significance_claimed=False,
                edge_claimed=False,
            ),
            "attach_nextday_returns": self.attach_nextday_returns,
            "label": (
                NEXTDAY_RESEARCH_LABEL
                if self.attach_nextday_returns
                else "研究用・未宣言"
            ),
        }


def summarize_signal_day(
    signal_payload: Mapping[str, Any],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Per-day aggregate: signal count, non-null rate, sign distribution (+1/0/-1)."""
    rc = signal_payload.get("row_counts") if isinstance(signal_payload, Mapping) else None
    if not isinstance(rc, Mapping):
        rc = {}
    computed = int(rc.get("computed") or 0)
    non_null = int(rc.get("non_null") or 0)
    null_n = int(rc.get("null") or 0)
    long_n = int(rc.get("long") or 0)
    short_n = int(rc.get("short") or 0)
    flat_n = int(rc.get("flat") or 0)
    rate = (float(non_null) / float(computed)) if computed else None
    sample = list(signal_payload.get("sample_values") or [])[:10]
    return {
        "date": str(as_of)[:10],
        "as_of": str(as_of),
        "signal_count": computed,
        "non_null": non_null,
        "null": null_n,
        "non_null_rate": rate,
        "sign_distribution": {
            "+1": long_n,
            "0": flat_n,
            "-1": short_n,
            "null": null_n,
        },
        "row_counts": {
            "computed": computed,
            "non_null": non_null,
            "null": null_n,
            "long": long_n,
            "short": short_n,
            "flat": flat_n,
        },
        "sample_values": sample,
        "signal_id": signal_payload.get("signal_id"),
        "candidate_only": signal_payload.get("candidate_only"),
        **_closed_flags(),
    }


def session_close_as_of(date: str) -> str:
    """JST equity session-close as_of clock for a calendar date."""
    d = str(date).strip()[:10]
    return f"{d}T15:30:00+09:00"


def build_equity_close_index(
    tip_rows_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Map ``(code, date)`` → close/available_at from tip equity bars."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in tip_rows_by_dataset.get("equities_bars_daily") or []:
        code = str(row.get("code") or "").strip()
        date = str(row.get("date") or "")[:10]
        close = row.get("close")
        if not code or not date or close is None:
            continue
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            continue
        out[(code, date)] = {
            "code": code,
            "date": date,
            "close": close_f,
            "available_at": row.get("available_at"),
            "event_time": row.get("event_time"),
        }
    return out


def next_trading_day_map(trading_days: Sequence[str]) -> dict[str, str | None]:
    """For each trading day, map to the next trading day (or None at tip edge)."""
    days = sorted({str(d).strip()[:10] for d in trading_days if str(d).strip()})
    out: dict[str, str | None] = {}
    for i, d in enumerate(days):
        out[d] = days[i + 1] if i + 1 < len(days) else None
    return out


def _nextday_setup(
    rows_by_ds: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    period_start: str,
    period_end: str,
    need_close_index: bool = True,
) -> tuple[list[str], dict[str, str | None], dict[tuple[str, str], dict[str, Any]]]:
    full_trading_days = discover_tip_trading_days(
        rows_by_ds, period_start=period_start, period_end=period_end
    )
    bar_days = sorted(
        {
            str(r.get("date") or "")[:10]
            for r in (rows_by_ds.get("equities_bars_daily") or [])
            if r.get("date")
        }
    )
    next_map = next_trading_day_map(
        sorted(set(full_trading_days or []) | set(bar_days))
    )
    close_index = (
        build_equity_close_index(rows_by_ds) if need_close_index else {}
    )
    return full_trading_days, next_map, close_index


def _cap_as_of_days(
    as_of_days: Sequence[str] | None,
    full_trading_days: Sequence[str],
    max_days: int,
) -> list[str]:
    if as_of_days:
        day_list = sorted({str(d).strip()[:10] for d in as_of_days if str(d).strip()})
    else:
        day_list = list(full_trading_days)
    if len(day_list) > max_days:
        day_list = day_list[-int(max_days) :]
    return day_list


def attach_next_day_returns(
    observations: Sequence[Mapping[str, Any]],
    *,
    signal_date: str,
    next_date: str | None,
    close_index: Mapping[tuple[str, str], Mapping[str, Any]],
    evaluation_as_of: str | None = None,
    feature_as_of: str | None = None,
) -> list[dict[str, Any]]:
    """Attach close-to-close next-day return per signal observation."""
    sig_d = str(signal_date).strip()[:10]
    feat_as_of = feature_as_of or session_close_as_of(sig_d)
    nxt_d = str(next_date).strip()[:10] if next_date else None
    eval_as_of = (
        evaluation_as_of
        if evaluation_as_of is not None
        else (session_close_as_of(nxt_d) if nxt_d else None)
    )

    out: list[dict[str, Any]] = []
    for obs in observations:
        rec = dict(obs)
        code = str(obs.get("code") or "").strip()
        close_t: float | None = None
        close_t1: float | None = None
        next_day_return: float | None = None
        pit_ok = False
        reason: str | None

        if not nxt_d:
            reason = "no_next_trading_day"
        elif not code:
            reason = "missing_code"
        elif eval_as_of is None:
            reason = "missing_evaluation_as_of"
        else:
            t_bar = close_index.get((code, sig_d))
            t1_bar = close_index.get((code, nxt_d))
            if t_bar is None:
                reason = "missing_close_T"
            elif t1_bar is None:
                reason = "missing_close_T1"
            elif not _available_at_ok(t_bar.get("available_at"), eval_as_of):
                reason = "pit_fail_T"
            elif not _available_at_ok(t1_bar.get("available_at"), eval_as_of):
                reason = "pit_fail_T1"
            else:
                try:
                    close_t = float(t_bar["close"])
                    close_t1 = float(t1_bar["close"])
                except (TypeError, ValueError, KeyError):
                    reason = "non_numeric_close"
                    close_t = None
                    close_t1 = None
                else:
                    if close_t == 0.0:
                        reason = "zero_close_T"
                    else:
                        next_day_return = (close_t1 / close_t) - 1.0
                        pit_ok = True
                        reason = None

        rec["signal_date"] = sig_d
        rec["next_day_date"] = nxt_d
        rec["close_T"] = close_t
        rec["close_T1"] = close_t1
        rec["next_day_return"] = next_day_return
        rec["feature_as_of"] = feat_as_of
        rec["evaluation_as_of"] = eval_as_of
        rec["next_day_return_pit_ok"] = pit_ok
        rec["next_day_return_null_reason"] = reason
        rec["label"] = NEXTDAY_RESEARCH_LABEL
        out.append(rec)
    return out


def _median_f(values: Sequence[float]) -> float | None:
    """Simple median of a non-empty numeric sequence (research helper)."""
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def summarize_nextday_by_sign(
    aligned_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Mean/median next-day return by signal sign (+1 / 0 / −1)."""

    def _sign_key(value: Any) -> str:
        if value is None:
            return "null_signal"
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "null_signal"
        if v == 1.0:
            return "+1"
        if v == -1.0:
            return "-1"
        if v == 0.0:
            return "0"
        return "null_signal"

    def _bucket_summary(returns: Sequence[Any]) -> dict[str, Any]:
        n = len(returns)
        non_null = [float(r) for r in returns if r is not None]
        null_n = n - len(non_null)
        mean = (sum(non_null) / len(non_null)) if non_null else None
        median = _median_f(non_null)
        return {
            "count": n,
            "non_null_return_count": len(non_null),
            "null_return_count": null_n,
            "null_return_rate": (float(null_n) / float(n)) if n else None,
            "mean_next_day_return": mean,
            "median_next_day_return": median,
        }

    buckets: dict[str, list[Any]] = {
        "+1": [],
        "0": [],
        "-1": [],
        "null_signal": [],
    }
    for row in aligned_rows:
        key = _sign_key(row.get("value"))
        buckets[key].append(row.get("next_day_return"))

    by_sign = {k: _bucket_summary(v) for k, v in buckets.items()}
    overall = _bucket_summary([row.get("next_day_return") for row in aligned_rows])

    signed_rows = [
        row
        for row in aligned_rows
        if row.get("value") is not None
        and float(row["value"]) in (1.0, 0.0, -1.0)
    ]
    signed_overall = _bucket_summary(
        [row.get("next_day_return") for row in signed_rows]
    )

    return {
        "version": "nextday-by-sign/v2",
        "label": NEXTDAY_RESEARCH_LABEL,
        "by_sign": by_sign,
        "overall": overall,
        "signed_overall": signed_overall,
        "n_rows": len(aligned_rows),
        "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
        **_closed_flags(significance_claimed=False, edge_claimed=False),
    }


def execute_multiday_signal_eval(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815au-g1-multiday",
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
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> MultidaySignalEval:
    """Run single_shot-equivalent signal compute across multiple as_of days."""
    assert_mass_and_phase7_off()
    start, end, jid = _require_job_window(period_start, period_end, job_id)
    _ = min_days

    dataset_ids = require_complete_21_only(
        DEFAULT_SIGNAL_DATASETS, context="multiday signal eval datasets"
    )
    selected_codes = _select_codes(codes)

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
        context="multiday signal feature extract",
    )
    rows_by_ds = tip_feature_extract.get("rows_by_dataset") or {}
    if codes is None and tip_feature_extract.get("selected_codes"):
        selected_codes = list(tip_feature_extract["selected_codes"])

    full_trading_days, next_map, close_index = _nextday_setup(
        rows_by_ds,
        period_start=start,
        period_end=end,
        need_close_index=bool(attach_nextday_returns),
    )
    day_list = _cap_as_of_days(as_of_days, full_trading_days, max_days)
    if not day_list:
        raise SingleShotJobError(
            "multiday signal eval: no trading days found in tip window "
            f"{start}..{end}"
        )

    paths = design_artifact_paths(jid)
    prefix = str(paths["prefix"])
    batch_key = f"{prefix}/batch_summary.json"
    executed_at = _now_utc()

    day_results: list[dict[str, Any]] = []
    for d in day_list:
        as_of = session_close_as_of(d)
        feature_payload = compute_tip_candidate_features(
            rows_by_ds,
            as_of=as_of,
            feature_ids=DEFAULT_SIGNAL_FEATURE_IDS,
            codes=selected_codes,
            dates=[d],
        )
        signal_core = compute_signal_from_feature_observations(
            feature_payload.get("observations") or [],
            as_of=as_of,
            volume_change_abs_min=volume_change_abs_min,
            codes=selected_codes,
        )
        day_summary = summarize_signal_day(signal_core, as_of=as_of)
        day_summary["feature_tip_input_row_counts"] = feature_payload.get(
            "tip_input_row_counts"
        )
        day_summary["feature_ids"] = list(DEFAULT_SIGNAL_FEATURE_IDS)
        day_summary["codes"] = list(selected_codes)
        day_summary["feature_status"] = feature_payload.get("status")
        day_summary["definition"] = signal_definition()
        day_summary["observations"] = list(signal_core.get("observations") or [])
        day_summary["feature_as_of"] = as_of
        day_summary["label"] = (
            NEXTDAY_RESEARCH_LABEL if attach_nextday_returns else "研究用・未宣言"
        )

        if attach_nextday_returns:
            nxt = next_map.get(d)
            eval_as_of = session_close_as_of(nxt) if nxt else None
            aligned = attach_next_day_returns(
                day_summary["observations"],
                signal_date=d,
                next_date=nxt,
                close_index=close_index,
                evaluation_as_of=eval_as_of,
                feature_as_of=as_of,
            )
            day_summary["observations"] = aligned
            day_summary["next_day_date"] = nxt
            day_summary["evaluation_as_of"] = eval_as_of
            day_summary["attach_nextday_returns"] = True
            day_summary["look_ahead_policy"] = dict(NEXTDAY_LOOKAHEAD_POLICY)
            day_summary["sample_values"] = [
                {
                    "code": r.get("code"),
                    "value": r.get("value"),
                    "next_day_return": r.get("next_day_return"),
                    "next_day_date": r.get("next_day_date"),
                    "close_T": r.get("close_T"),
                    "close_T1": r.get("close_T1"),
                    "topix_relative": (r.get("metadata") or {}).get(
                        "topix_relative"
                    ),
                    "next_day_return_null_reason": r.get(
                        "next_day_return_null_reason"
                    ),
                }
                for r in aligned[:10]
            ]
            day_summary["nextday_day_summary"] = summarize_nextday_by_sign(aligned)

        day_results.append(day_summary)

    total_computed = sum(int(d.get("signal_count") or 0) for d in day_results)
    total_non_null = sum(int(d.get("non_null") or 0) for d in day_results)
    total_null = sum(int(d.get("null") or 0) for d in day_results)
    total_long = sum(int((d.get("sign_distribution") or {}).get("+1") or 0) for d in day_results)
    total_short = sum(int((d.get("sign_distribution") or {}).get("-1") or 0) for d in day_results)
    total_flat = sum(int((d.get("sign_distribution") or {}).get("0") or 0) for d in day_results)
    overall_rate = (
        float(total_non_null) / float(total_computed) if total_computed else None
    )

    per_day_compact = [
        {
            "date": d.get("date"),
            "as_of": d.get("as_of"),
            "feature_as_of": d.get("feature_as_of"),
            "signal_count": d.get("signal_count"),
            "non_null": d.get("non_null"),
            "null": d.get("null"),
            "non_null_rate": d.get("non_null_rate"),
            "sign_distribution": d.get("sign_distribution"),
            "sample_values": d.get("sample_values"),
            **(
                {
                    "next_day_date": d.get("next_day_date"),
                    "evaluation_as_of": d.get("evaluation_as_of"),
                    "nextday_day_summary": d.get("nextday_day_summary"),
                }
                if attach_nextday_returns
                else {}
            ),
        }
        for d in day_results
    ]

    batch_summary: dict[str, Any] = {
        "version": (
            "multiday-signal-nextday-batch/v1"
            if attach_nextday_returns
            else "multiday-signal-batch/v1"
        ),
        "job_id": jid,
        "signal_id": DEFAULT_SIGNAL_ID,
        "signal_version": DEFAULT_SIGNAL_VERSION,
        "signal_status": "candidate",
        "candidate_only": SIGNAL_CANDIDATE_ONLY,
        "definition": signal_definition(),
        "feature_ids": list(DEFAULT_SIGNAL_FEATURE_IDS),
        "feature_status_pins": {
            "topix_relative_1d": "approved",
            "is_trading_day": "approved",
            "volume_change_1d": "approved",
        },
        "approved_legs_only": True,
        "dataset_ids": list(dataset_ids),
        "period_start": start,
        "period_end": end,
        "codes": list(selected_codes),
        "n_days": len(day_results),
        "as_of_days": [d.get("date") for d in day_results],
        "history_source": hist_src,
        "tip_plane": tip_feature_extract.get("plane")
        or ("R2_history" if hist_src == "r2" else "D1_hot_tip"),
        "d1_database": (
            None if hist_src == "r2" else D1_DATABASE_NAME
        ),
        "r2_bucket": (
            tip_feature_extract.get("bucket")
            if hist_src == "r2"
            else None
        ),
        "tip_extracted_row_counts": tip_feature_extract.get("extracted_row_counts"),
        "tip_raw_tip_counts": tip_feature_extract.get("raw_tip_counts")
        or tip_feature_extract.get("raw_envelope_counts"),
        "per_day": per_day_compact,
        "aggregate": {
            "signal_count": total_computed,
            "non_null": total_non_null,
            "null": total_null,
            "non_null_rate": overall_rate,
            "sign_distribution": {
                "+1": total_long,
                "0": total_flat,
                "-1": total_short,
                "null": total_null,
            },
        },
        "volume_change_abs_min": volume_change_abs_min,
        "executed_at_utc": executed_at,
        "artifact": {
            "bucket": RESEARCH_ARTIFACT_BUCKET,
            "prefix": prefix,
            "batch_summary_r2_key": batch_key,
            "per_day_key_template": f"{prefix}/days/date={{date}}/signals.json",
        },
        **_closed_flags(
            connected_to_mass_research_loop=False,
            densify=False,
            significance_claimed=False,
            edge_claimed=False,
        ),
        "attach_nextday_returns": bool(attach_nextday_returns),
        "label": (
            NEXTDAY_RESEARCH_LABEL if attach_nextday_returns else "研究用・未宣言"
        ),
    }

    if attach_nextday_returns:
        all_aligned: list[Mapping[str, Any]] = []
        for d in day_results:
            all_aligned.extend(d.get("observations") or [])
        nextday_summary = summarize_nextday_by_sign(all_aligned)
        batch_summary["nextday_return"] = nextday_summary
        batch_summary["look_ahead_policy"] = dict(NEXTDAY_LOOKAHEAD_POLICY)

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
            day_body = {
                "version": (
                    "multiday-signal-nextday-day/v1"
                    if attach_nextday_returns
                    else "multiday-signal-day/v1"
                ),
                "job_id": jid,
                **{k: d[k] for k in d if k != "definition"},
                "definition": d.get("definition") or signal_definition(),
                **_closed_flags(),
                "label": "研究用・未宣言",
            }
            puts.append(_put(day_key, day_body))
            d["signals_r2_key"] = day_key

    manifest_key = str(paths["manifest_r2_key"])
    manifest = {
        "version": (
            "multiday-signal-nextday-manifest/v1"
            if attach_nextday_returns
            else "multiday-signal-manifest/v1"
        ),
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
        "as_of_days": [d.get("date") for d in day_results],
        "codes": list(selected_codes),
        "signal_id": DEFAULT_SIGNAL_ID,
        "candidate_only": SIGNAL_CANDIDATE_ONLY,
        "aggregate": batch_summary["aggregate"],
        "executed_at_utc": executed_at,
        "dry_run": bool(dry_run),
        **_closed_flags(connected_to_mass_research_loop=False),
        "attach_nextday_returns": bool(attach_nextday_returns),
        "label": "研究用・未宣言",
        **(
            {
                "nextday_return": batch_summary.get("nextday_return"),
                "look_ahead_policy": dict(NEXTDAY_LOOKAHEAD_POLICY),
            }
            if attach_nextday_returns
            else {}
        ),
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
        attach_nextday_returns=bool(attach_nextday_returns),
        version=(
            "multiday-signal-nextday-eval/v1"
            if attach_nextday_returns
            else "multiday-signal-eval/v1"
        ),
    )


def execute_multiday_nextday_return_eval(
    *,
    period_start: str,
    period_end: str,
    job_id: str = "w0815aw-g1-expand20",
    codes: Sequence[str] | None = None,
    as_of_days: Sequence[str] | None = None,
    max_days: int = 20,
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
    r2_get: Callable[[str, str], bytes] | None = None,
    r2_bucket: str = "quant-structured",
) -> MultidaySignalEval:
    """Multiday signal eval with next-day return alignment."""
    return execute_multiday_signal_eval(
        period_start=period_start,
        period_end=period_end,
        job_id=job_id,
        codes=codes,
        as_of_days=as_of_days,
        max_days=max_days,
        min_days=min_days,
        feature_row_limit=feature_row_limit,
        volume_change_abs_min=volume_change_abs_min,
        attach_nextday_returns=True,
        history_source=history_source,
        r2_object_keys_by_dataset=r2_object_keys_by_dataset,
        r2_local_paths_by_dataset=r2_local_paths_by_dataset,
        r2_raw_lines_by_dataset=r2_raw_lines_by_dataset,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
        write_per_day_artifacts=write_per_day_artifacts,
        dry_run=dry_run,
        d1_execute=d1_execute,
        r2_put=r2_put,
        staging_dir=staging_dir,
        wrangler=wrangler,
        wrangler_config=wrangler_config,
    )


_COMPARE_EXPORTS: frozenset[str] = frozenset(
    {
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
    }
)


def __getattr__(name: str):
    if name in _COMPARE_EXPORTS:
        import research.single_shot_compare as _single_shot_compare

        return getattr(_single_shot_compare, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _COMPARE_EXPORTS | set(__all__))


__all__ = [
    "MultidaySignalEval",
    "NEXTDAY_LOOKAHEAD_POLICY",
    "NEXTDAY_RESEARCH_LABEL",
    "RESEARCH_COST_LABEL",
    "RESEARCH_COST_NOTE",
    "RESEARCH_ONE_WAY_COST",
    "RESEARCH_ONE_WAY_COST_BP",
    "RESEARCH_ROUND_TRIP_COST",
    "attach_next_day_returns",
    "attach_research_cost_fields",
    "build_equity_close_index",
    "execute_extra_hyp_signals_compare",
    "execute_multiday_multisignal_compare",
    "execute_multiday_nextday_return_eval",
    "execute_multiday_signal_eval",
    "next_trading_day_map",
    "session_close_as_of",
    "signed_position_from_signal",
    "summarize_nextday_by_sign",
    "summarize_research_cost",
    "summarize_signal_day",
]
