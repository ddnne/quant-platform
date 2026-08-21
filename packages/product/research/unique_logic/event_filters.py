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
    CS_AND_SIDE_LOGIC_IDS,
)

_assert_frozen_pins_untouched = assert_frozen_pins_untouched

from research.unique_logic.event import (  # noqa: E402
    _collect_event_entries,
    _held_from_event_entries,
    pit_median_on_dates,
)
import research.unique_logic.event as event  # noqa: E402

NEW_UNIQUE_LOGIC: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "large_surprise_event_hold",
        "family_id": "large_surprise_filter",
        "kind": "large_surprise_event_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW SIGNAL FILTER: take PIT surprise-sign hold only when "
            "|surprise| ≥ PIT trailing median of |surprise| among prior "
            "universe events (disc_date strictly before). Not event_post "
            "(all signed surprises) and not surprise_xs_rank (CS rank)."
        ),
        "thesis": (
            "Small earnings surprises are noise. Hold the surprise sign only "
            "when |surprise| is at/above its PIT trailing median across prior "
            "universe disclosures — large-surprise PEAD, not all-event PEAD."
        ),
        "signal_definition": (
            "earnings surprise proxy; enter iff abs(surprise) >= PIT median "
            "of abs(surprise) on events with disc_date < this disc_date "
            "(min_hist=20); median unformed → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip entire "
            "event when |surprise| is below the PIT median or median unformed"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
            "mode": "large_surprise_event_hold",
            "gate": "abs_surprise_ge_pit_trailing_median",
        },
    },
    {
        "logic_id": "afterclose_only_event_hold",
        "family_id": "afterclose_event_timing",
        "kind": "afterclose_only_event_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": False,
        "why_unique": (
            "NEW ENTRY TIMING: surprise hold only when DiscTime is at/after "
            "that day's TSE session close. Missing DiscTime → skip (no invent). "
            "Pre-close disclosures skipped. Not event_post_disclosure_hold "
            "(which takes both pre-close same-day and after-close next-day)."
        ),
        "thesis": (
            "After-hours disclosures avoid same-session leakage. Take the PIT "
            "surprise-sign hold only for DiscTime ≥ session close; skip "
            "intraday prints and time-unknown rows."
        ),
        "signal_definition": (
            "surprise-sign AND parseable DiscTime >= session_close_hhmmss"
            "(disc_date); missing/unparseable DiscTime → skip (no invent)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; flatten/skip "
            "when DiscTime is pre-close or unknown"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "mode": "afterclose_only_event_hold",
            "gate": "disctime_ge_session_close",
        },
    },
    {
        "logic_id": "event_pre_mom_agree_hold",
        "family_id": "event_mom_agree_combo",
        "kind": "event_pre_mom_agree_hold",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW COMBO: event surprise hold only when own-name N-day momentum "
            "ending at the last close strictly before entry agrees in sign "
            "with surprise. Not a sticky CS-mom book and not own-sign PEAD "
            "without confirmation."
        ),
        "thesis": (
            "PEAD is more informative when the name was already drifting in "
            "the surprise direction. Confirm surprise-sign hold with own-name "
            "pre-entry momentum; skip disagreement and missing history."
        ),
        "signal_definition": (
            "surprise-sign AND sign(close[entry-1]/close[entry-1-n]-1) == "
            "surprise-sign; n=5; insufficient bars or zero mom → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip when "
            "pre-entry mom disagrees, is flat, or history is short"
        ),
        "datasets": [
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "momentum_n": 5,
            "mode": "event_pre_mom_agree_hold",
            "gate": "own_pre_entry_mom_sign_agrees",
        },
    },
    {
        "logic_id": "event_margin_crowding_skip",
        "family_id": "event_margin_crowd_combo",
        "kind": "event_margin_crowding_skip",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "NEW DATASET COMBO: skip post-disclosure surprise entry when the "
            "name's last PIT margin-interest print (strictly before entry, "
            "max 14 calendar days stale) is at/above that name's PIT trailing "
            "median. Not flow_margin_pressure (not a continuous flow book) "
            "and not a sticky-approx gate."
        ),
        "thesis": (
            "PEAD is weaker when the name is already crowded in margin. Skip "
            "the event when last-known name-level LongVol+ShrtVol is at/above "
            "its PIT trailing median; missing/stale margin → skip (no ffill)."
        ),
        "signal_definition": (
            "surprise-sign; enter only if last margin print with date < "
            "entry_date and age<=14d is strictly below PIT trailing median "
            "of that name's prior prints (min_hist=20); missing/stale → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; skip entire "
            "event when margin is crowded, unformed, missing, or stale"
        ),
        "datasets": [
            "fins_summary",
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
            "stale_calendar_days": 14,
            "mode": "event_margin_crowding_skip",
            "gate": "name_margin_lt_pit_trailing_median",
        },
    },
)


def pit_median_from_pairs(
    pairs: Sequence[tuple[str, float]],
    query_dates: Sequence[str],
    *,
    min_hist: int,
) -> dict[str, float | None]:
    """PIT trailing median over a multiset of (date, value); date < query only."""
    items: list[tuple[str, float]] = []
    for d, v in pairs:
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


def _ymd(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _event_key(ev: Mapping[str, Any]) -> str:
    return f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"


def _abs_surprise_pairs(
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[tuple[str, float]]:
    from features.class_signals import earnings_surprise_proxy

    pairs: list[tuple[str, float]] = []
    for evs in (events_by_code or {}).values():
        for ev in evs:
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            surprise, _meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            if surprise is None:
                continue
            try:
                av = abs(float(surprise))
            except (TypeError, ValueError):
                continue
            if math.isfinite(av):
                pairs.append((disc, av))
    return pairs


def _attach_disc_time(
    collected: Mapping[str, Any],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Join DiscTime onto collected entries (never invent)."""
    by: dict[tuple[str, str], Any] = {}
    for code, evs in (events_by_code or {}).items():
        for ev in evs:
            disc = str(ev.get("disc_date") or "")[:10]
            if disc:
                by[(str(code), disc)] = ev.get("disc_time")
    out = dict(collected)
    entries = []
    for ev in list(collected.get("entries") or []):
        rec = dict(ev)
        rec["disc_time"] = by.get((str(ev["code"]), str(ev["disc_date"])))
        entries.append(rec)
    out["entries"] = entries
    per_code: dict[str, Any] = {}
    for code, pack in (collected.get("per_code") or {}).items():
        recs = []
        for ev in list(pack.get("entries") or []):
            rec = dict(ev)
            rec["disc_time"] = by.get((str(code), str(ev["disc_date"])))
            recs.append(rec)
        per_code[code] = {**dict(pack), "entries": recs}
    out["per_code"] = per_code
    return out


def _pre_entry_mom(
    *,
    dlist: Sequence[str],
    close_by_code: Mapping[str, float],
    entry_idx: int,
    momentum_n: int,
) -> float | None:
    """Own-name mom ending at last close strictly before entry. No look-ahead."""
    n = int(momentum_n)
    j = int(entry_idx) - 1
    i = j - n
    if i < 0 or j < 0 or j >= len(dlist):
        return None
    c0 = close_by_code.get(dlist[i])
    c1 = close_by_code.get(dlist[j])
    if c0 is None or c1 is None:
        return None
    try:
        f0 = float(c0)
        f1 = float(c1)
    except (TypeError, ValueError):
        return None
    if f0 == 0.0 or not math.isfinite(f0) or not math.isfinite(f1):
        return None
    return (f1 / f0) - 1.0


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


def _collect(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    period_start: str | None,
    period_end: str | None,
) -> dict[str, Any]:
    collected = event._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    return _attach_disc_time(collected, events_by_code)


def _base_extra(spec: Mapping[str, Any], collected: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": spec.get("kind"),
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "n_events": collected["n_events"],
        "n_eligible_pre_gate": collected["n_eligible"],
        "n_no_surprise": collected["n_no_surprise"],
        "n_no_bar_match": collected["n_no_bar"],
        "ffill_applied": False,
        "invent_fill": False,
        "promote_as_main": False,
        "go": False,
        "research_only": True,
    }


def _empty_extra_or_events(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    extra: Mapping[str, Any],
    empty_dataset: bool,
    empty_reason: str,
) -> dict[str, Any] | None:
    dates = list(collected["calendar"])
    if empty_dataset:
        return {
            "status": "missing_extra_dataset",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": empty_reason,
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
    return None


def _finish_event_book(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    accept: Mapping[str, bool],
    extra: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    dates = list(collected["calendar"])
    held = event._held_from_event_entries(collected, accept=accept)
    pack = held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
    )
    pack["data_path"] = extra.get("data_path")
    pack["new_unique_logic"] = True
    pack["catalog"] = False
    pack["promote_as_main"] = False
    pack["go"] = False
    return pack


def evaluate_large_surprise_event_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only when |surprise| ≥ PIT trailing median."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "min_hist": min_hist,
        "gate": "abs_surprise_ge_pit_trailing_median",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
    }
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=False,
        empty_reason="",
    )
    if blocked:
        return blocked

    pairs = _abs_surprise_pairs(events_by_code)
    query = sorted({e["disc_date"] for e in collected["entries"]})
    med_by = pit_median_from_pairs(pairs, query, min_hist=min_hist)
    accept: dict[str, bool] = {}
    n_skip_unformed = 0
    n_skip_small = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        med = med_by.get(ev["disc_date"])
        if med is None:
            accept[key] = False
            n_skip_unformed += 1
            continue
        if abs(float(ev["surprise"])) < float(med):
            accept[key] = False
            n_skip_small += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_small_surprise": n_skip_small,
            "n_abs_surprise_history": len(pairs),
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


def evaluate_afterclose_only_event_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only for DiscTime ≥ session close (no invent)."""
    from features.class_signals import parse_disc_time_hhmmss, session_close_hhmmss

    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "gate": "disctime_ge_session_close",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
    }
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=False,
        empty_reason="",
    )
    if blocked:
        return blocked

    accept: dict[str, bool] = {}
    n_skip_missing = 0
    n_skip_preclose = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        dt = parse_disc_time_hhmmss(ev.get("disc_time"))
        if dt is None:
            accept[key] = False
            n_skip_missing += 1
            continue
        close_clock = session_close_hhmmss(str(ev["disc_date"]))
        if dt < close_clock:
            accept[key] = False
            n_skip_preclose += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_missing_disctime": n_skip_missing,
            "n_skip_preclose": n_skip_preclose,
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


def evaluate_event_pre_mom_agree_hold_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold only when own pre-entry mom sign agrees."""
    from features.class_signals import sign_from_numeric

    params = dict(spec.get("params") or {})
    mom_n = int(spec.get("momentum_n") or params.get("momentum_n") or 5)
    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "momentum_n": mom_n,
        "gate": "own_pre_entry_mom_sign_agrees",
        "extra_dataset": "fins_summary",
        "data_path": "local_real_mirrors+local_sqlite_fins_summary",
    }
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=False,
        empty_reason="",
    )
    if blocked:
        return blocked

    accept: dict[str, bool] = {}
    n_skip_hist = 0
    n_skip_disagree = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        code = ev["code"]
        pack = (collected.get("per_code") or {}).get(code) or {}
        dlist = list(pack.get("dlist") or [])
        mom = _pre_entry_mom(
            dlist=dlist,
            close_by_code=collected["close_by"].get(code) or {},
            entry_idx=int(ev["entry_idx"]),
            momentum_n=mom_n,
        )
        mom_sign = sign_from_numeric(mom)
        if mom is None or mom_sign is None or mom_sign == 0.0:
            accept[key] = False
            n_skip_hist += 1
            continue
        if float(mom_sign) != float(ev["sign"]):
            accept[key] = False
            n_skip_disagree += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_mom_history": n_skip_hist,
            "n_skip_mom_disagree": n_skip_disagree,
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


def evaluate_event_margin_crowding_skip_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    margin_by_code: Mapping[str, Mapping[str, float]] | None,
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Event surprise hold skipped when name-level margin is PIT-crowded.

    Last margin print must have date < entry_date and age ≤ stale_calendar_days.
    No ffill across longer gaps. Missing series → incomplete (not approximated).
    """
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    stale_days = int(
        spec.get("stale_calendar_days") or params.get("stale_calendar_days") or 14
    )
    collected = _collect(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_base_extra(spec, collected),
        "min_hist": min_hist,
        "stale_calendar_days": stale_days,
        "gate": "name_margin_lt_pit_trailing_median",
        "extra_dataset": "fins_summary+markets_margin_interest",
        "data_path": "local_real_mirrors+local_sqlite_fins+margin",
    }
    margin_ok = bool(margin_by_code) and any(
        bool(v) for v in (margin_by_code or {}).values()
    )
    blocked = _empty_extra_or_events(
        spec=spec,
        collected=collected,
        extra=extra,
        empty_dataset=not margin_ok,
        empty_reason=(
            "markets_margin_interest series empty — cannot apply name-level "
            "margin crowding PIT gate. Not approximated."
        ),
    )
    if blocked:
        return blocked

    accept: dict[str, bool] = {}
    n_skip_missing = 0
    n_skip_stale = 0
    n_skip_unformed = 0
    n_skip_crowded = 0
    n_entered = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        series = dict((margin_by_code or {}).get(ev["code"]) or {})
        last = _last_print_before(series, ev["entry_date"])
        if last is None:
            accept[key] = False
            n_skip_missing += 1
            continue
        last_d, last_v = last
        age = (_ymd(ev["entry_date"]) - _ymd(last_d)).days
        if age > int(stale_days):
            accept[key] = False
            n_skip_stale += 1
            continue
        med_by = event.pit_median_on_dates(
            series, [ev["entry_date"]], min_hist=min_hist
        )
        med = med_by.get(ev["entry_date"])
        if med is None:
            accept[key] = False
            n_skip_unformed += 1
            continue
        if float(last_v) >= float(med):
            accept[key] = False
            n_skip_crowded += 1
            continue
        accept[key] = True
        n_entered += 1
    extra.update(
        {
            "n_entered": n_entered,
            "n_skip_missing_margin": n_skip_missing,
            "n_skip_stale_margin": n_skip_stale,
            "n_skip_median_unformed": n_skip_unformed,
            "n_skip_margin_crowded": n_skip_crowded,
        }
    )
    return _finish_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
    )


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

