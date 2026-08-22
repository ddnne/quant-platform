"""Year-split extra-hyp (S4/S5) multi-year eval (W56 next-day; not SoT).

``run_multi_year_extra_hyp_eval``.
Gap years skipped honestly — never invent margin. Mass/READY/GO closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from research.eval_harness import (
    _compact_compare_rows,
    _selected_codes,
    _skip_year_row,
    assert_harness_closed,
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
    annotate_period_rows_with_cost,
    evaluate_research_robustness_gate,
    period_rows_from_cross_table,
)
from research.single_shot_job import (
    DEFAULT_FEATURE_ROW_LIMIT,
    D1ExecuteFn,
    RESEARCH_ONE_WAY_COST,
    R2PutFn,
    execute_extra_hyp_signals_compare,
)


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
    period_list = _resolve_year_periods(
        periods,
        years,
        max_days=max_days,
        min_days=min_days,
        codes=codes,
        empty_msg="multi-year extra-hyp requires at least one period",
    )
    selected_default = _selected_codes(codes, DEFAULT_MULTIYEAR_CODES)
    want_signals = (
        {str(s) for s in signal_ids}
        if signal_ids is not None
        else {"c21_margin_change_sign"}
    )
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
        s4_ok = p.get("s4_eligible")
        if s4_ok is None:
            y = p.get("year")
            s4_ok = not (y is not None and (int(y) == 2024 or int(y) < 2013))
        skip_reason = p.get("skip_reason")
        if skip_reason:
            results.append(
                _skip_year_row(
                    p, pid=pid, skip_reason=str(skip_reason), s4_eligible=s4_ok
                )
            )
            continue
        if not s4_ok:
            results.append(
                _skip_year_row(
                    p,
                    pid=pid,
                    skip_reason="margin data gap / not s4_eligible (not invented)",
                    s4_eligible=False,
                )
            )
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
        allow_empty = list(p.get("r2_allow_empty_datasets") or [])
        if "markets_short_ratio" not in allow_empty:
            allow_empty.append("markets_short_ratio")
        try:
            ex = execute_extra_hyp_signals_compare(
                period_start=start,
                period_end=end,
                job_id=f"{job_id_prefix}-{pid}",
                codes=p.get("codes") or selected_default,
                max_days=int(p.get("max_days") or max_days),
                min_days=int(p.get("min_days") or min_days),
                one_way_cost=one_way_cost,
                r2_allow_empty_datasets=allow_empty,
                **_period_history(p, **hist),
            )
            compare = [
                dict(r)
                for r in _compact_compare_rows(ex.batch_summary or {})
                if str(r.get("signal_id") or "") in want_signals
            ]
            results.append(
                _ok_year_row(
                    p,
                    pid=pid,
                    start=start,
                    end=end,
                    ex=ex,
                    extracted_row_counts=(ex.batch_summary or {}).get(
                        "tip_extracted_row_counts"
                    ),
                    compare_table=compare,
                    s4_eligible=True,
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
            gates[sid] = evaluate_research_robustness_gate(
                period_rows_from_cross_table(cross, signal_id=sid),
                signal_id=sid,
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
        signal_ids=sorted(want_signals),
        cross_year_compare_table=cross,
        robustness_gates=gates,
    )

__all__ = [
    "run_multi_year_extra_hyp_eval",
]
