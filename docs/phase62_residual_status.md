# Phase 6.2 residual status (honest)

**HEAD**: `git log -1`  
**Track**: GLM parallel + orchestrated land

## Code-complete

| Item | Evidence |
|------|----------|
| 31-endpoint inventory (26 governed + 5 experimental) | `data_contracts/canonical_datasets.json`, `inventory.py` |
| Ops projection publisher + D1 apply (no SQL BEGIN) | `scripts/publish_ops_projection.py` applied remote successfully |
| Coverage V2 plan granularities (month/year/day/file) | `storage/coverage_ledger.py` |
| Local ledger refresh | `scripts/refresh_coverage_ledger.py` → 26 PARTIAL (honest, no receipts) |
| Remote Ops 16 tools + migration 0003 + redeploy | Worker live |
| Sync → optional `--publish-ops` / `--apply-remote-ops` | `scripts/sync_d1_to_sqlite.py` |
| Phase 7 stubs | `knowledge/`, `selection/`, `gateway/` |
| Offline pytest | keep green on land |

## Live operational (still open)

| Item | Status |
|------|--------|
| Coverage COMPLETE (needs real collection receipts + full backfill) | **Open** — all governed PARTIAL/UNKNOWN with 0 receipts |
| Production READY ≥1 | **Open** — coherence correctly blocks |
| Full multi-year JQ/JSDA backfill finished | **Open** — requires long live runs (credentials present; not fully executed here) |
| Cron auto-projection without any human flag | **Partial** — flag exists; CF cron wiring not claimed complete |

## Phase 7 mass research

**NO-GO** until READY + real COMPLETE evidence.

## Parallel GLM

Lanes C/D/E/F continue polish on worktrees; merge when green.
