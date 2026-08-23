# Independent review A revisit — after V3 planner wire

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `d93335b` (`d93335b1f97badb952971e7f4842a62137a59faa`)  
**Branch at audit:** `grok/p632-ind-A-revisit` (from `grok/phase63-ci-source-closure`)  
**Prior freeze:** `3ab87d0` (`docs/reviews/P632_ind_A_pit_complete.md`)  
**Scope:** re-diff IND-A after `5796fb0` (V3 planner), `1c92bad` (OTC spec), `cc4e340` (23-col adapter). Core profile may still omit master.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

---

## Live MCP (this isolation turn — not invented FRESH)

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 178705 (~49.6 h) |
| `stages.refresh_success` | **false** |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner):

| Dataset | Live `history_target_start` | `evaluated_at` |
|---------|-----------------------------|----------------|
| `equities_master` | **2006-08-13** | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. Reconstitution apply remains **false**. This file is not a ledger refresh.

---

## Scoreboard vs `3ab87d0`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` |
|----|-------|-----|--------------|--------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | **FIXED** (`plan_required_segments`; residuals below) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | **OPEN** (still calendar walk) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | **OPEN** |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | **OPEN** (raw-only ban still FIXED; event-zero + raw label + string COMPLETE still OPEN) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | **OPEN** (`core_v1` still omits master) |

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (`plan_required_segments` uses V3 for master / AM / earnings)  
file:line: `packages/data_plane/storage/coverage_ledger.py:188-257`; `packages/data_plane/data_contracts/collection_coverage.json:13-74`

observed fact (HEAD vs `3ab87d0`):

`plan_required_segments` now loads `SourceCapabilityContract` and clips through `required_domain_subset_official`:

```188:257:packages/data_plane/storage/coverage_ledger.py
    capability = _source_capability_for(policy.dataset_id)
    domain = _official_domain_for(capability)
    start = date.fromisoformat(policy.history_target_start)
    if domain is not None:
        official = date.fromisoformat(domain.earliest_official_availability)
        if start < official:
            start = official
    ...
    tip_snapshot = _is_tip_snapshot_policy(policy, domain)
    ...
    if tip_snapshot:
        # Current collection window only. Do not expand monthly history.
        _append(end.isoformat(), end, end)
        return tuple(segments)
```

`collection_coverage.json` is rewritten for the three datasets (`policy_version=collection-coverage/v3`; document root remains `collection-coverage/v2`):

| Dataset | Contract start | Grain / history_mode | Planned required set (tests) |
|---------|----------------|----------------------|------------------------------|
| `equities_master` | **2008-05-07** | `calendar_month` / `bounded_history` | months from 2008-05; 2006-08..2008-04 **not** in ids (`test_v3_planner_required_start_is_official_not_entitlement_floor`) |
| `equities_bars_daily_am` | 2024-01-04 | `same_trading_day_am_snapshot` / `recent_snapshot` | **1** cutoff snapshot, not 32 months (`test_planner_required_count_is_not_32_months`) |
| `equities_earnings_calendar` | 2010-01-04 | `collection_cutoff_snapshot` / `next_business_day_snapshot` | **1** cutoff snapshot, not 200 months (`test_planner_required_count_is_not_200_months`) |

Migration artifacts now say `behavior_change.collection_coverage_json = "wired_v3_planner"` (master / AM / earnings). `refresh_coverage_ledger` uses `plan_required_segments` for these grains (`coverage_ledger.py:855-877`), not the archive-day inventory replay.

This is the structural fix named at `3ab87d0`: production `plan_required_segments` subsets official domain. Do not treat the wire as Dataset COMPLETE 23. Official 2008-05-07 is domain correction, not a COMPLETE mint. AM / earnings remaining required count is a current snapshot, not empty-COMPLETE of 31 / 199 months.

residuals (do **not** reopen the planner P0; still not FRESH):

1. **Live MCP is STALE** and still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger.
2. **`BackfillPlanner` does not call `plan_required_segments`.** It month-chunks from `cov.history_target_start` (`ops/backfill_planner.py:422-469`). Master start is now 2008-05-07 via the rewritten coverage JSON. AM / earnings still fall through to `YYYY-MM` segment ids. Tip snapshot grain is not consumed there.
3. Parallel SoT still on the entitlement / V2 floor:
   - `canonical_datasets.json:19` `equities_master.historical_start` = `2006-08-13` (`contracts.coverage` still `collection_coverage/v2`)
   - `cf_platform/ingest_premium/coverage.py:23` `EXPECTED_START["equities_master"]` = `2006-08-13`; AM `2024-01-04`; earnings `2010-01-04`
   - `range_batch_scheduler.py:76` `TRACK_A_FOCUS_RANGES["equities_master"]` = `("2006-08-13", "2099-12-31")`
   - `jquants_premium_core.json` AM `params=["code","date"]` (`:55`); earnings `date_mode=range` and `params=["from","to","date"]` (`:140-150`)
   - `MASTER_JQ_SCOPE["bands"]["MISDATE"]["coverage"]` remains `REQUIRED_PARTIAL` with “until wire-later” (`permanent_defer.py:110-127`)
4. `source_capability.py:11-12` still claims “This module does not rewrite `plan_required_segments`.” That sentence is stale after `5796fb0`.
5. `CollectionCoverageContract.from_dict` still does not copy vendor annotation keys into `history_target_start` (`coverage.py:91-94`). Official start is set explicitly in JSON for the three wired datasets.

why it still matters: claiming Dataset COMPLETE 23 from this SHA would convert excluded MISDATE / tip months to COMPLETE. Live 22/4 is STALE last-known-good, not a remeasure of the wired planner.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **OPEN**  
file:line: `packages/data_plane/storage/coverage_ledger.py:269-278` (calendar walk); `:839-854` (inventory replay)

observed fact:

OTC now **has** a SourceCapabilityContract (`specs/source_capability/jsda_otc_bond_reference_prices.json`; `history_mode=official_archive_index`; `publication_days_only=true`; `collection_window.grain=official_archive_index_day`). `required_domain_subset_official` sets `publication_days_only=True` (`source_capability.py:449`). **`plan_required_segments` does not read that flag.** Grain stays V2 `official_archive_day`. The calendar walk is still in production:

```269:278:packages/data_plane/storage/coverage_ledger.py
    elif granularity == "official_archive_day":
        # Walks every calendar day. JSDA OTC coverage_mode is
        # official_archive_index_reconciled — required publication days come
        # from the official year index, not weekends/holidays. Calendar-day
        # inventory is why jsda_otc PARTIAL (~2898) >> PARSE_ZERO (2).
        # Do not COMPLETE empty non-index days from this expansion.
        cursor = start
        while cursor <= end:
            _append(cursor.isoformat(), cursor, cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
```

Tests **pin** the walk: `test_v2_planner_still_expands_calendar_days_v3_does_not_use_that_set` (`tests/test_jsda_otc_official_domain.py:171-188`) asserts `len(planned) == 8784` through `2026-08-19` and that weekend `2002-08-03` is in the required ids. Migration `behavior_change.collection_coverage_json` remains `"unchanged_until_wire"`. Coverage JSON for OTC is still `collection-coverage/v2` / `official_archive_day` / `2002-08-02`. V3 grain `official_archive_index_day` is **not** in `SEGMENT_GRANULARITIES`.

`refresh_coverage_ledger` for `official_archive_day` **replays existing inventory** (`coverage_ledger.py:839-854`) and does not call `plan_required_segments`. Phantom weekend/holiday ids persist once recorded. `write_collection_receipts.py:99-101` still lists via `plan_required_segments`.

23-col adapter (`cc4e340`, `ingestion/jsda/parse.py:192-219` / `_OTC_EARLY_LAYOUT_COLUMN_LIMIT = 23`) parses overlapping prefix fields. Tests (`test_otc_headerless_23col_maps_overlapping_positional_fields`) say this is **not** a live 2002-08-02 COMPLETE seal. Comment: “Parser rows are not Coverage COMPLETE.” PARSE_ZERO days stay genuine gaps in the OTC migration (`stay_PARTIAL`; `parse_zero_invent_complete=FORBIDDEN`).

Live STALE gap row still has `history_target_start=2002-08-02` and Wave-0 inventory **8784 = 5886 COMPLETE + 2898 PARTIAL**. 2898 ≠ 2.

root cause: required inventory grain = calendar day; official product grain = index publication days. Spec exists; planner is not wired.

why it matters: Completing 2510 weekend ids (or raising the floor to 2002-08-06) invents COMPLETE. Leaving phantoms in the required set keeps Dataset PARTIAL without a source gap. 23-col parse without a receipt/evaluate path is not Dataset COMPLETE.

structural fix (unchanged): required set = official index days (plus remaining PARSE_ZERO publication files until sealed). Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **OPEN**  
file:line: `packages/data_plane/pit/api.py:264-288`; `packages/data_plane/data_contracts/identity.py:242-271`; `packages/product/research/eval_loaders_sidecars.py:401-428`; `packages/research_runtime/core/engine.py:452-486`; `packages/research_runtime/features/runtime.py:86-95`

observed fact (unchanged vs `3ab87d0` except that planner domain is now wired — PIT still is not):

1. **Official PIT history start is still JSON-only.** V3 `pit_history_start=2008-05-07`. `get_equity_master` applies only `available_at IS NOT NULL AND available_at <= as_of` (`pit/query.py:175-190`). It does not clamp `as_of` / `snapshot_date` to official provision start. `apply_official_query_clamp` remains a **test helper** (`tests/test_equities_master_official_domain.py:187`).
2. **`available_at_for` is still ingest-time for master.** `jquants_premium_core.json:12` `available_at_policy=ingest_time_conservative`. `available_at_for` falls through to `ingested_at` (`identity.py:269-271`). It does not read SourceCapabilityContract.
3. **Eval sqlite is still an explicit non-PIT path.** `load_repo_rows_from_sqlite` docstring: “Load jsda_repo_rates rows from local SQLite (not PIT).” Filter is `as_of_date` range; no `available_at <= as_of`. Callers: `eval_loaders`, `cf_mass_eval_thicken`, `offline/factory_eval_data`, `offline/multiyear`.
4. **Fixed universe still skips PIT master membership.** `run_backtest(..., universe=...)` sets `fixed_universe` and uses it instead of `load_master` (`engine.py:452-486`).
5. **Feature history still DEFERs the entire master.** `FeatureContext.get_equity_master` → `require_feature_dataset("equities_master")` → `PermanentDeferHistoryError` (`runtime.py:86-95`). V3 says `historical_research_eligible=true` from 2008-05-07. That is not a look-ahead bypass; it is a domain bypass: research cannot use the official island through the feature gate, while eval sqlite / fixed universe can skip PIT.

`pit.query.run_query` still always AND-gates `available_at <= as_of` on `pit.get_*`. That gate remains **FIXED** and must stay. The OPEN issue is the other read paths and the unwired official domain on PIT.

why it matters: Look-ahead or survivorship through sqlite / fixed universe is not caught by `test_pit_lookahead.py`. Claiming PIT history from 2008-05-07 is false until `get_equity_master` and loaders enforce it.

structural fix (unchanged): Eval loaders that feed research must take `as_of` and apply the same SQL gate (or call `pit.get_*`). Clip master PIT to official start. Do not pass a caller-supplied universe without a PIT membership proof. Align `available_at_for` with SourceCapabilityContract for master/AM/earnings.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened; not re-audited beyond HEAD presence of `is_complete_eligible_receipt`)

No production change in this revisit window re-exports `build_synthetic_complete_receipt` or lets unsigned `TRUSTED_COLLECTION` COMPLETE. Keep cryptographic eligibility. Residual API hygiene (fixture object shape) is unchanged and is not a live COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **OPEN** (raw-only evaluate ban **FIXED**; event-zero + raw-plane labels + string COMPLETE **OPEN**)  
file:line: `packages/data_plane/storage/coverage_ledger.py:346-368`; `tests/test_phase61_coverage_v2.py:126-133`; `platform/workers/ingestion-premium/src/index.ts:514`; `packages/product/research/research_data_profile.py:354-371`

observed fact:

**FIXED (must stay):** `evaluate_segment` PARTIAL on missing receipt, unsigned / RECOVERED_RAW_ONLY, non-exhausted pagination, raw/structured mismatch, non-event empty `observed_items`. MCP `classifyRawAcquisition` (`domain.js:113-122`) maps raw `completeness=COMPLETE` to acquisition states; note at `:573` “raw acquisition COMPLETE is not dataset Coverage COMPLETE”.

**OPEN — event-zero COMPLETE.** `evaluate_segment` still returns COMPLETE when `observed_items==0` if `expected_frequency=event_driven` and a trusted SUCCESS receipt exists. `test_event_zero_successful_exhausted_raw_receipt_is_complete` still pins this (`test_phase61_coverage_v2.py:126-133`). Earnings calendar is still `expected_frequency=event_driven` (`collection_coverage.json:71`). IND-A-DOMAIN now drops the 200 monthly shells from **required** inventory, so the 199-month empty-COMPLETE path is planner-mitigated. Evaluate itself still COMPLETEs event-zero on the remaining snapshot (and on other event_driven datasets). V3 `empty_complete_past_months=FORBIDDEN` is still a migration JSON rule, not an evaluate rule.

**OPEN — raw-plane COMPLETE string.** Worker `ingestion-premium` still writes `completeness: complete ? "COMPLETE" : "FAILED"` (`index.ts:514`).

**OPEN — READY predicate accepts a bare `"COMPLETE"` string.** `_complete_under_official`: if evidence is a `str`, `return evidence == "COMPLETE"` — **no** `official_mode(d)` check (`research_data_profile.py:361-362`). Mapping evidence requires `coverage_mode` only when present (`None` is accepted).

why it matters: Earnings snapshot, AM Sunday envelope, OTC PARSE_ZERO, and `profile_ready` can still be labeled COMPLETE without Coverage official-domain completeness. Planner wire does not mint Dataset COMPLETE 23.

structural fix: Keep evaluate raw-only ban. Stop COMPLETE on event-zero for tip-snapshot datasets until grain is collection_cutoff **and** evaluate forbids empty COMPLETE. Do not let `profile_ready` treat a string as COMPLETE. Raw manifest completeness must stay a distinct enum in any surface that research reads.

Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **OPEN**  
file:line: `specs/research_profiles/core_v1.json:5-11`; `packages/product/research/research_data_profile.py:52-59`, `:119-157`; `packages/product/research/hypothesis_classes.py:248-254`

observed fact (core profile **still omits master**):

`core_v1.json` `required_datasets` =

`equities_bars_daily`, `fins_details`, `fins_dividend`, `fins_earnings_date`, `fins_summary`, `markets_calendar`.

**`equities_master` is absent.** `permitted_universe` is `tse_prime_with_fins`, `tse_dividend_payers`. `CORE_REQUIRED_DATASETS` (`research_data_profile.py:52-59`) matches that list. `resolve_deps` walks FeatureRef / StrategySpec dataset lists only. It requires `permitted_universe` non-empty but **does not** expand universe names (or core-engine `load_master`) into `equities_master`. Empty `feature_dependencies` / `strategy_dependencies` still construct a profile whose READY(P) ignores master.

Core engine universe is still defined as PIT master only (`core/universe.py:1-6`). Default `run_backtest` calls `load_master(decision_as_of)` every day unless a caller injects `fixed_universe` (IND-A-PIT-BYPASS). A digest-bound READY(P) that omits master can be true while the engine cannot build an anti-survivorship universe.

Tip-only AM / earnings calendar **are** excluded from core (`core_v1.json:32-35`; `_assert_core_exclusions`). That omission-check remains **FIXED** for *listed* datasets. It does not cover implicit universe/master.

`CLASS_FUNDAMENTALS_PRICE.datasets_required` is fins_* + bars + calendar — same master hole — while `constraints` include `pit_available_at_for_fundamentals`.

`official_mode(d)` reads `coverage_contract_for(d).coverage_mode`. Core `contract_versions.coverage_policy` is still `collection-coverage/v2` (`core_v1.json:16`). Master V3 `research_profile_eligibility.include_in` is still empty. Profile construction cannot bind the official island.

Live READY snapshot is **null**. This review does not publish READY. Predicate true with omitted master is still an omission.

root cause: Deps(P) implementation = declared `required_datasets` plus listed FeatureRef/StrategySpec ids. Universe and PIT master are documentation-only.

why it matters: READY(P) can AND-complete six datasets and still trade a non-PIT universe. Adding master without a FRESH official-domain ledger would AND against STALE V2 PARTIAL (21 MISDATE months) and keep READY false — honest until live inventory is rebuilt from the wired planner. Omitting master to avoid that PARTIAL is the forbidden shortcut.

structural fix (unchanged): Core Deps must include `equities_master` (or a named universe dataset that canonicalizes to it) when `permitted_universe` is non-empty. Fail closed if universe names have no dataset mapping. Do not mark `profile_ready` true on string COMPLETE (IND-A-FALSE-COMPLETE). Do not publish READY.

---

## What this review does not claim

- `5796fb0` is a live Coverage remeasure. Live MCP is **STALE**; READY is **null**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only; sealer still requires nz parse, raw==structured, digest match, and a trusted receipt.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree.
- `BackfillPlanner` AM/earnings monthly expansion was confirmed from source (`backfill_planner.py:422-469`); it was not executed against a live DB in this isolation worktree.
