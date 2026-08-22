"""Hypothesis class registry. simple_daily_sign is opt-in, lowest priority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from features.research_freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    MASS_GENERATE_SIGNALS,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PHASE7,
    READY_DECLARED,
    S1_S5_UNREJECT,
)

REGISTRY_VERSION: str = "hypothesis-class-registry/v1"
REGISTRY_WAVE: str = "W77 / w0816k"

CLASS_MULTI_DAY_HOLD: str = "multi_day_hold"
CLASS_EVENT_POST: str = "event_post"
CLASS_CROSS_SECTION_RELATIVE: str = "cross_section_relative"
CLASS_MACRO_CONDITIONED: str = "macro_conditioned"
CLASS_FUNDAMENTALS_PRICE: str = "fundamentals_price"
CLASS_FLOW_DEMAND: str = "flow_demand"
CLASS_SIMPLE_DAILY_SIGN: str = "simple_daily_sign"

_SIMPLE_DAILY_SIGN_PRIORITY: int = 99
_PASS_CLOSED: tuple[str, ...] = (
    "multi_year_or_long_periods_required",
    "pass_does_not_connect_ready_mass",
)

REQUIRED_CLASS_FIELDS: tuple[str, ...] = (
    "class_id",
    "horizon",
    "universe",
    "datasets_required",
    "feature_kinds",
    "constraints",
    "generation_enabled_by_default",
    "priority",
)


@dataclass(frozen=True)
class HypothesisClassSpec:
    """One hypothesis class. Opt-in if generation_enabled_by_default is False."""

    class_id: str
    horizon: str
    universe: tuple[str, ...]
    datasets_required: tuple[str, ...]
    feature_kinds: tuple[str, ...]
    constraints: tuple[str, ...]
    generation_enabled_by_default: bool
    priority: int
    display_name: str = ""
    description: str = ""
    opt_in_required: bool = False
    research_status_note: str = ""

    def __post_init__(self) -> None:
        if not str(self.class_id).strip():
            raise ValueError("class_id must be non-empty")
        if not str(self.horizon).strip():
            raise ValueError(f"{self.class_id}: horizon required")
        if not self.universe:
            raise ValueError(f"{self.class_id}: universe required")
        if not self.datasets_required:
            raise ValueError(f"{self.class_id}: datasets_required required")
        if not self.feature_kinds:
            raise ValueError(f"{self.class_id}: feature_kinds required")
        if not self.constraints:
            raise ValueError(f"{self.class_id}: constraints required")
        if self.priority < 0:
            raise ValueError(f"{self.class_id}: priority must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "display_name": self.display_name or self.class_id,
            "description": self.description,
            "horizon": self.horizon,
            "universe": list(self.universe),
            "datasets_required": list(self.datasets_required),
            "feature_kinds": list(self.feature_kinds),
            "constraints": list(self.constraints),
            "generation_enabled_by_default": self.generation_enabled_by_default,
            "priority": self.priority,
            "opt_in_required": self.opt_in_required,
            "research_status_note": self.research_status_note,
        }

    def research_idea_defaults(self) -> dict[str, Any]:
        """Map class fields onto ResearchIdea-aligned keys."""
        return {
            "target_horizon": self.horizon,
            "intended_universe": list(self.universe),
            "candidate_concepts": list(self.feature_kinds),
            "constraints": list(self.constraints),
            "lineage": {
                "hypothesis_class": self.class_id,
                "datasets_required": list(self.datasets_required),
                "generation_enabled_by_default": self.generation_enabled_by_default,
                "priority": self.priority,
                "opt_in_required": self.opt_in_required,
                "registry_version": REGISTRY_VERSION,
                "registry_wave": REGISTRY_WAVE,
            },
        }


def _spec(
    class_id: str,
    *,
    horizon: str,
    universe: Sequence[str],
    datasets_required: Sequence[str],
    feature_kinds: Sequence[str],
    constraints: Sequence[str],
    generation_enabled_by_default: bool,
    priority: int,
    display_name: str,
    description: str = "",
    opt_in_required: bool = False,
    research_status_note: str = "",
) -> HypothesisClassSpec:
    return HypothesisClassSpec(
        class_id=class_id,
        horizon=horizon,
        universe=tuple(str(x) for x in universe),
        datasets_required=tuple(str(x) for x in datasets_required),
        feature_kinds=tuple(str(x) for x in feature_kinds),
        constraints=tuple(str(x) for x in constraints),
        generation_enabled_by_default=generation_enabled_by_default,
        priority=int(priority),
        display_name=display_name,
        description=description,
        opt_in_required=opt_in_required,
        research_status_note=research_status_note,
    )


HYPOTHESIS_CLASS_REGISTRY: dict[str, HypothesisClassSpec] = {
    CLASS_MULTI_DAY_HOLD: _spec(
        CLASS_MULTI_DAY_HOLD,
        display_name="Multi-day hold",
        horizon="5d_to_20d_hold",
        universe=("tse_prime_liquid", "tse_topix500"),
        datasets_required=(
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ),
        feature_kinds=(
            "multi_day_return",
            "momentum_n",
            "hold_period_score",
            "turnover_aware_signal",
        ),
        constraints=(
            "no_daily_flip_as_primary",
            "holding_metrics_required",
            "cost_amortization_over_hold",
            *_PASS_CLOSED,
        ),
        generation_enabled_by_default=True,
        priority=10,
    ),
    CLASS_EVENT_POST: _spec(
        CLASS_EVENT_POST,
        display_name="Post-event",
        horizon="1d_to_5d_post_event",
        universe=("tse_prime_event_universe", "tse_disclosure_active"),
        datasets_required=(
            "fins_summary",
            "fins_details",
            "equities_bars_daily",
            "markets_calendar",
        ),
        feature_kinds=(
            "disclosure_flag",
            "event_window",
            "post_event_drift",
            "earnings_surprise_proxy",
        ),
        constraints=(
            "event_window_must_be_defined",
            "no_lookahead_into_pre_event_features",
            "pit_available_at_for_disclosure",
            *_PASS_CLOSED,
        ),
        generation_enabled_by_default=True,
        priority=20,
    ),
    CLASS_CROSS_SECTION_RELATIVE: _spec(
        CLASS_CROSS_SECTION_RELATIVE,
        display_name="Cross-section relative",
        horizon="5d_to_20d_cross_section",
        universe=("tse_prime_liquid", "tse_sector_neutral_panel"),
        datasets_required=(
            "equities_bars_daily",
            "indices_bars_daily_topix",
            "markets_calendar",
            "markets_breakdown",
        ),
        feature_kinds=(
            "cross_section_rank",
            "relative_value",
            "sector_neutral_score",
            "dispersion_signal",
        ),
        constraints=(
            "rank_based_not_absolute_sign",
            "min_universe_size_required",
            "sector_or_market_neutral_disclosed",
            *_PASS_CLOSED,
        ),
        generation_enabled_by_default=True,
        priority=30,
    ),
    CLASS_MACRO_CONDITIONED: _spec(
        CLASS_MACRO_CONDITIONED,
        display_name="Macro-conditioned",
        horizon="20d_to_60d_regime_conditioned",
        universe=("tse_prime_liquid", "tse_beta_sorted"),
        datasets_required=(
            "indices_bars_daily",
            "indices_bars_daily_topix",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
            "equities_bars_daily",
        ),
        feature_kinds=(
            "regime_label",
            "macro_state",
            "conditioned_signal",
            "rate_environment",
        ),
        constraints=(
            "explicit_regime_definition",
            "multi_regime_eval_required",
            "regime_shift_disclosure",
            *_PASS_CLOSED,
        ),
        generation_enabled_by_default=True,
        priority=40,
    ),
    CLASS_FUNDAMENTALS_PRICE: _spec(
        CLASS_FUNDAMENTALS_PRICE,
        display_name="Fundamentals vs price",
        horizon="20d_to_60d_fundamental",
        universe=("tse_prime_with_fins", "tse_dividend_payers"),
        datasets_required=(
            "fins_summary",
            "fins_details",
            "fins_dividend",
            "equities_bars_daily",
            "markets_calendar",
        ),
        feature_kinds=(
            "fundamental_ratio",
            "earnings_surprise_proxy",
            "value_score",
            "dividend_yield_signal",
        ),
        constraints=(
            "pit_available_at_for_fundamentals",
            "no_lookahead_fundamentals",
            "sparse_fins_disclosure_required",
            *_PASS_CLOSED,
        ),
        generation_enabled_by_default=True,
        priority=50,
    ),
    CLASS_FLOW_DEMAND: _spec(
        CLASS_FLOW_DEMAND,
        display_name="Flow / demand",
        horizon="5d_to_20d_flow",
        universe=("tse_prime_liquid", "tse_margin_active"),
        datasets_required=(
            "markets_margin_interest",
            "markets_short_ratio",
            "markets_short_sale_report",
            "equities_investor_types",
            "equities_bars_daily",
            "markets_calendar",
        ),
        feature_kinds=(
            "flow_delta",
            "demand_pressure",
            "positioning_level",
            "investor_type_imbalance",
        ),
        constraints=(
            "not_simple_daily_sign_rehash",
            "margin_short_gap_disclosure_required",
            "multi_day_or_level_structure",
            *_PASS_CLOSED,
        ),
        generation_enabled_by_default=True,
        priority=60,
    ),
    CLASS_SIMPLE_DAILY_SIGN: _spec(
        CLASS_SIMPLE_DAILY_SIGN,
        display_name="Simple daily sign",
        horizon="1d_nextday_close_to_close",
        universe=("tse_prime_liquid",),
        datasets_required=(
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ),
        feature_kinds=(
            "daily_sign",
            "nextday_return",
            "topix_relative_1d",
        ),
        constraints=(
            "s1_s5_remain_research_baseline_rejected",
            "default_generation_off",
            "explicit_opt_in_only",
            "not_mass_default",
            "lowest_priority_class",
            "standard_eval_checklist_required",
            "pass_does_not_connect_ready_mass",
            "no_unreject_without_human_decision",
        ),
        generation_enabled_by_default=False,
        priority=_SIMPLE_DAILY_SIGN_PRIORITY,
        opt_in_required=True,
    ),
}


ALL_CLASS_IDS: tuple[str, ...] = tuple(
    sorted(
        HYPOTHESIS_CLASS_REGISTRY.keys(),
        key=lambda cid: (
            HYPOTHESIS_CLASS_REGISTRY[cid].priority,
            cid,
        ),
    )
)

DEFAULT_GENERATION_CLASS_IDS: tuple[str, ...] = tuple(
    cid
    for cid in ALL_CLASS_IDS
    if HYPOTHESIS_CLASS_REGISTRY[cid].generation_enabled_by_default
)


def get_hypothesis_class(class_id: str) -> HypothesisClassSpec:
    """Return class spec or raise KeyError."""
    key = str(class_id).strip()
    if key not in HYPOTHESIS_CLASS_REGISTRY:
        raise KeyError(
            f"unknown hypothesis class {class_id!r}; "
            f"known={list(ALL_CLASS_IDS)}"
        )
    return HYPOTHESIS_CLASS_REGISTRY[key]


def list_hypothesis_classes(
    *,
    generation_enabled_only: bool = False,
) -> tuple[HypothesisClassSpec, ...]:
    """Return specs ordered by priority (ascending)."""
    specs = tuple(HYPOTHESIS_CLASS_REGISTRY[cid] for cid in ALL_CLASS_IDS)
    if generation_enabled_only:
        specs = tuple(s for s in specs if s.generation_enabled_by_default)
    return specs


def default_generation_class_ids() -> tuple[str, ...]:
    """Classes eligible for default idea generation (no simple_daily_sign)."""
    return DEFAULT_GENERATION_CLASS_IDS


def is_simple_daily_sign(class_id: str) -> bool:
    return str(class_id).strip() == CLASS_SIMPLE_DAILY_SIGN


def is_generation_enabled(
    class_id: str,
    *,
    explicit_opt_in: Sequence[str] | None = None,
) -> bool:
    """True if class may be used in idea generation (opt-in for simple_daily_sign)."""
    spec = get_hypothesis_class(class_id)
    opt_in = {str(x).strip() for x in (explicit_opt_in or ()) if str(x).strip()}
    if spec.generation_enabled_by_default and not spec.opt_in_required:
        return True
    if spec.opt_in_required or not spec.generation_enabled_by_default:
        return spec.class_id in opt_in
    return False


def select_generation_classes(
    *,
    n: int | None = None,
    explicit_opt_in: Sequence[str] | None = None,
    include_simple_daily_sign: bool = False,
    class_ids: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Select hypothesis classes. simple_daily_sign is opt-in only."""
    opt_in_list = list(explicit_opt_in or ())
    if include_simple_daily_sign and CLASS_SIMPLE_DAILY_SIGN not in {
        str(x).strip() for x in opt_in_list
    }:
        opt_in_list.append(CLASS_SIMPLE_DAILY_SIGN)

    if class_ids is not None:
        candidates = [str(x).strip() for x in class_ids if str(x).strip()]
    else:
        candidates = list(DEFAULT_GENERATION_CLASS_IDS)
        for cid in opt_in_list:
            c = str(cid).strip()
            if c and c not in candidates:
                candidates.append(c)

    selected = [
        cid
        for cid in dict.fromkeys(candidates)
        if is_generation_enabled(cid, explicit_opt_in=opt_in_list)
    ]
    selected.sort(
        key=lambda c: (
            HYPOTHESIS_CLASS_REGISTRY[c].priority
            if c in HYPOTHESIS_CLASS_REGISTRY
            else 10_000,
            c,
        )
    )

    if n is not None:
        if n < 0:
            raise ValueError("n must be >= 0")
        selected = selected[: int(n)]

    assert_generation_mix_not_skewed(selected)
    return tuple(selected)


def assert_generation_mix_not_skewed(
    class_ids: Sequence[str],
    *,
    max_simple_daily_sign_share: float = 0.34,
) -> None:
    """Fail closed if mix is simple_daily_sign-only or majority-skewed."""
    ids = [str(x).strip() for x in class_ids if str(x).strip()]
    if not ids:
        return
    n_simple = sum(1 for c in ids if is_simple_daily_sign(c))
    if n_simple == 0:
        return
    if len(ids) == 1 and n_simple == 1:
        raise ValueError(
            "generation mix must not be simple_daily_sign-only "
            "(not mass-default; use multi-class mix or non-daily classes)"
        )
    share = n_simple / float(len(ids))
    if share > float(max_simple_daily_sign_share) + 1e-15:
        raise ValueError(
            f"generation mix skewed to simple_daily_sign "
            f"(share={share:.2f} > max={max_simple_daily_sign_share}): {ids}"
        )


def build_research_idea_payload(
    *,
    class_id: str,
    idea_id: str,
    hypothesis: str,
    author: str,
    explicit_opt_in: Sequence[str] | None = None,
    extra_constraints: Sequence[str] | None = None,
    extra_lineage: Mapping[str, Any] | None = None,
    allow_disabled_class: bool = False,
) -> dict[str, Any]:
    """Build a ResearchIdea-compatible dict from a hypothesis class."""
    spec = get_hypothesis_class(class_id)
    if not allow_disabled_class and not is_generation_enabled(
        class_id, explicit_opt_in=explicit_opt_in
    ):
        raise ValueError(
            f"hypothesis class {class_id!r} is not generation-enabled "
            f"(simple_daily_sign and other opt-in classes require "
            f"explicit_opt_in; default generation OFF for "
            f"{CLASS_SIMPLE_DAILY_SIGN!r})"
        )
    defaults = spec.research_idea_defaults()
    constraints = list(defaults["constraints"])
    if extra_constraints:
        constraints.extend(str(x) for x in extra_constraints)
    lineage = dict(defaults["lineage"])
    if extra_lineage:
        lineage.update(dict(extra_lineage))
    return {
        "idea_id": str(idea_id).strip(),
        "hypothesis": str(hypothesis).strip(),
        "target_horizon": defaults["target_horizon"],
        "intended_universe": list(defaults["intended_universe"]),
        "candidate_concepts": list(defaults["candidate_concepts"]),
        "constraints": constraints,
        "author": str(author).strip(),
        "lineage": lineage,
        "version": "research-idea/v1",
    }


def hypothesis_class_registry_document() -> dict[str, Any]:
    """Public document for the hypothesis class registry."""
    return {
        "version": REGISTRY_VERSION,
        "simple_daily_sign_default_enabled": False,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "edge_claimed": EDGE_CLAIMED,
        "mass_generate_signals": MASS_GENERATE_SIGNALS,
        "s1_s5_unreject": S1_S5_UNREJECT,
    }


def assert_registry_closed_to_ready_mass(
    doc: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed if registry document ever arms READY/Mass."""
    body = dict(doc) if doc is not None else hypothesis_class_registry_document()
    closed_false = (
        ("ready_declared", "hypothesis registry must keep ready_declared=False"),
        ("operational_go", "hypothesis registry must keep operational_go=False"),
        ("connected_to_ready", "hypothesis registry must keep connected_to_ready=False"),
        ("connected_to_mass", "hypothesis registry must keep connected_to_mass=False"),
        ("mass_generate_signals", "hypothesis registry must not mass-generate signals"),
        ("edge_claimed", "hypothesis registry must not claim edge"),
        ("s1_s5_unreject", "hypothesis registry must not un-reject S1–S5"),
        ("simple_daily_sign_default_enabled", "simple_daily_sign must remain default generation OFF"),
    )
    for key, msg in closed_false:
        if body.get(key) is not False:
            raise AssertionError(msg)
    if body.get("mass_research") != MASS_RESEARCH:
        raise AssertionError(
            f"hypothesis registry mass_research must be {MASS_RESEARCH}"
        )
    if body.get("phase7") != PHASE7:
        raise AssertionError(f"hypothesis registry phase7 must be {PHASE7}")


def assert_simple_daily_sign_not_default_enabled() -> None:
    """Unit/guard helper: simple_daily_sign is not in default generation set."""
    spec = get_hypothesis_class(CLASS_SIMPLE_DAILY_SIGN)
    if spec.generation_enabled_by_default:
        raise AssertionError(
            "simple_daily_sign.generation_enabled_by_default must be False"
        )
    if not spec.opt_in_required:
        raise AssertionError("simple_daily_sign.opt_in_required must be True")
    if CLASS_SIMPLE_DAILY_SIGN in DEFAULT_GENERATION_CLASS_IDS:
        raise AssertionError(
            "simple_daily_sign must not appear in DEFAULT_GENERATION_CLASS_IDS"
        )
    if is_generation_enabled(CLASS_SIMPLE_DAILY_SIGN):
        raise AssertionError(
            "simple_daily_sign must not be generation-enabled without opt-in"
        )
    if is_generation_enabled(
        CLASS_SIMPLE_DAILY_SIGN,
        explicit_opt_in=(CLASS_SIMPLE_DAILY_SIGN,),
    ) is not True:
        raise AssertionError(
            "simple_daily_sign must be generation-enabled with explicit opt-in"
        )


def validate_all_classes_have_required_fields() -> None:
    """Raise if any registered class is missing required fields."""
    for cid, spec in HYPOTHESIS_CLASS_REGISTRY.items():
        d = spec.to_dict()
        for field in REQUIRED_CLASS_FIELDS:
            if field not in d:
                raise AssertionError(f"{cid}: missing required field {field}")
            val = d[field]
            if val is None:
                raise AssertionError(f"{cid}: required field {field} is None")
            if field in {
                "horizon",
                "universe",
                "datasets_required",
                "feature_kinds",
                "constraints",
            } and not val:
                raise AssertionError(f"{cid}: required field {field} is empty")


__all__ = [
    "ALL_CLASS_IDS",
    "CLASS_CROSS_SECTION_RELATIVE",
    "CLASS_EVENT_POST",
    "CLASS_FLOW_DEMAND",
    "CLASS_FUNDAMENTALS_PRICE",
    "CLASS_MACRO_CONDITIONED",
    "CLASS_MULTI_DAY_HOLD",
    "CLASS_SIMPLE_DAILY_SIGN",
    "DEFAULT_GENERATION_CLASS_IDS",
    "HYPOTHESIS_CLASS_REGISTRY",
    "HypothesisClassSpec",
    "MASS_RESEARCH",
    "PHASE7",
    "READY_DECLARED",
    "REGISTRY_VERSION",
    "REGISTRY_WAVE",
    "REQUIRED_CLASS_FIELDS",
    "assert_generation_mix_not_skewed",
    "assert_registry_closed_to_ready_mass",
    "assert_simple_daily_sign_not_default_enabled",
    "build_research_idea_payload",
    "default_generation_class_ids",
    "get_hypothesis_class",
    "hypothesis_class_registry_document",
    "is_generation_enabled",
    "is_simple_daily_sign",
    "list_hypothesis_classes",
    "select_generation_classes",
    "validate_all_classes_have_required_fields",
]
