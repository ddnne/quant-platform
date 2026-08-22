"""Shared unique_logic constants (not eval scores)."""

from __future__ import annotations

from typing import Sequence

# Official JQuants fins/summary v2 payload keys. Do not invent aliases
# (NCTA is a sparse non-consolidated field, not Total Assets).
FINS_SUMMARY_TA_KEY: str = "TA"
FINS_SUMMARY_EQAR_KEY: str = "EqAR"
FINS_SUMMARY_EQ_KEY: str = "Eq"
FINS_SUMMARY_OFFICIAL_KEYS: dict[str, str] = {
    "ta": FINS_SUMMARY_TA_KEY,
    "eq_ar": FINS_SUMMARY_EQAR_KEY,
    "eq": FINS_SUMMARY_EQ_KEY,
}

# Must match Worker COMBO_EVENT_GATES plus Python-only gates. Unknown → skip.
COMBO_EVENT_GATES: frozenset[str] = frozenset(
    {
        "skip_monday",
        "skip_tuesday",
        "skip_wednesday",
        "friday_skip",
        "friday_only",
        "tue_thu",
        "not_last_week",
        "month_start7",
        "not_first_week",
        "first_half_month",
        "midmonth",
        "afterclose",
        "overnight_easing",
        "easy_funding",
        "tight_funding",
        "steep_curve",
        "uncrowded_margin",
        "cluster",
        "invert_curve",
        "on_impulse",
        "cheap_iv",
        "rich_iv",
        "cheap_pb",
        "positive_eps",
        "eps_up",
        "div_positive",
        "margin_up",
        "margin_down",
        "eq_ar_high",
        "eq_ar_low",
        "ta_up",
        "overnight_p10",
        "curve_flatten",
        "repo_3m_down",
        "nky_vol_high_skip",
        "large_surprise",
        "liq_high",
        "price_down",
    }
)
PYTHON_ONLY_EVENT_GATES: frozenset[str] = frozenset(
    {
        "crowded_margin",
        "pre_mom",
        "month_end_skip",
        "fy_end",
        "fy_results",
        "fy_start",
        "overnight_tightening",
    }
)
KNOWN_EVENT_GATES: frozenset[str] = COMBO_EVENT_GATES | PYTHON_ONLY_EVENT_GATES

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
        "event_skip_monday",
        "event_tue_thu_only",
        "event_friday_skip",
        "fy_end_event_fade",
        "fy_start_event_follow",
        "event_midmonth_only",
        "surprise_xs_afterclose",
        "event_easing_uncrowded",
        "surprise_xs_tue_thu",
        "event_afterclose_midmonth",
        "event_easing_midmonth",
        "event_friday_easing",
        "event_uncrowded_midmonth",
        "event_may_results_follow",
        "event_tue_thu_easing",
        "surprise_xs_midmonth",
        "surprise_xs_easing_change",
        "surprise_xs_afterclose_easing",
        "event_tue_thu_uncrowded",
        "event_afterclose_easing",
        "event_may_easing",
        "event_skip_monday_uncrowded",
        "event_first_half_easing",
        "surprise_xs_skip_monday",
        "surprise_xs_friday_skip",
        "surprise_xs_uncrowded",
        "event_friday_uncrowded",
        "event_skip_monday_easing",
        "event_afterclose_skip_monday",
        "event_easing_skip_friday",
        "event_first_half_uncrowded",
        "event_tue_thu_steep",
        "event_midmonth_steep",
        "surprise_xs_first_half",
        "surprise_xs_afterclose_skip_monday",
        "surprise_xs_steep_skip_monday",
        "surprise_xs_uncrowded_skip_monday",
        "event_skip_tuesday",
        "event_skip_wednesday",
        "event_not_last_week",
        "event_month_start7",
        "event_not_first_week",
        "event_afterclose_skip_friday",
        "event_easing_skip_tuesday",
        "event_uncrowded_skip_friday",
        "event_tight_skip_monday",
        "event_cluster_skip_monday",
        "event_easy_skip_tuesday",
        "event_afterclose_not_last_week",
        "surprise_xs_skip_tuesday",
        "surprise_xs_not_last_week",
        "surprise_xs_month_start7",
        "surprise_xs_not_first_week",
        "surprise_xs_easing_skip_friday",
        "surprise_xs_afterclose_skip_friday",
        "surprise_xs_tight_fade",
        "surprise_xs_on_impulse",
        "surprise_xs_invert_fade",
        "event_on_impulse_pead",
        "event_margin_delta_fade",
        "event_cheap_iv_pead",
        "event_rich_iv_fade",
        "surprise_xs_cheap_iv",
        "event_positive_eps_pead",
        "event_cheap_pb_pead",
        "surprise_xs_eps_up",
        "event_div_payer_pead",
        "event_eqar_high_pead",
        "event_eqar_low_fade",
        "event_ta_up_pead",
        "surprise_xs_eqar_high",
        "event_cheap_pb_easy_funding",
        "surprise_xs_margin_up_fade",
        "event_margin_down_follow",
        "event_crowd_on_impulse",
        "surprise_xs_margin_up",
        "event_overnight_p10_pead",
        "event_curve_flatten_pead",
        "event_repo3m_down_pead",
        "surprise_xs_repo3m_down",
        "event_cheap_iv_cheap_pb",
        "surprise_xs_rich_iv_fade",
        "event_nky_high_skip",
        "surprise_xs_div_payer",
        "event_eqar_high_easy",
        "event_eqar_high_on_impulse",
        "event_eqar_low_tight_fade",
        "event_ta_up_easy_funding",
        "surprise_xs_eqar_high_easy",
        "event_eqar_high_repo3m_down",
        "event_ta_up_curve_flatten",
        "surprise_xs_ta_up",
        "event_eqar_low_on_impulse_fade",
        "event_eqar_high_overnight_p10",
        "surprise_xs_margin_down",
        "event_margin_up_tight_fade",
        "event_margin_down_easy",
        "surprise_xs_margin_up_on_impulse",
        "event_repo3m_down_uncrowded",
        "surprise_xs_overnight_p10",
        "event_curve_flatten_uncrowded",
        "event_on_impulse_uncrowded",
        "event_eqar_high_cheap_iv",
        "surprise_xs_eqar_high_cheap_iv",
        "event_ta_up_cheap_iv",
        "event_rich_iv_eqar_low_fade",
        "event_div_payer_easy",
        "surprise_xs_eqar_low_fade",
        "event_positive_eps_easy",
        "event_cheap_pb_on_impulse",
        "event_ta_up_on_impulse",
        "event_eqar_high_uncrowded",
        "event_ta_up_uncrowded",
        "surprise_xs_ta_up_easy",
        "event_eqar_low_repo3m_down_fade",
        "event_eqar_high_steep",
        "surprise_xs_eqar_high_repo3m_down",
        "event_ta_up_overnight_p10",
        "event_eqar_high_afterclose",
        "event_margin_down_on_impulse",
        "event_margin_up_easy",
        "surprise_xs_eqar_high_on_impulse",
        "event_eqar_low_cheap_iv_fade",
        "surprise_xs_div_payer_easy",
        "event_div_payer_cheap_iv",
        "event_positive_eps_on_impulse",
        "event_cheap_pb_repo3m_down",
        "event_overnight_p10_eqar_low_fade",
        "surprise_xs_curve_flatten",
        "event_ta_up_afterclose",
        "event_eps_up_easy",
        "surprise_xs_ta_up_on_impulse",
        "event_eqar_high_margin_down",
        "event_ta_up_margin_down",
        "event_cheap_pb_uncrowded",
        "surprise_xs_positive_eps_easy",
        "event_repo3m_down_afterclose",
        "surprise_xs_margin_down_on_impulse",
        "event_eqar_high_cluster",
        "event_ta_up_cluster",
        "event_cheap_pb_cluster",
        "event_eqar_high_large_surprise",
        "event_ta_up_large_surprise",
        "event_cheap_pb_large_surprise",
        "event_eqar_high_margin_up_fade",
        "event_ta_up_margin_up_fade",
        "event_cheap_pb_margin_up_fade",
        "event_eqar_high_liq_high",
        "event_ta_up_liq_high",
        "event_cheap_pb_liq_high",
        "event_eqar_high_price_down",
        "event_ta_up_price_down",
        "event_cheap_pb_price_down",
        "event_margin_up_price_down_fade",
        "event_margin_down_price_down",
        "event_eqar_high_eps_up",
        "event_ta_up_eps_up",
        "event_positive_eps_margin_down",
        "event_div_payer_margin_down",
        "event_eqar_low_margin_up_fade",
        "event_liq_high_large_surprise",
        "surprise_xs_eqar_high_liq_high",
        "surprise_xs_margin_up_price_down",
        "surprise_xs_eqar_high_price_down",
        "event_positive_eps_liq_high",
        "event_div_payer_liq_high",
        "event_eqar_low_liq_high_fade",
        "event_margin_down_liq_high",
        "event_margin_up_liq_high_fade",
        "event_eps_up_liq_high",
        "event_eqar_high_positive_eps",
        "event_ta_up_positive_eps",
        "event_cheap_pb_positive_eps",
        "event_eqar_high_div_payer",
        "event_ta_up_div_payer",
        "event_cheap_pb_eps_up",
        "event_eqar_high_price_down_liq",
        "event_ta_up_price_down_liq",
        "event_cheap_pb_price_down_liq",
        "event_eqar_low_price_down_fade",
        "event_positive_eps_price_down",
        "event_div_payer_price_down",
        "event_cheap_pb_margin_down",
        "event_positive_eps_uncrowded",
        "event_div_payer_uncrowded",
        "event_ta_up_uncrowded_liq",
        "surprise_xs_cheap_pb_liq_high",
        "surprise_xs_ta_up_liq_high",
        "surprise_xs_eqar_high_margin_down",
        "surprise_xs_ta_up_margin_down",
        "surprise_xs_positive_eps_liq_high",
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
        "cs_skip_monday",
        "cs_tue_thu_follow",
        "overnight_down_cs_follow",
        "overnight_up_cs_fade",
        "cs_midmonth_follow",
        "cs_friday_fade",
        "cs_not_month_end",
        "cs_easing_midmonth",
        "cs_tue_thu_down",
        "overnight_down_skip_monday_cs",
        "cs_friday_tight_fade",
        "flow_disagree_midmonth",
        "curve_steep_midmonth_cs",
        "rate_up_tue_thu_cs",
        "cs_steep_skip_monday",
        "cs_midmonth_tight_fade",
        "flow_disagree_tue_thu",
        "iv_below_midmonth_cs",
        "overnight_down_first_half_cs",
        "rate_up_midmonth_cs",
        "cs_month_start_easing",
        "nky_vol_compress_midmonth_cs",
        "cs_friday_down",
        "cs_tue_thu_steep",
        "overnight_up_skip_monday_cs",
        "flow_disagree_skip_monday",
        "cs_easy_tue_thu",
        "cs_easy_skip_monday",
        "cs_not_friday_down",
        "cs_midmonth_easy",
        "cs_steep_friday",
        "cs_skip_tuesday",
        "cs_skip_wednesday",
        "cs_not_last_week",
        "cs_month_start7",
        "cs_not_first_week",
        "cs_easy_skip_friday",
        "flow_disagree_skip_friday",
        "overnight_down_skip_tuesday_cs",
        "cs_margin_up_chase",
        "cs_margin_down_follow",
        "cs_short_ratio_up_fade",
        "cs_on_impulse",
        "cs_overnight_p10",
        "cs_repo3m_down",
        "cs_curve_flatten",
        "cs_nky_vol_high_fade",
        "cs_cheap_pb",
        "cs_expensive_pb_fade",
        "cs_earnings_yield_high",
        "cs_roe_high",
        "cs_div_positive",
        "cs_np_positive",
        "cs_eqar_high",
        "cs_eqar_low_fade",
        "cs_ta_up",
        "cs_eqar_high_easy",
        "cs_eqar_high_cheap_iv",
        "cs_margin_up_tight_fade",
        "cs_short_ratio_down_follow",
        "cs_eqar_high_repo3m_down",
        "cs_margin_down_easy",
        "cs_overnight_p10_steep",
        "cs_repo3m_down_easy",
        "cs_cheap_pb_cheap_iv",
        "cs_eqar_high_flatten",
        "cs_eqar_high_overnight_p10",
        "cs_ta_up_easy",
        "cs_margin_up_easy",
        "cs_curve_flatten_easy",
        "cs_eqar_low_tight",
        "cs_eqar_high_margin_down",
        "cs_ta_up_margin_down",
        "cs_cheap_pb_easy",
        "cs_eqar_high_on_impulse",
        "cs_cheap_pb_margin_down",
        "cs_eqar_low_margin_up",
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
NEAR_EMPTY_OCCUPANCY: float = 0.05
# CF daily_path implements a unique rate-gated book (not fund_value_mom_agree).
# Overnight-change confirm (eval-cf-dp-mf-chg-20260822a) brought occupancy
# just under 0.85. Live candidate filter is occupancy, not this flag.
MF_VALUE_MOM_RATE_DELEGATES: bool = False
MF_VALUE_MOM_RATE_PATH: str = "unique_rate_gated_value_mom"
MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON: bool = False
# If a re-eval of mf_value_mom_rate has occupancy >= ALWAYS_ON_OCCUPANCY_WARN,
# summarize parks it (always_on). Do not densify to stay under the line.
# Candidate-grade SoT. Period-net mass-eval is bar-native auxiliary only.
CANDIDATE_EVAL_PROTOCOL: str = "daily_path_mtm_after_cost/v1"
PERIOD_NET_ROLE: str = "bar_native_auxiliary_unique_unsupported"
# Term-structure theses need distinct short/long vol maps. Occupancy 0 = unmet.
TERM_STRUCTURE_REQUIRED: frozenset[str] = frozenset(
    {
        "opt225_atm_iv_term_ratio",
        "opt225_basevol_term_ratio",
    }
)
# Linearized (no longer isolate-parked). Cluster hist was O(n²) per event;
# Worker now uses a linear window series. Cluster three completed on
# eval-cf-dp-liq100-cross-20260822a. CS name-level fund extras were 1102 at
# N=100; unparked after v21 csFundSnaps hoist + eval-cf-dp-cs-hoist-20260822a.
WORKER_ISOLATE_LINEARIZED_OK: frozenset[str] = frozenset(
    {
        "event_eqar_high_cluster",
        "event_ta_up_cluster",
        "event_cheap_pb_cluster",
        "cs_eqar_high_on_impulse",
        "cs_cheap_pb_margin_down",
        "cs_eqar_low_margin_up",
    }
)
# Empty after v21 csFundSnaps hoist + eval-cf-dp-cs-hoist-20260822a complete.
# Keep the set as the park mechanism; do not restore a 1102 without a path.
WORKER_ISOLATE_LIMIT_IDS: frozenset[str] = frozenset()
WORKER_ISOLATE_LIMIT_REASONS: dict[str, str] = {}
# Small-universe shards historically emptied these AND-gates. Parked until a
# larger-universe re-eval fills occupancy. data_requirement_unmet / main_pool=false.
SPARSE_ON_15NAME_SHARD: frozenset[str] = frozenset(
    {
        "event_may_easing",
        "flow_disagree_tue_thu",
        "event_midmonth_steep",
        "cs_steep_friday",
        "flow_disagree_skip_friday",
    }
)
# Gate combinations that empty a 15-name shard. New specs matching these
# are parked at generation (do not wait for a near_empty eval).
SPARSE_GATE_COMBOS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"fy_results", "overnight_easing"}), "may_plus_easing"),
    (frozenset({"tue_thu", "crowded_margin"}), "crowd_plus_weekday"),
    (frozenset({"margin_crowd_tue_thu_invert"}), "crowd_plus_weekday"),
    (frozenset({"midmonth", "steep_curve"}), "midmonth_plus_steep"),
    (frozenset({"friday_only", "steep_curve"}), "friday_plus_steep"),
    (frozenset({"friday_curve_steep"}), "friday_plus_steep"),
    (frozenset({"margin_crowd_skip_friday_invert"}), "crowd_plus_skip_weekday"),
    (frozenset({"cheap_iv", "cheap_pb"}), "cheap_iv_and_cheap_pb"),
    (frozenset({"overnight_p10_steep"}), "overnight_p10_plus_steep"),
    (frozenset({"div_positive", "cheap_iv"}), "div_payer_and_cheap_iv"),
)
# Name-level CS + sticky hold=10 is structurally always_on. Parked
# (main_pool=false). Crossed with overnight/IV/repo (cs_eqar_high_easy etc.) stay.
NAME_LEVEL_FUND_CS_GATES: frozenset[str] = frozenset(
    {
        "eq_ar_high",
        "eq_ar_low_invert",
        "ta_up",
        "cheap_pb",
        "expensive_pb_invert",
        "earnings_yield_high",
        "roe_high",
        "div_positive",
        "np_positive",
    }
)
ALWAYS_ON_CS_STICKY: frozenset[str] = frozenset(
    {
        "cs_eqar_high",
        "cs_eqar_low_fade",
        "cs_ta_up",
        "cs_cheap_pb",
        "cs_expensive_pb_fade",
        "cs_earnings_yield_high",
        "cs_roe_high",
        "cs_div_positive",
        "cs_np_positive",
    }
)


def is_ungated_name_level_cs(
    *,
    kind: str = "",
    cs_gate: str | None = None,
    logic_id: str = "",
) -> bool:
    """True when a CS sticky has only a persistent name-level fund gate."""
    lid = str(logic_id or "")
    if lid in ALWAYS_ON_CS_STICKY:
        return True
    if str(kind or "") != "cs":
        return False
    g = str(cs_gate or "").strip()
    return g in NAME_LEVEL_FUND_CS_GATES


def sparse_15name_reason(
    *,
    logic_id: str = "",
    gates: Sequence[str] | None = None,
    cs_gate: str | None = None,
) -> str | None:
    """Why a spec is empty on 15-name shards, or None if not flagged."""
    lid = str(logic_id or "")
    if lid in SPARSE_ON_15NAME_SHARD:
        return "listed_sparse_on_15name_shard"
    names = {str(g) for g in (gates or ()) if g}
    cg = str(cs_gate or "").strip()
    if cg and cg not in {"None", "none"}:
        names.add(cg)
    for combo, reason in SPARSE_GATE_COMBOS:
        if combo <= names:
            return reason
    return None
# Candidate pool: path ok, not always-on, not empty. Simple gated theses stay
# even with modest t/Sharpe — combination/funds may still use them.
CANDIDATE_POLICY: dict[str, object] = {
    "exclude": (
        "path_broken",
        "always_on",
        "near_empty",
        "data_requirement_unmet",
        "path_collapsed",
        "near_duplicate",
        "always_on_cs_sticky",
        "worker_isolate_limit",
    ),
    "always_on_occupancy": ALWAYS_ON_OCCUPANCY_WARN,
    "near_empty_occupancy": NEAR_EMPTY_OCCUPANCY,
    "strong_is_interest_flag": True,
    "strong_t_floor": None,
    "strong_sharpe_floor": None,
    "simple_strategies_kept_for_combinations": True,
    "promote_as_main": False,
    "go": False,
}

# Distinct economic themes added after the calendar-permutation audit.
# Gate reorderings are not listed here.
ECONOMIC_THEME_IDS: dict[str, frozenset[str]] = {
    "surprise_funding": frozenset(
        {
            "surprise_xs_tight_fade",
            "surprise_xs_on_impulse",
            "surprise_xs_invert_fade",
            "event_on_impulse_pead",
        }
    ),
    "margin_price_disagree": frozenset(
        {
            "cs_margin_up_chase",
            "cs_margin_down_follow",
            "cs_short_ratio_up_fade",
            "event_margin_delta_fade",
        }
    ),
    "repo_cs": frozenset(
        {
            "cs_on_impulse",
            "cs_overnight_p10",
            "cs_repo3m_down",
            "cs_curve_flatten",
        }
    ),
    "vol_conditional": frozenset(
        {
            "event_cheap_iv_pead",
            "event_rich_iv_fade",
            "surprise_xs_cheap_iv",
            "cs_nky_vol_high_fade",
        }
    ),
    "fundamentals": frozenset(
        {
            "cs_cheap_pb",
            "cs_expensive_pb_fade",
            "cs_earnings_yield_high",
            "cs_roe_high",
            "cs_div_positive",
            "event_positive_eps_pead",
            "event_cheap_pb_pead",
            "surprise_xs_eps_up",
            "cs_np_positive",
            "event_div_payer_pead",
        }
    ),
    "fund_leverage_cross": frozenset(
        {
            "cs_eqar_high",
            "cs_eqar_low_fade",
            "cs_ta_up",
            "event_eqar_high_pead",
            "event_eqar_low_fade",
            "surprise_xs_eqar_high",
            "cs_eqar_high_easy",
            "event_eqar_high_easy",
            "event_ta_up_pead",
            "event_cheap_pb_easy_funding",
            "cs_eqar_high_cheap_iv",
            "event_eqar_high_on_impulse",
            "event_eqar_low_tight_fade",
            "event_ta_up_easy_funding",
            "surprise_xs_eqar_high_easy",
            "event_eqar_high_repo3m_down",
            "event_ta_up_curve_flatten",
            "surprise_xs_ta_up",
            "event_eqar_low_on_impulse_fade",
            "event_eqar_high_overnight_p10",
            "cs_eqar_high_repo3m_down",
            "event_eqar_high_cheap_iv",
            "event_ta_up_cheap_iv",
            "cs_eqar_high_flatten",
            "surprise_xs_eqar_low_fade",
            "event_ta_up_on_impulse",
            "event_eqar_high_cluster",
            "event_eqar_high_large_surprise",
            "event_eqar_high_liq_high",
            "event_eqar_high_price_down",
            "event_ta_up_liq_high",
            "cs_eqar_high_margin_down",
            "cs_eqar_high_on_impulse",
        }
    ),
    "fund_flow_liq": frozenset(
        {
            "event_eqar_high_liq_high",
            "event_ta_up_liq_high",
            "event_cheap_pb_liq_high",
            "event_liq_high_large_surprise",
            "event_eqar_high_price_down",
            "event_margin_up_price_down_fade",
            "event_margin_down_price_down",
            "event_eqar_high_margin_up_fade",
            "surprise_xs_eqar_high_liq_high",
            "cs_cheap_pb_easy",
            "cs_ta_up_margin_down",
            "event_positive_eps_liq_high",
            "event_eqar_high_price_down_liq",
            "event_margin_down_liq_high",
            "surprise_xs_ta_up_liq_high",
            "cs_cheap_pb_margin_down",
        }
    ),
    "margin_surprise": frozenset(
        {
            "surprise_xs_margin_up_fade",
            "event_margin_down_follow",
            "surprise_xs_margin_up",
            "event_crowd_on_impulse",
            "cs_margin_up_tight_fade",
            "cs_short_ratio_down_follow",
            "surprise_xs_margin_down",
            "event_margin_up_tight_fade",
            "event_margin_down_easy",
            "surprise_xs_margin_up_on_impulse",
            "cs_margin_down_easy",
        }
    ),
    "repo_event": frozenset(
        {
            "event_overnight_p10_pead",
            "event_curve_flatten_pead",
            "event_repo3m_down_pead",
            "surprise_xs_repo3m_down",
            "event_repo3m_down_uncrowded",
            "surprise_xs_overnight_p10",
            "event_curve_flatten_uncrowded",
            "event_on_impulse_uncrowded",
            "cs_overnight_p10_steep",
            "cs_repo3m_down_easy",
        }
    ),
    "vol_fund_cross": frozenset(
        {
            "event_cheap_iv_cheap_pb",
            "surprise_xs_rich_iv_fade",
            "event_nky_high_skip",
            "surprise_xs_div_payer",
            "event_eqar_high_cheap_iv",
            "surprise_xs_eqar_high_cheap_iv",
            "event_ta_up_cheap_iv",
            "event_rich_iv_eqar_low_fade",
            "cs_cheap_pb_cheap_iv",
            "event_div_payer_easy",
            "event_positive_eps_easy",
            "event_cheap_pb_on_impulse",
            "event_eqar_low_cheap_iv_fade",
            "event_div_payer_cheap_iv",
            "cs_eqar_high_overnight_p10",
        }
    ),
}
