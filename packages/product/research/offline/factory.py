"""Mass strategy logic-diversity factory (generation; not GO / READY).

Distinct economic-logic individuals, then near-dup, then batch eval.
Profit-hypothesis LLM entry: ``research.offline.factory_propose``.
Eval: ``research.offline.factory_eval``. Panels: ``factory_eval_data``.
Unique/combo stay ungenerated (generation_enabled=False).
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
from research.offline.factory_templates import (
    DEFAULT_FAMILY_RATIOS,
    FACTORY_FAMILY_IDS,
    FAMILY_DEFINITIONS,
    FAMILY_INDEX_VOL_REGIME,
    FAMILY_OPTIONS_VOL_REGIME,
    FAMILY_VOL_RISK_ADJUSTED,
    LOGIC_TEMPLATE_IDS,
    LOGIC_TEMPLATES,
    LogicTemplate,
    NUMERIC_ONLY_KNOBS,
    family_definitions_document,
    logic_templates_document,
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
# Panels: research.offline.factory_eval_data. Eval/screen: factory_eval.
# Import after MassFactoryConfig.

from research.offline.factory_eval_data import (  # noqa: E402
    BatchDataContext,
    load_batch_data_context,
)
from research.offline.factory_eval import (  # noqa: E402
    evaluate_one_strategy,
    run_batch_eval,
    screen_strategy_result,
)
from research.offline.factory_propose import (  # noqa: E402
    llm_logic_entry_status,
    propose_profit_hypotheses,
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
            }
        },
        "generation_strategies": gen.get("strategies"),
        "strategies_after_dedup": gen.get("strategies_after_dedup"),
        "near_dup_dropped": gen.get("near_dup_dropped"),
        "generation_rejected": gen.get("gen_rejected"),
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
    md_path = od / "SUMMARY.md"
    md_path.write_text(
        f"# Mass factory run — {MASS_FACTORY_WAVE}\n\n"
        f"- version: `{MASS_FACTORY_VERSION}`\n"
        f"- n_generated: **{sm.get('n_generated')}** "
        f"unique={sm.get('n_unique_logic')} "
        f"after_dedup={sm.get('n_after_dedup')}\n"
        f"- n_survivors: **{sm.get('n_survivors')}** "
        f"eval={sm.get('n_strategies_evaluated')} "
        f"fail={sm.get('fail_rate')}\n"
        f"- mass_research: **{MASS_RESEARCH}** · READY: **{READY_DECLARED}** · "
        f"ops GO: **{OPERATIONAL_GO}**\n",
        encoding="utf-8",
    )
    paths["SUMMARY.md"] = str(md_path)
    return paths

# CF mass-eval worker status (tests pin try_cf_minimal_mass_batch).

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
    """CF mass-eval worker status (period-net screen, not a pass)."""
    return {
        "status": "available",
        "version": _research_mass_eval_version(),
        "worker": "quant-platform-research-mass-eval",
        "endpoint": "POST /v1/mass-eval",
        "r2_prefix": "research/mass_eval/job={id}/",
        "r2_bucket": "quant-structured",
        "n_survivors_are_not_a_pass": True,
        "candidate_grade": False,
        "not_yet_implemented": [
            "full rate/mf factor legs on pure-TS CF path",
            "direct structured/jsonl historical bar load",
            "queue/DO fan-out for 200-500 logics",
        ],
        "scale_queue_fanout": False,
        "n_cf_batch_cap": 200,
        **_freeze(),
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
    "FAMILY_INDEX_VOL_REGIME",
    "FAMILY_OPTIONS_VOL_REGIME",
    "RESEARCH_UNIQUE_LOGIC_IDS",
    "FAMILY_DEFINITIONS",
    "FACTORY_FAMILY_IDS",
    "DEFAULT_FAMILY_RATIOS",
    "DEFAULT_SEED",
    "DEFAULT_N",
    "DEFAULT_NEAR_DUP_THRESHOLD",
    "DEFAULT_MAX_FAMILY_SHARE",
    "FROZEN_DEFAULT_PATH",
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
    "stable_strategy_id",
    "validate_strategy_at_gen",
    "generate_strategy_batch",
    "similarity_score",
    "dedup_strategies",
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
