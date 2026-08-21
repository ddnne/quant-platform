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
CS_AND_SIDE_LOGIC_IDS: frozenset[str] = frozenset(
    set(CS_LOGIC_IDS) | set(EVENT_SIDES_LOGIC_IDS)
)
# CF daily_path eventHeld set (Python unique_logic event family on Worker).
CF_EVENT_DAILY_PATH_IDS: frozenset[str] = (
    EVENT_LOGIC_IDS | EVENT_FILTER_LOGIC_IDS | EVENT_SIDES_LOGIC_IDS | ADAPTIVE_LOGIC_IDS
)
ALWAYS_ON_OCCUPANCY_WARN: float = 0.85
