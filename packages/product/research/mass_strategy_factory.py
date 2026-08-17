"""Mass strategy logic-diversity factory + batch auto-experiment (W91 / w0818a).

Purpose
-------
Research factory that generates strategy **individuals** around **distinct
economic logic templates** (thesis + signal structure + position rule +
datasets), not hold_days / momentum_window / long_frac param grids.

W91 extends W90 with:
* Nikkei/index realized-vol regime logics (abs level · term levels · ratio)
* CF real multi-year panels (mode=r2_panels; synthetic not final success)

W90 held:
* strong-model profit-hypothesis generation (xAI grok-4.6 preferred)
* CF multi-logic × multi-period mass-eval Worker + R2 artifacts
* wide local eval of LLM-accepted + catalog survivors

W89 held:
* interest-rate factor logics (absolute level + curve-shape × CS)
* multi-factor logics (value×mom×rate, flow×price) with required theses
* near-group labels (flow hard/soft, fund slow kept parallel)
* programmatic profit-hypothesis entry (always through evaluator)

W87 risk addressed
------------------
N=100 "diversity" that was mostly family × multi-axis param slots
(hold / mom / frac) is rejected. Diversity now requires difference in:

* information source
* entry / signal logic
* position construction
* economic thesis

Does **not** count as distinct: hold_days-only, momentum window-only,
frac 0.3→0.4-only, or sign flip as a separate strategy (sign is eval aspect).

This is a **research factory**, not operational Mass / READY / live:

* Does **not** call ``agents.mass_research`` / arm Mass loop
* Does **not** mint READY / VerifiedResearchReadiness / operational GO
* Does **not** un-reject S1–S5 or use ``simple_daily_sign`` as diversity
* Does **not** retune the three frozen default-path representatives
* continuous paper remains **UNARMED**

Building blocks reused
----------------------
* ``hypothesis_classes`` — family ids / datasets
* ``class_signals`` / ``class_hyp_eval`` — pure bar evaluators
* ``cost_models`` · ``sign_selection`` · ``stats_metrics``
* ``llm_hyp_generator`` · ``cf_mass_eval_job`` (W90)

See: ``docs/proof/w0816y_w90_llm_hyp_cf_mass_eval_20260817.md``
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Mapping, Sequence

from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIMPLE_DAILY_SIGN,
    DEFAULT_GENERATION_CLASS_IDS,
    HYPOTHESIS_CLASS_REGISTRY,
    MASS_RESEARCH as HC_MASS,
    PHASE7 as HC_PHASE7,
    READY_DECLARED as HC_READY,
)
from research.cost_models import DEFAULT_ONE_WAY_COST
from research.sign_selection import (
    SIGN_INVERTED,
    SIGN_ORIGINAL,
    evaluate_sign_both_sides,
    choose_sign,
)
from research.stats_metrics import (
    period_stats_report,
    sample_mean,
    t_stat_vs_zero,
)
from features.class_signals import (
    DEFAULT_HOLD_DAYS,
    amortized_one_way_cost,
    apply_sticky_hold,
    multi_day_forward_return,
    sign_from_numeric,
)

# ---------------------------------------------------------------------------
# Identity / freezes (must never arm operational Mass)
# ---------------------------------------------------------------------------

MASS_FACTORY_VERSION: str = "mass-strategy-factory/v2.3"
MASS_FACTORY_WAVE: str = "W91 / w0818a"

MASS_RESEARCH: str = "NO-GO"  # operational Mass remains NO-GO
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False
CONNECTED_TO_READY: bool = False
CONNECTED_TO_MASS: bool = False
EDGE_CLAIMED: bool = False
SIGNIFICANCE_CLAIMED: bool = False
S1_S5_UNREJECT: bool = False
SIMPLE_DAILY_SIGN_AS_DIVERSITY: bool = False
CONTINUOUS_PAPER: str = "UNARMED"
LIVE_ORDERS: bool = False

# Factory "mass" here means bulk research generation — never operational Mass.
FACTORY_MASS_LOOP: str = "research_batch_only"

# Optional families not in hypothesis_classes registry.
FAMILY_VOL_RISK_ADJUSTED: str = "vol_risk_adjusted"
FAMILY_RATE_FACTOR: str = "rate_factor"
FAMILY_MULTI_FACTOR: str = "multi_factor"
FAMILY_INDEX_VOL_REGIME: str = "index_vol_regime"

# Near-groups kept parallel for comparison (do not merge early).
NEAR_LOGIC_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "group_id": "flow_margin_confirm",
        "label": "flow hard/soft/pressure (near-group parallel)",
        "logic_ids": (
            "flow_margin_pressure",
            "flow_margin_short_hard",
            "flow_margin_short_soft",
            "mf_flow_price",  # multi-factor cousin; price confirm vs short
        ),
        "note": (
            "Keep hard/soft/pressure parallel; mf_flow_price is multi-factor "
            "price-confirm cousin (not a short-confirm variant merge)."
        ),
    },
    {
        "group_id": "fund_value_mom",
        "label": "fund value×mom (slow variant parallel)",
        "logic_ids": (
            "fund_value_mom_agree",
            "fund_value_mom_agree_slow",
            "mf_value_mom_rate",  # multi-factor cousin; adds rate leg
        ),
        "note": (
            "Keep slow variant parallel; mf_value_mom_rate adds rate factor "
            "(not a near-dup of fund_value_mom_agree)."
        ),
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
        "note": (
            "macro_* = mom gate; rate_* = CS risk-adj factor logics. "
            "Keep distinct (not merge)."
        ),
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
        "note": (
            "vol_risk_adjusted_mom / vol_breakout_expand = per-name vol gate. "
            "nky_vol_* = index-level Nikkei/TOPIX RV regime × CS book. "
            "Keep parallel; do not merge name-level with index-level."
        ),
    },
    {
        "group_id": "index_vol_regime_family",
        "label": "index vol regime (abs vs term levels vs ratio)",
        "logic_ids": (
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ),
        "note": (
            "Three transforms of the same Nikkei/TOPIX RV series. "
            "Keep abs / dual-levels / ratio parallel for comparison."
        ),
    },
)

# Gen-time reject reason codes
REJECT_SIMPLE_DAILY_SIGN: str = "simple_daily_sign_forbidden"
REJECT_LOOKAHEAD: str = "pit_lookahead_forbidden"
REJECT_MISSING_DATASETS: str = "required_datasets_unavailable"
REJECT_INVALID_PARAMS: str = "invalid_params"
REJECT_S1_S5: str = "s1_s5_unreject_forbidden"
REJECT_UNKNOWN_FAMILY: str = "unknown_family"
REJECT_UNKNOWN_LOGIC: str = "unknown_logic_template"
REJECT_NEAR_DUPLICATE: str = "near_duplicate_grid_mutation"
REJECT_FROZEN_DEFAULT_RETUNE: str = "frozen_default_retune_forbidden"

# Eval / screen reason codes
SCREEN_NEAR_ZERO: str = "near_zero_after_cost"
SCREEN_POST_COST_COLLAPSE: str = "post_cost_collapse"
SCREEN_DATA_MISSING: str = "data_missing"
SCREEN_PIT_VIOLATION: str = "pit_violation"
SCREEN_EVAL_ERROR: str = "eval_error"
SCREEN_NO_PERIODS: str = "no_ok_periods"
SCREEN_LOW_ACTIVATION: str = "low_activation"
SCREEN_BOTH_SIGNS_FAIL: str = "both_signs_near_zero_or_nonpositive"

DEFAULT_SEED: int = 870816
DEFAULT_N: int = 100  # capacity; uniqueness measured by unique_logic / after_dedup
DEFAULT_NEAR_ZERO_ABS: float = 0.0005  # 5bp
DEFAULT_MIN_ACTIVATION: float = 0.01
DEFAULT_MAX_FAMILY_SHARE: float = 0.35  # soft; logic diversity is primary anti-bias
DEFAULT_ONE_WAY: float = DEFAULT_ONE_WAY_COST
DEFAULT_NEAR_DUP_THRESHOLD: float = 0.85  # drop when similarity >= this

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

# ---------------------------------------------------------------------------
# Frozen default-path representatives (W83–W86) — DO NOT retune here
# ---------------------------------------------------------------------------

FROZEN_DEFAULT_PATH: tuple[dict[str, Any], ...] = (
    {
        "representative_id": "cross_section_hold_10",
        "family_id": CLASS_CROSS_SECTION_RELATIVE,
        "hold_days": 10,
        "momentum_n": 5,
        "long_frac": 0.3,
        "short_frac": 0.3,
        "stance": "KEEP",
        "note": "W83–W86 default path; factory must not retune",
    },
    {
        "representative_id": "cross_section_hold_10_mom3",
        "family_id": CLASS_CROSS_SECTION_RELATIVE,
        "hold_days": 10,
        "momentum_n": 3,
        "long_frac": 0.3,
        "short_frac": 0.3,
        "stance": "PROMOTE",
        "note": "W85 promote; factory must not retune",
    },
    {
        "representative_id": "fundamentals_hold_10",
        "family_id": CLASS_FUNDAMENTALS_PRICE,
        "hold_days": 10,
        "momentum_n": 10,
        "mode": "value_momentum_agree",
        "stance": "KEEP",
        "note": "W83–W86 default path; factory must not retune",
    },
)

# Datasets the factory can satisfy offline (local mirrors + sqlite).
FACTORY_AVAILABLE_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily",
        "markets_calendar",
        "indices_bars_daily_topix",
        "indices_bars_daily",
        "derivatives_bars_daily_futures",
        "jsda_tokyo_repo_rates",
        "fins_summary",
        "fins_details",
        "fins_dividend",
        "fins_earnings_date",
        "markets_margin_interest",
        "markets_short_ratio",
        "markets_short_sale_report",
        "equities_investor_types",
        "markets_breakdown",
    }
)

# Event entry modes
_EVENT_ENTRY_SAFE: tuple[str, ...] = ("same_day_close_if_pre_close",)
_EVENT_ENTRY_FORBIDDEN: frozenset[str] = frozenset(
    {
        "same_day_close_always",
        "pre_disclosure_close",
        "look_ahead_close",
        "event_open_before_disc",
    }
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "edge_claimed": EDGE_CLAIMED,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "s1_s5_unreject": S1_S5_UNREJECT,
        "simple_daily_sign_as_diversity": SIMPLE_DAILY_SIGN_AS_DIVERSITY,
        "continuous_paper": CONTINUOUS_PAPER,
        "live_orders": LIVE_ORDERS,
        "factory_mass_loop": FACTORY_MASS_LOOP,
        "hypothesis_classes_mass": HC_MASS,
        "hypothesis_classes_phase7": HC_PHASE7,
        "hypothesis_classes_ready": HC_READY,
        "frozen_default_path": [
            r["representative_id"] for r in FROZEN_DEFAULT_PATH
        ],
        "frozen_defaults_retuned": False,
    }


# ---------------------------------------------------------------------------
# Logic templates (economic logic, not param grids)
# ---------------------------------------------------------------------------


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
        }


def _build_logic_templates() -> dict[str, LogicTemplate]:
    """Catalog of distinct economic logics (prefer many templates, few clones)."""
    bars = ("equities_bars_daily", "markets_calendar")
    bars_idx = bars + ("indices_bars_daily_topix",)
    tpls: list[LogicTemplate] = [
        LogicTemplate(
            logic_id="mdh_sticky_momentum",
            display_name="Sticky multi-day momentum",
            thesis="Short-horizon winners continue over multi-day sticky holds",
            signal_definition="sign(momentum_n) with n=hold; no daily flip",
            position_rule="fixed_horizon sticky hold; equal-weight active longs/shorts",
            datasets_used=bars_idx,
            family_id=CLASS_MULTI_DAY_HOLD,
            base_params={
                "hold_days": 10,
                "momentum_n": 10,
                "rebalance_mode": "fixed_horizon",
                "signal_polarity": 1,
            },
            structural_keys=("rebalance_mode", "signal_polarity"),
        ),
        LogicTemplate(
            logic_id="mdh_mean_reversion",
            display_name="Sticky multi-day mean reversion",
            thesis="Short-horizon moves reverse over multi-day holds (opposite entry)",
            signal_definition="−sign(momentum_n); reversion entry (not eval-time sign flip)",
            position_rule="fixed_horizon sticky hold of reversion signs",
            datasets_used=bars_idx,
            family_id=CLASS_MULTI_DAY_HOLD,
            base_params={
                "hold_days": 10,
                "momentum_n": 10,
                "rebalance_mode": "fixed_horizon",
                "signal_polarity": -1,
            },
            structural_keys=("rebalance_mode", "signal_polarity"),
            notes="Distinct entry logic vs mdh_sticky_momentum; not an eval sign flip.",
        ),
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
            logic_id="xs_rank_ls_sticky",
            display_name="Cross-section rank L-S sticky",
            thesis="Relative strength: long top rank mom, short bottom, multi-day sticky",
            signal_definition="same-day cross-section momentum ranks → L/S signs",
            position_rule="sticky fixed_horizon hold of daily rank signs; balanced L/S book",
            datasets_used=bars_idx,
            family_id=CLASS_CROSS_SECTION_RELATIVE,
            base_params={
                "hold_days": 10,
                "momentum_n": 5,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "book_mode": "balanced_ls",
            },
            structural_keys=("book_mode",),
            notes="Canonical structure matches frozen cross_section_hold_10 (mom5) shape; not a retune.",
        ),
        LogicTemplate(
            logic_id="xs_rank_ls_daily",
            display_name="Cross-section rank L-S daily rebalance",
            thesis="Relative strength harvested via daily rebalance (higher turnover)",
            signal_definition="same-day rank L/S on momentum",
            position_rule="hold_days=1 daily rebalance; balanced L/S",
            datasets_used=bars_idx,
            family_id=CLASS_CROSS_SECTION_RELATIVE,
            base_params={
                "hold_days": 1,
                "momentum_n": 5,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "book_mode": "balanced_ls_daily",
            },
            structural_keys=("book_mode",),
            notes="Position construction differs from sticky (daily vs multi-day).",
        ),
        LogicTemplate(
            logic_id="macro_repo_rate_change",
            display_name="Macro-conditioned mom (repo rate change)",
            thesis="Equity mom works differently under repo tightening vs easing",
            signal_definition="momentum gated/conditioned by Tokyo repo rate_change regime",
            position_rule="sticky multi-day hold under regime filter",
            datasets_used=bars_idx + ("jsda_tokyo_repo_rates",),
            family_id=CLASS_MACRO_CONDITIONED,
            base_params={
                "mode": "rate_change",
                "momentum_n": 10,
                "hold_days": 10,
                "high_threshold": 0.05,
                "low_threshold": 0.0,
            },
            structural_keys=("mode",),
        ),
        LogicTemplate(
            logic_id="macro_repo_rate_level",
            display_name="Macro-conditioned mom (repo rate level)",
            thesis="Equity mom differs in high vs low absolute funding-rate regimes",
            signal_definition="momentum conditioned on Tokyo repo rate_level regime",
            position_rule="sticky multi-day hold under level regime filter",
            datasets_used=bars_idx + ("jsda_tokyo_repo_rates",),
            family_id=CLASS_MACRO_CONDITIONED,
            base_params={
                "mode": "rate_level",
                "momentum_n": 10,
                "hold_days": 10,
                "high_threshold": 0.05,
                "low_threshold": 0.0,
            },
            structural_keys=("mode",),
        ),
        LogicTemplate(
            logic_id="fund_value_only",
            display_name="Fundamentals value-only",
            thesis="Cheap (PIT value) names earn a multi-day premium vs expensive",
            signal_definition="PIT fundamental_value_score sign only (no mom confirm)",
            position_rule="sticky fixed_horizon hold of value signs",
            datasets_used=("fins_summary",) + bars,
            family_id=CLASS_FUNDAMENTALS_PRICE,
            base_params={
                "hold_days": 10,
                "momentum_n": 10,
                "mode": "value_only",
            },
            structural_keys=("mode",),
        ),
        LogicTemplate(
            logic_id="fund_value_mom_agree",
            display_name="Fundamentals value × momentum agree",
            thesis="Value and price momentum agreement improves multi-day edge",
            signal_definition="enter only when value score and mom agree in sign",
            position_rule="sticky fixed_horizon hold of agree-filtered signs",
            datasets_used=("fins_summary",) + bars,
            family_id=CLASS_FUNDAMENTALS_PRICE,
            base_params={
                "hold_days": 10,
                "momentum_n": 10,
                "mode": "value_momentum_agree",
            },
            structural_keys=("mode",),
            notes="Canonical shape matches frozen fundamentals_hold_10; not a retune.",
        ),
        LogicTemplate(
            logic_id="flow_margin_pressure",
            display_name="Margin flow multi-day pressure",
            thesis="Rising margin interest proxies demand that persists multi-day",
            signal_definition="multi-day margin flow pressure (not S4 daily)",
            position_rule="min_hold sticky; no short-sale confirm",
            datasets_used=("markets_margin_interest",) + bars,
            family_id=CLASS_FLOW_DEMAND,
            base_params={
                "hold_days": 10,
                "short_confirm_mode": "off",
                "require_short_confirm": False,
            },
            structural_keys=("short_confirm_mode",),
        ),
        LogicTemplate(
            logic_id="flow_margin_short_hard",
            display_name="Margin flow + hard short confirm",
            thesis="Margin demand only when short-interest confirms directional pressure",
            signal_definition="margin flow AND hard short-ratio confirm filter",
            position_rule="min_hold sticky; hard short confirm required",
            datasets_used=(
                "markets_margin_interest",
                "markets_short_ratio",
            )
            + bars,
            family_id=CLASS_FLOW_DEMAND,
            base_params={
                "hold_days": 10,
                "short_confirm_mode": "hard",
                "require_short_confirm": True,
            },
            structural_keys=("short_confirm_mode",),
        ),
        LogicTemplate(
            logic_id="flow_margin_short_soft",
            display_name="Margin flow + soft short confirm",
            thesis="Margin demand with soft short-interest tilt (not hard veto)",
            signal_definition="margin flow with soft short-ratio modulation",
            position_rule="min_hold sticky; soft short confirm",
            datasets_used=(
                "markets_margin_interest",
                "markets_short_ratio",
            )
            + bars,
            family_id=CLASS_FLOW_DEMAND,
            base_params={
                "hold_days": 10,
                "short_confirm_mode": "soft",
                "require_short_confirm": False,
            },
            structural_keys=("short_confirm_mode",),
        ),
        LogicTemplate(
            logic_id="vol_risk_adjusted_mom",
            display_name="Vol-risk gated momentum",
            thesis="Momentum only when conviction |mom|/vol exceeds a risk floor",
            signal_definition="sign(mom) only if |mom|/realized_vol ≥ threshold else flat",
            position_rule="fixed_horizon sticky hold of risk-gated signs",
            datasets_used=bars,
            family_id=FAMILY_VOL_RISK_ADJUSTED,
            base_params={
                "hold_days": 10,
                "momentum_n": 10,
                "vol_n": 10,
                "vol_threshold": 1.0,
                "gate_mode": "mom_over_vol",
            },
            structural_keys=("gate_mode",),
            notes="Research-only family; not in hypothesis_classes registry.",
        ),
        LogicTemplate(
            logic_id="vol_breakout_expand",
            display_name="Vol-expansion breakout mom",
            thesis="Trend entries only when realized vol is expanding (breakout regime)",
            signal_definition="sign(mom) only if recent_vol / prior_vol ≥ expand_ratio",
            position_rule="fixed_horizon sticky hold of expansion-gated signs",
            datasets_used=bars,
            family_id=FAMILY_VOL_RISK_ADJUSTED,
            base_params={
                "hold_days": 10,
                "momentum_n": 10,
                "vol_n": 10,
                "vol_threshold": 1.0,  # expand ratio floor
                "gate_mode": "vol_expand",
            },
            structural_keys=("gate_mode",),
            notes="Different gate structure vs mom_over_vol (info used differently).",
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
            notes=(
                "book_mode encodes slow-rank construction (mom=20 pin of the logic). "
                "Not a free mom grid: one template, one structural horizon."
            ),
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
            notes=(
                "horizon_structure is part of thesis (cost amortization / turnover regime), "
                "not a hold_days grid clone of mdh_sticky_momentum."
            ),
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
            logic_id="fund_value_mom_agree_slow",
            display_name="Value×mom agree (slow price confirm)",
            thesis="Value confirmed by slower price mom (20d) is a different agreement filter",
            signal_definition="value × slow mom agree",
            position_rule="sticky hold; slow mom confirm pin",
            datasets_used=("fins_summary",) + bars,
            family_id=CLASS_FUNDAMENTALS_PRICE,
            base_params={
                "hold_days": 10,
                "momentum_n": 20,
                "mode": "value_momentum_agree",
                "mom_structure": "slow_20",
            },
            structural_keys=("mode", "mom_structure"),
            notes="Distinct mom_structure tag; not a free mom grid over fund_value_mom_agree.",
        ),
        # ----- W89 interest-rate factor logics -----
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
        # ----- W89 multi-factor logics -----
        LogicTemplate(
            logic_id="mf_value_mom_rate",
            display_name="Value × mom × rate multi-factor",
            thesis=(
                "Cheap winners under easy/mid funding and expensive losers under "
                "tight/mid funding earn a multi-day premium (three-factor agreement)"
            ),
            signal_definition=(
                "value_mom_agree AND funding alignment "
                "(long only if rate not high; short only if rate not low)"
            ),
            position_rule="sticky fixed_horizon hold of triple-agree signs",
            datasets_used=("fins_summary", "jsda_tokyo_repo_rates") + bars,
            family_id=FAMILY_MULTI_FACTOR,
            base_params={
                "mode": "value_mom_rate",
                "hold_days": 10,
                "momentum_n": 10,
                "high_threshold": 0.05,
                "low_threshold": 0.0,
            },
            structural_keys=("mode",),
            notes=(
                "Not a near-dup of fund_value_mom_agree: adds rate leg as third factor. "
                "Near-group cousin under fund_value_mom for comparison only."
            ),
        ),
        LogicTemplate(
            logic_id="mf_flow_price",
            display_name="Flow × price multi-factor",
            thesis=(
                "Margin demand pressure earns multi-day only when price momentum "
                "confirms the flow direction (flow×price co-movement)"
            ),
            signal_definition="enter only when sign(margin_change)==sign(price_mom)",
            position_rule="min_hold sticky; price confirm (not short-ratio confirm)",
            datasets_used=("markets_margin_interest",) + bars,
            family_id=FAMILY_MULTI_FACTOR,
            base_params={
                "mode": "flow_price",
                "hold_days": 10,
                "momentum_n": 10,
                "confirm": "price_mom",
            },
            structural_keys=("mode", "confirm"),
            notes=(
                "Distinct from flow_margin_short_hard/soft (short confirm). "
                "Keep parallel in flow near-group; do not merge."
            ),
        ),
        # ----- W91 Nikkei / index vol regime logics -----
        LogicTemplate(
            logic_id="nky_vol_abs_level",
            display_name="Nikkei abs vol-level × CS risk-on/off",
            thesis=(
                "Absolute Nikkei (NK225F) / TOPIX realized-vol level is a risk "
                "regime: low index RV → risk-on keep CS relative strength; "
                "high index RV → risk-off reverse CS; mid → flat"
            ),
            signal_definition=(
                "CS rank(mom) L-S risk-adjusted by absolute index RV "
                "(short-window annualized); not per-name |mom|/vol gate"
            ),
            position_rule="sticky fixed_horizon balanced L/S after abs-vol book transform",
            datasets_used=bars_idx
            + ("indices_bars_daily", "derivatives_bars_daily_futures"),
            family_id=FAMILY_INDEX_VOL_REGIME,
            base_params={
                "mode": "nky_vol_abs_level",
                "momentum_n": 5,
                "hold_days": 10,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "vol_short_n": 10,
                "vol_long_n": 60,
                "high_threshold": 0.20,
                "low_threshold": 0.10,
            },
            structural_keys=("mode",),
            notes=(
                "Index-level vol regime. Distinct from vol_risk_adjusted_mom "
                "(per-name mom/vol gate). Proxy: NK225F front RV → TOPIX fallback. "
                "NKVIF exists but abs path uses realized for term consistency."
            ),
        ),
        LogicTemplate(
            logic_id="nky_vol_term_levels",
            display_name="Nikkei short+long vol levels × CS",
            thesis=(
                "Joint short- and long-window index RV levels: both calm → "
                "risk-on CS; both stressed → risk-off reverse; disagreement → flat"
            ),
            signal_definition=(
                "CS rank mom L-S; regime requires short RV and long RV to agree "
                "on high or low absolute levels (not ratio-only)"
            ),
            position_rule="sticky fixed_horizon balanced L/S after dual-level vol transform",
            datasets_used=bars_idx
            + ("indices_bars_daily", "derivatives_bars_daily_futures"),
            family_id=FAMILY_INDEX_VOL_REGIME,
            base_params={
                "mode": "nky_vol_term_levels",
                "momentum_n": 5,
                "hold_days": 10,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "vol_short_n": 10,
                "vol_long_n": 60,
                "high_threshold": 0.20,
                "low_threshold": 0.10,
            },
            structural_keys=("mode", "vol_short_n", "vol_long_n"),
            notes=(
                "Dual absolute levels (not ratio). Distinct from nky_vol_abs_level "
                "and from per-name vol_breakout_expand."
            ),
        ),
        LogicTemplate(
            logic_id="nky_vol_term_ratio",
            display_name="Nikkei short/long vol ratio × CS",
            thesis=(
                "Index RV term structure (short/long): compressing → risk-on keep "
                "CS; expanding → risk-off reverse; mid → no trade"
            ),
            signal_definition=(
                "ratio = RV_short/RV_long on Nikkei proxy; CS L-S risk-adjusted "
                "by expand/compress regime (index-level, not per-name expand)"
            ),
            position_rule="sticky fixed_horizon balanced L/S after vol-term-ratio transform",
            datasets_used=bars_idx
            + ("indices_bars_daily", "derivatives_bars_daily_futures"),
            family_id=FAMILY_INDEX_VOL_REGIME,
            base_params={
                "mode": "nky_vol_term_ratio",
                "momentum_n": 5,
                "hold_days": 10,
                "long_frac": 0.3,
                "short_frac": 0.3,
                "vol_short_n": 10,
                "vol_long_n": 60,
                "expand_ratio": 1.20,
                "compress_ratio": 0.80,
            },
            structural_keys=("mode", "vol_short_n", "vol_long_n"),
            notes=(
                "Index-level term ratio. Name-level cousin is vol_breakout_expand "
                "(per-name recent/prior vol); keep parallel in vol near-group."
            ),
        ),
    ]
    return {t.logic_id: t for t in tpls}


LOGIC_TEMPLATES: dict[str, LogicTemplate] = _build_logic_templates()
LOGIC_TEMPLATE_IDS: tuple[str, ...] = tuple(LOGIC_TEMPLATES.keys())

# Back-compat family definitions (derived from templates; not grid sources)
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
        out[fid] = FamilyDefinition(
            family_id=fid,
            display_name=fid,
            description=(
                f"Eval family covering logic_ids: "
                f"{', '.join(t.logic_id for t in tpls)}. "
                "Diversity is logic-template based (W88), not param grids."
            ),
            datasets_required=tuple(ds),
            param_axes=tuple(axes) if axes else ("logic_id",),
            notes="W88: family is eval dispatch only; logic templates define diversity.",
        )
    return out


FAMILY_DEFINITIONS: dict[str, FamilyDefinition] = _derive_family_definitions()
FACTORY_FAMILY_IDS: tuple[str, ...] = tuple(FAMILY_DEFINITIONS.keys())

# Soft ratios for optional numeric fill only (not primary diversity)
DEFAULT_FAMILY_RATIOS: dict[str, float] = {
    fid: 1.0 / max(1, len(FACTORY_FAMILY_IDS)) for fid in FACTORY_FAMILY_IDS
}


def near_logic_groups_document() -> dict[str, Any]:
    """Near-groups kept parallel for comparison (do not merge early)."""
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "policy": (
            "Near-similar logics (flow hard/soft, fund slow, rate macro cousins) "
            "stay parallel for now — label as near-group; do not merge early."
        ),
        "groups": [dict(g) for g in NEAR_LOGIC_GROUPS],
    }


def logic_templates_document() -> dict[str, Any]:
    """Document logic templates + diversity rules."""
    rate_ids = [
        lid
        for lid, t in LOGIC_TEMPLATES.items()
        if t.family_id in {FAMILY_RATE_FACTOR, CLASS_MACRO_CONDITIONED}
        and ("rate" in lid or "macro_repo" in lid)
    ]
    mf_ids = [
        lid for lid, t in LOGIC_TEMPLATES.items() if t.family_id == FAMILY_MULTI_FACTOR
    ]
    nky_vol_ids = [
        lid
        for lid, t in LOGIC_TEMPLATES.items()
        if t.family_id == FAMILY_INDEX_VOL_REGIME
    ]
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "n_logic_templates": len(LOGIC_TEMPLATES),
        "logic_ids": list(LOGIC_TEMPLATE_IDS),
        "templates": {
            lid: LOGIC_TEMPLATES[lid].to_dict() for lid in LOGIC_TEMPLATE_IDS
        },
        "w89_rate_factor_logic_ids": rate_ids,
        "w89_multi_factor_logic_ids": mf_ids,
        "w91_index_vol_logic_ids": nky_vol_ids,
        "near_logic_groups": near_logic_groups_document(),
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
            "prefer": "many distinct templates over many param clones",
            "near_group_policy": "keep parallel; label; do not merge early",
        },
        "frozen_default_path": list(FROZEN_DEFAULT_PATH),
        "simple_daily_sign": "forbidden as diversity source",
        "s1_s5_unreject": "forbidden",
        "look_ahead": "gen-time reject",
        **_freeze(),
    }


def family_definitions_document() -> dict[str, Any]:
    """Back-compat family document; points primary diversity to logic templates."""
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "families": {
            fid: FAMILY_DEFINITIONS[fid].to_dict() for fid in FACTORY_FAMILY_IDS
        },
        "family_ids": list(FACTORY_FAMILY_IDS),
        "default_family_ratios": dict(DEFAULT_FAMILY_RATIOS),
        "logic_templates": logic_templates_document(),
        "sampling_rules": {
            "seed_reproducible": True,
            "primary_unit": "logic_template",
            "target_n_capacity": DEFAULT_N,
            "anti_bias": (
                "Prefer one individual per distinct logic template. "
                "Numeric knob clones are near-dup scored and dropped. "
                "hold/mom/frac grids do NOT count as diversity."
            ),
            "simple_daily_sign": "forbidden as diversity source",
            "s1_s5_unreject": "forbidden",
            "look_ahead": "gen-time reject",
            "quality_filter_stage": "eval (after logic dedup)",
        },
        "hypothesis_class_alignment": {
            "registry_default_generation": list(DEFAULT_GENERATION_CLASS_IDS),
            "extra_factory_families": [
                FAMILY_VOL_RISK_ADJUSTED,
                FAMILY_RATE_FACTOR,
                FAMILY_MULTI_FACTOR,
                FAMILY_INDEX_VOL_REGIME,
            ],
            "excluded": [CLASS_SIMPLE_DAILY_SIGN],
        },
        **_freeze(),
    }


# ---------------------------------------------------------------------------
# Config + generated strategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MassFactoryConfig:
    """Batch generation / eval configuration (logic-diversity factory)."""

    seed: int = DEFAULT_SEED
    n: int = DEFAULT_N
    family_ratios: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_FAMILY_RATIOS)
    )
    max_family_share: float = DEFAULT_MAX_FAMILY_SHARE
    one_way_cost: float = DEFAULT_ONE_WAY
    available_datasets: frozenset[str] = FACTORY_AVAILABLE_DATASETS
    # Eval lite knobs
    max_days_per_period: int = 80
    max_codes: int = 20
    use_q4_periods: bool = True
    paper_sample_k: int = 0
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS
    min_activation: float = DEFAULT_MIN_ACTIVATION
    fail_one_continue: bool = True
    # W88: allow limited numeric fill after unique logics (still near-duped)
    allow_numeric_variants: bool = True
    near_dup_threshold: float = DEFAULT_NEAR_DUP_THRESHOLD
    # Eval only after dedup (distinct logics)
    eval_after_dedup: bool = True

    def normalized_ratios(self) -> dict[str, float]:
        raw = {
            str(k): float(v)
            for k, v in dict(self.family_ratios).items()
            if float(v) > 0 and str(k) in FAMILY_DEFINITIONS
        }
        if not raw:
            raw = dict(DEFAULT_FAMILY_RATIOS)
        raw.pop(CLASS_SIMPLE_DAILY_SIGN, None)
        total = sum(raw.values())
        if total <= 0:
            raise ValueError("family_ratios must sum to > 0")
        return {k: v / total for k, v in raw.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": int(self.seed),
            "n": int(self.n),
            "family_ratios": self.normalized_ratios(),
            "max_family_share": float(self.max_family_share),
            "one_way_cost": float(self.one_way_cost),
            "available_datasets": sorted(self.available_datasets),
            "max_days_per_period": int(self.max_days_per_period),
            "max_codes": int(self.max_codes),
            "use_q4_periods": bool(self.use_q4_periods),
            "paper_sample_k": int(self.paper_sample_k),
            "near_zero_abs": float(self.near_zero_abs),
            "min_activation": float(self.min_activation),
            "fail_one_continue": bool(self.fail_one_continue),
            "allow_numeric_variants": bool(self.allow_numeric_variants),
            "near_dup_threshold": float(self.near_dup_threshold),
            "eval_after_dedup": bool(self.eval_after_dedup),
            "continuous_paper": CONTINUOUS_PAPER,
            **_freeze(),
        }


@dataclass(frozen=True)
class GeneratedStrategy:
    """One generated strategy individual (logic-centric)."""

    strategy_id: str
    family_id: str
    params: Mapping[str, Any]
    datasets_required: tuple[str, ...]
    generation_index: int
    seed: int
    status: str  # accepted | rejected_at_gen
    logic_id: str
    thesis: str
    signal_definition: str
    position_rule: str
    datasets_used: tuple[str, ...]
    logic_fingerprint: str
    is_numeric_variant: bool = False
    reject_reason: str | None = None
    hypothesis_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "logic_id": self.logic_id,
            "logic_fingerprint": self.logic_fingerprint,
            "thesis": self.thesis,
            "signal_definition": self.signal_definition,
            "position_rule": self.position_rule,
            "datasets_used": list(self.datasets_used),
            "family_id": self.family_id,
            "hypothesis_class": self.hypothesis_class or self.family_id,
            "params": dict(self.params),
            "datasets_required": list(self.datasets_required),
            "generation_index": int(self.generation_index),
            "seed": int(self.seed),
            "status": self.status,
            "is_numeric_variant": bool(self.is_numeric_variant),
            "reject_reason": self.reject_reason,
            "version": MASS_FACTORY_VERSION,
            "wave": MASS_FACTORY_WAVE,
            **_freeze(),
        }


def stable_strategy_id(
    *,
    seed: int,
    family_id: str,
    params: Mapping[str, Any],
    generation_index: int,
    logic_id: str | None = None,
) -> str:
    """Deterministic stable ID from seed + logic + params + index."""
    payload = {
        "seed": int(seed),
        "family_id": str(family_id),
        "logic_id": str(logic_id or ""),
        "params": _canonical_params(params),
        "i": int(generation_index),
        "v": MASS_FACTORY_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    tag = str(logic_id or family_id).replace("_", "")[:8]
    return f"msf_{int(seed):08x}_{int(generation_index):04d}_{tag}_{digest}"


def _canonical_params(params: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in sorted(params.keys()):
        v = params[k]
        if isinstance(v, float):
            out[k] = round(v, 8)
        elif isinstance(v, (int, str, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _coarse_bucket(key: str, value: Any) -> Any:
    """Coarse bucket for near-dup scoring (collapses micro grids)."""
    if value is None:
        return None
    if key in {"hold_days", "post_hold_days", "momentum_n", "vol_n"}:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return str(value)
        # buckets: short / mid / long
        if v <= 5:
            return "short"
        if v <= 12:
            return "mid"
        return "long"
    if key in {"long_frac", "short_frac", "vol_threshold", "high_threshold", "low_threshold"}:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        return round(v, 1)  # 0.3 and 0.4 → different only at 0.1; still high sim
    return value


def individual_similarity_features(ind: Mapping[str, Any]) -> dict[str, Any]:
    """Features used for near-duplicate scoring."""
    params = dict(ind.get("params") or {})
    structural = {
        k: params.get(k)
        for k in params
        if k not in NUMERIC_ONLY_KNOBS
    }
    coarse_knobs = {
        k: _coarse_bucket(k, params.get(k))
        for k in sorted(NUMERIC_ONLY_KNOBS)
        if k in params
    }
    return {
        "logic_id": str(ind.get("logic_id") or ""),
        "logic_fingerprint": str(ind.get("logic_fingerprint") or ""),
        "family_id": str(ind.get("family_id") or ""),
        "signal_definition": str(ind.get("signal_definition") or ""),
        "position_rule": str(ind.get("position_rule") or ""),
        "datasets": tuple(sorted(ind.get("datasets_used") or ind.get("datasets_required") or [])),
        "structural": structural,
        "coarse_knobs": coarse_knobs,
    }


def similarity_score(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """Score near-duplicate similarity in [0, 1].

    High score when only grid knobs differ (hold/mom/frac) under same
    signal family + position rule + datasets. Low when thesis / entry /
    position / datasets differ.
    """
    fa = individual_similarity_features(a)
    fb = individual_similarity_features(b)

    # Exact same logic fingerprint → pure clone / numeric twin
    if fa["logic_fingerprint"] and fa["logic_fingerprint"] == fb["logic_fingerprint"]:
        if fa["coarse_knobs"] == fb["coarse_knobs"]:
            return 1.0
        # same logic, different coarse knobs → still near-dup (grid mutation)
        return 0.95

    # Same logic_id different fingerprint (shouldn't happen often)
    if fa["logic_id"] and fa["logic_id"] == fb["logic_id"]:
        return 0.92

    score = 0.0
    # Family / signal / position / datasets (core of logic diversity)
    if fa["family_id"] == fb["family_id"] and fa["family_id"]:
        score += 0.25
    if fa["signal_definition"] == fb["signal_definition"] and fa["signal_definition"]:
        score += 0.25
    if fa["position_rule"] == fb["position_rule"] and fa["position_rule"]:
        score += 0.25
    if fa["datasets"] == fb["datasets"] and fa["datasets"]:
        score += 0.15

    # Structural keys agreement
    sa, sb = fa["structural"], fb["structural"]
    if sa or sb:
        keys = set(sa) | set(sb)
        if keys:
            agree = sum(1 for k in keys if sa.get(k) == sb.get(k))
            score += 0.10 * (agree / len(keys))

    # Coarse knob agreement alone cannot push past threshold without logic match
    ca, cb = fa["coarse_knobs"], fb["coarse_knobs"]
    if ca and cb and ca == cb and score >= 0.7:
        score = min(1.0, score + 0.05)

    return min(1.0, score)


def dedup_strategies(
    strategies: Sequence[Mapping[str, Any]],
    *,
    threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
) -> dict[str, Any]:
    """Drop high-similarity grid mutations; keep first of each logic cluster."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for raw in strategies:
        s = dict(raw)
        is_dup = False
        matched_id = None
        best_sim = 0.0
        for k in kept:
            sim = similarity_score(s, k)
            if sim >= threshold and sim > best_sim:
                is_dup = True
                matched_id = k.get("strategy_id")
                best_sim = sim
        if is_dup:
            dropped.append(
                {
                    **s,
                    "dedup_status": "dropped",
                    "near_dup_of": matched_id,
                    "similarity": round(best_sim, 4),
                    "reject_reason": REJECT_NEAR_DUPLICATE,
                }
            )
        else:
            kept.append({**s, "dedup_status": "kept"})
    return {
        "n_input": len(strategies),
        "n_after_dedup": len(kept),
        "n_dropped": len(dropped),
        "threshold": float(threshold),
        "kept": kept,
        "dropped": dropped,
    }


def validate_strategy_at_gen(
    family_id: str,
    params: Mapping[str, Any],
    *,
    available_datasets: frozenset[str] | set[str] = FACTORY_AVAILABLE_DATASETS,
    logic_id: str | None = None,
) -> tuple[bool, str | None]:
    """Gen-time validity: PIT, datasets, forbidden classes/params."""
    fid = str(family_id).strip()
    if fid == CLASS_SIMPLE_DAILY_SIGN:
        return False, REJECT_SIMPLE_DAILY_SIGN
    if fid.startswith("s") and fid[1:].isdigit() and int(fid[1:]) <= 5:
        return False, REJECT_S1_S5
    if logic_id is not None and str(logic_id) not in LOGIC_TEMPLATES:
        return False, REJECT_UNKNOWN_LOGIC
    if fid not in FAMILY_DEFINITIONS and fid != FAMILY_VOL_RISK_ADJUSTED:
        # FAMILY_VOL_RISK is in FAMILY_DEFINITIONS when templates include it
        if fid not in {t.family_id for t in LOGIC_TEMPLATES.values()}:
            return False, REJECT_UNKNOWN_FAMILY

    # Datasets from template if available
    if logic_id and logic_id in LOGIC_TEMPLATES:
        req = LOGIC_TEMPLATES[logic_id].datasets_used
    elif fid in FAMILY_DEFINITIONS:
        req = FAMILY_DEFINITIONS[fid].datasets_required
    else:
        req = ()
    missing = [d for d in req if d not in available_datasets]
    if missing:
        return False, f"{REJECT_MISSING_DATASETS}:{','.join(missing)}"

    p = dict(params)
    if fid == CLASS_EVENT_POST:
        em = str(p.get("entry_mode") or "")
        if em in _EVENT_ENTRY_FORBIDDEN or (
            "look" in em.lower() and "ahead" in em.lower()
        ):
            return False, REJECT_LOOKAHEAD
        if em and em not in _EVENT_ENTRY_SAFE:
            return False, REJECT_LOOKAHEAD
        h = int(p.get("post_hold_days") or 0)
        if h < 1:
            return False, REJECT_INVALID_PARAMS
    if fid == CLASS_MULTI_DAY_HOLD:
        h = int(p.get("hold_days") or 0)
        if h < 1:
            return False, REJECT_INVALID_PARAMS
    if fid == CLASS_CROSS_SECTION_RELATIVE:
        lf = float(p.get("long_frac") or 0)
        sf = float(p.get("short_frac") or 0)
        if lf <= 0 or sf <= 0 or lf + sf > 1.0 + 1e-9:
            return False, REJECT_INVALID_PARAMS
        if int(p.get("momentum_n") or 0) < 1 or int(p.get("hold_days") or 0) < 1:
            return False, REJECT_INVALID_PARAMS
    if fid == FAMILY_VOL_RISK_ADJUSTED:
        if float(p.get("vol_threshold") or 0) <= 0:
            return False, REJECT_INVALID_PARAMS
        if int(p.get("vol_n") or 0) < 2:
            return False, REJECT_INVALID_PARAMS
    if fid == FAMILY_INDEX_VOL_REGIME:
        mode = str(p.get("mode") or "")
        if mode not in {
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        }:
            return False, REJECT_INVALID_PARAMS
        if int(p.get("vol_short_n") or 0) < 2:
            return False, REJECT_INVALID_PARAMS
        if int(p.get("vol_long_n") or 0) < int(p.get("vol_short_n") or 0):
            return False, REJECT_INVALID_PARAMS
        if int(p.get("hold_days") or 0) < 1 or int(p.get("momentum_n") or 0) < 1:
            return False, REJECT_INVALID_PARAMS
    return True, None


def _minimal_numeric_variants(tpl: LogicTemplate) -> list[dict[str, Any]]:
    """At most a couple coarse numeric variants (will near-dup collapse).

    Not a hold/mom/frac mass grid. Used only when allow_numeric_variants and
    capacity remains after unique logics are placed.
    """
    base = dict(tpl.base_params)
    variants: list[dict[str, Any]] = []
    # One mild hold shift if hold-like key exists (explicitly a numeric variant)
    if "hold_days" in base and int(base["hold_days"]) not in (1,):
        v = dict(base)
        h = int(base["hold_days"])
        v["hold_days"] = 15 if h <= 10 else 10
        if "momentum_n" in v and int(v.get("momentum_n") or 0) == h:
            v["momentum_n"] = v["hold_days"]
        variants.append(v)
    if "post_hold_days" in base:
        v = dict(base)
        v["post_hold_days"] = 10 if int(base["post_hold_days"]) != 10 else 3
        variants.append(v)
    return variants[:1]  # at most one numeric variant per logic


def generate_strategy_batch(
    config: MassFactoryConfig | None = None,
    *,
    seed: int | None = None,
    n: int | None = None,
    family_ratios: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Generate strategy individuals from distinct logic templates.

    Primary unit = logic template. Numeric knob clones are secondary and
    near-dup scored. Returns metrics: n_generated, n_unique_logic,
    n_numeric_variant, n_after_dedup.
    """
    cfg = config or MassFactoryConfig()
    if seed is not None or n is not None or family_ratios is not None:
        cfg = MassFactoryConfig(
            seed=int(seed if seed is not None else cfg.seed),
            n=int(n if n is not None else cfg.n),
            family_ratios=dict(
                family_ratios if family_ratios is not None else cfg.family_ratios
            ),
            max_family_share=cfg.max_family_share,
            one_way_cost=cfg.one_way_cost,
            available_datasets=cfg.available_datasets,
            max_days_per_period=cfg.max_days_per_period,
            max_codes=cfg.max_codes,
            use_q4_periods=cfg.use_q4_periods,
            paper_sample_k=cfg.paper_sample_k,
            near_zero_abs=cfg.near_zero_abs,
            min_activation=cfg.min_activation,
            fail_one_continue=cfg.fail_one_continue,
            allow_numeric_variants=cfg.allow_numeric_variants,
            near_dup_threshold=cfg.near_dup_threshold,
            eval_after_dedup=cfg.eval_after_dedup,
        )
    if cfg.n < 1:
        raise ValueError("n must be >= 1")

    rng_state = int(cfg.seed) & 0xFFFFFFFF

    def _next_rand() -> int:
        nonlocal rng_state
        rng_state = (1664525 * rng_state + 1013904223) & 0xFFFFFFFF
        return rng_state

    # Deterministic order of logic templates
    logic_ids = list(LOGIC_TEMPLATE_IDS)
    for i in range(len(logic_ids) - 1, 0, -1):
        j = _next_rand() % (i + 1)
        logic_ids[i], logic_ids[j] = logic_ids[j], logic_ids[i]

    strategies: list[GeneratedStrategy] = []
    gen_rejected: list[GeneratedStrategy] = []
    family_dist: dict[str, int] = {}
    logic_dist: dict[str, int] = {}
    n_numeric = 0
    index = 0

    def _try_emit(tpl: LogicTemplate, params: dict[str, Any], *, numeric: bool) -> bool:
        nonlocal index, n_numeric
        if len(strategies) >= cfg.n:
            return False
        ok, reason = validate_strategy_at_gen(
            tpl.family_id,
            params,
            available_datasets=cfg.available_datasets,
            logic_id=tpl.logic_id,
        )
        sid = stable_strategy_id(
            seed=cfg.seed,
            family_id=tpl.family_id,
            params=params,
            generation_index=index,
            logic_id=tpl.logic_id,
        )
        hyp = tpl.family_id if tpl.family_id in HYPOTHESIS_CLASS_REGISTRY else tpl.family_id
        row = GeneratedStrategy(
            strategy_id=sid,
            family_id=tpl.family_id,
            params=params,
            datasets_required=tpl.datasets_used,
            generation_index=index,
            seed=cfg.seed,
            status="accepted" if ok else "rejected_at_gen",
            logic_id=tpl.logic_id,
            thesis=tpl.thesis,
            signal_definition=tpl.signal_definition,
            position_rule=tpl.position_rule,
            datasets_used=tpl.datasets_used,
            logic_fingerprint=tpl.logic_fingerprint(),
            is_numeric_variant=numeric,
            reject_reason=None if ok else reason,
            hypothesis_class=hyp,
        )
        index += 1
        if ok:
            strategies.append(row)
            family_dist[tpl.family_id] = family_dist.get(tpl.family_id, 0) + 1
            logic_dist[tpl.logic_id] = logic_dist.get(tpl.logic_id, 0) + 1
            if numeric:
                n_numeric += 1
            return True
        gen_rejected.append(row)
        return False

    # Pass 1: one primary individual per distinct logic template
    for lid in logic_ids:
        if len(strategies) >= cfg.n:
            break
        tpl = LOGIC_TEMPLATES[lid]
        if not tpl.generation_enabled:
            continue
        _try_emit(tpl, dict(tpl.base_params), numeric=False)

    # Pass 2: optional limited numeric variants (capacity fill; near-dup later)
    if cfg.allow_numeric_variants and len(strategies) < cfg.n:
        for lid in logic_ids:
            if len(strategies) >= cfg.n:
                break
            tpl = LOGIC_TEMPLATES[lid]
            for vp in _minimal_numeric_variants(tpl):
                if len(strategies) >= cfg.n:
                    break
                # skip if identical to base
                if _canonical_params(vp) == _canonical_params(tpl.base_params):
                    continue
                _try_emit(tpl, vp, numeric=True)

    n_generated = len(strategies)
    unique_logic_ids = sorted({s.logic_id for s in strategies})
    n_unique_logic = len(unique_logic_ids)

    # Near-duplicate collapse (grid mutations out)
    dedup = dedup_strategies(
        [s.to_dict() for s in strategies],
        threshold=cfg.near_dup_threshold,
    )
    after_dedup = list(dedup["kept"])
    n_after_dedup = int(dedup["n_after_dedup"])

    shares = {
        f: (family_dist.get(f, 0) / n_generated if n_generated else 0.0)
        for f in sorted(set(list(FACTORY_FAMILY_IDS) + list(family_dist)))
    }
    max_share = max(shares.values()) if shares and n_generated else 0.0

    # Logic diversity ok: after_dedup close to unique_logic; not flooded by clones
    logic_diversity_ok = (
        n_unique_logic >= min(10, len(LOGIC_TEMPLATES))
        and n_after_dedup >= n_unique_logic  # kept at least one per unique
        and (n_numeric == 0 or n_after_dedup <= n_unique_logic + 2)
    )

    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "config": cfg.to_dict(),
        "n_requested": int(cfg.n),
        # W88 primary metrics
        "n_generated": n_generated,
        "n_generated_accepted": n_generated,  # back-compat alias
        "n_unique_logic": n_unique_logic,
        "n_numeric_variant": n_numeric,
        "n_after_dedup": n_after_dedup,
        "n_dropped_near_dup": int(dedup["n_dropped"]),
        "unique_logic_ids": unique_logic_ids,
        "logic_distribution": logic_dist,
        "unique_logic_count": n_unique_logic,
        "numeric_variant_count": n_numeric,
        # capacity / legacy
        "n_ge_100": n_generated >= 100 or n_after_dedup >= len(LOGIC_TEMPLATES),
        "n_rejected_at_gen": len(gen_rejected),
        "family_distribution": family_dist,
        "family_shares": shares,
        "max_family_share_observed": max_share,
        "anti_bias_ok": (
            max_share <= cfg.max_family_share + 1e-9 if n_generated else False
        ),
        "logic_diversity_ok": logic_diversity_ok,
        "n_families_used": sum(1 for v in family_dist.values() if v > 0),
        "n_logic_templates_catalog": len(LOGIC_TEMPLATES),
        "strategies": [s.to_dict() for s in strategies],
        "strategies_after_dedup": after_dedup,
        "near_dup_dropped": dedup["dropped"],
        "dedup": {
            "threshold": dedup["threshold"],
            "n_input": dedup["n_input"],
            "n_after_dedup": dedup["n_after_dedup"],
            "n_dropped": dedup["n_dropped"],
        },
        "gen_rejected": [s.to_dict() for s in gen_rejected],
        "families_document": family_definitions_document(),
        "logic_templates_document": logic_templates_document(),
        "frozen_default_path": list(FROZEN_DEFAULT_PATH),
        "note": (
            "Diversity = unique economic logics after near-dup. "
            "n_generated may exceed n_unique_logic when numeric fill is on; "
            "eval should use strategies_after_dedup. "
            "3 default-path reps frozen (not retuned)."
        ),
        **_freeze(),
    }


# ---------------------------------------------------------------------------
# Vol-risk / vol-expand pure evaluators (bars only)
# ---------------------------------------------------------------------------


def _realized_vol(closes: Sequence[float], end_i: int, vol_n: int) -> float | None:
    if end_i < vol_n or vol_n < 2:
        return None
    rets: list[float] = []
    for j in range(end_i - vol_n + 1, end_i + 1):
        if j < 1:
            return None
        c0, c1 = closes[j - 1], closes[j]
        if c0 is None or c1 is None or c0 == 0:
            return None
        rets.append((float(c1) / float(c0)) - 1.0)
    if len(rets) < 2:
        return None
    m = mean(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) if var >= 0 else None


def evaluate_vol_risk_adjusted_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = 5,
    vol_n: int = 10,
    vol_threshold: float = 1.0,
    one_way_cost: float = DEFAULT_ONE_WAY,
    gate_mode: str = "mom_over_vol",
) -> dict[str, Any]:
    """Vol-gated multi-day mom (mom_over_vol or vol_expand)."""
    from research.class_hyp_eval import momentum_series

    h = int(hold_days)
    vn = int(vol_n)
    thr = float(vol_threshold)
    mode = str(gate_mode or "mom_over_vol")
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_active = 0
    n_filtered = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, vn) + 2:
            continue
        moms = momentum_series(pairs_l, n=h)
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        entry_signs: list[float | None] = []
        for i, (_d, mom) in enumerate(moms):
            if mom is None:
                entry_signs.append(None)
                continue
            vol = _realized_vol(closes, i, vn)
            if vol is None or vol <= 1e-12:
                entry_signs.append(None)
                n_filtered += 1
                continue
            if mode == "vol_expand":
                # prior window vol
                prior = _realized_vol(closes, i - vn, vn) if i >= 2 * vn else None
                if prior is None or prior <= 1e-12:
                    entry_signs.append(None)
                    n_filtered += 1
                    continue
                expand = vol / prior
                if expand < thr:
                    entry_signs.append(0.0)
                    n_filtered += 1
                    continue
                entry_signs.append(sign_from_numeric(mom))
            else:
                score = abs(float(mom)) / vol
                if score < thr:
                    entry_signs.append(0.0)
                    n_filtered += 1
                    continue
                entry_signs.append(sign_from_numeric(mom))
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="fixed_horizon"
        )
        for i, pos in enumerate(held):
            holding_records.append(
                {"date": dates[i], "code": code, "sign": pos}
            )
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    return {
        "signal_id": f"c21_vol_risk_{mode}",
        "hypothesis_class": FAMILY_VOL_RISK_ADJUSTED,
        "hold_days": h,
        "vol_n": vn,
        "vol_threshold": thr,
        "gate_mode": mode,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_filtered": n_filtered,
        "n_signed_returns": len(signed_returns),
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": {
            "activation_rate": (
                float(n_active) / float(n_code_days) if n_code_days else None
            ),
            "n_active": n_active,
        },
        **_freeze(),
        "note": (
            f"Vol gate mode={mode} thr={thr} hold={h} vol_n={vn}. "
            "Not READY / not Mass."
        ),
    }


# ---------------------------------------------------------------------------
# Batch evaluation context + per-strategy eval
# ---------------------------------------------------------------------------


@dataclass
class BatchDataContext:
    """Cached offline panels for fail-fast batch eval."""

    periods: list[dict[str, Any]]
    panels: list[dict[str, Any]]
    one_way_cost: float
    load_notes: dict[str, Any] = field(default_factory=dict)


def load_batch_data_context(
    config: MassFactoryConfig,
    *,
    periods: Sequence[Mapping[str, Any]] | None = None,
    codes: Sequence[str] | None = None,
    mirror_dir: str | Path | None = None,
    sqlite_path: str | Path | None = None,
    synthetic: bool = False,
) -> BatchDataContext:
    """Load period panels once for the batch (lite multi-year by default)."""
    from research.class_hyp_eval import (
        DEFAULT_EVAL_CODES,
        DEFAULT_PERIODS,
        DEFAULT_PERIODS_Q4,
        DEFAULT_BARS_MIRROR_DIR,
        DEFAULT_SQLITE,
        bars_rich_to_close_panel,
        build_repo_curve_series,
        load_bars_ndjson_rich,
        load_fins_events_from_sqlite,
        load_margin_ndjson,
        load_nky_vol_series_from_sqlite,
        load_repo_rows_all_tenors_from_sqlite,
        load_repo_rows_from_sqlite,
        load_short_ratio_series_from_sqlite,
        resolve_bars_path,
        resolve_margin_path,
    )
    from research.cost_models import load_repo_rate_series_from_rows

    if synthetic:
        return _synthetic_batch_context(config)

    period_list = [
        dict(p)
        for p in (
            periods
            or (
                DEFAULT_PERIODS_Q4
                if config.use_q4_periods
                else DEFAULT_PERIODS
            )
        )
    ]
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else list(DEFAULT_EVAL_CODES)[: int(config.max_codes)]
    )
    mdir = Path(mirror_dir) if mirror_dir else DEFAULT_BARS_MIRROR_DIR
    db = Path(sqlite_path) if sqlite_path else DEFAULT_SQLITE

    repo_rows = load_repo_rows_from_sqlite(db) if db.exists() else []
    repo_series = (
        load_repo_rate_series_from_rows(repo_rows) if repo_rows else None
    )
    # Multi-tenor for curve-shape factor (W89); overnight-only rows lack 3M.
    repo_all = load_repo_rows_all_tenors_from_sqlite(db) if db.exists() else []
    curve_series = build_repo_curve_series(repo_all) if repo_all else None
    # W91: Nikkei/TOPIX realized-vol series (NK225F prefer → TOPIX fallback)
    nky_vol_series = (
        load_nky_vol_series_from_sqlite(
            db, start="2014-01-01", end="2026-12-31"
        )
        if db.exists()
        else None
    )
    fins_events = (
        load_fins_events_from_sqlite(
            db, codes=selected, start="2014-01-01", end="2026-12-31"
        )
        if db.exists()
        else {}
    )
    short_series = (
        load_short_ratio_series_from_sqlite(
            db, section="0050", start="2014-01-01", end="2026-12-31"
        )
        if db.exists()
        else []
    )

    panels: list[dict[str, Any]] = []
    for raw in period_list:
        p = dict(raw)
        pid = str(p.get("period_id") or p.get("year") or "period")
        p_start = str(p.get("period_start") or "")[:10] or None
        p_end = str(p.get("period_end") or "")[:10] or None
        bars_path = p.get("bars_path") or resolve_bars_path(pid, mirror_dir=mdir)
        if bars_path is None or not Path(bars_path).exists():
            panels.append(
                {
                    "period_id": pid,
                    "year": p.get("year"),
                    "period_start": p_start,
                    "period_end": p_end,
                    "status": "missing_bars",
                    "bars": {},
                    "margin": {},
                    "repo_series": repo_series,
                    "curve_series": curve_series,
                    "nky_vol_series": nky_vol_series,
                    "fins_events": fins_events,
                    "short_series": short_series,
                }
            )
            continue
        rich = load_bars_ndjson_rich(
            bars_path,
            codes=selected,
            max_days=int(config.max_days_per_period),
            period_start=p_start,
            period_end=p_end,
        )
        bars = bars_rich_to_close_panel(rich)
        margin_path = resolve_margin_path(pid, mirror_dir=mdir)
        margin: dict[str, list[tuple[str, float]]] = {}
        if margin_path is not None and Path(margin_path).exists():
            try:
                margin = load_margin_ndjson(margin_path, codes=selected)
            except Exception:
                margin = {}
        panels.append(
            {
                "period_id": pid,
                "year": p.get("year"),
                "period_start": p_start,
                "period_end": p_end,
                "status": "ok" if bars else "empty_bars",
                "bars": bars,
                "margin": margin,
                "repo_series": repo_series,
                "curve_series": curve_series,
                "nky_vol_series": nky_vol_series,
                "fins_events": fins_events,
                "short_series": short_series,
                "bars_path": str(bars_path),
            }
        )

    return BatchDataContext(
        periods=period_list,
        panels=panels,
        one_way_cost=float(config.one_way_cost),
        load_notes={
            "n_periods": len(panels),
            "n_codes": len(selected),
            "codes": selected,
            "mirror_dir": str(mdir),
            "sqlite": str(db),
            "sqlite_exists": db.exists(),
            "n_repo_rows": len(repo_rows),
            "n_repo_all_tenor_rows": len(repo_all),
            "n_curve_spread_obs": (
                int((curve_series or {}).get("n_obs_spread") or 0)
            ),
            "curve_definition": (curve_series or {}).get("definition"),
            "nky_vol_source": (nky_vol_series or {}).get("source"),
            "nky_vol_dataset": (nky_vol_series or {}).get("dataset"),
            "n_nky_vol_short": int((nky_vol_series or {}).get("n_obs_short") or 0),
            "n_nky_vol_long": int((nky_vol_series or {}).get("n_obs_long") or 0),
            "n_fins_codes": len(fins_events),
            "use_q4_periods": bool(config.use_q4_periods),
            "max_days_per_period": int(config.max_days_per_period),
            "tradeoff": (
                "Lite multi-year: Q4 (or capped full) windows + code subsample "
                "for wall-time. Not production research_candidate SoT; "
                "survivors need deeper class_hyp re-eval before any promotion. "
                "Heavy multi-year only for promising survivors."
            ),
        },
    )


def _synthetic_batch_context(config: MassFactoryConfig) -> BatchDataContext:
    """Deterministic synthetic panels for unit tests (no disk)."""
    panels: list[dict[str, Any]] = []
    for yi, year in enumerate((2019, 2021, 2023)):
        dates = [f"{year}-10-{d:02d}" for d in range(1, 29)]
        bars: dict[str, list[tuple[str, float]]] = {}
        margin: dict[str, list[tuple[str, float]]] = {}
        for ci, code in enumerate(("13010", "72030", "67580", "99840")):
            base = 100.0 + 10 * ci + yi
            series = [
                (d, base + 0.4 * i + (0.2 if (i + ci) % 5 == 0 else 0.0))
                for i, d in enumerate(dates)
            ]
            bars[code] = series
            margin[code] = [
                (dates[i], 1000.0 + 20 * i + 5 * ci)
                for i in range(0, len(dates), 3)
            ]
        rates = {d: 0.05 + 0.001 * i for i, d in enumerate(dates)}
        short_r = {d: 0.04 + 0.001 * i for i, d in enumerate(dates)}
        long_r = {
            d: (0.06 + 0.001 * i if i % 7 != 0 else 0.02 + 0.0005 * i)
            for i, d in enumerate(dates)
        }
        spread = {d: long_r[d] - short_r[d] for d in dates}
        repo_series = {
            "rates_by_date": rates,
            "dataset": "jsda_tokyo_repo_rates",
            "source": "synthetic",
        }
        curve_series = {
            "kind": "repo_curve_series",
            "dataset": "jsda_tokyo_repo_rates",
            "short_tenor": "overnight/翌日物/T+0",
            "long_tenor": "3M/T+1",
            "definition": "spread = long_tenor_rate - short_tenor_rate",
            "short_rates_by_date": short_r,
            "long_rates_by_date": long_r,
            "spread_by_date": spread,
            "rates_by_date": short_r,
            "n_obs_spread": len(spread),
            "source": "synthetic",
        }
        # Synthetic Nikkei-proxy RV: oscillate short/long levels + ratio regimes
        from research.class_hyp_eval import build_nky_vol_series

        nky_closes = []
        px = 38000.0 + 500 * yi
        for i, d in enumerate(dates):
            # mild trend + regime-ish noise so short/long RV differ
            shock = 0.02 if (i % 11 == 0) else (0.005 if i % 3 == 0 else 0.001)
            sign = 1.0 if i % 2 == 0 else -1.0
            px = max(1000.0, px * (1.0 + sign * shock * (1.0 + 0.1 * (i % 5))))
            nky_closes.append((d, px))
        nky_vol_series = build_nky_vol_series(
            nky_closes,
            short_n=5,
            long_n=15,
            source="synthetic_nk225f",
            dataset="synthetic",
        )
        fins_events = {
            "13010": [
                {
                    "disc_date": dates[5],
                    "disc_time": "15:00:00",
                    "eps": 10.0 + yi,
                    "feps": 9.0,
                    "bps": 50.0,
                    "prior_eps": 8.0,
                }
            ],
            "72030": [
                {
                    "disc_date": dates[10],
                    "disc_time": "16:00:00",
                    "eps": 5.0,
                    "feps": 6.0,
                    "bps": 20.0,
                    "prior_eps": 5.5,
                }
            ],
        }
        panels.append(
            {
                "period_id": f"y{year}_syn",
                "year": year,
                "period_start": dates[0],
                "period_end": dates[-1],
                "status": "ok",
                "bars": bars,
                "margin": margin,
                "repo_series": repo_series,
                "curve_series": curve_series,
                "nky_vol_series": nky_vol_series,
                "fins_events": fins_events,
                "short_series": [
                    (d, 0.01 + 0.0001 * i) for i, d in enumerate(dates)
                ],
            }
        )
    return BatchDataContext(
        periods=[{"period_id": p["period_id"], "year": p["year"]} for p in panels],
        panels=panels,
        one_way_cost=float(config.one_way_cost),
        load_notes={"synthetic": True, "n_periods": len(panels)},
    )


def _eval_on_panel(
    family_id: str,
    params: Mapping[str, Any],
    panel: Mapping[str, Any],
    *,
    one_way_cost: float,
) -> dict[str, Any]:
    """Dispatch pure evaluator for one strategy × one period panel."""
    from research.class_hyp_eval import (
        evaluate_cross_section_on_bars,
        evaluate_event_post_on_bars,
        evaluate_flow_demand_on_bars,
        evaluate_fundamentals_price_on_bars,
        evaluate_macro_conditioned_on_bars,
        evaluate_mf_flow_price_on_bars,
        evaluate_mf_value_mom_rate_on_bars,
        evaluate_multi_day_hold_on_bars,
        evaluate_nky_vol_abs_level_on_bars,
        evaluate_nky_vol_term_levels_on_bars,
        evaluate_nky_vol_term_ratio_on_bars,
        evaluate_rate_curve_xs_on_bars,
        evaluate_rate_level_xs_on_bars,
        momentum_series,
    )

    bars = panel.get("bars") or {}
    if not bars:
        return {
            "status": "data_missing",
            "skip_reason": "empty_or_missing_bars",
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
        }

    fid = str(family_id)
    p = dict(params)
    if fid == CLASS_MULTI_DAY_HOLD:
        polarity = int(p.get("signal_polarity") or 1)
        if polarity >= 0:
            out = evaluate_multi_day_hold_on_bars(
                bars,
                hold_days=int(p.get("hold_days") or DEFAULT_HOLD_DAYS),
                one_way_cost=one_way_cost,
                rebalance_mode=str(p.get("rebalance_mode") or "fixed_horizon"),
            )
        else:
            # Mean-reversion entry: invert momentum sign at signal time
            out = _evaluate_mdh_polarity_on_bars(
                bars,
                hold_days=int(p.get("hold_days") or DEFAULT_HOLD_DAYS),
                one_way_cost=one_way_cost,
                rebalance_mode=str(p.get("rebalance_mode") or "fixed_horizon"),
                polarity=-1,
                momentum_series_fn=momentum_series,
            )
    elif fid == CLASS_CROSS_SECTION_RELATIVE:
        out = evaluate_cross_section_on_bars(
            bars,
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 5),
            long_frac=float(p.get("long_frac") or 0.3),
            short_frac=float(p.get("short_frac") or 0.3),
            one_way_cost=one_way_cost,
        )
    elif fid == CLASS_MACRO_CONDITIONED:
        out = evaluate_macro_conditioned_on_bars(
            bars,
            panel.get("repo_series"),
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 5),
            mode=str(p.get("mode") or "rate_change"),
            one_way_cost=one_way_cost,
            high_threshold=float(p.get("high_threshold") or 0.05),
            low_threshold=float(p.get("low_threshold") or 0.0),
        )
    elif fid == FAMILY_RATE_FACTOR:
        mode = str(p.get("mode") or "rate_level_xs_risk_adj")
        if mode == "rate_curve_shape_xs":
            out = evaluate_rate_curve_xs_on_bars(
                bars,
                panel.get("curve_series"),
                momentum_n=int(p.get("momentum_n") or 5),
                hold_days=int(p.get("hold_days") or 10),
                long_frac=float(p.get("long_frac") or 0.3),
                short_frac=float(p.get("short_frac") or 0.3),
                one_way_cost=one_way_cost,
                steep_threshold=float(p.get("steep_threshold") or 0.0),
                invert_threshold=float(p.get("invert_threshold") or 0.0),
            )
        else:
            out = evaluate_rate_level_xs_on_bars(
                bars,
                panel.get("repo_series"),
                momentum_n=int(p.get("momentum_n") or 5),
                hold_days=int(p.get("hold_days") or 10),
                long_frac=float(p.get("long_frac") or 0.3),
                short_frac=float(p.get("short_frac") or 0.3),
                one_way_cost=one_way_cost,
                high_threshold=float(p.get("high_threshold") or 0.05),
                low_threshold=float(p.get("low_threshold") or 0.0),
            )
    elif fid == FAMILY_MULTI_FACTOR:
        mode = str(p.get("mode") or "value_mom_rate")
        if mode == "flow_price":
            out = evaluate_mf_flow_price_on_bars(
                bars,
                panel.get("margin") or {},
                hold_days=int(p.get("hold_days") or 10),
                momentum_n=int(p.get("momentum_n") or 10),
                one_way_cost=one_way_cost,
            )
        else:
            out = evaluate_mf_value_mom_rate_on_bars(
                bars,
                panel.get("fins_events") or {},
                panel.get("repo_series"),
                hold_days=int(p.get("hold_days") or 10),
                momentum_n=int(p.get("momentum_n") or 10),
                one_way_cost=one_way_cost,
                high_threshold=float(p.get("high_threshold") or 0.05),
                low_threshold=float(p.get("low_threshold") or 0.0),
            )
    elif fid == CLASS_EVENT_POST:
        out = evaluate_event_post_on_bars(
            bars,
            panel.get("fins_events") or {},
            post_hold_days=int(p.get("post_hold_days") or 5),
            one_way_cost=one_way_cost,
            period_start=panel.get("period_start"),
            period_end=panel.get("period_end"),
            entry_mode=str(p.get("entry_mode") or "same_day_close_if_pre_close"),
        )
    elif fid == CLASS_FUNDAMENTALS_PRICE:
        out = evaluate_fundamentals_price_on_bars(
            bars,
            panel.get("fins_events") or {},
            hold_days=int(p.get("hold_days") or 10),
            momentum_n=int(p.get("momentum_n") or 10),
            one_way_cost=one_way_cost,
            mode=str(p.get("mode") or "value_momentum_agree"),
        )
    elif fid == CLASS_FLOW_DEMAND:
        out = evaluate_flow_demand_on_bars(
            bars,
            panel.get("margin") or {},
            panel.get("short_series"),
            hold_days=int(p.get("hold_days") or 5),
            one_way_cost=one_way_cost,
            require_short_confirm=bool(p.get("require_short_confirm") or False),
            short_confirm_mode=str(p.get("short_confirm_mode") or "off"),
        )
    elif fid == FAMILY_VOL_RISK_ADJUSTED:
        out = evaluate_vol_risk_adjusted_on_bars(
            bars,
            hold_days=int(p.get("hold_days") or 5),
            vol_n=int(p.get("vol_n") or 10),
            vol_threshold=float(p.get("vol_threshold") or 1.0),
            one_way_cost=one_way_cost,
            gate_mode=str(p.get("gate_mode") or "mom_over_vol"),
        )
    elif fid == FAMILY_INDEX_VOL_REGIME:
        mode = str(p.get("mode") or "nky_vol_abs_level")
        nky = panel.get("nky_vol_series")
        common_kw = dict(
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 10),
            long_frac=float(p.get("long_frac") or 0.3),
            short_frac=float(p.get("short_frac") or 0.3),
            one_way_cost=one_way_cost,
        )
        if mode == "nky_vol_term_ratio":
            out = evaluate_nky_vol_term_ratio_on_bars(
                bars,
                nky,
                expand_ratio=float(p.get("expand_ratio") or 1.20),
                compress_ratio=float(p.get("compress_ratio") or 0.80),
                **common_kw,
            )
        elif mode == "nky_vol_term_levels":
            out = evaluate_nky_vol_term_levels_on_bars(
                bars,
                nky,
                high_threshold=float(p.get("high_threshold") or 0.20),
                low_threshold=float(p.get("low_threshold") or 0.10),
                **common_kw,
            )
        else:
            out = evaluate_nky_vol_abs_level_on_bars(
                bars,
                nky,
                high_threshold=float(p.get("high_threshold") or 0.20),
                low_threshold=float(p.get("low_threshold") or 0.10),
                **common_kw,
            )
    else:
        return {
            "status": "error",
            "skip_reason": f"unknown_family:{fid}",
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
        }

    return {
        "status": "ok",
        "gross_signed_mean_active": out.get("gross_signed_mean_active"),
        "net_one_way_mean_active": out.get("net_one_way_mean_active"),
        "amortized_one_way_cost": out.get("amortized_one_way_cost")
        or out.get("one_way_cost"),
        "n_active_positions": out.get("n_active_positions"),
        "occurrence": out.get("occurrence"),
        "signal_id": out.get("signal_id"),
        "hold_days": out.get("hold_days") or out.get("hold_days_documented"),
    }


def _evaluate_mdh_polarity_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int,
    one_way_cost: float,
    rebalance_mode: str,
    polarity: int,
    momentum_series_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Multi-day hold with explicit entry polarity (reversion when −1)."""
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    pol = -1.0 if int(polarity) < 0 else 1.0

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        moms = momentum_series_fn(pairs_l, n=h)
        entry_signs = []
        for _, m in moms:
            s = sign_from_numeric(m)
            if s is None:
                entry_signs.append(None)
            else:
                entry_signs.append(float(s) * pol)
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode=rebalance_mode
        )
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        for i, pos in enumerate(held):
            holding_records.append({"date": dates[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if rebalance_mode == "fixed_horizon" and i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    return {
        "signal_id": "c21_multi_day_hold_reversion",
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "hold_days": h,
        "signal_polarity": int(polarity),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "occurrence": {
            "activation_rate": (
                float(n_active) / float(n_code_days) if n_code_days else None
            ),
            "n_active": n_active,
        },
        **_freeze(),
        "note": "Mean-reversion entry polarity=-1. Not eval sign flip. Not READY.",
    }


def evaluate_one_strategy(
    strategy: Mapping[str, Any],
    ctx: BatchDataContext,
    *,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS,
    min_activation: float = DEFAULT_MIN_ACTIVATION,
) -> dict[str, Any]:
    """Evaluate one strategy across all periods; both signs after cost."""
    sid = str(strategy.get("strategy_id") or "")
    family = str(strategy.get("family_id") or "")
    params = dict(strategy.get("params") or {})
    logic_id = str(strategy.get("logic_id") or "")
    period_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for panel in ctx.panels:
        pid = str(panel.get("period_id") or "")
        if panel.get("status") not in {"ok", None} and not panel.get("bars"):
            period_rows.append(
                {
                    "period_id": pid,
                    "status": "data_missing",
                    "gross_signed_mean_active": None,
                    "net_one_way_mean_active": None,
                }
            )
            continue
        try:
            ev = _eval_on_panel(
                family, params, panel, one_way_cost=ctx.one_way_cost
            )
            row = {
                "period_id": pid,
                "year": panel.get("year"),
                **ev,
            }
            period_rows.append(row)
        except Exception as exc:
            errors.append(f"{pid}:{type(exc).__name__}:{exc}")
            period_rows.append(
                {
                    "period_id": pid,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "gross_signed_mean_active": None,
                    "net_one_way_mean_active": None,
                }
            )

    ok_rows = [r for r in period_rows if r.get("status") == "ok"]
    grosses = [r.get("gross_signed_mean_active") for r in ok_rows]
    nets = [r.get("net_one_way_mean_active") for r in ok_rows]
    costs = [r.get("amortized_one_way_cost") for r in ok_rows]
    pids = [str(r.get("period_id")) for r in ok_rows]
    hold = None
    for r in ok_rows:
        if r.get("hold_days") is not None:
            hold = int(r["hold_days"])
            break

    act_rates: list[float] = []
    for r in ok_rows:
        occ = r.get("occurrence") or {}
        ar = occ.get("activation_rate")
        if ar is not None:
            try:
                act_rates.append(float(ar))
            except (TypeError, ValueError):
                pass
    mean_activation = sample_mean(act_rates)

    both = evaluate_sign_both_sides(
        period_grosses=grosses,
        period_nets=nets,
        amortized_costs=costs if any(c is not None for c in costs) else None,
        period_ids=pids,
        hold_days=hold,
        near_zero_abs=near_zero_abs,
    )
    choice = choose_sign(both, near_zero_abs=near_zero_abs)
    chosen_sign = choice.get("chosen_sign")
    side_key = (
        "original"
        if chosen_sign == SIGN_ORIGINAL
        else ("inverted" if chosen_sign == SIGN_INVERTED else "original")
    )
    side = dict(both.get(side_key) or {})
    side_nets = list(side.get("nets") or nets)
    stats = period_stats_report(side_nets)
    mean_net = side.get("mean_net")
    if mean_net is None:
        mean_net = sample_mean(nets)
    mean_gross = sample_mean(grosses)
    t_stat = side.get("t_stat")
    if t_stat is None:
        t_stat = t_stat_vs_zero(side_nets)

    return {
        "strategy_id": sid,
        "logic_id": logic_id,
        "logic_fingerprint": strategy.get("logic_fingerprint"),
        "thesis": strategy.get("thesis"),
        "family_id": family,
        "params": params,
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "sharpe_period": stats.get("sharpe"),
        "win_rate": stats.get("win_rate"),
        "n_positive_periods": stats.get("n_positive"),
        "mean_activation": mean_activation,
        "sign_selection": {
            "chosen_sign": chosen_sign,
            "decision": choice.get("decision"),
            "reason": choice.get("reason"),
            "original_mean_net": (both.get("original") or {}).get("mean_net"),
            "inverted_mean_net": (both.get("inverted") or {}).get("mean_net"),
        },
        "chosen_sign": chosen_sign,
        "period_stats": stats,
        "errors": errors,
        "status": "evaluated",
        **_freeze(),
    }


def screen_strategy_result(
    result: Mapping[str, Any],
    *,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS,
    min_activation: float = DEFAULT_MIN_ACTIVATION,
) -> dict[str, Any]:
    """Auto-reject near-zero / data missing / post-cost collapse / both-sign fail."""
    reasons: list[str] = []
    n_ok = int(result.get("n_periods_ok") or 0)
    if n_ok <= 0:
        reasons.append(SCREEN_NO_PERIODS)
    period_rows = list(result.get("period_rows") or [])
    if any(r.get("status") == "data_missing" for r in period_rows) and n_ok == 0:
        reasons.append(SCREEN_DATA_MISSING)
    if result.get("errors"):
        if n_ok == 0:
            reasons.append(SCREEN_EVAL_ERROR)

    mean_gross = result.get("mean_gross")
    mean_net = result.get("mean_net")
    if mean_gross is not None and mean_net is not None:
        try:
            g, n = float(mean_gross), float(mean_net)
            if abs(g) >= near_zero_abs and abs(n) < near_zero_abs:
                reasons.append(SCREEN_POST_COST_COLLAPSE)
            if g > near_zero_abs and n < -near_zero_abs and (g - n) > abs(g):
                if SCREEN_POST_COST_COLLAPSE not in reasons:
                    reasons.append(SCREEN_POST_COST_COLLAPSE)
        except (TypeError, ValueError):
            pass

    if mean_net is not None:
        try:
            if abs(float(mean_net)) < near_zero_abs:
                reasons.append(SCREEN_NEAR_ZERO)
        except (TypeError, ValueError):
            pass
    else:
        if n_ok > 0:
            reasons.append(SCREEN_NEAR_ZERO)

    ss = dict(result.get("sign_selection") or {})
    if ss.get("decision") in {"reject", "explore_demote"} or ss.get("chosen_sign") is None:
        if n_ok > 0:
            reasons.append(SCREEN_BOTH_SIGNS_FAIL)

    act = result.get("mean_activation")
    if act is not None:
        try:
            if float(act) < float(min_activation) and n_ok > 0:
                reasons.append(SCREEN_LOW_ACTIVATION)
        except (TypeError, ValueError):
            pass

    seen: set[str] = set()
    uniq: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)

    survived = len(uniq) == 0 and n_ok > 0
    return {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id"),
        "survived": survived,
        "reject_reasons": uniq,
        "mean_net": mean_net,
        "mean_gross": mean_gross,
        "t_stat": result.get("t_stat"),
        "sharpe_period": result.get("sharpe_period"),
        "chosen_sign": result.get("chosen_sign"),
        "mean_activation": act,
        "n_periods_ok": n_ok,
    }


def run_batch_eval(
    generation: Mapping[str, Any],
    *,
    config: MassFactoryConfig | None = None,
    ctx: BatchDataContext | None = None,
    synthetic: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Batch-evaluate distinct logics (after dedup); fail-one-continue.

    Does **not** pick human main candidates. continuous paper UNARMED.
    Does **not** retune frozen default-path representatives.
    """
    t0 = time.perf_counter()
    cfg = config or MassFactoryConfig(
        seed=int((generation.get("config") or {}).get("seed") or DEFAULT_SEED),
        n=int(generation.get("n_requested") or DEFAULT_N),
    )
    if ctx is None:
        ctx = load_batch_data_context(cfg, synthetic=synthetic)

    # Prefer after-dedup strategies (distinct logics)
    if cfg.eval_after_dedup and generation.get("strategies_after_dedup"):
        strategies = list(generation.get("strategies_after_dedup") or [])
        eval_set = "after_dedup"
    else:
        strategies = list(generation.get("strategies") or [])
        eval_set = "generated_all"

    results: list[dict[str, Any]] = []
    screens: list[dict[str, Any]] = []
    n_fail = 0
    n_ok_eval = 0

    for i, strat in enumerate(strategies):
        sid = str(strat.get("strategy_id") or f"idx{i}")
        if progress_cb is not None:
            progress_cb(i + 1, len(strategies), sid)
        try:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            n_ok_eval += 1
        except Exception as exc:
            n_fail += 1
            if not cfg.fail_one_continue:
                raise
            res = {
                "strategy_id": sid,
                "logic_id": strat.get("logic_id"),
                "family_id": strat.get("family_id"),
                "params": strat.get("params"),
                "status": "eval_error",
                "errors": [f"{type(exc).__name__}: {exc}"],
                "error_traceback": traceback.format_exc(limit=5),
                "n_periods_ok": 0,
                "n_periods_total": 0,
                "period_rows": [],
                "mean_gross": None,
                "mean_net": None,
                "t_stat": None,
                "sharpe_period": None,
                "chosen_sign": None,
                "sign_selection": {"decision": "reject", "reason": "eval_error"},
                **_freeze(),
            }
        scr = screen_strategy_result(
            res,
            near_zero_abs=cfg.near_zero_abs,
            min_activation=cfg.min_activation,
        )
        res["screen"] = scr
        results.append(res)
        screens.append(scr)

    survivors = [s for s in screens if s.get("survived")]
    rejected = [s for s in screens if not s.get("survived")]

    def _rank_key(s: Mapping[str, Any]) -> tuple[float, float]:
        t = s.get("t_stat")
        m = s.get("mean_net")
        tv = abs(float(t)) if t is not None and math.isfinite(float(t)) else -1.0
        mv = float(m) if m is not None and math.isfinite(float(m)) else -1e9
        return (tv, mv)

    survivors_ranked = sorted(survivors, key=_rank_key, reverse=True)

    by_family: dict[str, list[dict[str, Any]]] = {}
    by_logic: dict[str, list[dict[str, Any]]] = {}
    for s in survivors_ranked:
        by_family.setdefault(str(s.get("family_id")), []).append(dict(s))
        by_logic.setdefault(str(s.get("logic_id") or ""), []).append(dict(s))
    family_top: dict[str, list[dict[str, Any]]] = {
        f: rows[:3] for f, rows in sorted(by_family.items())
    }
    survivor_family_dist = {f: len(v) for f, v in by_family.items()}
    survivor_logic_dist = {k: len(v) for k, v in by_logic.items() if k}

    reason_hist: dict[str, int] = {}
    for s in rejected:
        for r in s.get("reject_reasons") or ["unspecified"]:
            reason_hist[str(r)] = reason_hist.get(str(r), 0) + 1

    wall = time.perf_counter() - t0
    ranking = [
        {
            "rank": i + 1,
            "strategy_id": s.get("strategy_id"),
            "logic_id": s.get("logic_id"),
            "family_id": s.get("family_id"),
            "mean_net": s.get("mean_net"),
            "t_stat": s.get("t_stat"),
            "sharpe_period": s.get("sharpe_period"),
            "chosen_sign": s.get("chosen_sign"),
            "mean_activation": s.get("mean_activation"),
        }
        for i, s in enumerate(survivors_ranked)
    ]

    paper_note = {
        "continuous_paper": CONTINUOUS_PAPER,
        "paper_sample_k": int(cfg.paper_sample_k),
        "paper_ran": False,
        "note": (
            "Optional short paper only for sample subset (top-k); "
            "not full papers. continuous paper UNARMED this wave."
        ),
    }
    if cfg.paper_sample_k > 0 and survivors_ranked:
        paper_note["sample_ids"] = [
            s.get("strategy_id") for s in survivors_ranked[: cfg.paper_sample_k]
        ]
        paper_note["note"] += " Sample ids recorded only; paper runner not armed."

    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "config": cfg.to_dict(),
        "data_load_notes": ctx.load_notes,
        "eval_set": eval_set,
        "n_strategies_evaluated": len(strategies),
        "n_eval_ok": n_ok_eval,
        "n_eval_fail": n_fail,
        "fail_rate": (n_fail / len(strategies)) if strategies else 0.0,
        "n_survivors": len(survivors),
        "n_screen_rejected": len(rejected),
        "wall_time_sec": round(wall, 3),
        "n_generated": generation.get("n_generated")
        or generation.get("n_generated_accepted"),
        "n_unique_logic": generation.get("n_unique_logic"),
        "n_after_dedup": generation.get("n_after_dedup"),
        "n_numeric_variant": generation.get("n_numeric_variant"),
        "n_ge_100_generated": bool(generation.get("n_ge_100")),
        "n_generated_accepted": generation.get("n_generated_accepted"),
        "generation_family_distribution": generation.get("family_distribution"),
        "generation_logic_distribution": generation.get("logic_distribution"),
        "survivor_family_distribution": survivor_family_dist,
        "survivor_logic_distribution": survivor_logic_dist,
        "family_top_survivors": family_top,
        "ranking": ranking,
        "reject_reason_histogram": reason_hist,
        "screens": screens,
        "results": results,
        "paper": paper_note,
        "human_main_candidates_selected": False,
        "frozen_default_path": list(FROZEN_DEFAULT_PATH),
        "frozen_defaults_retuned": False,
        "note": (
            "Auto screen on distinct logics only (after near-dup). "
            "Do NOT treat survivors as human main candidates or "
            "research_candidate production defaults. "
            "3 frozen defaults untouched. Mass/READY/ops GO remain closed."
        ),
        **_freeze(),
    }


def run_mass_factory(
    *,
    seed: int = DEFAULT_SEED,
    n: int = DEFAULT_N,
    family_ratios: Mapping[str, float] | None = None,
    synthetic: bool = False,
    config: MassFactoryConfig | None = None,
    out_dir: str | Path | None = None,
    progress: bool = False,
) -> dict[str, Any]:
    """End-to-end: generate logics → near-dup → batch eval → screen."""
    cfg = config or MassFactoryConfig(
        seed=seed,
        n=n,
        family_ratios=dict(family_ratios or DEFAULT_FAMILY_RATIOS),
    )
    if config is None and (
        seed != DEFAULT_SEED or n != DEFAULT_N or family_ratios is not None
    ):
        cfg = MassFactoryConfig(
            seed=int(seed),
            n=int(n),
            family_ratios=dict(family_ratios or cfg.family_ratios),
            max_family_share=cfg.max_family_share,
            one_way_cost=cfg.one_way_cost,
            available_datasets=cfg.available_datasets,
            max_days_per_period=cfg.max_days_per_period,
            max_codes=cfg.max_codes,
            use_q4_periods=cfg.use_q4_periods,
            paper_sample_k=cfg.paper_sample_k,
            near_zero_abs=cfg.near_zero_abs,
            min_activation=cfg.min_activation,
            fail_one_continue=cfg.fail_one_continue,
            allow_numeric_variants=cfg.allow_numeric_variants,
            near_dup_threshold=cfg.near_dup_threshold,
            eval_after_dedup=cfg.eval_after_dedup,
        )

    t0 = time.perf_counter()
    gen = generate_strategy_batch(cfg)
    ctx = load_batch_data_context(cfg, synthetic=synthetic)

    def _cb(i: int, total: int, sid: str) -> None:
        if progress and (i == 1 or i == total or i % 5 == 0):
            print(f"[mass-factory] eval {i}/{total} {sid}", flush=True)

    batch = run_batch_eval(
        gen,
        config=cfg,
        ctx=ctx,
        synthetic=synthetic,
        progress_cb=_cb if progress else None,
    )
    wall = time.perf_counter() - t0

    pack = {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "wall_time_sec_total": round(wall, 3),
        "generation": {
            k: gen[k]
            for k in gen
            if k
            not in {
                "strategies",
                "strategies_after_dedup",
                "near_dup_dropped",
                "gen_rejected",
                "families_document",
                "logic_templates_document",
            }
        },
        "generation_strategies": gen.get("strategies"),
        "strategies_after_dedup": gen.get("strategies_after_dedup"),
        "near_dup_dropped": gen.get("near_dup_dropped"),
        "generation_rejected": gen.get("gen_rejected"),
        "families": family_definitions_document(),
        "logic_templates": logic_templates_document(),
        "batch": {
            k: batch[k] for k in batch if k not in {"results", "screens"}
        },
        "batch_ranking": batch.get("ranking"),
        "batch_screens": batch.get("screens"),
        "batch_results": batch.get("results"),
        "summary": {
            "n_requested": gen.get("n_requested"),
            "n_generated": gen.get("n_generated"),
            "n_generated_accepted": gen.get("n_generated_accepted"),
            "n_unique_logic": gen.get("n_unique_logic"),
            "n_numeric_variant": gen.get("n_numeric_variant"),
            "n_after_dedup": gen.get("n_after_dedup"),
            "n_dropped_near_dup": gen.get("n_dropped_near_dup"),
            "unique_logic_ids": gen.get("unique_logic_ids"),
            "logic_distribution": gen.get("logic_distribution"),
            "logic_diversity_ok": gen.get("logic_diversity_ok"),
            "n_ge_100": gen.get("n_ge_100"),
            "n_families_used": gen.get("n_families_used"),
            "anti_bias_ok": gen.get("anti_bias_ok"),
            "family_distribution": gen.get("family_distribution"),
            "n_survivors": batch.get("n_survivors"),
            "n_strategies_evaluated": batch.get("n_strategies_evaluated"),
            "eval_set": batch.get("eval_set"),
            "fail_rate": batch.get("fail_rate"),
            "wall_time_sec": round(wall, 3),
            "survivor_family_distribution": batch.get(
                "survivor_family_distribution"
            ),
            "survivor_logic_distribution": batch.get(
                "survivor_logic_distribution"
            ),
            "top5": (batch.get("ranking") or [])[:5],
            "human_main_candidates_selected": False,
            "continuous_paper": CONTINUOUS_PAPER,
            "frozen_defaults_retuned": False,
        },
        **_freeze(),
    }

    if out_dir is not None:
        write_factory_outputs(pack, out_dir)

    return pack


def write_factory_outputs(
    pack: Mapping[str, Any], out_dir: str | Path
) -> dict[str, str]:
    """Write machine-readable factory outputs under out_dir."""
    od = Path(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    def _w(name: str, obj: Any) -> None:
        p = od / name
        p.write_text(
            json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8"
        )
        paths[name] = str(p)

    _w("factory_run.json", pack)
    _w(
        "generation_summary.json",
        {
            "summary": pack.get("summary"),
            "generation": pack.get("generation"),
            "family_distribution": (pack.get("summary") or {}).get(
                "family_distribution"
            ),
            "logic_distribution": (pack.get("summary") or {}).get(
                "logic_distribution"
            ),
            "n_unique_logic": (pack.get("summary") or {}).get("n_unique_logic"),
            "n_after_dedup": (pack.get("summary") or {}).get("n_after_dedup"),
            "n_numeric_variant": (pack.get("summary") or {}).get(
                "n_numeric_variant"
            ),
        },
    )
    _w("strategies.json", pack.get("generation_strategies") or [])
    _w("strategies_after_dedup.json", pack.get("strategies_after_dedup") or [])
    _w("near_dup_dropped.json", pack.get("near_dup_dropped") or [])
    _w("ranking.json", pack.get("batch_ranking") or [])
    _w(
        "screens.json",
        {
            "screens": pack.get("batch_screens") or [],
            "reject_reason_histogram": (pack.get("batch") or {}).get(
                "reject_reason_histogram"
            ),
            "survivor_family_distribution": (pack.get("batch") or {}).get(
                "survivor_family_distribution"
            ),
            "survivor_logic_distribution": (pack.get("batch") or {}).get(
                "survivor_logic_distribution"
            ),
            "family_top_survivors": (pack.get("batch") or {}).get(
                "family_top_survivors"
            ),
        },
    )
    compact_results = []
    for r in pack.get("batch_results") or []:
        compact_results.append(
            {
                k: r.get(k)
                for k in (
                    "strategy_id",
                    "logic_id",
                    "logic_fingerprint",
                    "thesis",
                    "family_id",
                    "params",
                    "n_periods_ok",
                    "mean_gross",
                    "mean_net",
                    "t_stat",
                    "sharpe_period",
                    "win_rate",
                    "mean_activation",
                    "chosen_sign",
                    "sign_selection",
                    "screen",
                    "status",
                    "errors",
                )
            }
        )
    _w("results_compact.json", compact_results)
    _w("families.json", pack.get("families") or family_definitions_document())
    _w(
        "logic_templates.json",
        pack.get("logic_templates") or logic_templates_document(),
    )
    _w("frozen_defaults.json", list(FROZEN_DEFAULT_PATH))

    sm = pack.get("summary") or {}
    lines = [
        f"# Mass strategy logic-diversity factory run — {MASS_FACTORY_WAVE}",
        "",
        f"- version: `{MASS_FACTORY_VERSION}`",
        f"- n_requested: **{sm.get('n_requested')}**",
        f"- n_generated: **{sm.get('n_generated')}**",
        f"- n_unique_logic: **{sm.get('n_unique_logic')}**",
        f"- n_numeric_variant: **{sm.get('n_numeric_variant')}**",
        f"- n_after_dedup: **{sm.get('n_after_dedup')}**",
        f"- n_dropped_near_dup: **{sm.get('n_dropped_near_dup')}**",
        f"- logic_diversity_ok: **{sm.get('logic_diversity_ok')}**",
        f"- n_families_used: **{sm.get('n_families_used')}**",
        f"- n_strategies_evaluated: **{sm.get('n_strategies_evaluated')}** "
        f"(eval_set={sm.get('eval_set')})",
        f"- n_survivors: **{sm.get('n_survivors')}**",
        f"- fail_rate: **{sm.get('fail_rate')}**",
        f"- wall_time_sec: **{sm.get('wall_time_sec')}**",
        f"- continuous_paper: **{sm.get('continuous_paper')}**",
        f"- frozen_defaults_retuned: **{sm.get('frozen_defaults_retuned')}**",
        f"- human_main_candidates_selected: **{sm.get('human_main_candidates_selected')}**",
        f"- mass_research: **{MASS_RESEARCH}** · READY: **{READY_DECLARED}** · "
        f"ops GO: **{OPERATIONAL_GO}**",
        "",
        "## Logic distribution (generated)",
        "",
        "```json",
        json.dumps(sm.get("logic_distribution") or {}, indent=2),
        "```",
        "",
        "## Family distribution (generated)",
        "",
        "```json",
        json.dumps(sm.get("family_distribution") or {}, indent=2),
        "```",
        "",
        "## Survivor logic distribution",
        "",
        "```json",
        json.dumps(sm.get("survivor_logic_distribution") or {}, indent=2),
        "```",
        "",
        "## Top 5 (research ranking only — not human main candidates)",
        "",
    ]
    for row in sm.get("top5") or []:
        lines.append(
            f"- rank {row.get('rank')}: `{row.get('strategy_id')}` "
            f"logic={row.get('logic_id')} family={row.get('family_id')} "
            f"mean_net={row.get('mean_net')} t={row.get('t_stat')} "
            f"sign={row.get('chosen_sign')}"
        )
    lines.extend(
        [
            "",
            "## Frozen defaults (not retuned)",
            "",
            "```json",
            json.dumps(
                [r["representative_id"] for r in FROZEN_DEFAULT_PATH], indent=2
            ),
            "```",
            "",
            "## Re-run recipe",
            "",
            "```bash",
            "python scripts/run_mass_strategy_batch.py --seed 870816 --n 100 \\",
            "  --out-dir .glm-logs/w0816x_w89_rate_mf/",
            "```",
            "",
            "Synthetic (tests / no mirrors):",
            "",
            "```bash",
            "python scripts/run_mass_strategy_batch.py --synthetic --n 100 "
            "--out-dir /tmp/msf",
            "```",
            "",
        ]
    )
    md_path = od / "SUMMARY.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["SUMMARY.md"] = str(md_path)
    return paths


# ---------------------------------------------------------------------------
# CF minimal path (honest blocker if no mass-factory CF job)
# ---------------------------------------------------------------------------


def try_cf_minimal_mass_batch() -> dict[str, Any]:
    """Prefer a stable minimal CF job returning one small batch result.

    Status
    ------
    **W90 / w0816y:** CF worker ``quant-platform-research-mass-eval`` exists
    under ``platform/workers/research-mass-eval/`` with
    ``POST /v1/mass-eval`` → R2 ``research/mass_eval/job={id}/``.

    Pure-TS lite multi-period path (synthetic / r2_panels / nets_only).
    Full rate/mf factor legs on CF remain **not-yet-implemented** (fallback
    multi_day_hold or nets_only). Local ``run_mass_factory`` remains the
    full-factory path. Scaling to 200/500 queue fan-out is not-yet-implemented.
    """
    return {
        "status": "available",
        "wave": "W90 / w0816y",
        "version": "research-mass-eval/v1",
        "factory_wave": MASS_FACTORY_WAVE,
        "factory_version": MASS_FACTORY_VERSION,
        # Primary W90 task path: POST /v1/mass-eval → research/mass_eval/job=
        "worker": "quant-platform-research-mass-eval",
        "worker_path": "platform/workers/research-mass-eval/",
        "endpoint": "POST /v1/mass-eval",
        "request_shape": {
            "seed": "int",
            "logics": "list[{logic_id, family_id?, params?, thesis?}]",
            "periods": "list[{period_id, year?}]",
            "job_id": "str",
            "mode": "synthetic | r2_panels | nets_only",
        },
        "r2_prefix": "research/mass_eval/job={id}/",
        "r2_bucket": "quant-structured",
        # Parallel W90 track (D1 tip bars + research/mass_factory/):
        "alt_worker": "quant-platform-mass-eval",
        "alt_worker_path": "platform/workers/mass-eval/",
        "alt_endpoint": "POST /v1/research/mass_eval",
        "alt_r2_prefix": "research/mass_factory/job={id}/",
        "existing_cf_paths": [
            "platform/workers/research-mass-eval (POST /v1/mass-eval → research/mass_eval/)",
            "platform/workers/mass-eval (POST /v1/research/mass_eval → research/mass_factory/)",
            "research.single_shot_job.execute_single_shot_job",
            "research.single_shot_job.execute_multiday_signal_eval",
            "packages/edge/cf_platform (ingestion / ops)",
        ],
        "supported_path_cf": (
            "wrangler deploy platform/workers/research-mass-eval && "
            "POST /v1/mass-eval"
        ),
        "supported_path_local": (
            "local run_mass_factory / scripts/run_mass_strategy_batch.py"
        ),
        "python_driver": "research.cf_mass_eval_job (alt mass-eval worker driver)",
        "not_yet_implemented": [
            "full rate/mf factor legs on pure-TS CF path",
            "direct structured/jsonl historical bar load",
            "queue/DO fan-out for 200-500 logics",
        ],
        "scale_queue_fanout": False,
        "n_cf_batch_cap": 200,
        **_freeze(),
    }


def _is_window_tweak_only(proposal: Mapping[str, Any]) -> bool:
    """True when proposal only mutates hold/mom/frac without new thesis/signal."""
    thesis = str(proposal.get("thesis") or "").strip()
    signal = str(
        proposal.get("signal_definition") or proposal.get("signal") or ""
    ).strip()
    position = str(
        proposal.get("position_rule") or proposal.get("position") or ""
    ).strip()
    if not thesis or not signal or not position:
        return True
    # Explicit window-tweak: same catalog logic_id + only numeric knobs
    # (hold/mom/frac) without structural mode / new signal.
    structural = (
        proposal.get("structural_keys")
        or proposal.get("mode")
        or (proposal.get("params") or {}).get("mode")
    )
    params = dict(proposal.get("params") or {})
    only_numeric = (
        bool(params)
        and set(params.keys()) <= NUMERIC_ONLY_KNOBS
        and not structural
    )
    if only_numeric and str(proposal.get("logic_id") or "") in LOGIC_TEMPLATES:
        # same logic_id + only numeric overrides → window tweak
        return True
    tweak_words = ("window", "hold_days only", "mom only", "frac only")
    blob = f"{thesis} {signal}".lower()
    if any(w in blob for w in tweak_words) and "factor" not in blob:
        if not proposal.get("datasets") and not proposal.get("datasets_used"):
            return True
    return False


def propose_profit_hypotheses(
    proposals: Sequence[Mapping[str, Any]],
    *,
    evaluate: bool = True,
    synthetic: bool = False,
    config: MassFactoryConfig | None = None,
    ctx: BatchDataContext | None = None,
) -> dict[str, Any]:
    """Entry for **different profit hypotheses** (not window tweaks).

    Programmatic / LLM-agent hook: each proposal must carry thesis, signal
    definition, position rule, and datasets. Window-tweak-only proposals are
    rejected at entry. Accepted proposals map to catalog logic templates when
    ``logic_id`` matches, else ad-hoc individuals. When ``evaluate=True``,
    **always** routes through the factory evaluator (PIT + cost).

    Does not arm Mass / READY / GO / continuous paper.
    """
    cfg = config or MassFactoryConfig(seed=DEFAULT_SEED, n=max(20, len(proposals) + 5))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for i, raw in enumerate(proposals):
        prop = dict(raw or {})
        if _is_window_tweak_only(prop):
            rejected.append(
                {
                    "index": i,
                    "proposal": prop,
                    "reject_reason": "window_tweak_only_forbidden",
                    "note": (
                        "Proposals must change economic thesis / signal / "
                        "position / datasets — not hold/mom/frac windows only."
                    ),
                }
            )
            continue
        logic_id = str(prop.get("logic_id") or "").strip()
        if logic_id and logic_id in LOGIC_TEMPLATES:
            tpl = LOGIC_TEMPLATES[logic_id]
            params = dict(tpl.base_params)
            params.update(dict(prop.get("params") or {}))
            ok, reason = validate_strategy_at_gen(
                tpl.family_id,
                params,
                available_datasets=cfg.available_datasets,
                logic_id=logic_id,
            )
            if not ok:
                rejected.append(
                    {
                        "index": i,
                        "proposal": prop,
                        "reject_reason": reason,
                    }
                )
                continue
            ind = {
                "strategy_id": stable_strategy_id(
                    seed=cfg.seed,
                    family_id=tpl.family_id,
                    params=params,
                    generation_index=i,
                    logic_id=logic_id,
                ),
                "logic_id": logic_id,
                "logic_fingerprint": tpl.logic_fingerprint(),
                "thesis": str(prop.get("thesis") or tpl.thesis),
                "signal_definition": str(
                    prop.get("signal_definition") or tpl.signal_definition
                ),
                "position_rule": str(
                    prop.get("position_rule") or tpl.position_rule
                ),
                "datasets_used": list(
                    prop.get("datasets_used")
                    or prop.get("datasets")
                    or tpl.datasets_used
                ),
                "datasets_required": list(tpl.datasets_used),
                "family_id": tpl.family_id,
                "params": params,
                "status": "accepted",
                "source": "profit_hypothesis_entry",
                "generation_index": i,
                "seed": cfg.seed,
            }
            accepted.append(ind)
        else:
            # Ad-hoc: require family_id + full thesis fields
            family = str(
                prop.get("family_id") or prop.get("family") or ""
            ).strip()
            if not family:
                rejected.append(
                    {
                        "index": i,
                        "proposal": prop,
                        "reject_reason": "missing_logic_id_or_family",
                    }
                )
                continue
            params = dict(prop.get("params") or {})
            ind = {
                "strategy_id": stable_strategy_id(
                    seed=cfg.seed,
                    family_id=family,
                    params=params,
                    generation_index=i,
                    logic_id=logic_id or f"adhoc_{i}",
                ),
                "logic_id": logic_id or f"adhoc_{i}",
                "logic_fingerprint": hashlib.sha256(
                    json.dumps(
                        {
                            "thesis": prop.get("thesis"),
                            "signal": prop.get("signal_definition"),
                            "position": prop.get("position_rule"),
                            "family": family,
                        },
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:16],
                "thesis": str(prop.get("thesis") or ""),
                "signal_definition": str(
                    prop.get("signal_definition") or prop.get("signal") or ""
                ),
                "position_rule": str(
                    prop.get("position_rule") or prop.get("position") or ""
                ),
                "datasets_used": list(
                    prop.get("datasets_used") or prop.get("datasets") or []
                ),
                "datasets_required": list(
                    prop.get("datasets_used") or prop.get("datasets") or []
                ),
                "family_id": family,
                "params": params,
                "status": "accepted",
                "source": "profit_hypothesis_entry_adhoc",
                "generation_index": i,
                "seed": cfg.seed,
            }
            accepted.append(ind)

    out: dict[str, Any] = {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "entry": "propose_profit_hypotheses",
        "n_proposals": len(proposals),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
        "always_through_evaluator": bool(evaluate),
        "window_tweaks_forbidden": True,
        **_freeze(),
    }
    if evaluate and accepted:
        gen = {
            "strategies_after_dedup": accepted,
            "strategies": accepted,
            "n_generated": len(accepted),
            "n_unique_logic": len({a["logic_id"] for a in accepted}),
            "n_after_dedup": len(accepted),
            "n_numeric_variant": 0,
            "n_requested": len(accepted),
            "config": cfg.to_dict(),
        }
        batch = run_batch_eval(
            gen, config=cfg, ctx=ctx, synthetic=synthetic
        )
        out["eval"] = {
            k: batch[k]
            for k in batch
            if k not in {"results", "screens"}
        }
        out["eval_screens"] = batch.get("screens")
        out["eval_ranking"] = batch.get("ranking")
        out["eval_results"] = batch.get("results")
    elif evaluate and not accepted:
        out["eval"] = {
            "n_strategies_evaluated": 0,
            "note": "no accepted proposals to evaluate",
        }
    return out


def llm_logic_entry_status() -> dict[str, Any]:
    """LLM / agent entry for different profit hypotheses (not window tweaks)."""
    return {
        "status": "connected",
        "wave": MASS_FACTORY_WAVE,
        "version": MASS_FACTORY_VERSION,
        "entry_fn": "research.mass_strategy_factory.propose_profit_hypotheses",
        "strong_model_entry": (
            "research.llm_hyp_generator.generate_profit_hypotheses_via_llm"
        ),
        "preferred_model": "grok-4.6 (xAI api.x.ai)",
        "fallback_model": "@cf/openai/gpt-oss-120b (Workers AI)",
        "declaration_helper": "research.idea_generator.generate_idea_payloads",
        "rules": {
            "require": [
                "thesis (what earns)",
                "signal_definition (entry structure)",
                "position_rule (book / hold construction)",
                "datasets (info source)",
            ],
            "forbid": [
                "hold/mom/frac window tweaks only",
                "sign flip as separate strategy",
                "simple_daily_sign mass",
            ],
            "always_through_evaluator": True,
            "prompt_guidance": (
                "Propose different economic profit hypotheses "
                "(info source / entry / position / thesis). "
                "Never propose window-only mutations. "
                "Every proposal is screened by the factory evaluator "
                "(PIT + cost + both signs)."
            ),
        },
        "catalog_logic_ids": list(LOGIC_TEMPLATE_IDS),
        "near_logic_groups": near_logic_groups_document(),
        "note": (
            "W90: strong-model path generate_profit_hypotheses_via_llm "
            "(xAI grok-4.6 preferred) → near-dup → propose_profit_hypotheses "
            "(always through evaluator). idea_generator remains ResearchIdea helper."
        ),
        "always_through_evaluator": True,
        **_freeze(),
    }


def mass_factory_document() -> dict[str, Any]:
    """Public document for the logic-diversity mass strategy factory."""
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "purpose": (
            "Generate distinct economic logic templates and batch-evaluate "
            "after near-dup (research factory). W90 adds strong-model hyp "
            "generation + CF multi-logic multi-period eval. W89 rate + "
            "multi-factor logics held. Not hold/mom/frac grid mass."
        ),
        "primary_metrics": [
            "n_generated",
            "n_unique_logic",
            "n_numeric_variant",
            "n_after_dedup",
        ],
        "logic_templates": logic_templates_document(),
        "near_logic_groups": near_logic_groups_document(),
        "families": family_definitions_document(),
        "default_config": MassFactoryConfig().to_dict(),
        "frozen_default_path": list(FROZEN_DEFAULT_PATH),
        "cf_minimal": try_cf_minimal_mass_batch(),
        "llm_entry": llm_logic_entry_status(),
        "profit_hypothesis_entry": "propose_profit_hypotheses",
        "not_goals": [
            "hold/mom/frac grid as 100 strategies",
            "retune 3 frozen defaults (mom5/mom3/fund)",
            "operational GO / Mass / READY / live",
            "simple_daily_sign mass as diversity",
            "S1–S5 un-reject",
            "human main candidate selection this wave",
            "CF 200/500 full multi-year scale",
            "merge near-groups early",
        ],
        "eval_tradeoffs": (
            "CF lite multi-period (bounded codes/days) via mass-eval Worker. "
            "Local wide eval after near-dup. Heavy multi-year only for "
            "promising survivors. Survivors need deeper class_hyp re-eval "
            "before promotion."
        ),
        "continuous_paper": CONTINUOUS_PAPER,
        **_freeze(),
        "proof": "docs/proof/w0816y_w90_llm_hyp_cf_mass_eval_20260817.md",
        "w91_index_vol": {
            "family": FAMILY_INDEX_VOL_REGIME,
            "logic_ids": [
                "nky_vol_abs_level",
                "nky_vol_term_levels",
                "nky_vol_term_ratio",
            ],
            "proxy": "NK225F front realized → TOPIX fallback; NKVIF available",
            "distinct_from": [
                "vol_risk_adjusted_mom",
                "vol_breakout_expand",
            ],
        },
    }


__all__ = [
    "MASS_FACTORY_VERSION",
    "MASS_FACTORY_WAVE",
    "MASS_RESEARCH",
    "PHASE7",
    "READY_DECLARED",
    "OPERATIONAL_GO",
    "CONTINUOUS_PAPER",
    "FAMILY_VOL_RISK_ADJUSTED",
    "FAMILY_RATE_FACTOR",
    "FAMILY_MULTI_FACTOR",
    "FAMILY_INDEX_VOL_REGIME",
    "FAMILY_DEFINITIONS",
    "FACTORY_FAMILY_IDS",
    "DEFAULT_FAMILY_RATIOS",
    "DEFAULT_SEED",
    "DEFAULT_N",
    "DEFAULT_NEAR_DUP_THRESHOLD",
    "DEFAULT_MAX_FAMILY_SHARE",
    "FROZEN_DEFAULT_PATH",
    "NEAR_LOGIC_GROUPS",
    "LOGIC_TEMPLATES",
    "LOGIC_TEMPLATE_IDS",
    "LogicTemplate",
    "MassFactoryConfig",
    "GeneratedStrategy",
    "BatchDataContext",
    "REJECT_SIMPLE_DAILY_SIGN",
    "REJECT_LOOKAHEAD",
    "REJECT_NEAR_DUPLICATE",
    "family_definitions_document",
    "logic_templates_document",
    "near_logic_groups_document",
    "mass_factory_document",
    "stable_strategy_id",
    "validate_strategy_at_gen",
    "generate_strategy_batch",
    "similarity_score",
    "dedup_strategies",
    "evaluate_vol_risk_adjusted_on_bars",
    "load_batch_data_context",
    "evaluate_one_strategy",
    "screen_strategy_result",
    "run_batch_eval",
    "propose_profit_hypotheses",
    "run_mass_factory",
    "write_factory_outputs",
    "try_cf_minimal_mass_batch",
    "llm_logic_entry_status",
]
