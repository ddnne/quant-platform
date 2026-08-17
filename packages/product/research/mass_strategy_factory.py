"""Mass strategy generation factory + batch auto-experiment (W87 / w0816v).

Purpose
-------
Stable factory that generates **100+ diverse strategy specs per run** across
multiple hypothesis **families**, then batch-evaluates them automatically
(post-cost, both signs when applicable, t/Sharpe/activation).

This is a **research factory**, not operational Mass / READY / live:

* Does **not** call ``agents.mass_research`` / arm Mass loop
* Does **not** mint READY / VerifiedResearchReadiness / operational GO
* Does **not** un-reject S1–S5 or use ``simple_daily_sign`` as diversity
* Does **not** flood one family with micro param grids (anti-bias)
* continuous paper remains **UNARMED** (optional short paper subset only)

Building blocks reused
----------------------
* ``hypothesis_classes`` — family ids / datasets / generation policy
* ``class_signals`` / ``class_hyp_eval`` — pure bar evaluators
* ``cost_models`` — one-way / amortized cost
* ``sign_selection`` — both sides after cost
* ``stats_metrics`` — period t / Sharpe / win-rate
* checklist v2 completeness is **not** auto-promoted to research_candidate
  for mass survivors (screening only; human main candidates deferred)

See: ``docs/proof/w0816v_w87_mass_strategy_factory_20260817.md``
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
    get_hypothesis_class,
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
    SUPPORTED_HOLD_DAYS,
    amortized_one_way_cost,
    apply_sticky_hold,
    multi_day_forward_return,
    sign_from_numeric,
)

# ---------------------------------------------------------------------------
# Identity / freezes (must never arm operational Mass)
# ---------------------------------------------------------------------------

MASS_FACTORY_VERSION: str = "mass-strategy-factory/v1"
MASS_FACTORY_WAVE: str = "W87 / w0816v"

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

# Optional family not in hypothesis_classes registry (pure price vol filter).
FAMILY_VOL_RISK_ADJUSTED: str = "vol_risk_adjusted"

# Gen-time reject reason codes
REJECT_SIMPLE_DAILY_SIGN: str = "simple_daily_sign_forbidden"
REJECT_LOOKAHEAD: str = "pit_lookahead_forbidden"
REJECT_MISSING_DATASETS: str = "required_datasets_unavailable"
REJECT_INVALID_PARAMS: str = "invalid_params"
REJECT_S1_S5: str = "s1_s5_unreject_forbidden"
REJECT_UNKNOWN_FAMILY: str = "unknown_family"

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
DEFAULT_N: int = 100
DEFAULT_NEAR_ZERO_ABS: float = 0.0005  # 5bp
DEFAULT_MIN_ACTIVATION: float = 0.01
DEFAULT_MAX_FAMILY_SHARE: float = 0.28  # anti-bias: no family > 28% of N
DEFAULT_ONE_WAY: float = DEFAULT_ONE_WAY_COST

# Default family ratios (direction diversity; sum ≈ 1.0)
DEFAULT_FAMILY_RATIOS: dict[str, float] = {
    CLASS_MULTI_DAY_HOLD: 0.16,
    CLASS_EVENT_POST: 0.14,
    CLASS_CROSS_SECTION_RELATIVE: 0.20,
    CLASS_MACRO_CONDITIONED: 0.14,
    CLASS_FUNDAMENTALS_PRICE: 0.14,
    CLASS_FLOW_DEMAND: 0.12,
    FAMILY_VOL_RISK_ADJUSTED: 0.10,
}

# Datasets the factory can satisfy offline (local mirrors + sqlite).
FACTORY_AVAILABLE_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily",
        "markets_calendar",
        "indices_bars_daily_topix",
        "indices_bars_daily",
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
    }


# ---------------------------------------------------------------------------
# Family definitions (direction + sampling rules)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FamilyDefinition:
    """One strategy family (direction) for mass generation."""

    family_id: str
    display_name: str
    description: str
    datasets_required: tuple[str, ...]
    # Distinct param axes used for diversity (not a single-axis mom grid).
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


FAMILY_DEFINITIONS: dict[str, FamilyDefinition] = {
    CLASS_MULTI_DAY_HOLD: FamilyDefinition(
        family_id=CLASS_MULTI_DAY_HOLD,
        display_name="Multi-day hold",
        description=(
            "Sticky multi-day momentum hold (not 1d flip). "
            "Axes: hold_days × rebalance_mode."
        ),
        datasets_required=(
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ),
        param_axes=("hold_days", "rebalance_mode"),
    ),
    CLASS_EVENT_POST: FamilyDefinition(
        family_id=CLASS_EVENT_POST,
        display_name="Post-event",
        description=(
            "Post-disclosure hold with PIT DiscDate+DiscTime entry only. "
            "Axes: post_hold_days × entry_mode (lookahead modes rejected)."
        ),
        datasets_required=(
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ),
        param_axes=("post_hold_days", "entry_mode"),
        notes="Look-ahead entry modes are gen-time rejected.",
    ),
    CLASS_CROSS_SECTION_RELATIVE: FamilyDefinition(
        family_id=CLASS_CROSS_SECTION_RELATIVE,
        display_name="Cross-section relative",
        description=(
            "Same-day rank L-S with optional sticky hold. "
            "Axes: hold_days × momentum_n × long_frac × short_frac "
            "(not mom-only microgrid)."
        ),
        datasets_required=(
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ),
        param_axes=("hold_days", "momentum_n", "long_frac", "short_frac"),
    ),
    CLASS_MACRO_CONDITIONED: FamilyDefinition(
        family_id=CLASS_MACRO_CONDITIONED,
        display_name="Macro-conditioned",
        description=(
            "Momentum conditioned on Tokyo repo regime. "
            "Axes: mode × momentum_n × hold_days × high/low thresholds."
        ),
        datasets_required=(
            "equities_bars_daily",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
            "indices_bars_daily_topix",
        ),
        param_axes=("mode", "momentum_n", "hold_days", "high_threshold", "low_threshold"),
    ),
    CLASS_FUNDAMENTALS_PRICE: FamilyDefinition(
        family_id=CLASS_FUNDAMENTALS_PRICE,
        display_name="Fundamentals vs price",
        description=(
            "PIT fundamentals × price (value / value×mom). "
            "Axes: hold_days × momentum_n × mode."
        ),
        datasets_required=(
            "fins_summary",
            "equities_bars_daily",
            "markets_calendar",
        ),
        param_axes=("hold_days", "momentum_n", "mode"),
    ),
    CLASS_FLOW_DEMAND: FamilyDefinition(
        family_id=CLASS_FLOW_DEMAND,
        display_name="Flow / demand",
        description=(
            "Multi-day margin flow pressure (not S4 daily). "
            "Axes: hold_days × short_confirm_mode."
        ),
        datasets_required=(
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ),
        param_axes=("hold_days", "short_confirm_mode"),
    ),
    FAMILY_VOL_RISK_ADJUSTED: FamilyDefinition(
        family_id=FAMILY_VOL_RISK_ADJUSTED,
        display_name="Vol / risk-adjusted",
        description=(
            "Multi-day momentum gated by realized-vol floor "
            "(enter only when |mom|/vol ≥ threshold). Pure bars; "
            "risk filter is the structural difference vs multi_day_hold."
        ),
        datasets_required=(
            "equities_bars_daily",
            "markets_calendar",
        ),
        param_axes=("hold_days", "vol_n", "vol_threshold"),
        notes="Research-only family; not in hypothesis_classes registry.",
    ),
}

FACTORY_FAMILY_IDS: tuple[str, ...] = tuple(FAMILY_DEFINITIONS.keys())


def family_definitions_document() -> dict[str, Any]:
    """Document families + sampling / anti-bias rules."""
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "families": {
            fid: FAMILY_DEFINITIONS[fid].to_dict() for fid in FACTORY_FAMILY_IDS
        },
        "family_ids": list(FACTORY_FAMILY_IDS),
        "default_family_ratios": dict(DEFAULT_FAMILY_RATIOS),
        "sampling_rules": {
            "seed_reproducible": True,
            "target_n_min": DEFAULT_N,
            "max_family_share": DEFAULT_MAX_FAMILY_SHARE,
            "anti_bias": (
                "No flooding one family with micro param grids "
                "(e.g. mom 3/4/5… alone as the 100). "
                "Batch must sample across multiple families; "
                "within family, multi-axis combinatorial slots "
                "cycled with seed, not sequential single-axis flood."
            ),
            "simple_daily_sign": "forbidden as diversity source",
            "s1_s5_unreject": "forbidden",
            "look_ahead": "gen-time reject",
            "gen_time_reject": [
                REJECT_SIMPLE_DAILY_SIGN,
                REJECT_LOOKAHEAD,
                REJECT_MISSING_DATASETS,
                REJECT_INVALID_PARAMS,
                REJECT_S1_S5,
                REJECT_UNKNOWN_FAMILY,
            ],
            "quality_filter_stage": "eval (not gen)",
        },
        "hypothesis_class_alignment": {
            "registry_default_generation": list(DEFAULT_GENERATION_CLASS_IDS),
            "extra_factory_families": [FAMILY_VOL_RISK_ADJUSTED],
            "excluded": [CLASS_SIMPLE_DAILY_SIGN],
        },
        **_freeze(),
    }


# ---------------------------------------------------------------------------
# Param catalogs (multi-axis; intentionally NOT a mom-only grid of 100)
# ---------------------------------------------------------------------------

# hold / horizon diversity
_HOLD_DAYS: tuple[int, ...] = (5, 10, 15, 20)
_MOM_N: tuple[int, ...] = (3, 5, 10, 20)  # used with hold/frac — not alone
_REBALANCE: tuple[str, ...] = ("fixed_horizon",)
_XS_LONG_FRAC: tuple[float, ...] = (0.2, 0.3, 0.4)
_XS_SHORT_FRAC: tuple[float, ...] = (0.2, 0.3, 0.4)
_MACRO_MODE: tuple[str, ...] = ("rate_change", "rate_level")
_MACRO_HIGH: tuple[float, ...] = (0.03, 0.05, 0.10)
_MACRO_LOW: tuple[float, ...] = (-0.02, 0.0, 0.02)
_EVENT_HOLD: tuple[int, ...] = (3, 5, 10, 20)
# Only PIT-safe entry mode is allowed; others exist for reject tests.
_EVENT_ENTRY_SAFE: tuple[str, ...] = ("same_day_close_if_pre_close",)
_EVENT_ENTRY_FORBIDDEN: frozenset[str] = frozenset(
    {
        "same_day_close_always",
        "pre_disclosure_close",
        "look_ahead_close",
        "event_open_before_disc",
    }
)
_FUND_MODE: tuple[str, ...] = ("value_momentum_agree", "value_only")
_FUND_HOLD: tuple[int, ...] = (5, 10, 15, 20)
_FUND_MOM: tuple[int, ...] = (5, 10, 20)
_FLOW_HOLD: tuple[int, ...] = (5, 10, 20)
_FLOW_CONFIRM: tuple[str, ...] = ("off", "soft", "hard")
_VOL_N: tuple[int, ...] = (5, 10, 20)
_VOL_THRESH: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)


def _param_slots_for_family(family_id: str) -> list[dict[str, Any]]:
    """Build diverse multi-axis param slots for a family (not mom-only flood)."""
    slots: list[dict[str, Any]] = []
    if family_id == CLASS_MULTI_DAY_HOLD:
        for h in _HOLD_DAYS:
            for rb in _REBALANCE:
                slots.append(
                    {
                        "hold_days": h,
                        "rebalance_mode": rb,
                        # momentum lookback matches hold (class_hyp convention)
                        "momentum_n": h,
                    }
                )
    elif family_id == CLASS_EVENT_POST:
        for h in _EVENT_HOLD:
            for em in _EVENT_ENTRY_SAFE:
                slots.append({"post_hold_days": h, "entry_mode": em})
    elif family_id == CLASS_CROSS_SECTION_RELATIVE:
        for h in (5, 10, 20):
            for mom in _MOM_N:
                for lf in _XS_LONG_FRAC:
                    for sf in _XS_SHORT_FRAC:
                        # skip pure micro-dupes where long==short only when
                        # mom==h and only one frac — keep all structural combos
                        # but cap later via cycle index (not 100 mom steps)
                        if abs(lf - sf) > 0.15 and mom in (3, 20):
                            # keep asymmetric books only for extreme moms
                            slots.append(
                                {
                                    "hold_days": h,
                                    "momentum_n": mom,
                                    "long_frac": lf,
                                    "short_frac": sf,
                                }
                            )
                        elif abs(lf - sf) <= 0.15:
                            slots.append(
                                {
                                    "hold_days": h,
                                    "momentum_n": mom,
                                    "long_frac": lf,
                                    "short_frac": sf,
                                }
                            )
    elif family_id == CLASS_MACRO_CONDITIONED:
        for mode in _MACRO_MODE:
            for mom in (5, 10, 20):
                for h in (5, 10, 20):
                    for hi in _MACRO_HIGH:
                        for lo in _MACRO_LOW:
                            if lo >= hi:
                                continue
                            slots.append(
                                {
                                    "mode": mode,
                                    "momentum_n": mom,
                                    "hold_days": h,
                                    "high_threshold": hi,
                                    "low_threshold": lo,
                                }
                            )
    elif family_id == CLASS_FUNDAMENTALS_PRICE:
        for h in _FUND_HOLD:
            for mom in _FUND_MOM:
                for mode in _FUND_MODE:
                    slots.append(
                        {
                            "hold_days": h,
                            "momentum_n": mom,
                            "mode": mode,
                        }
                    )
    elif family_id == CLASS_FLOW_DEMAND:
        for h in _FLOW_HOLD:
            for sc in _FLOW_CONFIRM:
                slots.append(
                    {
                        "hold_days": h,
                        "short_confirm_mode": sc,
                        "require_short_confirm": sc == "hard",
                    }
                )
    elif family_id == FAMILY_VOL_RISK_ADJUSTED:
        for h in (5, 10, 20):
            for vn in _VOL_N:
                for thr in _VOL_THRESH:
                    slots.append(
                        {
                            "hold_days": h,
                            "momentum_n": h,
                            "vol_n": vn,
                            "vol_threshold": thr,
                        }
                    )
    else:
        raise KeyError(f"unknown family for param slots: {family_id!r}")
    return slots


# ---------------------------------------------------------------------------
# Config + generated strategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MassFactoryConfig:
    """Batch generation / eval configuration."""

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
    use_q4_periods: bool = True  # lite multi-year; document tradeoff
    paper_sample_k: int = 0  # short paper for top-k only; 0 = off
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS
    min_activation: float = DEFAULT_MIN_ACTIVATION
    fail_one_continue: bool = True

    def normalized_ratios(self) -> dict[str, float]:
        raw = {
            str(k): float(v)
            for k, v in dict(self.family_ratios).items()
            if float(v) > 0 and str(k) in FAMILY_DEFINITIONS
        }
        if not raw:
            raw = dict(DEFAULT_FAMILY_RATIOS)
        # Drop simple_daily_sign if sneaked in
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
            "continuous_paper": CONTINUOUS_PAPER,
            **_freeze(),
        }


@dataclass(frozen=True)
class GeneratedStrategy:
    """One generated strategy spec (research factory output)."""

    strategy_id: str
    family_id: str
    params: Mapping[str, Any]
    datasets_required: tuple[str, ...]
    generation_index: int
    seed: int
    status: str  # accepted | rejected_at_gen
    reject_reason: str | None = None
    hypothesis_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "family_id": self.family_id,
            "hypothesis_class": self.hypothesis_class or self.family_id,
            "params": dict(self.params),
            "datasets_required": list(self.datasets_required),
            "generation_index": int(self.generation_index),
            "seed": int(self.seed),
            "status": self.status,
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
) -> str:
    """Deterministic stable ID from seed + family + params + index."""
    payload = {
        "seed": int(seed),
        "family_id": str(family_id),
        "params": _canonical_params(params),
        "i": int(generation_index),
        "v": MASS_FACTORY_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    fam = str(family_id).replace("_", "")[:8]
    return f"msf_{int(seed):08x}_{int(generation_index):04d}_{fam}_{digest}"


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


def _split_counts(n: int, ratios: Mapping[str, float], max_share: float) -> dict[str, int]:
    """Allocate integer counts per family with anti-bias cap."""
    fams = [k for k, v in ratios.items() if v > 0]
    if not fams:
        raise ValueError("no families in ratios")
    cap = max(1, int(math.floor(float(max_share) * n)))
    # largest remainder method with iterative rebalance under cap
    raw = {f: ratios[f] * n for f in fams}
    counts = {f: int(math.floor(raw[f])) for f in fams}
    rem = n - sum(counts.values())
    order = sorted(fams, key=lambda f: (raw[f] - counts[f], ratios[f], f), reverse=True)
    i = 0
    while rem > 0 and i < 10_000:
        f = order[i % len(order)]
        if counts[f] < cap:
            counts[f] += 1
            rem -= 1
        i += 1
        if i % len(order) == 0 and all(counts[x] >= cap for x in fams):
            # all capped — allow overflow on highest-ratio families to hit N
            for f2 in order:
                if rem <= 0:
                    break
                counts[f2] += 1
                rem -= 1
            break
    # ensure at least 1 for each enabled family when n is large enough
    if n >= len(fams):
        for f in fams:
            if counts[f] == 0:
                donor = max(fams, key=lambda x: counts[x])
                if counts[donor] > 1:
                    counts[donor] -= 1
                    counts[f] = 1
    # final pad/trim to exact n
    diff = n - sum(counts.values())
    order2 = sorted(fams, key=lambda f: (-ratios[f], f))
    j = 0
    while diff != 0 and j < 10_000:
        f = order2[j % len(order2)]
        if diff > 0:
            counts[f] += 1
            diff -= 1
        elif counts[f] > 0:
            counts[f] -= 1
            diff += 1
        j += 1
    return counts


def validate_strategy_at_gen(
    family_id: str,
    params: Mapping[str, Any],
    *,
    available_datasets: frozenset[str] | set[str] = FACTORY_AVAILABLE_DATASETS,
) -> tuple[bool, str | None]:
    """Gen-time validity: PIT, datasets, forbidden classes/params."""
    fid = str(family_id).strip()
    if fid == CLASS_SIMPLE_DAILY_SIGN:
        return False, REJECT_SIMPLE_DAILY_SIGN
    if fid.startswith("s") and fid[1:].isdigit() and int(fid[1:]) <= 5:
        return False, REJECT_S1_S5
    if fid not in FAMILY_DEFINITIONS:
        return False, REJECT_UNKNOWN_FAMILY

    fam = FAMILY_DEFINITIONS[fid]
    missing = [d for d in fam.datasets_required if d not in available_datasets]
    if missing:
        return False, f"{REJECT_MISSING_DATASETS}:{','.join(missing)}"

    p = dict(params)
    if fid == CLASS_EVENT_POST:
        em = str(p.get("entry_mode") or "")
        if em in _EVENT_ENTRY_FORBIDDEN or "look" in em.lower() and "ahead" in em.lower():
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
    return True, None


def generate_strategy_batch(
    config: MassFactoryConfig | None = None,
    *,
    seed: int | None = None,
    n: int | None = None,
    family_ratios: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Generate N strategy specs with stable IDs across multiple families.

    Returns machine-readable pack with accepted + gen-rejected rows.
    Target: N>=100 accepted when datasets available; quality filter at eval.
    """
    cfg = config or MassFactoryConfig()
    if seed is not None or n is not None or family_ratios is not None:
        cfg = MassFactoryConfig(
            seed=int(seed if seed is not None else cfg.seed),
            n=int(n if n is not None else cfg.n),
            family_ratios=dict(family_ratios if family_ratios is not None else cfg.family_ratios),
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
        )
    if cfg.n < 1:
        raise ValueError("n must be >= 1")

    ratios = cfg.normalized_ratios()
    counts = _split_counts(cfg.n, ratios, cfg.max_family_share)
    slots_by_fam = {f: _param_slots_for_family(f) for f in counts}

    # Deterministic shuffle of slot order per family using seed
    rng_state = int(cfg.seed) & 0xFFFFFFFF

    def _next_rand() -> int:
        nonlocal rng_state
        # LCG (Numerical Recipes); pure python, reproducible
        rng_state = (1664525 * rng_state + 1013904223) & 0xFFFFFFFF
        return rng_state

    strategies: list[GeneratedStrategy] = []
    gen_rejected: list[GeneratedStrategy] = []
    family_dist: dict[str, int] = {f: 0 for f in counts}
    index = 0

    # Build ordered worklist: interleave families by ratio weight
    work: list[str] = []
    for f, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        work.extend([f] * c)
    # seed-stable interleave shuffle
    for i in range(len(work) - 1, 0, -1):
        j = _next_rand() % (i + 1)
        work[i], work[j] = work[j], work[i]

    # per-family cursor into shuffled multi-axis slots (anti micro-grid flood:
    # Fisher–Yates with seed so consecutive picks diversify hold/mom/frac axes)
    cursors: dict[str, int] = {}
    rotated_slots: dict[str, list[dict[str, Any]]] = {}
    for f, slots in slots_by_fam.items():
        if not slots:
            rotated_slots[f] = [{}]
            continue
        shuffled = list(slots)
        for i in range(len(shuffled) - 1, 0, -1):
            j = _next_rand() % (i + 1)
            shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
        rotated_slots[f] = shuffled
        cursors[f] = 0

    for fam in work:
        slots = rotated_slots[fam]
        cursor = cursors.get(fam, 0)
        # try up to len(slots) param variants to find a valid one
        accepted_local: GeneratedStrategy | None = None
        for attempt in range(max(1, len(slots))):
            params = dict(slots[(cursor + attempt) % len(slots)])
            # tiny seed-based jitter on continuous params without creating
            # a 100-step microgrid: pick alternate threshold index
            if fam == CLASS_MACRO_CONDITIONED and attempt > 0:
                params = dict(slots[(cursor + attempt) % len(slots)])
            ok, reason = validate_strategy_at_gen(
                fam, params, available_datasets=cfg.available_datasets
            )
            sid = stable_strategy_id(
                seed=cfg.seed,
                family_id=fam,
                params=params,
                generation_index=index,
            )
            hyp = fam if fam in HYPOTHESIS_CLASS_REGISTRY else fam
            if ok:
                accepted_local = GeneratedStrategy(
                    strategy_id=sid,
                    family_id=fam,
                    params=params,
                    datasets_required=FAMILY_DEFINITIONS[fam].datasets_required,
                    generation_index=index,
                    seed=cfg.seed,
                    status="accepted",
                    reject_reason=None,
                    hypothesis_class=hyp,
                )
                cursors[fam] = (cursor + attempt + 1) % max(1, len(slots))
                break
            else:
                gen_rejected.append(
                    GeneratedStrategy(
                        strategy_id=sid,
                        family_id=fam,
                        params=params,
                        datasets_required=FAMILY_DEFINITIONS[fam].datasets_required,
                        generation_index=index,
                        seed=cfg.seed,
                        status="rejected_at_gen",
                        reject_reason=reason,
                        hypothesis_class=hyp,
                    )
                )
        if accepted_local is not None:
            strategies.append(accepted_local)
            family_dist[fam] = family_dist.get(fam, 0) + 1
        else:
            # could not place valid strategy for this slot
            family_dist.setdefault(fam, 0)
        index += 1

    n_accepted = len(strategies)
    shares = {
        f: (family_dist.get(f, 0) / n_accepted if n_accepted else 0.0)
        for f in sorted(set(list(counts) + list(family_dist)))
    }
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "config": cfg.to_dict(),
        "n_requested": int(cfg.n),
        "n_generated_accepted": n_accepted,
        "n_rejected_at_gen": len(gen_rejected),
        "n_ge_100": n_accepted >= 100,
        "family_counts_requested": counts,
        "family_distribution": family_dist,
        "family_shares": shares,
        "max_family_share_observed": max(shares.values()) if shares else 0.0,
        "anti_bias_ok": (
            (max(shares.values()) <= cfg.max_family_share + 1e-9)
            if shares and n_accepted
            else False
        ),
        "n_families_used": sum(1 for v in family_dist.values() if v > 0),
        "strategies": [s.to_dict() for s in strategies],
        "gen_rejected": [s.to_dict() for s in gen_rejected],
        "families_document": family_definitions_document(),
        **_freeze(),
    }


# ---------------------------------------------------------------------------
# Vol-risk pure evaluator (bars only)
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
) -> dict[str, Any]:
    """Multi-day mom hold gated by |mom|/vol ≥ threshold (research only)."""
    from research.class_hyp_eval import momentum_series

    h = int(hold_days)
    vn = int(vol_n)
    thr = float(vol_threshold)
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
        "signal_id": "c21_vol_risk_adjusted_hold",
        "hypothesis_class": FAMILY_VOL_RISK_ADJUSTED,
        "hold_days": h,
        "vol_n": vn,
        "vol_threshold": thr,
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
            f"Vol-risk gate |mom|/vol>={thr} hold={h} vol_n={vn}. "
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
    panels: list[dict[str, Any]]  # per period: bars, repo, fins, margin, short
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
        load_bars_ndjson_rich,
        load_fins_events_from_sqlite,
        load_margin_ndjson,
        load_repo_rows_from_sqlite,
        load_short_ratio_series_from_sqlite,
        resolve_bars_path,
        resolve_margin_path,
    )
    from research.cost_models import load_repo_rate_series_from_rows

    if synthetic:
        return _synthetic_batch_context(config)

    period_list = [dict(p) for p in (periods or (
        DEFAULT_PERIODS_Q4 if config.use_q4_periods else DEFAULT_PERIODS
    ))]
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
                margin = load_margin_ndjson(
                    margin_path, codes=selected
                )
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
            "n_fins_codes": len(fins_events),
            "use_q4_periods": bool(config.use_q4_periods),
            "max_days_per_period": int(config.max_days_per_period),
            "tradeoff": (
                "Lite multi-year: Q4 (or capped full) windows + code subsample "
                "for N>=100 wall-time. Not production research_candidate SoT; "
                "survivors need deeper class_hyp re-eval before any promotion."
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
            # trending + mild noise
            series = [
                (d, base + 0.4 * i + (0.2 if (i + ci) % 5 == 0 else 0.0))
                for i, d in enumerate(dates)
            ]
            bars[code] = series
            margin[code] = [
                (dates[i], 1000.0 + 20 * i + 5 * ci)
                for i in range(0, len(dates), 3)
            ]
        # simple repo series
        rates = {d: 0.05 + 0.001 * i for i, d in enumerate(dates)}
        repo_series = {
            "rates_by_date": rates,
            "dataset": "jsda_tokyo_repo_rates",
            "source": "synthetic",
        }
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
                "fins_events": fins_events,
                "short_series": [(d, 0.01 + 0.0001 * i) for i, d in enumerate(dates)],
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
        evaluate_multi_day_hold_on_bars,
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
        out = evaluate_multi_day_hold_on_bars(
            bars,
            hold_days=int(p.get("hold_days") or DEFAULT_HOLD_DAYS),
            one_way_cost=one_way_cost,
            rebalance_mode=str(p.get("rebalance_mode") or "fixed_horizon"),
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
        except Exception as exc:  # fail-one-continue at period level
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
    # Metrics on chosen side nets
    side_key = "original" if chosen_sign == SIGN_ORIGINAL else (
        "inverted" if chosen_sign == SIGN_INVERTED else "original"
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
        # errors alone don't reject if some periods ok
        if n_ok == 0:
            reasons.append(SCREEN_EVAL_ERROR)

    mean_gross = result.get("mean_gross")
    mean_net = result.get("mean_net")
    if mean_gross is not None and mean_net is not None:
        try:
            g, n = float(mean_gross), float(mean_net)
            # collapse: gross positive-ish but net near-zero/negative much worse
            if abs(g) >= near_zero_abs and abs(n) < near_zero_abs:
                reasons.append(SCREEN_POST_COST_COLLAPSE)
            if g > near_zero_abs and n < -near_zero_abs and (g - n) > abs(g):
                # cost ate more than gross magnitude
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

    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)

    survived = len(uniq) == 0 and n_ok > 0
    return {
        "strategy_id": result.get("strategy_id"),
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
    """Batch-evaluate accepted strategies; fail-one-continue; screen survivors.

    Does **not** pick human main candidates. continuous paper UNARMED.
    """
    t0 = time.perf_counter()
    cfg = config or MassFactoryConfig(
        seed=int((generation.get("config") or {}).get("seed") or DEFAULT_SEED),
        n=int(generation.get("n_requested") or DEFAULT_N),
    )
    if ctx is None:
        ctx = load_batch_data_context(cfg, synthetic=synthetic)

    strategies = list(generation.get("strategies") or [])
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

    # Rank survivors by |t| then mean_net (research ranking only)
    def _rank_key(s: Mapping[str, Any]) -> tuple[float, float]:
        t = s.get("t_stat")
        m = s.get("mean_net")
        tv = abs(float(t)) if t is not None and math.isfinite(float(t)) else -1.0
        mv = float(m) if m is not None and math.isfinite(float(m)) else -1e9
        return (tv, mv)

    survivors_ranked = sorted(survivors, key=_rank_key, reverse=True)

    # Family summary for survivors (few top per family)
    by_family: dict[str, list[dict[str, Any]]] = {}
    for s in survivors_ranked:
        by_family.setdefault(str(s.get("family_id")), []).append(dict(s))
    family_top: dict[str, list[dict[str, Any]]] = {
        f: rows[:3] for f, rows in sorted(by_family.items())
    }
    survivor_family_dist = {f: len(v) for f, v in by_family.items()}

    # Reject reason histogram
    reason_hist: dict[str, int] = {}
    for s in rejected:
        for r in s.get("reject_reasons") or ["unspecified"]:
            reason_hist[str(r)] = reason_hist.get(str(r), 0) + 1

    wall = time.perf_counter() - t0
    ranking = [
        {
            "rank": i + 1,
            "strategy_id": s.get("strategy_id"),
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
            "not 100 full papers. continuous paper UNARMED this wave."
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
        "n_strategies_evaluated": len(strategies),
        "n_eval_ok": n_ok_eval,
        "n_eval_fail": n_fail,
        "fail_rate": (n_fail / len(strategies)) if strategies else 0.0,
        "n_survivors": len(survivors),
        "n_screen_rejected": len(rejected),
        "wall_time_sec": round(wall, 3),
        "n_ge_100_generated": bool(generation.get("n_ge_100")),
        "n_generated_accepted": generation.get("n_generated_accepted"),
        "generation_family_distribution": generation.get("family_distribution"),
        "survivor_family_distribution": survivor_family_dist,
        "family_top_survivors": family_top,
        "ranking": ranking,
        "reject_reason_histogram": reason_hist,
        "screens": screens,
        "results": results,
        "paper": paper_note,
        "human_main_candidates_selected": False,
        "note": (
            "Auto screen only. Do NOT treat survivors as human main candidates "
            "or research_candidate production defaults this wave. "
            "Deeper class_hyp re-eval required before any promotion. "
            "Mass/READY/ops GO remain closed."
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
    """End-to-end: generate → batch eval → screen → optional write logs."""
    cfg = config or MassFactoryConfig(
        seed=seed,
        n=n,
        family_ratios=dict(family_ratios or DEFAULT_FAMILY_RATIOS),
    )
    if seed != DEFAULT_SEED or n != DEFAULT_N or family_ratios is not None:
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
        )

    t0 = time.perf_counter()
    gen = generate_strategy_batch(cfg)
    ctx = load_batch_data_context(cfg, synthetic=synthetic)

    def _cb(i: int, total: int, sid: str) -> None:
        if progress and (i == 1 or i == total or i % 10 == 0):
            print(f"[mass-factory] eval {i}/{total} {sid}", flush=True)

    batch = run_batch_eval(
        gen, config=cfg, ctx=ctx, synthetic=synthetic, progress_cb=_cb if progress else None
    )
    wall = time.perf_counter() - t0

    pack = {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "wall_time_sec_total": round(wall, 3),
        "generation": {
            k: gen[k]
            for k in gen
            if k not in {"strategies", "gen_rejected", "families_document"}
        },
        "generation_strategies": gen.get("strategies"),
        "generation_rejected": gen.get("gen_rejected"),
        "families": family_definitions_document(),
        "batch": {
            k: batch[k]
            for k in batch
            if k not in {"results", "screens"}
        },
        "batch_ranking": batch.get("ranking"),
        "batch_screens": batch.get("screens"),
        "batch_results": batch.get("results"),
        "summary": {
            "n_requested": gen.get("n_requested"),
            "n_generated_accepted": gen.get("n_generated_accepted"),
            "n_ge_100": gen.get("n_ge_100"),
            "n_families_used": gen.get("n_families_used"),
            "anti_bias_ok": gen.get("anti_bias_ok"),
            "family_distribution": gen.get("family_distribution"),
            "n_survivors": batch.get("n_survivors"),
            "fail_rate": batch.get("fail_rate"),
            "wall_time_sec": round(wall, 3),
            "survivor_family_distribution": batch.get("survivor_family_distribution"),
            "top5": (batch.get("ranking") or [])[:5],
            "human_main_candidates_selected": False,
            "continuous_paper": CONTINUOUS_PAPER,
        },
        **_freeze(),
    }

    if out_dir is not None:
        write_factory_outputs(pack, out_dir)

    return pack


def write_factory_outputs(pack: Mapping[str, Any], out_dir: str | Path) -> dict[str, str]:
    """Write machine-readable factory outputs under out_dir."""
    od = Path(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    def _w(name: str, obj: Any) -> None:
        p = od / name
        p.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")
        paths[name] = str(p)

    _w("factory_run.json", pack)
    _w(
        "generation_summary.json",
        {
            "summary": pack.get("summary"),
            "generation": pack.get("generation"),
            "family_distribution": (pack.get("summary") or {}).get("family_distribution"),
        },
    )
    _w("strategies.json", pack.get("generation_strategies") or [])
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
            "family_top_survivors": (pack.get("batch") or {}).get("family_top_survivors"),
        },
    )
    # Compact results without full period holding dumps
    compact_results = []
    for r in pack.get("batch_results") or []:
        compact_results.append(
            {
                k: r.get(k)
                for k in (
                    "strategy_id",
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

    # Markdown summary
    sm = pack.get("summary") or {}
    lines = [
        f"# Mass strategy factory run — {MASS_FACTORY_WAVE}",
        "",
        f"- version: `{MASS_FACTORY_VERSION}`",
        f"- n_requested: **{sm.get('n_requested')}**",
        f"- n_generated_accepted: **{sm.get('n_generated_accepted')}** (N≥100: **{sm.get('n_ge_100')}**)",
        f"- n_families_used: **{sm.get('n_families_used')}**",
        f"- anti_bias_ok: **{sm.get('anti_bias_ok')}**",
        f"- n_survivors: **{sm.get('n_survivors')}**",
        f"- fail_rate: **{sm.get('fail_rate')}**",
        f"- wall_time_sec: **{sm.get('wall_time_sec')}**",
        f"- continuous_paper: **{sm.get('continuous_paper')}**",
        f"- human_main_candidates_selected: **{sm.get('human_main_candidates_selected')}**",
        f"- mass_research: **{MASS_RESEARCH}** · READY: **{READY_DECLARED}** · ops GO: **{OPERATIONAL_GO}**",
        "",
        "## Family distribution (generated)",
        "",
        "```json",
        json.dumps(sm.get("family_distribution") or {}, indent=2),
        "```",
        "",
        "## Survivor family distribution",
        "",
        "```json",
        json.dumps(sm.get("survivor_family_distribution") or {}, indent=2),
        "```",
        "",
        "## Top 5 (research ranking only — not human main candidates)",
        "",
    ]
    for row in sm.get("top5") or []:
        lines.append(
            f"- rank {row.get('rank')}: `{row.get('strategy_id')}` "
            f"family={row.get('family_id')} mean_net={row.get('mean_net')} "
            f"t={row.get('t_stat')} sign={row.get('chosen_sign')}"
        )
    lines.extend(
        [
            "",
            "## Re-run recipe",
            "",
            "```bash",
            "python scripts/run_mass_strategy_batch.py --seed 870816 --n 100 \\",
            "  --out-dir .glm-logs/w0816v_w87_mass/",
            "```",
            "",
            "Synthetic (tests / no mirrors):",
            "",
            "```bash",
            "python scripts/run_mass_strategy_batch.py --synthetic --n 100 --out-dir /tmp/msf",
            "```",
            "",
        ]
    )
    md_path = od / "SUMMARY.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["SUMMARY.md"] = str(md_path)
    return paths


def mass_factory_document() -> dict[str, Any]:
    """Public document for the mass strategy factory."""
    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "purpose": (
            "Generate 100+ diverse strategies across families and "
            "batch-evaluate automatically (research factory)."
        ),
        "families": family_definitions_document(),
        "default_config": MassFactoryConfig().to_dict(),
        "not_goals": [
            "polishing 3 candidates",
            "operational GO / Mass / READY / live",
            "simple_daily_sign mass as diversity",
            "S1–S5 un-reject",
            "mom grid only as the 100",
            "human main candidate selection this wave",
        ],
        "eval_tradeoffs": (
            "Lite multi-year (Q4 windows + code subsample) so N>=100 fits "
            "wall-time. Survivors need deeper class_hyp re-eval before promotion."
        ),
        "continuous_paper": CONTINUOUS_PAPER,
        **_freeze(),
        "proof": "docs/proof/w0816v_w87_mass_strategy_factory_20260817.md",
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
    "FAMILY_DEFINITIONS",
    "FACTORY_FAMILY_IDS",
    "DEFAULT_FAMILY_RATIOS",
    "DEFAULT_SEED",
    "DEFAULT_N",
    "MassFactoryConfig",
    "GeneratedStrategy",
    "BatchDataContext",
    "family_definitions_document",
    "mass_factory_document",
    "stable_strategy_id",
    "validate_strategy_at_gen",
    "generate_strategy_batch",
    "evaluate_vol_risk_adjusted_on_bars",
    "load_batch_data_context",
    "evaluate_one_strategy",
    "screen_strategy_result",
    "run_batch_eval",
    "run_mass_factory",
    "write_factory_outputs",
]
