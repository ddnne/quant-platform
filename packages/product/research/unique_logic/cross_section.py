"""Unique-logic evaluators (candidate-grade daily MTM).

Does not promote / GO / retune pins.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Sequence

from research.daily_path_eval import (
    held_book_daily_mtm,
    panel_index,
)
from research.unique_logic.constants import ALWAYS_ON_OCCUPANCY_WARN
from research.unique_logic.catalog import yaml_unique_rows
from research.unique_logic import event

PACK_BIAS = "mixed"


NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = tuple(
    yaml_unique_rows(
        logic_ids=(
            "funding_impulse_cs_tilt",
            "curve_steepen_impulse_cs",
            "xs_margin_delta_rank",
            "idio_mom_macro_impulse",
        )
    )
)


def _ymd(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def prior_delta_by_date(series_by_date: Mapping[str, float]) -> dict[str, float]:
    """Same-date minus strictly-prior print. No ffill onto missing dates."""
    items: list[tuple[str, float]] = []
    for d, v in (series_by_date or {}).items():
        ds = str(d)[:10]
        if not ds:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            items.append((ds, fv))
    items.sort(key=lambda x: x[0])
    out: dict[str, float] = {}
    for i in range(1, len(items)):
        out[items[i][0]] = items[i][1] - items[i - 1][1]
    return out


def _last_print_before(
    series_by_date: Mapping[str, float],
    query_date: str,
) -> tuple[str, float] | None:
    prior = [d for d in series_by_date if str(d)[:10] < str(query_date)[:10]]
    if not prior:
        return None
    d = max(prior)
    try:
        return str(d)[:10], float(series_by_date[d])
    except (TypeError, ValueError):
        return None


def _cs_params(spec: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(spec.get("params") or {})
    return {
        "momentum_n": int(spec.get("momentum_n") or params.get("momentum_n") or 5),
        "hold_days": int(spec.get("hold_days") or params.get("hold_days") or 10),
        "long_frac": float(spec.get("long_frac") or params.get("long_frac") or 0.3),
        "short_frac": float(spec.get("short_frac") or params.get("short_frac") or 0.3),
        "min_hist": int(spec.get("min_hist") or params.get("min_hist") or 20),
        "stale_calendar_days": int(
            spec.get("stale_calendar_days") or params.get("stale_calendar_days") or 14
        ),
        "params": params,
    }


def _base_cs_extra(
    spec: Mapping[str, Any],
    *,
    n: int,
    h: int,
    lf: float,
    sf: float,
    min_hist: int,
    gate: str,
    extra_dataset: str,
    data_path: str,
) -> dict[str, Any]:
    return {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "momentum_n": n,
        "hold_days": h,
        "long_frac": lf,
        "short_frac": sf,
        "min_hist": min_hist,
        "gate": gate,
        "axis": spec.get("axis"),
        "extra_dataset": extra_dataset,
        "data_path": data_path,
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
        "sticky_approx_always_on_gate": False,
        "pack_bias": PACK_BIAS,
    }


def _occupancy_note(n_on: int, n_dates: int) -> dict[str, Any]:
    frac = (float(n_on) / float(n_dates)) if n_dates else 0.0
    return {
        "n_gate_on_days": n_on,
        "n_bar_dates": n_dates,
        "occupancy_frac": frac,
        "occupancy_always_on_warning": bool(frac >= ALWAYS_ON_OCCUPANCY_WARN),
        "sticky_approx_always_on_gate": False,
    }


def _cs_held_from_daily(
    *,
    dates_by_code: Mapping[str, Sequence[str]],
    daily_rank: Mapping[str, Mapping[str, float | None]],
    hold_days: int,
) -> dict[str, dict[str, float | None]]:
    from features.class_signals import apply_sticky_hold

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(
            entries, hold_days=int(hold_days), rebalance_mode="fixed_horizon"
        )
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]))
            for i in range(len(dlist))
        }
    return held_by_code_date


def _finish_cs_book(
    *,
    spec: Mapping[str, Any],
    panel: Mapping[str, Any],
    daily_rank: Mapping[str, Mapping[str, float | None]],
    extra: Mapping[str, Any],
    one_way_cost: float,
    hold_days: int,
) -> dict[str, Any]:
    held = _cs_held_from_daily(
        dates_by_code=panel["dates_by_code"],
        daily_rank=daily_rank,
        hold_days=hold_days,
    )
    pack = held_book_daily_mtm(
        held_by_code_date=held,
        close_by=panel["close_by"],
        dates=list(panel["dates"]),
        hold_days=int(hold_days),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra.get("data_path")
    pack["new_unique_logic"] = True
    pack["catalog"] = False
    pack["promote_as_main"] = False
    pack["go"] = False
    pack["pack_bias"] = PACK_BIAS
    return pack


def _empty_extra(
    *,
    spec: Mapping[str, Any],
    extra: Mapping[str, Any],
    reason: str,
    status: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "logic_id": spec["logic_id"],
        "daily_path_complete": False,
        "incomplete_reason": reason,
        **extra,
    }


def evaluate_funding_impulse_cs_tilt_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    overnight_by_date: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom L-S tilted by large overnight repo Δ (funding impulse)."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="abs_overnight_delta_ge_pit_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    overnight = dict(overnight_by_date or {})
    if not overnight:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_overnight_series",
            reason=(
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "funding-impulse CS tilt. Not approximated."
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

    deltas = prior_delta_by_date(overnight)
    abs_deltas = {d: abs(v) for d, v in deltas.items()}
    med_by = event.pit_median_on_dates(abs_deltas, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_small = 0
    n_tilt_fade = 0
    n_tilt_follow = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        if d not in overnight:
            n_skip_missing += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        dv = deltas.get(d)
        if dv is None:
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
        if abs(float(dv)) < float(med) or float(dv) == 0.0:
            n_skip_small += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        tilt = -1.0 if float(dv) > 0.0 else 1.0
        if tilt < 0:
            n_tilt_fade += 1
        else:
            n_tilt_follow += 1
        n_on += 1
        for code, sign in ranks.items():
            sval = 0.0 if sign is None else float(sign) * tilt
            daily_rank.setdefault(code, {})[d] = sval

    extra.update(
        {
            **_occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_small_delta": n_skip_small,
            "n_tilt_fade_days": n_tilt_fade,
            "n_tilt_follow_days": n_tilt_follow,
            "n_overnight_prints": len(overnight),
            "n_overnight_deltas": len(deltas),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def evaluate_curve_steepen_impulse_cs_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom L-S only on large 3M−ON steepening impulses (macro)."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="spread_delta_gt_0_and_abs_ge_pit_median",
        extra_dataset="jsda_tokyo_repo_rates",
        data_path="local_real_mirrors+local_sqlite_jsda_repo_rates",
    )
    spread_by = dict((curve_series or {}).get("spread_by_date") or {})
    if not spread_by:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_curve_series",
            reason=(
                "jsda_tokyo_repo_rates curve series empty — cannot apply "
                "curve-steepening impulse CS. Not approximated."
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

    deltas = prior_delta_by_date(spread_by)
    abs_deltas = {d: abs(v) for d, v in deltas.items()}
    med_by = event.pit_median_on_dates(abs_deltas, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_gap = 0
    n_skip_unformed = 0
    n_skip_not_steepen = 0
    n_skip_small = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        if d not in spread_by or d not in deltas:
            n_skip_gap += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        dv = float(deltas[d])
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if dv <= 0.0:
            n_skip_not_steepen += 1
            n_off += 1
            for code in ranks:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if abs(dv) < float(med):
            n_skip_small += 1
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
            **_occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_curve_gap": n_skip_gap,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_not_steepen": n_skip_not_steepen,
            "n_skip_small_delta": n_skip_small,
            "n_spread_prints": len(spread_by),
            "n_spread_deltas": len(deltas),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def _margin_delta_score(
    series_by_date: Mapping[str, float],
    query_date: str,
    *,
    stale_days: int,
) -> float | None:
    last = _last_print_before(series_by_date, query_date)
    if last is None:
        return None
    last_d, last_v = last
    age = (_ymd(query_date) - _ymd(last_d)).days
    if age > int(stale_days):
        return None
    prev = _last_print_before(series_by_date, last_d)
    if prev is None:
        return None
    _prev_d, prev_v = prev
    if prev_v == 0.0 or not math.isfinite(prev_v) or not math.isfinite(last_v):
        return None
    # Shrinking margin (de-crowd) → positive score → long.
    return -((last_v - prev_v) / abs(prev_v))


def evaluate_xs_margin_delta_rank_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS rank of PIT name-level margin %change (flow XS, not price mom)."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
    )
    stale_days = int(p["stale_calendar_days"])
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=0,
        gate="name_margin_delta_cs_rank",
        extra_dataset="markets_margin_interest",
        data_path="local_real_mirrors+local_sqlite_margin",
    )
    extra["stale_calendar_days"] = stale_days
    extra["momentum_n"] = None  # signal is margin Δ, not price mom
    margin_ok = bool(margin_by_code) and any(
        bool(v) for v in (margin_by_code or {}).values()
    )
    if not margin_ok:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_extra_dataset",
            reason=(
                "markets_margin_interest series empty — cannot rank name-level "
                "margin delta. Not approximated."
            ),
        )

    # Panel uses mom only to share the bar calendar / close map.
    panel = panel_index(bars_by_code, momentum_n=max(1, int(n)))
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra,
        }

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_ranked = 0
    n_flat_sparse = 0
    n_names_ranked = 0
    n_skip_stale_or_missing = 0
    for d in dates:
        scores: dict[str, float] = {}
        for code in dates_by_code:
            series = dict((margin_by_code or {}).get(code) or {})
            sc = _margin_delta_score(series, d, stale_days=stale_days)
            if sc is None:
                n_skip_stale_or_missing += 1
                continue
            scores[code] = float(sc)
        if len(scores) < 2:
            n_flat_sparse += 1
            for code in dates_by_code:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        n_ranked += 1
        n_names_ranked += len(scores)
        for code in dates_by_code:
            sign = ranks.get(code)
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **_occupancy_note(n_ranked, len(dates)),
            "n_ranked_days": n_ranked,
            "n_flat_sparse_days": n_flat_sparse,
            "n_skip_stale_or_missing": n_skip_stale_or_missing,
            "mean_names_on_ranked_days": (
                float(n_names_ranked) / float(n_ranked) if n_ranked else 0.0
            ),
            "occupancy_note": (
                "Ranked occupancy is honest: needs ≥2 names with two PIT "
                "margin prints, last print age ≤ stale cap. Not filled."
            ),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )


def _index_mom_on_dates(
    close_by_date: Mapping[str, float],
    dates: Sequence[str],
    *,
    momentum_n: int,
) -> dict[str, float | None]:
    n = int(momentum_n)
    out: dict[str, float | None] = {}
    for i, d in enumerate(dates):
        if i < n:
            out[str(d)[:10]] = None
            continue
        d0 = str(dates[i - n])[:10]
        c0 = close_by_date.get(d0)
        c1 = close_by_date.get(str(d)[:10])
        if c0 is None or c1 is None:
            out[str(d)[:10]] = None
            continue
        try:
            f0 = float(c0)
            f1 = float(c1)
        except (TypeError, ValueError):
            out[str(d)[:10]] = None
            continue
        if f0 == 0.0 or not math.isfinite(f0) or not math.isfinite(f1):
            out[str(d)[:10]] = None
            continue
        out[str(d)[:10]] = (f1 / f0) - 1.0
    return out


def evaluate_idio_mom_macro_impulse_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    topix_by_date: Mapping[str, float] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS rank of residual mom vs TOPIX on large |TOPIX mom| days."""
    from features.class_signals import cross_section_rank_signs

    p = _cs_params(spec)
    n, h, lf, sf, min_hist = (
        p["momentum_n"],
        p["hold_days"],
        p["long_frac"],
        p["short_frac"],
        p["min_hist"],
    )
    extra = _base_cs_extra(
        spec,
        n=n,
        h=h,
        lf=lf,
        sf=sf,
        min_hist=min_hist,
        gate="abs_topix_mom_ge_pit_median",
        extra_dataset="indices_bars_daily_topix",
        data_path="local_real_mirrors+local_sqlite_topix",
    )
    topix = dict(topix_by_date or {})
    if not topix:
        return _empty_extra(
            spec=spec,
            extra=extra,
            status="missing_topix_series",
            reason=(
                "indices_bars_daily_topix series empty — cannot build "
                "idiosyncratic mom vs TOPIX. Not approximated."
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

    topix_mom = _index_mom_on_dates(topix, dates, momentum_n=n)
    abs_mom = {
        d: abs(v) for d, v in topix_mom.items() if v is not None and math.isfinite(v)
    }
    med_by = event.pit_median_on_dates(abs_mom, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_on = 0
    n_off = 0
    n_skip_missing = 0
    n_skip_unformed = 0
    n_skip_quiet = 0
    for d in dates:
        t_mom = topix_mom.get(d)
        name_moms = dict(by_date.get(d) or {})
        if t_mom is None:
            n_skip_missing += 1
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_unformed += 1
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        if abs(float(t_mom)) < float(med):
            n_skip_quiet += 1
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        residuals: dict[str, float] = {}
        for code, m in name_moms.items():
            if m is None:
                continue
            try:
                residuals[code] = float(m) - float(t_mom)
            except (TypeError, ValueError):
                continue
        if len(residuals) < 2:
            n_off += 1
            for code in name_moms:
                daily_rank.setdefault(code, {})[d] = 0.0
            continue
        ranks = cross_section_rank_signs(residuals, long_frac=lf, short_frac=sf)
        n_on += 1
        for code in name_moms:
            sign = ranks.get(code)
            daily_rank.setdefault(code, {})[d] = (
                0.0 if sign is None else float(sign)
            )

    extra.update(
        {
            **_occupancy_note(n_on, len(dates)),
            "n_gated_off_days": n_off,
            "n_skip_missing_topix": n_skip_missing,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_quiet_macro": n_skip_quiet,
            "n_topix_prints": len(topix),
            "n_topix_mom": len(abs_mom),
        }
    )
    return _finish_cs_book(
        spec=spec,
        panel=panel,
        daily_rank=daily_rank,
        extra=extra,
        one_way_cost=one_way_cost,
        hold_days=h,
    )

