"""Mass strategy logic-diversity factory + batch auto-experiment.

Purpose
-------
Research factory that generates strategy **individuals** around **distinct
economic logic templates** (thesis + signal structure + position rule +
datasets), not hold_days / momentum_window / long_frac param grids.

Includes:
* Nikkei/index realized-vol regime logics (abs level · term levels · ratio)
* CF real multi-year panels (mode=r2_panels; synthetic not a pass)
* interest-rate factor logics (absolute level + curve-shape × CS)
* multi-factor logics (value×mom×rate, flow×price) with required theses
* programmatic profit-hypothesis entry (always through evaluator)

CF ``n_survivors`` is a period-net screen only. Candidate-grade eval is
``research.daily_path_eval`` recorded to R2 ``research/eval/job={id}/``.

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
* ``class_signals`` — pure bar evaluators
* ``cost_models`` · ``sign_selection`` · ``stats_metrics``
* ``cf_mass_eval_job`` · ``cf_daily_path_job``

See: ``docs/architecture/adr_research_recording.md``
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIMPLE_DAILY_SIGN,
    HYPOTHESIS_CLASS_REGISTRY,
    MASS_RESEARCH as HC_MASS,
    PHASE7 as HC_PHASE7,
    READY_DECLARED as HC_READY,
)
from research.cost_models import DEFAULT_ONE_WAY_COST
from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    CONTINUOUS_PAPER,
    EDGE_CLAIMED,
    FROZEN_DEFAULT_PATH,
    LIVE_ORDERS,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    S1_S5_UNREJECT,
    SIGNIFICANCE_CLAIMED,
    SIMPLE_DAILY_SIGN_AS_DIVERSITY,
)
from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS
from research.offline.bar_eval import evaluate_vol_risk_adjusted_on_bars
from research.offline.factory_templates import (
    DEFAULT_FAMILY_RATIOS,
    FACTORY_FAMILY_IDS,
    FAMILY_AFTERCLOSE_EVENT_TIMING,
    FAMILY_CURVE_STEEPEN_IMPULSE_CS,
    FAMILY_DEFINITIONS,
    FAMILY_DISCLOSURE_CLUSTER_GATE,
    FAMILY_EVENT_CALENDAR_GATE,
    FAMILY_EVENT_FUNDING_COMBO,
    FAMILY_EVENT_MACRO_CURVE_COMBO,
    FAMILY_EVENT_MARGIN_CROWD_COMBO,
    FAMILY_EVENT_MOM_AGREE_COMBO,
    FAMILY_FUNDING_IMPULSE_CS,
    FAMILY_IDIO_MOM_MACRO,
    FAMILY_INDEX_VOL_REGIME,
    FAMILY_LARGE_SURPRISE_FILTER,
    FAMILY_MONTH_END_CS,
    FAMILY_MULTI_FACTOR,
    FAMILY_OPTIONS_VOL_REGIME,
    FAMILY_OVERNIGHT_LEVEL_CS,
    FAMILY_RATE_FACTOR,
    FAMILY_REPO_3M_LEVEL_CS,
    FAMILY_RESEARCH_UNIQUE_LOGIC,
    FAMILY_SURPRISE_XS_RANK,
    FAMILY_VOL_RISK_ADJUSTED,
    FAMILY_XS_LOW_VOL_MOM,
    FAMILY_XS_MARGIN_DELTA,
    LOGIC_TEMPLATE_IDS,
    LOGIC_TEMPLATES,
    LogicTemplate,
    NEAR_LOGIC_GROUPS,
    NUMERIC_ONLY_KNOBS,
    RESEARCH_FAMILY_APPEND_ID,
    RESEARCH_FAMILY_APPEND_LOGIC_IDS,
    RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE,
    RESEARCH_FAMILY_REGISTER_ID,
    RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS,
    RESEARCH_UNIQUE_FAMILY_IDS,
    family_definitions_document,
    logic_templates_document,
    near_logic_groups_document,
    research_family_append_document,
    research_family_register_document,
)

# ---------------------------------------------------------------------------
# Identity / freezes (must never arm operational Mass)
# ---------------------------------------------------------------------------

MASS_FACTORY_VERSION: str = "mass-strategy-factory/v2.8"
MASS_FACTORY_WAVE: str = "research-unique-logic"

# Factory "mass" here means bulk research generation — never operational Mass.
FACTORY_MASS_LOOP: str = "research_batch_only"

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
# W95: small-n near-identical period nets inflate |t|; demote/exclude survivors.
SCREEN_INFLATED_T_LOW_VARIANCE: str = "inflated_t_low_variance"

DEFAULT_SEED: int = 870816
DEFAULT_N: int = 100  # capacity; uniqueness measured by unique_logic / after_dedup
DEFAULT_NEAR_ZERO_ABS: float = 0.0005  # 5bp
DEFAULT_MIN_ACTIVATION: float = 0.01
DEFAULT_MAX_FAMILY_SHARE: float = 0.35  # soft; logic diversity is primary anti-bias
DEFAULT_ONE_WAY: float = DEFAULT_ONE_WAY_COST
DEFAULT_NEAR_DUP_THRESHOLD: float = 0.85  # drop when similarity >= this

# Frozen default-path representatives live in research.freezes (do not retune).

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
        "derivatives_bars_daily_options_225",
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

_REPO_ROOT = Path(__file__).resolve().parents[4]


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


# Logic templates, FAMILY_*, NEAR_LOGIC_GROUPS, documents live in
# research.offline.factory_templates (BAR_NATIVE_SPECS SoT for 30 ids).

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
    if fid == FAMILY_OPTIONS_VOL_REGIME:
        mode = str(p.get("mode") or "")
        if mode not in {
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
        }:
            return False, REJECT_INVALID_PARAMS
        if str(p.get("series_kind") or "") not in {
            "basevol",
            "atm_iv",
            "spread",
            "spread_change",
            "skew",
            "cm_term",
            "basevol_delta",
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
        if lid in RESEARCH_UNIQUE_LOGIC_IDS:
            continue
        tpl = LOGIC_TEMPLATES[lid]
        if not tpl.generation_enabled:
            continue
        _try_emit(tpl, dict(tpl.base_params), numeric=False)

    # Pass 2: optional limited numeric variants (capacity fill; near-dup later)
    if cfg.allow_numeric_variants and len(strategies) < cfg.n:
        for lid in logic_ids:
            if len(strategies) >= cfg.n:
                break
            if lid in RESEARCH_UNIQUE_LOGIC_IDS:
                continue
            tpl = LOGIC_TEMPLATES[lid]
            if not tpl.generation_enabled:
                continue
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
# Batch evaluation context + per-strategy eval
# ---------------------------------------------------------------------------
# Bodies live in research.offline.factory_eval (import after MassFactoryConfig).

from research.offline.factory_eval import (  # noqa: E402
    BatchDataContext,
    evaluate_one_strategy,
    load_batch_data_context,
    run_batch_eval,
    screen_strategy_result,
)


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
            "python -m research.cf_daily_path_job  # CF isolate fan-out",
            "python -m research.unique_logic --all --backend local  # serial fallback",
            "```",
            "",
            "Synthetic (tests / no mirrors):",
            "",
            "```bash",
            "python -m research.offline.factory --synthetic --n 100",
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


def _research_mass_eval_version() -> str:
    from qp_paths import repo_root

    p = repo_root() / "platform" / "workers" / "research-mass-eval" / "wrangler.toml"
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("MASS_EVAL_VERSION"):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "research-mass-eval/unknown"


def try_cf_minimal_mass_batch() -> dict[str, Any]:
    """Prefer a stable minimal CF job returning one small batch result.

    Status
    ------
    CF worker ``quant-platform-research-mass-eval`` exists under
    ``platform/workers/research-mass-eval/`` with
    ``POST /v1/mass-eval`` → R2 ``research/mass_eval/job={id}/``.

    Pure-TS lite multi-period path (synthetic / r2_panels / nets_only).
    Period-net ``n_survivors`` is a screen, not a ``daily_path_DD`` pass.
    Full rate/mf factor legs on CF remain **not-yet-implemented** (fallback
    multi_day_hold or nets_only). Local ``run_mass_factory`` remains the
    full-factory path. Scaling to 200/500 queue fan-out is not-yet-implemented.
    """
    return {
        "status": "available",
        "wave": MASS_FACTORY_WAVE,
        "version": _research_mass_eval_version(),
        "factory_wave": MASS_FACTORY_WAVE,
        "factory_version": MASS_FACTORY_VERSION,
        "worker": "quant-platform-research-mass-eval",
        "worker_path": "platform/workers/research-mass-eval/",
        "endpoint": "POST /v1/mass-eval",
        "request_shape": {
            "seed": "int",
            "logics": "list[{logic_id, family_id?, params?, thesis?}]",
            "periods": "list[{period_id, year?}]",
            "job_id": "str",
            "mode": "synthetic | r2_panels | nets_only | d1_bars",
        },
        "r2_prefix": "research/mass_eval/job={id}/",
        "r2_bucket": "quant-structured",
        "screen_kind": "period_net",
        "n_survivors_are_not_a_pass": True,
        "candidate_grade": False,
        "existing_cf_paths": [
            "platform/workers/research-mass-eval (POST /v1/mass-eval → research/mass_eval/)",
            "research.single_shot_job.execute_single_shot_job",
            "research.single_shot_job.execute_multiday_signal_eval",
            "packages/edge/cf_platform (ingestion / ops)",
        ],
        "supported_path_cf": (
            "wrangler deploy platform/workers/research-mass-eval && "
            "POST /v1/mass-eval"
        ),
        "supported_path_local": (
            "local run_mass_factory / python -m research.unique_logic --backend local"
        ),
        "python_driver": "research.cf_mass_eval_job",
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
            if logic_id in RESEARCH_UNIQUE_LOGIC_IDS:
                # Recognition, not a catalog remap / not a promotion.
                ind["eval_mapped_to_catalog"] = False
                ind["research_family_recognition"] = True
                ind["research_candidate"] = False
                ind["promote_as_main"] = False
                ind["go"] = False
                ind["registration"] = "recognition"
                ind["registration_is_not_a_pass"] = True
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
        "entry_fn": "research.offline.factory.propose_profit_hypotheses",
        "strong_model_entry": (
            "research.offline.factory.propose_profit_hypotheses"
        ),
        "preferred_model": "grok-4.6 (xAI api.x.ai)",
        "fallback_model": "@cf/openai/gpt-oss-120b (Workers AI)",
        "declaration_helper": "research.hypothesis_classes.build_research_idea_payload",
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
            "Hypothesis entry is propose_profit_hypotheses "
            "(always through evaluator)."
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
            "treat research-family registration as pass / promotion",
            "auto research_candidate from unique_logic register",
        ],
        "research_family_registration": research_family_register_document(),
        "eval_tradeoffs": (
            "CF lite multi-period (bounded codes/days) via mass-eval Worker. "
            "Local wide eval after near-dup. Heavy multi-year only for "
            "promising survivors. Survivors need deeper class_hyp re-eval "
            "before promotion."
        ),
        "continuous_paper": CONTINUOUS_PAPER,
        **_freeze(),
        "proof": "docs/architecture/adr_research_recording.md",
        "w91_index_vol": {
            "family": FAMILY_INDEX_VOL_REGIME,
            "logic_ids": [
                "nky_vol_abs_level",
                "nky_vol_term_levels",
                "nky_vol_term_ratio",
            ],
            "proxy": "NK225F front realized → TOPIX fallback; NKVIF available",
            "role": "proxy_compare_only",
            "distinct_from": [
                "vol_risk_adjusted_mom",
                "vol_breakout_expand",
            ],
        },
        "w92_options_vol": {
            "family": FAMILY_OPTIONS_VOL_REGIME,
            "logic_ids": [
                "opt225_basevol_abs_level",
                "opt225_basevol_term_levels",
                "opt225_basevol_term_ratio",
                "opt225_atm_iv_abs_level",
                "opt225_atm_iv_term_levels",
                "opt225_atm_iv_term_ratio",
                "opt225_iv_base_spread_abs",
                "opt225_iv_base_spread_change",
            ],
            "dataset": "derivatives_bars_daily_options_225",
            "role": "canonical_nky_vol_sot",
            "spread_convention": "atm_iv - base_vol",
            "units": "percent_vol_points",
            "distinct_from_proxy": [
                "nky_vol_abs_level",
                "nky_vol_term_levels",
                "nky_vol_term_ratio",
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
    "FAMILY_OPTIONS_VOL_REGIME",
    "FAMILY_EVENT_FUNDING_COMBO",
    "FAMILY_EVENT_MACRO_CURVE_COMBO",
    "FAMILY_DISCLOSURE_CLUSTER_GATE",
    "FAMILY_SURPRISE_XS_RANK",
    "FAMILY_LARGE_SURPRISE_FILTER",
    "FAMILY_AFTERCLOSE_EVENT_TIMING",
    "FAMILY_EVENT_MOM_AGREE_COMBO",
    "FAMILY_EVENT_MARGIN_CROWD_COMBO",
    "FAMILY_FUNDING_IMPULSE_CS",
    "FAMILY_CURVE_STEEPEN_IMPULSE_CS",
    "FAMILY_XS_MARGIN_DELTA",
    "FAMILY_IDIO_MOM_MACRO",
    "FAMILY_OVERNIGHT_LEVEL_CS",
    "FAMILY_MONTH_END_CS",
    "FAMILY_XS_LOW_VOL_MOM",
    "FAMILY_REPO_3M_LEVEL_CS",
    "FAMILY_RESEARCH_UNIQUE_LOGIC",
    "RESEARCH_UNIQUE_FAMILY_IDS",
    "RESEARCH_UNIQUE_LOGIC_IDS",
    "RESEARCH_FAMILY_APPEND_LOGIC_IDS",
    "RESEARCH_FAMILY_REGISTER_ID",
    "RESEARCH_FAMILY_APPEND_ID",
    "RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS",
    "RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE",
    "research_family_append_document",
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
    "research_family_register_document",
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
