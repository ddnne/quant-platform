"""UNARMED paper receptacle: class_hyp / research candidate → StrategySpec.

Closed envelope with nested StrategySpec plus horizon / costs / universe /
rebalance. Does not arm the paper scheduler, call ``run_paper``, or touch
the live order path. Mass NO-GO · Phase7 OFF · READY undeclared · GO closed.
``research_candidate`` is never auto-promoted. Hostile arm/live/go input is
stripped. Residuals stay on the envelope. Do not simplify research.

Builders live in ``paper_candidate_specs``; adapt/envelope in
``paper_candidate_adapt``. This module re-exports the public surface.
"""

from __future__ import annotations

from research.freezes import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    EDGE_CLAIMED,
    LIVE_ORDER_PATH_ENABLED,
    LIVE_ORDERS,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    PAPER_CONTINUOUS,
    PAPER_SCHEDULER_ARMED,
    PHASE7,
    READY_DECLARED,
    SIGNIFICANCE_CLAIMED,
)
from research.paper_candidate_adapt import (
    PAPER_CANDIDATE_ADAPTER_VERSION,
    PAPER_CANDIDATE_SPEC_VERSION,
    PAPER_CANDIDATE_WAVE,
    DEFAULT_ONE_WAY_COST,
    PaperCandidateReceptacle,
    adapt_class_hyp_candidate,
    adapt_from_class_hyp_bundle,
    assert_unarmed,
    emit_example_paper_specs,
    example_event_post_payload,
    example_multi_day_hold_10d_payload,
)
from research.paper_candidate_specs import (
    DEFAULT_CS_LONG_FRAC,
    DEFAULT_CS_MOMENTUM_N,
    DEFAULT_CS_SHORT_FRAC,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_TOP_K,
    build_cross_section_hold_strategy_spec,
    build_event_post_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)

__all__ = [
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "DEFAULT_CS_LONG_FRAC",
    "DEFAULT_CS_MOMENTUM_N",
    "DEFAULT_CS_SHORT_FRAC",
    "DEFAULT_FUND_MOMENTUM_N",
    "DEFAULT_ONE_WAY_COST",
    "DEFAULT_TOP_K",
    "EDGE_CLAIMED",
    "LIVE_ORDER_PATH_ENABLED",
    "LIVE_ORDERS",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PAPER_CANDIDATE_ADAPTER_VERSION",
    "PAPER_CANDIDATE_SPEC_VERSION",
    "PAPER_CANDIDATE_WAVE",
    "PAPER_CONTINUOUS",
    "PAPER_SCHEDULER_ARMED",
    "PHASE7",
    "READY_DECLARED",
    "SIGNIFICANCE_CLAIMED",
    "PaperCandidateReceptacle",
    "adapt_class_hyp_candidate",
    "adapt_from_class_hyp_bundle",
    "assert_unarmed",
    "build_cross_section_hold_strategy_spec",
    "build_event_post_strategy_spec",
    "build_fundamentals_hold_strategy_spec",
    "build_multi_day_hold_strategy_spec",
    "emit_example_paper_specs",
    "example_event_post_payload",
    "example_multi_day_hold_10d_payload",
]
