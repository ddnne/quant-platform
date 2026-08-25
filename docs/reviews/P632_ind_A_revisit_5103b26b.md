# Independent review A revisit — at `5103b26b`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `5103b26b` (`5103b26bb40b2d73b49d079e03f8cf5b9c2a4c58`)  
**Branch at audit:** `grok/p632-ind-A-revisit-5103b26b` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freezes:** `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md)); `ed94d504` ([`P632_ind_A_revisit_ed94d504.md`](P632_ind_A_revisit_ed94d504.md))  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A after IR codec generated from schema; Python POST `/v1/children-then-manifest`; remaining `issue_receipts` `index_text` CLIs landed on parent after `ed94d504`. Prior at `ed94d504` said tree P0 = 0. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, or Phase 7 GO.

Landing verified in tree (not trusted from titles):

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| `issue_receipts_parallel` passes local `--index-text` | `e0699dbf` | IND-A-JSDA-PHANTOM (CLI omit residual) |
| `issue_signed_receipts_for_segments` passes local `--index-text` | `fd660c40` | IND-A-JSDA-PHANTOM (CLI omit residual) |
| pipeline plan reuses already-held OTC year-index HTML | `34701984` | IND-A-JSDA-PHANTOM (persist omit residual) |
| JQ `plan_required_segments` without `index_text` is not OTC weekend COMPLETE | `9da05fc5` | IND-A-JSDA-PHANTOM (fixture pin) |
| Evaluation IR encode/decode emitted from `schema.json` | `4661fb14` | not an Independent A P0 (codec generate) |
| Python POST Worker `/v1/children-then-manifest` | `5103b26b` | not an Independent A P0 (R2 put authority) |

PIT / `core_v1` / `research_data_profile` / `backfill_planner` / `coverage_ledger` files are unchanged `ed94d504..5103b26b`.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 184880 (~51.4 h) |
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

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s `index_text` CLIs, pipeline helper, IR codec, or Worker POST):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; planner files unchanged) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | FIXED | **FIXED** (not reopened; remaining receipt CLIs + pipeline helper now pass `index_text`; omit-without-HTML still empty) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; empty-observed gate unchanged) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `ed94d504`. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened; remaining receipt CLIs and pipeline helper now forward `index_text`)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `packages/data_plane/ingestion/pipeline.py:119-163,448-479`; `scripts/jsda_otc_seal_official.py:117-166,468-490,571`; `scripts/issue_receipts_parallel.py:500-524,633-634`; `scripts/issue_signed_receipts_for_segments.py:102-148,224,345`; `tests/test_issue_receipts_parallel_cli.py`; `tests/test_issue_signed_receipts_for_segments.py`; `tests/test_pipeline_otc_index_text.py`; `tests/test_jsda_otc_official_domain.py`

observed fact (HEAD vs `ed94d504`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:912-917`). OTC grain remains `official_archive_index_day`. Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty (`test_refresh_without_index_text_is_fail_closed_empty_not_calendar`). Ledger / planner files are unchanged this window.

**Tightened — remaining receipt CLIs (`e0699dbf` / `fd660c40`).** Both `issue_receipts_parallel` and `issue_signed_receipts_for_segments` now take optional `--index-text PATH` and always forward `index_text=` into `refresh_coverage_ledger`. Omitted flag → `None`. Missing PATH raises `FileNotFoundError` (CLI exit 1). Does not fetch live JSDA HTML. Tests pin argparse, `_read_index_text`, and the refresh kwargs (`test_main_omitted_index_text_is_none_not_calendar_replay`, `test_main_passes_local_index_text_through` / `test_refresh_issued_coverage_always_passes_index_text`). They do not run a live ledger.

**Tightened — pipeline helper (`34701984`).** `_plan_required_segments` wraps ledger plan and always routes `index_text` through `_index_text_for_plan` (`pipeline.py:132-163`). Blank / missing text is `None`. Persist (`_persist`, `:394`) has no year-index HTML in hand, so it calls `_index_text_for_plan(policy)` with none (`:448-450`) — OTC required set is empty, not 8784 weekends. Tests: `test_pipeline_otc_plan_without_index_text_is_empty`, `test_pipeline_otc_plan_with_fixture_html_lists_publication_days_not_weekend`, `test_pipeline_persist_passes_index_text_into_plan`. Does not fetch live HTML.

**Tightened — JQ fixture pin (`9da05fc5`).** Snapshot / coherence fixtures plan JQ datasets only. Missing `index_text` on an OTC policy would empty the required set, not invent weekend COMPLETE (`test_coherence_with_receipts.py:29-35`).

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `5103b26b` |
|--------|----------------------------|
| `packages/data_plane/ingestion/jsda/archive.py:528-535` | fetched year-index HTML; empty fetch → `None` |
| `scripts/refresh_coverage_ledger.py:147-160` | `--index-text PATH` or omitted `None` |
| `scripts/write_collection_receipts.py:105-138,271-275` | `--index-text` / `QP_INDEX_TEXT` or omitted `None` |
| `scripts/publish_ops_projection.py:242-247` | `--otc-index-html` or omitted/`OSError`/`blank` → `None` |
| `scripts/jsda_otc_seal_official.py:490,571` | passed (local HTML or `None`) |
| `scripts/issue_receipts_parallel.py:541,634` | **now passed** (local HTML or `None`) |
| `scripts/issue_signed_receipts_for_segments.py:224,345` | **now passed** (local HTML or `None`) |
| `packages/data_plane/ingestion/pipeline.py:450,456,479` | **now passed**; persist has no held HTML → `None` |
| `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-111` | **omitted** (jquants READY path; OTC empty if included) |

A live refresh that omits `index_text` / has no HTML would DELETE the STALE 8784 calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still 8784 under STALE V2. Canonical inventory / `endpoint_status` still advertise `coverage_segment_granularity=official_archive_day`.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / CLIs is not a live official-index republish.

structural fix (still in tree; remaining CLIs + pipeline helper tightened): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; BackfillPlanner files unchanged this window)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-7,51-59,323-495,518-553`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

No `ed94d504..5103b26b` rewrite of master / AM / earnings planner clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. All governed JQ jobs still come from `plan_required_segments` (`backfill_planner.py:518-553`). Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`

No PIT file changes `ed94d504..5103b26b`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO.

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

No `ed94d504..5103b26b` change to `_empty_observed_forbids_complete`. Tip / archive-index empty SUCCESS stays PARTIAL even if `event_driven` (`:338-342`, `:397-400`). Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18278` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE. Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

No `ed94d504..5103b26b` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. This review does not publish READY.

---

## Evaluation IR codec generated from schema (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** (`4661fb14`); does not reopen named A holes  
file:line: `packages/product/research/evaluation_ir.py:19-24,563-710,1013-1035`; `platform/workers/research-mass-eval/src/evaluation_ir.ts:11-33`; `platform/workers/research-mass-eval/src/evaluation_ir_codec.generated.ts`; `scripts/verify_ci.sh:80-83`; `tests/test_evaluation_ir.py:67-136`

Hand-written Worker encode/decode body is gone from `evaluation_ir.ts` (façade re-exports). Python emits `evaluation_ir_codec.generated.ts` from `schema.json` properties. `EVALUATION_IR_VERSION` is now the schema `const` (prior residual at `ed94d504` was a Worker string literal). Encode still calls `jobCandidateGrade`. CI freeze-checks generated codec + ALLOWED_FIELDS + encode keys vs schema properties. Decode still rejects unknown fields and `version !== evaluation-ir/v1`. This is a codec generate lock, not a Coverage COMPLETE mint, not a PIT bypass, and not READY.

Residual (not A P0): `_TS_ENCODE_VALUE_EXPR` is still a Python map of TS expressions keyed to schema properties (must equal; extra/missing fail generate). Grade remains `jobCandidateGrade`, not a schema `if`/`then`.

---

## Python POST `/v1/children-then-manifest` (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** (`5103b26b`); does not reopen named A holes  
file:line: `packages/product/research/r2_io.py:1-11,48-51,134-268`; `platform/workers/research-mass-eval/src/http_routes.ts:321-400`; `tests/test_immutable_artifact.py:188-405`

`put_children_then_manifest_via_worker` now POSTs `/v1/children-then-manifest` with `X-Mass-Eval-Token` instead of raising on a bound Worker. Unbound URL/token still fail closed (`WORKER_CHILDREN_THEN_MANIFEST_ERROR`). `dry_run` stays local. There is no CLI put fallback and no digest forge. Non-JSON body fail-closes. Worker route returns `go: false` / `not_a_pass: true`. This is R2 put authority, not a Coverage COMPLETE mint, not a PIT bypass, and not READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-`index_text` / IR codec / Worker POST wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- Receipt CLIs `--index-text` rebuilt production D1. Isolation did not run live JSDA fetch or seal.
- Pipeline persist with no held HTML rebuilt the live ledger. Persist is fail-closed empty for OTC, not weekend COMPLETE, and not FRESH.
- Caller `snapshot_publish_policy` omitting `index_text` rebuilt the live ledger. It remains fail-closed empty if OTC is included, not weekend COMPLETE.
- IR codec generate republished READY or Mass. It did not.
- Python POST children-then-manifest republished READY or Mass. Worker `go` is **false**.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- This file is not a seal, densify, floor bump, Mass ON, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `5103b26b`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18278` still counts historical `completeness=COMPLETE` strings.
- `issue_receipts_parallel` / `issue_signed_receipts_for_segments` / pipeline `index_text` were confirmed from source + unit tests at HEAD; they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit caller (`snapshot_publish_policy`) was not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
- IR codec generate and Worker POST children-then-manifest were confirmed from source + unit tests; they were not executed against a live Worker / R2 in this isolation worktree.
