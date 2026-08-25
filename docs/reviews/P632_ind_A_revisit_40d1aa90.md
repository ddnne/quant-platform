# Independent review A revisit — at `40d1aa90`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `40d1aa90` (`40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4`)  
**Branch at audit:** `grok/p632-ind-A-revisit-40d1aa90` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freezes:** `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md))  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A after `40d1aa90` (`coverage: OTC refresh required set from official index not inventory`). Named hole at `f224e7e` was IND-A-JSDA-PHANTOM refresh inventory replay. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

Landing verified in tree (not trusted from the title): `40d1aa90` touches only `packages/data_plane/storage/coverage_ledger.py` and `tests/test_jsda_otc_official_domain.py`.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 182395 (~50.7 h) |
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
| `collection_sla_status(jsda_otc)` | `current_state` **PROJECTION_STALE** (`ops_projection_stale`) |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s refresh wire):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. Reconstitution apply remains **false**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` |
|----|-------|-----|--------------|--------------|--------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | **FIXED** (refresh required set = official index, not inventory) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | **FIXED** (not reopened) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | **FIXED** (not reopened) |

Independent P0 remaining: **0**. Named Independent A P0s are closed in tree. Callers omitting `index_text` are residuals (fail-closed empty), not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (planner calendar-walk remains FIXED; `refresh_coverage_ledger` inventory replay **closed** at `40d1aa90`)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-292,788-801,900-945,1010-1017,1069-1077`; `packages/data_plane/storage/coverage_ledger_io.py:212-243`; `packages/data_plane/ingestion/jsda/official_index.py:42-52`; `packages/data_plane/data_contracts/collection_coverage.json:165-172`; `tests/test_jsda_otc_official_domain.py:300-369`; `scripts/write_collection_receipts.py:99-101`; `scripts/refresh_coverage_ledger.py:124-130`

observed fact (HEAD vs `f224e7e`):

**FIXED (must stay) — planner.** `plan_required_segments` still takes official-archive-index datasets through `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-292`) after `_uses_official_archive_index` (`:180-195`; coverage_mode `official_archive_index_reconciled`, capability `history_mode=official_archive_index`, `publication_days_only`). Missing `index_text` yields an **empty** required set, not a calendar walk (`:212-214`; `test_plan_required_segments_fail_closed_without_index_text`). Tiny fixture lists `2002-08-02/05/06` and excludes weekend `2002-08-03` (`test_plan_required_segments_uses_official_index_not_calendar`). Empty archive-index receipts stay PARTIAL (`_empty_observed_forbids_complete`, `:343`). PARSE_ZERO `2002-08-02` / `2002-08-05` stay `stay_PARTIAL`; `parse_zero_invent_complete=FORBIDDEN`. 23-col parse is still not Coverage COMPLETE.

**FIXED — production refresh no longer replays calendar inventory for OTC.** At `f224e7e`, `refresh_coverage_ledger` for grain `official_archive_day` rebuilt required from existing `coverage_segments` (`:894-909` then). `40d1aa90` adds `index_text` (`:795`) and gates that inventory branch:

```900:945:packages/data_plane/storage/coverage_ledger.py
        domain = _official_domain_for(_source_capability_for(dataset))
        if (
            policy.segment_granularity in {
                "official_archive_day", "source_time_series_file"
            }
            and not _uses_official_archive_index(policy, domain)
        ):
            # Keep inventory through target_end, plus already-COMPLETE days past UTC (JST can lead).
            required_segments = tuple(sorted(
                (
                    _required_from_inventory(row)
                    ...
                ),
                ...
            ))
        else:
            base_segments = plan_required_segments(
                policy, target_end, source=source, index_text=index_text,
            )
            ...
            required_segments = plan_required_segments(
                ...
                index_text=index_text,
            )
```

OTC `_uses_official_archive_index` is true, so refresh calls `plan_required_segments` / official index days. Calendar inventory is **not** the required set. `persist_refreshed_coverage` DELETE-then-INSERT (`coverage_ledger_io.py:239-250`) replaces `coverage_segments` with the planned ids only.

Tests pin the closed hole:

- `test_refresh_does_not_rerequire_weekend_absent_from_official_index` — calendar inventory including COMPLETE weekend `2002-08-03` is **dropped** after refresh with fixture HTML; remaining ids are listed days only; PARSE_ZERO rows stay PARTIAL; dataset status `!= COMPLETE`.
- `test_refresh_without_index_text_is_fail_closed_empty_not_calendar` — `index_text` None / `""` / `"   "` → `required_segments == 0`, weekend id absent, status `!= COMPLETE`. Empty is not 8784 and is not weekend COMPLETE.

`evaluate_required_segments` on an empty required list is PARTIAL, not COMPLETE (`coverage_ledger.py:779-784`, sticky recompute `:1010-1017`: `segment_statuses and all(...)` is false when empty).

**Residual (do not reopen the named P0):** callers omitting `index_text` are fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` |
|--------|----------------|
| `scripts/refresh_coverage_ledger.py:124-130` | omitted |
| `scripts/jsda_otc_seal_official.py:478-483` | omitted |
| `scripts/publish_ops_projection.py:220` | omitted |
| `scripts/issue_receipts_parallel.py:598` | omitted |
| `scripts/issue_signed_receipts_for_segments.py:288` | omitted |
| `packages/data_plane/ingestion/jsda/archive.py:524-529` | omitted |
| `scripts/write_collection_receipts.py:99-101` | `plan_required_segments` without `index_text` → empty OTC plan |

A live refresh that omits `index_text` would DELETE the STALE 8784 calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Grain in `collection_coverage.json` is still `official_archive_day` (`:172`); V3 capability grain remains `official_archive_index_day`. The grain string is no longer the refresh branch selector for OTC because `_uses_official_archive_index` is true.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either.

structural fix (landed in tree): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`. Do not treat this SHA as OTC Dataset COMPLETE. Do not treat omitted-`index_text` empty as FRESH.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/coverage_ledger.py:198-285`; `packages/data_plane/ops/backfill_planner.py:404-517`

`40d1aa90` does not rewrite master / AM / earnings planner clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`

`40d1aa90` does not touch PIT. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

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
file:line: `packages/data_plane/storage/coverage_ledger.py:326-343,386-389`; `packages/product/research/research_data_profile.py:183-201,385-409`

`40d1aa90` does not reopen tip-snapshot empty PARTIAL, string-COMPLETE rejection, raw `ACQUIRED`, or missing-V3 fail-closed. Empty official-archive-index receipts stay PARTIAL. `test_event_zero_successful_exhausted_raw_receipt_is_complete` still pins COMPLETE for genuine `event_driven` fins windows — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18255` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE. Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

`40d1aa90` does not omit master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. This review does not publish READY. Residuals from `f224e7e` (non-core `resolve_deps` universe names; `CLASS_FUNDAMENTALS_PRICE` without master; `official_mode` reads V2 coverage_mode) do not reopen the core-omission P0.

---

## What this review does not claim

- Planner / PIT / profile / OTC-refresh wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- Callers omitting `index_text` rebuilt the live ledger. They are fail-closed empty, not weekend COMPLETE, and not FRESH.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `40d1aa90`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18255` still counts historical `completeness=COMPLETE` strings.
- `refresh_coverage_ledger` OTC index path was confirmed from source + unit tests at HEAD; it was not executed against a live DB in this isolation worktree (would need official index HTML).
- Production callers listed above were not run. Omit-`index_text` empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
