# Independent review A — PIT, official domain, false-COMPLETE

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `3ab87d0` (`3ab87d0ef0f65199d25b9dadccee3b796a384bed`)  
**Branch at audit:** `grok/phase63-ci-source-closure` (isolation: `grok/p632-ind-A-pit-complete`)  
**Scope:** PIT bypass; official availability vs required domain (master / AM / earnings); JSDA calendar-day phantom segments; forged receipt; false COMPLETE / raw-only COMPLETE; READY profile dependency omission.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

Live residual (unchanged by this review; last-known-good under STALE projection, not current Coverage): **22 COMPLETE held · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. Reconstitution apply remains **false**.

V3 JSON + typed loader at this SHA are **artifacts**. They are not a wire of Coverage V2, PIT, the planner, or READY(P). Tests in this tree pin `collection_coverage_json=unchanged_until_wire`.

---

## Summary

| ID | Topic | Sev | Status |
|----|-------|-----|--------|
| IND-A-DOMAIN | Official availability vs V2 required domain (master / AM / earnings) | P0 | OPEN |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN (evaluate raw-only ban FIXED; event-zero + raw label OPEN) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN |

---

## IND-A-DOMAIN

severity: **P0**  
status: **OPEN**  
affected: `specs/source_capability/{equities_master,equities_bars_daily_am,equities_earnings_calendar}.json`; `specs/coverage_v3/*_migration.json`; `packages/data_plane/data_contracts/source_capability.py`; `packages/data_plane/data_contracts/coverage.py`; `packages/data_plane/data_contracts/collection_coverage.json`; `packages/data_plane/storage/coverage_ledger.py` `plan_required_segments`; `packages/data_plane/ops/backfill_planner.py`; `packages/data_plane/ops/range_batch_scheduler.py`; `packages/edge/cf_platform/ingest_premium/coverage.py`; `packages/data_plane/data_contracts/canonical_datasets.json`; `packages/data_plane/data_contracts/jquants_premium_core.json`; `packages/data_plane/data_contracts/permanent_defer.py`

observed fact:

SourceCapabilityContract v3 loads three datasets at HEAD (`all_source_capability_contracts()` n=3). Official domains in those documents:

| Dataset | V3 official domain | V3 grain / mode | V2 `history_target_start` | V2 grain | Live required (A10 / gap audit) |
|---------|--------------------|-----------------|---------------------------|----------|----------------------------------|
| `equities_master` | 2008-05-07 | `calendar_month` / `bounded_history` | **2006-08-13** | `calendar_month` | 241 required · 220 COMPLETE · 21 PARTIAL |
| `equities_bars_daily_am` | tip `recent_snapshot` | `same_trading_day_am_snapshot` | **2024-01-04** | `calendar_month` | 32 required · 1 COMPLETE · 31 PARTIAL |
| `equities_earnings_calendar` | tip `next_business_day_snapshot` | `collection_cutoff_snapshot` | **2010-01-04** | `calendar_month` | 200 required · 1 COMPLETE · 199 PARTIAL |

`required_domain_subset_official` exists and, for the two tip modes, sets `admit_historical_required_segments=False`. **No production caller clips the planner to that subset.** The function is used from tests and re-exported; `plan_required_segments` / `backfill_planner` / `refresh_coverage_ledger` do not import it.

`CollectionCoverageContract.from_dict` still ignores vendor annotation keys (`vendor_data_provision_start`, `vendor_history_policy`). V2 floors stay:

- master 2006-08-13 (subscription entitlement, not listed-info provision)
- AM 2024-01-04 monthly history against a vendor “recent data only” endpoint
- earnings 2010-01-04 monthly history against a next-business-day `pagination_key` snapshot

Migration artifacts themselves record `behavior_change.collection_coverage_json = "unchanged_until_wire"` and `dataset_complete_claim: false`. Tests pin that (`test_v2_coverage_floor_not_rewritten_here`, `test_v2_planner_still_expands_200_months_v3_does_not_use_that_set`).

Parallel SoT still on the V2 floor:

- `canonical_datasets.json` `equities_master.historical_start` = `2006-08-13`
- `ingest_premium/coverage.py` `EXPECTED_START` master `2006-08-13`, AM `2024-01-04`, earnings `2010-01-04`
- `range_batch_scheduler.TRACK_A_FOCUS_RANGES["equities_master"]` = `("2006-08-13", "2099-12-31")`
- `jquants_premium_core.json`: AM `params=["code","date"]` (V3/vendor: `code` + `pagination_key` only); earnings `date_mode=range` and `params=["from","to","date"]` (V3/vendor: `pagination_key` only)
- `MASTER_JQ_SCOPE["bands"]["MISDATE"]["coverage"]` remains `REQUIRED_PARTIAL` “until wire”

HEAD `3ab87d0` only opens nested SourceCapability evidence maps. It does not rewrite V2 required inventory.

root cause: Coverage required set is still collection-coverage/v2 `history_target_start` × `segment_granularity`. Official-availability JSON is a parallel document.

why it matters: Treating V3 as live would drop 21 + 31 + 199 required segments and mint Dataset COMPLETE 23. Leaving V2 unwired keeps false-PARTIAL inventory that planners/backfill still try to fill.

structural fix: One wire that makes `plan_required_segments` subset `required_domain_subset_official`. Until then: do not copy `2008-05-07` into V2 `history_target_start`; do not abolish 32/200 months by floor bump; do not seal empty COMPLETE for excluded months.

residual: V3 `remaining_genuine_gaps` for master still says post-2008-05 PARTIAL stays PARTIAL. That is correct and is not a COMPLETE claim.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **OPEN**  
affected: `storage/coverage_ledger.py` `plan_required_segments` (`official_archive_day`); `data_contracts/collection_coverage.json` `jsda_otc_bond_reference_prices`; `ingestion/jsda/archive.py`; `scripts/write_collection_receipts.py`; no `specs/source_capability` row for JSDA

observed fact:

OTC coverage contract: `coverage_mode=official_archive_index_reconciled`, `segment_granularity=official_archive_day`, `history_target_start=2002-08-02`.

`plan_required_segments` for `official_archive_day` walks **every calendar day** from start through `target_end`. The in-function comment states this is why live PARTIAL (~2898) >> PARSE_ZERO (2).

`required_domain_subset_official` would set `publication_days_only=True` only when `history_mode=="official_archive_index"`. There is **no** JSDA SourceCapabilityContract (`source_capability_contract_for("jsda_otc_bond_reference_prices")` → KeyError). The helper cannot clip OTC even if a later lane called it.

Governed ingest (`ingestion/jsda/archive.py`) discovers publication files from the official year index (`discover_otc_reference_segments`) and records those segment ids. That path is not the calendar walk. Live ledger required **8784** = 5886 COMPLETE + 2898 PARTIAL still matches **inclusive calendar days** 2002-08-02 … 2026-08-19, not the index. `refresh_coverage_ledger` for `official_archive_day` **replays existing inventory**, so phantom weekend/holiday ids persist once recorded.

`write_collection_receipts.py` still lists/writes via `plan_required_segments` (calendar expansion).

Official remaining failed seal is **2 PARSE_ZERO** (`2002-08-02`, `2002-08-05`; 23-col vs 29-col parser). 2898 ≠ 2. Weekend/holiday calendar ids are inventory overhang, not missing source files.

root cause: required inventory grain = calendar day; official product grain = index publication days.

why it matters: Completing 2510 weekend ids (or raising the floor to 2002-08-06) invents COMPLETE. Leaving phantoms in the required set keeps Dataset PARTIAL forever without a source gap.

structural fix: required set = official index days (plus the two PARSE_ZERO publication files). Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

residual: 23-col parser for the two 2002 files is a separate P1 parser gap; empty-raw / PARSE_ZERO COMPLETE remains banned.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **OPEN**  
affected: `packages/data_plane/pit/api.py` `get_equity_master`; `packages/data_plane/pit/query.py`; `packages/data_plane/data_contracts/identity.py` `available_at_for`; `packages/product/research/eval_loaders_sidecars.py` `load_repo_rows_from_sqlite`; `packages/research_runtime/core/engine.py` `run_backtest`; `packages/research_runtime/features/runtime.py` `FeatureContext.get_equity_master`; `packages/research_runtime/core/universe.py`

observed fact:

1. **Official PIT history start is JSON-only.** V3 master `collection_window.pit_history_start` / `research_profile_eligibility.pit_history_start` = `2008-05-07`. `get_equity_master` applies only `available_at IS NOT NULL AND available_at <= as_of`. It does not clamp query dates, snapshot_date, or as_of to the official provision start. Test helper `apply_official_query_clamp` lives in `tests/test_equities_master_official_domain.py` and is **not** production PIT.

2. **`available_at` policy is ingest-time, not the V3 publication calendar.** `jquants_premium_core.json` master: `available_at_policy=ingest_time_conservative`. `available_at_for` falls through to `ingested_at` for that policy. V3 nested calendar says next-business-day after 17:30 JST. Nested maps are open at `3ab87d0`; the identity function does not read SourceCapabilityContract. Historical `as_of` either sees nothing (ingest in 2026) or, if an override writes `available_at` from `Date`, sees listed-info at observation midnight — both miss official availability.

3. **Eval sqlite is an explicit non-PIT path.** `load_repo_rows_from_sqlite` docstring: “Load jsda_repo_rates rows from local SQLite (not PIT).” Filter is `as_of_date` range only; no `available_at <= as_of`. Callers: `eval_loaders`, `cf_mass_eval_thicken`, `offline/factory_eval_data`. `pit/query.py` even documents this loader as the historical JSDA repo path while managed PIT fails closed until a READY snapshot.

4. **Fixed universe skips PIT master membership.** `run_backtest(..., universe=...)` uses `fixed_universe` and does not call `load_master` / `build_universe` for membership. Survivorship filter is optional.

5. **Feature history still DEFERs the entire master.** `FeatureContext.get_equity_master` → `require_feature_dataset("equities_master")` → `PermanentDeferHistoryError`. V3 says `historical_research_eligible=true` from 2008-05-07. The honest island is not a PIT read path for features; it is a total block. That is not a look-ahead bypass, but it is a domain bypass: research cannot use the official island through the feature gate, while eval sqlite / fixed universe can skip PIT entirely.

`pit.query.run_query` still always AND-gates `available_at <= as_of` on `pit.get_*`. That gate is **FIXED** and must stay. The OPEN issue is the other read paths and the unwired official domain.

root cause: PIT sole-read is a convention plus `pit.get_*`; eval/backtest/feature-defer have parallel paths. Official domain is not a PIT constraint.

why it matters: Look-ahead or survivorship through sqlite / fixed universe is not caught by `test_pit_lookahead.py`. Claiming PIT history from 2008-05-07 is false until `get_equity_master` and loaders enforce it.

structural fix: Eval loaders that feed research must take `as_of` and apply the same SQL gate (or call `pit.get_*`). Clip master PIT to official start. Do not pass a caller-supplied universe without a PIT membership proof. Align `available_at_for` with SourceCapabilityContract for master/AM/earnings.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED**  
affected: `storage/coverage_receipts.py` `build_collection_receipt` / `build_synthetic_complete_receipt`; `storage/coverage_ledger.py` `receipt_eligibility` / `is_complete_eligible_receipt`; `storage/__init__.py`; `scripts/write_collection_receipts.py`; `tests/test_receipt_eligibility.py`

observed fact (HEAD):

- Bare `eligibility=TRUSTED_COLLECTION` without Ed25519 fields is rewritten to `RECOVERED_RAW_ONLY` in `build_collection_receipt`.
- `test_string_issuer_cannot_complete` pins issuer_id `"forged"` → stripped → `evaluate_segment` PARTIAL.
- `is_synthetic_receipt` is true when `digests.synthetic`; `is_complete_eligible_receipt` returns False for synthetic **before** signature verify.
- `receipt_eligibility` maps synthetic / recovered-raw-only origins to `RECOVERED_RAW_ONLY`.
- COMPLETE requires `eligibility==TRUSTED_COLLECTION` **and** `verify_receipt_signature`.
- `build_synthetic_complete_receipt` is **not** re-exported from `storage`. CLI `--synthetic` requires `--allow-fixture-synthetic` and writes the sentinel.
- JSDA/JQ SUCCESS emit requires `SignedReceiptAuthority` and rejects empty-raw SUCCESS.

root cause (historical): TRUSTED_COLLECTION was a string; synthetic receipts were COMPLETE-shaped.

why it still matters: The builder still emits `eligibility=TRUSTED_COLLECTION` plus a zero digest for fixtures. Production evaluate is fail-closed; do not re-export or un-gate the writer.

structural fix already in tree: keep `is_complete_eligible_receipt` cryptographic; keep synthetic off the public storage surface.

residual (not a reopen of P0): fixture object shape can still confuse a reader who skips `evaluate_segment`. That is documentation / API hygiene, not a live COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **OPEN** (raw-only evaluate ban **FIXED**; event-zero + raw-plane labels **OPEN**)  
affected: `storage/coverage_ledger.py` `evaluate_segment`; `tests/test_phase61_coverage_v2.py`; `specs/coverage_v3/equities_earnings_calendar_migration.json`; `platform/workers/ingestion-premium/src/index.ts` raw `completeness`; `platform/workers/quant-ops-mcp/src/domain.js` `classifyRawAcquisition`; `packages/product/research/research_data_profile.py` `_complete_under_official`

observed fact:

**FIXED (must stay):** `evaluate_segment` PARTIAL on missing receipt, unsigned / RECOVERED_RAW_ONLY, non-exhausted pagination, raw/structured mismatch, non-event empty observed_items. `test_recovered_raw_only_cannot_complete` and JSDA/JQ empty-raw SUCCESS tests pin this. MCP `classifyRawAcquisition` comments “Raw acquisition ≠ dataset Coverage COMPLETE” and maps raw `completeness=COMPLETE` to acquisition states, not ledger COMPLETE.

**OPEN — event-zero COMPLETE on event_driven months.** `evaluate_segment` returns COMPLETE when `observed_items==0` if the dataset is `expected_frequency=event_driven` and a trusted SUCCESS receipt exists (`test_event_zero_successful_exhausted_raw_receipt_is_complete`). `equities_earnings_calendar` is `event_reconciled` / `event_driven` with V2 **200 calendar months**. V3 says `empty_complete_past_months=FORBIDDEN` and does not wire the planner. A signed empty (or snapshot) receipt on a false-PARTIAL month would COMPLETE that month under V2 evaluate. That is the monthly-shell path A10 / gap audit forbade.

**OPEN — raw-plane COMPLETE string.** Worker `ingestion-premium` writes `completeness: complete ? "COMPLETE" : "FAILED"` on raw manifests. Gap audit already recorded Sunday AM 0-row / 88-byte ingest as raw completeness COMPLETE. That is not Coverage COMPLETE; the string is still COMPLETE.

**OPEN — READY predicate accepts a bare `"COMPLETE"` string.** `_complete_under_official`: if evidence is a `str`, `return evidence == "COMPLETE"` — **no** `official_mode(d)` check. Mapping evidence requires `coverage_mode` only when present (`None` is accepted).

root cause: five evidence planes (raw / parse / structured / receipt / evaluate) still share the token COMPLETE. V3 empty-complete ban is JSON.

why it matters: Earnings 199 months, AM Sunday envelope, OTC PARSE_ZERO, and profile_ready can all be labeled COMPLETE without Coverage V2 official-domain completeness.

structural fix: Keep evaluate raw-only ban. Stop COMPLETE on event-zero for tip-snapshot datasets until grain is collection_cutoff. Do not let profile_ready treat a string as COMPLETE. Raw manifest completeness must stay a distinct enum in any surface that research reads.

Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **OPEN**  
affected: `specs/research_profiles/core_v1.json`; `packages/product/research/research_data_profile.py`; `packages/research_runtime/core/universe.py`; `packages/research_runtime/core/engine.py`; `packages/product/research/hypothesis_classes.py` `CLASS_FUNDAMENTALS_PRICE`

observed fact:

Docstring: `READY(P) = AND Complete(d, official_mode(d)) for d in Deps(P)` and `Deps(P) = transitive StrategySpec + FeatureRef + Universe + Evaluation protocol + Risk inputs`.

`core_v1.json` `required_datasets` =

`equities_bars_daily`, `fins_details`, `fins_dividend`, `fins_earnings_date`, `fins_summary`, `markets_calendar`.

**`equities_master` is absent.** `permitted_universe` is `tse_prime_with_fins`, `tse_dividend_payers`. `resolve_deps` walks FeatureRef / StrategySpec dataset lists only. It does **not** expand `permitted_universe` (or core-engine `load_master`) into `equities_master`. Empty `feature_dependencies` / `strategy_dependencies` therefore construct a profile whose READY(P) ignores master.

Core engine universe is defined as PIT master only (`core/universe.py`: “built only from the PIT equity master”). Default `run_backtest` calls `load_master(decision_as_of)` every day. A digest-bound READY(P) that omits master can be true while the engine cannot build an anti-survivorship universe, or while a caller injects `fixed_universe` (IND-A-PIT-BYPASS).

Tip-only AM / earnings calendar **are** excluded from core and fail-closed if a FeatureRef lists them without adding them to `required_datasets`. That omission-check is **FIXED** for *listed* datasets. It does not cover implicit universe/master.

`CLASS_FUNDAMENTALS_PRICE.datasets_required` is fins_* + bars + calendar — same master hole — while `constraints` include `pit_available_at_for_fundamentals`.

`official_mode(d)` reads V2 `coverage_contract_for(d).coverage_mode`, not SourceCapabilityContract. Core `contract_versions.coverage_policy` is still `collection-coverage/v2`. Master V3 `research_profile_eligibility` has empty `include_in` (historical_research / pit_history_start live only as nested open keys). Profile construction cannot bind the official island.

`profile_ready` is a predicate. This review does not publish a READY generation. Predicate true with omitted master is still an omission.

root cause: Deps(P) implementation = declared `required_datasets` plus listed FeatureRef/StrategySpec ids. Universe and PIT master are documentation-only.

why it matters: READY(P) can AND-complete six datasets and still trade a non-PIT universe. Adding master without official-domain wire would also AND against V2 PARTIAL (21 MISDATE months) and keep READY false — which is honest until IND-A-DOMAIN is wired. Omitting master to avoid that PARTIAL is the forbidden shortcut.

structural fix: Core Deps must include `equities_master` (or a named universe dataset that canonicalizes to it) when `permitted_universe` is non-empty. Fail closed if universe names have no dataset mapping. Do not mark profile_ready true on string COMPLETE (IND-A-FALSE-COMPLETE). Do not publish READY.

---

## What this review does not claim

- V3 artifacts are wrong as **metadata**. Official URLs (listed-info 2008-05-07; AM recent-only; earnings next-business-day) match A10 / `docs/phase63_coverage_gap_audit.md`.
- Ed25519 COMPLETE eligibility is FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- Dataset COMPLETE remains **22**. PARTIAL remains **4**. This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 and projection generation was not re-fetched in this isolation worktree. Counts above are from in-tree residual / A10 / Wave-0 (`docs/reviews/P632_wave0_live.md`) at this SHA’s narrative, not a new ops projection.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate + tests at HEAD.
