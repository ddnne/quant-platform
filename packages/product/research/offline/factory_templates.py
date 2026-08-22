"""Factory logic-template catalog. BAR_NATIVE_SPECS SoT for 30; six factory-only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Mapping

from research.bar_native_specs import BAR_NATIVE_LOGIC_IDS, BAR_NATIVE_SPECS
from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_MULTI_DAY_HOLD,
)

FAMILY_VOL_RISK_ADJUSTED: str = "vol_risk_adjusted"
FAMILY_RATE_FACTOR: str = "rate_factor"
FAMILY_MULTI_FACTOR: str = "multi_factor"
FAMILY_INDEX_VOL_REGIME: str = "index_vol_regime"
FAMILY_OPTIONS_VOL_REGIME: str = "options_vol_regime"
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
RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS: bool = True
RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE: bool = False

NEAR_LOGIC_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "group_id": "flow_margin_confirm",
        "logic_ids": (
            "flow_margin_pressure",
            "flow_margin_short_hard",
            "flow_margin_short_soft",
            "mf_flow_price",
        ),
    },
    {
        "group_id": "fund_value_mom",
        "logic_ids": (
            "fund_value_mom_agree",
            "fund_value_mom_agree_slow",
            "mf_value_mom_rate",
        ),
    },
    {
        "group_id": "rate_macro_family",
        "logic_ids": (
            "macro_repo_rate_change",
            "macro_repo_rate_level",
            "rate_abs_level_xs",
            "rate_curve_shape_xs",
        ),
    },
    {
        "group_id": "vol_family_name_vs_index",
        "logic_ids": (
            "vol_risk_adjusted_mom",
            "vol_breakout_expand",
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ),
    },
    {
        "group_id": "index_vol_regime_family",
        "logic_ids": (
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ),
    },
    {
        "group_id": "options_vol_regime_family",
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
    },
    {
        "group_id": "nky_vol_proxy_vs_options_sot",
        "logic_ids": (
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
            "opt225_basevol_abs_level",
            "opt225_skew_abs_level",
            "opt225_atm_iv_abs_level",
        ),
    },
    {
        "group_id": "unique_logic_research_family",
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
    },
    {
        "group_id": "unique_logic_ls_append",
        "logic_ids": (
            "funding_impulse_cs_tilt",
            "curve_steepen_impulse_cs",
            "xs_margin_delta_rank",
            "idio_mom_macro_impulse",
            "event_funding_easy_short",
            "event_funding_stress_ls",
            "surprise_xs_rank_flip",
        ),
    },
    {
        "group_id": "unique_logic_overlay_append",
        "logic_ids": (
            "overnight_level_cs_tilt",
            "overnight_easy_cs_follow",
            "month_end_cs_fade",
            "xs_low_vol_mom",
            "repo_3m_level_cs",
            "event_funding_adaptive_side",
            "surprise_xs_rank_adaptive",
        ),
    },
)

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
    """One distinct economic logic (counts toward unique_logic)."""

    logic_id: str
    thesis: str
    signal_definition: str
    position_rule: str
    datasets_used: tuple[str, ...]
    family_id: str
    base_params: Mapping[str, Any]
    structural_keys: tuple[str, ...] = ()
    # Fail-closed. Bar-native / factory-only templates set True explicitly.
    # Unique/combo YAML stays generation_enabled False and is not in LOGIC_TEMPLATES.
    generation_enabled: bool = False

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
            "thesis": self.thesis,
            "signal_definition": self.signal_definition,
            "position_rule": self.position_rule,
            "datasets_used": list(self.datasets_used),
            "family_id": self.family_id,
            "base_params": dict(self.base_params),
            "structural_keys": list(self.structural_keys),
            "logic_fingerprint": self.logic_fingerprint(),
            "generation_enabled": self.generation_enabled,
        }


def logic_template_from_bar_native(spec: Mapping[str, Any]) -> LogicTemplate:
    """LogicTemplate from a BAR_NATIVE_SPECS row."""
    return LogicTemplate(
        logic_id=str(spec["logic_id"]),
        thesis=str(spec["thesis"]),
        signal_definition=str(spec["signal_definition"]),
        position_rule=str(spec["position_rule"]),
        datasets_used=tuple(spec["datasets_used"]),
        family_id=str(spec["family_id"]),
        base_params=dict(spec["params"]),
        structural_keys=tuple(spec.get("structural_keys") or ()),
        generation_enabled=True,
    )


def _factory_only_templates() -> list[LogicTemplate]:
    """Offline-only templates (not in the CF bar-native set of 30)."""
    bars = ("equities_bars_daily", "markets_calendar")
    bars_idx = bars + ("indices_bars_daily_topix",)
    rows = [
        LogicTemplate(
            logic_id="event_post_disclosure_hold",
            thesis="Post-disclosure PIT close drift",
            signal_definition="earnings surprise proxy; entry only when DiscTime pre-close",
            position_rule="fixed post_hold after first non-look-ahead session close",
            datasets_used=("fins_summary",) + bars,
            family_id=CLASS_EVENT_POST,
            base_params={
                "post_hold_days": 5,
                "entry_mode": "same_day_close_if_pre_close",
            },
            structural_keys=("entry_mode",),
        ),
        LogicTemplate(
            logic_id="xs_rank_mom_slow",
            thesis="Slow CS rank mom sticky L/S",
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
        ),
        LogicTemplate(
            logic_id="mdh_short_horizon_mom",
            thesis="Short 5d multi-day continuation",
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
        ),
        LogicTemplate(
            logic_id="event_post_long_horizon",
            thesis="Long 20d post-disclosure drift",
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
            thesis="Abs Tokyo repo as CS risk factor",
            signal_definition="CS rank(mom) L-S risk-adjusted by abs repo rate_level",
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
        ),
        LogicTemplate(
            logic_id="rate_curve_shape_xs",
            thesis="Repo curve steepness as CS factor",
            signal_definition="CS rank mom L-S risk-adjusted by 3M−ON repo curve",
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
        ),
    ]
    return [replace(t, generation_enabled=True) for t in rows]


def _build_logic_templates() -> dict[str, LogicTemplate]:
    """Catalog of distinct economic logics."""
    factory_only = {t.logic_id: t for t in _factory_only_templates()}
    missing_fo = set(FACTORY_ONLY_LOGIC_IDS) - set(factory_only)
    if missing_fo:
        raise RuntimeError(f"factory-only templates missing {sorted(missing_fo)}")
    out: dict[str, LogicTemplate] = {}
    for lid in _LOGIC_TEMPLATE_ORDER:
        if lid in BAR_NATIVE_SPECS:
            out[lid] = logic_template_from_bar_native(BAR_NATIVE_SPECS[lid])
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
    """Eval-dispatch family covering one or more logic templates."""

    family_id: str
    datasets_required: tuple[str, ...]
    generation_enabled: bool = False


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
        out[fid] = FamilyDefinition(
            family_id=fid,
            datasets_required=tuple(ds),
            generation_enabled=any(bool(t.generation_enabled) for t in tpls),
        )
    for fid in RESEARCH_UNIQUE_FAMILY_IDS:
        if fid in out:
            continue
        out[fid] = FamilyDefinition(
            family_id=fid,
            datasets_required=(),
            generation_enabled=False,
        )
    return out


FAMILY_DEFINITIONS: dict[str, FamilyDefinition] = _derive_family_definitions()
FACTORY_FAMILY_IDS: tuple[str, ...] = tuple(FAMILY_DEFINITIONS.keys())


if set(BAR_NATIVE_LOGIC_IDS) - set(LOGIC_TEMPLATE_IDS):
    raise RuntimeError(
        "BAR_NATIVE_LOGIC_IDS must be a subset of LOGIC_TEMPLATE_IDS, missing "
        f"{sorted(set(BAR_NATIVE_LOGIC_IDS) - set(LOGIC_TEMPLATE_IDS))}"
    )
if set(FACTORY_ONLY_LOGIC_IDS) & set(BAR_NATIVE_SPECS):
    raise RuntimeError("factory-only ids must not be in BAR_NATIVE_SPECS")
