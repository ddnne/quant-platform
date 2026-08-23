# Independent review A revisit — at `3b64bdfc`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `3b64bdfc` (`3b64bdfc9a41be76a6e4e881aaea1ff9751443ed`)  
**Branch at audit:** `grok/p632-ind-A-revisit-3b64bdfc` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freezes:** `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md)); `ed94d504` ([`P632_ind_A_revisit_ed94d504.md`](P632_ind_A_revisit_ed94d504.md)); `5103b26b` ([`P632_ind_A_revisit_5103b26b.md`](P632_ind_A_revisit_5103b26b.md))  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A after wave-7 follow-ups on `origin/grok/phase63-ci-source-closure` (overlay never CLI-put; research artifacts Worker POST; unbound children-then-manifest 503; leftover occupancy HOLD pointer). Prior at `5103b26b` said tree P0 = 0. Docs only. Detect-only. This file does not rewrite earlier freeze files.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, Phase 6.3.2 COMPLETE, or Phase 7 GO.

`git rev-list --count 5103b26b..3b64bdfc` = **16**. Independent A PIT / ledger / planner / profile files are unchanged this window. Code follow-ups below are not Independent A P0s.

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| Worker POST `/v1/children-then-manifest` unbound token is 503 | `52f3e70e` | not an Independent A P0 (R2 put fail-closed) |
| `verify_ci` Evaluation IR generated-TS freeze invocations pinned | `2e264a08` | not an Independent A P0 (CI freeze pin) |
| leftover occupancy HOLD pointer; do not unify | `046ae438` | not an Independent A P0 (catalog park residual) |
| remote Python R2 put never CLI-puts even with overlay | `0b81eedb` | not an Independent A P0 (R2 put authority) |
| remote job artifacts use Worker children-then-manifest | `d6567268` | not an Independent A P0 (R2 put authority) |

PIT / `core_v1` / `research_data_profile` / `backfill_planner` / `coverage_ledger` / JSDA `index_text` CLI files are unchanged `5103b26b..3b64bdfc`.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**. Live STALE V2 floors are last-known, not current V3.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 185847 (~51.6 h) |
| `stages.refresh_success` | **false** (`refresh_attempt=true`) |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.governed_dataset_count` | 26 |
| `ops_status.raw_retention.complete` | 18278 (raw-manifest column — **not** Dataset COMPLETE). Live payload has no `acquired` field. |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |
| `sync_status` | `applied_feed_cursor` **null**; datasets `LAGGING_APPLY_UNPINNED` / `EXPORT_CURRENT_APPLY_UNPINNED` |
| `validation_summary.dataset_count` | 23 (cron/validation run of current datasets — **not** Dataset COMPLETE 23) |
| `ingestion_last_run.detail.datasetCount` | 23 passed (same: current jquants cron, not Coverage COMPLETE) |
| `collection_sla_status(jsda_otc_bond_reference_prices)` | `current_state` **PROJECTION_STALE** (`ops_projection_stale`) |
| `endpoint_status(...).coverage_segment_granularity` | `official_archive_day` (canonical inventory under STALE projection — **not** the tree JSON grain) |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s overlay / Worker POST / occupancy HOLD pointer):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set. PARSE_ZERO `2002-08-02` / `2002-08-05` stay PARTIAL (`PARSE_ZERO_SEAL_PROOF` empty).

Same generation as the `5103b26b` freeze (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 184880 → 185847. Floors and 4-PARTIAL set are unchanged.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` | At `3b64bdfc` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; planner files unchanged) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `index_text` callers unchanged; omit-without-HTML still empty) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; empty-observed gate unchanged; PARSE_ZERO 2 stay PARTIAL) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `5103b26b`. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## Tree deltas after `5103b26b`

Window: `5103b26b..3b64bdfc` (16 commits). Independent A surfaces (`packages/data_plane/pit/`, `coverage_ledger.py`, `backfill_planner.py`, `core_v1.json`, `research_data_profile.py`, JSDA `index_text` CLIs / pipeline / archive) have **empty** `git diff --stat`.

Wave-7 follow-ups at this HEAD (not Independent A P0; do not mint COMPLETE / FRESH / READY / GO):

1. **overlay never CLI-put** (`0b81eedb`). `default_r2_put` remote raises `WORKER_CHILDREN_THEN_MANIFEST_ERROR` even with `QP_ALLOW_PYTHON_R2_PUT=1`. Overlay env is not artifact authority and does not resurrect head-then-put TOCTOU. `dry_run` stays local. `authoritative=True` stays refused. `python_r2_put_allowed()` remains a flag reader; it does not grant CLI put (`r2_io.py:66-71,313-361`).
2. **research artifacts Worker POST** (`d6567268`). `put_research_artifact` remote POSTs empty children and the job object as the manifest via `put_children_then_manifest_via_worker`. `dry_run` still stages locally via `default_r2_put`. Tests stub HTTP; no live Worker (`r2_io.py:278-310`).
3. **unbound children-then-manifest 503** (`52f3e70e`). Worker `POST /v1/children-then-manifest` with unbound `MASS_EVAL_TOKEN` returns **503** and does not put. Missing header stays **401**. Route still returns `go: false` / `not_a_pass: true` (`http_routes.ts:321-403`; `http.test.ts:406-428`).
4. **leftover occupancy HOLD pointer** (`046ae438`). Two comment lines on `unique22_occupancy_park`: park reasons live in `UNIQUE22_PARK_REASONS`; leftover occupancy stays in `daily_path.ts`. Do not unify with `comboEventGateOk`. Does not unpark (`worker_bodies.py:83-113`).

Also in-window, not Independent A: `2e264a08` pins `verify_ci` Evaluation IR generated-TS freeze invocations (codec freeze, not Coverage COMPLETE). Remaining 11 commits are docs (wave-7 status, Independent A/B/C revisits at `5103b26b`, banners). [`P632_wave7_status.md`](P632_wave7_status.md) reviews `5103b26b` vs `ed94d504`; it is not this SHA’s Independent A freeze.

Feature branch is **not** merged to `origin/main` (`git merge-base --is-ancestor 3b64bdfc origin/main` is false). Isolation did not push `main` and did not deploy.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened; remaining receipt CLIs and pipeline helper still forward `index_text`)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `packages/data_plane/ingestion/pipeline.py:119-163,448-479`; `scripts/jsda_otc_seal_official.py:117-166,468-490,571`; `scripts/issue_receipts_parallel.py:500-524,633-634`; `scripts/issue_signed_receipts_for_segments.py:102-148,224,345`; `tests/test_issue_receipts_parallel_cli.py`; `tests/test_issue_signed_receipts_for_segments.py`; `tests/test_pipeline_otc_index_text.py`; `tests/test_jsda_otc_official_domain.py`

observed fact (HEAD vs `5103b26b`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:912-917`). OTC grain remains `official_archive_index_day`. Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty (`test_refresh_without_index_text_is_fail_closed_empty_not_calendar`). Ledger / planner / CLI files are unchanged this window.

**Unchanged — remaining receipt CLIs / pipeline helper / JQ fixture pin.** `issue_receipts_parallel` and `issue_signed_receipts_for_segments` still take optional `--index-text PATH` and always forward `index_text=` into `refresh_coverage_ledger`. Pipeline persist still has no year-index HTML → `_index_text_for_plan(policy)` with none (`pipeline.py:448-450`) — OTC required set is empty, not 8784 weekends. Coherence fixtures still plan JQ datasets only (`test_coherence_with_receipts.py:29-35`).

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `3b64bdfc` |
|--------|----------------------------|
| `packages/data_plane/ingestion/jsda/archive.py:528-535` | fetched year-index HTML; empty fetch → `None` |
| `scripts/refresh_coverage_ledger.py:147-160` | `--index-text PATH` or omitted `None` |
| `scripts/write_collection_receipts.py:105-138,271-275` | `--index-text` / `QP_INDEX_TEXT` or omitted `None` |
| `scripts/publish_ops_projection.py:242-247` | `--otc-index-html` or omitted/`OSError`/`blank` → `None` |
| `scripts/jsda_otc_seal_official.py:490,571` | passed (local HTML or `None`) |
| `scripts/issue_receipts_parallel.py:541,634` | passed (local HTML or `None`) |
| `scripts/issue_signed_receipts_for_segments.py:224,345` | passed (local HTML or `None`) |
| `packages/data_plane/ingestion/pipeline.py:450,456,479` | passed; persist has no held HTML → `None` |
| `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-111` | **omitted** (jquants READY path; OTC empty if included) |

A live refresh that omits `index_text` / has no HTML would DELETE the STALE 8784 calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still 8784 under STALE V2. Canonical inventory / `endpoint_status` still advertise `coverage_segment_granularity=official_archive_day`.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / CLIs is not a live official-index republish. Overlay / Worker POST / occupancy HOLD pointer do not republish the OTC required set.

structural fix (still in tree): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; BackfillPlanner files unchanged this window)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-7,51-59,323-495,518-553`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

No `5103b26b..3b64bdfc` rewrite of master / AM / earnings planner clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. All governed JQ jobs still come from `plan_required_segments` (`backfill_planner.py:518-553`). Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`

No PIT file changes `5103b26b..3b64bdfc`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO (`packages/research_runtime/core/universe.py:15-19,32`).

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1439`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint. Worker `go: false` on children-then-manifest is R2 put authority, not a receipt COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:127-138,330-354,357-434`; `scripts/jsda_otc_seal_official.py:50-52,138-141`; `tests/test_phase61_coverage_v2.py:126-251`; `tests/test_am_bars_tip_only.py:219-232`; `tests/test_earnings_calendar_tip_only.py`

No `5103b26b..3b64bdfc` change to `_empty_observed_forbids_complete`. Tip / archive-index empty SUCCESS stays PARTIAL even if `event_driven` (`:338-342`, `:397-400`). Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18278` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE. PARSE_ZERO days `2002-08-02` / `2002-08-05` stay PARTIAL: `PARSE_ZERO_SEAL_PROOF: dict[str, tuple[str, int]] = {}` (no in-repo digest+count). Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

No `5103b26b..3b64bdfc` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. Overlay / Worker POST / occupancy HOLD pointer do not publish READY. This review does not publish READY.

---

## Wave-7 follow-ups (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** at `3b64bdfc`; do not reopen named A holes  
file:line: `packages/product/research/r2_io.py:1-15,66-71,197-275,278-361`; `platform/workers/research-mass-eval/src/http_routes.ts:321-403`; `platform/workers/research-mass-eval/src/http.test.ts:406-428`; `packages/product/research/unique_logic/worker_bodies.py:83-113`; `tests/test_immutable_artifact.py`; `tests/test_verify_ci_script.py`

- Unbound Worker token is 503 and does not put. Missing header stays 401. `go` stays **false**.
- Remote `default_r2_put` never CLI-puts, including with overlay `QP_ALLOW_PYTHON_R2_PUT=1`.
- Remote research job artifacts POST Worker children-then-manifest (empty children, object as manifest). dry_run local. Tests stub HTTP.
- Leftover occupancy HOLD pointer is a comment; park set is unchanged. Do not unpark.
- `verify_ci` IR generated-TS freeze pin is a CI lock, not a Coverage COMPLETE mint.

These are R2 put authority / catalog park residual / CI freeze, not a PIT bypass, not an official-domain reopen, and not READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-`index_text` / overlay / Worker POST wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- Receipt CLIs `--index-text` rebuilt production D1. Isolation did not run live JSDA fetch or seal.
- Pipeline persist with no held HTML rebuilt the live ledger. Persist is fail-closed empty for OTC, not weekend COMPLETE, and not FRESH.
- Caller `snapshot_publish_policy` omitting `index_text` rebuilt the live ledger. It remains fail-closed empty if OTC is included, not weekend COMPLETE.
- Overlay never CLI-put / research-artifact Worker POST / unbound 503 republished READY or Mass. They did not. Worker `go` is **false**.
- Leftover occupancy HOLD pointer unparked unique-22. It did not.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- PARSE_ZERO `2002-08-02` / `2002-08-05` are sealed. `PARSE_ZERO_SEAL_PROOF` is empty.
- This file is not a seal, densify, floor bump, Mass ON, Phase 6.3.2 COMPLETE, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `3b64bdfc`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18278` still counts historical `completeness=COMPLETE` strings.
- `issue_receipts_parallel` / `issue_signed_receipts_for_segments` / pipeline `index_text` were confirmed from source + unit tests at HEAD; they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit caller (`snapshot_publish_policy`) was not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
- Overlay never CLI-put, research-artifact Worker POST, and unbound 503 were confirmed from source + unit tests; they were not executed against a live Worker / R2 in this isolation worktree.
