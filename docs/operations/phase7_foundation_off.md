# Phase 7 Foundation — OFF (operations note)

**Status: OFF / foundation only.**  
Mass Autonomous Research is **not** enabled. READY / B0 production GO is **not**
declared. This note records the fail-closed surface so operators do not treat
schema/stubs as a live switch.

Related architecture note: [docs/architecture/phase7_fail_closed.md](../architecture/phase7_fail_closed.md)  
Residual SoT: [docs/phase62_residual_status.md](../phase62_residual_status.md)

## Explicit non-claims

| Claim | State |
|-------|--------|
| Mass Autonomous Research ON | **NO** |
| Phase 7 production ready / READY GO | **NO** |
| B0 production gate satisfied | **NO** |
| Env/flag that flips Phase 7 mass research ON | **None** (default remain closed) |

There is **no** `PHASE7_*`, `MASS_RESEARCH_ENABLE`, or similar environment switch
that arms mass research. Presence of stubs (`knowledge/`, `selection/`,
`gateway/`, `research/`) is scaffolding only.

## Fail-closed entry points (code)

| Path | Behavior when mass start is attempted without readiness |
|------|----------------------------------------------------------|
| `agents/mass_research.py` → `start_mass_research` | Requires `ResearchBudgetCapability` + `VerifiedResearchReadiness`; rejects `operator_override` and caller-supplied `ready_count` / `governed_*` / `go_override` with `MassResearchDisabledError` |
| `research/readiness.py` → `require_mass_research_start` | Fail-closed if budget or readiness missing/invalid/expired |
| `selection/budget_ledger.py` → `require_budget_capability` | `MassResearchDisabledError` if capability is `None`; hard token caps required on `ResearchBudgetCapability` |
| `research/scheduler.py` → `ExperimentScheduler.schedule` | Re-checks readiness signature before lease |
| `data_access/service.py` ops claims | Hardcodes `"mass_research": "NO-GO"` |

Operator overrides (`OperatorOverrideService`) are limited to non-safety scopes
(`hold_period`, `selection_threshold`, `single_extra_experiment`). Scope
`mass_research` is rejected.

## Foundation artifacts present (not an enablement)

- Budget / lease ledger: `selection/budget_ledger.py`
- Selection screen + `ExperimentBudget`: `selection/screen.py`
- Closed-schema AI gateway: `gateway/ai.py` (default offline stub provider)
- Knowledge store stub: `knowledge/store.py`
- Research idea/plan types: `research/artifacts.py` (lineage only; mass loop OFF)
- Readiness attestation types: `research/readiness.py` (mint requires verified READY snapshot)

## Offline verification

```bash
pytest -q \
  tests/test_mass_research_gate.py \
  tests/test_research_budget_ledger.py \
  tests/test_phase622_remainder.py \
  tests/test_phase7_gateway.py \
  tests/test_phase7_selection.py \
  tests/test_phase7_knowledge.py \
  tests/test_phase7_pipeline_budget.py \
  tests/test_gateway_fail_closed.py
```

Expect mass-start paths to raise `MassResearchDisabledError` without a valid
`VerifiedResearchReadiness` + budget capability.

## Operator rule

Do **not** interpret merge of foundation docs or stubs as authorization to run
mass autonomous research. Enabling is a separate, explicit human decision after
production READY ≥1 and real Coverage V2 COMPLETE evidence exist (see residual
status). Until then: **switch remains OFF**.
