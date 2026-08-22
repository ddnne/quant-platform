"""UNARMED paper receptacle. Implementation: ``paper_candidate_adapt``."""

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
