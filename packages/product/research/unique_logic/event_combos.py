"""New unique theses as combo gates (not numeric variants).

CF Worker eventHeld / gatedCsHeld is the candidate-grade path.
This module declares the specs and a Python fallback that applies the
same gate names. Does not promote / GO.
"""
from __future__ import annotations

from typing import Any, Mapping

from research.daily_path_eval import held_book_daily_mtm, panel_index
from research.unique_logic.constants import CF_NEW_THESIS_IDS
from research.unique_logic import event, event_filters, event_sides

COMBO_LOGIC_IDS: frozenset[str] = frozenset(CF_NEW_THESIS_IDS)

# thesis, family, kind, event_gates, side, cs_gate
_SPECS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "event_funding_tight_fade",
        "family_id": "event_funding_combo",
        "thesis": "When Tokyo overnight is tight (at/above PIT median), fade surprise rather than skip.",
        "gates": ("tight_funding",),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "event_curve_invert_fade",
        "family_id": "event_macro_curve_combo",
        "thesis": "Inverted or flat repo curve (3M-ON <= 0) fades post-event surprise.",
        "gates": ("invert_curve",),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "event_afterclose_easy_funding",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close disclosure plus easy overnight: overnight info with cheap carry.",
        "gates": ("afterclose", "easy_funding"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_large_surprise_easy_funding",
        "family_id": "large_surprise_filter",
        "thesis": "Large-surprise PEAD only when overnight funding is easy.",
        "gates": ("large_surprise", "easy_funding"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_pre_mom_easy_funding",
        "family_id": "event_mom_agree_combo",
        "thesis": "Pre-event mom agrees with surprise and funding is easy.",
        "gates": ("pre_mom", "easy_funding"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_margin_or_funding_skip",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Skip PEAD when name is crowded in margin OR overnight is tight.",
        "gates": ("uncrowded_margin", "easy_funding"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_large_surprise_steep_curve",
        "family_id": "event_macro_curve_combo",
        "thesis": "Large surprise confirmed only when the repo curve is steep.",
        "gates": ("large_surprise", "steep_curve"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_afterclose_steep_curve",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close PEAD confirmed by a steep term-funding curve.",
        "gates": ("afterclose", "steep_curve"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_tight_and_crowded_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Tight overnight AND crowded margin: fade the surprise (squeeze/unwind).",
        "gates": ("tight_funding", "crowded_margin"),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "event_cluster_easy_pead",
        "family_id": "disclosure_cluster_gate",
        "thesis": "Own-sign PEAD only in an earnings-cluster and easy overnight.",
        "gates": ("cluster", "easy_funding"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "surprise_xs_rank_easy_funding",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank only on easy-overnight dates.",
        "gates": ("easy_funding",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_rank_steep_curve",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank only when the repo curve is steep.",
        "gates": ("steep_curve",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "event_pre_mom_steep_curve",
        "family_id": "event_mom_agree_combo",
        "thesis": "Pre-mom-confirmed PEAD only in a steep curve regime.",
        "gates": ("pre_mom", "steep_curve"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_large_surprise_afterclose",
        "family_id": "large_surprise_filter",
        "thesis": "Large after-close surprises: size plus overnight information.",
        "gates": ("large_surprise", "afterclose"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_margin_uncrowded_steep",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Uncrowded names plus steep curve: PEAD with room and carry.",
        "gates": ("uncrowded_margin", "steep_curve"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_easy_funding_curve_steep",
        "family_id": "event_macro_curve_combo",
        "thesis": "Easy overnight AND steep 3M-ON: carry-friendly PEAD occupancy.",
        "gates": ("easy_funding", "steep_curve"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "overnight_tight_cs_fade",
        "family_id": "overnight_level_cs",
        "thesis": "When overnight is tight, fade CS momentum (not follow).",
        "cs_gate": "overnight_tight_invert",
        "kind": "cs",
    },
    {
        "logic_id": "curve_invert_cs_fade",
        "family_id": "curve_steepen_impulse_cs",
        "thesis": "Inverted repo curve fades CS momentum.",
        "cs_gate": "curve_invert_invert",
        "kind": "cs",
    },
    {
        "logic_id": "xs_high_vol_fade",
        "family_id": "xs_low_vol_mom",
        "thesis": "Fade CS winners (high-vol unwind), opposite of low-vol mom follow.",
        "cs_gate": "always_invert",
        "kind": "cs",
    },
    {
        "logic_id": "month_start_cs_follow",
        "family_id": "month_end_cs",
        "thesis": "Follow CS momentum in the first sessions of the month (not month-end fade).",
        "cs_gate": "month_start",
        "kind": "cs",
    },
    {
        "logic_id": "rate_change_cs_confirm",
        "family_id": "funding_impulse_cs",
        "thesis": "CS mom only on dates when overnight rose versus the prior print.",
        "cs_gate": "overnight_up",
        "kind": "cs",
    },
    {
        "logic_id": "flow_price_margin_triple",
        "family_id": "xs_margin_delta",
        "thesis": "CS mom only when name-level margin is de-crowding (flow confirms price).",
        "cs_gate": "margin_decrowd",
        "kind": "cs",
    },
    {
        "logic_id": "opt225_skew_cs_gate",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom only when NKY 225 put skew is at/above its PIT median.",
        "cs_gate": "opt225_skew_high",
        "kind": "cs",
    },
    {
        "logic_id": "nky_vol_term_cs_gate",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom only when index vol term ratio is at/above its PIT median.",
        "cs_gate": "nky_term_high",
        "kind": "cs",
    },
    {
        "logic_id": "opt225_spread_cs_tilt",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom only when ATM-BaseVol spread is wide versus PIT median.",
        "cs_gate": "opt225_spread_wide",
        "kind": "cs",
    },
    {
        "logic_id": "repo_3m_change_cs",
        "family_id": "repo_3m_level_cs",
        "thesis": "CS mom tilt on 3M repo CHANGE, not the 3M level.",
        "cs_gate": "repo_3m_up",
        "kind": "cs",
    },
    {
        "logic_id": "flow_margin_price_agree",
        "family_id": "xs_margin_delta",
        "thesis": "CS mom only when universe-average margin change agrees with the CS book.",
        "cs_gate": "margin_change_nonzero",
        "kind": "cs",
    },
    {
        "logic_id": "cs_mom_easy_funding",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom occupancy only when overnight is easy (below PIT median).",
        "cs_gate": "overnight_easy",
        "kind": "cs",
    },
    # Wave-3: time structure / flow-price disagree / rate reversal / vol nonlinear.
    {
        "logic_id": "event_skip_announce_day",
        "family_id": "afterclose_event_timing",
        "thesis": "Skip the announcement close; PEAD starts the next session (overnight info delay).",
        "gates": (),
        "side": "orig",
        "kind": "event",
        "entry_shift": 1,
    },
    {
        "logic_id": "event_late_hold_only",
        "family_id": "afterclose_event_timing",
        "thesis": "Only the last two days of the post-event hold — late drift, not announcement pop.",
        "gates": (),
        "side": "orig",
        "kind": "event",
        "hold_tail_days": 2,
    },
    {
        "logic_id": "month_end_event_skip",
        "family_id": "event_funding_combo",
        "thesis": "Skip PEAD in the last calendar days of the month (rebalance/window dressing).",
        "gates": ("month_end_skip",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_first_half_month",
        "family_id": "event_funding_combo",
        "thesis": "PEAD only in the first half of the month, when positioning is less crowded.",
        "gates": ("first_half_month",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "overnight_easing_event",
        "family_id": "event_funding_combo",
        "thesis": "PEAD only on days when overnight fell versus the prior print (funding easing).",
        "gates": ("overnight_easing",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "overnight_tightening_fade_event",
        "family_id": "event_funding_combo",
        "thesis": "Fade surprise when overnight rose versus the prior print (funding shock).",
        "gates": ("overnight_tightening",),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "event_cluster_fade",
        "family_id": "disclosure_cluster_gate",
        "thesis": "In a disclosure cluster, fade own-sign PEAD (information overload / crowding).",
        "gates": ("cluster",),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "margin_crowd_fade_event",
        "family_id": "event_margin_crowd_combo",
        "thesis": "When the name is PIT-crowded in margin, fade the surprise instead of skipping.",
        "gates": ("crowded_margin",),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "surprise_xs_month_start",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank only in the first five calendar days of the month.",
        "gates": ("first_half_month",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_fy_end",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank concentrated in late March FY-end positioning.",
        "gates": ("fy_end",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "fy_end_cs_fade",
        "family_id": "month_end_cs",
        "thesis": "Fade CS momentum in late March (Japan FY-end unwind), not generic month-end.",
        "cs_gate": "fy_end_invert",
        "kind": "cs",
    },
    {
        "logic_id": "fy_start_cs_follow",
        "family_id": "month_end_cs",
        "thesis": "Follow CS momentum in April (FY-start re-risk), opposite of FY-end fade.",
        "cs_gate": "fy_start",
        "kind": "cs",
    },
    {
        "logic_id": "curve_steep_cs_follow",
        "family_id": "curve_steepen_impulse_cs",
        "thesis": "CS mom only when 3M-ON spread is strictly positive (carry-friendly).",
        "cs_gate": "curve_steep",
        "kind": "cs",
    },
    {
        "logic_id": "overnight_p90_cs_flip",
        "family_id": "overnight_level_cs",
        "thesis": "Invert CS only in the right tail of overnight (PIT 90th pct), not at the median.",
        "cs_gate": "overnight_p90_invert",
        "kind": "cs",
    },
    {
        "logic_id": "flow_price_disagree_fade",
        "family_id": "xs_margin_delta",
        "thesis": "Fade CS when name-level margin is crowding with the price move (chase).",
        "cs_gate": "margin_crowd_chase",
        "kind": "cs",
    },
    {
        "logic_id": "nky_vol_compress_cs",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when index vol term ratio is falling (compression, not a level).",
        "cs_gate": "nky_term_compress",
        "kind": "cs",
    },
    {
        "logic_id": "opt225_skew_and_term_cs",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom only when both 225 put skew and vol term are elevated (joint crash-hedge).",
        "cs_gate": "opt225_skew_and_term",
        "kind": "cs",
    },
    {
        "logic_id": "basevol_up_day_fade",
        "family_id": "xs_low_vol_mom",
        "thesis": "Fade CS on days BaseVol rose (vol-of-vol shock), not a static level book.",
        "cs_gate": "basevol_up",
        "kind": "cs",
    },
    {
        "logic_id": "iv_below_basevol_cs",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom only when ATM IV sits below BaseVol (negative vol spread).",
        "cs_gate": "iv_below_basevol",
        "kind": "cs",
    },
    {
        "logic_id": "event_afterclose_delay2",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close disclosure, enter two sessions later (slow overnight digestion).",
        "gates": ("afterclose",),
        "side": "orig",
        "kind": "event",
        "entry_shift": 2,
    },
    {
        "logic_id": "event_skip_monday",
        "family_id": "event_calendar_gate",
        "thesis": "Skip Monday PEAD entries (weekend information dump / gap).",
        "gates": ("skip_monday",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_tue_thu_only",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only Tuesday–Thursday when the calendar is less seasonal.",
        "gates": ("tue_thu",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_friday_skip",
        "family_id": "event_calendar_gate",
        "thesis": "Skip Friday PEAD (weekend hold / reduced Monday liquidity).",
        "gates": ("friday_skip",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "fy_end_event_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade surprise in late March FY-end positioning (not a skip).",
        "gates": ("fy_end",),
        "side": "flip",
        "kind": "event",
    },
    {
        "logic_id": "fy_start_event_follow",
        "family_id": "event_calendar_gate",
        "thesis": "Follow PEAD in April FY-start re-risk, opposite of FY-end fade.",
        "gates": ("fy_start",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_midmonth_only",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only on calendar days 10–20 (away from month-turn rebalance).",
        "gates": ("midmonth",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "surprise_xs_afterclose",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank only after-close disclosures.",
        "gates": ("afterclose",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "event_easing_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD only when overnight eased AND the name is uncrowded in margin.",
        "gates": ("overnight_easing", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "cs_skip_monday",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom occupancy skips Mondays (weekend gap).",
        "cs_gate": "skip_monday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_tue_thu_follow",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom only Tuesday–Thursday.",
        "cs_gate": "tue_thu",
        "kind": "cs",
    },
    {
        "logic_id": "overnight_down_cs_follow",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom only when overnight fell versus the prior print.",
        "cs_gate": "overnight_down",
        "kind": "cs",
    },
    {
        "logic_id": "overnight_up_cs_fade",
        "family_id": "overnight_level_cs",
        "thesis": "Fade CS mom when overnight rose versus the prior print.",
        "cs_gate": "overnight_up_invert",
        "kind": "cs",
    },
    {
        "logic_id": "cs_midmonth_follow",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom only on calendar days 10–20.",
        "cs_gate": "midmonth",
        "kind": "cs",
    },
    {
        "logic_id": "cs_friday_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade CS momentum on Fridays (weekend unwind).",
        "cs_gate": "friday_invert",
        "kind": "cs",
    },
    {
        "logic_id": "cs_not_month_end",
        "family_id": "month_end_cs",
        "thesis": "CS mom occupancy skips the last three calendar days of the month.",
        "cs_gate": "not_month_end",
        "kind": "cs",
    },
    {
        "logic_id": "surprise_xs_tue_thu",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank Tuesday–Thursday only.",
        "gates": ("tue_thu",),
        "side": "orig",
        "kind": "surprise_xs",
    },
)

NEW_COMBO_LOGIC: tuple[dict[str, Any], ...] = tuple(
    {
        **s,
        "new_unique_logic": True,
        "catalog": True,
        "headline": False,
        "promote_as_main": False,
        "go": False,
        "generation_enabled": False,
        "params": {
            "post_hold_days": 5,
            "hold_days": 10,
            "momentum_n": 5,
            "min_hist": 20,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "gates": list(s.get("gates") or ()),
            "side": s.get("side") or "orig",
            "cs_gate": s.get("cs_gate"),
            "entry_shift": s.get("entry_shift") or 0,
            "hold_tail_days": s.get("hold_tail_days") or 0,
            "mode": s["logic_id"],
        },
        "datasets": [
            "equities_bars_daily",
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
        ],
        "signal_definition": s["thesis"],
        "position_rule": "PIT gates; missing sidecar → skip (no ffill / no invent)",
        "evaluator": "research.unique_logic.event_combos.evaluate_combo_daily_mtm",
    }
    for s in _SPECS
)


def spec_by_id(logic_id: str) -> dict[str, Any] | None:
    for s in NEW_COMBO_LOGIC:
        if s["logic_id"] == logic_id:
            return s
    return None


def evaluate_combo_daily_mtm(
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
) -> dict[str, Any]:
    """Python fallback for combo theses. CF Worker is the SoT path."""
    lid = str(spec.get("logic_id") or "")
    declared = spec_by_id(lid) or dict(spec)
    kind = str(declared.get("kind") or "event")
    if kind in {"event", "surprise_xs"}:
        return _eval_event_combo(
            declared,
            bars=bars,
            overnight=overnight,
            curve=curve,
            events=events,
            margin_by_code=margin_by_code,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
        )
    return _eval_cs_combo(
        declared,
        bars=bars,
        overnight=overnight,
        curve=curve,
        margin_by_code=margin_by_code,
        one_way_cost=one_way_cost,
    )


def _eval_event_combo(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    events: Mapping[str, Any],
    margin_by_code: Mapping[str, Mapping[str, float]],
    one_way_cost: float,
    period_start: str | None,
    period_end: str | None,
) -> dict[str, Any]:
    params = dict(spec.get("params") or {})
    gates = tuple(params.get("gates") or spec.get("gates") or ())
    side = str(params.get("side") or spec.get("side") or "orig")
    min_hist = int(params.get("min_hist") or 20)
    collected = event._collect_event_entries(
        bars, events, spec=spec, period_start=period_start, period_end=period_end
    )
    collected = event_filters._attach_disc_time(collected, events)
    extra: dict[str, Any] = {
        "combo_gates": list(gates),
        "side": side,
        "cf_native": True,
        "promote_as_main": False,
        "go": False,
    }
    if collected.get("n_events") == 0:
        return {
            "status": "no_events_in_shard",
            "logic_id": spec["logic_id"],
            "daily_path_complete": False,
            "incomplete_reason": "no events in shard",
            **extra,
        }
    fund = event_sides.classify_funding_entries(
        collected, overnight, min_hist=min_hist
    )
    abs_pairs = event_filters._abs_surprise_pairs(events)
    spread = dict((curve or {}).get("spread_by_date") or {})
    accept: dict[str, bool] = {}
    sign_mult: dict[str, float] = {}
    for ev in collected["entries"]:
        key = event_sides._event_key(ev)
        ok = True
        for g in gates:
            if g == "easy_funding" and not fund["easy"].get(key):
                ok = False
            elif g == "tight_funding":
                on = overnight.get(ev["entry_date"])
                med = event.pit_median_on_dates(
                    overnight, [ev["entry_date"]], min_hist=min_hist
                ).get(ev["entry_date"])
                if on is None or med is None or float(on) < float(med):
                    ok = False
            elif g == "steep_curve" and float(spread.get(ev["entry_date"]) or 0) <= 0:
                ok = False
            elif g == "invert_curve" and float(spread.get(ev["entry_date"]) or 1) > 0:
                ok = False
            elif g == "afterclose":
                t = str(ev.get("disc_time") or "").strip()
                hh = int(t[:2]) if len(t) >= 2 and t[:2].isdigit() else -1
                if hh < 15:
                    ok = False
            elif g == "large_surprise":
                prior = [a for d, a in abs_pairs if d < ev["disc_date"]]
                if len(prior) < min_hist:
                    ok = False
                else:
                    prior_s = sorted(prior)
                    mid = len(prior_s) // 2
                    med = (
                        prior_s[mid]
                        if len(prior_s) % 2
                        else (prior_s[mid - 1] + prior_s[mid]) / 2
                    )
                    if abs(float(ev["surprise"])) < med:
                        ok = False
            elif g == "uncrowded_margin":
                series = dict((margin_by_code or {}).get(ev["code"]) or {})
                last = event_filters._last_print_before(series, ev["entry_date"])
                if last is None:
                    ok = False
                else:
                    med_by = event.pit_median_on_dates(
                        series, [ev["entry_date"]], min_hist=min_hist
                    )
                    med = med_by.get(ev["entry_date"])
                    if med is None or float(last[1]) >= float(med):
                        ok = False
            elif g == "crowded_margin":
                series = dict((margin_by_code or {}).get(ev["code"]) or {})
                last = event_filters._last_print_before(series, ev["entry_date"])
                med_by = event.pit_median_on_dates(
                    series, [ev["entry_date"]], min_hist=min_hist
                )
                med = med_by.get(ev["entry_date"])
                if last is None or med is None or float(last[1]) < float(med):
                    ok = False
            elif g == "pre_mom":
                pack = (collected.get("per_code") or {}).get(ev["code"]) or {}
                mom = event_filters._pre_entry_mom(
                    dlist=list(pack.get("dlist") or []),
                    close_by_code=(collected.get("close_by") or {}).get(ev["code"]) or {},
                    entry_idx=int(ev["entry_idx"]),
                    momentum_n=5,
                )
                if mom is None or mom == 0 or (1 if mom > 0 else -1) != int(ev["sign"]):
                    ok = False
            elif g == "cluster":
                disc_dates = sorted(
                    {str(e.get("disc_date") or "")[:10] for e in collected["entries"]}
                )
                entry_d = str(ev["entry_date"])[:10]
                n_disc = sum(
                    1
                    for x in disc_dates
                    if x < entry_d and x >= _add_days(entry_d, -5)
                )
                hist = {
                    dd: float(
                        sum(1 for x in disc_dates if x < dd and x >= _add_days(dd, -5))
                    )
                    for dd in disc_dates
                    if dd < entry_d
                }
                med_c = event.pit_median_on_dates(hist, [entry_d], min_hist=10).get(
                    entry_d
                )
                if med_c is None or n_disc < float(med_c):
                    ok = False
            elif g == "first_half_month":
                if str(ev["entry_date"])[8:10] > "15":
                    ok = False
            elif g == "month_end_skip":
                if str(ev["entry_date"])[8:10] >= "28":
                    ok = False
            elif g == "fy_end":
                if not (
                    str(ev["entry_date"])[5:7] == "03"
                    and str(ev["entry_date"])[8:10] >= "15"
                ):
                    ok = False
            elif g == "fy_start":
                if str(ev["entry_date"])[5:7] != "04":
                    ok = False
            elif g == "overnight_easing":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                if not prevs or overnight.get(d) is None:
                    ok = False
                elif float(overnight[d]) >= float(overnight[prevs[-1]]):
                    ok = False
            elif g == "overnight_tightening":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                if not prevs or overnight.get(d) is None:
                    ok = False
                elif float(overnight[d]) <= float(overnight[prevs[-1]]):
                    ok = False
            elif g == "skip_monday":
                if _weekday(str(ev["entry_date"])) == 0:
                    ok = False
            elif g == "tue_thu":
                if _weekday(str(ev["entry_date"])) not in {1, 2, 3}:
                    ok = False
            elif g == "friday_skip":
                if _weekday(str(ev["entry_date"])) == 4:
                    ok = False
            elif g == "midmonth":
                dd = str(ev["entry_date"])[8:10]
                if dd < "10" or dd > "20":
                    ok = False
        accept[key] = ok
        sign_mult[key] = -1.0 if side == "flip" else 1.0
    shift = int(params.get("entry_shift") or spec.get("entry_shift") or 0)
    tail = int(params.get("hold_tail_days") or spec.get("hold_tail_days") or 0)
    if shift or tail:
        new_entries = []
        per = dict(collected.get("per_code") or {})
        for ev in collected["entries"]:
            rec = dict(ev)
            pack = per.get(rec["code"]) or {}
            dlist = list(pack.get("dlist") or [])
            i0 = int(rec["entry_idx"]) + shift
            if tail:
                end0 = min(int(rec["entry_idx"]) + int(collected["hold_days"]), len(dlist))
                i0 = max(i0, end0 - tail)
            if i0 < 0 or i0 >= len(dlist):
                accept[event_sides._event_key(ev)] = False
                continue
            rec["entry_idx"] = i0
            rec["entry_date"] = dlist[i0]
            new_entries.append(rec)
        collected = dict(collected)
        collected["entries"] = new_entries
    if str(spec.get("kind")) == "surprise_xs":
        pack = event.evaluate_surprise_xs_rank_hold_daily_mtm(
            bars,
            events,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
        )
        pack["logic_id"] = spec["logic_id"]
        pack["combo_gates"] = list(gates)
        pack["promote_as_main"] = False
        pack["go"] = False
        return pack
    return event_sides._finish_signed_event_book(
        spec=spec,
        collected=collected,
        accept=accept,
        extra=extra,
        one_way_cost=one_way_cost,
        sign_mult_by_key=sign_mult,
        repo_by_date=overnight,
    )


def _eval_cs_combo(
    spec: Mapping[str, Any],
    *,
    bars: Mapping[str, Any],
    overnight: Mapping[str, float],
    curve: Mapping[str, Any],
    margin_by_code: Mapping[str, Mapping[str, float]],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS mom occupancy with a date gate (matches Worker gatedCsHeld)."""
    from features.class_signals import cross_section_rank_signs

    params = dict(spec.get("params") or {})
    n = int(params.get("momentum_n") or 5)
    idx = panel_index(bars, momentum_n=n)
    dates = list(idx.get("dates") or [])
    h = int(params.get("hold_days") or 10)
    lf = float(params.get("long_frac") or 0.3)
    sf = float(params.get("short_frac") or 0.3)
    invert = str(spec.get("cs_gate") or params.get("cs_gate") or "") in {
        "always_invert",
        "overnight_tight_invert",
        "curve_invert_invert",
    }
    close_by = idx.get("close_by") or {}
    scores_by_date: dict[str, dict[str, float]] = {d: {} for d in dates}
    for code, cmap in close_by.items():
        for i, d in enumerate(dates):
            if i < n:
                continue
            c0 = cmap.get(dates[i - n])
            c1 = cmap.get(d)
            if c0 and c1 and c0 != 0:
                scores_by_date[d][code] = (c1 / c0) - 1.0
    held: dict[str, dict[str, float | None]] = {
        c: {d: None for d in dates} for c in close_by
    }
    spread = dict((curve or {}).get("spread_by_date") or {})
    gate = str(spec.get("cs_gate") or params.get("cs_gate") or "")
    extra_cf_only: list[str] = []
    for i, d in enumerate(dates):
        on = overnight.get(d)
        prev_on = overnight.get(dates[i - 1]) if i else None
        med_on = None
        if overnight:
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d)
        keep = True
        loc_invert = invert
        if gate == "overnight_easy":
            keep = on is not None and med_on is not None and float(on) < float(med_on)
        elif gate == "overnight_tight_invert":
            keep = on is not None and med_on is not None and float(on) >= float(med_on)
            loc_invert = True
        elif gate == "curve_invert_invert":
            keep = float(spread.get(d) or 1) <= 0
            loc_invert = True
        elif gate == "month_start":
            keep = d[8:10] <= "05"
        elif gate == "overnight_up":
            keep = prev_on is not None and on is not None and float(on) > float(prev_on)
        elif gate == "fy_end_invert":
            keep = d[5:7] == "03" and d[8:10] >= "15"
            loc_invert = True
        elif gate == "fy_start":
            keep = d[5:7] == "04"
        elif gate == "curve_steep":
            keep = float(spread.get(d) or 0) > 0
        elif gate == "overnight_p90_invert":
            hist = [overnight[x] for x in overnight if x < d]
            if len(hist) < 20 or on is None:
                keep = False
            else:
                srt = sorted(hist)
                p90 = srt[int(0.9 * (len(srt) - 1))]
                keep = float(on) >= float(p90)
                loc_invert = True
        elif gate == "margin_crowd_chase":
            keep = _universe_margin_delta(margin_by_code, d) > 0
            loc_invert = True
        elif gate == "margin_decrowd":
            keep = _universe_margin_delta(margin_by_code, d) < 0
        elif gate == "margin_change_nonzero":
            keep = _universe_margin_delta(margin_by_code, d) != 0
        elif gate == "repo_3m_up":
            prev_sp = spread.get(dates[i - 1]) if i else None
            sp = spread.get(d)
            keep = (
                prev_on is not None
                and on is not None
                and prev_sp is not None
                and sp is not None
                and (float(on) + float(sp)) > (float(prev_on) + float(prev_sp))
            )
        elif gate == "skip_monday":
            keep = _weekday(d) != 0
        elif gate == "tue_thu":
            keep = _weekday(d) in {1, 2, 3}
        elif gate == "overnight_down":
            keep = (
                prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "overnight_up_invert":
            keep = (
                prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
            loc_invert = True
        elif gate == "midmonth":
            keep = d[8:10] >= "10" and d[8:10] <= "20"
        elif gate == "friday_invert":
            keep = _weekday(d) == 4
            loc_invert = True
        elif gate == "not_month_end":
            keep = d[8:10] < "28"
        elif gate in {
            "opt225_skew_high",
            "nky_term_high",
            "opt225_spread_wide",
            "nky_term_compress",
            "opt225_skew_and_term",
            "basevol_up",
            "iv_below_basevol",
        }:
            vol = _vol_sidecar()
            keep = _apply_vol_gate(gate, d, dates[i - 1] if i else None, vol)
            if not vol:
                extra_cf_only.append(gate)
        scores = scores_by_date.get(d) or {}
        if not keep or len(scores) < 2:
            continue
        ranks = cross_section_rank_signs(scores, long_frac=lf, short_frac=sf)
        for code, sgn in ranks.items():
            if sgn is None:
                continue
            v = -float(sgn) if loc_invert else float(sgn)
            held.setdefault(code, {})[d] = v
    sticky: dict[str, dict[str, float]] = {}
    for code, cmap in held.items():
        sticky[code] = {}
        held_pos = 0.0
        since = 0
        for i, d in enumerate(dates):
            entry = cmap.get(d)
            if i == 0 or since >= h:
                if entry is not None:
                    held_pos = float(entry)
                since = 1
            else:
                since += 1
            sticky[code][d] = held_pos
    pack = held_book_daily_mtm(
        held_by_code_date=sticky,
        close_by=idx.get("close_by") or {},
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra={"cs_gate": gate, "cf_native": True},
        repo_by_date=overnight,
    )
    pack.update(
        {
            "logic_id": spec["logic_id"],
            "status": "ok",
            "cs_gate": gate,
            "promote_as_main": False,
            "go": False,
            "cf_native": True,
            "cf_only_gates": extra_cf_only,
            "python_skipped_cf_only": bool(extra_cf_only),
        }
    )
    return pack


def _add_days(iso: str, n: int) -> str:
    from datetime import date, timedelta

    try:
        y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
        return (date(y, m, d) + timedelta(days=n)).isoformat()
    except (TypeError, ValueError):
        return iso


def _weekday(iso: str) -> int:
    """Monday=0 … Sunday=6. Invalid date → -1 (gate fail-closed)."""
    from datetime import date

    try:
        return date(int(iso[:4]), int(iso[5:7]), int(iso[8:10])).weekday()
    except (TypeError, ValueError):
        return -1


_VOL_CACHE: dict[str, dict[str, float]] | None = None


def _vol_sidecar() -> dict[str, dict[str, float]]:
    global _VOL_CACHE
    if _VOL_CACHE is not None:
        return _VOL_CACHE
    out: dict[str, dict[str, float]] = {}
    try:
        from research.class_hyp_eval import (
            load_nky_vol_series_from_sqlite,
            load_opt225_regime_bundle_for_eval,
        )

        nky = load_nky_vol_series_from_sqlite() or {}
        out["nky_term"] = {
            str(k)[:10]: float(v)
            for k, v in dict(nky.get("rv_ratio_by_date") or {}).items()
            if v is not None
        }
        opt = load_opt225_regime_bundle_for_eval() or {}
        def _abs(series: Any) -> dict[str, float]:
            if not isinstance(series, dict):
                return {}
            raw = series.get("rv_abs_by_date") or series
            if not isinstance(raw, dict):
                return {}
            return {str(k)[:10]: float(v) for k, v in raw.items() if v is not None}

        out["skew"] = _abs(opt.get("skew") or {})
        out["spread"] = _abs(opt.get("spread") or {})
        out["basevol"] = _abs(opt.get("basevol") or {})
        out["nky_abs"] = {
            str(k)[:10]: float(v)
            for k, v in dict(nky.get("rv_abs_by_date") or {}).items()
            if v is not None
        }
    except Exception:
        out = {}
    _VOL_CACHE = out
    return out


def _apply_vol_gate(
    gate: str,
    d: str,
    prev: str | None,
    vol: Mapping[str, Mapping[str, float]],
) -> bool:
    if not vol:
        return False
    if gate == "nky_term_high":
        series = vol.get("nky_term") or {}
        med = event.pit_median_on_dates(series, [d], min_hist=20).get(d)
        v = series.get(d)
        return med is not None and v is not None and float(v) >= float(med)
    if gate == "nky_term_compress":
        series = vol.get("nky_term") or {}
        if not prev:
            return False
        a, b = series.get(d), series.get(prev)
        return a is not None and b is not None and float(a) < float(b)
    if gate == "opt225_skew_high":
        series = vol.get("skew") or {}
        med = event.pit_median_on_dates(series, [d], min_hist=20).get(d)
        v = series.get(d)
        return med is not None and v is not None and float(v) >= float(med)
    if gate == "opt225_spread_wide":
        series = vol.get("spread") or {}
        med = event.pit_median_on_dates(
            {k: abs(float(x)) for k, x in series.items()}, [d], min_hist=20
        ).get(d)
        v = series.get(d)
        return med is not None and v is not None and abs(float(v)) >= float(med)
    if gate == "opt225_skew_and_term":
        return _apply_vol_gate("opt225_skew_high", d, prev, vol) and _apply_vol_gate(
            "nky_term_high", d, prev, vol
        )
    if gate == "basevol_up":
        series = vol.get("basevol") or {}
        if not prev:
            return False
        a, b = series.get(d), series.get(prev)
        return a is not None and b is not None and float(a) > float(b)
    if gate == "iv_below_basevol":
        series = vol.get("spread") or {}
        v = series.get(d)
        return v is not None and float(v) < 0
    return False


def _universe_margin_delta(
    margin_by_code: Mapping[str, Mapping[str, float]],
    query: str,
) -> float:
    deltas: list[float] = []
    q = str(query)[:10]
    for series in (margin_by_code or {}).values():
        prior = sorted(d for d in series if str(d)[:10] < q)
        if len(prior) < 2:
            continue
        a = series[prior[-2]]
        b = series[prior[-1]]
        try:
            deltas.append(float(b) - float(a))
        except (TypeError, ValueError):
            continue
    if not deltas:
        return 0.0
    return sum(deltas) / len(deltas)
