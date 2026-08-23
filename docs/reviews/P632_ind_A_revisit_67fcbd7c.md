# Independent review A revisit — at `67fcbd7c`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `67fcbd7c` (`67fcbd7cd56847a9fc0fba7bcefbd743b43fc106`)  
**Branch at audit:** `grok/p632-ind-A-revisit-67fcbd7c` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freezes:** `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md))  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A after OTC JSON grain `official_archive_index_day`, `index_text` callers, JSDA archive pass HTML. Prior at `40d1aa90` said tree P0 = 0. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

Landing verified in tree (not trusted from titles):

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| OTC refresh required set from official index | `40d1aa90` | IND-A-JSDA-PHANTOM (refresh wire) |
| optional `--otc-index-html` on projection refresh | `9524dab7` | omit-`index_text` residual (CLI) |
| `--index-text PATH` on `refresh_coverage_ledger` CLI | `34dc85df` | omit-`index_text` residual (CLI) |
| `write_collection_receipts` local OTC index HTML | `db569fc7` | omit-`index_text` residual (CLI) |
| OTC JSON grain `official_archive_index_day` | `26a6ca5e` | grain vs inventory branch |
| JSDA archive refresh reuses fetched year-index HTML | `ddc40ae9` | omit-`index_text` residual (ingest) |

PIT / profile / master / AM / earnings planner files are unchanged `40d1aa90..67fcbd7c`.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 183062 (~50.9 h) |
| `stages.refresh_success` | **false** (`refresh_attempt=true`) |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.governed_dataset_count` | 26 |
| `ops_status.raw_retention.complete` | 18278 (raw-manifest column — **not** Dataset COMPLETE) |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |
| `sync_status` | `applied_cursor` **null**; datasets `LAGGING_APPLY_UNPINNED` / `EXPORT_CURRENT_APPLY_UNPINNED` |
| `validation_summary.dataset_count` | 23 (cron/validation run of current datasets — **not** Dataset COMPLETE 23) |
| `ingestion_last_run.detail.datasetCount` | 23 passed (same: current jquants cron, not Coverage COMPLETE) |
| `collection_sla_status(jsda_otc_bond_reference_prices)` | `current_state` **PROJECTION_STALE** (`ops_projection_stale`) |
| `endpoint_status(...).coverage_segment_granularity` | `official_archive_day` (canonical inventory under STALE projection — **not** the tree JSON grain) |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s refresh wire):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. Reconstitution apply remains **false**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | **FIXED** (not reopened; grain + HTML callers tighten, omit-without-HTML still empty) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | **FIXED** (not reopened) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `40d1aa90`. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,308-313,330-349,779-791,794-808,907-951,1015-1023`; `packages/data_plane/storage/coverage_ledger_io.py:212-250`; `packages/data_plane/ingestion/jsda/official_index.py:14-52`; `packages/data_plane/ingestion/jsda/archive.py:331-344,528-535`; `packages/data_plane/data_contracts/collection_coverage.json:165-172`; `packages/data_plane/data_contracts/coverage.py:34-40`; `tests/test_jsda_otc_official_domain.py:186-375`; `tests/test_jsda_governed.py:48,332-377`; `scripts/refresh_coverage_ledger.py:60-67,82-89,147-160`; `scripts/write_collection_receipts.py:105-138`; `scripts/publish_ops_projection.py:48-58,199-206,242-247`

observed fact (HEAD vs `40d1aa90`):

**FIXED (must stay) — planner.** `plan_required_segments` still takes official-archive-index datasets through `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`) after `_uses_official_archive_index` (`:180-195`) **or** grain `official_archive_index_day`. Missing `index_text` yields an **empty** required set, not a calendar walk (`:212-214`; `test_plan_required_segments_fail_closed_without_index_text`). Tiny fixture lists `2002-08-02/05/06` and excludes weekend `2002-08-03`. Empty archive-index receipts stay PARTIAL (`_empty_observed_forbids_complete`, `:347-349` now also matches grain `official_archive_index_day`). PARSE_ZERO `2002-08-02` / `2002-08-05` stay `stay_PARTIAL`; `parse_zero_invent_complete=FORBIDDEN`. 23-col parse is still not Coverage COMPLETE.

**FIXED (must stay) — refresh does not replay calendar inventory for OTC.** Inventory branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:907-925`). Else `plan_required_segments(..., index_text=index_text)` (`:927-951`). `persist_refreshed_coverage` DELETE-then-INSERT (`coverage_ledger_io.py:239-250`) replaces `coverage_segments` with the planned ids only. `evaluate_required_segments` on an empty required list is PARTIAL (`:779-791`; sticky recompute `:1015-1023`: `segment_statuses and all(...)` is false when empty). Tests still pin:

- `test_refresh_does_not_rerequire_weekend_absent_from_official_index` — calendar inventory including COMPLETE weekend `2002-08-03` is **dropped** after refresh with fixture HTML; remaining ids are listed days only; PARSE_ZERO rows stay PARTIAL; dataset status `!= COMPLETE`.
- `test_refresh_without_index_text_is_fail_closed_empty_not_calendar` — `index_text` None / `""` / `"   "` → `required_segments == 0`, weekend id absent, status `!= COMPLETE`. Empty is not 8784 and is not weekend COMPLETE.

**Grain (`26a6ca5e`) — not a reopen.** `collection_coverage.json` OTC `segment_granularity` is now `official_archive_index_day` (`:172`). Loader admits the token (`coverage.py` `SEGMENT_GRANULARITIES`). Planner treats that grain as `official_index_days`, not the non-index `official_archive_day` calendar walk (`:308-313`). Because grain is no longer `official_archive_day`, OTC cannot take the inventory-replay branch even if `_uses_official_archive_index` were false. Tests pin `policy.segment_granularity == "official_archive_index_day"` and planned `expected_scope["segment_granularity"]` the same. V2 floor `history_target_start=2002-08-02` is not rewritten.

**Archive HTML (`ddc40ae9`) — not a reopen; not weekend COMPLETE.** `run_otc_reference_backfill` collects fetched year-index HTML (`archive.py:331-344`) and passes `index_text="\n".join(index_texts) if index_texts else None` into `refresh_coverage_ledger` (`:528-535`). Missing year HTML stays **None** (fail-closed empty), not a calendar walk. `test_otc_archive_refresh_reuses_fetched_index_html_not_weekends` pins listed `2002-08-02/05/06`, weekend `2002-08-03` absent from required set **and** from parsed `index_text`, missing-link day `!= COMPLETE`, dataset `!= COMPLETE`.

**CLI callers that can pass local HTML — omitted still empty.** `--index-text` / `--otc-index-html` / `QP_INDEX_TEXT` read a **local** file. Missing path, missing file, or blank text is `None`. Tests: `test_refresh_coverage_ledger_cli.py` (`omitted_index_text_is_none_not_calendar_replay`); `test_write_collection_receipts.py` (`test_no_index_path_empty_otc_required_set`, missing path, blank file); `test_ops_projection_publish.py` (`test_publish_refresh_index_text_none_when_html_path_omitted`). None of these mint weekend COMPLETE.

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `67fcbd7c` |
|--------|----------------------------|
| `packages/data_plane/ingestion/jsda/archive.py:528-535` | fetched year-index HTML; empty fetch → `None` |
| `scripts/refresh_coverage_ledger.py:147-160` | `--index-text PATH` or omitted `None` |
| `scripts/write_collection_receipts.py:105-138,271-275` | `--index-text` / `QP_INDEX_TEXT` or omitted `None` |
| `scripts/publish_ops_projection.py:242-247` | `--otc-index-html` or omitted/`OSError`/`blank` → `None` |
| `scripts/jsda_otc_seal_official.py:478-483` | **omitted** (fail-closed empty) |
| `scripts/issue_receipts_parallel.py:598` | **omitted** (fail-closed empty) |
| `scripts/issue_signed_receipts_for_segments.py:288` | **omitted** (fail-closed empty) |
| `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-111` | **omitted** (jquants READY path; OTC empty if included) |

A live refresh that omits `index_text` / has no HTML would DELETE the STALE 8784 calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still 8784 under STALE V2. Canonical inventory / `endpoint_status` still advertise `coverage_segment_granularity=official_archive_day`; adapter spec (`adapters.py:39`) and seal helper strings still say `official_archive_day`. Those leftovers are not the refresh branch selector for OTC (`_uses_official_archive_index` is true **and** grain is `official_archive_index_day`).

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests is not a live official-index republish.

structural fix (still in tree; tightened): refresh required set = official index days when `index_text` is supplied. Grain JSON matches capability grain. Archive reuse of fetched HTML is listed publication days, not weekends. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`. Do not treat this SHA as OTC Dataset COMPLETE. Do not treat omitted-`index_text` empty as FRESH.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/coverage_ledger.py:198-285`; `packages/data_plane/ops/backfill_planner.py:404-517`

No `40d1aa90..67fcbd7c` rewrite of master / AM / earnings planner clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`

No PIT file changes `40d1aa90..67fcbd7c`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1399`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:330-349,386-389`; `packages/product/research/research_data_profile.py:183-201,385-409`

Grain `official_archive_index_day` now also forbids empty observed COMPLETE (`:347-348`) in addition to `"official_archive_index" in mode`. That tightens, it does not mint COMPLETE. Tip-snapshot empty PARTIAL, string-COMPLETE rejection, raw `ACQUIRED`, and missing-V3 fail-closed are untouched. Empty official-archive-index receipts stay PARTIAL. `test_event_zero_successful_exhausted_raw_receipt_is_complete` still pins COMPLETE for genuine `event_driven` fins windows — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18278` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE. Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

No `40d1aa90..67fcbd7c` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. This review does not publish READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-refresh / archive-HTML wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- Grain JSON `official_archive_index_day` republished the live ledger. Canonical inventory / MCP `endpoint_status` still say `official_archive_day` under STALE.
- Archive pass HTML rebuilt production D1. Isolation did not run live JSDA fetch.
- Callers omitting `index_text` without HTML rebuilt the live ledger. They are fail-closed empty, not weekend COMPLETE, and not FRESH.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `67fcbd7c`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18278` still counts historical `completeness=COMPLETE` strings.
- `refresh_coverage_ledger` OTC index path and archive HTML pass were confirmed from source + unit tests at HEAD; they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch).
- Production omit callers (`jsda_otc_seal_official`, `issue_receipts_parallel`, `issue_signed_receipts_for_segments`) were not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
