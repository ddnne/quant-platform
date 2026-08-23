# Independent review A revisit — at `b1605c36`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `b1605c36` (`b1605c36e4a5f2c5048264d71baadea8589c4ed4`)  
**Branch at audit:** `grok/p632-ind-A-revisit-b1605c36` (from `origin/grok/phase63-ci-source-closure` at this SHA; did not checkout `grok/phase63-ci-source-closure` by name)  
**Prior freeze:** `b5f6f2de` ([`P632_ind_A_revisit_b5f6f2de.md`](P632_ind_A_revisit_b5f6f2de.md)). Earlier: `cf7da56c` ([`P632_ind_A_revisit_cf7da56c.md`](P632_ind_A_revisit_cf7da56c.md)); `02fb6cbd` ([`P632_ind_A_revisit_02fb6cbd.md`](P632_ind_A_revisit_02fb6cbd.md)); `2b82ec7d` ([`P632_ind_A_revisit_2b82ec7d.md`](P632_ind_A_revisit_2b82ec7d.md)); `242c2484` ([`P632_ind_A_revisit_242c2484.md`](P632_ind_A_revisit_242c2484.md)); `3b64bdfc` ([`P632_ind_A_revisit_3b64bdfc.md`](P632_ind_A_revisit_3b64bdfc.md)); `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md)); `ed94d504` ([`P632_ind_A_revisit_ed94d504.md`](P632_ind_A_revisit_ed94d504.md)); `5103b26b` ([`P632_ind_A_revisit_5103b26b.md`](P632_ind_A_revisit_5103b26b.md)). This file does not rewrite those freezes.  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A at current `origin/grok/phase63-ci-source-closure` vs `b5f6f2de`. Named tree deltas: C12 addon ids from catalog, ops fail-closed Worker units (cold-archive / changelog prune / parquet-manifest / artifacts-plan), master SCD2 write unit. Those are **not** Independent A P0s unless they reopen PIT / COMPLETE. Addon ids from catalog is **not** Dataset COMPLETE 23. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, Phase 6.3.2 COMPLETE, or Phase 7 GO.

GitHub compare `b5f6f2de...b1605c36`: **16** commits, **17** files, `ahead_by=16`. PIT / `coverage_ledger.py` / `backfill_planner.py` / `core_v1.json` / `research_data_profile.py` / pipeline / archive / `official_index.py` / `snapshot_publish_policy.py` / `range_batch_scheduler.py` / receipt CLIs / `cf_premium_backfill.py` have **identical git blob SHAs** this window (empty `git diff`). Production Worker sources (`ingestion-premium/src/{catalog,index,natural_key_migration,http_export,r2_structured_writer,rate_limit,collection_receipts,ops_cold_archive,ops_prune_changelog,ops_parquet_manifest,ops_artifacts_plan}.ts`, `master_scd2/write.ts`) are empty this window. Independent-A-adjacent code is one Python catalog-id map plus Worker-unit tests.

Blob identity vs `b5f6f2de` (unchanged): `coverage_ledger.py` `f6b0f6ba`; `backfill_planner.py` `c74b711c`; `pit/api.py` `b70a2d6f`; `pit/query.py` `debaece1`; `official_index.py` `11812220`; `snapshot_publish_policy.py` `e270efa2`; `core_v1.json` `65065e3a`; `master_scd2/write.ts` `136ef73f`.

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| C12 addon guard ids come from catalog not a second list | `de8f87bf` | not an Independent A P0 (C12 leak fail; 5 catalog addon ids disjoint from premium-core; **not** Dataset COMPLETE 23) |
| premium cold-archive token and args are fail-closed Worker unit | `9956ab51` | not an Independent A P0 (401/400; no D1 DELETE / R2 put; body forbids `COMPLETE`) |
| premium changelog prune unbound token is 401 | `9b0582d4` | not an Independent A P0 (401 without D1; not a COMPLETE mint) |
| premium parquet-manifest unbound token is 401 | `359b2566` | not an Independent A P0 (401 without R2 list/put; not a COMPLETE mint) |
| premium artifacts-plan token is fail-closed Worker unit | `329f3959` | not an Independent A P0 (401/400; authorized mock is `mass_research=NO-GO`; forbids `COMPLETE` / READY / GO) |
| premium master SCD2 write is Worker unit with mock R2 | `ee167188` | not an Independent A P0 (ingest `jstDate(when)` effective_date; mock R2; forbids `COMPLETE`; not `pit.get_*`) |

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools were **not callable** in this isolation subagent (no MCP invoke surface). Values below are **this-turn parent reads**. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**. Live STALE V2 floors are last-known, not current V3.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `stages.refresh_success` | **false** |
| `latest_ready_snapshot` | **null** |
| `b0_status` | **UNKNOWN** |
| coverage | **22 COMPLETE / 4 PARTIAL** (`collection-coverage/v2`) |
| `equities_master` | PARTIAL `history_target_start` **2006-08-13** |
| `equities_bars_daily_am` | PARTIAL `history_target_start` **2024-01-04** |
| `equities_earnings_calendar` | PARTIAL `history_target_start` **2010-01-04** |
| `jsda_otc_bond_reference_prices` | PARTIAL `history_target_start` **2002-08-02** |
| `applied_feed_cursor` | **null** → never CURRENT |
| PR #1 | **MERGEABLE / BLOCKED**, check-runs **0** |
| `quant-platform-ci-aggregate` | wrangler deployments list → **10007 Worker does not exist** |
| leftover occupancy | **HOLD** |
| unique22 | **HOLD** |
| reconstitution APPLY | **false** |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live STALE V2 floors are last-known. PARSE_ZERO `2002-08-02` / `2002-08-05` stay PARTIAL (`PARSE_ZERO_SEAL_PROOF` empty). Live STALE is **not** an Independent A P0.

Same generation as the `b5f6f2de` freeze (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew vs 190457 at that freeze. Floors and 4-PARTIAL set are unchanged.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b` / `3b64bdfc` / `242c2484` / `2b82ec7d` / `02fb6cbd` / `cf7da56c` / `b5f6f2de`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` | At `3b64bdfc` | At `242c2484` | At `2b82ec7d` | At `02fb6cbd` | At `cf7da56c` | At `b5f6f2de` | At `b1605c36` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `plan_required_segments` clip unchanged) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `index_text` callers unchanged this window; omit-without-HTML still empty; C12 / ops units / SCD2 mock do not walk a calendar) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged; SCD2 fixture `asOf` is ingest `jstDate(when)`, not `pit.get_*`) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; Worker required-segment INSERT is still `UNKNOWN`; ops 401 does not persist) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; empty-observed gate unchanged; PARSE_ZERO 2 stay PARTIAL; C12 catalog 5-id set and SCD2 / ops bodies forbid `COMPLETE`) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master; artifacts-plan mock is `NO-GO`, not a research READY snapshot) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `b5f6f2de`. C12 addon ids from catalog / ops fail-closed units / SCD2 write unit do **not** reopen PIT or COMPLETE. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE**. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## Tree deltas after `b5f6f2de`

Window: `b5f6f2de..b1605c36` (16 commits). Independent A core surfaces have **empty** `git diff` (identical blobs listed above). Production Worker sources named above are empty this window. Code landings are one C12 catalog-id map plus Worker-unit tests.

Code landings at this HEAD (not Independent A P0; do not mint COMPLETE / FRESH / READY / GO):

1. **C12 addon ids from catalog** (`de8f87bf`). `_ADDON_IDS` is now `frozenset(list_datasets("addon"))` (`coverage.py:18,62-64`). The second hardcoded 5-id list is gone. Worker/Python unit pins catalog addon group (`test_phase35_coverage_daily.py:76-90`): `equities_bars_minute` / `equities_trades` / `td_list` / `td_files` / `td_bulk`, equal to `list_datasets("addon")`, **disjoint** from `PREMIUM_CORE_DATASETS`. C12 **fails** if any of those are present (`coverage.py:569-581`) — leak fail-closed, not a COMPLETE mint. Catalog addon count 5 is not Dataset COMPLETE 23 and not premium-core path count 23. `snapshot_publish_policy` still calls `run_coverage` on governed JQ (`:112-118`); C12 still does not evaluate OTC weekends or rewrite V2 floors.
2. **cold-archive fail-closed Worker unit** (`9956ab51`). `ops_cold_archive.test.ts` executes `handleArchiveCold`. Missing / wrong / unbound `INGESTION_RUN_TOKEN` is **401** `{error: "unauthorized"}`. Missing `dataset` / bad `before` is **400**. SQL and R2 puts stay `[]`. No `DELETE`. No `coverage_segments` / `collection_receipts` / `raw_retention_manifests`. Body forbids `COMPLETE` / READY / Coverage. Production `ops_cold_archive.ts` is unchanged this window (already 401 before D1/R2).
3. **changelog prune unbound 401** (`9b0582d4`). `ops_prune_changelog.test.ts` executes `handlePruneChangelog`. Unbound / missing / wrong token is **401**. D1 `prepare` is never reached (`sql === []`). Body forbids `COMPLETE` / READY. Production handler unchanged this window.
4. **parquet-manifest unbound 401** (`359b2566`). `ops_parquet_manifest.test.ts` executes `handleParquetManifest`. Missing / wrong / unbound token is **401**. R2 `list` / `put` stay `[]`. Body forbids `COMPLETE` / READY. Production handler unchanged this window.
5. **artifacts-plan fail-closed Worker unit** (`329f3959`). `ops_artifacts_plan.test.ts` executes `handleArtifactsJoinPlan`. Unbound / missing / wrong token is **401**; missing `datasets` is **400**. Rejecting D1/R2 are not called on 401. Authorized mock path is **200** `schema=artifacts-join-plan/v1` with `mass_research=NO-GO` (not GO). JSON has no `READY` / `COMPLETE` keys. Production handler unchanged this window. Not a published research READY snapshot.
6. **master SCD2 write Worker unit** (`ee167188`). `master_scd2/write.test.ts` executes `writeMasterScd2` against an in-memory mock bucket. First write puts `CURRENT.json` schema `equities_master_scd2_current/v1` plus one `LISTED` event. Unchanged attrs rewrite CURRENT with `events_key=null`. Changed attrs emit `ATTRIBUTE_CORRECT`. Fixture `AS_OF="2025-04-01"` is ingest `jstDate(when)` (`write.ts:44-47,161`) copied onto event `effective_date` — ingest persist identity, not `pit.get_*`, not an `as_of` look-ahead rewrite. `assertNoCoverageComplete` on snapshot / metadata / events / result. Production `write.ts` blob is unchanged this window (`136ef73f`). Isolation did not put to production R2.

Remaining 10 commits are docs (Independent A/B/C revisits at `b5f6f2de`, original-plan-gap banner, residual SoT banner, §10 mixed, review index, wave-13, test inventory, verify_ci). [`P632_ind_A_revisit_b5f6f2de.md`](P632_ind_A_revisit_b5f6f2de.md) is the prior Independent A freeze; this file does not rewrite it.

Feature branch is **not** merged to `origin/main` (`b1605c36` is not an ancestor of `b5c326a`). Isolation did not push `main` and did not deploy.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; `plan_required_segments` clip unchanged this window)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-9,350-430,508-578`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

No `b5f6f2de..b1605c36` rewrite of master / AM / earnings official-domain clipping (`coverage_ledger.py` blob `f6b0f6ba`; `backfill_planner.py` blob `c74b711c`). `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. All governed JQ jobs still come from `plan_required_segments` (`backfill_planner.py:557-568`). C12 catalog addon ids pin minute/tick/TDnet **out** of premium-core; they do not call `plan_required_segments` and do not rewrite V2 floors. Live STALE still advertises V2 floors (master `2006-08-13`, AM 2024-01-04 / earnings 2010-01-04 inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened; `index_text` callers unchanged this window; omit-without-HTML still empty; C12 / ops units / SCD2 mock do not walk a calendar)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ops/backfill_planner.py:4-9,408-430,508-538,563-567`; `packages/data_plane/ingestion/jsda/official_index.py:16-40,43-81`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `packages/data_plane/ingestion/pipeline.py:119-163,448-479`; `scripts/jsda_otc_seal_official.py:33-35,50-55,135-149`; `scripts/ops/cf_premium_backfill.py:57-59,210-218,256-274`; `tests/test_backfill_planner.py:422-536`; `tests/test_jsda_otc_official_domain.py:189-210`; `tests/test_cf_premium_backfill_cli.py:98-139`

observed fact (HEAD vs `b5f6f2de`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index`. OTC grain in tree JSON remains `official_archive_index_day`. Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). `official_index.py` blob `11812220` unchanged. Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty.

**Unchanged — remaining omit-without-HTML callers.** Pipeline persist still has no year-index HTML → `_index_text_for_plan(policy)` with none (`pipeline.py:448-450`). `snapshot_publish_policy` still omits `index_text` (`:109-111`). `range_batch_scheduler.plan()` still omits the kwarg. `publish_ops_projection.load_otc_index_text` is still a private loader, not the shared reader; omitted/`OSError`/blank still `None`.

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `b1605c36` |
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

A live refresh that omits `index_text` / has no HTML would DELETE the STALE calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still STALE under V2. Canonical inventory still advertises `coverage_segment_granularity=official_archive_day`.

C12 catalog ids / ops 401 units / SCD2 mock put do not fetch year-index HTML and do not walk a calendar. They do not republish the OTC required set.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / CLIs is not a live official-index republish. Ops 401 / SCD2 mock put / C12 5-id pin are not Dataset COMPLETE.

structural fix (still in tree): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; SCD2 fixture `asOf` is ingest `jstDate(when)`; ops units do not open `pit.get_*`)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`; `packages/product/research/eval_loaders_sidecars.py:404-427`; `packages/research_runtime/core/universe.py:15-19,32`; `packages/research_runtime/features/runtime.py:108-124`; `platform/workers/ingestion-premium/src/master_scd2/write.ts:44-47,155-161`; `platform/workers/ingestion-premium/src/master_scd2/write.test.ts`

No PIT file changes `b5f6f2de..b1605c36` (`api.py` blob `b70a2d6f`; `query.py` blob `debaece1`). Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of` + `available_at <= as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at IS NOT NULL AND available_at <= as_of` (`query.py:175-191`). `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

SCD2 write unit (`ee167188`) copies ingest `jstDate(when)` onto event `effective_date` (`write.ts:44-47,161`). That is ingest persist identity, not a PIT read path and not a look-ahead rewrite of research `as_of`. Production writer is unchanged this window (`136ef73f`). C12 / ops 401 units do not read payload `available_at` and do not open `pit.get_*`.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1423-1432,1439`; `platform/workers/ingestion-premium/src/collection_receipts.test.ts:47-81`; `platform/workers/ingestion-premium/src/ops_cold_archive.test.ts`; `platform/workers/ingestion-premium/src/ops_prune_changelog.test.ts`; `platform/workers/ingestion-premium/src/ops_parquet_manifest.test.ts`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint.

Worker `writeRequiredCoverageSegment` still inserts `coverage_segments` as `'UNKNOWN'` with planned query units (file unchanged this window). Cold-archive / changelog prune / parquet-manifest 401 never reach D1. SCD2 writer unit puts JSON to a mock bucket and does not sign receipts. C12 catalog ids do not sign receipts.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:127-138,330-354,357-434`; `scripts/jsda_otc_seal_official.py:50-55,120-132`; `tests/test_phase61_coverage_v2.py:126-251,372-`; `packages/edge/cf_platform/ingest_premium/coverage.py:62-64,569-581`; `tests/test_phase35_coverage_daily.py:76-90`; `platform/workers/ingestion-premium/src/master_scd2/write.test.ts`; `platform/workers/ingestion-premium/src/ops_cold_archive.test.ts`; `platform/workers/ingestion-premium/src/ops_artifacts_plan.test.ts`

No `b5f6f2de..b1605c36` change to `_empty_observed_forbids_complete`. Tip / archive-index empty SUCCESS stays PARTIAL even if `event_driven` (`:330-342`, `:397-400`). Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends.

C12 catalog 5-id set is addon leak identity — **not** Dataset COMPLETE 23. Authorized artifacts-plan mock is `mass_research=NO-GO` and has no `COMPLETE` key. SCD2 writer unit forbids the string `COMPLETE` in snapshot / metadata / events / result. Ops 401 bodies are `{error: "unauthorized"}`, not COMPLETE. PARSE_ZERO days `2002-08-02` / `2002-08-05` stay PARTIAL: `PARSE_ZERO_SEAL_PROOF: dict[str, tuple[str, int]] = {}` (no in-repo digest+count). Empty SUCCESS shell Python invariant remains. Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat C12 catalog 5, Worker catalog/write-path 23, cron `datasetCount=23`, SCD2 mock put, or ops 401 as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`; `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-118`; `platform/workers/ingestion-premium/src/ops_artifacts_plan.test.ts`

No `b5f6f2de..b1605c36` omission of master from core (`core_v1.json` blob `65065e3a`). `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. Artifacts-plan authorized mock is `mass_research=NO-GO` and has no `READY` property; 401 never reaches the join. C12 fail (addon present) is a quality fail that would block READY publication, not a READY mint. Premium Worker units do not publish READY. This review does not publish READY.

---

## Named tree deltas (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** at `b1605c36`; do not reopen named A holes  
file:line: `packages/edge/cf_platform/ingest_premium/coverage.py`; `tests/test_phase35_coverage_daily.py`; `platform/workers/ingestion-premium/src/ops_cold_archive.test.ts`; `platform/workers/ingestion-premium/src/ops_prune_changelog.test.ts`; `platform/workers/ingestion-premium/src/ops_parquet_manifest.test.ts`; `platform/workers/ingestion-premium/src/ops_artifacts_plan.test.ts`; `platform/workers/ingestion-premium/src/master_scd2/write.test.ts`

- C12 addon ids from catalog: `_ADDON_IDS` maps JSON via `list_datasets("addon")`; second hardcoded list dropped. Five addon ids, disjoint from premium-core. Not Coverage COMPLETE.
- Cold-archive / changelog prune / parquet-manifest Worker units: 401/400 without D1/R2 side effects. Bodies forbid `COMPLETE`. Not Dataset COMPLETE.
- Artifacts-plan Worker unit: 401 fail-closed; authorized mock `mass_research=NO-GO`. Not research READY. Not GO.
- SCD2 write Worker unit: mock-bucket CURRENT.json + events; ingest `jstDate(when)`; forbids `COMPLETE`. Not `pit.get_*`. Not Dataset COMPLETE.

These are Worker-unit pins (plus one catalog-id map), not a PIT bypass, not an official-domain reopen, and not READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-`index_text` / shared reader / backfill `--index-text` / Worker units are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. C12 catalog addon count 5 is not Coverage COMPLETE. Worker catalog / write-path `length===23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still STALE calendar ids.
- C12 / ops fail-closed / SCD2 units rebuilt production D1/R2. Isolation did not run live JSDA fetch, seal, premium `/v1/run`, export, archive-cold, or R2 put against production.
- Artifacts-plan mock `NO-GO` is a published research READY snapshot. It is not. Live `latest_ready_snapshot` is **null**.
- Worker required-segment INSERT `UNKNOWN` is Dataset COMPLETE. It is not.
- SCD2 mock CURRENT.json put is Dataset COMPLETE. It is not.
- Pipeline persist with no held HTML rebuilt the live ledger. Persist is fail-closed empty for OTC, not weekend COMPLETE, and not FRESH.
- Caller `snapshot_publish_policy` / `range_batch_scheduler` omitting `index_text` rebuilt the live ledger. They remain fail-closed empty if OTC is included, not weekend COMPLETE.
- `publish_ops_projection` private loader is the shared reader. It is not; omitted/blank is still fail-closed empty.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- PARSE_ZERO `2002-08-02` / `2002-08-05` are sealed. `PARSE_ZERO_SEAL_PROOF` is empty.
- leftover occupancy HOLD / unique22 HOLD / reconstitution APPLY false / ci-aggregate 10007 / PR #1 BLOCKED are live or Independent B/C facts. They are not Independent A P0s and are not GO.
- This file is not a seal, densify, floor bump, Mass ON, Phase 6.3.2 COMPLETE, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was **not** fetched from quant_mcp in this subagent (tools not callable). Parent this-turn reads are **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `b1605c36`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree.
- Shared `read_local_index_text` / `BackfillPlanner.plan(index_text=...)` / `cf_premium_backfill --index-text` / remaining receipt CLIs / pipeline `index_text` were confirmed from source + identical blobs vs `b5f6f2de`; they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit callers (`snapshot_publish_policy`, `range_batch_scheduler`) were not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar` and `test_planner_omitted_index_text_is_not_weekend_complete`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass. SCD2 unit pins ingest `jstDate(when)` copy only.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
- Worker units were confirmed from source + vitest pins; they were not executed against a live Worker / R2 / J-Quants / JSDA HTML in this isolation worktree.
- `publish_ops_projection.load_otc_index_text` was not migrated to the shared reader. Residual only; omitted/blank is still fail-closed empty. Not scored as Independent A P0.
- Isolation did not `wrangler deploy`, did not create `quant-platform-ci-aggregate`, and did not push `main`.
