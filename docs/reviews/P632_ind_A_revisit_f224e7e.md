# Independent review A revisit — at `f224e7e`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `f224e7e` (`f224e7e922d93dfdcc14ae86578883cad337ebca`)  
**Branch at audit:** `grok/p632-ind-A-revisit-f224e7e` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freezes:** `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md))  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A (PIT / official domain / false-COMPLETE / READY-DEPS) after landings named below. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

Later landings on this branch (after `d93335b`; verified in tree, not trusted from titles):

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| V3 planner clips official domain | `5796fb0` / `025395f` | IND-A-DOMAIN |
| OTC required days from official index | `9a63402` | IND-A-JSDA-PHANTOM |
| master PIT clamp 2008-05-07 | `e22b33f` | IND-A-PIT-BYPASS |
| FeatureContext official island | `154472f` | IND-A-PIT-BYPASS |
| `fixed_universe` PIT proof | `8ae9363` | IND-A-PIT-BYPASS |
| eval sqlite `as_of` | `6bee72a` | IND-A-PIT-BYPASS |
| tip-snapshot empty PARTIAL | `5c9c93a` | IND-A-FALSE-COMPLETE |
| `profile_ready` rejects string COMPLETE | `b23820e` | IND-A-FALSE-COMPLETE |
| raw `ACQUIRED` | `42b0e37` / `697fb1a` | IND-A-FALSE-COMPLETE |
| missing V3 fail-closed | `f224e7e` | IND-A-FALSE-COMPLETE / READY-DEPS |
| `core_v1` includes master | `aaa830f` | IND-A-READY-DEPS |

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 181072 (~50.3 h) |
| `stages.refresh_success` | **false** |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.governed_dataset_count` | 26 |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |
| `sync_status` | `applied_cursor` **null**; datasets `LAGGING_APPLY_UNPINNED` / `EXPORT_CURRENT_APPLY_UNPINNED` |
| `validation_summary.dataset_count` | 23 (cron/validation run of current datasets — **not** Dataset COMPLETE 23) |
| `ingestion_last_run.detail.datasetCount` | 23 passed (same: current jquants cron, not Coverage COMPLETE) |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. Reconstitution apply remains **false**. This file is not a ledger refresh and is not Dataset COMPLETE 23.

---

## Scoreboard vs `3ab87d0` / `d93335b`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` |
|----|-------|-----|--------------|--------------|--------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | **FIXED** (parallel SoT + tip BackfillPlanner residuals closed; live STALE still V2) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | **OPEN** (planner index-days FIXED; refresh inventory replay still OPEN) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | **FIXED** (named read paths gated; `available_at` still ingest-time fail-safe) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | **FIXED** (tip empty PARTIAL; string COMPLETE rejected; raw ACQUIRED; missing V3 fail-closed) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | **FIXED** (`core_v1` includes `equities_master`) |

Independent P0 remaining: **1** (IND-A-JSDA-PHANTOM — live refresh still replays calendar inventory). Tree-level planner / PIT / false-COMPLETE / core-deps holes named at `3ab87d0` are closed. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/coverage_ledger.py:198-285`; `packages/data_plane/ops/backfill_planner.py:404-517`; `packages/data_plane/data_contracts/canonical_datasets.json:19`; `packages/edge/cf_platform/ingest_premium/coverage.py:23`; `packages/data_plane/ops/range_batch_scheduler.py:75-76`; `packages/data_plane/data_contracts/jquants_premium_core.json:55,150`; `packages/data_plane/data_contracts/permanent_defer.py:113-131`

observed fact (HEAD vs `d93335b`):

`plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment (`:282-285`). Missing V3 loads as `None` and falls through to coverage JSON (`source_capability_contract_or_none`); evaluate of that segment without a receipt is PARTIAL, not COMPLETE (`tests/test_source_capability.py:78-96`).

Residuals named at `d93335b` that **closed** in tree:

1. **`BackfillPlanner` tip path.** `_is_tip_snapshot_dataset` now calls `_jobs_from_required_segments` → `plan_required_segments` (`backfill_planner.py:506-516`). AM / earnings are not month-chunked there (`792ae2b`).
2. **Parallel SoT master start is 2008-05-07:** `canonical_datasets.json:19`, `EXPECTED_START["equities_master"]`, `TRACK_A_FOCUS_RANGES["equities_master"]`.
3. **JQ vendor params:** AM `params=["code","pagination_key"]`; earnings `params=["pagination_key"]` (no `from`/`to`/`date` range).
4. **`source_capability.py` docstring** now says the ledger **must** subset official domain (`:8-10`). Stale “does not rewrite `plan_required_segments`” sentence is gone.
5. **Vendor annotations** are retained on `CollectionCoverageContract` and are **not** copied into `history_target_start` (`coverage.py:54-74,117-119`).
6. **`MASTER_JQ_SCOPE` MISDATE** is `excluded_official_unavailable`, not `REQUIRED_PARTIAL` (`permanent_defer.py:113-131`).

why it still matters: claiming Dataset COMPLETE 23 from this SHA would convert excluded MISDATE / tip months to COMPLETE. Live MCP is **STALE** and still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger.

residual (do **not** reopen the planner P0; still not FRESH): live `dataset_coverage("equities_master")` `policy_version=collection-coverage/v2`, `history_target_start=2006-08-13`, 241 required / 21 PARTIAL. `applied_cursor` null.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **OPEN** (planner calendar-walk **FIXED**; `refresh_coverage_ledger` inventory replay **OPEN**)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-214,286-292,894-909`; `packages/data_plane/ingestion/jsda/official_index.py:42-52`; `packages/data_plane/data_contracts/collection_coverage.json:165-172`; `scripts/write_collection_receipts.py:99-101`

observed fact:

**FIXED (must stay):** `plan_required_segments` takes official-archive-index datasets through `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-292`). Missing `index_text` yields an **empty** required set, not a calendar walk (`:212-214`; `test_plan_required_segments_fail_closed_without_index_text`). Tiny fixture lists `2002-08-02/05/06` and excludes weekend `2002-08-03` (`test_plan_required_segments_uses_official_index_not_calendar`). V3 grain in the capability JSON is `official_archive_index_day`. Empty archive-index receipts are PARTIAL (`_empty_observed_forbids_complete`, `:343`). PARSE_ZERO `2002-08-02` / `2002-08-05` stay `stay_PARTIAL`; `parse_zero_invent_complete=FORBIDDEN`. 23-col parse is still not Coverage COMPLETE.

**OPEN — production refresh still replays calendar inventory.** `collection_coverage.json` OTC grain is still `official_archive_day` (`:172`). `refresh_coverage_ledger` for that grain **does not** call `plan_required_segments`; it rebuilds required from existing inventory (`:894-909`). Phantom weekend/holiday ids persist once recorded. Live STALE `backfill_status` is still **8784 = 5886 COMPLETE + 2898 PARTIAL**. `write_collection_receipts.py` calls `plan_required_segments` **without** `index_text` (`:99-101`) → empty OTC required set (fail-closed, not a weekend COMPLETE mint, and not a live index rebuild).

root cause (remaining): live required inventory used by refresh/evaluate is still the recorded calendar set; the planner is wired only when `index_text` is supplied.

why it matters: Completing 2510 weekend ids (or raising the floor to 2002-08-06) still invents COMPLETE against the live inventory. Leaving phantoms in the refresh path keeps Dataset PARTIAL without a source gap. Empty evaluate on archive-index is now PARTIAL — that blocks empty-COMPLETE of phantoms, it does not drop them from required.

structural fix (unchanged for the live path): refresh required set = official index days (plus remaining PARSE_ZERO publication files until sealed). Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (named bypasses gated; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`; `packages/data_plane/data_contracts/identity.py:285-308`; `packages/product/research/eval_loaders_sidecars.py:401-427`; `packages/research_runtime/core/universe.py:106-164,171-201`; `packages/research_runtime/core/engine.py:448-492`; `packages/research_runtime/features/runtime.py:86-109`

observed fact (the five holes named at `3ab87d0` / `d93335b`):

1. **Official PIT history start is production.** `get_equity_master` loads `source_capability_contract_for("equities_master")` and clips `snapshot_date` via `apply_official_query_clamp` to `earliest_official_availability` (`pit/api.py:286-303`). `as_of` for `available_at <= as_of` is **not** rewritten (`:280-281`). The test helper is no longer the only clamp.
2. **`available_at_for` consults official start.** Pre-official event/session dates under `ingest_time_conservative` / `calendar_prepublished` stay `ingested_at` (`identity.py:299-308`). Master policy remains `ingest_time_conservative` (`jquants_premium_core.json:12`). Nested V3 17:30 JST publication calendar is still not the timestamp writer. That is fail-safe (historical `as_of` sees nothing, not look-ahead).
3. **Eval sqlite is PIT-gated.** `load_repo_rows_from_sqlite` requires keyword `as_of` and SQL `available_at IS NOT NULL AND available_at <= ?` (`eval_loaders_sidecars.py:401-427`). Callers (`eval_loaders`, `cf_mass_eval_thicken`, `offline/factory_eval_data`, `offline/multiyear`) pass `as_of`. Empty/`None` raises (`test_eval_loaders.py:159-170`).
4. **Fixed universe cannot skip PIT membership.** `run_backtest(..., universe=...)` goes through `resolve_injected_universe`. Raw code lists raise `RawFixedUniverseError` unless `QP_ALLOW_FIXED_UNIVERSE=1` (research-only; not Mass / READY / GO) (`universe.py:15-19,106-164`; `test_core_engine.py:415-433`). Default path still `load_master(decision_as_of)` every day (`engine.py:489-492`). `load_master` requires `as_of` and calls `pit.get_equity_master`.
5. **FeatureContext official island.** `FeatureContext.get_equity_master` no longer `require_feature_dataset` → `PermanentDeferHistoryError`. Pre-`2008-05-07` `as_of` returns empty `PitResult`; otherwise `_read("equity_master")` → `pit.get_equity_master` (`runtime.py:86-109`; `154472f`). Generic `get_jquants_records("equities_master")` still DEFERs (PD-D2-MASTER). Tip-only AM / earnings / OTC stay DEFER.

`pit.query.run_query` still always AND-gates `available_at <= as_of` (`query.py:175-191`). That gate remains **FIXED** and must stay.

why it still matters: ingest-time `available_at` means a 2010 `as_of` does not see 2026-ingested master rows. That is conservative, not a look-ahead bypass. Do not claim PIT history from 2008-05-07 is a populated island until publication-calendar `available_at` is written. `QP_ALLOW_FIXED_UNIVERSE=1` remains an explicit research escape, not GO.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1399`

No production change in this window re-exports `build_synthetic_complete_receipt` from `storage` (`__init__.py:34`). COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Keep cryptographic eligibility. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:326-343,386-389`; `tests/test_phase61_coverage_v2.py:126-152`; `platform/workers/ingestion-premium/src/index.ts:516-561`; `packages/product/research/research_data_profile.py:183-201,385-409`; `tests/test_source_capability.py:99-135`

observed fact:

**FIXED (must stay):** `evaluate_segment` PARTIAL on missing receipt, unsigned / RECOVERED_RAW_ONLY, non-exhausted pagination, raw/structured mismatch, non-event empty `observed_items`.

**FIXED — tip-snapshot empty is PARTIAL.** `_empty_observed_forbids_complete` is true for snapshot coverage_mode / snapshot grains / official_archive_index (`coverage_ledger.py:326-343`). Earnings calendar `coverage_mode=next_business_day_snapshot` + `collection_cutoff_snapshot`; AM `recent_snapshot` + `same_trading_day_am_snapshot`. `test_tip_snapshot_empty_receipt_is_partial_not_complete` pins both (`test_phase61_coverage_v2.py:136-152`). IND-A-DOMAIN already dropped the 199-month empty-COMPLETE path from required inventory.

**FIXED — READY predicate rejects a string `"COMPLETE"`.** `_complete_under_official` requires a mapping (`:398-399`). `test_profile_ready_rejects_string_complete_labels` pins this. STALE `projection_status` and null `applied_cursor` are false (`:400-403`; `test_profile_ready_false_on_stale_v2_live_evidence`).

**FIXED — missing V3 is not official-complete.** `_complete_under_official` returns False when `source_capability_contract_or_none(dataset_id) is None` (`:393-394`). Core `required_datasets` still include fins_* / bars / calendar **without** V3 JSON, so `profile_ready(load_core_profile(), synthetic_COMPLETE_maps)` is **False** (`test_profile_ready_missing_v3_is_not_official_complete`). That is fail-closed, not a READY publish.

**FIXED — new raw writes are `ACQUIRED`, not Coverage COMPLETE.** Worker `ingestion-premium` sets `raw_acquisition = complete ? "ACQUIRED" : "FAILED"` and stores that string in the `completeness` column (`index.ts:516-561`). Tests pin `body.raw_acquisition === "ACQUIRED"` and `not.toHaveProperty("completeness")` on the HTTP body. MCP `classifyRawAcquisition` still maps historical `completeness=COMPLETE` rows to acquisition states, not ledger COMPLETE (`domain.js:112-121`). Live `ops_status.raw_retention.complete=18255` is that column’s historical COMPLETE count — **not** Dataset COMPLETE.

**Residual (not a reopen of the named P0):** `test_event_zero_successful_exhausted_raw_receipt_is_complete` still pins COMPLETE for genuine `event_driven` fins windows (`fins_summary`). That is the Coverage V2 event-zero rule the original review left for disclosures, not the earnings/AM monthly-shell path. MCP SQL still `SUM(completeness='COMPLETE')` over raw manifests (legacy enum). Column name `completeness` still exists.

Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`; `packages/product/research/hypothesis_classes.py:248-254`

observed fact:

`core_v1.json` `required_datasets` now starts with **`equities_master`**, then bars / fins_* / `markets_calendar`. `CORE_REQUIRED_DATASETS` matches. `load_core_profile` → `_assert_core_exclusions` fails if any core historical dataset is omitted (`:378-382`). `test_tip_only_not_in_core` asserts `"equities_master" in profile.required_datasets`. Tip-only AM / earnings remain excluded (`:32-35`). `contract_versions.coverage_policy` stays `collection-coverage/v2` (document root; live MCP is STALE V2 — `04af1ed`).

`profile_ready` ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. This review does not publish READY.

residuals (do **not** reopen the core-omission P0):

1. **`resolve_deps` still does not expand `permitted_universe` names into `equities_master`.** Non-core profiles with a universe and no master listed can still construct. Core construction is protected by `CORE_REQUIRED_DATASETS`.
2. **`CLASS_FUNDAMENTALS_PRICE.datasets_required`** is still fins_* + bars + calendar — no master — while `constraints` include `pit_available_at_for_fundamentals` (`hypothesis_classes.py:248-254`). Hypothesis class, not the READY(P) predicate.
3. **`official_mode(d)`** still reads V2 `coverage_contract_for(d).coverage_mode`, not SourceCapabilityContract.

why it still matters: adding master without a FRESH official-domain ledger keeps READY false — honest until live inventory is rebuilt from the wired planner. Omitting master to avoid STALE PARTIAL was the forbidden shortcut; that shortcut is gone on core.

---

## What this review does not claim

- Planner / PIT / profile wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- OTC live required set = official index days. Planner is wired; refresh still replays 8784 calendar ids.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or OTC index required set.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18255` still counts historical `completeness=COMPLETE` strings.
- `refresh_coverage_ledger` OTC inventory replay was confirmed from source (`coverage_ledger.py:894-909`); it was not executed against a live DB in this isolation worktree.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
