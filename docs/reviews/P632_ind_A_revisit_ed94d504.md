# Independent review A revisit — at `ed94d504`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `ed94d504` (`ed94d5041969c3630b35c93927dcd1bb42f85c74`)  
**Branch at audit:** `grok/p632-ind-A-revisit-ed94d504` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freezes:** `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md))  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A after BackfillPlanner all JQ jobs from `plan_required_segments`; event-zero tip/index PARTIAL; IR encode keys schema lock; OTC sealer `index_text`. Prior at `67fcbd7c` said tree P0 = 0. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

Landing verified in tree (not trusted from titles):

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| missing V3 does not invent BackfillPlanner official domain | `b7ea539a` / `ed94d504` | IND-A-DOMAIN |
| event-zero COMPLETE does not apply to tip or archive-index | `6abfb085` | IND-A-FALSE-COMPLETE |
| OTC sealer passes local `index_text` | `2ec8f572` | IND-A-JSDA-PHANTOM (sealer omit) |
| Evaluation IR encode keys locked to schema properties | `574ff1be` | not an Independent A P0 (codec lock) |
| BackfillPlanner month-chunks from `plan_required_segments` | `bcd52f47` | IND-A-DOMAIN (independent calendar walk) |

PIT / `core_v1` / `research_data_profile` files are unchanged `67fcbd7c..ed94d504`. `coverage_ledger.py` gained five lines in `_empty_observed_forbids_complete` only.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 184065 (~51.1 h) |
| `stages.refresh_success` | **false** (`refresh_attempt=true`) |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.governed_dataset_count` | 26 |
| `ops_status.raw_retention.complete` | 18278 (raw-manifest column — **not** Dataset COMPLETE). Live payload has no `acquired` field; tree `b96d60bd` is undeployed here. |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |
| `sync_status` | `applied_cursor` **null**; datasets `LAGGING_APPLY_UNPINNED` / `EXPORT_CURRENT_APPLY_UNPINNED` |
| `validation_summary.dataset_count` | 23 (cron/validation run of current datasets — **not** Dataset COMPLETE 23) |
| `ingestion_last_run.detail.datasetCount` | 23 passed (same: current jquants cron, not Coverage COMPLETE) |
| `collection_sla_status(jsda_otc_bond_reference_prices)` | `current_state` **PROJECTION_STALE** (`ops_projection_stale`) |
| `endpoint_status(...).coverage_segment_granularity` | `official_archive_day` (canonical inventory under STALE projection — **not** the tree JSON grain) |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s sealer or BackfillPlanner wire):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. Reconstitution apply remains **false**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; all JQ jobs from `plan_required_segments`) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | **FIXED** (not reopened; sealer now passes local HTML; omit-without-HTML still empty) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | **FIXED** (not reopened; tip/index empty stays PARTIAL) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `67fcbd7c`. Callers `issue_receipts_parallel` / `issue_signed_receipts_for_segments` omitting `index_text` remain fail-closed empty residuals, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; BackfillPlanner no longer walks months independently of `plan_required_segments`)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-7,51-59,323-495,518-553`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

observed fact (HEAD vs `67fcbd7c`):

**FIXED (must stay) — planner clips official domain.** `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment (`:282-285`). Missing V3 loads as `None` and falls through to coverage JSON. Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger.

**Tightened — all governed JQ jobs come from `plan_required_segments`.** `BackfillPlanner.plan` inventories governed JQ contracts and calls `_jobs_from_required_segments` (`backfill_planner.py:518-553`). That helper is the only job emitter (`:403-495`): `plan_required_segments(cov, cutoff, source="jquants")`, skip already-COMPLETE ids, clamp `JQUANTS_SUBSCRIPTION_FLOOR` (2006-08-19 entitlement, not domain), emit pending jobs. JSDA is skipped (different runtime). `JobState` has no `COMPLETE` (`:51-59`). Tests pin:

- AM / earnings: one cutoff job, not 32 / 200 monthly shells (`test_planner_am_snapshot_is_not_32_month_densify`, `test_planner_earnings_snapshot_is_not_200_month_densify`).
- Master: `2006-08..2008-04` excluded; May starts `2008-05-07` (`test_planner_master_jobs_exclude_pre_official_months`).
- Bars/fins without V3: job ids / from / to equal `plan_required_segments` (`test_planner_bars_and_fins_month_chunks_match_required_segments`). `equities_bars_daily` → `2008-05/06/07`; `fins_summary` → `2008-07`.
- Missing V3: `source_capability_contract_or_none("fins_summary") is None`; start is coverage JSON `2008-07-01`; `evaluate_segment(..., None)` is PARTIAL (`test_planner_fins_summary_without_v3_uses_coverage_json_not_invented_domain`). Invented official-domain keys on a no-V3 dataset emit `UNPLANNABLE` / `fail`, not COMPLETE (`_invented_official_domain_without_v3`, `:334-344`; `test_planner_missing_v3_invented_official_domain_is_fail_closed`).

**Residual (do not reopen):** `_week_chunks` still subdivides today-mode `calendar_month` when `prefer_month_chunks_for_today=False`. Default is True. Coverage segment id stays `YYYY-MM`. Ops dispatch is not Dataset COMPLETE. Live MCP still shows V2 241 / 32 / 200 required.

why it still matters: claiming Dataset COMPLETE 23 from this SHA would ignore STALE V2 inventory and unpublished V3 planner. BackfillPlanner `pass` is worker summary, not Coverage COMPLETE.

structural fix (still in tree; tightened): required JQ jobs = `plan_required_segments`. Missing V3 does not invent official domain. Do not treat this SHA as Coverage COMPLETE 23.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `scripts/jsda_otc_seal_official.py:117-166,468-490,571`; `scripts/issue_receipts_parallel.py:598`; `scripts/issue_signed_receipts_for_segments.py:288`; `tests/test_jsda_otc_seal_official.py:44-166`; `tests/test_jsda_otc_official_domain.py`

observed fact (HEAD vs `67fcbd7c`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:912-917`). OTC grain remains `official_archive_index_day` (`collection_coverage.json:172`). Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty (`test_refresh_without_index_text_is_fail_closed_empty_not_calendar`).

**Tightened — sealer (`2ec8f572`).** `jsda_otc_seal_official.refresh_otc_coverage` always forwards `index_text=` (`:152-166`). `--index-text PATH` reads a **local** file (`_read_index_text`, `:117-134`). Omitted / blank / whitespace file → `None`. Missing PATH raises `FileNotFoundError` (CLI exit 1). Does not fetch live JSDA HTML (`urllib` / `requests` / `urlopen` absent). Grain default is `official_archive_index_day`. `PARSE_ZERO_SEAL_PROOF == {}` so `2002-08-02` / `2002-08-05` stay `PARSE_ZERO` / unsealed without in-repo digest+count. Tests: `test_refresh_otc_coverage_always_passes_index_text`, `test_read_index_text_omitted_blank_fixture`, `test_seal_day_parse_zero_stays_unsealed_without_proof`.

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `ed94d504` |
|--------|----------------------------|
| `packages/data_plane/ingestion/jsda/archive.py:528-535` | fetched year-index HTML; empty fetch → `None` |
| `scripts/refresh_coverage_ledger.py:147-160` | `--index-text PATH` or omitted `None` |
| `scripts/write_collection_receipts.py:105-138,271-275` | `--index-text` / `QP_INDEX_TEXT` or omitted `None` |
| `scripts/publish_ops_projection.py:242-247` | `--otc-index-html` or omitted/`OSError`/`blank` → `None` |
| `scripts/jsda_otc_seal_official.py:490,571` | **now passed** (local HTML or `None`) |
| `scripts/issue_receipts_parallel.py:598` | **omitted** (fail-closed empty) |
| `scripts/issue_signed_receipts_for_segments.py:288` | **omitted** (fail-closed empty) |
| `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-111` | **omitted** (jquants READY path; OTC empty if included) |

`issue_receipts_parallel` / `issue_signed_receipts_for_segments` still call `refresh_coverage_ledger(...)` without `index_text=`. If those scripts touch OTC, refresh DELETEs STALE 8784 calendar rows and writes **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still 8784 under STALE V2. Canonical inventory / `endpoint_status` still advertise `coverage_segment_granularity=official_archive_day`.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / sealer CLI is not a live official-index republish.

structural fix (still in tree; sealer tightened): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`

No PIT file changes `67fcbd7c..ed94d504`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1439`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:127-138,330-354,357-434`; `tests/test_phase61_coverage_v2.py:126-251`; `tests/test_am_bars_tip_only.py:219-232`; `tests/test_earnings_calendar_tip_only.py`

observed fact (HEAD vs `67fcbd7c`):

**Tightened — tip / archive-index empty is PARTIAL even if `event_driven`.** `_empty_observed_forbids_complete` now returns True when `_is_tip_snapshot_policy` or `_uses_official_archive_index` (`:338-342`) **before** the string/grain checks. `evaluate_segment` on empty SUCCESS + that gate is PARTIAL with reason `empty tip-snapshot or archive-index receipt is not complete` (`:397-400`). Tests pin:

- Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts (`test_event_zero_successful_exhausted_raw_receipt_is_complete`) — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends.
- AM `recent_snapshot` / earnings `next_business_day_snapshot` empty SUCCESS → PARTIAL (`test_tip_snapshot_empty_receipt_is_partial_not_complete`).
- Earnings stays PARTIAL even though `expected_frequency == event_driven` (`test_earnings_event_driven_empty_is_not_event_zero_complete`).
- AM stays PARTIAL even if relabeled `event_driven` (`test_tip_snapshot_empty_stays_partial_even_if_event_driven`).
- OTC `official_archive_index_day` empty SUCCESS → PARTIAL, including if relabeled `event_driven` (`test_official_archive_index_empty_receipt_is_partial_not_complete`, `test_archive_index_empty_stays_partial_even_if_event_driven`).

Tip-snapshot empty PARTIAL, string-COMPLETE rejection, raw `ACQUIRED`, and missing-V3 fail-closed are untouched. Empty official-archive-index receipts stay PARTIAL. Live `ops_status.raw_retention.complete=18278` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE. Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

No `67fcbd7c..ed94d504` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. This review does not publish READY.

---

## Evaluation IR encode keys (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** (`574ff1be`); does not reopen named A holes  
file:line: `packages/product/research/evaluation_ir.py:679-701`; `platform/workers/research-mass-eval/src/evaluation_ir.ts:107-166`; `scripts/verify_ci.sh:80-82`; `tests/test_evaluation_ir.py:64-79`

Hand-written `CANONICAL_FIELDS` is gone. Python `encode_evaluation_ir` still calls `job_candidate_grade`. Worker encode still calls `jobCandidateGrade` and `assertEncodeKeys` against generated `ALLOWED_FIELDS`. `assert_evaluation_ir_encode_keys_match_schema` fails CI if Python or Worker encode keys drift from `schema.json` properties. Decode still rejects unknown fields and `version !== evaluation-ir/v1`. This is a codec lock, not a Coverage COMPLETE mint, not a PIT bypass, and not READY.

Residual (not A P0): Worker `EVALUATION_IR_VERSION` is still a string literal; Python reads the schema `const`. CI still compares encode keys to schema properties.

---

## What this review does not claim

- Planner / PIT / profile / OTC-sealer / event-zero wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- Sealer `--index-text` rebuilt production D1. Isolation did not run live JSDA fetch or seal.
- Callers `issue_receipts_parallel` / `issue_signed_receipts_for_segments` omitting `index_text` rebuilt the live ledger. They remain fail-closed empty, not weekend COMPLETE, and not FRESH.
- IR encode-key lock republished READY or Mass. It did not.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `ed94d504`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18278` still counts historical `completeness=COMPLETE` strings.
- `BackfillPlanner` / event-zero / sealer `index_text` were confirmed from source + unit tests at HEAD; they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit callers (`issue_receipts_parallel`, `issue_signed_receipts_for_segments`) were not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
