"""Schema for the next profit-hypothesis proposal (not an eval warehouse).

Read existing theses + weakness flags from R2
``research/eval/job={id}/summary_family.json`` then propose a payload that
differs in information source, entry rule, or position construction — never
hold_days/momentum_n alone.
"""
from __future__ import annotations

from typing import Any, Mapping

PROPOSAL_SCHEMA_VERSION: str = "research-hyp-proposal/v1"

# Combination/funds may use simple gated theses. Do not cull the pool with
# a t/Sharpe floor. Exclude only path_broken, always_on, and near_empty.
CANDIDATE_KEEP_SIMPLE: str = (
    "Simple occupancy-gated theses stay in the candidate pool for later "
    "combination/funds even when single-name t/Sharpe is modest. "
    "path_broken, always_on, and near_empty are excluded."
)

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


def weakness_flags_from_summary(summary: Mapping[str, Any]) -> dict[str, list[str]]:
    """Read ``summary_family.json`` weakness flags. Does not execute a proposal."""
    out: dict[str, list[str]] = {}
    for row in summary.get("logics") or []:
        if not isinstance(row, Mapping):
            continue
        lid = str(row.get("logic_id") or "").strip()
        if not lid:
            continue
        flags = [str(x) for x in (row.get("flags") or [])]
        tag = str(row.get("tag") or "")
        if tag and tag not in flags:
            flags = [*flags, f"tag:{tag}"]
        out[lid] = flags
    return out


def proposal_blocked_by_summary(
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[str]:
    """Return reasons a proposal is blocked by known path/occupancy flags.

    Numeric hold/mom clones of a path_broken or always_on parent are rejected.
    """
    flags = weakness_flags_from_summary(summary)
    reasons: list[str] = []
    parents = [str(x) for x in (payload.get("why_different_from") or [])]
    for parent in parents:
        pf = flags.get(parent) or []
        if "path_broken" in pf:
            reasons.append(f"parent_path_broken:{parent}")
        if "always_on" in pf and not payload.get("signal_definition"):
            reasons.append(f"parent_always_on_needs_new_signal:{parent}")
    return reasons
