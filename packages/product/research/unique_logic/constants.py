"""Shared unique_logic constants (not eval scores)."""

from __future__ import annotations

from typing import Sequence

from research.unique_logic.catalog import (
    combo_thesis_ids_by_kind,
    economic_theme_ids,
    unique_family_ids_from_yaml,
)

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
        "month_end_skip",
        "fy_end",
        "fy_results",
        "fy_start",
        "midmonth",
        "afterclose",
        "overnight_easing",
        "overnight_tightening",
        "easy_funding",
        "tight_funding",
        "steep_curve",
        "uncrowded_margin",
        "crowded_margin",
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
        "eq_ar_falling",
        "eq_ar_high",
        "eq_ar_low",
        "eq_ar_rising",
        "eps_down",
        "np_negative",
        "pb_rising",
        "roe_low",
        "sales_down",
        "ta_down",
        "ta_up",
        "overnight_p10",
        "curve_flatten",
        "repo_3m_down",
        "nky_vol_high_skip",
        "large_surprise",
        "liq_high",
        "pre_mom",
        "price_down",
    }
)
PYTHON_ONLY_EVENT_GATES: frozenset[str] = frozenset()
KNOWN_EVENT_GATES: frozenset[str] = COMBO_EVENT_GATES | PYTHON_ONLY_EVENT_GATES
WORKER_PYTHON_ONLY_GATE_POLICY: str = "python_local_or_lid_branch"
CHEAP_PB_EVENT_VS_CS: str = "event_bars_x_fins_not_csfundsnaps"
CHEAP_PB_EVENT_SOURCE: str = "bars_x_fins_bps_over_close"
CHEAP_PB_CS_SOURCE: str = "cs_fund_snaps"
CHEAP_PB_UNIFIED: bool = False
# Calendar/weekday permutations stay in COMBO_EVENT_GATES (existing occupancy).
# Propose-LLM must not emit them as a new thesis.
PROPOSE_CALENDAR_GATES: frozenset[str] = frozenset(
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
        "month_end_skip",
        "fy_end",
        "fy_results",
        "fy_start",
        "midmonth",
    }
)
PROPOSE_ALLOWED_GATES: frozenset[str] = COMBO_EVENT_GATES - PROPOSE_CALENDAR_GATES
if not PROPOSE_CALENDAR_GATES <= COMBO_EVENT_GATES:
    raise RuntimeError("PROPOSE_CALENDAR_GATES must be a subset of COMBO_EVENT_GATES")
if not PROPOSE_ALLOWED_GATES:
    raise RuntimeError("PROPOSE_ALLOWED_GATES must be non-empty")


def python_only_gate_logic_ids() -> frozenset[str]:
    """Combo lids whose params.gates intersect PYTHON_ONLY_EVENT_GATES."""
    from research.unique_logic.event_combos import NEW_COMBO_LOGIC

    lids: set[str] = set()
    for spec in NEW_COMBO_LOGIC:
        gates = (spec.get("params") or {}).get("gates") or spec.get("gates") or ()
        if PYTHON_ONLY_EVENT_GATES.intersection(str(g) for g in gates):
            lids.add(str(spec["logic_id"]))
    return frozenset(lids)

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
_families = unique_family_ids_from_yaml()
EVENT_LOGIC_IDS: frozenset[str] = _families["event"]
EVENT_FILTER_LOGIC_IDS: frozenset[str] = _families["event_filter"]
EVENT_SIDES_LOGIC_IDS: frozenset[str] = _families["event_sides"]
ADAPTIVE_LOGIC_IDS: frozenset[str] = _families["adaptive"]
CS_LOGIC_IDS: frozenset[str] = _families["cs"]
_kinds = combo_thesis_ids_by_kind()
_event = _kinds["event"] | _kinds["surprise_xs"]
_cs = _kinds["cs"]
CF_NEW_EVENT_THESIS_IDS: frozenset[str] = _event
CF_NEW_CS_THESIS_IDS: frozenset[str] = _cs
CF_NEW_THESIS_IDS: frozenset[str] = _event | _cs
RESEARCH_UNIQUE_LOGIC_IDS: frozenset[str] = (
    EVENT_LOGIC_IDS
    | EVENT_FILTER_LOGIC_IDS
    | EVENT_SIDES_LOGIC_IDS
    | ADAPTIVE_LOGIC_IDS
    | CS_LOGIC_IDS
    | CF_NEW_THESIS_IDS
)
CF_EVENT_DAILY_PATH_IDS: frozenset[str] = (
    EVENT_LOGIC_IDS
    | EVENT_FILTER_LOGIC_IDS
    | EVENT_SIDES_LOGIC_IDS
    | ADAPTIVE_LOGIC_IDS
    | CF_NEW_EVENT_THESIS_IDS
)
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
# Inclusive thin sleeve band is (NEAR_EMPTY, USABLE_OCCUPANCY_MIN].
USABLE_OCCUPANCY_MIN: float = 0.12
# Recorded mean occupancy ≤ NEAR_EMPTY_OCCUPANCY on both tracks (plus32vf).
# Not countable, not basket material. Do not silently unpark.
NEAR_EMPTY_PARK_IDS: frozenset[str] = frozenset(
    {
        "event_cheap_iv_eqar_rising_steep",
        "event_cheap_iv_margin_up_repo3m",
        "event_margin_down_eqar_rising_steep",
        "event_rich_iv_margin_up_eqar_falling_fade",
        "event_nkyvol_steep_uncrowded",
        "event_nkyvol_steep_pre_mom",
        "event_roe_low_tight_on",
        "surprise_xs_pre_mom_roe_low",
        "surprise_xs_repo3m_cheap_iv",
        "surprise_xs_roe_low_uncrowded",
        "event_invert_px_down_roe_low",
        "event_flatten_roe_low_np_neg",
        "event_invert_roe_low",
        "event_p10_px_down_np_neg",
        "event_p10_sales_down_eps_up",
        "event_overnight_p10_np_negative",
        "event_tight_funding_sales_np_neg",
        "event_pb_rising_np_negative",
        "event_flatten_p10_pb_rising",
        "event_flatten_p10_sales_down",
        "event_flatten_p10_px_down",
        "event_flatten_np_tight",
        "event_p10_pb_eps_down",
        "event_p10_pb_sales_down",
        "event_p10_pb_px_down",
        "event_p10_sales_invert",
        "event_p10_sales_px_down",
        "event_pb_eps_tight",
        "event_pb_sales_tight",
        "event_pb_sales_px_down",
        "event_np_steep_easing",
        "event_np_steep",
        "event_pb_tight_px_down",
        "event_flatten_easing",
        "surprise_xs_flatten_easing",
        "event_cheap_iv_cheap_pb",
        "event_cheap_iv_margin_down",
        "event_cheap_iv_steep",
        "event_cheap_pb_margin_down",
        "event_cheap_pb_margin_down_easing_cluster",
        "flow_disagree_skip_friday",
        "fy_end_cs_fade",
        "fy_start_cs_follow",
        "surprise_xs_fy_end",
        "cs_overnight_p10_steep",
        "cs_roe_high",
        "cs_roe_low",
        "event_margin_down_steep",
        "event_margin_down_tight_steep_curve",
        "event_rich_iv_margin_down",
        "event_roe_low_afterclose_fade",
        "event_roe_low_crowded_fade",
        "event_roe_low_fade",
        "event_roe_low_liq_high_fade",
        "event_roe_low_tight_fade",
        "event_steep_margin_up_liq",
        "event_ta_down_margin_up_repo_afterclose",
    }
)
# Recorded mean occupancy ≥ ALWAYS_ON_OCCUPANCY_WARN. Not countable, not
# basket material.
ALWAYS_ON_PARK_IDS: frozenset[str] = frozenset(
    {
        "cs_eqar_falling",
        "cs_eqar_high",
        "cs_eqar_low_fade",
        "cs_eqar_rising",
        "cs_ta_down",
        "cs_ta_up",
        "cs_np_positive",
    }
)
# Countable but too thin for mechanical sleeves (recorded both-track
# occupancy in (NEAR_EMPTY, ~0.12]). Do not use as basket material.
THIN_SLEEVE_EXCLUDE_IDS: frozenset[str] = frozenset(
    {
        "event_p10_pb_rising",
        "event_overnight_p10_eps_down",
        "event_eps_down_pb_rising",
        "event_flatten_overnight_p10",
        "event_invert_px_down_tight_funding",
        "event_p10_eps_down_px_down",
        "event_overnight_p10_sales_down",
        "event_tight_funding_eps_px_down",
        "event_invert_tight_sales_down",
        "event_steep_tight_px_down",
        "event_easing_eps_down_np_neg",
        "event_pb_rising_sales_down",
        "event_pb_rising_px_down",
        "event_np_negative_tight_funding",
        "event_flatten_p10_eps_down",
        "event_flatten_pb_eps_down",
        "event_flatten_pb_sales_down",
        "event_flatten_np_px_down",
        "event_flatten_pb_tight",
        "event_flatten_pb_px_down",
        "event_flatten_np_sales_down",
        "event_flatten_sales_tight",
        "event_flatten_sales_px_down",
        "event_p10_pb_invert",
        "event_p10_eps_sales_down",
        "event_p10_eps_invert",
        "event_p10_invert_px_down",
        "event_pb_eps_sales_down",
        "event_pb_eps_invert",
        "event_pb_eps_px_down",
        "event_pb_sales_invert",
        "event_pb_invert_tight",
        "event_pb_invert_px_down",
        "event_eps_np_px_down",
        "event_eps_np_sales_down",
        "event_flatten_repo3m_np_neg",
        "event_eps_px_steep",
        "event_eps_steep",
        "event_div_margin_up",
        "surprise_xs_div_margin_up",
        "cs_cheap_pb_cheap_iv",
        "event_cheap_iv_cluster_uncrowded",
        "event_cheap_iv_eps_down",
        "event_cheap_iv_eqar_falling_fade",
        "event_cheap_iv_liq_eqar_high",
        "event_cheap_iv_liq_uncrowded",
        "event_cheap_iv_on_impulse",
        "event_cheap_iv_overnight_easing",
        "event_cheap_iv_ta_up_easy",
        "event_cheap_iv_uncrowded",
        "event_cheap_pb_easy_funding",
        "event_cheap_pb_eps_up",
        "event_cheap_pb_margin_up_fade",
        "event_cheap_pb_on_impulse",
        "event_cheap_pb_repo3m_down",
        "event_cheap_pb_cluster",
        "event_cheap_pb_price_down_liq",
        "fy_end_event_fade",
        "surprise_xs_afterclose_cheap_iv",
        "surprise_xs_cheap_iv_liq",
        "surprise_xs_eqar_high_cheap_iv",
        "event_np_invert_px",
        "event_np_sales_px",
        "event_sales_tight_px",
        "event_np_sales_invert",
        "event_steep_tight_on",
        "cs_eqar_high_cheap_iv",
        "cs_margin_down_easy",
        "cs_margin_up_easy",
        "event_cluster_steep_curve",
        "event_crowded_cheap_iv",
        "event_div_payer_margin_down",
        "event_div_payer_price_down",
        "event_div_payer_cheap_iv",
        "event_easing_pb_rising",
        "event_easy_funding_curve_steep",
        "event_eps_up_margin_up_easing",
        "event_eqar_high_cheap_iv",
        "event_eqar_high_overnight_p10",
        "event_eqar_high_steep",
        "event_eqar_low_cheap_iv_fade",
        "event_eqar_rising_cheap_iv",
        "fy_start_event_follow",
        "surprise_xs_impulse_np_neg",
        "surprise_xs_margin_down_on_impulse",
        "surprise_xs_margin_down_p10",
        "surprise_xs_nkyvol_cheap_iv",
        "surprise_xs_nkyvol_np_neg",
        "surprise_xs_eqar_high_np_neg",
        "surprise_xs_pb_rising_crowded",
        "event_eqar_rising_steep_curve",
        "event_large_surprise_steep_curve",
        "event_margin_down_easing",
        "event_margin_down_easing_liq",
        "event_margin_down_easing_ta_up",
        "event_margin_down_on_impulse",
        "event_margin_down_overnight_tight",
        "event_margin_down_price_down",
        "event_margin_uncrowded_steep",
        "event_margin_up_eqar_low_nkyvol_fade",
        "event_margin_up_overnight_tight",
        "event_margin_up_repo3m_down",
        "event_margin_up_repo3m_eqar_rising",
        "event_margin_up_steep_curve",
        "event_margin_up_ta_down_overnight_tight_fade",
        "event_may_easing",
        "event_may_results_follow",
        "event_midmonth_steep",
        "event_nkyvol_invert_margin_down",
        "event_nkyvol_liq_div",
        "event_nkyvol_liq_margin_down",
        "event_nkyvol_margin_down",
        "event_nkyvol_margin_up_ta_down",
        "event_nkyvol_repo3m_eqar_high",
        "event_nkyvol_tight_ta_down",
        "event_nkyvol_uncrowded_div",
        "event_np_negative_price_down_liq_fade",
        "event_overnight_p10_uncrowded",
        "event_overnight_tight_eqar_falling_steep_fade",
        "event_pb_rising_margin_up_fade",
        "event_pb_rising_tight_fade",
        "event_repo3m_div",
        "event_repo3m_down_np_neg",
        "event_repo3m_margin_down",
        "event_repo3m_margin_up_eqar_high",
        "event_rich_iv_crowded_repo3m_fade",
        "event_rich_iv_eqar_low_overnight_tight_fade",
        "event_rich_iv_invert_sales_down_fade",
        "event_rich_iv_tight_funding_fade",
        "event_rich_iv_tight_ta_down_fade",
        "event_steep_eqar_falling",
        "event_ta_down_cheap_pb",
        "surprise_xs_rich_iv_tight_on",
        "event_liq_high_overnight_tight_margin_up",
        "event_liq_high_steep_curve",
        "event_ta_down_steep_curve",
        "event_ta_down_tight_liq_fade",
        "event_ta_up_cheap_iv",
        "event_ta_up_margin_up_tight_premom",
        "event_ta_up_np_neg_price_down_fade",
        "event_tight_on_np_neg",
        "event_tue_thu_steep",
        "event_uncrowded_easing_div",
        "event_uncrowded_eqar_rising_steep",
        "event_uncrowded_overnight_p10",
        "cs_margin_up_tight_fade",
        "event_eqar_rising_cheap_pb_liq",
        "event_flatten_tight_px_down",
        "event_nkyvol_easing_div",
        "event_pre_mom_steep_curve",
        "event_price_down_nkyvol_repo3m_fade",
        "event_px_down_p10",
    }
)
MF_VALUE_MOM_RATE_DELEGATES: bool = False
MF_VALUE_MOM_RATE_PATH: str = "unique_rate_gated_value_mom"
MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON: bool = False
TERM_STRUCTURE_REQUIRED: frozenset[str] = frozenset(
    {
        "opt225_atm_iv_term_ratio",
        "opt225_basevol_term_ratio",
    }
)
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
WORKER_ISOLATE_LIMIT_IDS: frozenset[str] = frozenset()
WORKER_ISOLATE_LIMIT_REASONS: dict[str, str] = {}
SPARSE_ON_15NAME_SHARD: frozenset[str] = frozenset(
    {
        "event_may_easing",
        "flow_disagree_tue_thu",
        "event_midmonth_steep",
        "cs_steep_friday",
        "flow_disagree_skip_friday",
    }
)
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
    # plus32q both-track occupancy ≤ 0.05 (parked). Do not re-emit.
    (frozenset({"nky_vol_high_skip", "steep_curve"}), "nkyvol_plus_steep"),
    # plus32vf both-track occupancy ≤ 0.05 (parked). Do not re-emit.
    (frozenset({"cheap_iv", "steep_curve"}), "cheap_iv_plus_steep"),
    (frozenset({"cheap_iv", "margin_up", "repo_3m_down"}), "cheap_iv_margin_up_repo3m"),
    (frozenset({"margin_down", "eq_ar_rising", "steep_curve"}), "margin_down_eqar_rising_steep"),
    (frozenset({"rich_iv", "margin_up", "eq_ar_falling"}), "rich_iv_margin_up_eqar_falling"),
    # plus60 both-track occupancy ≤ 0.05 (parked). Do not re-emit.
    (frozenset({"roe_low", "overnight_tightening"}), "roe_low_plus_tight_on"),
    (frozenset({"pre_mom", "roe_low"}), "pre_mom_plus_roe_low"),
    (frozenset({"repo_3m_down", "cheap_iv"}), "repo3m_plus_cheap_iv"),
    (frozenset({"roe_low", "uncrowded_margin"}), "roe_low_plus_uncrowded"),
    (frozenset({"invert_curve", "price_down", "roe_low"}), "invert_px_down_roe_low"),
    (frozenset({"curve_flatten", "roe_low", "np_negative"}), "flatten_roe_low_np_neg"),
    (frozenset({"invert_curve", "roe_low"}), "invert_plus_roe_low"),
    (frozenset({"overnight_p10", "price_down", "np_negative"}), "p10_px_down_np_neg"),
    (frozenset({"overnight_p10", "sales_down", "eps_up"}), "p10_sales_down_eps_up"),
    (frozenset({"overnight_p10", "np_negative"}), "p10_np_negative"),
    (frozenset({"tight_funding", "sales_down", "np_negative"}), "tight_sales_np_neg"),
    (frozenset({"pb_rising", "np_negative"}), "pb_rising_np_negative"),
    (frozenset({"curve_flatten", "overnight_p10", "pb_rising"}), "flatten_p10_pb_rising"),
    (frozenset({"curve_flatten", "overnight_p10", "sales_down"}), "flatten_p10_sales_down"),
    (frozenset({"curve_flatten", "overnight_p10", "price_down"}), "flatten_p10_px_down"),
    (frozenset({"curve_flatten", "np_negative", "tight_funding"}), "flatten_np_tight"),
    (frozenset({"overnight_p10", "pb_rising", "eps_down"}), "p10_pb_eps_down"),
    (frozenset({"overnight_p10", "pb_rising", "sales_down"}), "p10_pb_sales_down"),
    (frozenset({"overnight_p10", "pb_rising", "price_down"}), "p10_pb_px_down"),
    (frozenset({"overnight_p10", "sales_down", "invert_curve"}), "p10_sales_invert"),
    (frozenset({"overnight_p10", "sales_down", "price_down"}), "p10_sales_px_down"),
    (frozenset({"pb_rising", "eps_down", "tight_funding"}), "pb_eps_tight"),
    (frozenset({"pb_rising", "sales_down", "tight_funding"}), "pb_sales_tight"),
    (frozenset({"pb_rising", "sales_down", "price_down"}), "pb_sales_px_down"),
    (frozenset({"np_negative", "steep_curve", "overnight_easing"}), "np_steep_easing"),
    (frozenset({"np_negative", "steep_curve"}), "np_steep"),
    (frozenset({"pb_rising", "tight_funding", "price_down"}), "pb_tight_px_down"),
    (frozenset({"fy_end"}), "fy_end_empty"),
)


def _occupancy_parent_two_ands() -> tuple[tuple[frozenset[str], str], ...]:
    """1-AND park and 2-AND thin/park YAML. Nested ANDs cannot be sleeve material."""
    from research.unique_logic.catalog import load_catalog_specs

    wanted = NEAR_EMPTY_PARK_IDS | THIN_SLEEVE_EXCLUDE_IDS
    seen = {combo for combo, _reason in SPARSE_GATE_COMBOS}
    out: list[tuple[frozenset[str], str]] = []
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "")
        if lid not in wanted:
            continue
        params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
        raw = params.get("gates") or spec.get("gates") or ""
        if isinstance(raw, str):
            gset = frozenset(x.strip() for x in raw.split(",") if x.strip())
        else:
            gset = frozenset(str(x) for x in raw if str(x).strip())
        n = len(gset)
        if n == 1 and lid not in NEAR_EMPTY_PARK_IDS:
            continue
        if n not in (1, 2) or gset in seen:
            continue
        seen.add(gset)
        out.append((gset, f"occupancy_parent_{lid}"))
    return tuple(out)


SPARSE_GATE_COMBOS = SPARSE_GATE_COMBOS + _occupancy_parent_two_ands()
NAME_LEVEL_FUND_CS_GATES: frozenset[str] = frozenset(
    {
        "eq_ar_falling",
        "eq_ar_high",
        "eq_ar_low_invert",
        "eq_ar_rising",
        "ta_down",
        "ta_up",
        "cheap_pb",
        "expensive_pb_invert",
        "earnings_yield_high",
        "pb_rising",
        "roe_high",
        "roe_low",
        "sales_down",
        "div_positive",
        "np_positive",
    }
)
ALWAYS_ON_CS_STICKY: frozenset[str] = frozenset(
    {
        "cs_eqar_falling",
        "cs_eqar_high",
        "cs_eqar_low_fade",
        "cs_eqar_rising",
        "cs_ta_down",
        "cs_ta_up",
        "cs_cheap_pb",
        "cs_expensive_pb_fade",
        "cs_earnings_yield_high",
        "cs_pb_rising",
        "cs_roe_high",
        "cs_roe_low",
        "cs_sales_down",
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
        "worker_body_missing",
        "unique22_occupancy_mismatch",
        "near_empty_parked",
        "always_on_parked",
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

ECONOMIC_THEME_IDS: dict[str, frozenset[str]] = economic_theme_ids()


def worker_implemented_logic_ids() -> frozenset[str]:
    """IDs that have Worker bodies. YAML-only clones do not count."""
    from research.unique_logic.worker_bodies import (
        worker_implemented_logic_ids as _impl,
    )

    return _impl()


def countable_thesis_ids() -> frozenset[str]:
    """Catalog + Worker body + implemented gates; YAML clones do not count."""
    from research.unique_logic.worker_bodies import countable_thesis_ids as _impl

    return _impl()
