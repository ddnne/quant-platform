"""Unique-logic evaluators (candidate-grade daily MTM).

Does not promote / GO / retune pins.
"""
from __future__ import annotations

import math
from datetime import date
from statistics import median
from typing import Any, Mapping, Sequence

from research.daily_path_eval import (
    assert_frozen_pins_untouched,
    held_book_daily_mtm,
    panel_index,
)
from research.unique_logic.constants import (
    ALWAYS_ON_OCCUPANCY_WARN,
    KNOWN_DEMOTED_OR_WEAK,
    KNOWN_WEAK_THESIS,
    LOGIC_CATALOG_HEADLINE_BAN,
    EVENT_LOGIC_IDS,
    EVENT_FILTER_LOGIC_IDS,
)

_assert_frozen_pins_untouched = assert_frozen_pins_untouched

NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_stress_skip",
        "family_id": "event_funding_combo",
        "kind": "event_funding_stress_skip",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW PIT GATE + funding×disclosure: skip post-disclosure surprise "
            "entry when overnight Tokyo repo is at/above its PIT trailing "
            "median (funding stress). Not event_post_disclosure_hold remap."
        ),
        "thesis": (
            "Post-earnings surprise drift is financing-sensitive. When overnight "
            "Tokyo repo is at/above its PIT trailing median, skip the event "
            "entry; take surprise-sign hold only when funding is easy."
        ),
        "signal_definition": (
            "earnings surprise proxy; enter only if overnight repo on entry "
            "date is strictly below PIT trailing median of prior overnight "
            "prints; missing same-date overnight → skip (no ffill)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip entire "
            "event when funding-stress gate is on or overnight is missing"
        ),
        "datasets": [
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
            "mode": "funding_stress_skip",
            "gate": "overnight_lt_pit_trailing_median",
        },
    },
    {
        "logic_id": "curve_steep_event_confirm",
        "family_id": "event_macro_curve_combo",
        "kind": "curve_steep_event_confirm",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW combo funding×disclosure×macro: event surprise hold only "
            "when 3M−ON repo curve is steep (spread>0, both tenors same date, "
            "no ffill). Distinct from overnight-level gate and from "
            "rate_curve_shape_xs (not a CS-mom book)."
        ),
        "thesis": (
            "Event surprise drift is confirmed only in a carry-friendly term-"
            "funding regime: take PIT surprise-sign hold iff the JSDA Tokyo "
            "repo curve (3M−overnight) is steep on the entry date."
        ),
        "signal_definition": (
            "surprise-sign AND same-date repo spread (3M/T+1 − overnight/T+0) "
            "> 0; missing either tenor → skip (no ffill / no invent)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; flatten/skip "
            "when curve is flat, inverted, or gapped"
        ),
        "datasets": [
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "steep_threshold": 0.0,
            "mode": "curve_steep_event_confirm",
            "gate": "repo_curve_spread_gt_0",
        },
    },
    {
        "logic_id": "disclosure_cluster_mom_gate",
        "family_id": "disclosure_cluster_gate",
        "kind": "disclosure_cluster_mom_gate",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "why_unique": (
            "NEW PIT GATE: CS mom L-S sticky only when PIT count of recent "
            "universe disclosures ≥ trailing median. Distinct from "
            "xs_cs_dispersion_gate (disclosure count, not mom std) and not a "
            "sticky remap."
        ),
        "thesis": (
            "Relative-strength L-S is more informative during earnings-season "
            "information flow. Gate the CS mom book ON only when the PIT "
            "count of disclosures in the last N sessions is at/above its "
            "trailing median."
        ),
        "signal_definition": (
            "CS rank mom L-S × PIT disclosure-cluster count vs trailing "
            "median (strict: DiscDate < today; no same-day look-ahead)"
        ),
        "position_rule": (
            "sticky fixed_horizon hold of gated rank signs; flat when "
            "disclosure cluster is below PIT trailing median"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "cluster_lookback": 5,
            "min_hist": 10,
            "mode": "disclosure_cluster_gate",
            "gate": "n_recent_disclosures_ge_pit_median",
        },
    },
    {
        "logic_id": "surprise_xs_rank_hold",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "why_unique": (
            "NEW SIGNAL: cross-section rank of earnings surprise among names "
            "currently in a PIT event window — relative surprise, not "
            "own-sign time-series event_post hold."
        ),
        "thesis": (
            "Among names that have a PIT-available disclosure in the last H "
            "sessions, long high-surprise / short low-surprise. Relative "
            "surprise, not own-sign PEAD hold."
        ),
        "signal_definition": (
            "CS rank of surprise among names whose PIT event entry is inside "
            "the last post_hold_days sessions; <2 names → flat (no invent)"
        ),
        "position_rule": (
            "balanced L/S on surprise ranks for currently-in-window names; "
            "names with no recent PIT disclosure stay flat"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "long_frac": 0.3,
            "short_frac": 0.3,
            "mode": "surprise_xs_rank",
        },
    },
)


def pit_median_on_dates(
    series_by_date: Mapping[str, float],
    query_dates: Sequence[str],
    *,
    min_hist: int,
) -> dict[str, float | None]:
    """PIT trailing median: values with series_date < query_date only."""
    items: list[tuple[str, float]] = []
    for d, v in series_by_date.items():
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
    hist: list[float] = []
    j = 0
    out: dict[str, float | None] = {}
    for d in query_dates:
        ds = str(d)[:10]
        while j < len(items) and items[j][0] < ds:
            hist.append(items[j][1])
            j += 1
        out[ds] = float(median(hist)) if len(hist) >= int(min_hist) else None
    return out


def _collect_event_entries(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """PIT event entries (no DiscTime invent). Shared by event-gated logics."""
    from features.class_signals import (
        earnings_surprise_proxy,
        event_post_entry_bar_index,
        sign_from_numeric,
    )

    h = int(spec.get("post_hold_days") or spec.get("params", {}).get("post_hold_days") or 5)
    entry_mode = str(
        spec.get("entry_mode")
        or (spec.get("params") or {}).get("entry_mode")
        or "same_day_close_if_pre_close"
    )
    p0 = str(period_start)[:10] if period_start else None
    p1 = str(period_end)[:10] if period_end else None

    close_by: dict[str, dict[str, float]] = {}
    calendar: set[str] = set()
    per_code: dict[str, dict[str, Any]] = {}
    n_events = 0
    n_no_surprise = 0
    n_no_bar = 0
    entries: list[dict[str, Any]] = []

    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        dlist = [str(d)[:10] for d, _ in pairs_l]
        date_to_idx = {d: i for i, d in enumerate(dlist)}
        for d, c in pairs_l:
            close_by.setdefault(code, {})[str(d)[:10]] = float(c)
            calendar.add(str(d)[:10])
        code_entries: list[dict[str, Any]] = []
        for ev in list(events_by_code.get(code) or []):
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            if p0 and disc < p0:
                continue
            if p1 and disc > p1:
                continue
            n_events += 1
            surprise, _s_meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            disc_time = ev.get("disc_time")
            event_time = ev.get("event_time") or ev.get("available_at")
            idx, entry_date, _meta = event_post_entry_bar_index(
                date_to_idx,
                disc_date=disc,
                disc_time=disc_time,
                event_time=str(event_time) if event_time else None,
                entry_mode=entry_mode,
            )
            if idx is None or entry_date is None:
                n_no_bar += 1
                continue
            sgn = sign_from_numeric(surprise)
            if sgn is None or sgn == 0.0 or surprise is None:
                n_no_surprise += 1
                continue
            rec = {
                "code": code,
                "disc_date": disc,
                "entry_idx": int(idx),
                "entry_date": str(entry_date)[:10],
                "surprise": float(surprise),
                "sign": float(sgn),
                "eps": ev.get("eps"),
                "prior_eps": ev.get("prior_eps"),
                "bps": ev.get("bps"),
                "roe": ev.get("roe"),
                "div_ann": ev.get("div_ann"),
                "np": ev.get("np"),
                "eq": ev.get("eq"),
                "ta": ev.get("ta"),
                "eq_ar": ev.get("eq_ar"),
                "prior_ta": ev.get("prior_ta"),
            }
            code_entries.append(rec)
            entries.append(rec)
        per_code[code] = {"dlist": dlist, "entries": code_entries}

    return {
        "hold_days": h,
        "entry_mode": entry_mode,
        "close_by": close_by,
        "calendar": sorted(calendar),
        "per_code": per_code,
        "entries": entries,
        "n_events": n_events,
        "n_no_surprise": n_no_surprise,
        "n_no_bar": n_no_bar,
        "n_eligible": len(entries),
    }


def _held_from_event_entries(
    collected: Mapping[str, Any],
    *,
    accept: Mapping[str, bool] | None = None,
    sign_mult_by_key: Mapping[str, float] | None = None,
) -> dict[str, dict[str, float | None]]:
    """Build last-event-wins held book; accept[entry_key] gates entries.

    sign_mult_by_key: optional per-entry sign multiplier (e.g. -1 short side).
    Missing multiplier after accept is skip (no invent).
    """
    h = int(collected["hold_days"])
    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, pack in (collected.get("per_code") or {}).items():
        dlist = list(pack.get("dlist") or [])
        held: list[float | None] = [None] * len(dlist)
        for ev in pack.get("entries") or []:
            key = f"{code}|{ev['entry_date']}|{ev['disc_date']}"
            if accept is not None and not accept.get(key, False):
                continue
            idx = int(ev["entry_idx"])
            sgn = float(ev["sign"])
            if sign_mult_by_key is not None:
                if key not in sign_mult_by_key:
                    continue
                try:
                    sgn = sgn * float(sign_mult_by_key[key])
                except (TypeError, ValueError):
                    continue
                if sgn == 0.0:
                    continue
            end = min(idx + h, len(dlist))
            for j in range(idx, end):
                held[j] = sgn
        held_by_code_date[code] = {dlist[i]: held[i] for i in range(len(dlist))}
    return held_by_code_date


def evaluate_event_funding_stress_skip_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold skipped under PIT overnight funding stress.

    Gate (PIT): overnight[entry_date] < trailing median of overnight prints
    with date < entry_date. Missing same-date overnight → skip (no ffill).
    """
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = _collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    dates = list(collected["calendar"])
    extra = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "min_hist": min_hist,
        "gate": "overnight_lt_pit_trailing_median",
        "n_events": collected["n_events"],
        "n_eligible_pre_gate": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "extra_dataset": "fins_summary+jsda_tokyo_repo_rates",
        "data_path": "local_real_mirrors+local_sqlite_fins+repo",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if not overnight_by_date:
        return {
            "status": "missing_overnight_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "funding-stress PIT gate. Not approximated."
            ),
            **extra,
        }
    if collected["n_events"] == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary loaded but no DiscDate events in this shard "
                "for eval codes — daily book empty. Not approximated."
            ),
            **extra,
        }

    entry_dates = sorted({e["entry_date"] for e in collected["entries"]})
    med_by = pit_median_on_dates(overnight_by_date, entry_dates, min_hist=min_hist)
    accept: dict[str, bool] = {}
    n_skip_missing = 0
    n_skip_no_median = 0
    n_skip_stress = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"
        d = ev["entry_date"]
        on = overnight_by_date.get(d)
        if on is None:
            accept[key] = False
            n_skip_missing += 1
            continue
        med = med_by.get(d)
        if med is None:
            accept[key] = False
            n_skip_no_median += 1
            continue
        if float(on) >= float(med):
            accept[key] = False
            n_skip_stress += 1
            continue
        accept[key] = True
        n_entered += 1

    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_missing_overnight": n_skip_missing,
            "n_skip_median_unformed": n_skip_no_median,
            "n_skip_funding_stress": n_skip_stress,
        }
    )
    held = _held_from_event_entries(collected, accept=accept)
    pack = held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_curve_steep_event_confirm_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    curve_series: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only when same-date repo curve is steep (no ffill)."""
    params = dict(spec.get("params") or {})
    steep = float(spec.get("steep_threshold") or params.get("steep_threshold") or 0.0)
    collected = _collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    dates = list(collected["calendar"])
    spread_by = dict((curve_series or {}).get("spread_by_date") or {})
    extra = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "steep_threshold": steep,
        "gate": "repo_curve_spread_gt_steep_threshold",
        "n_events": collected["n_events"],
        "n_eligible_pre_gate": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "extra_dataset": "fins_summary+jsda_tokyo_repo_rates",
        "data_path": "local_real_mirrors+local_sqlite_fins+repo",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if not spread_by:
        return {
            "status": "missing_curve_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates curve series empty — cannot apply "
                "steep-curve event confirm. Not approximated."
            ),
            **extra,
        }
    if collected["n_events"] == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary loaded but no DiscDate events in this shard "
                "for eval codes — daily book empty. Not approximated."
            ),
            **extra,
        }

    accept: dict[str, bool] = {}
    n_skip_gap = 0
    n_skip_not_steep = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"
        sp = spread_by.get(ev["entry_date"])
        if sp is None:
            accept[key] = False
            n_skip_gap += 1
            continue
        if float(sp) <= float(steep):
            accept[key] = False
            n_skip_not_steep += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_curve_gap": n_skip_gap,
            "n_skip_not_steep": n_skip_not_steep,
        }
    )
    held = _held_from_event_entries(collected, accept=accept)
    pack = held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_disclosure_cluster_mom_gate_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom L-S sticky gated by PIT universe disclosure-cluster count.

    Distinct from xs_cs_dispersion_gate (mom std). DiscDate < today only.
    """
    from features.class_signals import apply_sticky_hold, cross_section_rank_signs

    params = dict(spec.get("params") or {})
    n = int(spec.get("momentum_n") or params.get("momentum_n") or 5)
    h = int(spec.get("hold_days") or params.get("hold_days") or 10)
    lf = float(spec.get("long_frac") or params.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or params.get("short_frac") or 0.3)
    lookback = int(spec.get("cluster_lookback") or params.get("cluster_lookback") or 5)
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 10)

    extra_base = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "momentum_n": n,
        "hold_days": h,
        "long_frac": lf,
        "short_frac": sf,
        "cluster_lookback": lookback,
        "min_hist": min_hist,
        "gate": "n_recent_disclosures_ge_pit_median",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    n_disc = sum(len(v) for v in (events_by_code or {}).values())
    if n_disc == 0:
        return {
            "status": "no_events",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary events empty — disclosure-cluster gate cannot "
                "be built. Not approximated."
            ),
            **extra_base,
        }

    panel = panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            **extra_base,
        }

    disc_dates: list[str] = []
    for evs in (events_by_code or {}).values():
        for ev in evs:
            d = str(ev.get("disc_date") or "")[:10]
            if d:
                disc_dates.append(d)
    disc_dates.sort()

    # Per bar date: count DiscDate in the previous `lookback` bar dates (strict).
    date_set_index = {d: i for i, d in enumerate(dates)}
    cluster_by: dict[str, float] = {}
    for i, d in enumerate(dates):
        lo = max(0, i - lookback)
        window = set(dates[lo:i])  # excludes today
        c = sum(1 for dd in disc_dates if dd in window)
        cluster_by[d] = float(c)
    med_by = pit_median_on_dates(cluster_by, dates, min_hist=min_hist)

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_gated_off = 0
    n_gate_on = 0
    n_median_unformed = 0
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        med = med_by.get(d)
        cl = cluster_by.get(d, 0.0)
        if med is None:
            on = False
            n_median_unformed += 1
        else:
            on = float(cl) >= float(med)
        if on:
            n_gate_on += 1
        else:
            n_gated_off += 1
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = sign if on else 0.0

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]))
            for i in range(len(dlist))
        }
    extra = {
        **extra_base,
        "n_gated_off_days": n_gated_off,
        "n_gate_on_days": n_gate_on,
        "n_median_unformed_days": n_median_unformed,
        "n_disclosure_prints": n_disc,
        "n_bar_dates": len(dates),
        "n_date_index": len(date_set_index),
    }
    pack = held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=panel["close_by"],
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def evaluate_surprise_xs_rank_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
    entries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """CS rank of surprise among names in a PIT event window (new signal)."""
    from features.class_signals import cross_section_rank_signs

    params = dict(spec.get("params") or {})
    lf = float(spec.get("long_frac") or params.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or params.get("short_frac") or 0.3)
    sign_flip = bool(spec.get("sign_flip") or params.get("sign_flip") or False)
    collected = _collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    if entries is not None:
        collected = dict(collected)
        collected["entries"] = list(entries)
        collected["n_eligible"] = len(collected["entries"])
    h = int(collected["hold_days"])
    dates = list(collected["calendar"])
    extra = {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "post_hold_days": h,
        "entry_mode": collected["entry_mode"],
        "long_frac": lf,
        "short_frac": sf,
        "sign_flip": sign_flip,
        "n_events": collected["n_events"],
        "n_eligible": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }
    if collected["n_events"] == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
            "daily_path_complete": False,
            "incomplete_reason": (
                "fins_summary loaded but no DiscDate events in this shard "
                "for eval codes — daily book empty. Not approximated."
            ),
            **extra,
        }
    if not dates:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": 0,
            **extra,
        }

    # Active surprise by date: names whose PIT entry is in [d-h+1, d] wait —
    # position lives on [entry, entry+h). Rank those currently held-in-window.
    date_to_idx = {d: i for i, d in enumerate(dates)}
    surprise_by_date: dict[str, dict[str, float]] = {d: {} for d in dates}
    for ev in collected["entries"]:
        ed = ev["entry_date"]
        if ed not in date_to_idx:
            continue
        i0 = date_to_idx[ed]
        for j in range(i0, min(i0 + h, len(dates))):
            surprise_by_date[dates[j]][ev["code"]] = float(ev["surprise"])

    held_by_code_date: dict[str, dict[str, float | None]] = {
        code: {d: None for d in dates} for code in collected["per_code"]
    }
    n_ranked_days = 0
    n_flat_sparse = 0
    n_names_ranked = 0
    for d in dates:
        scores = surprise_by_date.get(d) or {}
        if len(scores) < 2:
            n_flat_sparse += 1
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        n_ranked_days += 1
        n_names_ranked += len(scores)
        for code, sign in ranks.items():
            s = None if sign is None else float(sign)
            if s is not None and sign_flip:
                s = -s
            held_by_code_date.setdefault(code, {})[d] = s

    extra.update(
        {
            "n_ranked_days": n_ranked_days,
            "n_flat_sparse_days": n_flat_sparse,
            "mean_names_on_ranked_days": (
                float(n_names_ranked) / float(n_ranked_days) if n_ranked_days else 0.0
            ),
            "occupancy_note": (
                "Sparse occupancy is honest: CS surprise rank needs ≥2 names "
                "in-window. Not filled."
            ),
        }
    )
    pack = held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra["data_path"]
    return pack


def proposals_for_factory() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in NEW_UNIQUE_LOGIC:
        out.append(
            {
                "logic_id": spec["logic_id"],
                "family_id": spec["family_id"],
                "thesis": spec["thesis"],
                "signal_definition": spec["signal_definition"],
                "position_rule": spec["position_rule"],
                "datasets": list(spec["datasets"]),
                "datasets_used": list(spec["datasets"]),
                "params": dict(spec["params"]),
                "new_unique_logic": True,
                "catalog": False,
                "eval_mapped_to_catalog": False,
                "weak_template_mapping": "OFF",
            }
        )
    return out

