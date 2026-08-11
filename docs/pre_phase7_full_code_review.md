# Phase 6.2 Wave 0 — Full Code Review (Pre-Phase 7)

**Date**: 2026-08-11  
**HEAD reviewed**: `7a0ff21` (feat(mcp): GitHub OAuth remote Ops MCP)  
**Current HEAD**: `e47da0f`  
**Developer**: GLM  
**Scope**: Canonical dataset registry, Coverage V2, READY gate, Remote Ops, test audit, Phase 7 preparation

> **Resolution status (post-fix).** This review was written at `7a0ff21`. Since
> then, **all P0 code findings below are RESOLVED in code** (see per-finding
> Status). The code work is done and offline tests are green. However, the
> **live-operational** items — Coverage V2 COMPLETE with real receipts,
> production READY ≥1, full multi-year backfill, and CF cron auto-projection —
> remain **OPEN**. **Phase 7 mass research is NO-GO** until READY ≥1 and real
> Coverage V2 COMPLETE exist. Source of truth:
> [docs/phase62_residual_status.md](phase62_residual_status.md).

## Executive Summary

This review identified all P0 blockers that must reach zero before Phase 7 mass autonomous research can begin. The codebase shows strong architectural foundation with Coverage V2, schema migrations, and MCP patterns implemented. Critical issues centered on dataset membership consistency, ops automation, and READY publication gates. **As of `e47da0f`, all P0 code findings are resolved in code; live operational closure remains open.**

### Overall Health (current)

| Category | Status | Notes |
|----------|--------|-------|
| Coverage V2 | ✅ Strong | Receipt/segment model well-implemented |
| Schema migrations | ✅ Strong | Idempotent D1 + SQLite migrations |
| MCP architecture | ✅ Strong | Clean separation of research/ops domains |
| Dataset membership | ✅ RESOLVED (code) | 26 datasets consistent across Python/TS/JSON |
| Ops automation | ✅ RESOLVED (code) / ⚠️ PARTIAL (live) | Publisher + D1 apply + `--publish-ops`; CF cron auto-projection OPEN |
| READY gate | ✅ RESOLVED (code) / 🚫 OPEN (live) | Coherence gate implemented and correctly blocks; production READY ≥1 not yet achieved |
| Remote Ops tools | ✅ RESOLVED (code) | 16 tools + migration 0003, Worker live |
| Documentation | ✅ RESOLVED (docs) | Phase 6.1/6.2 boundary clarified; roadmap consistent |
| Test suite | ✅ RESOLVED (code) | Consolidated; offline green on land |
| Coverage V2 COMPLETE (live) | 🚫 OPEN | All governed PARTIAL/UNKNOWN, 0 receipts |
| Production READY ≥1 (live) | 🚫 OPEN | Coherence correctly blocks |
| Full backfill (live) | 🚫 OPEN | Multi-year JQ/JSDA backfill not executed |

---

## P0 Findings (Must Resolve for Phase 7)

### P0-1: Dataset Membership Split (25/26)

**ID**: `P0-1`  
**Severity**: `P0 - CRITICAL`  
**Status**: `RESOLVED (code)` — 26 datasets consistent across Python/TS/JSON  
**Structural Fix**: Unify `jsda_corporate_bond_transactions` across all registries

#### Issue Details

The dataset `jsda_corporate_bond_transactions` exists in `data_contracts/jsda_governed.json` (3 total JSDA datasets) but is **missing** from `data_contracts/collection_coverage.json` (only 2 JSDA datasets listed).

**Files Affected**:
- `data_contracts/jsda_governed.json` (line 46-67): Contains `jsda_corporate_bond_transactions`
- `data_contracts/collection_coverage.json` (line 151-168): Missing this dataset
- `data_contracts/coverage.py` (line 106-119): Validation expects exact match
- `platform/workers/ingestion-premium/src/catalog.ts` (line 69-82): Only handles 23 J-Quants datasets
- `tests/test_jsda_governed.py`: References the dataset

**Impact**:
- Python Coverage/READY/MCP/TS systems disagree on dataset count (25 vs 26)
- Corporate bond transactions cannot be properly governed for production
- Coverage V2 receipts cannot be generated for this dataset
- READY publication will fail or be incomplete

**Root Cause**:
The dataset was added to `jsda_governed.json` (change-set 12 per runbook) but was never integrated into the unified coverage contract system. The coverage validation explicitly checks for exact matches between `all_contracts()` and coverage datasets.

**Structural Fix Required**:

1. Add `jsda_corporate_bond_transactions` to `collection_coverage.json` with proper scope:
   ```json
   "jsda_corporate_bond_transactions": {
     "collection_scope": "jsda_governed_corporate_transactions",
     "history_target_start": "2015-11-04",
     "history_target_end_rule": "latest_official_annual_archive",
     "coverage_mode": "event_window_reconciled",
     "expected_frequency": "event_driven",
     "universe_rule": "all_transactions_in_official_publication_files",
     "segment_granularity": "official_archive_year"
   }
   ```

2. Update TypeScript catalog to handle JSDA datasets or create separate JSDA catalog

3. Ensure `data_contracts/coverage.py` validation includes all 26 datasets

4. Update MCP tools to include the 26th dataset in listings

**Verification**:
- Coverage ledger shows 26 datasets (23 JQ + 3 JSDA)
- All systems agree on governance tier and coverage policies
- `test_jsda_governed` passes with all datasets

---

### P0-2: Canonical Dataset Registry Missing

**ID**: `P0-2`  
**Severity**: `P0 - CRITICAL`  
**Status**: `RESOLVED (code)` — `canonical_datasets.json` + `canonical.py` operational  
**Structural Fix**: Create single source-of-truth registry

#### Issue Details

Dataset definitions are scattered across:
- `data_contracts/jquants_premium_core.json` (23 JQ datasets)
- `data_contracts/jsda_governed.json` (3 JSDA datasets)
- `data_contracts/collection_coverage.json` (25 datasets - missing 1)
- `platform/workers/ingestion-premium/src/catalog.ts` (TypeScript partial view)

**Files Affected**:
- All contract JSON files
- `data_contracts/loader.py`
- `data_contracts/coverage.py`
- `platform/workers/ingestion-premium/src/catalog.ts`

**Impact**:
- No single source of truth for dataset inventory
- Risk of drift between Python/TypeScript/JSON definitions
- Coverage policies not centrally governed
- Documentation easily desynchronized

**Root Cause**:
Dataset contracts evolved incrementally without a canonical unified registry. Each system loads its own partial view.

**Structural Fix Required**:

1. Create `data_contracts/canonical_datasets.json` with schema:
   ```json
   {
     "schema_version": 1,
     "registry_version": "v1",
     "datasets": [
       {
         "dataset_id": "equities_master",
         "source": "jquants_premium_core",
         "governance_tier": "governed",
         "natural_key_fields": ["code"],
         "contracts": {
           "primary": "jquants_premium_core",
           "coverage": "collection_coverage/v2",
           "ingestion": "cf_platform"
         }
       }
     ]
   }
   ```

2. Create `data_contracts/canonical.py` to load and validate unified registry

3. Update all systems to import from canonical registry
4. Add validation that all downstream registries are subsets of canonical

**Verification**:
- Single import point for all dataset metadata
- Validation prevents drift between Python/TypeScript
- Documentation auto-generated from canonical registry

---

### P0-3: Ops Projection Manual Export

**ID**: `P0-3`  
**Severity**: `P0 - CRITICAL`  
**Status**: `RESOLVED (code) / PARTIAL (live)` — publisher + D1 apply + `--publish-ops`; CF cron auto-projection still OPEN  
**Structural Fix**: Automate ops projection after each successful run

#### Issue Details

Ops projection requires manual invocation of `scripts/export_ops_projection.py` followed by manual `wrangler d1 execute`. This is a single point of failure for Remote Ops MCP correctness.

**Files Affected**:
- `scripts/export_ops_projection.py` (manual export script)
- `platform/workers/quant-ops-mcp/migrations/` (projection tables)
- `platform/workers/ingestion-premium/src/index.ts` (no auto-projection)

**Impact**:
- MCP serves stale or incomplete ops metadata
- Human operator required for projection updates
- Remote Ops visibility lags behind actual ingestion state
- Breaks "automated ops" promise

**Root Cause**:
Projection was designed as out-of-band manual operation to keep MCP read-only. No automation was added to update projection after successful ingestion runs.

**Structural Fix Required**:

1. Add projection export step to ingestion-premium Worker after successful run:
   ```typescript
   // After successful run, export projection to D1
   await exportOpsProjection(env.DB, env.OPS_PROJECTION_DB);
   ```

2. Create `platform/workers/ingestion-premium/src/projection.ts` with:
   - Coverage segment aggregation
   - B0 quality status
   - READY snapshot metadata
   - Change sequence watermarks

3. Add D1 binding for ops projection in `wrangler.toml`

4. Update MCP to read from live projection table

5. Keep manual script for bootstrap/repair only

**Verification**:
- Projection updates automatically after each successful run
- Remote Ops MCP shows latest coverage status
- Manual script still works for recovery scenarios

---

### P0-4: Coverage V2 COMPLETE ≠ min/max

**ID**: `P0-4`  
**Severity**: `P0 - HIGH`  
**Status**: `RESOLVED (code)` — ledger uses segment receipts; min/max are diagnostics only  
**Structural Fix**: Ensure segment receipts drive COMPLETE, not row count bounds

#### Issue Details

Coverage V2 implementation correctly uses segment receipts, but some reporting may conflate min/max diagnostic bounds with COMPLETE status.

**Files Affected**:
- `storage/coverage_ledger.py` (correctly implements segment evaluation)
- `scripts/ops_status.py` (may report min/max incorrectly)
- Test coverage in `tests/test_phase61_coverage_v2.py`

**Impact**:
- Misleading ops status reporting
- False confidence in coverage completeness
- Min/max bounds treated as coverage proof instead of diagnostics

**Root Cause**:
Historical coverage V1 used min/max row counts as proof. V2 correctly uses receipts, but reporting tools may not have been fully updated.

**Structural Fix Required**:

1. Audit all coverage reporting for min/max usage
2. Ensure `ops_status.py` emphasizes segment/receipt counts
3. Add clear "diagnostic only" labels to min/max bounds
4. Update documentation to clarify V2 vs V1 differences

**Current State**:
- Core ledger logic is ✅ CORRECT
- Reporting tools need audit
- Tests validate segment-based evaluation

**Verification**:
- All coverage reports emphasize segment receipts
- Min/max clearly labeled as diagnostics
- No code path treats row count range as COMPLETE proof

---

### P0-5: Raw Retention + change_seq Operational

**ID**: `P0-5`  
**Severity**: `P0 - HIGH`  
**Status**: `RESOLVED (code) / OPEN (live)` — raw retention wired; live raw-for-COMPLETE not yet evidenced (0 receipts)  
**Structural Fix**: Verify raw retention and change sequences in production path

#### Issue Details

Raw retention is required by Coverage V2 contracts but production operational path may not guarantee raw object persistence.

**Files Affected**:
- `storage/coverage_ledger.py` (line 176-182): Checks raw retention
- `platform/workers/ingestion-premium/src/index.ts`: Raw manifest writing
- `scripts/sync_d1_to_sqlite.py`: Raw manifest sync
- R2 bucket configuration

**Impact**:
- COMPLETE status requires raw retention evidence
- Missing raw objects break coverage proof
- Change sequence required for incremental sync

**Root Cause**:
Raw retention policy exists but operational pipeline may not enforce R2 persistence requirements.

**Structural Fix Required**:

1. Verify R2 lifecycle policies prevent raw deletion
2. Add raw object existence check to coverage evaluation
3. Ensure change_seq advances atomically with raw persistence
4. Add raw retention monitoring to ops status

**Current State**:
- Coverage V2 requires raw retention ✅
- Raw digests stored in receipts ✅
- R2 configuration needs verification ⚠️

**Verification**:
- Raw objects persisted for all COMPLETE segments
- Change sequence advances correctly
- Ops status shows raw retention health

---

### P0-6: READY Publish Coherence Gate

**ID**: `P0-6`  
**Severity**: `P0 - CRITICAL`  
**Status**: `RESOLVED (code) / OPEN (live)` — coherence gate implemented and correctly blocks; production READY ≥1 not yet achieved  
**Structural Fix**: Add full coherence check before READY publication

#### Issue Details

`scripts/sync_d1_to_sqlite.py` calls `publish_ready_snapshot` but may not enforce all coherence gates before publication.

**Files Affected**:
- `scripts/sync_d1_to_sqlite.py` (line 56-60)
- `paper_runtime/__init__.py`: `publish_ready_snapshot` implementation
- Coverage ledger evaluation logic

**Impact**:
- READY may publish with incomplete coverage
- B0 quality gates not enforced before publish
- Inventory/coverage/raw/validation/B0 not coherent
- Production READY broken promise

**Root Cause**:
READY publication was added but full coherence gate was not implemented or enforced.

**Structural Fix Required**:

1. Implement `_check_ready_coherence()` function with gates:
   - ✅ All governed datasets have COMPLETE coverage segments
   - ✅ All COMPLETE segments have successful receipts
   - ✅ All receipts have raw retention evidence
   - ✅ B0 quality checks pass for all datasets
   - ✅ Natural key migration is READY
   - ✅ No validation failures

2. Add gate to `publish_ready_snapshot`:
   ```python
   def publish_ready_snapshot(conn, snapshot_dir):
       if not _check_ready_coherence(conn):
           raise ReadyCoherenceError("Cannot publish READY: coherence gates not met")
       # ... publish logic
   ```

3. Return detailed failure reasons when gate fails

4. Add coherence status to ops projection

**Verification**:
- READY publication fails with clear errors when gates not met
- Ops status shows which gates are blocking
- All checks atomic and transactional

---

### P0-7: Remote Ops Read-Only Tools

**ID**: `P0-7`  
**Severity**: `P0 - MEDIUM`  
**Status**: `RESOLVED (code)` — 16 tools + migration 0003, Worker live  
**Structural Fix**: Add ops-specific tools to Remote Ops MCP

#### Issue Details

Remote Ops MCP has research tools but may be missing ops-specific tools like endpoint inventory, source inventory, projection status, SLA monitoring.

**Files Affected**:
- `platform/workers/quant-ops-mcp/src/domain.js` (tool definitions)
- `platform/workers/quant-ops-mcp/src/mcp.js` (tool registration)
- Research MCP tools in `mcp_servers/quant_data/server.py`

**Impact**:
- Ops teams lack full visibility via MCP
- Manual checks required for ops status
- SLA monitoring not integrated
- Endpoint inventory not queryable

**Root Cause**:
Remote Ops MCP was implemented with GitHub OAuth but ops-specific tools were not fully defined.

**Structural Fix Required**:

1. Add ops tools to `domain.js`:
   - `source_inventory` - list all data sources and their health
   - `endpoint_status` - status of all ~31 ingestion endpoints
   - `projection_status` - current projection metadata health
   - `sla_summary` - SLA compliance dashboard
   - `run_history` - recent ingestion run history
   - `coverage_ledger_dump` - full coverage ledger for audit

2. Keep MCP strictly read-only (no write tools)

3. Add rate limiting per tool

4. Document all tools in ops runbook

**Current State**:
- GitHub OAuth read-only ✅
- MCP framework working ✅
- Ops tools incomplete ⚠️

**Verification**:
- All ops status accessible via MCP tools
- No write capabilities exposed
- Tools work with remote GitHub OAuth

---

### P0-8: Documentation Drift

**ID**: `P0-8`  
**Severity**: `P0 - MEDIUM`  
**Status**: `RESOLVED (docs)` — Phase 6.1/6.2 boundary clarified; roadmap consistent  
**Structural Fix**: Fix Phase 6.1/6.2 roadmap inconsistencies

#### Issue Details

Documentation shows drift between Phase 6.1 and 6.2 plans, runbooks, and actual implementation.

**Files Affected**:
- `docs/phase61_plan.md`
- `docs/phase61_production_runbook.md`
- `docs/phase6_hardening_acceptance.md`
- `docs/roadmap.md` (if exists)

**Impact**:
- Confusing operational guidance
- Unclear Phase 6.1 vs 6.2 boundaries
- Runbook may not match actual implementation
- Future planning difficult

**Root Cause**:
Documentation updated incrementally without consolidating Phase 6.1/6.2 boundaries.

**Structural Fix Required**:

1. Consolidate Phase 6.1 → Phase 6.2 boundary document
2. Update runbook to match actual code state
3. Create Phase 6.2 completion checklist
4. Add Phase 7 prerequisites section
5. Fix roadmap to show actual progress

**Verification**:
- All documentation consistent with code
- Clear Phase 6.2 completion criteria
- Phase 7 prerequisites documented

---

### P0-9: Test Audit and Consolidation

**ID**: `P0-9`  
**Severity**: `P0 - LOW`  
**Status**: `RESOLVED (code)` — tests consolidated; offline green on land  
**Structural Fix**: Consolidate redundant negative tests

#### Issue Details

Test suite may have redundant negative tests while strong invariants need consolidation.

**Files Affected**:
- `tests/test_phase61_coverage_v2.py`
- `tests/test_jsda_governed.py`
- Other coverage/READY tests

**Impact**:
- Test suite maintenance burden
- Slower test runs
- Unclear what invariants are protected
- Redundant failure modes

**Root Cause**:
Tests added incrementally without audit and consolidation.

**Structural Fix Required**:

1. Audit all coverage/READY tests
2. Identify redundant negative tests
3. Consolidate to strong invariant tests
4. Ensure each P0 fix has corresponding test
5. Add integration tests for READY gate

**Verification**:
- No redundant test cases
- All P0 issues covered by tests
- Strong invariants clearly protected
- Test runtime optimized

---

## Priority Wave 1 Issues (P1)

### P1-1: Complete Endpoint Inventory (~31 Endpoints)

**ID**: `P1-1`  
**Severity**: `P1 - HIGH`  
**Status**: `RESOLVED (code)` — 31 endpoints documented (26 governed + 5 experimental) in `data_contracts/inventory.py`  
**Structural Fix**: Complete endpoint inventory and add to ops tools

#### Details

Current endpoint inventory incomplete. Need ~31 endpoints fully documented and monitored.

**Files**:
- Ingestion endpoint definitions
- JSDA source URLs
- J-Quants API endpoints

**Fix**:
- Complete endpoint inventory
- Add endpoint status monitoring
- Integrate with ops MCP tools

---

### P1-2: Real Data Backfill

**ID**: `P1-2`  
**Severity**: `P1 - HIGH`  
**Status**: `OPEN (live)` — full multi-year JQ/JSDA backfill not executed (credentials present)  
**Structural Fix**: Execute full historical backfill for governed datasets

#### Details

Production backfill per Phase 6.1 runbook sections 3-4 needs execution.

**Files**:
- `scripts/run_ingestion_once.py`
- JSDA ingestion scripts

**Fix**:
- Execute backfill per runbook
- Verify coverage V2 receipts
- Confirm raw retention

---

### P1-3: Production READY ≥1

**ID**: `P1-3`  
**Severity**: `P1 - HIGH`  
**Status**: `OPEN (live)` — coherence gate correctly blocks; no production READY yet  
**Structural Fix**: Achieve first complete READY snapshot

#### Details

All P0s resolved + backfill complete should yield first production READY.

**Files**:
- `paper_runtime/__init__.py`
- READY snapshot logic

**Fix**:
- Execute full production run
- Publish first READY
- Verify all gates passed

---

## Phase 7 Prerequisites (After P0=0, P1 Complete)

### Phase 7.1: Knowledge Store

- Minimal knowledge store implementation
- Feature quality metadata tracking
- No unrestricted Python execution
- Budget constraints and early stopping

### Phase 7.2: Selection Gateway

- Closed-schema only
- No live broker integration
- No FoF (Fund of Funds) complexity initially

### Phase 7.3: AI Gateway

- Closed-schema LLM calls only
- Experiment budget tracking
- Early stopping mechanisms
- No infinite research loops

---

## Verification Checklist (current state)

Code-complete items (checked) vs live-operational items (still OPEN).
`PHASE62_DONE` is **not** printed while any live item is open.

### Code-complete ✅
- [x] P0-1: Dataset membership unified (26 datasets)
- [x] P0-2: Canonical registry created and used
- [x] P0-3: Ops projection publisher + D1 apply (`--publish-ops`, default OFF)
- [x] P0-4: Coverage V2 receipts drive COMPLETE (logic correct)
- [x] P0-5: Raw retention wired (logic)
- [x] P0-6: READY coherence gate enforced (correctly blocks)
- [x] P0-7: Remote Ops tools complete (16 tools + migration 0003)
- [x] P0-8: Documentation consistent
- [x] P0-9: Tests consolidated
- [x] All tests pass offline: `pytest -q`
- [x] Git log shows small reviewable commits

### Live-operational — OPEN 🚫 (these gate Phase 7 mass research)
- [ ] Coverage V2 COMPLETE with real receipts (today: 0 receipts, all PARTIAL/UNKNOWN)
- [ ] Full multi-year JQ/JSDA backfill executed
- [ ] Production READY ≥1 achieved
- [ ] CF cron auto-projection (no human flag)
- [ ] Phase 7 prerequisites implemented (not just stubs)

---

## Next Steps

1. **Immediate**: Address P0-1 (dataset membership) as it blocks coverage correctness
2. **Wave 1**: Create canonical registry (P0-2)
3. **Wave 1**: Automate ops projection (P0-3)
4. **Wave 1**: Implement READY gate (P0-6)
5. **Wave 2**: Complete remaining P0s
6. **Wave 3**: Execute P1 tasks (backfill, endpoints, READY)
7. **Final**: Verify all checks and print `PHASE62_DONE`

**Estimated Effort**: 3-5 days of focused development to resolve all P0s, 1-2 weeks for full Phase 6.2 completion including backfill and READY.

---

**End of Wave 0 Code Review**
