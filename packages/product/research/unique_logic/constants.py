"""Shared unique_logic constants (not eval scores)."""

from __future__ import annotations

KNOWN_WEAK_THESIS: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",
        "flow_margin_short_hard",
    }
)
KNOWN_DEMOTED_OR_WEAK: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",
        "flow_margin_short_hard",
        "flow_margin_short_soft",
        "flow_margin_pressure",
        "fund_value_mom_agree_slow",
        "opt225_skew_abs_level",
        "opt225_cm_term_abs_level",
        "opt225_basevol_delta_abs",
        "macro_repo_rate_level",
    }
)
LOGIC_CATALOG_HEADLINE_BAN: frozenset[str] = frozenset(
    {
        "xs_rank_ls_sticky",
        "event_post_disclosure_hold",
        "vol_risk_adjusted_mom",
    }
)
EVENT_LOGIC_IDS: frozenset[str] = frozenset(
    {
        "event_funding_stress_skip",
        "curve_steep_event_confirm",
        "disclosure_cluster_mom_gate",
        "surprise_xs_rank_hold",
    }
)
EVENT_FILTER_LOGIC_IDS: frozenset[str] = frozenset(
    {
        "large_surprise_event_hold",
        "afterclose_only_event_hold",
        "event_pre_mom_agree_hold",
        "event_margin_crowding_skip",
    }
)
EVENT_SIDES_LOGIC_IDS: frozenset[str] = frozenset(
    {
        "event_funding_easy_short",
        "event_funding_stress_ls",
        "surprise_xs_rank_flip",
    }
)
ADAPTIVE_LOGIC_IDS: frozenset[str] = frozenset(
    {
        "event_funding_adaptive_side",
        "surprise_xs_rank_adaptive",
    }
)
CS_LOGIC_IDS: frozenset[str] = frozenset(
    {
        "funding_impulse_cs_tilt",
        "curve_steepen_impulse_cs",
        "xs_margin_delta_rank",
        "idio_mom_macro_impulse",
        "overnight_level_cs_tilt",
        "overnight_easy_cs_follow",
        "month_end_cs_fade",
        "xs_low_vol_mom",
        "repo_3m_level_cs",
    }
)
# Distinct economic theses added after the 52-logic path check.
# Not numeric hold/momentum variants of an existing thesis.
CF_NEW_EVENT_THESIS_IDS: frozenset[str] = frozenset(
    {
        "event_funding_tight_fade",
        "event_curve_invert_fade",
        "event_afterclose_easy_funding",
        "event_large_surprise_easy_funding",
        "event_pre_mom_easy_funding",
        "event_margin_or_funding_skip",
        "event_large_surprise_steep_curve",
        "event_afterclose_steep_curve",
        "event_tight_and_crowded_fade",
        "event_cluster_easy_pead",
        "surprise_xs_rank_easy_funding",
        "surprise_xs_rank_steep_curve",
        "event_pre_mom_steep_curve",
        "event_large_surprise_afterclose",
        "event_margin_uncrowded_steep",
        "event_easy_funding_curve_steep",
        "event_skip_announce_day",
        "event_late_hold_only",
        "month_end_event_skip",
        "event_first_half_month",
        "overnight_easing_event",
        "overnight_tightening_fade_event",
        "event_cluster_fade",
        "margin_crowd_fade_event",
        "surprise_xs_month_start",
        "surprise_xs_fy_end",
        "event_afterclose_delay2",
    }
)
CF_NEW_CS_THESIS_IDS: frozenset[str] = frozenset(
    {
        "overnight_tight_cs_fade",
        "curve_invert_cs_fade",
        "xs_high_vol_fade",
        "month_start_cs_follow",
        "rate_change_cs_confirm",
        "flow_price_margin_triple",
        "opt225_skew_cs_gate",
        "nky_vol_term_cs_gate",
        "opt225_spread_cs_tilt",
        "repo_3m_change_cs",
        "flow_margin_price_agree",
        "cs_mom_easy_funding",
        "fy_end_cs_fade",
        "fy_start_cs_follow",
        "curve_steep_cs_follow",
        "overnight_p90_cs_flip",
        "flow_price_disagree_fade",
        "nky_vol_compress_cs",
        "opt225_skew_and_term_cs",
        "basevol_up_day_fade",
        "iv_below_basevol_cs",
    }
)
CF_NEW_THESIS_IDS: frozenset[str] = CF_NEW_EVENT_THESIS_IDS | CF_NEW_CS_THESIS_IDS
# CF daily_path eventHeld set (Python unique_logic event family on Worker).
CF_EVENT_DAILY_PATH_IDS: frozenset[str] = (
    EVENT_LOGIC_IDS
    | EVENT_FILTER_LOGIC_IDS
    | EVENT_SIDES_LOGIC_IDS
    | ADAPTIVE_LOGIC_IDS
    | CF_NEW_EVENT_THESIS_IDS
)
# Intended lite vs filled gaps. Worker CF_EVENT_FIDELITY must match this.
CF_EVENT_FIDELITY: dict[str, str] = {
    "surprise": "aligned: feps-eps else eps-prior_eps (no invent)",
    "adaptive_trail_k": "aligned: last K completed holds orig vs flip; min K",
    "margin_pit": "aligned: last print < entry, stale<=14d, level < PIT median",
    "surprise_xs": "aligned: rank surprise among in-window names (not price mom)",
    "intended_lite_windows": "Worker period shards vs Python HONEST_3Y stitch",
    "intended_lite_entry": "disc_time hour>=15 vs full event_post_entry_bar_index",
}
ALWAYS_ON_OCCUPANCY_WARN: float = 0.85
