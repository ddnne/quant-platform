"""New unique theses as combo gates (not numeric variants).

CF Worker eventHeld / gatedCsHeld is the candidate-grade path.
This module declares the specs and a Python fallback that applies the
same gate names. Does not promote / GO.
"""
from __future__ import annotations

from typing import Any, Mapping

from research.daily_path_eval import held_book_daily_mtm, panel_index
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    KNOWN_EVENT_GATES,
    WORKER_ISOLATE_LIMIT_IDS,
    is_ungated_name_level_cs,
    sparse_15name_reason,
)
from research.unique_logic.near_duplicate import is_near_duplicate
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
        "thesis": (
            "Fade surprise in May FY-results season. Late-March event PEAD is "
            "empty on 15-name shards (data_requirement); May is the JP results dump."
        ),
        "gates": ("fy_results",),
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
        "thesis": (
            "Relative-surprise CS rank of after-close disclosures only on "
            "calendar days 10–20 (afterclose alone is ~always_on)."
        ),
        "gates": ("afterclose", "midmonth"),
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
    {
        "logic_id": "event_afterclose_midmonth",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close PEAD only on calendar days 10–20 (not month-turn).",
        "gates": ("afterclose", "midmonth"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_easing_midmonth",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only when overnight eased AND the calendar is mid-month.",
        "gates": ("overnight_easing", "midmonth"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_friday_easing",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only on Fridays when overnight eased (weekend carry when cheap).",
        "gates": ("friday_only", "overnight_easing"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_uncrowded_midmonth",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD only when uncrowded AND the calendar is mid-month.",
        "gates": ("uncrowded_margin", "midmonth"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_may_results_follow",
        "family_id": "event_calendar_gate",
        "thesis": "Follow PEAD in May FY-results season (opposite of May fade).",
        "gates": ("fy_results",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_tue_thu_easing",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD Tuesday–Thursday only when overnight eased.",
        "gates": ("tue_thu", "overnight_easing"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "surprise_xs_midmonth",
        "family_id": "surprise_xs_rank",
        "thesis": "Relative-surprise CS rank only on calendar days 10–20.",
        "gates": ("midmonth",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_easing_change",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when overnight fell versus the prior print (change, not PIT level).",
        "gates": ("overnight_easing",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_afterclose_easing",
        "family_id": "surprise_xs_rank",
        "thesis": "After-close surprise CS rank only on an overnight easing day.",
        "gates": ("afterclose", "overnight_easing"),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "cs_easing_midmonth",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom only mid-month AND overnight declined.",
        "cs_gate": "midmonth_overnight_down",
        "kind": "cs",
    },
    {
        "logic_id": "cs_tue_thu_down",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom Tuesday–Thursday only when overnight declined.",
        "cs_gate": "tue_thu_overnight_down",
        "kind": "cs",
    },
    {
        "logic_id": "overnight_down_skip_monday_cs",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom on overnight decline, skipping Mondays.",
        "cs_gate": "overnight_down_skip_monday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_friday_tight_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade CS on Fridays when overnight rose (weekend + tightening).",
        "cs_gate": "friday_overnight_up_invert",
        "kind": "cs",
    },
    {
        "logic_id": "flow_disagree_midmonth",
        "family_id": "xs_margin_delta",
        "thesis": "Fade CS when margin crowded, but only mid-month.",
        "cs_gate": "margin_crowd_midmonth_invert",
        "kind": "cs",
    },
    {
        "logic_id": "curve_steep_midmonth_cs",
        "family_id": "event_macro_curve_combo",
        "thesis": "CS mom when the repo curve is steep AND the calendar is mid-month.",
        "cs_gate": "curve_steep_midmonth",
        "kind": "cs",
    },
    {
        "logic_id": "rate_up_tue_thu_cs",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom Tuesday–Thursday only when overnight rose.",
        "cs_gate": "tue_thu_overnight_up",
        "kind": "cs",
    },
    {
        "logic_id": "event_tue_thu_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD Tuesday–Thursday only when the name is uncrowded in margin.",
        "gates": ("tue_thu", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_afterclose_easing",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close PEAD only on a one-day overnight decline.",
        "gates": ("afterclose", "overnight_easing"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_may_easing",
        "family_id": "event_calendar_gate",
        "thesis": (
            "PEAD in May FY-results only when overnight eased. "
            "15-name shards are too sparse (data_requirement_unmet)."
        ),
        "gates": ("fy_results", "overnight_easing"),
        "side": "orig",
        "kind": "event",
        "main_pool": False,
    },
    {
        "logic_id": "event_skip_monday_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Skip Monday PEAD; remaining days only when uncrowded.",
        "gates": ("skip_monday", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_first_half_easing",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD in the first half of the month only when overnight eased.",
        "gates": ("first_half_month", "overnight_easing"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "surprise_xs_skip_monday",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank skips Monday entries (weekend gap).",
        "gates": ("skip_monday",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_friday_skip",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank skips Friday entries (weekend hold).",
        "gates": ("friday_skip",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_uncrowded",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when the name is uncrowded in margin.",
        "gates": ("uncrowded_margin",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "cs_steep_skip_monday",
        "family_id": "event_macro_curve_combo",
        "thesis": "CS mom when the repo curve is steep, skipping Mondays.",
        "cs_gate": "curve_steep_skip_monday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_midmonth_tight_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade CS mid-month when overnight rose.",
        "cs_gate": "midmonth_overnight_up_invert",
        "kind": "cs",
    },
    {
        "logic_id": "flow_disagree_tue_thu",
        "family_id": "xs_margin_delta",
        "thesis": (
            "Fade CS when margin crowded, Tuesday–Thursday only. "
            "Crowd+weekday is empty on 15-name shards (data_requirement_unmet)."
        ),
        "cs_gate": "margin_crowd_tue_thu_invert",
        "kind": "cs",
        "main_pool": False,
    },
    {
        "logic_id": "iv_below_midmonth_cs",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom skipping Mondays when ATM IV sits below BaseVol (midmonth was empty).",
        "cs_gate": "iv_below_skip_monday",
        "kind": "cs",
    },
    {
        "logic_id": "overnight_down_first_half_cs",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom on overnight decline in the first half of the month.",
        "cs_gate": "first_half_overnight_down",
        "kind": "cs",
    },
    {
        "logic_id": "rate_up_midmonth_cs",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom mid-month only when overnight rose.",
        "cs_gate": "midmonth_overnight_up",
        "kind": "cs",
    },
    {
        "logic_id": "cs_month_start_easing",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom in the first ten calendar days only when overnight declined.",
        "cs_gate": "month_start10_overnight_down",
        "kind": "cs",
    },
    {
        "logic_id": "nky_vol_compress_midmonth_cs",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom mid-month only when NKY vol term compressed versus the prior print.",
        "cs_gate": "nky_compress_midmonth",
        "kind": "cs",
    },
    {
        "logic_id": "event_friday_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD only on Fridays when the name is uncrowded.",
        "gates": ("friday_only", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_skip_monday_easing",
        "family_id": "event_calendar_gate",
        "thesis": "Skip Monday PEAD; remaining days only when overnight eased.",
        "gates": ("skip_monday", "overnight_easing"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_afterclose_skip_monday",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close PEAD skipping Monday entries.",
        "gates": ("afterclose", "skip_monday"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_easing_skip_friday",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when overnight eased, skipping Friday entries.",
        "gates": ("overnight_easing", "friday_skip"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_first_half_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD in the first half of the month only when uncrowded.",
        "gates": ("first_half_month", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_tue_thu_steep",
        "family_id": "event_macro_curve_combo",
        "thesis": "PEAD Tuesday–Thursday only when the repo curve is steep.",
        "gates": ("tue_thu", "steep_curve"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_midmonth_steep",
        "family_id": "event_macro_curve_combo",
        "thesis": (
            "PEAD mid-month only when the repo curve is steep. "
            "15-name shards are too sparse (data_requirement_unmet)."
        ),
        "gates": ("midmonth", "steep_curve"),
        "side": "orig",
        "kind": "event",
        "main_pool": False,
    },
    {
        "logic_id": "surprise_xs_first_half",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only in the first half of the month.",
        "gates": ("first_half_month",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_afterclose_skip_monday",
        "family_id": "surprise_xs_rank",
        "thesis": "After-close surprise CS rank skipping Mondays.",
        "gates": ("afterclose", "skip_monday"),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_steep_skip_monday",
        "family_id": "surprise_xs_rank",
        "thesis": "Steep-curve surprise CS rank skipping Mondays.",
        "gates": ("steep_curve", "skip_monday"),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "cs_friday_down",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom on Fridays when overnight declined.",
        "cs_gate": "friday_overnight_down",
        "kind": "cs",
    },
    {
        "logic_id": "cs_tue_thu_steep",
        "family_id": "event_macro_curve_combo",
        "thesis": "CS mom Tuesday–Thursday when the repo curve is steep.",
        "cs_gate": "tue_thu_curve_steep",
        "kind": "cs",
    },
    {
        "logic_id": "overnight_up_skip_monday_cs",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when overnight rose, skipping Mondays.",
        "cs_gate": "overnight_up_skip_monday",
        "kind": "cs",
    },
    {
        "logic_id": "flow_disagree_skip_monday",
        "family_id": "xs_margin_delta",
        "thesis": "Fade CS when margin crowded, skipping Mondays.",
        "cs_gate": "margin_crowd_skip_monday_invert",
        "kind": "cs",
    },
    {
        "logic_id": "cs_easy_tue_thu",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom Tuesday–Thursday when overnight is easy versus PIT median.",
        "cs_gate": "tue_thu_overnight_easy",
        "kind": "cs",
    },
    {
        "logic_id": "cs_easy_skip_monday",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when overnight is easy (below PIT median), skipping Mondays.",
        "cs_gate": "overnight_easy_skip_monday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_not_friday_down",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom on overnight decline, skipping Fridays.",
        "cs_gate": "overnight_down_skip_friday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_midmonth_easy",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom mid-month only when overnight is easy versus PIT median.",
        "cs_gate": "midmonth_overnight_easy",
        "kind": "cs",
    },
    {
        "logic_id": "cs_steep_friday",
        "family_id": "event_macro_curve_combo",
        "thesis": (
            "CS mom on Fridays when the repo curve is steep. "
            "Friday+steep is empty on 15-name shards (data_requirement_unmet)."
        ),
        "cs_gate": "friday_curve_steep",
        "kind": "cs",
        "main_pool": False,
    },
    {
        "logic_id": "surprise_xs_uncrowded_skip_monday",
        "family_id": "surprise_xs_rank",
        "thesis": "Uncrowded surprise CS rank skipping Mondays.",
        "gates": ("uncrowded_margin", "skip_monday"),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "event_skip_tuesday",
        "family_id": "event_calendar_gate",
        "thesis": "Skip Tuesday PEAD entries (post-Monday continuation dump).",
        "gates": ("skip_tuesday",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_skip_wednesday",
        "family_id": "event_calendar_gate",
        "thesis": "Skip Wednesday PEAD entries (mid-week liquidity hole).",
        "gates": ("skip_wednesday",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_not_last_week",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only before calendar day 24 (avoid month-end window dressing).",
        "gates": ("not_last_week",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_month_start7",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only in the first seven calendar days.",
        "gates": ("month_start7",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_not_first_week",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD skipping the first seven calendar days (post month-start).",
        "gates": ("not_first_week",),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_afterclose_skip_friday",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close PEAD skipping Friday entries.",
        "gates": ("afterclose", "friday_skip"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_easing_skip_tuesday",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when overnight eased, skipping Tuesdays.",
        "gates": ("overnight_easing", "skip_tuesday"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_uncrowded_skip_friday",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Uncrowded PEAD skipping Friday entries.",
        "gates": ("uncrowded_margin", "friday_skip"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_tight_skip_monday",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when overnight is tight versus PIT median, skipping Mondays.",
        "gates": ("tight_funding", "skip_monday"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_cluster_skip_monday",
        "family_id": "disclosure_cluster_gate",
        "thesis": "Cluster-day PEAD skipping Monday entries.",
        "gates": ("cluster", "skip_monday"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_easy_skip_tuesday",
        "family_id": "event_funding_combo",
        "thesis": "Easy-overnight PEAD skipping Tuesdays.",
        "gates": ("easy_funding", "skip_tuesday"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "event_afterclose_not_last_week",
        "family_id": "afterclose_event_timing",
        "thesis": "After-close PEAD before calendar day 24.",
        "gates": ("afterclose", "not_last_week"),
        "side": "orig",
        "kind": "event",
    },
    {
        "logic_id": "surprise_xs_skip_tuesday",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank skipping Tuesday entries.",
        "gates": ("skip_tuesday",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_not_last_week",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank before calendar day 24.",
        "gates": ("not_last_week",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_month_start7",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank in the first seven calendar days.",
        "gates": ("month_start7",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_not_first_week",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank skipping the first seven calendar days.",
        "gates": ("not_first_week",),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_easing_skip_friday",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank on overnight easing, skipping Fridays.",
        "gates": ("overnight_easing", "friday_skip"),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "surprise_xs_afterclose_skip_friday",
        "family_id": "surprise_xs_rank",
        "thesis": "After-close surprise CS rank skipping Fridays.",
        "gates": ("afterclose", "friday_skip"),
        "side": "orig",
        "kind": "surprise_xs",
    },
    {
        "logic_id": "cs_skip_tuesday",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom skipping Tuesdays.",
        "cs_gate": "skip_tuesday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_skip_wednesday",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom skipping Wednesdays.",
        "cs_gate": "skip_wednesday",
        "kind": "cs",
    },
    {
        "logic_id": "cs_not_last_week",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom before calendar day 24.",
        "cs_gate": "not_last_week",
        "kind": "cs",
    },
    {
        "logic_id": "cs_month_start7",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom in the first seven calendar days.",
        "cs_gate": "month_start7",
        "kind": "cs",
    },
    {
        "logic_id": "cs_not_first_week",
        "family_id": "event_calendar_gate",
        "thesis": "CS mom skipping the first seven calendar days.",
        "cs_gate": "not_first_week",
        "kind": "cs",
    },
    {
        "logic_id": "cs_easy_skip_friday",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when overnight is easy versus PIT median, skipping Fridays.",
        "cs_gate": "overnight_easy_skip_friday",
        "kind": "cs",
    },
    {
        "logic_id": "flow_disagree_skip_friday",
        "family_id": "xs_margin_delta",
        "thesis": (
            "Fade CS when margin crowded, skipping Fridays. "
            "Crowd+weekday is empty on 15-name shards (data_requirement_unmet)."
        ),
        "cs_gate": "margin_crowd_skip_friday_invert",
        "kind": "cs",
        "main_pool": False,
    },
    {
        "logic_id": "overnight_down_skip_tuesday_cs",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom on overnight decline, skipping Tuesdays.",
        "cs_gate": "overnight_down_skip_tuesday",
        "kind": "cs",
    },
    {
        "logic_id": "surprise_xs_tight_fade",
        "family_id": "surprise_xs_rank",
        "thesis": "Fade relative-surprise ranks when overnight is tight versus PIT median (funding squeeze).",
        "gates": ("tight_funding",),
        "side": "flip",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_rank_easy_funding", "surprise_xs_easing_change"],
    },
    {
        "logic_id": "surprise_xs_on_impulse",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only on a large one-day overnight impulse (|dON| above PIT median).",
        "gates": ("on_impulse",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_easing_change", "surprise_xs_rank_easy_funding"],
    },
    {
        "logic_id": "surprise_xs_invert_fade",
        "family_id": "surprise_xs_rank",
        "thesis": "Fade surprise ranks when the repo curve is inverted or flat (term-funding stress).",
        "gates": ("invert_curve",),
        "side": "flip",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_rank_steep_curve", "event_curve_invert_fade"],
    },
    {
        "logic_id": "event_on_impulse_pead",
        "family_id": "event_funding_combo",
        "thesis": "PEAD only when overnight jumped or dropped by more than its PIT median absolute change.",
        "gates": ("on_impulse",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["overnight_easing_event", "event_funding_stress_skip"],
    },
    {
        "logic_id": "cs_margin_up_chase",
        "family_id": "xs_margin_delta",
        "thesis": "Follow CS mom when name-level margin interest rose (crowding chase, not a fade).",
        "cs_gate": "margin_up",
        "kind": "cs",
        "why_different_from": ["flow_disagree_midmonth", "flow_price_disagree_fade"],
    },
    {
        "logic_id": "cs_margin_down_follow",
        "family_id": "xs_margin_delta",
        "thesis": "Follow CS mom when name-level margin interest fell (decrowd continuation).",
        "cs_gate": "margin_down",
        "kind": "cs",
        "why_different_from": ["cs_margin_up_chase", "flow_disagree_skip_monday"],
    },
    {
        "logic_id": "cs_short_ratio_up_fade",
        "family_id": "xs_margin_delta",
        "thesis": "Fade CS mom when market short-ratio rose versus the prior print (shorting pressure).",
        "cs_gate": "short_ratio_up_invert",
        "kind": "cs",
        "why_different_from": ["flow_margin_short_hard", "cs_margin_up_chase"],
    },
    {
        "logic_id": "event_margin_delta_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade PEAD when the name's margin interest increased into the disclosure (crowded news).",
        "gates": ("margin_up",),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["margin_crowd_fade_event", "event_margin_crowding_skip"],
    },
    {
        "logic_id": "cs_on_impulse",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom only on large overnight impulses (|dON| above PIT median of absolute changes).",
        "cs_gate": "on_impulse",
        "kind": "cs",
        "why_different_from": ["rate_change_cs_confirm", "overnight_down_cs_follow"],
    },
    {
        "logic_id": "cs_overnight_p10",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when overnight is in the easiest decile of its PIT history (very easy carry).",
        "cs_gate": "overnight_p10",
        "kind": "cs",
        "why_different_from": ["cs_mom_easy_funding", "overnight_p90_cs_flip"],
    },
    {
        "logic_id": "cs_repo3m_down",
        "family_id": "repo_3m_level_cs",
        "thesis": "CS mom when 3M Tokyo repo declined versus the prior print.",
        "cs_gate": "repo_3m_down",
        "kind": "cs",
        "why_different_from": ["repo_3m_change_cs", "repo_3m_level_cs"],
    },
    {
        "logic_id": "cs_curve_flatten",
        "family_id": "event_macro_curve_combo",
        "thesis": "CS mom when the 3M-ON repo spread flattened versus the prior print.",
        "cs_gate": "curve_flatten",
        "kind": "cs",
        "why_different_from": ["curve_steep_cs_follow", "curve_steepen_impulse_cs"],
    },
    {
        "logic_id": "event_cheap_iv_pead",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only when ATM IV sits below BaseVol (cheap insurance / low implied crash premium).",
        "gates": ("cheap_iv",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["iv_below_basevol_cs", "event_easing_uncrowded"],
    },
    {
        "logic_id": "event_rich_iv_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade PEAD when ATM IV sits above BaseVol (rich crash insurance).",
        "gates": ("rich_iv",),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_cheap_iv_pead", "basevol_up_day_fade"],
    },
    {
        "logic_id": "surprise_xs_cheap_iv",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when ATM IV is below BaseVol.",
        "gates": ("cheap_iv",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_cheap_iv_pead", "surprise_xs_uncrowded"],
    },
    {
        "logic_id": "cs_nky_vol_high_fade",
        "family_id": "xs_low_vol_mom",
        "thesis": "Fade CS mom when NKY realized-vol term is above its PIT median (risk-off vol regime).",
        "cs_gate": "nky_vol_high_invert",
        "kind": "cs",
        "why_different_from": ["nky_vol_compress_cs", "nky_vol_term_cs_gate"],
    },
    {
        "logic_id": "cs_cheap_pb",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when name P/B (close/BPS) is below its own PIT median (value tilt).",
        "cs_gate": "cheap_pb",
        "kind": "cs",
        "why_different_from": ["fund_value_only", "fund_value_mom_agree"],
    },
    {
        "logic_id": "cs_expensive_pb_fade",
        "family_id": "xs_low_vol_mom",
        "thesis": "Fade CS mom when name P/B is above its PIT median (expensive book).",
        "cs_gate": "expensive_pb_invert",
        "kind": "cs",
        "why_different_from": ["cs_cheap_pb", "fund_value_only"],
    },
    {
        "logic_id": "cs_earnings_yield_high",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when EPS/close is above the name's PIT median earnings yield.",
        "cs_gate": "earnings_yield_high",
        "kind": "cs",
        "why_different_from": ["cs_cheap_pb", "fund_value_mom_agree"],
    },
    {
        "logic_id": "cs_roe_high",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when reported ROE is above the name's PIT median (quality). Missing ROE skips.",
        "cs_gate": "roe_high",
        "kind": "cs",
        "why_different_from": ["cs_earnings_yield_high", "fundamentals_hold_10"],
    },
    {
        "logic_id": "cs_div_positive",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom only when announced dividend (DivAnn) is strictly positive. Missing DivAnn skips.",
        "cs_gate": "div_positive",
        "kind": "cs",
        "why_different_from": ["cs_roe_high", "fund_value_only"],
    },
    {
        "logic_id": "event_positive_eps_pead",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only when latest EPS is strictly positive (skip loss-makers).",
        "gates": ("positive_eps",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_skip_monday", "large_surprise_event_hold"],
    },
    {
        "logic_id": "event_cheap_pb_pead",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only when the name's P/B is below its PIT median.",
        "gates": ("cheap_pb",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_cheap_pb", "event_positive_eps_pead"],
    },
    {
        "logic_id": "surprise_xs_eps_up",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when EPS rose versus the prior print (earnings improvement).",
        "gates": ("eps_up",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_rank_hold", "event_positive_eps_pead"],
    },
    {
        "logic_id": "cs_np_positive",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when net profit is strictly positive. Missing NP skips (no invent).",
        "cs_gate": "np_positive",
        "kind": "cs",
        "why_different_from": ["cs_div_positive", "event_positive_eps_pead"],
    },
    {
        "logic_id": "event_div_payer_pead",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only for names with strictly positive announced dividend. Missing DivAnn skips.",
        "gates": ("div_positive",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_div_positive", "event_positive_eps_pead"],
    },
    {
        "logic_id": "cs_eqar_high",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when equity-to-asset ratio (EqAR) is above the name PIT median (low leverage / quality).",
        "cs_gate": "eq_ar_high",
        "kind": "cs",
        "why_different_from": ["cs_roe_high", "cs_cheap_pb"],
    },
    {
        "logic_id": "cs_eqar_low_fade",
        "family_id": "xs_low_vol_mom",
        "thesis": "Fade CS mom when EqAR is below the name PIT median (levered names). Missing EqAR skips.",
        "cs_gate": "eq_ar_low_invert",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high", "cs_expensive_pb_fade"],
    },
    {
        "logic_id": "cs_ta_up",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when total assets (TA) rose versus the prior print. Missing TA skips.",
        "cs_gate": "ta_up",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high", "cs_np_positive"],
    },
    {
        "logic_id": "event_eqar_high_pead",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD only when EqAR is above the name PIT median (conservatively financed issuers).",
        "gates": ("eq_ar_high",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "cs_eqar_high"],
    },
    {
        "logic_id": "event_eqar_low_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade PEAD when EqAR is below the name PIT median (levered issuers).",
        "gates": ("eq_ar_low",),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "cs_eqar_low_fade"],
    },
    {
        "logic_id": "surprise_xs_eqar_high",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only for names with EqAR above PIT median.",
        "gates": ("eq_ar_high",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_eps_up", "event_eqar_high_pead"],
    },
    {
        "logic_id": "cs_eqar_high_easy",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when EqAR is high AND overnight is easy versus PIT median (quality × cheap carry).",
        "cs_gate": "eq_ar_high_easy",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high", "cs_mom_easy_funding"],
    },
    {
        "logic_id": "event_eqar_high_easy",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EqAR is high and overnight is easy (quality issuer, cheap funding).",
        "gates": ("eq_ar_high", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_on_impulse_pead"],
    },
    {
        "logic_id": "event_ta_up_pead",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when total assets rose versus the prior print (balance-sheet expansion).",
        "gates": ("ta_up",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_ta_up", "event_eqar_high_pead"],
    },
    {
        "logic_id": "event_cheap_pb_easy_funding",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when P/B is cheap AND overnight is easy (value × carry).",
        "gates": ("cheap_pb", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_easy"],
    },
    {
        "logic_id": "cs_eqar_high_cheap_iv",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when EqAR is high AND ATM IV is below BaseVol (quality in cheap-vol regimes).",
        "cs_gate": "eq_ar_high_cheap_iv",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high", "event_cheap_iv_pead"],
    },
    {
        "logic_id": "surprise_xs_margin_up_fade",
        "family_id": "surprise_xs_rank",
        "thesis": "Fade surprise ranks when the name's margin interest rose into the print (crowded news).",
        "gates": ("margin_up",),
        "side": "flip",
        "kind": "surprise_xs",
        "why_different_from": ["event_margin_delta_fade", "surprise_xs_tight_fade"],
    },
    {
        "logic_id": "event_margin_down_follow",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when name-level margin interest fell (decrowd into the disclosure).",
        "gates": ("margin_down",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_margin_delta_fade", "cs_margin_down_follow"],
    },
    {
        "logic_id": "surprise_xs_margin_up",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when name margin interest rose (crowding chase of news).",
        "gates": ("margin_up",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_margin_up_fade", "cs_margin_up_chase"],
    },
    {
        "logic_id": "event_crowd_on_impulse",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade PEAD when margin rose AND overnight impulse is large (crowded news into a rate shock).",
        "gates": ("margin_up", "on_impulse"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_margin_delta_fade", "event_on_impulse_pead"],
    },
    {
        "logic_id": "cs_margin_up_tight_fade",
        "family_id": "xs_margin_delta",
        "thesis": "Fade CS when name margin rose AND overnight is tight (crowding into funding stress).",
        "cs_gate": "margin_up_tight_invert",
        "kind": "cs",
        "why_different_from": ["cs_margin_up_chase", "cs_short_ratio_up_fade"],
    },
    {
        "logic_id": "cs_short_ratio_down_follow",
        "family_id": "xs_margin_delta",
        "thesis": "Follow CS mom when market short-ratio fell versus the prior print (short covering).",
        "cs_gate": "short_ratio_down",
        "kind": "cs",
        "why_different_from": ["cs_short_ratio_up_fade", "cs_margin_down_follow"],
    },
    {
        "logic_id": "event_overnight_p10_pead",
        "family_id": "event_funding_combo",
        "thesis": "PEAD only when overnight is in the easiest decile of its PIT history.",
        "gates": ("overnight_p10",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_on_impulse_pead", "cs_overnight_p10"],
    },
    {
        "logic_id": "event_curve_flatten_pead",
        "family_id": "event_macro_curve_combo",
        "thesis": "PEAD when the 3M-ON spread flattened versus the prior print.",
        "gates": ("curve_flatten",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_curve_flatten", "event_curve_invert_fade"],
    },
    {
        "logic_id": "event_repo3m_down_pead",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when 3M Tokyo repo declined versus the prior print.",
        "gates": ("repo_3m_down",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_repo3m_down", "event_on_impulse_pead"],
    },
    {
        "logic_id": "surprise_xs_repo3m_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when 3M repo declined versus the prior print.",
        "gates": ("repo_3m_down",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_repo3m_down_pead", "surprise_xs_on_impulse"],
    },
    {
        "logic_id": "event_cheap_iv_cheap_pb",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when ATM IV is below BaseVol AND P/B is cheap (cheap vol × value).",
        "gates": ("cheap_iv", "cheap_pb"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_iv_pead", "event_cheap_pb_pead"],
    },
    {
        "logic_id": "surprise_xs_rich_iv_fade",
        "family_id": "surprise_xs_rank",
        "thesis": "Fade surprise ranks when ATM IV sits above BaseVol.",
        "gates": ("rich_iv",),
        "side": "flip",
        "kind": "surprise_xs",
        "why_different_from": ["event_rich_iv_fade", "surprise_xs_cheap_iv"],
    },
    {
        "logic_id": "event_nky_high_skip",
        "family_id": "event_calendar_gate",
        "thesis": "Skip PEAD when NKY realized vol is above its PIT median (risk-off).",
        "gates": ("nky_vol_high_skip",),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_nky_vol_high_fade", "event_cheap_iv_pead"],
    },
    {
        "logic_id": "surprise_xs_div_payer",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only for names with strictly positive DivAnn. Missing skips.",
        "gates": ("div_positive",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_div_payer_pead", "cs_div_positive"],
    },
    {
        "logic_id": "event_eqar_high_on_impulse",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EqAR is high AND overnight impulse is large (quality into a rate shock).",
        "gates": ("eq_ar_high", "on_impulse"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_on_impulse_pead"],
    },
    {
        "logic_id": "event_eqar_low_tight_fade",
        "family_id": "event_funding_combo",
        "thesis": "Fade PEAD when EqAR is low AND overnight is tight (levered issuer, expensive carry).",
        "gates": ("eq_ar_low", "tight_funding"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_funding_tight_fade"],
    },
    {
        "logic_id": "event_ta_up_easy_funding",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when total assets rose AND overnight is easy (balance-sheet growth, cheap carry).",
        "gates": ("ta_up", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_easy"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_easy",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND overnight is easy.",
        "gates": ("eq_ar_high", "easy_funding"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_eqar_high", "event_eqar_high_easy"],
    },
    {
        "logic_id": "event_eqar_high_repo3m_down",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EqAR is high AND 3M repo declined versus the prior print.",
        "gates": ("eq_ar_high", "repo_3m_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_repo3m_down_pead"],
    },
    {
        "logic_id": "event_ta_up_curve_flatten",
        "family_id": "event_macro_curve_combo",
        "thesis": "PEAD when TA rose AND the 3M-ON spread flattened.",
        "gates": ("ta_up", "curve_flatten"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_curve_flatten_pead"],
    },
    {
        "logic_id": "surprise_xs_ta_up",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when total assets rose versus the prior print. Missing TA skips.",
        "gates": ("ta_up",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_ta_up_pead", "surprise_xs_eqar_high"],
    },
    {
        "logic_id": "event_eqar_low_on_impulse_fade",
        "family_id": "event_funding_combo",
        "thesis": "Fade PEAD when EqAR is low AND overnight impulse is large (levered names into a rate shock).",
        "gates": ("eq_ar_low", "on_impulse"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_crowd_on_impulse"],
    },
    {
        "logic_id": "event_eqar_high_overnight_p10",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EqAR is high AND overnight is in the easiest decile.",
        "gates": ("eq_ar_high", "overnight_p10"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_easy", "event_overnight_p10_pead"],
    },
    {
        "logic_id": "cs_eqar_high_repo3m_down",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when EqAR is high AND 3M repo declined (quality × cheaper term funding).",
        "cs_gate": "eq_ar_high_repo3m_down",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "cs_repo3m_down"],
    },
    {
        "logic_id": "surprise_xs_margin_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when name margin interest fell (decrowd into the print).",
        "gates": ("margin_down",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_margin_down_follow", "surprise_xs_margin_up"],
    },
    {
        "logic_id": "event_margin_up_tight_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade PEAD when margin rose AND overnight is tight (crowding into funding stress).",
        "gates": ("margin_up", "tight_funding"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_crowd_on_impulse", "cs_margin_up_tight_fade"],
    },
    {
        "logic_id": "event_margin_down_easy",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when name margin fell AND overnight is easy (decrowd, cheap carry).",
        "gates": ("margin_down", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_margin_down_follow", "event_eqar_high_easy"],
    },
    {
        "logic_id": "cs_margin_down_easy",
        "family_id": "xs_margin_delta",
        "thesis": "CS mom when name margin fell AND overnight is easy (decrowd × cheap carry).",
        "cs_gate": "margin_down_easy",
        "kind": "cs",
        "why_different_from": ["cs_margin_down_follow", "cs_eqar_high_easy"],
    },
    {
        "logic_id": "surprise_xs_margin_up_on_impulse",
        "family_id": "surprise_xs_rank",
        "thesis": "Fade surprise ranks when margin rose AND overnight impulse is large.",
        "gates": ("margin_up", "on_impulse"),
        "side": "flip",
        "kind": "surprise_xs",
        "why_different_from": ["event_crowd_on_impulse", "surprise_xs_margin_up_fade"],
    },
    {
        "logic_id": "cs_overnight_p10_steep",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when overnight is in the easiest decile AND the curve is steep.",
        "cs_gate": "overnight_p10_steep",
        "kind": "cs",
        "why_different_from": ["cs_overnight_p10", "cs_tue_thu_steep"],
    },
    {
        "logic_id": "event_repo3m_down_uncrowded",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when 3M repo declined AND the name is uncrowded on margin.",
        "gates": ("repo_3m_down", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_repo3m_down_pead", "event_easing_uncrowded"],
    },
    {
        "logic_id": "surprise_xs_overnight_p10",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when overnight is in the easiest decile.",
        "gates": ("overnight_p10",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_overnight_p10_pead", "surprise_xs_on_impulse"],
    },
    {
        "logic_id": "event_curve_flatten_uncrowded",
        "family_id": "event_macro_curve_combo",
        "thesis": "PEAD when the curve flattened AND the name is uncrowded on margin.",
        "gates": ("curve_flatten", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_curve_flatten_pead", "event_repo3m_down_uncrowded"],
    },
    {
        "logic_id": "cs_repo3m_down_easy",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when 3M repo declined AND overnight is easy versus PIT median.",
        "cs_gate": "repo3m_down_easy",
        "kind": "cs",
        "why_different_from": ["cs_repo3m_down", "cs_eqar_high_easy"],
    },
    {
        "logic_id": "event_on_impulse_uncrowded",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when overnight impulse is large AND the name is uncrowded on margin.",
        "gates": ("on_impulse", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_on_impulse_pead", "event_repo3m_down_uncrowded"],
    },
    {
        "logic_id": "event_eqar_high_cheap_iv",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when EqAR is high AND ATM IV is below BaseVol (quality in cheap-vol).",
        "gates": ("eq_ar_high", "cheap_iv"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["cs_eqar_high_cheap_iv", "event_eqar_high_pead"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_cheap_iv",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND ATM IV is below BaseVol.",
        "gates": ("eq_ar_high", "cheap_iv"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_eqar_high_cheap_iv", "surprise_xs_eqar_high"],
    },
    {
        "logic_id": "event_ta_up_cheap_iv",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when TA rose AND ATM IV is below BaseVol.",
        "gates": ("ta_up", "cheap_iv"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_cheap_iv"],
    },
    {
        "logic_id": "event_rich_iv_eqar_low_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade PEAD when ATM IV is above BaseVol AND EqAR is low (rich vol, levered).",
        "gates": ("rich_iv", "eq_ar_low"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_rich_iv_fade", "event_eqar_low_fade"],
    },
    {
        "logic_id": "cs_cheap_pb_cheap_iv",
        "family_id": "xs_low_vol_mom",
        "thesis": "CS mom when P/B is cheap AND ATM IV is below BaseVol (value in cheap-vol).",
        "cs_gate": "cheap_pb_cheap_iv",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_cheap_iv", "event_cheap_iv_cheap_pb"],
    },
    {
        "logic_id": "event_div_payer_easy",
        "family_id": "event_funding_combo",
        "thesis": "PEAD for dividend payers when overnight is easy. Missing DivAnn skips.",
        "gates": ("div_positive", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_div_payer_pead", "event_eqar_high_easy"],
    },
    {
        "logic_id": "surprise_xs_eqar_low_fade",
        "family_id": "surprise_xs_rank",
        "thesis": "Fade surprise ranks when EqAR is below the name PIT median.",
        "gates": ("eq_ar_low",),
        "side": "flip",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_eqar_high", "event_eqar_low_fade"],
    },
    {
        "logic_id": "event_positive_eps_easy",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EPS is positive AND overnight is easy.",
        "gates": ("positive_eps", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "event_eqar_high_easy"],
    },
    {
        "logic_id": "event_cheap_pb_on_impulse",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when P/B is cheap AND overnight impulse is large (value into a rate shock).",
        "gates": ("cheap_pb", "on_impulse"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_on_impulse"],
    },
    {
        "logic_id": "cs_eqar_high_flatten",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when EqAR is high AND the 3M-ON spread flattened.",
        "cs_gate": "eq_ar_high_flatten",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "cs_curve_flatten"],
    },
    {
        "logic_id": "event_ta_up_on_impulse",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when TA rose AND overnight impulse is large.",
        "gates": ("ta_up", "on_impulse"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_on_impulse"],
    },
    {
        "logic_id": "event_eqar_high_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when EqAR is high AND the name is uncrowded on margin.",
        "gates": ("eq_ar_high", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_repo3m_down_uncrowded"],
    },
    {
        "logic_id": "event_ta_up_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when TA rose AND the name is uncrowded on margin.",
        "gates": ("ta_up", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_uncrowded"],
    },
    {
        "logic_id": "surprise_xs_ta_up_easy",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when TA rose AND overnight is easy.",
        "gates": ("ta_up", "easy_funding"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_ta_up", "event_ta_up_easy_funding"],
    },
    {
        "logic_id": "event_eqar_low_repo3m_down_fade",
        "family_id": "event_funding_combo",
        "thesis": "Fade PEAD when EqAR is low AND 3M repo declined (levered names into cheaper term funding).",
        "gates": ("eq_ar_low", "repo_3m_down"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_eqar_high_repo3m_down"],
    },
    {
        "logic_id": "cs_eqar_high_overnight_p10",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when EqAR is high AND overnight is in the easiest decile.",
        "cs_gate": "eq_ar_high_overnight_p10",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "event_eqar_high_overnight_p10"],
    },
    {
        "logic_id": "event_eqar_high_steep",
        "family_id": "event_macro_curve_combo",
        "thesis": "PEAD when EqAR is high AND the curve is steep.",
        "gates": ("eq_ar_high", "steep_curve"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_tue_thu_steep"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_repo3m_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND 3M repo declined.",
        "gates": ("eq_ar_high", "repo_3m_down"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_eqar_high_repo3m_down", "surprise_xs_eqar_high"],
    },
    {
        "logic_id": "event_ta_up_overnight_p10",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when TA rose AND overnight is in the easiest decile.",
        "gates": ("ta_up", "overnight_p10"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_easy_funding", "event_overnight_p10_pead"],
    },
    {
        "logic_id": "event_eqar_high_afterclose",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when EqAR is high AND the disclosure is after the close.",
        "gates": ("eq_ar_high", "afterclose"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_afterclose_easing"],
    },
    {
        "logic_id": "cs_ta_up_easy",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when TA rose AND overnight is easy versus PIT median.",
        "cs_gate": "ta_up_easy",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "event_ta_up_easy_funding"],
    },
    {
        "logic_id": "event_margin_down_on_impulse",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when name margin fell AND overnight impulse is large.",
        "gates": ("margin_down", "on_impulse"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_margin_down_follow", "event_crowd_on_impulse"],
    },
    {
        "logic_id": "cs_margin_up_easy",
        "family_id": "xs_margin_delta",
        "thesis": "CS mom when name margin rose AND overnight is easy (crowding into cheap carry).",
        "cs_gate": "margin_up_easy",
        "kind": "cs",
        "why_different_from": ["cs_margin_up_chase", "cs_margin_down_easy"],
    },
    {
        "logic_id": "event_margin_up_easy",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when name margin rose AND overnight is easy.",
        "gates": ("margin_up", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_margin_up_tight_fade", "event_margin_down_easy"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_on_impulse",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND overnight impulse is large.",
        "gates": ("eq_ar_high", "on_impulse"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_eqar_high_on_impulse", "surprise_xs_eqar_high"],
    },
    {
        "logic_id": "event_eqar_low_cheap_iv_fade",
        "family_id": "event_calendar_gate",
        "thesis": "Fade PEAD when EqAR is low AND ATM IV is below BaseVol.",
        "gates": ("eq_ar_low", "cheap_iv"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_eqar_high_cheap_iv"],
    },
    {
        "logic_id": "surprise_xs_div_payer_easy",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank for dividend payers when overnight is easy.",
        "gates": ("div_positive", "easy_funding"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_div_payer_easy", "surprise_xs_div_payer"],
    },
    {
        "logic_id": "event_div_payer_cheap_iv",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD for dividend payers when ATM IV is below BaseVol.",
        "gates": ("div_positive", "cheap_iv"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_div_payer_pead", "event_eqar_high_cheap_iv"],
    },
    {
        "logic_id": "event_positive_eps_on_impulse",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EPS is positive AND overnight impulse is large.",
        "gates": ("positive_eps", "on_impulse"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "event_eqar_high_on_impulse"],
    },
    {
        "logic_id": "event_cheap_pb_repo3m_down",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when P/B is cheap AND 3M repo declined.",
        "gates": ("cheap_pb", "repo_3m_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_repo3m_down"],
    },
    {
        "logic_id": "cs_curve_flatten_easy",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when the curve flattened AND overnight is easy.",
        "cs_gate": "curve_flatten_easy",
        "kind": "cs",
        "why_different_from": ["cs_curve_flatten", "cs_repo3m_down_easy"],
    },
    {
        "logic_id": "event_overnight_p10_eqar_low_fade",
        "family_id": "event_funding_combo",
        "thesis": "Fade PEAD when overnight is easiest-decile AND EqAR is low.",
        "gates": ("overnight_p10", "eq_ar_low"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_overnight_p10_pead", "event_eqar_low_fade"],
    },
    {
        "logic_id": "surprise_xs_curve_flatten",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank only when the 3M-ON spread flattened.",
        "gates": ("curve_flatten",),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_curve_flatten_pead", "surprise_xs_repo3m_down"],
    },
    {
        "logic_id": "event_ta_up_afterclose",
        "family_id": "event_calendar_gate",
        "thesis": "PEAD when TA rose AND the disclosure is after the close.",
        "gates": ("ta_up", "afterclose"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_afterclose"],
    },
    {
        "logic_id": "cs_eqar_low_tight",
        "family_id": "overnight_level_cs",
        "thesis": "Fade CS when EqAR is low AND overnight is tight (levered names, expensive carry).",
        "cs_gate": "eq_ar_low_tight_invert",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "event_eqar_low_tight_fade"],
    },
    {
        "logic_id": "event_eps_up_easy",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when EPS rose versus the prior print AND overnight is easy.",
        "gates": ("eps_up", "easy_funding"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["surprise_xs_eps_up", "event_positive_eps_easy"],
    },
    {
        "logic_id": "surprise_xs_ta_up_on_impulse",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when TA rose AND overnight impulse is large.",
        "gates": ("ta_up", "on_impulse"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_ta_up_on_impulse", "surprise_xs_ta_up"],
    },
    {
        "logic_id": "event_eqar_high_margin_down",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when EqAR is high AND name margin interest fell.",
        "gates": ("eq_ar_high", "margin_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_uncrowded", "event_margin_down_follow"],
    },
    {
        "logic_id": "event_ta_up_margin_down",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when TA rose AND name margin interest fell.",
        "gates": ("ta_up", "margin_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_uncrowded", "event_eqar_high_margin_down"],
    },
    {
        "logic_id": "event_cheap_pb_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when P/B is cheap AND the name is uncrowded on margin.",
        "gates": ("cheap_pb", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_uncrowded"],
    },
    {
        "logic_id": "surprise_xs_positive_eps_easy",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EPS is positive AND overnight is easy.",
        "gates": ("positive_eps", "easy_funding"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_positive_eps_easy", "surprise_xs_eps_up"],
    },
    {
        "logic_id": "event_repo3m_down_afterclose",
        "family_id": "event_funding_combo",
        "thesis": "PEAD when 3M repo declined AND the disclosure is after the close.",
        "gates": ("repo_3m_down", "afterclose"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_repo3m_down_pead", "event_eqar_high_afterclose"],
    },
    {
        "logic_id": "surprise_xs_margin_down_on_impulse",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when name margin fell AND overnight impulse is large.",
        "gates": ("margin_down", "on_impulse"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_margin_down_on_impulse", "surprise_xs_margin_down"],
    },
    {
        "logic_id": "event_eqar_high_cluster",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EqAR is high AND disclosures are clustered (quality in a busy week).",
        "gates": ("eq_ar_high", "cluster"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_cluster_easy_pead"],
    },
    {
        "logic_id": "event_ta_up_cluster",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose AND disclosures are clustered.",
        "gates": ("ta_up", "cluster"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_cluster"],
    },
    {
        "logic_id": "event_cheap_pb_cluster",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when P/B is cheap AND disclosures are clustered.",
        "gates": ("cheap_pb", "cluster"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_cluster"],
    },
    {
        "logic_id": "event_eqar_high_large_surprise",
        "family_id": "event_fund_cross",
        "thesis": "Large-surprise PEAD only when EqAR is high (quality confirms the surprise).",
        "gates": ("eq_ar_high", "large_surprise"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_large_surprise_easy_funding"],
    },
    {
        "logic_id": "event_ta_up_large_surprise",
        "family_id": "event_fund_cross",
        "thesis": "Large-surprise PEAD only when TA rose (growth confirms the surprise).",
        "gates": ("ta_up", "large_surprise"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_large_surprise"],
    },
    {
        "logic_id": "event_cheap_pb_large_surprise",
        "family_id": "event_fund_cross",
        "thesis": "Large-surprise PEAD only when P/B is cheap (value PEAD).",
        "gates": ("cheap_pb", "large_surprise"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_large_surprise"],
    },
    {
        "logic_id": "event_eqar_high_margin_up_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade quality PEAD when the name is crowding on margin (quality crowding).",
        "gates": ("eq_ar_high", "margin_up"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_high_margin_down", "event_eqar_high_uncrowded"],
    },
    {
        "logic_id": "event_ta_up_margin_up_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade TA-up PEAD when the name is crowding on margin.",
        "gates": ("ta_up", "margin_up"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_ta_up_margin_down", "event_eqar_high_margin_up_fade"],
    },
    {
        "logic_id": "event_cheap_pb_margin_up_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade cheap-PB PEAD when the name is crowding on margin.",
        "gates": ("cheap_pb", "margin_up"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_uncrowded", "event_eqar_high_margin_up_fade"],
    },
    {
        "logic_id": "event_eqar_high_liq_high",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EqAR is high AND the name's ADV is above the universe median (liquid quality).",
        "gates": ("eq_ar_high", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_eqar_high_uncrowded"],
    },
    {
        "logic_id": "event_ta_up_liq_high",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose AND ADV is above the universe median.",
        "gates": ("ta_up", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "event_cheap_pb_liq_high",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when P/B is cheap AND ADV is above the universe median (liquid value).",
        "gates": ("cheap_pb", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "event_eqar_high_price_down",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EqAR is high AND the name sold off into the event (quality dip).",
        "gates": ("eq_ar_high", "price_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_eqar_high_on_impulse"],
    },
    {
        "logic_id": "event_ta_up_price_down",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose AND the name sold off into the event.",
        "gates": ("ta_up", "price_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_price_down"],
    },
    {
        "logic_id": "event_cheap_pb_price_down",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when P/B is cheap AND the name sold off into the event (value dip).",
        "gates": ("cheap_pb", "price_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_price_down"],
    },
    {
        "logic_id": "event_margin_up_price_down_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade PEAD when margin interest rose AND price already sold off (crowded unwind).",
        "gates": ("margin_up", "price_down"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_margin_delta_fade", "cs_margin_up_chase"],
    },
    {
        "logic_id": "event_margin_down_price_down",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when margin interest fell AND price sold off (de-crowding dip follow).",
        "gates": ("margin_down", "price_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_margin_down_follow", "event_margin_up_price_down_fade"],
    },
    {
        "logic_id": "event_eqar_high_eps_up",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EqAR is high AND EPS rose versus the prior print.",
        "gates": ("eq_ar_high", "eps_up"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_eps_up_easy"],
    },
    {
        "logic_id": "event_ta_up_eps_up",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose AND EPS rose versus the prior print.",
        "gates": ("ta_up", "eps_up"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_eps_up"],
    },
    {
        "logic_id": "event_positive_eps_margin_down",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when EPS is positive AND name margin interest fell.",
        "gates": ("positive_eps", "margin_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "event_eqar_high_margin_down"],
    },
    {
        "logic_id": "event_div_payer_margin_down",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when the name pays a dividend AND margin interest fell.",
        "gates": ("div_positive", "margin_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_div_payer_pead", "event_positive_eps_margin_down"],
    },
    {
        "logic_id": "event_eqar_low_margin_up_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade PEAD when EqAR is low AND the name is crowding (weak BS + leverage).",
        "gates": ("eq_ar_low", "margin_up"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_eqar_high_margin_up_fade"],
    },
    {
        "logic_id": "event_liq_high_large_surprise",
        "family_id": "event_fund_cross",
        "thesis": "Large-surprise PEAD only in above-median ADV names (liquidity-conditioned PEAD).",
        "gates": ("liq_high", "large_surprise"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_large_surprise", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_liq_high",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND ADV is above the universe median.",
        "gates": ("eq_ar_high", "liq_high"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_eqar_high", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "surprise_xs_margin_up_price_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when margin rose AND price sold off (crowded dip).",
        "gates": ("margin_up", "price_down"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_margin_up", "event_margin_up_price_down_fade"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_price_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND price sold off into the event.",
        "gates": ("eq_ar_high", "price_down"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["surprise_xs_eqar_high", "event_eqar_high_price_down"],
    },
    {
        "logic_id": "cs_eqar_high_margin_down",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when EqAR is high AND name margin interest fell (quality de-crowding).",
        "cs_gate": "eq_ar_high_margin_down",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "cs_margin_down_easy"],
    },
    {
        "logic_id": "cs_ta_up_margin_down",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when TA rose AND name margin interest fell.",
        "cs_gate": "ta_up_margin_down",
        "kind": "cs",
        "why_different_from": ["cs_ta_up_easy", "cs_eqar_high_margin_down"],
    },
    {
        "logic_id": "cs_cheap_pb_easy",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when P/B is cheap AND overnight is easy (value with cheap carry).",
        "cs_gate": "cheap_pb_easy",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "event_cheap_pb_easy_funding"],
    },
    {
        "logic_id": "cs_eqar_high_on_impulse",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when EqAR is high AND overnight impulse is large.",
        "cs_gate": "eq_ar_high_on_impulse",
        "kind": "cs",
        "why_different_from": ["cs_eqar_high_easy", "cs_on_impulse"],
    },
    {
        "logic_id": "event_positive_eps_liq_high",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EPS is positive AND ADV is above the universe median.",
        "gates": ("positive_eps", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "event_div_payer_liq_high",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when the name pays a dividend AND ADV is above the universe median.",
        "gates": ("div_positive", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_div_payer_pead", "event_positive_eps_liq_high"],
    },
    {
        "logic_id": "event_eqar_low_liq_high_fade",
        "family_id": "event_fund_cross",
        "thesis": "Fade PEAD when EqAR is low even in liquid names (weak BS is tradable).",
        "gates": ("eq_ar_low", "liq_high"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "event_margin_down_liq_high",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when margin interest fell AND ADV is above the universe median.",
        "gates": ("margin_down", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_margin_down_follow", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "event_margin_up_liq_high_fade",
        "family_id": "event_margin_crowd_combo",
        "thesis": "Fade PEAD when margin interest rose in a liquid name (crowded and tradable).",
        "gates": ("margin_up", "liq_high"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_margin_up_price_down_fade", "event_margin_down_liq_high"],
    },
    {
        "logic_id": "event_eps_up_liq_high",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EPS rose versus the prior print AND ADV is above-median.",
        "gates": ("eps_up", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eps_up_easy", "event_positive_eps_liq_high"],
    },
    {
        "logic_id": "event_eqar_high_positive_eps",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EqAR is high AND EPS is positive (quality + profitable).",
        "gates": ("eq_ar_high", "positive_eps"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_positive_eps_pead"],
    },
    {
        "logic_id": "event_ta_up_positive_eps",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose AND EPS is positive.",
        "gates": ("ta_up", "positive_eps"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_positive_eps"],
    },
    {
        "logic_id": "event_cheap_pb_positive_eps",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when P/B is cheap AND EPS is positive (value + profitable).",
        "gates": ("cheap_pb", "positive_eps"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eqar_high_positive_eps"],
    },
    {
        "logic_id": "event_eqar_high_div_payer",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EqAR is high AND the name pays a dividend.",
        "gates": ("eq_ar_high", "div_positive"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_pead", "event_div_payer_pead"],
    },
    {
        "logic_id": "event_ta_up_div_payer",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose AND the name pays a dividend.",
        "gates": ("ta_up", "div_positive"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_pead", "event_eqar_high_div_payer"],
    },
    {
        "logic_id": "event_cheap_pb_eps_up",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when P/B is cheap AND EPS rose versus the prior print.",
        "gates": ("cheap_pb", "eps_up"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_pead", "event_eps_up_easy"],
    },
    {
        "logic_id": "event_eqar_high_price_down_liq",
        "family_id": "event_fund_cross",
        "thesis": "Quality dip PEAD only in above-median ADV names.",
        "gates": ("eq_ar_high", "price_down", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_eqar_high_price_down", "event_eqar_high_liq_high"],
    },
    {
        "logic_id": "event_ta_up_price_down_liq",
        "family_id": "event_fund_cross",
        "thesis": "TA-up dip PEAD only in above-median ADV names.",
        "gates": ("ta_up", "price_down", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_price_down", "event_eqar_high_price_down_liq"],
    },
    {
        "logic_id": "event_cheap_pb_price_down_liq",
        "family_id": "event_fund_cross",
        "thesis": "Cheap-PB dip PEAD only in above-median ADV names.",
        "gates": ("cheap_pb", "price_down", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_price_down", "event_eqar_high_price_down_liq"],
    },
    {
        "logic_id": "event_eqar_low_price_down_fade",
        "family_id": "event_fund_cross",
        "thesis": "Fade PEAD when EqAR is low AND price already sold off (weak dip is not quality).",
        "gates": ("eq_ar_low", "price_down"),
        "side": "flip",
        "kind": "event",
        "why_different_from": ["event_eqar_low_fade", "event_eqar_high_price_down"],
    },
    {
        "logic_id": "event_positive_eps_price_down",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when EPS is positive AND the name sold off into the event.",
        "gates": ("positive_eps", "price_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "event_eqar_high_price_down"],
    },
    {
        "logic_id": "event_div_payer_price_down",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when the name pays a dividend AND price sold off into the event.",
        "gates": ("div_positive", "price_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_div_payer_pead", "event_positive_eps_price_down"],
    },
    {
        "logic_id": "event_cheap_pb_margin_down",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when P/B is cheap AND name margin interest fell.",
        "gates": ("cheap_pb", "margin_down"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_cheap_pb_uncrowded", "event_eqar_high_margin_down"],
    },
    {
        "logic_id": "event_positive_eps_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when EPS is positive AND the name is uncrowded on margin.",
        "gates": ("positive_eps", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_positive_eps_pead", "event_cheap_pb_uncrowded"],
    },
    {
        "logic_id": "event_div_payer_uncrowded",
        "family_id": "event_margin_crowd_combo",
        "thesis": "PEAD when the name pays a dividend AND is uncrowded on margin.",
        "gates": ("div_positive", "uncrowded_margin"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_div_payer_pead", "event_positive_eps_uncrowded"],
    },
    {
        "logic_id": "event_ta_up_uncrowded_liq",
        "family_id": "event_fund_cross",
        "thesis": "PEAD when TA rose, the name is uncrowded, AND ADV is above-median.",
        "gates": ("ta_up", "uncrowded_margin", "liq_high"),
        "side": "orig",
        "kind": "event",
        "why_different_from": ["event_ta_up_uncrowded", "event_ta_up_liq_high"],
    },
    {
        "logic_id": "surprise_xs_cheap_pb_liq_high",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when P/B is cheap AND ADV is above the universe median.",
        "gates": ("cheap_pb", "liq_high"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_cheap_pb_liq_high", "surprise_xs_eqar_high_liq_high"],
    },
    {
        "logic_id": "surprise_xs_ta_up_liq_high",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when TA rose AND ADV is above the universe median.",
        "gates": ("ta_up", "liq_high"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_ta_up_liq_high", "surprise_xs_eqar_high_liq_high"],
    },
    {
        "logic_id": "surprise_xs_eqar_high_margin_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EqAR is high AND name margin interest fell.",
        "gates": ("eq_ar_high", "margin_down"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_eqar_high_margin_down", "surprise_xs_margin_down"],
    },
    {
        "logic_id": "surprise_xs_ta_up_margin_down",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when TA rose AND name margin interest fell.",
        "gates": ("ta_up", "margin_down"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_ta_up_margin_down", "surprise_xs_eqar_high_margin_down"],
    },
    {
        "logic_id": "surprise_xs_positive_eps_liq_high",
        "family_id": "surprise_xs_rank",
        "thesis": "Surprise CS rank when EPS is positive AND ADV is above-median.",
        "gates": ("positive_eps", "liq_high"),
        "side": "orig",
        "kind": "surprise_xs",
        "why_different_from": ["event_positive_eps_liq_high", "surprise_xs_eqar_high_liq_high"],
    },
    {
        "logic_id": "cs_cheap_pb_margin_down",
        "family_id": "overnight_level_cs",
        "thesis": "CS mom when P/B is cheap AND name margin interest fell.",
        "cs_gate": "cheap_pb_margin_down",
        "kind": "cs",
        "why_different_from": ["cs_cheap_pb_easy", "cs_eqar_high_margin_down"],
    },
    {
        "logic_id": "cs_eqar_low_margin_up",
        "family_id": "overnight_level_cs",
        "thesis": "Fade CS when EqAR is low AND the name is crowding on margin.",
        "cs_gate": "eq_ar_low_margin_up_invert",
        "kind": "cs",
        "why_different_from": ["cs_eqar_low_tight", "cs_eqar_high_margin_down"],
    },
)

def _combo_row(s: Mapping[str, Any]) -> dict[str, Any]:
    sparse = sparse_15name_reason(
        logic_id=str(s.get("logic_id") or ""),
        gates=[str(g) for g in (s.get("gates") or ())],
        cs_gate=str(s.get("cs_gate") or ""),
    )
    dup = is_near_duplicate(str(s.get("logic_id") or ""))
    ao = is_ungated_name_level_cs(
        kind=str(s.get("kind") or ""),
        cs_gate=str(s.get("cs_gate") or ""),
        logic_id=str(s.get("logic_id") or ""),
    )
    isolate = str(s.get("logic_id") or "") in WORKER_ISOLATE_LIMIT_IDS
    main_pool = False if (sparse or dup or ao or isolate) else bool(s.get("main_pool", True))
    return {
        **dict(s),
        "new_unique_logic": True,
        "catalog": True,
        "headline": False,
        "promote_as_main": False,
        "go": False,
        "generation_enabled": False,
        "main_pool": main_pool,
        "data_requirement_unmet": bool(sparse),
        "worker_isolate_limit": isolate,
        "near_duplicate": dup,
        "always_on_cs_sticky": ao,
        "sparse_15name_reason": sparse,
        "why_different_from": list(s.get("why_different_from") or []),
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


NEW_COMBO_LOGIC: tuple[dict[str, Any], ...] = tuple(_combo_row(s) for s in _SPECS)


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
    topix_by_date: Mapping[str, float] | None = None,
    one_way_cost: float = 0.001,
    period_start: str | None = None,
    period_end: str | None = None,
    adv_by_code: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Python fallback for combo theses. CF Worker is the SoT path."""
    lid = str(spec.get("logic_id") or "")
    declared = spec_by_id(lid) or dict(spec)
    kind = str(declared.get("kind") or "event")
    extra_adv = adv_by_code or dict(
        ((declared.get("extra") or spec.get("extra") or {}).get("adv_by_code") or {})
    )
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
            adv_by_code=extra_adv,
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
    adv_by_code: Mapping[str, float] | None = None,
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
            if g not in KNOWN_EVENT_GATES:
                ok = False
                continue
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
            elif g == "fy_results":
                if str(ev["entry_date"])[5:7] != "05":
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
            elif g == "friday_only":
                if _weekday(str(ev["entry_date"])) != 4:
                    ok = False
            elif g == "skip_tuesday":
                if _weekday(str(ev["entry_date"])) == 1:
                    ok = False
            elif g == "skip_wednesday":
                if _weekday(str(ev["entry_date"])) == 2:
                    ok = False
            elif g == "not_last_week":
                if str(ev["entry_date"])[8:10] >= "24":
                    ok = False
            elif g == "month_start7":
                if str(ev["entry_date"])[8:10] > "07":
                    ok = False
            elif g == "not_first_week":
                if str(ev["entry_date"])[8:10] <= "07":
                    ok = False
            elif g == "on_impulse":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                if not prevs or overnight.get(d) is None:
                    ok = False
                else:
                    abs_ch = abs(float(overnight[d]) - float(overnight[prevs[-1]]))
                    hist = {}
                    prev_list = list(prevs)
                    for i, dd in enumerate(prev_list[1:], start=1):
                        hist[dd] = abs(float(overnight[dd]) - float(overnight[prev_list[i - 1]]))
                    med = event.pit_median_on_dates(hist, [d], min_hist=20).get(d)
                    if med is None or abs_ch < float(med):
                        ok = False
            elif g == "invert_curve":
                if float(spread.get(ev["entry_date"]) or 1) > 0:
                    ok = False
            elif g == "positive_eps":
                if ev.get("eps") is None or float(ev.get("eps") or 0) <= 0:
                    ok = False
            elif g == "eps_up":
                if ev.get("eps") is None or ev.get("prior_eps") is None:
                    ok = False
                elif float(ev["eps"]) <= float(ev["prior_eps"]):
                    ok = False
            elif g == "midmonth":
                dd = str(ev["entry_date"])[8:10]
                if dd < "10" or dd > "20":
                    ok = False
            elif g == "div_positive":
                if ev.get("div_ann") is None or float(ev.get("div_ann") or 0) <= 0:
                    ok = False
            elif g == "eq_ar_high" or g == "eq_ar_low":
                val = ev.get("eq_ar")
                if val is None:
                    ok = False
                else:
                    hist: dict[str, float] = {}
                    for row in list(events.get(ev["code"]) or []):
                        dd = str(row.get("disc_date") or "")[:10]
                        q = row.get("eq_ar")
                        if dd and dd < ev["entry_date"] and q is not None:
                            hist[dd] = float(q)
                    med = event.pit_median_on_dates(
                        hist, [ev["entry_date"]], min_hist=8
                    ).get(ev["entry_date"])
                    if med is None:
                        ok = False
                    elif g == "eq_ar_high" and float(val) < float(med):
                        ok = False
                    elif g == "eq_ar_low" and float(val) >= float(med):
                        ok = False
            elif g == "ta_up":
                if ev.get("ta") is None or ev.get("prior_ta") is None:
                    ok = False
                elif float(ev["ta"]) <= float(ev["prior_ta"]):
                    ok = False
            elif g == "cheap_pb":
                bps = ev.get("bps")
                close = ((collected.get("close_by") or {}).get(ev["code"]) or {}).get(
                    ev["entry_date"]
                )
                if bps is None or close is None or float(bps) == 0:
                    ok = False
                else:
                    pb = float(close) / float(bps)
                    hist = {}
                    cmap = (collected.get("close_by") or {}).get(ev["code"]) or {}
                    fins = list(events.get(ev["code"]) or [])
                    for dd, px in sorted(cmap.items()):
                        if dd >= ev["entry_date"]:
                            break
                        fin = None
                        for row in fins:
                            x = str(row.get("disc_date") or "")[:10]
                            if x and x <= dd:
                                fin = row
                        b = (fin or {}).get("bps") if fin else None
                        if b is not None and float(b) != 0 and px:
                            hist[dd] = float(px) / float(b)
                    med = event.pit_median_on_dates(
                        hist, [ev["entry_date"]], min_hist=min_hist
                    ).get(ev["entry_date"])
                    if med is None or pb >= float(med):
                        ok = False
            elif g == "margin_up" or g == "margin_down":
                series = dict((margin_by_code or {}).get(ev["code"]) or {})
                prior = sorted(k for k in series if k < ev["entry_date"])
                if len(prior) < 2:
                    ok = False
                else:
                    delta = float(series[prior[-1]]) - float(series[prior[-2]])
                    if g == "margin_up" and delta <= 0:
                        ok = False
                    if g == "margin_down" and delta >= 0:
                        ok = False
            elif g == "overnight_p10":
                d = str(ev["entry_date"])[:10]
                on = overnight.get(d)
                hist = [overnight[x] for x in overnight if x < d]
                if len(hist) < min_hist or on is None:
                    ok = False
                else:
                    srt = sorted(hist)
                    p10 = srt[max(0, int(0.1 * (len(srt) - 1)))]
                    if float(on) > float(p10):
                        ok = False
            elif g == "curve_flatten":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in spread if x < d)
                sp = spread.get(d)
                if not prevs or sp is None:
                    ok = False
                elif float(sp) >= float(spread[prevs[-1]]):
                    ok = False
            elif g == "repo_3m_down":
                d = str(ev["entry_date"])[:10]
                prevs = sorted(x for x in overnight if x < d)
                on = overnight.get(d)
                sp = spread.get(d)
                if not prevs or on is None or sp is None:
                    ok = False
                else:
                    prev = prevs[-1]
                    psp = spread.get(prev)
                    pon = overnight.get(prev)
                    if psp is None or pon is None:
                        ok = False
                    elif float(on) + float(sp) >= float(pon) + float(psp):
                        ok = False
            elif g == "liq_high":
                adv_map = dict(adv_by_code or {})
                adv = adv_map.get(ev["code"])
                vals = [float(v) for v in adv_map.values() if v is not None]
                if adv is None or len(vals) < 4:
                    ok = False
                else:
                    med = sorted(vals)[len(vals) // 2]
                    if float(adv) < float(med):
                        ok = False
            elif g == "price_down":
                pack = (collected.get("per_code") or {}).get(ev["code"]) or {}
                dlist = list(pack.get("dlist") or [])
                close_by = (collected.get("close_by") or {}).get(ev["code"]) or {}
                i = int(ev.get("entry_idx") or 0)
                if i < 5 or not dlist:
                    ok = False
                else:
                    c0 = close_by.get(dlist[i - 5])
                    c1 = close_by.get(dlist[i] if i < len(dlist) else None)
                    if c0 is None or c1 is None or float(c0) == 0:
                        ok = False
                    elif (float(c1) / float(c0) - 1.0) >= 0:
                        ok = False
            elif g in {"cheap_iv", "rich_iv", "nky_vol_high_skip"}:
                # Worker SoT: needs panel vol sidecar. Missing → skip, no invent.
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
        collected = dict(collected)
        collected["entries"] = [
            ev
            for ev in collected["entries"]
            if accept.get(event_sides._event_key(ev), False)
        ]
        pack = event.evaluate_surprise_xs_rank_hold_daily_mtm(
            bars,
            events,
            spec=spec,
            one_way_cost=one_way_cost,
            period_start=period_start,
            period_end=period_end,
            entries=[
                ev
                for ev in collected["entries"]
                if accept.get(event_sides._event_key(ev), False)
            ],
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
        elif gate == "skip_tuesday":
            keep = _weekday(d) != 1
        elif gate == "skip_wednesday":
            keep = _weekday(d) != 2
        elif gate == "not_last_week":
            keep = d[8:10] < "24"
        elif gate == "month_start7":
            keep = d[8:10] <= "07"
        elif gate == "not_first_week":
            keep = d[8:10] > "07"
        elif gate == "overnight_easy_skip_friday":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                _weekday(d) != 4
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "margin_crowd_skip_friday_invert":
            keep = _weekday(d) != 4 and _universe_margin_delta(margin_by_code, d) > 0
            loc_invert = True
        elif gate == "overnight_down_skip_tuesday":
            keep = (
                _weekday(d) != 1
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "margin_up":
            keep = _universe_margin_delta(margin_by_code, d) > 0
        elif gate == "margin_down":
            keep = _universe_margin_delta(margin_by_code, d) < 0
        elif gate == "on_impulse":
            if prev_on is None or on is None:
                keep = False
            else:
                abs_ch = abs(float(on) - float(prev_on))
                hist = {}
                for j in range(1, i):
                    a = overnight.get(dates[j])
                    b = overnight.get(dates[j - 1])
                    if a is not None and b is not None:
                        hist[dates[j]] = abs(float(a) - float(b))
                med = event.pit_median_on_dates(hist, [d], min_hist=20).get(d) if hist else None
                keep = med is not None and abs_ch >= float(med)
        elif gate == "overnight_p10":
            hist = [overnight[x] for x in overnight if x < d]
            if len(hist) < 20 or on is None:
                keep = False
            else:
                srt = sorted(hist)
                p10 = srt[max(0, int(0.1 * (len(srt) - 1)))]
                keep = float(on) <= float(p10)
        elif gate == "repo_3m_down":
            prev_sp = spread.get(dates[i - 1]) if i else None
            sp = spread.get(d)
            keep = (
                prev_on is not None
                and on is not None
                and prev_sp is not None
                and sp is not None
                and (float(on) + float(sp)) < (float(prev_on) + float(prev_sp))
            )
        elif gate == "curve_flatten":
            prev_sp = spread.get(dates[i - 1]) if i else None
            sp = spread.get(d)
            keep = prev_sp is not None and sp is not None and float(sp) < float(prev_sp)
        elif gate in {
            "eq_ar_high_margin_down",
            "ta_up_margin_down",
            "cheap_pb_easy",
            "eq_ar_high_on_impulse",
            "cheap_pb_margin_down",
            "eq_ar_low_margin_up_invert",
        }:
            extra_cf_only.append(gate)
            keep = False
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
        elif gate == "midmonth_overnight_down":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "tue_thu_overnight_down":
            keep = (
                _weekday(d) in {1, 2, 3}
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "overnight_down_skip_monday":
            keep = (
                _weekday(d) != 0
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "friday_overnight_up_invert":
            keep = (
                _weekday(d) == 4
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
            loc_invert = True
        elif gate == "margin_crowd_midmonth_invert":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and _universe_margin_delta(margin_by_code, d) > 0
            )
            loc_invert = True
        elif gate == "curve_steep_midmonth":
            keep = d[8:10] >= "10" and d[8:10] <= "20" and float(spread.get(d) or 0) > 0
        elif gate == "tue_thu_overnight_up":
            keep = (
                _weekday(d) in {1, 2, 3}
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
        elif gate == "curve_steep_skip_monday":
            keep = _weekday(d) != 0 and float(spread.get(d) or 0) > 0
        elif gate == "midmonth_overnight_up_invert":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
            loc_invert = True
        elif gate == "margin_crowd_tue_thu_invert":
            keep = (
                _weekday(d) in {1, 2, 3}
                and _universe_margin_delta(margin_by_code, d) > 0
            )
            loc_invert = True
        elif gate == "first_half_overnight_down":
            keep = (
                d[8:10] <= "15"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "midmonth_overnight_up":
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
        elif gate == "month_start_overnight_down":
            keep = (
                d[8:10] <= "05"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "month_start10_overnight_down":
            keep = (
                d[8:10] <= "10"
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "iv_below_skip_monday":
            vol = _vol_sidecar()
            keep = _weekday(d) != 0 and _apply_vol_gate(
                "iv_below_basevol", d, dates[i - 1] if i else None, vol
            )
            if not vol:
                extra_cf_only.append(gate)
        elif gate == "friday_overnight_down":
            keep = (
                _weekday(d) == 4
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "tue_thu_curve_steep":
            keep = _weekday(d) in {1, 2, 3} and float(spread.get(d) or 0) > 0
        elif gate == "overnight_up_skip_monday":
            keep = (
                _weekday(d) != 0
                and prev_on is not None
                and on is not None
                and float(on) > float(prev_on)
            )
        elif gate == "margin_crowd_skip_monday_invert":
            keep = _weekday(d) != 0 and _universe_margin_delta(margin_by_code, d) > 0
            loc_invert = True
        elif gate == "overnight_easy_skip_monday":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                _weekday(d) != 0
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "overnight_down_skip_friday":
            keep = (
                _weekday(d) != 4
                and prev_on is not None
                and on is not None
                and float(on) < float(prev_on)
            )
        elif gate == "midmonth_overnight_easy":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "tue_thu_overnight_easy":
            med_on = event.pit_median_on_dates(overnight, [d], min_hist=20).get(d) if overnight else None
            keep = (
                _weekday(d) in {1, 2, 3}
                and on is not None
                and med_on is not None
                and float(on) < float(med_on)
            )
        elif gate == "friday_curve_steep":
            keep = _weekday(d) == 4 and float(spread.get(d) or 0) > 0
        elif gate == "nky_compress_midmonth":
            vol = _vol_sidecar()
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and _apply_vol_gate("nky_term_compress", d, dates[i - 1] if i else None, vol)
            )
            if not vol:
                extra_cf_only.append(gate)
        elif gate == "iv_below_midmonth":
            vol = _vol_sidecar()
            keep = (
                d[8:10] >= "10"
                and d[8:10] <= "20"
                and _apply_vol_gate("iv_below_basevol", d, dates[i - 1] if i else None, vol)
            )
            if not vol:
                extra_cf_only.append(gate)
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
        elif gate in {
            "eq_ar_high",
            "eq_ar_low_invert",
            "ta_up",
            "eq_ar_high_easy",
            "eq_ar_high_cheap_iv",
            "eq_ar_high_repo3m_down",
            "eq_ar_high_flatten",
            "margin_down_easy",
            "overnight_p10_steep",
            "repo3m_down_easy",
            "cheap_pb_cheap_iv",
            "eq_ar_high_overnight_p10",
            "ta_up_easy",
            "margin_up_easy",
            "curve_flatten_easy",
            "eq_ar_low_tight_invert",
            "cheap_pb",
            "expensive_pb_invert",
            "earnings_yield_high",
            "roe_high",
            "div_positive",
            "np_positive",
            "nky_vol_high_invert",
            "short_ratio_up_invert",
            "short_ratio_down",
            "margin_up_tight_invert",
        }:
            # Name-level fund/flow extras are Worker SoT. Local skip, no invent.
            keep = False
            extra_cf_only.append(gate)
        elif gate:
            keep = False
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
