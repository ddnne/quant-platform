"""Unique-logic evaluators (candidate-grade daily MTM).

Does not promote / GO / retune pins.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from research.unique_logic.catalog import yaml_unique_rows
from research.unique_logic import event

NEW_LS_VARIANTS: tuple[dict[str, Any], ...] = tuple(
    yaml_unique_rows(
        logic_ids=(
            "event_funding_easy_short",
            "event_funding_stress_ls",
            "surprise_xs_rank_flip",
        )
    )
)


_event_key = event._event_key


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
        **event._base_extra(spec, collected),
        "min_hist": min_hist,
        "n_eligible_pre_gate": collected["n_eligible"],
        "extra_dataset": "fins_summary+jsda_tokyo_repo_rates",
        "data_path": "local_real_mirrors+local_sqlite_fins+repo",
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
        return event._no_events_pack(spec, extra, n_days=len(dates))
    return None


_finish_signed_event_book = event._finish_event_book


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
    pack["occupancy_vs_parent"] = "same_as_rank_hold"
    pack["sign_flip_is_not_a_kill"] = True
    return pack

