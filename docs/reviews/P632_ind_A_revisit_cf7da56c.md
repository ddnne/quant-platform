# Independent review A revisit — at `cf7da56c`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `cf7da56c` (`cf7da56c17260da2c2693540f28af91c849bd542`)  
**Branch at audit:** `grok/p632-ind-A-revisit-cf7da56c` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freeze:** `02fb6cbd` ([`P632_ind_A_revisit_02fb6cbd.md`](P632_ind_A_revisit_02fb6cbd.md)). Earlier: `2b82ec7d` ([`P632_ind_A_revisit_2b82ec7d.md`](P632_ind_A_revisit_2b82ec7d.md)); `242c2484` ([`P632_ind_A_revisit_242c2484.md`](P632_ind_A_revisit_242c2484.md)); `3b64bdfc` ([`P632_ind_A_revisit_3b64bdfc.md`](P632_ind_A_revisit_3b64bdfc.md)); `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md)); `ed94d504` ([`P632_ind_A_revisit_ed94d504.md`](P632_ind_A_revisit_ed94d504.md)); `5103b26b` ([`P632_ind_A_revisit_5103b26b.md`](P632_ind_A_revisit_5103b26b.md)). This file does not rewrite those freezes.  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A at current `origin/grok/phase63-ci-source-closure` vs `02fb6cbd`. Named tree deltas: dateMode Worker unit, leftover catalog grep drop, JSDA fail-closed token, NK rebuild Worker unit. Those are **not** Independent A P0s unless they reopen PIT / COMPLETE. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, Phase 6.3.2 COMPLETE, or Phase 7 GO.

`git rev-list --count 02fb6cbd..cf7da56c` = **14**. PIT / `coverage_ledger` / `backfill_planner` / `core_v1` / `research_data_profile` / pipeline / archive / `official_index` / `snapshot_publish_policy` / `range_batch_scheduler` / receipt CLIs / `cf_premium_backfill` have **empty** `git diff --stat` this window. Production Worker sources (`ingestion-jsda/src/index.ts`, `ingestion-premium/src/{catalog,index,natural_key_migration}.ts`) are also empty this window. Independent-A-adjacent code is Worker-unit pins plus Python grep deletions.

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| leftover catalog.ts grep dropped; Worker catalog.test.ts owns identity | `44642dfc` | not an Independent A P0 (Python id-set vs JSON; Worker `toHaveLength(23)` is premium-core **paths** — not Dataset COMPLETE 23) |
| premium dateMode is JSON contract via Worker unit | `2218b861` | not an Independent A P0 (ingest query `date_mode` mapping; not a PIT `as_of` read path) |
| JSDA worker fail-closed run-token and no invented COMPLETE | `afd94e58` | not an Independent A P0 (401 without fetch/persist; body forbids `COMPLETE`/`READY`; not a calendar walk) |
| premium NK rebuild is Worker unit not Python grep | `8fc9fa30` | not an Independent A P0 (D1 natural-key migration control-row `READY` ≠ research READY snapshot; does not read payload `available_at`) |

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**. Live STALE V2 floors are last-known, not current V3.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 189739 (~52.7 h) |
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

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s Worker units):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set. PARSE_ZERO `2002-08-02` / `2002-08-05` stay PARTIAL (`PARSE_ZERO_SEAL_PROOF` empty). Live STALE V2 floors are last-known.

Same generation as the `02fb6cbd` freeze (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 188693 → 189739. Floors and 4-PARTIAL set are unchanged. `raw_retention.complete` stayed 18301 — still the live raw-manifest column, **not** Coverage COMPLETE.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b` / `3b64bdfc` / `242c2484` / `2b82ec7d` / `02fb6cbd`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` | At `3b64bdfc` | At `242c2484` | At `2b82ec7d` | At `02fb6cbd` | At `cf7da56c` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `plan_required_segments` clip unchanged) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `index_text` callers unchanged this window; omit-without-HTML still empty; JSDA still skipped at `plan()`; Worker 401 does not walk a calendar) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged; dateMode is ingest query mapping; NK rebuild does not read payload `available_at`) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; Worker required-segment INSERT is still `UNKNOWN`; JSDA 401 does not persist) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; empty-observed gate unchanged; PARSE_ZERO 2 stay PARTIAL; JSDA body forbids `COMPLETE`; NK migration `READY` ≠ Dataset COMPLETE) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master; NK control-row `READY` is not a research READY snapshot) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `02fb6cbd`. dateMode Worker unit / leftover catalog grep drop / JSDA fail-closed token / NK rebuild Worker unit do **not** reopen PIT or COMPLETE. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## Tree deltas after `02fb6cbd`

Window: `02fb6cbd..cf7da56c` (14 commits). Independent A core surfaces (`packages/data_plane/pit/`, `coverage_ledger.py`, `backfill_planner.py`, `core_v1.json`, `research_data_profile.py`, pipeline, archive, `official_index.py`, receipt CLIs, `cf_premium_backfill.py`) have **empty** `git diff --stat`. Production Worker sources named above are empty this window. Code landings are Worker-unit tests plus Python grep deletions.

Code landings at this HEAD (not Independent A P0; do not mint COMPLETE / FRESH / READY / GO):

1. **leftover catalog.ts grep drop** (`44642dfc`). `tests/test_phase35_premium_set.py` no longer reads `catalog.ts`. Python still asserts `set(_contract_entries()) == set(PREMIUM_CORE_DATASETS)`. Worker identity remains `catalog.test.ts` (`toHaveLength(23)` is premium-core **path count**, not Dataset COMPLETE 23).
2. **premium dateMode Worker unit** (`2218b861`). `catalog.test.ts` maps every JSON `date_mode` onto Worker `spec.dateMode` (and `day_param` → `dayParam` when present). Production `catalog.ts:93-99` already did `dateMode: contract.date_mode`. Ingest query construction, not a PIT `as_of` look-ahead. Planner official-domain clip is unchanged.
3. **JSDA fail-closed run-token** (`afd94e58`). `ingestion-jsda/src/index.test.ts` executes `/health` and `/v1/run` against mock env. Missing / wrong / unbound `INGESTION_RUN_TOKEN` is **401** `{error: "unauthorized"}`. No live JSDA HTML fetch. No D1/R2 persist. Body `not.toContain("COMPLETE")` / `not.toContain("READY")` and does not leak the token. Production `index.ts:610-611` still returns 401 before run. Does not walk a calendar. Does not mint Dataset COMPLETE.
4. **premium NK rebuild Worker unit** (`8fc9fa30`). `natural_key_migration.test.ts` executes `rebuildNaturalKeysV2` / `requireNaturalKeysV2Ready` against in-memory SQLite D1. Control-row state `READY` is **natural-key migration** (`NATURAL_KEY_MIGRATION_ID=jquants-premium-natural-keys-v2`), not a published research READY snapshot. `requireNaturalKeysV2Ready` fails closed on `PENDING`/`REJECTED`. Source pin: `index.ts` contains `await requireNaturalKeysV2Ready(env.DB)` and does **not** contain `typeof row["available_at"]`. Python grep of `natural_key_migration.ts` was dropped. Live MCP `latest_ready_snapshot` is still **null**.

Remaining 10 commits are docs (Independent A/B/C revisits at `02fb6cbd`, wave-11, test inventory, verify_ci code-lane, banners, §10 mixed, review index). [`P632_ind_A_revisit_02fb6cbd.md`](P632_ind_A_revisit_02fb6cbd.md) is the prior Independent A freeze; this file does not rewrite it.

Feature branch is **not** merged to `origin/main` (`git merge-base --is-ancestor cf7da56c origin/main` is false). Isolation did not push `main` and did not deploy.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; `plan_required_segments` clip unchanged this window)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-9,350-430,508-578`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

No `02fb6cbd..cf7da56c` rewrite of master / AM / earnings official-domain clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. All governed JQ jobs still come from `plan_required_segments` (`backfill_planner.py:557-568`). dateMode Worker unit pins JSON `date_mode` onto ingest specs; it does not call `plan_required_segments` and does not rewrite V2 floors. Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened; `index_text` callers unchanged this window; omit-without-HTML still empty; JSDA Worker 401 does not walk a calendar)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ops/backfill_planner.py:4-9,408-430,508-538,563-567`; `packages/data_plane/ingestion/jsda/official_index.py:16-40,43-81`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `packages/data_plane/ingestion/pipeline.py:119-163,448-479`; `scripts/jsda_otc_seal_official.py:33-35,50-55,135-149`; `scripts/ops/cf_premium_backfill.py:57-59,210-218,256-274`; `tests/test_backfill_planner.py:422-536`; `tests/test_jsda_otc_official_domain.py:189-210`; `tests/test_cf_premium_backfill_cli.py:98-139`; `platform/workers/ingestion-jsda/src/index.test.ts:63-157`

observed fact (HEAD vs `02fb6cbd`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:912-917`). OTC grain in tree JSON remains `official_archive_index_day`. Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty (`test_refresh_without_index_text_is_fail_closed_empty_not_calendar`). Ledger / pipeline / archive / planner / shared reader / `cf_premium_backfill` files are unchanged this window.

**Unchanged — remaining omit-without-HTML callers.** Pipeline persist still has no year-index HTML → `_index_text_for_plan(policy)` with none (`pipeline.py:448-450`). `snapshot_publish_policy` still omits `index_text` (`:109-111`). `range_batch_scheduler.plan()` still omits the kwarg (`:463`). `publish_ops_projection.load_otc_index_text` is still a private loader (`:48-58`), not the shared reader; omitted/`OSError`/blank still `None`.

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `cf7da56c` |
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

JSDA Worker unit (`afd94e58`) does not fetch year-index HTML and does not walk a calendar. 401 fail-closed is token auth, not official-index days. Premium NK / dateMode / catalog units do not republish the OTC required set.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / CLIs is not a live official-index republish. JSDA Worker 401 is not Dataset COMPLETE.

structural fix (still in tree): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; dateMode is ingest query mapping; NK rebuild does not read payload `available_at`)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`; `packages/product/research/eval_loaders_sidecars.py:404-427`; `packages/research_runtime/core/universe.py:15-19,32`; `packages/research_runtime/features/runtime.py:108-124`; `platform/workers/ingestion-premium/src/catalog.test.ts:18-30`; `platform/workers/ingestion-premium/src/natural_key_migration.test.ts:151-236`

No PIT file changes `02fb6cbd..cf7da56c`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of` + `available_at <= as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

dateMode Worker unit (`2218b861`) executes JSON `date_mode` → Worker `spec.dateMode`. That is ingest query construction, not a PIT read path and not a look-ahead rewrite of `as_of`. NK rebuild unit (`8fc9fa30`) pins `index.ts` does not read payload `available_at` (`typeof row["available_at"]` absent). Fixture D1 rows carry an `available_at` column for identity rebuild; that is not `pit.get_*`. Premium Worker units do not open a PIT read path.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1423-1432,1439`; `platform/workers/ingestion-premium/src/collection_receipts.test.ts:47-81`; `platform/workers/ingestion-jsda/src/index.test.ts:117-157`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint.

Worker `writeRequiredCoverageSegment` still inserts `coverage_segments` as `'UNKNOWN'` with planned query units (`collection_receipts.test.ts:61-80`; file unchanged this window). JSDA `/v1/run` 401 does not persist D1/R2 (`sql`/`r2Ops` empty). Catalog / dateMode / NK units do not sign receipts.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:127-138,330-354,357-434`; `scripts/jsda_otc_seal_official.py:50-55,120-132`; `tests/test_phase61_coverage_v2.py:126-251,372-`; `platform/workers/ingestion-jsda/src/index.test.ts:63-157`; `platform/workers/ingestion-premium/src/catalog.test.ts:5-16`; `platform/workers/ingestion-premium/src/natural_key_migration.test.ts:173-227`

No `02fb6cbd..cf7da56c` change to `_empty_observed_forbids_complete`. Tip / archive-index empty SUCCESS stays PARTIAL even if `event_driven` (`:338-342`, `:397-400`). Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18301` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE.

JSDA Worker unit forbids the string `COMPLETE` in health/401 bodies and does not persist. Catalog `toHaveLength(23)` is premium-core path count — **not** Dataset COMPLETE 23. Cron/validation `datasetCount=23` is still not Coverage COMPLETE. NK rebuild `status.state="READY"` is natural-key migration control-row, **not** Dataset COMPLETE and **not** a research READY snapshot. PARSE_ZERO days `2002-08-02` / `2002-08-05` stay PARTIAL: `PARSE_ZERO_SEAL_PROOF: dict[str, tuple[str, int]] = {}` (no in-repo digest+count). Empty SUCCESS shell Python invariant remains (`test_receipt_observed_window_ignores_empty_success_shells`). Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat Worker catalog 23, cron `datasetCount=23`, JSDA health `datasets: 3`, or NK migration `READY` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`; `platform/workers/ingestion-premium/src/natural_key_migration.ts:100-106,410`

No `02fb6cbd..cf7da56c` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. NK migration control-row `READY` (`requireNaturalKeysV2Ready`) is a D1 identity gate, not `profile_ready` and not a published READY generation. Premium Worker units do not publish READY. This review does not publish READY.

---

## Named tree deltas (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** at `cf7da56c`; do not reopen named A holes  
file:line: `platform/workers/ingestion-premium/src/catalog.test.ts`; `platform/workers/ingestion-jsda/src/index.test.ts`; `platform/workers/ingestion-premium/src/natural_key_migration.test.ts`; `tests/test_phase35_premium_set.py:78-80`; `tests/test_identity_runtime_parity.py:1-6`

- Leftover catalog.ts grep drop: Python owns JSON id-set; Worker catalog.test.ts owns Worker identity. `length===23` is JSON path identity, not Coverage COMPLETE.
- dateMode Worker unit maps JSON `date_mode` onto ingest `spec.dateMode`. Not a PIT `as_of` bypass.
- JSDA fail-closed token: 401 without fetch/persist; body forbids `COMPLETE`/`READY`. Not a calendar COMPLETE.
- NK rebuild Worker unit: D1 natural-key migration control-row `READY` / fail-closed `PENDING`/`REJECTED`. Does not read payload `available_at`. Not research READY. Not Dataset COMPLETE.

These are Worker-unit pins replacing Python greps, not a PIT bypass, not an official-domain reopen, and not READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-`index_text` / shared reader / backfill `--index-text` / Worker units are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE. Worker catalog `length===23` is not Coverage COMPLETE. JSDA health `datasets: 3` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- dateMode / catalog grep drop / JSDA fail-closed token / NK rebuild Worker units rebuilt production D1. Isolation did not run live JSDA fetch, seal, premium `/v1/run`, or NK rebuild against production D1/R2.
- NK migration control-row `READY` is a published research READY snapshot. It is not. Live `latest_ready_snapshot` is **null**.
- Worker required-segment INSERT `UNKNOWN` is Dataset COMPLETE. It is not.
- JSDA 401 `{error: "unauthorized"}` is Dataset COMPLETE. It is not.
- Pipeline persist with no held HTML rebuilt the live ledger. Persist is fail-closed empty for OTC, not weekend COMPLETE, and not FRESH.
- Caller `snapshot_publish_policy` / `range_batch_scheduler` omitting `index_text` rebuilt the live ledger. They remain fail-closed empty if OTC is included, not weekend COMPLETE.
- `publish_ops_projection` private loader is the shared reader. It is not; omitted/`OSError`/blank is still `None`.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- PARSE_ZERO `2002-08-02` / `2002-08-05` are sealed. `PARSE_ZERO_SEAL_PROOF` is empty.
- This file is not a seal, densify, floor bump, Mass ON, Phase 6.3.2 COMPLETE, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `cf7da56c`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests at the prior freeze; live `raw_retention.complete=18301` still counts historical `completeness=COMPLETE` strings.
- Shared `read_local_index_text` / `BackfillPlanner.plan(index_text=...)` / `cf_premium_backfill --index-text` / remaining receipt CLIs / pipeline `index_text` were confirmed from source + unit tests at HEAD (unchanged vs `02fb6cbd`); they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit callers (`snapshot_publish_policy`, `range_batch_scheduler`) were not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar` and `test_planner_omitted_index_text_is_not_weekend_complete`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass. dateMode unit pins ingest query mapping only. NK unit pins ingest-time identity rebuild and no payload `available_at` read.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
- Worker units were confirmed from source + vitest pins; they were not executed against a live Worker / R2 / J-Quants / JSDA HTML in this isolation worktree.
- `publish_ops_projection.load_otc_index_text` was not migrated to the shared reader. Residual only; omitted/blank is still fail-closed empty. Not scored as Independent A P0.
