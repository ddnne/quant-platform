# Phase 7 Foundation — fail-closed only

**Switch status: OFF.** Mass Autonomous Research, production LLM loops, and
READY/B0 production gates must remain disabled. This document is foundation
only (schema / isolation / budget lease concepts). Enabling switches is a
separate, explicit human decision — never implied by merge of this file.

**Mass Autonomous Research: NO-GO (switch remains closed)**

Operations checklist (entry points, offline tests):  
[docs/operations/phase7_foundation_off.md](../operations/phase7_foundation_off.md)

Foundation scope only (no production LLM autonomy, no live broker):

1. Schema for research budgets / leases (`selection/budget_ledger.py`, `selection/screen.py`)
2. Isolation boundaries between research agents and ingestion control plane
3. Fail-closed gates: `agents/mass_research.py` + `research/readiness.require_mass_research_start`
   require signed `VerifiedResearchReadiness`; operator override cannot substitute
4. No env/flag that arms mass research (`PHASE7_*` / enable switches do not exist)
5. No “P0=0” or “Phase 7 production ready” / READY / B0 declarations without explicit human GO

Switches stay off. Residual SoT: [docs/phase62_residual_status.md](../phase62_residual_status.md).
