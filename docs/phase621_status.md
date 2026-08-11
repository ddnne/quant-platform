# Phase 6.2.1 status (honest)

**HEAD**: see `git log -1`  
**Developer**: GLM (+ orchestrated land)  
**Backfill**: left running (do not stop)

## Landed on main

| Item | Status |
|------|--------|
| P0 receipt eligibility TRUSTED vs RECOVERED_RAW_ONLY | ✅ `d0d2bcd` |
| rebuild_from_raw non-COMPLETE-eligible | ✅ |
| JSDA corporate → jsda_bond_trades mapping | ✅ |
| Coherence latest receipt + change_seq>0 | ✅ |
| MCP governed.js generated from coverage SoT | ✅ `36c7398` |
| ResearchBudgetCapability SQLite ledger | ✅ |
| PaperExecutionService foundation | ✅ |

## In flight (GLM lanes A–G)

Canonical endpoints metadata, READY policy unify, ops projection states, AM SLA,
ImmutableArtifactStore, AI gateway typed, agent capability — worktrees `/tmp/qp-621-*`

## Still open / long

- Full READY PublicationPolicy consolidation
- Live 26/26 COMPLETE + READY≥1 (backfill)
- JSDA live + publication lag semantics polish
- quant-mcp redeploy tools/list==16
- Phase 7 mass research: **NO-GO**

## Priority remaining

1. Land/merge GLM lanes when green  
2. Typed AI gateway + ImmutableArtifactStore  
3. Orchestrator run_paper → PaperExecutionService  
4. MCP redeploy + inventory path metadata  
