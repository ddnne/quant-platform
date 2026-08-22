"""Year-split S1 multi-year eval (W56 next-day; not candidate SoT).

``run_multi_year_s1_eval`` plus S1 metrics helpers. Public imports stay on
:mod:`research.eval_harness` / :mod:`research.eval_harness_multiyear`.
Approved legs / fail-closed via eval_harness. Mass/READY/GO closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from features.minimal_signal import (
    DEFAULT_VOLUME_CHANGE_ABS_MIN,
    SIGNAL_ID as DEFAULT_SIGNAL_ID,
)
from research.eval_harness import (
    _compact_compare_rows,
    _selected_codes,
    _skip_year_row,
    assert_harness_closed,
    require_approved_signal_legs,
    require_harness_datasets,
)
from research.eval_harness_multiyear import (
    DEFAULT_MULTIYEAR_CODES,
    _ok_year_row,
    _pack_multi_year,
    _period_history,
    _resolve_year_periods,
    _year_period_error_row,
)
from research.robustness_gate import (
    DEFAULT_ONE_WAY_COST,
    annotate_period_rows_with_cost,
    evaluate_research_robustness_gate,
)
from research.single_shot_job import (
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    R2PutFn,
    execute_multiday_signal_eval,
)


def _int0(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _s1_metrics_from_batch_summary(
    batch_summary: Mapping[str, Any],
    *,
    period_id: str,
    n_days: int,
    n_codes: int,
) -> dict[str, Any]:
    """Gate-ready S1 metrics from nextday batch_summary (research-only)."""
    bs = dict(batch_summary or {})
    for row in _compact_compare_rows(bs):
        if str(row.get("signal_id") or "") == DEFAULT_SIGNAL_ID:
            return {**dict(row), "period_id": period_id, "n_days": n_days, "n_codes": n_codes}

    nd = bs.get("nextday_return") or bs.get("nextday_summary") or {}
    by_sign = nd.get("by_sign") if isinstance(nd, Mapping) else None
    mean_plus = mean_minus = None
    n_plus = n_minus = 0
    if isinstance(by_sign, Mapping):
        plus = by_sign.get("+1") or {}
        minus = by_sign.get("-1") or {}
        mean_plus = plus.get("mean_next_day_return")
        mean_minus = minus.get("mean_next_day_return")
        n_plus = _int0(plus.get("non_null_return_count") or plus.get("count"))
        n_minus = _int0(minus.get("non_null_return_count") or minus.get("count"))
    n_active = n_plus + n_minus
    gross = None
    try:
        if mean_plus is not None and mean_minus is not None and n_active > 0:
            gross = (float(mean_plus) * n_plus - float(mean_minus) * n_minus) / float(
                n_active
            )
        elif mean_plus is not None and n_minus == 0 and n_plus > 0:
            gross = float(mean_plus)
        elif mean_minus is not None and n_plus == 0 and n_minus > 0:
            gross = -float(mean_minus)
    except (TypeError, ValueError, ZeroDivisionError):
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
    period_list = _resolve_year_periods(
        periods,
        years,
        max_days=max_days,
        min_days=min_days,
        codes=codes,
        empty_msg="multi-year S1 requires at least one period",
    )
    selected_default = _selected_codes(codes, DEFAULT_MULTIYEAR_CODES)
    hist = dict(
        history_source=history_source,
        feature_row_limit=feature_row_limit,
        write_per_day_artifacts=write_per_day_artifacts,
        dry_run=dry_run,
        d1_execute=d1_execute,
        r2_put=r2_put,
        staging_dir=staging_dir,
        wrangler=wrangler,
        wrangler_config=wrangler_config,
        r2_get=r2_get,
        r2_bucket=r2_bucket,
    )
    results: list[dict[str, Any]] = []
    for i, raw in enumerate(period_list):
        p = dict(raw)
        pid = str(p.get("period_id") or f"y{i}").strip()
        skip_reason = p.get("skip_reason")
        if skip_reason:
            results.append(
                _skip_year_row(p, pid=pid, skip_reason=str(skip_reason), s1_row=None)
            )
            continue
        start = str(p.get("period_start") or "").strip()[:10]
        end = str(p.get("period_end") or "").strip()[:10]
        if not start or not end:
            results.append(
                _skip_year_row(
                    p,
                    pid=pid,
                    skip_reason="missing period_start/period_end",
                    s1_row=None,
                )
            )
            continue
        try:
            ex = execute_multiday_signal_eval(
                period_start=start,
                period_end=end,
                job_id=f"{job_id_prefix}-{pid}",
                codes=p.get("codes") or selected_default,
                max_days=int(p.get("max_days") or max_days),
                min_days=int(p.get("min_days") or min_days),
                volume_change_abs_min=volume_change_abs_min,
                attach_nextday_returns=True,
                **_period_history(p, **hist),
            )
            bs = ex.batch_summary or {}
            s1_row = _s1_metrics_from_batch_summary(
                bs, period_id=pid, n_days=ex.n_days, n_codes=len(ex.codes)
            )
            compare = _compact_compare_rows(bs)
            for row in compare:
                if str(row.get("signal_id") or "") == DEFAULT_SIGNAL_ID:
                    s1_row = {**s1_row, **dict(row), "period_id": pid}
                    break
            results.append(
                _ok_year_row(
                    p,
                    pid=pid,
                    start=start,
                    end=end,
                    ex=ex,
                    history_source=history_source,
                    tip_plane=bs.get("tip_plane"),
                    extracted_row_counts=bs.get("tip_extracted_row_counts"),
                    s1_row=s1_row,
                    compare_table=compare or [s1_row],
                )
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
    cross = annotate_period_rows_with_cost(cross, one_way_cost=one_way_cost)
    gate: dict[str, Any] | None = None
    if apply_robustness_gate:
        gate = evaluate_research_robustness_gate(
            [
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
            ],
            signal_id=DEFAULT_SIGNAL_ID,
            min_periods=min_periods_gate,
            min_active_per_period=min_active_per_period,
            one_way_cost=one_way_cost,
            require_net_sign_majority=require_net_sign_majority,
        )
    return _pack_multi_year(
        job_id_prefix=job_id_prefix,
        period_list=period_list,
        results=results,
        one_way_cost=one_way_cost,
        require_net_sign_majority=require_net_sign_majority,
        history_source=history_source,
        signal_id=DEFAULT_SIGNAL_ID,
        cross_year_s1_table=cross,
        robustness_gate=gate,
    )

__all__ = [
    "run_multi_year_s1_eval",
]
