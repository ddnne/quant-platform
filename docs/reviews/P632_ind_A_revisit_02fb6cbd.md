# Independent review A revisit — at `02fb6cbd`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `02fb6cbd` (`02fb6cbd70f2039cd47bcf7a15838182842f3426`)  
**Branch at audit:** `grok/p632-ind-A-revisit-02fb6cbd` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freeze:** `2b82ec7d` ([`P632_ind_A_revisit_2b82ec7d.md`](P632_ind_A_revisit_2b82ec7d.md)). Earlier: `242c2484` ([`P632_ind_A_revisit_242c2484.md`](P632_ind_A_revisit_242c2484.md)); `3b64bdfc` ([`P632_ind_A_revisit_3b64bdfc.md`](P632_ind_A_revisit_3b64bdfc.md)); `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md)); `ed94d504` ([`P632_ind_A_revisit_ed94d504.md`](P632_ind_A_revisit_ed94d504.md)); `5103b26b` ([`P632_ind_A_revisit_5103b26b.md`](P632_ind_A_revisit_5103b26b.md)). This file does not rewrite those freezes.  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A at current `origin/grok/phase63-ci-source-closure` vs `2b82ec7d`. Named tree deltas: premium catalog / availability / identity / raw-page / coverage-segment Worker units. Those are **not** Independent A P0s unless they reopen PIT / COMPLETE. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, Phase 6.3.2 COMPLETE, or Phase 7 GO.

`git rev-list --count 2b82ec7d..02fb6cbd` = **15**. PIT / `coverage_ledger` / `backfill_planner` / `core_v1` / `research_data_profile` / pipeline / archive / `official_index` / `snapshot_publish_policy` / `range_batch_scheduler` / receipt CLIs / `cf_premium_backfill` have **empty** `git diff --stat` this window. Independent-A-adjacent code is Worker-unit pins that replaced Python greps of premium TS (catalog identity, availability policy, JST clocks, raw-page retain, coverage-segment plan).

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| premium catalog identity is Worker unit not Python grep | `23a5cbb9` | not an Independent A P0 (Worker catalog `length===23` is premium-core **paths** — not Dataset COMPLETE 23) |
| premium availability policy is Worker unit not Python grep | `8fc13e24` | not an Independent A P0 (Worker `available_at` wrapper; ingest-time fail-safe; not a PIT `as_of` read path) |
| premium identity JST clocks are Worker unit not Python grep | `5ac9cce1` | not an Independent A P0 (session-close JST constants; not PIT, not COMPLETE) |
| premium raw-page retain is Worker unit not Python grep | `0383311f` | not an Independent A P0 (raw `ACQUIRED` / pagination `complete` boolean; JSON never `COMPLETE`) |
| premium coverage-segment plan is Worker unit not Python grep | `0fee1b1e` | not an Independent A P0 (required `coverage_segments` INSERT is `UNKNOWN`; empty SUCCESS shell stays Python invariant) |

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**. Live STALE V2 floors are last-known, not current V3.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 188693 (~52.4 h) |
| `stages.refresh_success` | **false** (`refresh_attempt=true`) |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.governed_dataset_count` | 26 |
| `ops_status.raw_retention.complete` | 18301 (raw-manifest column — **not** Dataset COMPLETE). Live payload has no `acquired` field. |
| `ops_status.last_run` | id **14319** PASS (`jquants`, `2026-08-24T01:15:01+09:00`) |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |
| `sync_status` | `applied_feed_cursor` **null**; datasets `LAGGING_APPLY_UNPINNED` / `EXPORT_CURRENT_APPLY_UNPINNED` |
| `validation_summary.dataset_count` | 23 (cron/validation run of current datasets — **not** Dataset COMPLETE 23) |
| `ingestion_last_run.detail.datasetCount` | 23 passed (same: current jquants cron, not Coverage COMPLETE) |
| `collection_sla_status(jsda_otc_bond_reference_prices)` | `current_state` **PROJECTION_STALE** (`ops_projection_stale`) |
| `endpoint_status(...).coverage_segment_granularity` | `official_archive_day` (canonical inventory under STALE projection — **not** the tree JSON grain `official_archive_index_day`) |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s premium Worker units):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set. PARSE_ZERO `2002-08-02` / `2002-08-05` stay PARTIAL (`PARSE_ZERO_SEAL_PROOF` empty).

Same generation as the `2b82ec7d` freeze (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 187976 → 188693. Floors and 4-PARTIAL set are unchanged. `raw_retention.complete` stayed 18301 — still the live raw-manifest column, **not** Coverage COMPLETE.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b` / `3b64bdfc` / `242c2484` / `2b82ec7d`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` | At `3b64bdfc` | At `242c2484` | At `2b82ec7d` | At `02fb6cbd` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `plan_required_segments` clip unchanged) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `index_text` callers unchanged this window; omit-without-HTML still empty; JSDA still skipped at `plan()`) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged; Worker availability is ingest-time fail-safe, not a PIT read) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; Worker required-segment INSERT is `UNKNOWN`) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; empty-observed gate unchanged; PARSE_ZERO 2 stay PARTIAL; Worker raw `ACQUIRED` ≠ Dataset COMPLETE) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `2b82ec7d`. Premium catalog / availability / identity / raw-page / coverage-segment Worker units do **not** reopen PIT or COMPLETE. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## Tree deltas after `2b82ec7d`

Window: `2b82ec7d..02fb6cbd` (15 commits). Independent A core surfaces (`packages/data_plane/pit/`, `coverage_ledger.py`, `backfill_planner.py`, `core_v1.json`, `research_data_profile.py`, pipeline, archive, `official_index.py`, receipt CLIs, `cf_premium_backfill.py`) have **empty** `git diff --stat`. Code landings are Worker-unit tests plus Python grep deletions.

Code landings at this HEAD (not Independent A P0; do not mint COMPLETE / FRESH / READY / GO):

1. **premium catalog identity Worker unit** (`23a5cbb9`). `platform/workers/ingestion-premium/src/catalog.test.ts` executes `PREMIUM_CORE_DATASETS` vs `jquants_premium_core.json`. `toHaveLength(23)` is premium-core **path count**, not Dataset COMPLETE 23. Python `test_worker_catalog_imports_the_same_contract_document` grep was dropped.
2. **premium availability policy Worker unit** (`8fc13e24`). `availability.test.ts` executes `policyForDataset` / `pickAvailableAt`. Unknown dataset and missing contract field fail-safe to `ingest_time_conservative` / `ingestedAt`. That is ingest-time assignment, not a PIT `as_of` look-ahead. Python PIT files are unchanged this window.
3. **premium identity JST clocks Worker unit** (`5ac9cce1`). `identity.test.ts` pins `sessionCloseJst` 15:00 / 15:30 / 11:30 and `newRunId` UUID. Not a coverage evaluate. Not READY.
4. **premium raw-page retain Worker unit** (`0383311f`). `index.test.ts` executes `/v1/run` against mock D1/R2. Successful fetch writes `raw_acquisition=ACQUIRED`; failed fetch writes `FAILED`. Manifest boolean `complete` is pagination-exhausted, not the string `COMPLETE`. `JSON.stringify(body)` must not contain `COMPLETE`. Retention bind is `ACQUIRED`/`FAILED`. Live MCP `raw_retention.complete=18301` is still the historical raw-manifest **column**, not this pin and not Dataset COMPLETE. Python `test_worker_retains_every_raw_page_and_scopes_tokens` grep was dropped.
5. **premium coverage-segment plan Worker unit** (`0fee1b1e`). `collection_receipts.test.ts` + `index.test.ts` execute `writeRequiredCoverageSegment` against mock D1. Required INSERT is `'UNKNOWN'` and `not.toContain("COMPLETE")`. Non-event `expected_items` = `queries.length`; `event_driven` query units are null; non-canonical windows do not INSERT required segments. Commit message: SQLite schema and empty SUCCESS shell window stay invariant — `test_worker_d1_receipt_migration_has_reconciliation_evidence` and `test_receipt_observed_window_ignores_empty_success_shells` remain in `tests/test_phase61_coverage_v2.py`. Python `test_worker_plans_non_event_query_units_before_collection` grep was dropped. Does not mint Dataset COMPLETE. Does not republish OTC required set.

Remaining 10 commits are docs (Independent A/B/C revisits at `2b82ec7d`, wave-10, test inventory, verify_ci code-lane, banners, §10 mixed, review index). [`P632_ind_A_revisit_2b82ec7d.md`](P632_ind_A_revisit_2b82ec7d.md) is the prior Independent A freeze; this file does not rewrite it.

Feature branch is **not** merged to `origin/main` (`git merge-base --is-ancestor 02fb6cbd origin/main` is false). Isolation did not push `main` and did not deploy.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; `plan_required_segments` clip unchanged this window)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-9,350-430,508-578`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

No `2b82ec7d..02fb6cbd` rewrite of master / AM / earnings official-domain clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. All governed JQ jobs still come from `plan_required_segments` (`backfill_planner.py:557-568`). Premium Worker units do not call `plan_required_segments`. Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened; `index_text` callers unchanged this window; omit-without-HTML still empty)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ops/backfill_planner.py:4-9,408-430,508-538,563-567`; `packages/data_plane/ingestion/jsda/official_index.py:16-40,43-81`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `packages/data_plane/ingestion/pipeline.py:119-163,448-479`; `scripts/jsda_otc_seal_official.py:33-35,50-55,135-149`; `scripts/ops/cf_premium_backfill.py:57-59,210-218,256-274`; `tests/test_backfill_planner.py:422-536`; `tests/test_jsda_otc_official_domain.py:189-210`; `tests/test_cf_premium_backfill_cli.py:98-139`

observed fact (HEAD vs `2b82ec7d`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:912-917`). OTC grain in tree JSON remains `official_archive_index_day`. Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty (`test_refresh_without_index_text_is_fail_closed_empty_not_calendar`). Ledger / pipeline / archive / planner / shared reader / `cf_premium_backfill` files are unchanged this window.

**Unchanged — remaining omit-without-HTML callers.** Pipeline persist still has no year-index HTML → `_index_text_for_plan(policy)` with none (`pipeline.py:448-450`). `snapshot_publish_policy` still omits `index_text` (`:109-111`). `range_batch_scheduler.plan()` still omits the kwarg (`:463`). `publish_ops_projection.load_otc_index_text` is still a private loader (`:48-58`), not the shared reader; omitted/`OSError`/blank still `None`.

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `02fb6cbd` |
|--------|----------------------------|
| `packages/data_plane/ingestion/jsda/archive.py:528-535` | fetched year-index HTML; empty fetch → `None` |
| `scripts/refresh_coverage_ledger.py` | `--index-text PATH` via shared reader or omitted `None` |
| `scripts/write_collection_receipts.py` | `--index-text` / `QP_INDEX_TEXT` via shared reader `missing_ok=True` or omitted `None` |
| `scripts/publish_ops_projection.py` | `--otc-index-html` via **private** `load_otc_index_text`; omitted/`OSError`/`blank` → `None` |
| `scripts/jsda_otc_seal_official.py` | shared reader (local HTML or `None`) |
| `scripts/issue_receipts_parallel.py` | shared reader (local HTML or `None`) |
| `scripts/issue_signed_receipts_for_segments.py` | shared reader (local HTML or `None`) |
| `packages/data_plane/ingestion/pipeline.py:450,456,479` | passed; persist has no held HTML → `None` |
| `packages/data_plane/ops/backfill_planner.py:430,566` | forwarded; default `None`; JSDA skipped at `plan()` |
| `packages/data_plane/ops/range_batch_scheduler.py:463` | **omitted** (JQ dry plan; OTC skipped) |
| `scripts/ops/cf_premium_backfill.py:257,273` | `--index-text` via shared reader; default `None`; JSDA skipped at `plan()` |
| `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-111` | **omitted** (jquants READY path; OTC empty if included) |

A live refresh that omits `index_text` / has no HTML would DELETE the STALE 8784 calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still 8784 under STALE V2. Canonical inventory / `endpoint_status` still advertise `coverage_segment_granularity=official_archive_day`.

Premium Worker units do not fetch JSDA HTML and do not walk a calendar. Coverage-segment plan is JQ premium `coverage_segments` UNKNOWN, not OTC official-index days.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / CLIs is not a live official-index republish. Premium Worker units do not republish the OTC required set.

structural fix (still in tree): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`; `packages/product/research/eval_loaders_sidecars.py:404-427`; `packages/research_runtime/core/universe.py:15-19,32`; `packages/research_runtime/features/runtime.py:108-124`; `platform/workers/ingestion-premium/src/availability.test.ts:8-61`

No PIT file changes `2b82ec7d..02fb6cbd`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of` + `available_at <= as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

Worker availability unit (`8fc13e24`) executes the premium wrapper: unknown dataset / missing contract field → `ingest_time_conservative` / `ingestedAt`. That is fail-safe ingest-time, not a PIT read path and not a look-ahead rewrite of `as_of`. Identity JST clocks (`5ac9cce1`) pin session-close constants only. Premium Worker units do not open a PIT read path.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1423-1432,1439`; `platform/workers/ingestion-premium/src/collection_receipts.test.ts:47-81`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint.

Worker `writeRequiredCoverageSegment` inserts `coverage_segments` as `'UNKNOWN'` with planned query units (`collection_receipts.test.ts:61-80`). SQL and bind JSON `not.toContain("COMPLETE")`. That is a required-inventory placeholder, not a signed TRUSTED_COLLECTION COMPLETE mint. Catalog / availability / identity / raw-page units do not sign receipts.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:127-138,330-354,357-434`; `scripts/jsda_otc_seal_official.py:50-55,120-132`; `tests/test_phase61_coverage_v2.py:126-251,372-`; `platform/workers/ingestion-premium/src/index.test.ts:161-216,266-362`

No `2b82ec7d..02fb6cbd` change to `_empty_observed_forbids_complete`. Tip / archive-index empty SUCCESS stays PARTIAL even if `event_driven` (`:338-342`, `:397-400`). Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18301` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE.

Worker raw-page unit writes `raw_acquisition=ACQUIRED` (success) or `FAILED` (vendor error). Manifest boolean `complete` is pagination-exhausted, **not** the string `COMPLETE` and **not** Dataset COMPLETE (`index.test.ts:161-186`). Coverage-segment plan INSERTs `UNKNOWN`, not COMPLETE. Catalog `toHaveLength(23)` is premium-core path count — **not** Dataset COMPLETE 23. Cron/validation `datasetCount=23` is still not Coverage COMPLETE. PARSE_ZERO days `2002-08-02` / `2002-08-05` stay PARTIAL: `PARSE_ZERO_SEAL_PROOF: dict[str, tuple[str, int]] = {}` (no in-repo digest+count). Empty SUCCESS shell Python invariant remains (`test_receipt_observed_window_ignores_empty_success_shells`). Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat Worker catalog 23 or cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

No `2b82ec7d..02fb6cbd` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. Premium Worker units do not publish READY. This review does not publish READY.

---

## Named tree deltas (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** at `02fb6cbd`; do not reopen named A holes  
file:line: `platform/workers/ingestion-premium/src/catalog.test.ts`; `platform/workers/ingestion-premium/src/availability.test.ts`; `platform/workers/ingestion-premium/src/identity.test.ts`; `platform/workers/ingestion-premium/src/index.test.ts:135-362`; `platform/workers/ingestion-premium/src/collection_receipts.test.ts`; `tests/test_phase35_availability.py`; `tests/test_phase6_data_access.py`; `tests/test_phase61_coverage_v2.py:369-372`

- Catalog Worker unit `length===23` is JSON path identity, not Coverage COMPLETE.
- Availability Worker unit fail-safe is ingest-time `ingestedAt`, not a PIT `as_of` bypass.
- Identity Worker unit is session-close JST + UUID run id.
- Raw-page Worker unit is `ACQUIRED`/`FAILED` + page-NNNNNN.json retain; boolean `complete` is not Dataset COMPLETE.
- Coverage-segment Worker unit INSERTs `UNKNOWN` query-unit plans. Empty SUCCESS shell / SQLite schema stay Python.

These are Worker-unit pins replacing Python greps, not a PIT bypass, not an official-domain reopen, and not READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-`index_text` / shared reader / backfill `--index-text` / premium Worker units are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE. Worker catalog `length===23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- Premium catalog / availability / identity / raw-page / coverage-segment Worker units rebuilt production D1. Isolation did not run live JSDA fetch, seal, or premium `/v1/run` against production D1/R2.
- Worker required-segment INSERT `UNKNOWN` is Dataset COMPLETE. It is not.
- Worker raw manifest boolean `complete=true` is Dataset COMPLETE. It is not.
- Pipeline persist with no held HTML rebuilt the live ledger. Persist is fail-closed empty for OTC, not weekend COMPLETE, and not FRESH.
- Caller `snapshot_publish_policy` / `range_batch_scheduler` omitting `index_text` rebuilt the live ledger. They remain fail-closed empty if OTC is included, not weekend COMPLETE.
- `publish_ops_projection` private loader is the shared reader. It is not; omitted/`OSError`/blank is still `None`.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- PARSE_ZERO `2002-08-02` / `2002-08-05` are sealed. `PARSE_ZERO_SEAL_PROOF` is empty.
- This file is not a seal, densify, floor bump, Mass ON, Phase 6.3.2 COMPLETE, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `02fb6cbd`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18301` still counts historical `completeness=COMPLETE` strings.
- Shared `read_local_index_text` / `BackfillPlanner.plan(index_text=...)` / `cf_premium_backfill --index-text` / remaining receipt CLIs / pipeline `index_text` were confirmed from source + unit tests at HEAD (unchanged vs `2b82ec7d`); they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit callers (`snapshot_publish_policy`, `range_batch_scheduler`) were not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar` and `test_planner_omitted_index_text_is_not_weekend_complete`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass. Worker availability unit pins ingest-time fail-safe only.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
- Premium Worker units were confirmed from source + vitest pins; they were not executed against a live Worker / R2 / J-Quants in this isolation worktree.
- `publish_ops_projection.load_otc_index_text` was not migrated to the shared reader. Residual only; omitted/blank is still fail-closed empty. Not scored as Independent A P0.
