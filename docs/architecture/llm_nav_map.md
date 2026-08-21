# LLM / agent navigation map

**Status:** **Live** (Track B1 — productionized in README).  
**Paired ADR:** [`adr_llm_friendly_refactor.md`](./adr_llm_friendly_refactor.md) (**Accepted (Grok 2026-08-12)**).  
**Live residual SoT (sole):** [`../phase62_residual_status.md`](../phase62_residual_status.md)  
— **live flags only** (COMPLETE segs / Mass·READY / pins / DEFER). Experiment scores: R2 + D1.  
**This map never embeds live counts** (acq / residual agents own those numbers).  
**Layout SoT:** [`repo_layout_migration.md`](./repo_layout_migration.md) (**DONE** Batches 0–E; Batch Z DEFER)  
**Architecture hub:** [`../architecture.md`](../architecture.md) (PIT / Coverage V2 / MCP; not residual counts)

> **Mass Autonomous Research / production READY / Phase 7 switch: NO-GO · OFF.**  
> Do not upgrade those statuses from this map. Only residual + dated `docs/proof/*` may record live evidence.  
> **Do not** launch `cf_premium_backfill` / Mass / READY from this map or residual prose alone.

---

## 0. Read this first (≤5 files)

| # | File | Why |
|---|------|-----|
| 1 | [`../../README.md`](../../README.md) | Product orientation + `packages/*` tree |
| 2 | **This file** | Task routing + do-not list |
| 3 | [`../phase62_residual_status.md`](../phase62_residual_status.md) | **Live residual SoT (sole)** — COMPLETE segs, raw_n, C8, tip, Phase7 OFF, Mass NO-GO |
| 4 | [`../architecture.md`](../architecture.md) | PIT sole read path, Coverage V2, MCP planes (not residual counts) |
| 5 | *One* domain doc for your task (table below) | Contract detail |

**Refactor / layout / import policy work:** also read the [ADR](./adr_llm_friendly_refactor.md).

---

## 1. Do not (agent safety)

```text
✗ Claim or enable Mass ON, production READY, Phase 7 GO
✗ Invent COMPLETE segments or live B0 pass without residual+proof
✗ Move platform/workers/** or data/**
✗ Introduce quant_platform.* imports (Batch Z not approved for B1)
✗ Read facts via raw SQLite from core / features / strategies (use pit.get_*)
✗ Call market HTTP outside packages/data_plane/ingestion
✗ Commit secrets, data/*.sqlite, .venv, egg-info, node_modules
✗ Treat docs/phase62*_status.md / final_report as current residual SoT
✗ Weaken publish fail-closed guards or mass_research operator_override rejection
✗ Delete Python↔TS parity mirrors or governed.js codegen without replacement
✗ Create scripts/run_wNN_*.py or docs/proof/w08*_wNN_*.md as an eval warehouse
✗ Append ALL-TRACK experiment scorecards to phase62_residual_status.md
✗ Import scripts/run_w* (gone; evaluators in research.unique_logic.{event,event_filters,event_sides,cross_section,cs_overlays,adaptive})
✗ Treat .glm-logs or local sqlite as experiment SoT (R2 + D1 index only)
```

---

## 2. Repository planes (disk vs import)

```text
packages/
  edge/                 import: cf_platform, mcp_servers
  data_plane/           import: data_contracts, ingestion, storage, pit, data_access, ops
  research_runtime/     import: core, features, strategies, paper_runtime, risk, price_basis
  product/              import: agents, research, selection, execution, knowledge, gateway
platform/workers/**     NOT a Python package — path FROZEN (wrangler)
scripts/                CLI drivers (not installed packages)
tests/                  offline pytest (testpaths)
docs/                   architecture / domain / operations / proof / phase history
data/                   local gitignored domain — do not move
qp_paths.py             repo_root() — use instead of parents[N] in packages
```

**Import rule (B1 default):** leaf top-level names stay (`import pit`, not `data_plane.pit`).  
Physical path is for humans/agents browsing disk; Python path is setuptools multi-root.

---

## 3. Dependency direction (short)

```text
data_contracts ← ingestion ← storage ← pit
                      ↑           ↑
                 cf_platform  (coverage helpers)

pit ← features ← core ← strategies ← agents / execution
         ↑                 ↑
    price_basis      paper_runtime → storage, data_contracts, cf_platform

data_access → pit, features, paper_runtime, storage, data_contracts
mcp_servers → data_access

product (agents, gateway, …) must not fetch market data via ingestion HTTP
```

Details + exceptions: ADR §5.

---

## 4. Task → code + docs

| Task | Start here (code) | Domain doc |
|------|-------------------|------------|
| J-Quants / JSDA fetch | `packages/data_plane/ingestion/` | [`../data_sources.md`](../data_sources.md) |
| Dataset contracts / governed JSON | `packages/data_plane/data_contracts/` | package README + JSON files |
| Receipts / coverage ledger | `packages/data_plane/storage/` | residual + [`../phase61_production_runbook.md`](../phase61_production_runbook.md) |
| PIT fact read | `packages/data_plane/pit/` | [`../pit_api.md`](../pit_api.md) |
| Ops / research read adapter | `packages/data_plane/data_access/` | [`../quant_data_access.md`](../quant_data_access.md) |
| Backfill planning | `packages/data_plane/ops/` | residual / ops scripts |
| CF Premium algorithms (Python) | `packages/edge/cf_platform/` | [`../phase35_cf_ingest.md`](../phase35_cf_ingest.md) |
| Local stdio MCP | `packages/edge/mcp_servers/quant_data/` | [`../quant_data_access.md`](../quant_data_access.md) |
| Features | `packages/research_runtime/features/` | [`../features.md`](../features.md) |
| Backtest engine | `packages/research_runtime/core/` | [`../core_engine.md`](../core_engine.md) |
| StrategySpec / paper runner | `packages/research_runtime/strategies/` | [`../paper.md`](../paper.md), [`../agents.md`](../agents.md) |
| READY policy / snapshots | `packages/research_runtime/paper_runtime/` | residual (**READY NO-GO** for production) |
| Role agents / Mass gate | `packages/product/agents/` | [`../agents.md`](../agents.md), [`./phase7_fail_closed.md`](./phase7_fail_closed.md) |
| Selection / budget | `packages/product/selection/` | phase7 foundation OFF docs |
| AI gateway stubs | `packages/product/gateway/` | fail-closed tests |
| CF Workers (TS) | `platform/workers/<name>/` | worker README + phase runbooks |
| Publish ops projection | `scripts/publish_ops_projection.py` | [`../operations/projection_publish_guard.md`](../operations/projection_publish_guard.md) |
| A3 seal raw+struct months | `scripts/issue_receipts_parallel.py` | residual + [`../proof/complete_plus8_r2_raw_seal_20260813.md`](../proof/complete_plus8_r2_raw_seal_20260813.md); **never** invent COMPLETE; R2 mirror OK if usable raw |
| Packaging / paths | `pyproject.toml`, `qp_paths.py` | this map + layout migration |
| LLM-friendly refactor | plane READMEs + `tests/test_plane_import_boundaries.py` | [ADR](./adr_llm_friendly_refactor.md) (**Accepted**); residual for live status |
| New research hyp / daily_path_DD | `research.daily_path_eval` · `research.eval_registry` · `research.cf_mass_eval_job` | [ADR recording](./adr_research_recording.md) — **no new run_wNN script** |
| Existing `run_w*` / wave proofs | keep, deprecated | [`wave_assets_deprecated.md`](./wave_assets_deprecated.md) |
| Eval job index (D1/R2) | `research.eval_registry` · `platform/workers/quant-ops-mcp/migrations/0006_research_eval_jobs.sql` | recording ADR |
| Test tiers (G0/G1/G2) | `tests/README.md` | this map §11 B1-d |

---

## 5. Public entrypoints (cheat)

Prefer these over random deep imports for **new** code:

| Package | Prefer |
|---------|--------|
| `pit` | `get_equity_bars_daily`, `get_equity_master`, `get_jquants_records`, `get_*`, errors |
| `core` | `run_backtest`, `standard_cost` / `stress_cost`, strategy protocol |
| `storage` | coverage ledger API, `TrustedReceiptIssuer`, schema/store for writers |
| `agents` | `AgentPaperPipeline`, role types, `mass_research.start_mass_research` (fail-closed) |
| `data_contracts` | `loader` / `coverage` / `identity` / inventory helpers + JSON package data |
| `cf_platform` | `ingest_premium.*`, `live_gates.measure_b0` |
| `strategies` | `spec.schema`, `spec.interpreter`, `paper.runner` / store types |
| `ingestion` | `pipeline`, `jquants.catalog`, clients — root is namespace-light |

Full policy: ADR §5.2.

---

## 6. Name collision glossary

| Name you see | Means | Not to confuse with |
|--------------|-------|---------------------|
| **Track B0** | LLM-refactor design ADR (now Accepted) | Track B1 implementation batches |
| **Track B1** | Docs hub + plane guards (+ later B1-c…e) | B0 gates / Mass GO |
| **B0 gates** (`cf_platform.live_gates`) | Order-of-magnitude volume checks | Track B0/B1; Mass GO |
| **READY** | Research snapshot policy / publication | “repo ready to merge” |
| **COMPLETE** | Coverage V2 segment/dataset state | “phase complete” prose |
| **code-complete** | Implementation present | live GO |
| **NO-GO / OFF** | Must not enable | DEFER (postponed work) |
| `platform/` (disk) | Workers tree | stdlib `platform`; use `cf_platform` for Python |
| `execution` (three places) | core fill timing · paper_runtime helper · product paper service | Keep all three; see ADR §8.2 |
| `artifacts` (agents vs research) | Agent envelopes vs research idea artifacts | Do not merge casually |
| `data_access` | Read domain façade | Not a second PIT |
| `ingestion.jsda.adapters` | Formal JSDA adapter surface (Phase 6.2.3 design) | Not yet wired into fetch/parse paths — **keep** (not D-dead) |

---

## 7. Docs truth layers

| Layer | Paths | Agent rule |
|-------|-------|------------|
| **0 Current** | README, this map, **`phase62_residual_status.md` (sole live residual SoT)**, `architecture.md`, ADR (if refactoring) | Always prefer; **counts only in residual** |
| **1 Domain** | `pit_api`, `core_engine`, `features`, `paper`, `agents`, `quant_data_access`, `data_sources` | By task |
| **2 Ops** | `docs/operations/*`, phase runbooks, worker READMEs | When operating live systems; not residual counts |
| **3 Proof** | `docs/proof/*` | Cite evidence; do not invent status |
| **4 Historical** | `phase62_status`, `phase621_*`, `phase622_*`, `phase623_*`, `phase62_*checklist/final*`, `pre_phase7_*`, `phase6_hardening_*`, `phase61_plan`, dated `phase35_4_*` acceptance/ops verify, dated ops live-sync notes | Banner / archive; **not** residual SoT |

### 7.1 Phase / residual file index (maintenance)

| File | Tag |
|------|-----|
| `docs/phase62_residual_status.md` | **live residual SoT (sole)** — COMPLETE / raw_n / C8 / tip / Mass·READY / Phase7 |
| `docs/architecture.md` | **current architecture hub** (banner → residual; no live counts) |
| `docs/architecture/llm_nav_map.md` | **current** agent entry map (this file; no live counts) |
| `docs/architecture/repo_layout_migration.md` | **current layout SoT** |
| `docs/architecture/phase7_fail_closed.md` | **current** (Phase 7 **OFF**) |
| `docs/operations/phase7_foundation_off.md` | **current** ops note (Phase 7 **OFF**) |
| `docs/architecture/adr_llm_friendly_refactor.md` | **Accepted ADR (Grok 2026-08-12)** |
| `docs/architecture/adr_research_recording.md` | **Accepted** — experiment SoT = R2 + D1 index; no wave-script warehouse |
| `docs/architecture/adr_historical_raw_acceleration.md` | Track A ADR (infra/execute evidence in proof/) |
| `docs/complete_segment_checklist.md` | **current** COMPLETE evidence contract (not residual counts) |
| `docs/phase6_snapshot_publication.md` | domain (READY publication machine; production READY still **NO-GO**) |
| `docs/phase61_production_runbook.md` | runbook (not residual counts) |
| `docs/phase62_production_runbook.md` | runbook (not residual counts) |
| `docs/phase62_cf_edge_cron.md` | runbook / design note |
| `docs/phase35_cf_ingest.md`, `phase35_s0_secrets.md`, `phase35_storage_scale.md`, `phase35_validation_matrix.md` | domain + runbook (Phase 3.5) |
| `docs/phase35_4_acceptance_status.md` | historical acceptance snapshot |
| `docs/phase35_4_ops_verify_20260811.md` | historical ops verify snapshot |
| `docs/phase6_hardening_acceptance.md` | historical acceptance snapshot |
| `docs/phase61_plan.md` | historical plan |
| `docs/phase621_test_audit.md` | historical / audit |
| `docs/phase622_independent_review.md` | historical review |
| `docs/phase62_completion_checklist.md` | historical / checklist |
| `docs/pre_phase7_full_code_review.md` | historical Wave-0 review |
| `docs/operations/phase63_live_sync.md` | historical live-vs-code note (counts may be stale) |
| `docs/proof/*` | dated evidence |
| `docs/operations/*` | ops runbooks |

Historical phase status / final_report / checklist / acceptance-plan / dated live-sync files carry a **Historical snapshot** banner pointing at [`phase62_residual_status.md`](../phase62_residual_status.md). **Never** treat them as live residual SoT.

---

## 8. Tests — what to run

### Guard pack (every structural change)

```bash
python -m pytest \
  tests/test_smoke.py \
  tests/test_mass_research_gate.py \
  tests/test_gateway_fail_closed.py \
  tests/test_core_data_boundary.py \
  tests/test_features_data_boundary.py \
  tests/test_strategies_static_boundaries.py \
  tests/test_plane_import_boundaries.py \
  tests/test_phase7_gateway.py \
  tests/test_ops_projection_publish_guard.py \
  -q
```

### Full offline

```bash
pip install -e ".[dev]"   # after packaging/layout changes
python -m pytest tests/ -q
python -m unittest tests.test_smoke -v
```

Live (`QP_LIVE=1`) is **operator-only**, never a B1 merge gate.

Test tiers: `tests/README.md` (G0/G1/G2; ADR §12 / B1-d).

---

## 9. Scripts map (flat list → purpose)

| Script cluster | Examples | Plane |
|----------------|----------|-------|
| Ingest | `run_ingestion_once.py`, `run_historical_backfill.py`, `parse_jsda_from_r2_mirror.py` | data_plane |
| Coverage / receipts | `write_collection_receipts.py`, `refresh_coverage_ledger.py`, `issue_receipts_parallel.py`, `issue_signed_receipts_for_segments.py`, `evaluate_collection_sla.py` | data_plane / edge (**empty-raw ban** incl. `{"data":[]}`; no COMPLETE without raw; sticky COMPLETE survives day-roll) |
| Sync / D1 | `sync_d1_to_sqlite.py`, `report_d1_local_sync_lag.py`, `restore_local_complete_from_receipt.py` | ops |
| Projection | `export_ops_projection.py`, `publish_ops_projection.py`, `ops_reeval_freshness.py`, `ops_reeval_observed_window.py`, `ops_status.py` | ops (**publish fail-closed**; observed_* re-eval does not rewrite segments) |
| Paper / agents | `run_paper_once.py`, `run_agents_paper_once.py`, `rebuild_paper_index.py` | research / product |
| Validation | `run_phase35_validation.py`, `run_phase4_accept.py` | edge / features |
| Codegen | `generate_governed_js.py`, `verify_governed_js_drift.py` | contracts → Workers |

Shared ROOT bootstrap: `scripts/_bootstrap.py` (`ensure_repo_root`) — **B1-e partial**  
(ops/coverage/receipt CLIs migrated; `ensure_repo_root` inserts root + `packages/*` plane paths; remaining scripts still local inserts; **do not** regroup dirs).

---

## 10. Frozen paths

| Path | Rule |
|------|------|
| `platform/workers/**` | No moves; wrangler + runbooks + tests hardcode |
| `data/**` | Local domain; gitignore; never commit sqlite dumps/secrets |
| Import leaf names | Stable through B1 (`ingestion`, `pit`, …) |
| Mass / READY / Phase7 switches | Remain closed |

---

## 11. B1 batch pointer

| Batch | Theme | Status |
|-------|-------|--------|
| **B0** | This map + ADR design | **DONE** |
| **B1-a** | Docs hub, historical stamps, README link | **DONE** |
| **B1-b** | Plane READMEs, public API notes, boundary tests | **DONE** |
| **B1-c** | Dead code / empty dirs / collision docs | **partial** — inventory 2026-08-13: root `raw/` absent; `ingestion.jsda.adapters` unreferenced but **kept** as formal surface; no parity-mirror or fail-closed deletions; heuristic “zero-ref” scans **false-positive** on leaf imports (`from core import engine`) — do not mass-delete |
| **B1-d** | Test tiers / matrix navigation | **partial** — `tests/README.md` G0/G1/G2 + named guard table (2026-08-13); heavy matrix split still open |
| **B1-e** | Script bootstrap, `qp_paths` stragglers | **partial** — `_bootstrap` on ops/coverage + receipt CLIs; plane paths on `ensure_repo_root`; fingerprints no longer `parents[N]`; remaining scripts incremental (no dir moves) |
| B1-f | Optional archive move / script regroup | optional / last |
| Z | `quant_platform.*` namespace | **DEFER** (out of B1) |
| Docs SoT | residual live-sync + historical banners + this map | **DONE** (counts **only** in residual; this map / architecture hub / ADR = nav + pointers) |

ADR is **Accepted (Grok 2026-08-12)**. Mass / READY / Phase7 remain **NO-GO / OFF**.

---

## 12. Quick spirit checklist

```text
[ ] Ingestion-only network for market data
[ ] pit.get_* sole structured fact read (as_of, available_at)
[ ] core/features/strategies: no direct SQLite facts
[ ] CF contracts + Worker parity respected
[ ] Mass fail-closed; no operator_override
[ ] Publish fail-closed; no synthetic COMPLETE in prod export
[ ] Honest residual; proof dated; no GO fiction
```
