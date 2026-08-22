"""Candidate-grade daily MTM. Does not GO."""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence

from research.daily_path_eval import panel_index
from research.unique_logic.catalog import yaml_unique_rows
from research.unique_logic.constants import CS_LOGIC_IDS
from research.unique_logic import event, cross_section

# CS_LOGIC_IDS spans cross_section and this module; split on YAML evaluator module.
NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = tuple(
    row
    for row in yaml_unique_rows(logic_ids=sorted(CS_LOGIC_IDS))
    if ".cs_overlays." in str(row.get("evaluator") or "")
)


def _month_end_days(dates: Sequence[str], n_last: int) -> set[str]:
    by_ym: dict[str, list[str]] = {}
    for d in dates:
        ds = str(d)[:10]
        if len(ds) < 7:
            continue
        by_ym.setdefault(ds[:7], []).append(ds)
    out: set[str] = set()
    n = max(1, int(n_last))
    for _ym, ds in by_ym.items():
        ds_s = sorted(ds)
        out.update(ds_s[-n:])
    return out


def _trailing_vol_by_date(
    close_by: Mapping[str, float],
    dates: Sequence[str],
    *,
    lookback: int,
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    rets: list[float | None] = []
    prev: float | None = None
    min_n = max(5, int(lookback) // 2)
    for d in dates:
        ds = str(d)[:10]
        c = close_by.get(ds)
        r: float | None = None
        if prev is not None and c is not None and prev != 0.0:
            try:
                fv = (float(c) / float(prev)) - 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                fv = None
            if fv is not None and math.isfinite(fv):
                r = fv
        rets.append(r)
        window = [x for x in rets[-int(lookback) :] if x is not None]
        if len(window) >= min_n:
            m = sum(window) / float(len(window))
            var = sum((x - m) ** 2 for x in window) / float(len(window) - 1)
            out[ds] = math.sqrt(var) if var > 0.0 else 0.0
        else:
            out[ds] = None
        prev = float(c) if c is not None else None
    return out


def evaluate_overnight_level_cs_tilt_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    overnight_by_date: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom faded when overnight LEVEL is tight vs PIT median.

    ``params.tilt=follow_easy`` inverts occupancy: follow CS when overnight
    is *below* the PIT median (overnight_easy_cs_follow).
    """
    from features.class_signals import cross_section_rank_signs

    p = cross_section._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = cross_section._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate=str((spec.get("params") or {}).get("gate") or "overnight_ge_pit_trailing_median"),
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    overnight = dict(overnight_by_date or {})
    if not overnight:
        return cross_section._empty_extra(
            spec=spec,
            extra=extra,
            status="missing_overnight_series",
            reason=(
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "overnight-level CS tilt. Not approximated."
            ),
        )

    panel = panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    med_by = event.pit_median_on_dates(overnight, dates, min_hist=min_hist)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_easy = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        on = overnight.get(d)
        if on is None:
            n_skip_missing += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        follow_easy = str((spec.get("params") or {}).get("tilt") or "") == "follow_easy"
        if follow_easy:
            if float(on) >= float(med):
                n_skip_easy += 1
                n_off += 1
                for code in ranks:
                    daily_rank.setdefault(code, {})[d] = 0.0
                continue
            n_on += 1
            for code, sign in ranks.items():
                daily_rank.setdefault(code, {})[d] = (
                    0.0 if sign is None else float(sign)
                )
        else:
            if float(on) < float(med):
                n_skip_easy += 1
                n_off += 1
                for code in ranks:
                    daily_rank.setdefault(code, {})[d] = 0.0
                continue
            n_on += 1
            for code, sign in ranks.items():
                daily_rank.setdefault(code, {})[d] = (
                    0.0 if sign is None else -float(sign)
                )

    extra.update(
        {
            **cross_section._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_easy_overnight": n_skip_easy,
            "n_overnight_prints": len(overnight),
        }
    )
    return cross_section._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_month_end_cs_fade_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """Invert CS mom on last N bar sessions of each calendar month."""
    from features.class_signals import cross_section_rank_signs

    p = cross_section._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    n_last = int(
        spec.get("month_end_sessions")
        or p["params"].get("month_end_sessions")
        or 3
    )
    extra = cross_section._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="last_n_sessions_of_calendar_month",
        extra_dataset="equities_bars_daily",
        data_path="local_real_mirrors+local_sqlite_bars",
    )
    extra["month_end_sessions"] = n_last

    panel = panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    me = _month_end_days(dates, n_last)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        if d not in me:
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        n_on += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else -float(sign)
            )

    extra.update(
        {
            **cross_section._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_month_end_days": len(me),
        }
    )
    return cross_section._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_xs_low_vol_mom_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """High CS-vol regime: rank mom among the low-vol half."""
    from features.class_signals import cross_section_rank_signs

    p = cross_section._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    lookback = int(
        spec.get("vol_lookback") or p["params"].get("vol_lookback") or 20
    )
    extra = cross_section._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="cs_median_vol_ge_pit_median_then_low_vol_universe",
        extra_dataset="equities_bars_daily",
        data_path="local_real_mirrors+local_sqlite_bars",
    )
    extra["vol_lookback"] = lookback
    extra["not_vol_risk_adjusted_mom"] = True

    panel = panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    close_by = panel["close_by"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    vol_by_code: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        vol_by_code[code] = _trailing_vol_by_date(
            close_by.get(code) or {}, dlist, lookback=lookback
        )

    cs_med_vol: dict[str, float] = {}
    for d in dates:
        vals = []
        for code in dates_by_code:
            v = (vol_by_code.get(code) or {}).get(d)
            if v is not None and math.isfinite(float(v)):
                vals.append(float(v))
        if len(vals) >= 2:
            cs_med_vol[d] = float(median(vals))

    med_by = event.pit_median_on_dates(cs_med_vol, dates, min_hist=min_hist)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_unformed = 0
    n_skip_quiet = 0
    n_skip_sparse = 0
    n_names_ranked = 0
    for d in dates:
        cs_med = cs_med_vol.get(d)
        pit_med = med_by.get(d)
        if cs_med is None or pit_med is None:
            n_skip_unformed += 1
            n_off += 1
            moms = by_date.get(d) or {}
            for code in moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if float(cs_med) < float(pit_med):
            n_skip_quiet += 1
            n_off += 1
            moms = by_date.get(d) or {}
            for code in moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        scores: dict[str, float] = {}
        moms = by_date.get(d) or {}
        for code, mom in moms.items():
            if mom is None or not math.isfinite(float(mom)):
                continue
            v = (vol_by_code.get(code) or {}).get(d)
            if v is None or not math.isfinite(float(v)):
                continue
            if float(v) < float(cs_med):
                scores[code] = float(mom)
        if len(scores) < 2:
            n_skip_sparse += 1
            n_off += 1
            for code in moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        n_on += 1
        n_names_ranked += len(scores)
        for code in moms:
            sign = ranks.get(code)
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **cross_section._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_quiet_vol_regime": n_skip_quiet,
            "n_skip_sparse_low_vol": n_skip_sparse,
            "mean_names_on_ranked_days": (
                float(n_names_ranked) / float(n_on) if n_on else 0.0
            ),
        }
    )
    return cross_section._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_repo_3m_level_cs_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom followed when 3M repo LEVEL is tight vs PIT median."""
    from features.class_signals import cross_section_rank_signs

    p = cross_section._cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = cross_section._base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="term_3m_ge_pit_trailing_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    long_by = dict((curve_series or {}).get("long_rates_by_date") or {})
    if not long_by:
        return cross_section._empty_extra(
            spec=spec,
            extra=extra,
            status="missing_3m_series",
            reason=(
                "jsda_tokyo_repo_rates 3M series empty — cannot apply "
                "repo-3M-level CS. Not approximated."
            ),
        )

    panel = panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    med_by = event.pit_median_on_dates(long_by, dates, min_hist=min_hist)
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_easy = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        lv = long_by.get(d)
        if lv is None:
            n_skip_missing += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if float(lv) < float(med):
            n_skip_easy += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        n_on += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **cross_section._occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_3m": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_easy_3m": n_skip_easy,
            "n_3m_prints": len(long_by),
        }
    )
    return cross_section._finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )

