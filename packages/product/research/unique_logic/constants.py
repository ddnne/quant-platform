"""Shared unique_logic constants (not eval scores)."""

from __future__ import annotations

from typing import Sequence

from research.unique_logic.catalog import combo_thesis_ids_by_kind, economic_theme_ids

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
        "eq_ar_high",
        "eq_ar_low",
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
# Worker COMBO_EVENT_GATES stays disjoint of PYTHON_ONLY_EVENT_GATES:
# names-only (no generic bodies) would empty occupancy. Python local eval
# or lid-specific daily_path.ts branches cover the intersecting combos.
WORKER_PYTHON_ONLY_GATE_POLICY: str = "python_local_or_lid_branch"
# Event cheap_pb current PB = close/ev.bps; hist is bars×fins reverse-find at
# minHist. CS cheap_pb is csFundSnaps last-fin + pitMedian(..., 20) on union
# dates. Not occupancy-equal (current bps, hist keys, missing-bar last-fin).
# Keep event math; park reuse until proven equal (eval_tracks cheap_pb_event_reuse).
CHEAP_PB_EVENT_VS_CS: str = "event_bars_x_fins_not_csfundsnaps"


def python_only_gate_logic_ids() -> frozenset[str]:
    """Combo lids whose params.gates intersect PYTHON_ONLY_EVENT_GATES.

    Lazy import: ``event_combos`` imports this module. Worker lid branches
    cover the returned set; do not copy remaining PYTHON_ONLY names onto
    Worker ``COMBO_EVENT_GATES`` until leftover occupancy equals
    comboEventGateOk.
    """
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
# Combo evaluator YAML rows. kind cs → CS; event|surprise_xs → EVENT.
_kinds = combo_thesis_ids_by_kind()
_event = _kinds["event"] | _kinds["surprise_xs"]
_cs = _kinds["cs"]
CF_NEW_EVENT_THESIS_IDS: frozenset[str] = _event
CF_NEW_CS_THESIS_IDS: frozenset[str] = _cs
CF_NEW_THESIS_IDS: frozenset[str] = _event | _cs
# Unique-logic recognition set (catalog + factory). Not generation / not GO.
RESEARCH_UNIQUE_LOGIC_IDS: frozenset[str] = (
    EVENT_LOGIC_IDS
    | EVENT_FILTER_LOGIC_IDS
    | EVENT_SIDES_LOGIC_IDS
    | ADAPTIVE_LOGIC_IDS
    | CS_LOGIC_IDS
    | CF_NEW_THESIS_IDS
)
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
# Live candidate filter is occupancy, not this flag.
MF_VALUE_MOM_RATE_DELEGATES: bool = False
MF_VALUE_MOM_RATE_PATH: str = "unique_rate_gated_value_mom"
MF_VALUE_MOM_RATE_PARKED_ALWAYS_ON: bool = False
# If occupancy >= ALWAYS_ON_OCCUPANCY_WARN, summarize parks it (always_on).
# Do not densify to stay under the line.
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
# Worker now uses a linear window series.
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
# Keep the set as the park mechanism; do not restore isolate-limited lids
# without a Worker path.
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
# Gate reorderings are not listed here. YAML is the SoT.
ECONOMIC_THEME_IDS: dict[str, frozenset[str]] = economic_theme_ids()
