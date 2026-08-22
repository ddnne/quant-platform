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
)
from research.unique_logic.constants import (
    ALWAYS_ON_OCCUPANCY_WARN,
    KNOWN_DEMOTED_OR_WEAK,
    KNOWN_WEAK_THESIS,
    LOGIC_CATALOG_HEADLINE_BAN,
    EVENT_LOGIC_IDS,
    EVENT_FILTER_LOGIC_IDS,
)
from research.unique_logic import event

PARENT_LOGIC_IDS: tuple[str, ...] = (
    "event_funding_stress_skip",
    "surprise_xs_rank_hold",
)


NEW_LS_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_easy_short",
        "family_id": "event_funding_combo",
        "kind": "event_funding_easy_short",
        "parent_logic_id": "event_funding_stress_skip",
        "variant_kind": "sign_flip_short_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "SIGN-FLIP / SHORT SIDE of event_funding_stress_skip: same easy-"
            "funding occupancy, take −surprise-sign hold (not a kill of the "
            "parent; window sign-flip is a side table, not a discard)."
        ),
        "thesis": (
            "If post-earnings surprise drift under easy Tokyo overnight repo "
            "is window-unstable in sign, the short side of the same skip book "
            "is the other side of that table — not evidence to kill funding."
        ),
        "signal_definition": (
            "same PIT overnight-lt-median gate as event_funding_stress_skip; "
            "hold −surprise sign; missing overnight → skip (no ffill)"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; enter only when "
            "funding is easy; position is opposite of surprise sign"
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
            "mode": "funding_easy_short",
            "gate": "overnight_lt_pit_trailing_median",
            "side": "short_surprise",
        },
    },
    {
        "logic_id": "event_funding_stress_ls",
        "family_id": "event_funding_combo",
        "kind": "event_funding_stress_ls",
        "parent_logic_id": "event_funding_stress_skip",
        "variant_kind": "conditional_ls",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "CONDITIONAL L/S: keep surprise-sign when overnight is easy; take "
            "opposite only under funding stress. Occupancy expands vs skip "
            "(does not collapse). Missing overnight still skip (no ffill)."
        ),
        "thesis": (
            "Funding-stress is a side switch, not a skip-to-empty. Stay in "
            "the event book under both easy and stress overnight regimes; "
            "flip only the surprise sign under stress."
        ),
        "signal_definition": (
            "overnight present and PIT median formed; +surprise if overnight "
            "< median, −surprise if overnight >= median; missing → skip"
        ),
        "position_rule": (
            "PIT post_hold after first non-look-ahead close; original sign "
            "when easy, opposite only under stress; occupancy = classified "
            "events (easy + stress)"
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
            "mode": "funding_stress_ls",
            "gate": "overnight_present_pit_median",
            "side": "original_easy_opposite_stress",
        },
    },
    {
        "logic_id": "surprise_xs_rank_flip",
        "family_id": "surprise_xs_rank",
        "kind": "surprise_xs_rank_flip",
        "parent_logic_id": "surprise_xs_rank_hold",
        "variant_kind": "sign_flip_short_side",
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "headline": True,
        "why_unique": (
            "SIGN-FLIP / SHORT SIDE of surprise_xs_rank_hold: same ranked-day "
            "occupancy; long low-surprise / short high-surprise. Not a kill of "
            "the parent; window sign-flip is a side table."
        ),
        "thesis": (
            "Relative-surprise rank is window-unstable in sign. The flipped "
            "CS book is the other side of that table, with occupancy held."
        ),
        "signal_definition": (
            "CS rank of surprise among names whose PIT event entry is inside "
            "the last post_hold_days sessions; flip rank signs; <2 names → "
            "flat (no invent)"
        ),
        "position_rule": (
            "balanced L/S on flipped surprise ranks for currently-in-window "
            "names; names with no recent PIT disclosure stay flat"
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
            "mode": "surprise_xs_rank_flip",
            "sign_flip": True,
        },
    },
)


def _event_key(ev: Mapping[str, Any]) -> str:
    return f"{ev['code']}|{ev['entry_date']}|{ev['disc_date']}"


def classify_funding_entries(
    collected: Mapping[str, Any],
    overnight_by_date: Mapping[str, float],
    *,
    min_hist: int,
) -> dict[str, Any]:
    """PIT overnight vs trailing median. Missing overnight → skip (no ffill)."""
    entry_dates = sorted({e["entry_date"] for e in collected["entries"]})
    med_by = event.pit_median_on_dates(
        overnight_by_date, entry_dates, min_hist=min_hist
    )
    easy: dict[str, bool] = {}
    classified: dict[str, bool] = {}
    sign_mult: dict[str, float] = {}
    n_skip_missing = 0
    n_skip_no_median = 0
    n_easy = 0
    n_stress = 0
    for ev in collected["entries"]:
        key = _event_key(ev)
        d = ev["entry_date"]
        on = overnight_by_date.get(d)
        if on is None:
            n_skip_missing += 1
            continue
        med = med_by.get(d)
        if med is None:
            n_skip_no_median += 1
            continue
        classified[key] = True
        if float(on) >= float(med):
            n_stress += 1
            sign_mult[key] = -1.0
        else:
            n_easy += 1
            easy[key] = True
            sign_mult[key] = 1.0
    return {
        "easy": easy,
        "classified": classified,
        "sign_mult": sign_mult,
        "n_skip_missing": n_skip_missing,
        "n_skip_no_median": n_skip_no_median,
        "n_easy": n_easy,
        "n_stress": n_stress,
    }


def _funding_base_extra(
    spec: Mapping[str, Any], collected: Mapping[str, Any], *, min_hist: int
) -> dict[str, Any]:
    return {
        "kind": spec.get("kind"),
        "variant_kind": spec.get("variant_kind"),
        "parent_logic_id": spec.get("parent_logic_id"),
        "new_unique_logic": True,
        "catalog": False,
        "catalog_map": None,
        "post_hold_days": collected["hold_days"],
        "entry_mode": collected["entry_mode"],
        "min_hist": min_hist,
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
        "sign_flip_is_not_a_kill": True,
    }


def _blocked_overnight_or_events(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    overnight_by_date: Mapping[str, float],
    extra: Mapping[str, Any],
) -> dict[str, Any] | None:
    dates = list(collected["calendar"])
    if not overnight_by_date:
        return {
            "status": "missing_overnight_series",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": (
                "jsda_tokyo_repo_rates overnight series empty — cannot apply "
                "funding L/S PIT gate. Not approximated."
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
    return None


def _finish_signed_event_book(
    *,
    spec: Mapping[str, Any],
    collected: Mapping[str, Any],
    accept: Mapping[str, bool],
    extra: Mapping[str, Any],
    one_way_cost: float,
    sign_mult_by_key: Mapping[str, float] | None = None,
    repo_by_date: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    dates = list(collected["calendar"])
    held = event._held_from_event_entries(
        collected, accept=accept, sign_mult_by_key=sign_mult_by_key
    )
    pack = held_book_daily_mtm(
        held_by_code_date=held,
        close_by=collected["close_by"],
        dates=dates,
        hold_days=int(collected["hold_days"]),
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra=extra,
        repo_by_date=repo_by_date,
    )
    pack["data_path"] = extra.get("data_path")
    pack["new_unique_logic"] = True
    pack["catalog"] = False
    pack["promote_as_main"] = False
    pack["go"] = False
    pack["sign_flip_is_not_a_kill"] = True
    return pack


def evaluate_event_funding_easy_short_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Easy-funding occupancy of skip, flipped surprise sign."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = event._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_funding_base_extra(spec, collected, min_hist=min_hist),
        "gate": "overnight_lt_pit_trailing_median",
        "side": "short_surprise",
    }
    blocked = _blocked_overnight_or_events(
        spec=spec,
        collected=collected,
        overnight_by_date=overnight_by_date,
        extra=extra,
    )
    if blocked:
        return blocked
    gate = classify_funding_entries(
        collected, overnight_by_date, min_hist=min_hist
    )
    accept = dict(gate["easy"])
    sign_mult = {k: -1.0 for k in accept}
    extra.update(
        {
            "n_entered": int(gate["n_easy"]),
            "n_easy_entered": int(gate["n_easy"]),
            "n_stress_entered": 0,
            "n_skip_missing_overnight": int(gate["n_skip_missing"]),
            "n_skip_median_unformed": int(gate["n_skip_no_median"]),
            "n_skip_funding_stress": int(gate["n_stress"]),
            "occupancy_vs_parent": "same_as_skip",
        }
    )
    return _finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=sign_mult,
    )


def evaluate_event_funding_stress_ls_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    overnight_by_date: Mapping[str, float],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Conditional L/S: original when easy, opposite only under stress."""
    params = dict(spec.get("params") or {})
    min_hist = int(spec.get("min_hist") or params.get("min_hist") or 20)
    collected = event._collect_event_entries(
        bars_by_code,
        events_by_code,
        spec=spec,
        period_start=period_start,
        period_end=period_end,
    )
    extra = {
        **_funding_base_extra(spec, collected, min_hist=min_hist),
        "gate": "overnight_present_pit_median",
        "side": "original_easy_opposite_stress",
    }
    blocked = _blocked_overnight_or_events(
        spec=spec,
        collected=collected,
        overnight_by_date=overnight_by_date,
        extra=extra,
    )
    if blocked:
        return blocked
    gate = classify_funding_entries(
        collected, overnight_by_date, min_hist=min_hist
    )
    extra.update(
        {
            "n_entered": int(gate["n_easy"]) + int(gate["n_stress"]),
            "n_easy_entered": int(gate["n_easy"]),
            "n_stress_entered": int(gate["n_stress"]),
            "n_skip_missing_overnight": int(gate["n_skip_missing"]),
            "n_skip_median_unformed": int(gate["n_skip_no_median"]),
            "n_skip_funding_stress": 0,
            "occupancy_vs_parent": "expanded_vs_skip",
        }
    )
    return _finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=dict(gate["classified"]),
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=dict(gate["sign_mult"]),
    )


def evaluate_surprise_xs_rank_flip_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    """Same occupancy as surprise_xs_rank_hold; flipped rank signs."""
    flipped = dict(spec)
    params = dict(spec.get("params") or {})
    params["sign_flip"] = True
    flipped["params"] = params
    flipped["sign_flip"] = True
    pack = event.evaluate_surprise_xs_rank_hold_daily_mtm(
        bars_by_code,
        events_by_code,
        spec=flipped,
        one_way_cost=one_way_cost,
        period_start=period_start,
        period_end=period_end,
    )
    pack["logic_id"] = spec["logic_id"]
    pack["kind"] = spec.get("kind")
    pack["variant_kind"] = spec.get("variant_kind")
    pack["parent_logic_id"] = spec.get("parent_logic_id")
    pack["sign_flip"] = True
    pack["occupancy_vs_parent"] = "same_as_rank_hold"
    pack["sign_flip_is_not_a_kill"] = True
    pack["promote_as_main"] = False
    pack["go"] = False
    return pack


def _parent_spec(logic_id: str) -> dict[str, Any]:
    for s in event.NEW_UNIQUE_LOGIC:
        if s["logic_id"] == logic_id:
            return dict(s)
    raise KeyError(logic_id)


def proposals_for_factory() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in NEW_LS_VARIANTS:
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
                "parent_logic_id": spec.get("parent_logic_id"),
                "variant_kind": spec.get("variant_kind"),
            }
        )
    return out

