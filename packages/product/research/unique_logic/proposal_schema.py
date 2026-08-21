"""Schema for the next profit-hypothesis proposal (not an eval warehouse).

Read existing theses + weakness flags from R2
``research/eval/job={id}/summary_family.json`` then propose a payload that
differs in information source, entry rule, or position construction — never
hold_days/momentum_n alone.
"""
from __future__ import annotations

from typing import Any

PROPOSAL_SCHEMA_VERSION: str = "research-hyp-proposal/v1"

PROPOSAL_REQUIRED_KEYS: tuple[str, ...] = (
    "logic_id",
    "thesis",
    "signal_definition",
    "position_rule",
    "datasets",
    "why_different_from",
)

PROPOSAL_EXAMPLE: dict[str, Any] = {
    "schema": PROPOSAL_SCHEMA_VERSION,
    "logic_id": "example_easing_pead",
    "thesis": "PEAD occupancy only when overnight Tokyo repo fell versus the prior print.",
    "signal_definition": "surprise-sign hold iff overnight[t] < overnight[t-1]; missing → skip",
    "position_rule": "PIT post-hold; skip when overnight gap; no ffill",
    "datasets": [
        "fins_summary",
        "jsda_tokyo_repo_rates",
        "equities_bars_daily",
    ],
    "why_different_from": [
        "event_funding_stress_skip uses PIT median level, not a one-day change",
    ],
    "forbidden": [
        "hold_days-only clone",
        "momentum_n-only clone",
        "sign-flip of a parent presented as a kill",
    ],
    "promote_as_main": False,
    "go": False,
}


def validate_proposal(payload: dict[str, Any]) -> list[str]:
    missing = [k for k in PROPOSAL_REQUIRED_KEYS if not payload.get(k)]
    return missing
