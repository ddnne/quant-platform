"""UNARMED paper receptacle: class_hyp / research candidate → StrategySpec.

Closed envelope. Does not arm the paper scheduler, call ``run_paper``, or
touch the live order path. Mass NO-GO · Phase7 OFF · READY undeclared ·
GO closed. ``research_candidate`` is never auto-promoted.

Builders live in ``paper_candidate_specs``; adapt/envelope in
``paper_candidate_adapt``. This module re-exports the adapt surface.
"""

from __future__ import annotations

from research.paper_candidate_adapt import (
    PAPER_CANDIDATE_SPEC_VERSION,
    PaperCandidateReceptacle,
    adapt_class_hyp_candidate,
    adapt_from_class_hyp_bundle,
    assert_unarmed,
    emit_example_paper_specs,
    example_event_post_payload,
    example_multi_day_hold_10d_payload,
)

__all__ = [
    "PAPER_CANDIDATE_SPEC_VERSION",
    "PaperCandidateReceptacle",
    "adapt_class_hyp_candidate",
    "adapt_from_class_hyp_bundle",
    "assert_unarmed",
    "emit_example_paper_specs",
    "example_event_post_payload",
    "example_multi_day_hold_10d_payload",
]
