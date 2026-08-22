"""Factory logic-template catalog.

Overlapping 30 ids consume ``research.bar_native_specs.BAR_NATIVE_SPECS``
as SoT. Six factory-only ids stay explicit (offline-only; CF bar-native
set stays 30).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from research.bar_native_specs import BAR_NATIVE_LOGIC_IDS, BAR_NATIVE_SPECS
from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    MASS_RESEARCH,
    READY_DECLARED,
)
from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_MULTI_DAY_HOLD,
)
from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS

# Optional families not in hypothesis_classes registry.
FAMILY_VOL_RISK_ADJUSTED: str = "vol_risk_adjusted"
FAMILY_RATE_FACTOR: str = "rate_factor"
FAMILY_MULTI_FACTOR: str = "multi_factor"
FAMILY_INDEX_VOL_REGIME: str = "index_vol_regime"
FAMILY_OPTIONS_VOL_REGIME: str = "options_vol_regime"
# W105: research-family recognition only (not promotion / not generation).
# Distinct unique family_ids so factory period-net is not stuck at
# unknown_family. Registration = recognition, not a pass.
FAMILY_EVENT_FUNDING_COMBO: str = "event_funding_combo"
FAMILY_EVENT_MACRO_CURVE_COMBO: str = "event_macro_curve_combo"
FAMILY_DISCLOSURE_CLUSTER_GATE: str = "disclosure_cluster_gate"
FAMILY_SURPRISE_XS_RANK: str = "surprise_xs_rank"
FAMILY_LARGE_SURPRISE_FILTER: str = "large_surprise_filter"
FAMILY_AFTERCLOSE_EVENT_TIMING: str = "afterclose_event_timing"
FAMILY_EVENT_MOM_AGREE_COMBO: str = "event_mom_agree_combo"
FAMILY_EVENT_MARGIN_CROWD_COMBO: str = "event_margin_crowd_combo"
FAMILY_FUNDING_IMPULSE_CS: str = "funding_impulse_cs"
FAMILY_CURVE_STEEPEN_IMPULSE_CS: str = "curve_steepen_impulse_cs"
FAMILY_XS_MARGIN_DELTA: str = "xs_margin_delta"
FAMILY_IDIO_MOM_MACRO: str = "idio_mom_macro"
FAMILY_OVERNIGHT_LEVEL_CS: str = "overnight_level_cs"
FAMILY_MONTH_END_CS: str = "month_end_cs"
FAMILY_XS_LOW_VOL_MOM: str = "xs_low_vol_mom"
FAMILY_REPO_3M_LEVEL_CS: str = "repo_3m_level_cs"
FAMILY_EVENT_CALENDAR_GATE: str = "event_calendar_gate"
FAMILY_RESEARCH_UNIQUE_LOGIC: str = "research_unique_logic"
RESEARCH_UNIQUE_FAMILY_IDS: frozenset[str] = frozenset(
    {
        FAMILY_EVENT_FUNDING_COMBO,
        FAMILY_EVENT_MACRO_CURVE_COMBO,
        FAMILY_DISCLOSURE_CLUSTER_GATE,
        FAMILY_SURPRISE_XS_RANK,
        FAMILY_LARGE_SURPRISE_FILTER,
        FAMILY_AFTERCLOSE_EVENT_TIMING,
        FAMILY_EVENT_MOM_AGREE_COMBO,
        FAMILY_EVENT_MARGIN_CROWD_COMBO,
        FAMILY_FUNDING_IMPULSE_CS,
        FAMILY_CURVE_STEEPEN_IMPULSE_CS,
        FAMILY_XS_MARGIN_DELTA,
        FAMILY_IDIO_MOM_MACRO,
        FAMILY_OVERNIGHT_LEVEL_CS,
        FAMILY_MONTH_END_CS,
        FAMILY_XS_LOW_VOL_MOM,
        FAMILY_REPO_3M_LEVEL_CS,
        FAMILY_EVENT_CALENDAR_GATE,
    }
)
RESEARCH_FAMILY_APPEND_LOGIC_IDS: frozenset[str] = frozenset(
    {
        "overnight_level_cs_tilt",
        "overnight_easy_cs_follow",
        "month_end_cs_fade",
        "xs_low_vol_mom",
        "repo_3m_level_cs",
        "event_funding_adaptive_side",
        "surprise_xs_rank_adaptive",
    }
)
RESEARCH_FAMILY_REGISTER_ID: str = "unique_logic_research_family"
RESEARCH_FAMILY_APPEND_ID: str = "unique_logic_family_append"
RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS: bool = True
RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE: bool = False

# Near-groups stay parallel (do not merge).
NEAR_LOGIC_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "group_id": "flow_margin_confirm",
        "label": "flow hard/soft/pressure (near-group parallel)",
        "logic_ids": (
            "flow_margin_pressure",
            "flow_margin_short_hard",
            "flow_margin_short_soft",
            "mf_flow_price",
        ),
        "note": "Keep hard/soft/pressure + mf_flow_price parallel.",
    },
    {
        "group_id": "fund_value_mom",
        "label": "fund value×mom (slow variant parallel)",
        "logic_ids": (
            "fund_value_mom_agree",
            "fund_value_mom_agree_slow",
            "mf_value_mom_rate",
        ),
        "note": "Slow variant + unique rate-gated book stay parallel.",
    },
    {
        "group_id": "rate_macro_family",
        "label": "rate / macro family (level vs change vs CS factor)",
        "logic_ids": (
            "macro_repo_rate_change",
            "macro_repo_rate_level",
            "rate_abs_level_xs",
            "rate_curve_shape_xs",
        ),
        "note": "macro_* mom-gate vs rate_* CS factor; do not merge.",
    },
    {
        "group_id": "vol_family_name_vs_index",
        "label": "vol family: per-name gate vs index-vol regime (parallel)",
        "logic_ids": (
            "vol_risk_adjusted_mom",
            "vol_breakout_expand",
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ),
        "note": "Per-name vol gate vs index-level nky_vol_*; do not merge.",
    },
    {
        "group_id": "index_vol_regime_family",
        "label": "index vol regime (abs vs term levels vs ratio)",
        "logic_ids": (
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ),
        "note": "Abs / dual-levels / ratio stay parallel.",
    },
    {
        "group_id": "options_vol_regime_family",
        "label": "options_225 BaseVol / skew / CM-term / Δvol (+ ATM compare-only)",
        "logic_ids": (
            "opt225_basevol_abs_level",
            "opt225_basevol_term_levels",
            "opt225_basevol_term_ratio",
            "opt225_basevol_delta_abs",
            "opt225_skew_abs_level",
            "opt225_cm_term_abs_level",
            "opt225_atm_iv_abs_level",
            "opt225_atm_iv_term_levels",
            "opt225_atm_iv_term_ratio",
            "opt225_iv_base_spread_abs",
            "opt225_iv_base_spread_change",
        ),
        "note": "BaseVol canonical; ATM/spread compare-only; keep vs nky_vol_*.",
    },
    {
        "group_id": "nky_vol_proxy_vs_options_sot",
        "label": "Nikkei vol: TOPIX/NK225F RV proxy vs options_225 SoT",
        "logic_ids": (
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
            "opt225_basevol_abs_level",
            "opt225_skew_abs_level",
            "opt225_atm_iv_abs_level",
        ),
        "note": "nky_vol_* proxy vs opt225 BaseVol SoT; keep parallel.",
    },
    {
        "group_id": "unique_logic_research_family",
        "label": "unique_logic research family (recognition only)",
        "logic_ids": (
            "event_funding_stress_skip",
            "curve_steep_event_confirm",
            "disclosure_cluster_mom_gate",
            "surprise_xs_rank_hold",
            "large_surprise_event_hold",
            "afterclose_only_event_hold",
            "event_pre_mom_agree_hold",
            "event_margin_crowding_skip",
            "event_funding_easy_short",
            "event_funding_stress_ls",
            "surprise_xs_rank_flip",
            "funding_impulse_cs_tilt",
            "curve_steepen_impulse_cs",
            "xs_margin_delta_rank",
            "idio_mom_macro_impulse",
            "overnight_level_cs_tilt",
            "overnight_easy_cs_follow",
            "month_end_cs_fade",
            "xs_low_vol_mom",
            "repo_3m_level_cs",
            "event_funding_adaptive_side",
            "surprise_xs_rank_adaptive",
        ),
        "note": "Recognition only; generation_enabled=False; not a pass.",
    },
    {
        "group_id": "unique_logic_ls_append",
        "label": "unique_logic family append L/S (recognition only)",
        "logic_ids": (
            "funding_impulse_cs_tilt",
            "curve_steepen_impulse_cs",
            "xs_margin_delta_rank",
            "idio_mom_macro_impulse",
            "event_funding_easy_short",
            "event_funding_stress_ls",
            "surprise_xs_rank_flip",
        ),
        "note": "Recognition-only L/S append; not a pass.",
    },
    {
        "group_id": "unique_logic_overlay_append",
        "label": "unique_logic family append overlay (recognition only)",
        "logic_ids": (
            "overnight_level_cs_tilt",
            "overnight_easy_cs_follow",
            "month_end_cs_fade",
            "xs_low_vol_mom",
            "repo_3m_level_cs",
            "event_funding_adaptive_side",
            "surprise_xs_rank_adaptive",
        ),
        "note": "Recognition-only overlay append; not a pass.",
    },
)

# Numeric-only knobs that do **not** create a new logic by themselves.
NUMERIC_ONLY_KNOBS: frozenset[str] = frozenset(
    {
        "hold_days",
        "post_hold_days",
        "momentum_n",
        "long_frac",
        "short_frac",
        "vol_n",
        "vol_threshold",
        "high_threshold",
        "low_threshold",
    }
)

FACTORY_ONLY_LOGIC_IDS: tuple[str, ...] = (
    "event_post_disclosure_hold",
    "event_post_long_horizon",
    "mdh_short_horizon_mom",
    "rate_abs_level_xs",
    "rate_curve_shape_xs",
    "xs_rank_mom_slow",
)

# Catalog order matches the historical factory template list.
_LOGIC_TEMPLATE_ORDER: tuple[str, ...] = (
    "mdh_sticky_momentum",
    "mdh_mean_reversion",
    "event_post_disclosure_hold",
    "xs_rank_ls_sticky",
    "xs_rank_ls_daily",
    "macro_repo_rate_change",
    "macro_repo_rate_level",
    "fund_value_only",
    "fund_value_mom_agree",
    "flow_margin_pressure",
    "flow_margin_short_hard",
    "flow_margin_short_soft",
    "vol_risk_adjusted_mom",
    "vol_breakout_expand",
    "xs_rank_mom_slow",
    "mdh_short_horizon_mom",
    "event_post_long_horizon",
    "fund_value_mom_agree_slow",
    "rate_abs_level_xs",
    "rate_curve_shape_xs",
    "mf_value_mom_rate",
    "mf_flow_price",
    "nky_vol_abs_level",
    "nky_vol_term_levels",
    "nky_vol_term_ratio",
    "opt225_basevol_abs_level",
    "opt225_basevol_term_levels",
    "opt225_basevol_term_ratio",
    "opt225_atm_iv_abs_level",
    "opt225_atm_iv_term_levels",
    "opt225_atm_iv_term_ratio",
    "opt225_iv_base_spread_abs",
    "opt225_iv_base_spread_change",
    "opt225_skew_abs_level",
    "opt225_cm_term_abs_level",
    "opt225_basevol_delta_abs",
)


@dataclass(frozen=True)
class LogicTemplate:
    """One distinct economic logic (counts toward unique_logic).

    Counts as different from another template only if it differs in
    info source, entry logic, position construction, or economic thesis.
    """

    logic_id: str
    thesis: str
    signal_definition: str
    position_rule: str
    datasets_used: tuple[str, ...]
    # Eval dispatch family (class_hyp / factory-local)
    family_id: str
    # Canonical params for the logic (not a grid)
    base_params: Mapping[str, Any]
    # Coarse structural axes that are part of the logic fingerprint
    # (modes / entry structures — NOT hold/mom/frac alone)
    structural_keys: tuple[str, ...] = ()
    display_name: str = ""
    generation_enabled: bool = True
    notes: str = ""
    # Occupancy filter is the live candidate rule. Catalog hint only.
    main_pool: bool = True
    data_requirement: str = ""

    def logic_fingerprint(self) -> str:
        """Stable fingerprint of the economic logic (no numeric knobs)."""
        payload = {
            "logic_id": self.logic_id,
            "family_id": self.family_id,
            "signal_definition": self.signal_definition,
            "position_rule": self.position_rule,
            "datasets": list(self.datasets_used),
            "structural": {
                k: self.base_params.get(k)
                for k in self.structural_keys
                if k in self.base_params
            },
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "logic_id": self.logic_id,
            "display_name": self.display_name or self.logic_id,
            "thesis": self.thesis,
            "signal_definition": self.signal_definition,
            "position_rule": self.position_rule,
            "datasets_used": list(self.datasets_used),
            "family_id": self.family_id,
            "base_params": dict(self.base_params),
            "structural_keys": list(self.structural_keys),
            "logic_fingerprint": self.logic_fingerprint(),
            "generation_enabled": self.generation_enabled,
            "notes": self.notes,
            "main_pool": self.main_pool,
            "data_requirement": self.data_requirement,
        }


def logic_template_from_bar_native(
    spec: Mapping[str, Any],
    *,
    display_name: str = "",
    generation_enabled: bool = True,
    notes: str = "",
    main_pool: bool = True,
    data_requirement: str = "",
) -> LogicTemplate:
    """Rebuild a factory LogicTemplate from a BAR_NATIVE_SPECS row."""
    return LogicTemplate(
        logic_id=str(spec["logic_id"]),
        thesis=str(spec["thesis"]),
        signal_definition=str(spec["signal_definition"]),
        position_rule=str(spec["position_rule"]),
        datasets_used=tuple(spec["datasets_used"]),
        family_id=str(spec["family_id"]),
        base_params=dict(spec["params"]),
        structural_keys=tuple(spec.get("structural_keys") or ()),
        display_name=display_name,
        generation_enabled=bool(generation_enabled),
        notes=notes,
        main_pool=bool(main_pool),
        data_requirement=data_requirement,
    )


def _ov(
    display_name: str,
    *,
    generation_enabled: bool = True,
    notes: str = "",
    main_pool: bool = True,
    data_requirement: str = "",
) -> dict[str, Any]:
    """Factory-only overlay on a bar-native spec (do not flip generation)."""
    return {
        "display_name": display_name,
        "generation_enabled": generation_enabled,
        "notes": notes,
        "main_pool": main_pool,
        "data_requirement": data_requirement,
    }


# Preserve factory display_name / notes / main_pool / generation_enabled.
_BAR_NATIVE_TEMPLATE_OVERLAY: dict[str, dict[str, Any]] = {
    "mdh_sticky_momentum": _ov("Sticky multi-day momentum"),
    "mdh_mean_reversion": _ov(
        "Sticky multi-day mean reversion",
        notes="Distinct entry logic vs mdh_sticky_momentum; not an eval sign flip.",
    ),
    "xs_rank_ls_sticky": _ov(
        "Cross-section rank L-S sticky",
        notes="Canonical frozen cross_section_hold_10 (mom5) shape; not a retune.",
    ),
    "xs_rank_ls_daily": _ov(
        "Cross-section rank L-S daily rebalance",
        notes="Daily vs sticky position construction.",
    ),
    "macro_repo_rate_change": _ov("Macro-conditioned mom (repo rate change)"),
    "macro_repo_rate_level": _ov("Macro-conditioned mom (repo rate level)"),
    "fund_value_only": _ov("Fundamentals value-only"),
    "fund_value_mom_agree": _ov(
        "Fundamentals value × momentum agree",
        notes="Canonical shape matches frozen fundamentals_hold_10; not a retune.",
    ),
    "flow_margin_pressure": _ov("Margin flow multi-day pressure"),
    "flow_margin_short_hard": _ov("Margin flow + hard short confirm"),
    "flow_margin_short_soft": _ov("Margin flow + soft short confirm"),
    "vol_risk_adjusted_mom": _ov(
        "Vol-risk gated momentum",
        notes="Research-only family; not in hypothesis_classes registry.",
    ),
    "vol_breakout_expand": _ov(
        "Vol-expansion breakout mom",
        notes="Different gate vs mom_over_vol.",
    ),
    "fund_value_mom_agree_slow": _ov(
        "Value×mom agree (slow price confirm)",
        notes="Distinct mom_structure; not a mom grid. Keep parallel.",
    ),
    "mf_value_mom_rate": _ov(
        "Value × mom × rate multi-factor",
        notes=(
            "Unique rate-gated value×mom (not an alias of fund_value_mom_agree). "
            "Occupancy is the live candidate filter. No densify."
        ),
    ),
    "mf_flow_price": _ov(
        "Flow × price multi-factor",
        notes="Keep parallel in flow near-group; do not merge.",
    ),
    "nky_vol_abs_level": _ov(
        "Nikkei abs vol-level × CS risk-on/off",
        notes="Index-level vol; distinct from per-name vol_risk_adjusted_mom.",
    ),
    "nky_vol_term_levels": _ov(
        "Nikkei short+long vol levels × CS",
        notes="Dual absolute levels; keep parallel to abs and ratio.",
    ),
    "nky_vol_term_ratio": _ov(
        "Nikkei short/long vol ratio × CS",
        notes="Index-level term ratio; proxy/compare vs options_225 SoT.",
    ),
    "opt225_basevol_abs_level": _ov(
        "options_225 BaseVol abs × CS risk-on/off",
        notes="Canonical Nikkei vol SoT; keep parallel to nky_vol_* proxy.",
    ),
    "opt225_basevol_term_levels": _ov(
        "options_225 BaseVol short+long levels × CS",
        notes="BaseVol-only dual levels. Do not drop in favor of ATM-only.",
    ),
    "opt225_basevol_term_ratio": _ov(
        "options_225 BaseVol short/long ratio × CS",
        notes="Requires distinct short/long BaseVol maps.",
        main_pool=False,
        data_requirement="distinct short/long BaseVol maps",
    ),
    "opt225_atm_iv_abs_level": _ov(
        "options_225 ATM IV abs × CS (compare-only)",
        notes="COMPARE-ONLY. Prefer BaseVol as canonical level.",
    ),
    "opt225_atm_iv_term_levels": _ov(
        "options_225 ATM IV short+long levels × CS (compare-only)",
        notes="COMPARE-ONLY ATM dual levels. Prefer BaseVol dual levels.",
    ),
    "opt225_atm_iv_term_ratio": _ov(
        "options_225 ATM IV short/long ratio × CS (compare-only)",
        notes="COMPARE-ONLY. Requires distinct short/long ATM IV maps.",
        main_pool=False,
        data_requirement="distinct short/long ATM IV maps",
    ),
    "opt225_iv_base_spread_abs": _ov(
        "options_225 (ATM IV − BaseVol) abs × CS (compare-only)",
        notes="COMPARE-ONLY. Spread = atm_iv - base_vol.",
    ),
    "opt225_iv_base_spread_change": _ov(
        "options_225 (ATM−BaseVol) change × CS (compare-only)",
        notes="COMPARE-ONLY spread-change leg; parallel to abs spread.",
    ),
    "opt225_skew_abs_level": _ov(
        "options_225 95% put skew abs × CS",
        notes="put_iv(~0.95*S)−atm_mid. Never invent strikes.",
    ),
    "opt225_cm_term_abs_level": _ov(
        "options_225 near−next CM ATM term abs × CS",
        notes="Near−next CM term; distinct from rolling short/long term.",
    ),
    "opt225_basevol_delta_abs": _ov(
        "options_225 BaseVol Δ abs × CS",
        notes="Canonical-level arithmetic delta.",
    ),
}


def _factory_only_templates() -> list[LogicTemplate]:
    """Offline-only templates (not in the CF bar-native set of 30)."""
    bars = ("equities_bars_daily", "markets_calendar")
    bars_idx = bars + ("indices_bars_daily_topix",)
    return [
        LogicTemplate(
            logic_id="event_post_disclosure_hold",
            display_name="Post-disclosure PIT hold",
            thesis="Post-earnings / disclosure drift after PIT-available close only",
            signal_definition="earnings surprise proxy; entry only when DiscTime pre-close",
            position_rule="fixed post_hold after first non-look-ahead session close",
            datasets_used=("fins_summary",) + bars,
            family_id=CLASS_EVENT_POST,
            base_params={
                "post_hold_days": 5,
                "entry_mode": "same_day_close_if_pre_close",
            },
            structural_keys=("entry_mode",),
            notes="Look-ahead entry modes gen-time rejected.",
        ),
        LogicTemplate(
            logic_id="xs_rank_mom_slow",
            display_name="Cross-section slow-mom L-S sticky",
            thesis="Slower cross-section ranking horizon captures different relative book",
            signal_definition="rank on longer momentum window; sticky L/S",
            position_rule="sticky balanced L/S; structural mom horizon = slow",
            datasets_used=bars_idx,
            family_id=CLASS_CROSS_SECTION_RELATIVE,
            base_params={
                "hold_days": 10,
                "momentum_n": 20,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "book_mode": "balanced_ls_slow_mom",
            },
            structural_keys=("book_mode",),
            notes="Slow-rank construction (mom=20 pin); not a free mom grid.",
        ),
        LogicTemplate(
            logic_id="mdh_short_horizon_mom",
            display_name="Short-horizon sticky momentum",
            thesis="Very short multi-day continuation (5d structure) is a different hold economy",
            signal_definition="sign(mom) with 5d structural horizon",
            position_rule="fixed_horizon hold=5 (structure, not grid sample)",
            datasets_used=bars_idx,
            family_id=CLASS_MULTI_DAY_HOLD,
            base_params={
                "hold_days": 5,
                "momentum_n": 5,
                "rebalance_mode": "fixed_horizon",
                "signal_polarity": 1,
                "horizon_structure": "short_5d",
            },
            structural_keys=("rebalance_mode", "signal_polarity", "horizon_structure"),
            notes="5d horizon structure; not a hold_days clone of mdh_sticky_momentum.",
        ),
        LogicTemplate(
            logic_id="event_post_long_horizon",
            display_name="Post-disclosure long drift hold",
            thesis="Longer post-disclosure drift (20d) harvests slower earnings information",
            signal_definition="surprise proxy; longer post_hold structure",
            position_rule="post_hold_days=20 PIT entry",
            datasets_used=("fins_summary",) + bars,
            family_id=CLASS_EVENT_POST,
            base_params={
                "post_hold_days": 20,
                "entry_mode": "same_day_close_if_pre_close",
                "horizon_structure": "long_20d",
            },
            structural_keys=("entry_mode", "horizon_structure"),
        ),
        LogicTemplate(
            logic_id="rate_abs_level_xs",
            display_name="Absolute rate-level × CS risk-on/off",
            thesis=(
                "Absolute Tokyo repo funding level is a risk-appetite factor: "
                "low rates → risk-on keep CS relative strength book; "
                "high rates → risk-off reverse CS book; mid → flat"
            ),
            signal_definition=(
                "CS rank(mom) L-S signs risk-adjusted by absolute repo rate_level "
                "(not unidirectional mom gate)"
            ),
            position_rule="sticky fixed_horizon balanced L/S after rate-level book transform",
            datasets_used=bars_idx + ("jsda_tokyo_repo_rates",),
            family_id=FAMILY_RATE_FACTOR,
            base_params={
                "mode": "rate_level_xs_risk_adj",
                "momentum_n": 5,
                "hold_days": 10,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "high_threshold": 0.05,
                "low_threshold": 0.0,
            },
            structural_keys=("mode",),
            notes=(
                "Distinct from macro_repo_rate_level (mom gate). Combines rate "
                "factor with CS position construction."
            ),
        ),
        LogicTemplate(
            logic_id="rate_curve_shape_xs",
            display_name="Repo curve-shape × CS risk-on/off",
            thesis=(
                "Funding term-structure steepness proxies risk appetite: "
                "steep (3M−ON > 0) → keep CS book; inverted → reverse; flat → no trade"
            ),
            signal_definition=(
                "curve_spread = rate(3M/T+1) − rate(overnight/T+0) from "
                "jsda_tokyo_repo_rates; CS rank mom L-S risk-adjusted by curve regime"
            ),
            position_rule="sticky fixed_horizon balanced L/S after curve-shape book transform",
            datasets_used=bars_idx + ("jsda_tokyo_repo_rates",),
            family_id=FAMILY_RATE_FACTOR,
            base_params={
                "mode": "rate_curve_shape_xs",
                "momentum_n": 5,
                "hold_days": 10,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "steep_threshold": 0.0,
                "invert_threshold": 0.0,
                "curve_short_tenor": "overnight/翌日物/T+0",
                "curve_long_tenor": "3M/T+1",
            },
            structural_keys=("mode", "curve_short_tenor", "curve_long_tenor"),
            notes=(
                "Curve definition uses only observed JSDA repo tenors "
                "(no JGB/OIS invent). Funding term-structure proxy, not sovereign curve."
            ),
        ),
    ]


def _build_logic_templates() -> dict[str, LogicTemplate]:
    """Catalog of distinct economic logics (prefer many templates, few clones)."""
    missing_overlay = set(BAR_NATIVE_SPECS) - set(_BAR_NATIVE_TEMPLATE_OVERLAY)
    if missing_overlay:
        raise RuntimeError(
            f"BAR_NATIVE overlay missing for {sorted(missing_overlay)}"
        )
    extra_overlay = set(_BAR_NATIVE_TEMPLATE_OVERLAY) - set(BAR_NATIVE_SPECS)
    if extra_overlay:
        raise RuntimeError(
            f"overlay ids not in BAR_NATIVE_SPECS: {sorted(extra_overlay)}"
        )
    factory_only = {t.logic_id: t for t in _factory_only_templates()}
    missing_fo = set(FACTORY_ONLY_LOGIC_IDS) - set(factory_only)
    if missing_fo:
        raise RuntimeError(f"factory-only templates missing {sorted(missing_fo)}")
    out: dict[str, LogicTemplate] = {}
    for lid in _LOGIC_TEMPLATE_ORDER:
        if lid in BAR_NATIVE_SPECS:
            out[lid] = logic_template_from_bar_native(
                BAR_NATIVE_SPECS[lid],
                **_BAR_NATIVE_TEMPLATE_OVERLAY[lid],
            )
        elif lid in factory_only:
            out[lid] = factory_only[lid]
        else:
            raise RuntimeError(f"unknown logic template id: {lid}")
    missing_bn = set(BAR_NATIVE_SPECS) - set(out)
    if missing_bn:
        raise RuntimeError(f"BAR_NATIVE_SPECS not in catalog: {sorted(missing_bn)}")
    missing_fo_cat = set(factory_only) - set(out)
    if missing_fo_cat:
        raise RuntimeError(
            f"factory-only ids not in catalog: {sorted(missing_fo_cat)}"
        )
    return out


LOGIC_TEMPLATES: dict[str, LogicTemplate] = _build_logic_templates()
LOGIC_TEMPLATE_IDS: tuple[str, ...] = tuple(LOGIC_TEMPLATES.keys())


@dataclass(frozen=True)
class FamilyDefinition:
    """Legacy family document (W87 API); diversity now lives on LogicTemplate."""

    family_id: str
    display_name: str
    description: str
    datasets_required: tuple[str, ...]
    param_axes: tuple[str, ...]
    generation_enabled: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "display_name": self.display_name,
            "description": self.description,
            "datasets_required": list(self.datasets_required),
            "param_axes": list(self.param_axes),
            "generation_enabled": self.generation_enabled,
            "notes": self.notes,
        }


def _derive_family_definitions() -> dict[str, FamilyDefinition]:
    by_fam: dict[str, list[LogicTemplate]] = {}
    for t in LOGIC_TEMPLATES.values():
        by_fam.setdefault(t.family_id, []).append(t)
    out: dict[str, FamilyDefinition] = {}
    for fid, tpls in by_fam.items():
        ds: list[str] = []
        for t in tpls:
            for d in t.datasets_used:
                if d not in ds:
                    ds.append(d)
        axes = sorted(
            {
                k
                for t in tpls
                for k in (list(t.structural_keys) + list(t.base_params.keys()))
                if k not in NUMERIC_ONLY_KNOBS or k in t.structural_keys
            }
        )
        gen_on = any(bool(t.generation_enabled) for t in tpls)
        notes = "Family is eval dispatch; logic templates define diversity."
        out[fid] = FamilyDefinition(
            family_id=fid,
            display_name=fid,
            description=(
                f"Eval family covering logic_ids: "
                f"{', '.join(t.logic_id for t in tpls)}."
            ),
            datasets_required=tuple(ds),
            param_axes=tuple(axes) if axes else ("logic_id",),
            generation_enabled=gen_on,
            notes=notes,
        )
    # Unique families stay as recognition-only eval dispatch (no factory templates).
    research_notes = "Recognition only; generation_enabled=False; not a pass."
    for fid in RESEARCH_UNIQUE_FAMILY_IDS:
        if fid in out:
            continue
        out[fid] = FamilyDefinition(
            family_id=fid,
            display_name=fid,
            description="unique_logic recognition family (not factory-template diversity).",
            datasets_required=(),
            param_axes=("logic_id",),
            generation_enabled=False,
            notes=research_notes,
        )
    return out


FAMILY_DEFINITIONS: dict[str, FamilyDefinition] = _derive_family_definitions()
FACTORY_FAMILY_IDS: tuple[str, ...] = tuple(FAMILY_DEFINITIONS.keys())

# Soft ratios for optional numeric fill only (not primary diversity)
DEFAULT_FAMILY_RATIOS: dict[str, float] = {
    fid: 1.0 / max(1, len(FACTORY_FAMILY_IDS)) for fid in FACTORY_FAMILY_IDS
}


def _factory_doc_meta() -> tuple[str, str]:
    from research.offline.factory import MASS_FACTORY_VERSION, MASS_FACTORY_WAVE

    return MASS_FACTORY_VERSION, MASS_FACTORY_WAVE


def near_logic_groups_document() -> dict[str, Any]:
    """Near-groups kept parallel for comparison (do not merge early)."""
    version, wave = _factory_doc_meta()
    return {
        "version": version,
        "wave": wave,
        "policy": "Near-similar logics stay parallel; do not merge early.",
        "groups": [dict(g) for g in NEAR_LOGIC_GROUPS],
    }


def _research_family_base() -> dict[str, Any]:
    version, wave = _factory_doc_meta()
    return {
        "wave": wave,
        "version": version,
        "registration": "recognition",
        "registration_is_not_a_pass": RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS,
        "registration_is_not_promotion": True,
        "auto_research_candidate": RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE,
        "generation_enabled": False,
        "promote_as_main": False,
        "go": False,
        "mass_research": MASS_RESEARCH,
        "ready_declared": READY_DECLARED,
        "connected_to_mass": CONNECTED_TO_MASS,
        "connected_to_ready": CONNECTED_TO_READY,
        "family_group": FAMILY_RESEARCH_UNIQUE_LOGIC,
    }


def research_family_register_document() -> dict[str, Any]:
    """Research-family registration (recognition, not promotion)."""
    return {
        **_research_family_base(),
        "register_id": RESEARCH_FAMILY_REGISTER_ID,
        "kind": "research_family",
        "family_ids": sorted(RESEARCH_UNIQUE_FAMILY_IDS),
        "logic_ids": sorted(RESEARCH_UNIQUE_LOGIC_IDS),
    }


def research_family_append_document() -> dict[str, Any]:
    """Family append of this-wave newly min-implemented logics only."""
    return {
        **_research_family_base(),
        "append_id": RESEARCH_FAMILY_APPEND_ID,
        "register_id": RESEARCH_FAMILY_REGISTER_ID,
        "kind": "research_family_append",
        "this_wave_only": True,
        "appended_logic_ids": sorted(RESEARCH_FAMILY_APPEND_LOGIC_IDS),
        "did_not_kill_funding_surprise": True,
    }


def logic_templates_document() -> dict[str, Any]:
    """Document logic templates + diversity rules."""
    from research.offline.factory import DEFAULT_NEAR_DUP_THRESHOLD

    version, wave = _factory_doc_meta()
    nky_vol_ids = [
        lid
        for lid, t in LOGIC_TEMPLATES.items()
        if t.family_id == FAMILY_INDEX_VOL_REGIME
    ]
    opt225_ids = [
        lid
        for lid, t in LOGIC_TEMPLATES.items()
        if t.family_id == FAMILY_OPTIONS_VOL_REGIME
    ]
    return {
        "version": version,
        "wave": wave,
        "n_logic_templates": len(LOGIC_TEMPLATES),
        "logic_ids": list(LOGIC_TEMPLATE_IDS),
        "w91_index_vol_logic_ids": nky_vol_ids,
        "w92_options_vol_logic_ids": opt225_ids,
        "w94_options_vol_logic_ids": [
            lid
            for lid in opt225_ids
            if lid
            in {
                "opt225_skew_abs_level",
                "opt225_cm_term_abs_level",
                "opt225_basevol_delta_abs",
            }
        ],
        "unique_logic_ids": sorted(RESEARCH_UNIQUE_LOGIC_IDS),
        "unique_logic_append_logic_ids": sorted(RESEARCH_FAMILY_APPEND_LOGIC_IDS),
        "opt225_canonical_level": "basevol",
        "opt225_atm_iv_role": "compare_only",
        "diversity_rules": {
            "counts_as_different": [
                "info source / datasets",
                "entry / signal logic",
                "position construction",
                "economic thesis",
            ],
            "does_not_count": [
                "hold_days only",
                "momentum_window only",
                "long_frac/short_frac only (e.g. 0.3→0.4)",
                "sign flip as separate strategy (sign is eval aspect)",
            ],
            "near_dup_threshold": DEFAULT_NEAR_DUP_THRESHOLD,
            "numeric_only_knobs": sorted(NUMERIC_ONLY_KNOBS),
        },
    }


def family_definitions_document() -> dict[str, Any]:
    """Back-compat family document; points primary diversity to logic templates."""
    version, wave = _factory_doc_meta()
    return {
        "version": version,
        "wave": wave,
        "families": {
            fid: FAMILY_DEFINITIONS[fid].to_dict() for fid in FACTORY_FAMILY_IDS
        },
        "family_ids": list(FACTORY_FAMILY_IDS),
        "default_family_ratios": dict(DEFAULT_FAMILY_RATIOS),
    }


if set(BAR_NATIVE_LOGIC_IDS) - set(LOGIC_TEMPLATE_IDS):
    raise RuntimeError(
        "BAR_NATIVE_LOGIC_IDS must be a subset of LOGIC_TEMPLATE_IDS, missing "
        f"{sorted(set(BAR_NATIVE_LOGIC_IDS) - set(LOGIC_TEMPLATE_IDS))}"
    )
if set(FACTORY_ONLY_LOGIC_IDS) & set(BAR_NATIVE_SPECS):
    raise RuntimeError("factory-only ids must not be in BAR_NATIVE_SPECS")
