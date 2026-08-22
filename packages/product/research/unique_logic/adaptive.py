"""Unique-logic evaluators (candidate-grade daily MTM).

Does not promote / GO / retune pins.
"""
from __future__ import annotations

import math
from datetime import date
from statistics import median
from typing import Any, Mapping, Sequence

from research.daily_path_eval import (
    held_book_daily_mtm,
    panel_index,
    stitch_net,
)
from research.unique_logic.constants import (
    ALWAYS_ON_OCCUPANCY_WARN,
    KNOWN_DEMOTED_OR_WEAK,
    KNOWN_WEAK_THESIS,
    LOGIC_CATALOG_HEADLINE_BAN,
    EVENT_LOGIC_IDS,
    EVENT_FILTER_LOGIC_IDS,
)
from research.unique_logic import event, event_sides

TRAIL_K = 10


TRAIL_MIN = 5


ADAPTIVE_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_adaptive_side",
        "family_id": "event_funding_combo",
        "kind": "event_funding_adaptive_side",
        "parent_logic_id": "event_funding_stress_skip",
        "variant_kind": "trail_k_adaptive_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "ADAPTIVE SIDE of event_funding_stress_skip: same easy-funding "
            "occupancy; at each PIT entry pick orig vs flip from last K "
            "completed holds with hold_end < entry_date. Not a kill of the "
            "fixed L/S table."
        ),
        "thesis": (
            "Window sign-flip of easy-funding surprise is a side table. "
            "A PIT trail-K overlay can pick the recently-working side without "
            "discarding either parent."
        ),
        "signal_definition": (
            "same PIT overnight-lt-median gate as skip; sign = orig if mean "
            f"orig hold of last {TRAIL_K} completed (min {TRAIL_MIN}) >= mean "
            "flip, else flip; insufficient history → orig (no invent)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; enter only when "
            "funding is easy; side chosen from completed holds only"
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
            "trail_k": TRAIL_K,
            "trail_min": TRAIL_MIN,
            "mode": "funding_easy_adaptive_side",
            "gate": "overnight_lt_pit_trailing_median",
            "side": "trail_k_orig_vs_flip",
        },
    },
    {
        "logic_id": "surprise_xs_rank_adaptive",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_adaptive",
        "parent_logic_id": "surprise_xs_rank_hold",
        "variant_kind": "trail_k_adaptive_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "ADAPTIVE SIDE of surprise_xs_rank_hold: same ranked occupancy; "
            "each day pick orig vs flip from last K completed ranked-day orig "
            "nets with date < d. Not a kill of the parent or the flip."
        ),
        "thesis": (
            "Relative-surprise rank is window-unstable in sign. A PIT trail-K "
            "overlay sits beside orig and flip rather than killing either."
        ),
        "signal_definition": (
            "same CS surprise rank occupancy as parent; tilt = +1 if mean of "
            f"last {TRAIL_K} completed orig daily nets (min {TRAIL_MIN}) >= 0 "
            "else −1; insufficient history → orig"
        ),
        "position_rule": (
            "balanced L/S on (possibly flipped) surprise ranks for currently-"
            "in-window names; occupancy held vs parent"
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
            "trail_k": TRAIL_K,
            "trail_min": TRAIL_MIN,
            "mode": "surprise_xs_rank_adaptive",
        },
    },
)


PARENT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_stress_skip",
        "family_id": "event_funding_combo",
        "kind": "event_funding_stress_skip",
        "variant_kind": "parent_orig",
        "parent_logic_id": None,
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "min_hist": 20,
        },
        "why_unique": "W104 parent orig (fixed table, not a kill).",
    },
    {
        "logic_id": "surprise_xs_rank_hold",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_hold",
        "variant_kind": "parent_orig",
        "parent_logic_id": None,
        "params": {
            "post_hold_days": 5,
            "entry_mode": "same_day_close_if_pre_close",
            "long_frac": 0.3,
            "short_frac": 0.3,
        },
        "why_unique": "W104 parent orig (fixed table, not a kill).",
    },
)


def proposals_for_factory() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in ADAPTIVE_VARIANTS:
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


def _event_hold_end_and_raw(
    ev: Mapping[str, Any],
    collected: Mapping[str, Any],
) -> tuple[str, float] | None:
    code = str(ev["code"])
    pack = (collected.get("per_code") or {}).get(code) or {}
    dlist = list(pack.get("dlist") or [])
    idx = int(ev["entry_idx"])
    h = int(collected["hold_days"])
    if idx < 0 or idx >= len(dlist):
        return None
    end = min(idx + h, len(dlist)) - 1
    if end <= idx:
        return None
    close_by = (collected.get("close_by") or {}).get(code) or {}
    c0 = close_by.get(dlist[idx])
    c1 = close_by.get(dlist[end])
    if c0 is None or c1 is None:
        return None
    try:
        f0 = float(c0)
        f1 = float(c1)
    except (TypeError, ValueError):
        return None
    if f0 == 0.0:
        return None
    return str(dlist[end]), (f1 / f0) - 1.0


def evaluate_event_funding_adaptive_side_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Easy-funding occupancy; PIT trail-K orig vs flip side."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    trail_k = int(spec.get("trail_k") or params.get("trail_k") or TRAIL_K)
    trail_min = int(spec.get("trail_min") or params.get("trail_min") or TRAIL_MIN)
    collected = event._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **event_sides._funding_base_extra(spec, collected, min_hist=min_hist),
        "gate": "overnight_lt_pit_trailing_median",
        "side": "trail_k_orig_vs_flip",
        "trail_k": trail_k,
        "trail_min": trail_min,
        "occupancy_vs_parent": "same_as_skip",
    }
    blocked = event_sides._blocked_overnight_or_events(
        spec=spec,
        collected=collected,
        overnight_by_date=overnight_by_date,
        extra=extra,
    )
    if blocked:
        return blocked
    gate = event_sides.classify_funding_entries(
        collected, overnight_by_date, min_hist=min_hist
    )
    easy_keys = dict(gate["easy"])
    cost = 2.0 * float(one_way_cost)
    ordered = sorted(
        [e for e in collected["entries"] if easy_keys.get(event_sides._event_key(e))],
        key=lambda e: (e["entry_date"], e["code"], e["disc_date"]),
    )
    history: list[dict[str, Any]] = []
    sign_mult: dict[str, float] = {}
    n_orig = 0
    n_flip = 0
    n_default_orig = 0
    for ev in ordered:
        key = event_sides._event_key(ev)
        entry_d = str(ev["entry_date"])
        completed = [h for h in history if str(h["hold_end"]) < entry_d]
        lastk = completed[-trail_k:]
        if len(lastk) < trail_min:
            mult = 1.0
            n_default_orig += 1
        else:
            m_orig = sum(float(h["orig"]) for h in lastk) / float(len(lastk))
            m_flip = sum(float(h["flip"]) for h in lastk) / float(len(lastk))
            if m_orig >= m_flip:
                mult = 1.0
                n_orig += 1
            else:
                mult = -1.0
                n_flip += 1
        sign_mult[key] = mult
        hr = _event_hold_end_and_raw(ev, collected)
        if hr is None:
            continue
        hold_end, raw = hr
        sgn = float(ev["sign"])
        history.append(
            {
                "hold_end": hold_end,
                "orig": sgn * raw - cost,
                "flip": -sgn * raw - cost,
            }
        )
    extra.update(
        {
            "n_entered": int(gate["n_easy"]),
            "n_easy_entered": int(gate["n_easy"]),
            "n_stress_entered": 0,
            "n_skip_missing_overnight": int(gate["n_skip_missing"]),
            "n_skip_median_unformed": int(gate["n_skip_no_median"]),
            "n_skip_funding_stress": int(gate["n_stress"]),
            "n_adaptive_orig": n_orig + n_default_orig,
            "n_adaptive_flip": n_flip,
            "n_adaptive_default_orig": n_default_orig,
        }
    )
    return event_sides._finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=easy_keys,
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=sign_mult,
    )


def evaluate_surprise_xs_rank_adaptive_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Same occupancy as surprise_xs_rank_hold; PIT trail-K orig vs flip."""
    params = dict(spec.get("params") or {})
    trail_k = int(spec.get("trail_k") or params.get("trail_k") or TRAIL_K)
    trail_min = int(spec.get("trail_min") or params.get("trail_min") or TRAIL_MIN)
    orig_spec = dict(spec)
    orig_params = dict(params)
    orig_params["sign_flip"] = False
    orig_spec["params"] = orig_params
    orig_spec["sign_flip"] = False
    orig = event.evaluate_surprise_xs_rank_hold_daily_mtm(
        bars_by_code,
        events_by_code,
        spec=orig_spec,
        one_way_cost=one_way_cost,
        period_start=period_start,
        period_end=period_end,
    )
    orig["logic_id"] = spec["logic_id"]
    orig["kind"] = spec.get("kind")
    orig["variant_kind"] = spec.get("variant_kind")
    orig["parent_logic_id"] = spec.get("parent_logic_id")
    orig["occupancy_vs_parent"] = "same_as_rank_hold"
    orig["sign_flip_is_not_a_kill"] = True
    orig["promote_as_main"] = False
    orig["go"] = False
    orig["adaptive_side"] = True
    orig["trail_k"] = trail_k
    orig["trail_min"] = trail_min
    if orig.get("status") != "ok":
        return orig

    dates = list(orig.get("dates") or [])
    net = list(orig.get("net_daily") or [])
    gross = list(orig.get("gross_daily") or [])
    if not dates or not net or len(gross) != len(net):
        orig["status"] = "adaptive_path_incomplete"
        orig["daily_path_complete"] = False
        orig["incomplete_reason"] = (
            "orig surprise path missing gross/net series — adaptive overlay "
            "not approximated"
        )
        return orig

    hist: list[float] = []
    n_orig = n_flip = n_def = 0
    adapt_net: list[float] = []
    adapt_gross: list[float] = []
    for i, _d in enumerate(dates):
        lastk = hist[-trail_k:]
        if len(lastk) < trail_min:
            t = 1.0
            n_def += 1
        elif sum(lastk) / float(len(lastk)) >= 0.0:
            t = 1.0
            n_orig += 1
        else:
            t = -1.0
            n_flip += 1
        g = float(gross[i])
        n = float(net[i])
        cost = g - n
        adapt_g = t * g
        adapt_n = adapt_g - cost
        adapt_gross.append(adapt_g)
        adapt_net.append(adapt_n)
        hist.append(n)
    stitched = stitch_net(adapt_net, dates)
    orig["net_daily"] = adapt_net
    orig["gross_daily"] = adapt_gross
    orig["n_adaptive_orig"] = n_orig + n_def
    orig["n_adaptive_flip"] = n_flip
    orig["n_adaptive_default_orig"] = n_def
    orig.update(
        {
            k: stitched.get(k)
            for k in (
                "daily_path_DD",
                "dd_duration",
                "recovery_days",
                "recovered",
                "total_return_net",
                "equities",
            )
            if k in stitched
        }
    )
    orig["total_ret_net"] = stitched.get("total_return_net")
    orig["mean_net_daily"] = (
        (sum(adapt_net) / float(len(adapt_net))) if adapt_net else None
    )
    orig["status"] = "ok"
    orig["daily_path_complete"] = True
    return orig

