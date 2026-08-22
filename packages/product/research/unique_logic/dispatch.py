"""Dispatch unique_logic evaluators without going through factory period-net."""
from __future__ import annotations

from typing import Any, Mapping

from research.unique_logic import (
    adaptive,
    cross_section,
    cs_overlays,
    event,
    event_filters,
    event_sides,
)


def evaluate_logic_daily_mtm(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    events: Mapping[str, Any],
    margin_by_code: Mapping[str, Mapping[str, float]],
    topix_by_date: Mapping[str, float],
    one_way_cost: float,
    period_start: str | None = None,
    period_end: str | None = None,
    adv_by_code: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Call the candidate-grade daily MTM evaluator for ``spec['logic_id']``."""
    lid = str(spec.get("logic_id") or "")
    spec_l = dict(spec)
    if adv_by_code:
        extra = dict(spec_l.get("extra") or {})
        extra["adv_by_code"] = dict(adv_by_code)
        spec_l["extra"] = extra
    spec = spec_l
    kw = {"spec": spec, "one_way_cost": one_way_cost}
    adv_token = None
    if adv_by_code:
        from research.daily_path_eval import set_held_book_adv

        adv_token = set_held_book_adv(adv_by_code)
    try:
        return _dispatch_body(lid, spec, kw, bars, overnight, curve, events, margin_by_code, topix_by_date, period_start, period_end)
    finally:
        if adv_token is not None:
            from research.daily_path_eval import reset_held_book_adv

            reset_held_book_adv(adv_token)


def _dispatch_body(lid, spec, kw, bars, overnight, curve, events, margin_by_code, topix_by_date, period_start, period_end):

    if lid == "event_funding_stress_skip":
        return event.evaluate_event_funding_stress_skip_daily_mtm(
            bars, events, overnight, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "curve_steep_event_confirm":
        return event.evaluate_curve_steep_event_confirm_daily_mtm(
            bars, events, curve, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "disclosure_cluster_mom_gate":
        return event.evaluate_disclosure_cluster_mom_gate_daily_mtm(bars, events, **kw)
    if lid == "surprise_xs_rank_hold":
        return event.evaluate_surprise_xs_rank_hold_daily_mtm(
            bars, events, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "large_surprise_event_hold":
        return event_filters.evaluate_large_surprise_event_hold_daily_mtm(
            bars, events, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "afterclose_only_event_hold":
        return event_filters.evaluate_afterclose_only_event_hold_daily_mtm(
            bars, events, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "event_pre_mom_agree_hold":
        return event_filters.evaluate_event_pre_mom_agree_hold_daily_mtm(
            bars, events, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "event_margin_crowding_skip":
        return event_filters.evaluate_event_margin_crowding_skip_daily_mtm(
            bars,
            events,
            margin_by_code,
            period_start=period_start,
            period_end=period_end,
            **kw,
        )
    if lid == "event_funding_easy_short":
        return event_sides.evaluate_event_funding_easy_short_daily_mtm(
            bars, events, overnight, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "event_funding_stress_ls":
        return event_sides.evaluate_event_funding_stress_ls_daily_mtm(
            bars, events, overnight, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "surprise_xs_rank_flip":
        return event_sides.evaluate_surprise_xs_rank_flip_daily_mtm(
            bars, events, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "funding_impulse_cs_tilt":
        return cross_section.evaluate_funding_impulse_cs_tilt_daily_mtm(
            bars, overnight, **kw
        )
    if lid == "curve_steepen_impulse_cs":
        return cross_section.evaluate_curve_steepen_impulse_cs_daily_mtm(
            bars, curve, **kw
        )
    if lid == "xs_margin_delta_rank":
        return cross_section.evaluate_xs_margin_delta_rank_daily_mtm(
            bars, margin_by_code, **kw
        )
    if lid == "idio_mom_macro_impulse":
        return cross_section.evaluate_idio_mom_macro_impulse_daily_mtm(
            bars, topix_by_date, **kw
        )
    if lid == "overnight_level_cs_tilt":
        return cs_overlays.evaluate_overnight_level_cs_tilt_daily_mtm(
            bars, overnight, **kw
        )
    if lid == "overnight_easy_cs_follow":
        return cs_overlays.evaluate_overnight_level_cs_tilt_daily_mtm(
            bars, overnight, **kw
        )
    if lid == "month_end_cs_fade":
        return cs_overlays.evaluate_month_end_cs_fade_daily_mtm(bars, **kw)
    if lid == "xs_low_vol_mom":
        return cs_overlays.evaluate_xs_low_vol_mom_daily_mtm(bars, **kw)
    if lid == "repo_3m_level_cs":
        return cs_overlays.evaluate_repo_3m_level_cs_daily_mtm(bars, curve, **kw)
    if lid == "event_funding_adaptive_side":
        return adaptive.evaluate_event_funding_adaptive_side_daily_mtm(
            bars, events, overnight, period_start=period_start, period_end=period_end, **kw
        )
    if lid == "surprise_xs_rank_adaptive":
        return adaptive.evaluate_surprise_xs_rank_adaptive_daily_mtm(
            bars, events, period_start=period_start, period_end=period_end, **kw
        )
    from research.unique_logic.event_combos import COMBO_LOGIC_IDS, evaluate_combo_daily_mtm

    if lid in COMBO_LOGIC_IDS:
        return evaluate_combo_daily_mtm(
            spec,
            bars=bars,
            overnight=overnight,
            curve=curve,
            events=events,
            margin_by_code=margin_by_code,
            topix_by_date=topix_by_date,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
            adv_by_code=adv_by_code,
        )
    return {
        "status": "unknown_logic",
        "logic_id": lid,
        "daily_path_complete": False,
        "incomplete_reason": f"no catalog dispatch for {lid}",
    }
