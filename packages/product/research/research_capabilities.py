"""Typed research execution capabilities. Not caller booleans. Not GO.

Mass screen / daily path / proposal require these. Env flags alone are
not evidence; they can only deny. READY evidence is required to grant.
"""
from __future__ import annotations

from typing import Any, Mapping

MASS_RESEARCH_NO_GO: str = "NO-GO"


def research_capabilities(env: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Deny-by-default capability snapshot. Does not mint READY."""
    env = dict(env or {})
    mass = str(env.get("MASS_RESEARCH") or MASS_RESEARCH_NO_GO).strip() or MASS_RESEARCH_NO_GO
    phase7 = str(env.get("PHASE7") or "OFF").strip() or "OFF"
    ready_declared = str(env.get("READY_DECLARED") or "false").strip().lower() == "true"
    operational_go = str(env.get("OPERATIONAL_GO") or "false").strip().lower() == "true"
    paper = str(env.get("CONTINUOUS_PAPER") or "UNARMED").strip() or "UNARMED"
    token_bound = bool(str(env.get("MASS_EVAL_TOKEN") or "").strip())
    ready_attestation = env.get("verified_readiness")
    reasons: list[str] = []
    if mass != "GO":
        reasons.append("mass_research_no_go")
    if not ready_declared:
        reasons.append("ready_not_declared")
    if ready_attestation is None:
        reasons.append("verified_readiness_missing")
    if not token_bound:
        reasons.append("eval_token_unbound")
    if phase7 != "ON":
        reasons.append("phase7_off")
    if not operational_go:
        reasons.append("operational_go_false")
    if paper != "ARMED":
        reasons.append("paper_unarmed")
    granted = False
    return {
        "data_ready": granted,
        "generation": granted,
        "mass_screen": granted,
        "promotion": granted,
        "paper_execution": granted,
        "reasons": reasons,
        "mass_research": mass,
        "phase7": phase7,
        "ready_declared": ready_declared,
        "operator_override": False,
        "go": False,
        "not_a_pass": True,
    }


def require_capability(name: str, caps: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Raise-free refuse pack. Caller maps to HTTP 403. Does not GO."""
    snap = dict(caps or research_capabilities())
    allowed = bool(snap.get(name))
    return {
        "capability": name,
        "allowed": allowed,
        "reasons": list(snap.get("reasons") or []),
        "go": False,
        "not_a_pass": True,
    }
