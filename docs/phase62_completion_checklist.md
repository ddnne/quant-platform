# Phase 6.2 Completion Checklist

**Status**: 6/9 P0 COMPLETE (67%) | 0/3 P1 COMPLETE (0%)

## P0 Tasks (Critical — Must be 0 for Phase 7)

- [x] **P0-1**: Dataset membership unified (25/26 split fixed)
  - Added `jsda_corporate_bond_transactions` to coverage contracts
  - Added `official_archive_year` granularity support
  - All 26 datasets consistent across Python/TypeScript/JSON
  - Commits: `24c395e`, `d75cffe`

- [x] **P0-2**: Canonical dataset registry created
  - Created `data_contracts/canonical_datasets.json` with all 26 datasets
  - Implemented `canonical.py` with validation and consistency checks
  - All downstream registries validated as subsets
  - Commit: `1463e15`

- [x] **P0-3**: Ops projection operational
  - Manual export via `scripts/export_ops_projection.py` working
  - Remote Ops MCP can read projection data
  - Deferred full automation to Phase 6.3 (manual is safe/auditable)
  - Status: OPERATIONAL

- [x] **P0-4**: Coverage V2 implementation correct
  - Core ledger uses segment receipts, not min/max row counts
  - Tests validate segment-based evaluation
  - Min/max bounds are diagnostics only
  - Status: VERIFIED CORRECT

- [x] **P0-5**: Raw retention operational
  - Coverage V2 contracts require raw retention
  - Receipts include raw digests and manifest keys
  - R2 bucket configuration validated
  - Status: OPERATIONAL

- [x] **P0-6**: READY publish coherence gate implemented
  - Created `paper_runtime/coherence.py` with comprehensive gates
  - Gates: coverage completeness, receipts with raw, validation, natural keys, B0 quality, change seq
  - Exported from `paper_runtime` for integration
  - Commit: `48d9700`
  - Status: IMPLEMENTED (needs integration into publish_ready_snapshot)

- [x] **P0-7**: Remote Ops tools complete
  - 12 ops tools defined in `platform/workers/quant-ops-mcp/src/domain.js`
  - GitHub OAuth read-only authentication working
  - Tools: ops_status, coverage_gaps, dataset_coverage, backfill_status, etc.
  - Status: COMPLETE

- [ ] **P0-8**: Documentation drift fixed
  - Need Phase 6.1/6.2 boundary clarification
  - Update runbook with latest dataset count (26)
  - Fix roadmap inconsistencies
  - Status: IN PROGRESS

- [ ] **P0-9**: Test audit and consolidation
  - Audit test suite for redundant negative tests
  - Consolidate to strong invariant tests
  - Ensure P0 fixes have test coverage
  - Status: IN PROGRESS

## P1 Tasks (Important — Complete before full production)

- [ ] **P1-1**: Complete endpoint inventory (~31 endpoints)
  - Full endpoint documentation and monitoring
  - Integration with ops MCP tools
  - Status: PENDING

- [ ] **P1-2**: Real data backfill executed
  - Execute historical backfill per Phase 6.1 runbook
  - Verify coverage V2 receipts for all segments
  - Confirm raw retention for backfilled data
  - Status: PENDING

- [ ] **P1-3**: Production READY ≥1 achieved
  - Execute full production run
  - Publish first complete READY snapshot
  - Verify all coherence gates passed
  - Status: PENDING

## Phase 7 Prerequisites (After P0=0, P1 Complete)

### Knowledge Store
- [ ] Minimal knowledge store implementation
- [ ] Feature quality metadata tracking
- [ ] No unrestricted Python execution
- [ ] Budget constraints and early stopping

### Selection Gateway
- [ ] Closed-schema only
- [ ] No live broker integration
- [ ] No FoF complexity initially

### AI Gateway
- [ ] Closed-schema LLM calls only
- [ ] Experiment budget tracking
- [ ] Early stopping mechanisms
- [ ] No infinite research loops

## Verification Steps

Before printing `PHASE62_DONE`, verify:

- [ ] All P0 tasks complete (9/9)
- [ ] All tests pass: `pytest -q`
- [ ] Git log shows small reviewable commits
- [ ] READY snapshot achievable
- [ ] Phase 7 prerequisites documented
- [ ] Final report format matches instruction §29

## Recent Commits

```
48d9700 feat(runtime): implement READY publish coherence gate (P0-6)
1463e15 feat(contracts): add canonical dataset registry (P0-2)
d75cffe fix(coverage): add official_archive_year granularity and JSDA corporate transactions
24c395e fix(coverage): add jsda_corporate_bond_transactions to Coverage V2
7a0ff21 feat(mcp): GitHub OAuth remote Ops MCP (news-mcp pattern)
```

## Estimated Timeline

- **P0 remaining**: 1-2 days focused work (documentation + test audit)
- **P1 tasks**: 1-2 weeks including backfill execution
- **Phase 6.2 complete**: 2-3 weeks total from start
- **Phase 7 start**: Only after P0=0 and first production READY

---

**Last updated**: 2026-08-11  
**P0 Progress**: 6/9 COMPLETE (67%) | **P1 Progress**: 0/3 COMPLETE (0%)
