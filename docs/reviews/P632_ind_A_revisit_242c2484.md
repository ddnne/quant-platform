# Independent review A revisit — at `242c2484`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**HEAD:** `242c2484` (`242c2484e9307f9163b13fc603ad90f67c6a0919`)  
**Branch at audit:** `grok/p632-ind-A-revisit-242c2484` (from `origin/grok/phase63-ci-source-closure`)  
**Prior freeze:** `3b64bdfc` ([`P632_ind_A_revisit_3b64bdfc.md`](P632_ind_A_revisit_3b64bdfc.md)). Earlier: `3ab87d0` ([`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md)); `d93335b` ([`P632_ind_A_revisit.md`](P632_ind_A_revisit.md)); `f224e7e` ([`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md)); `40d1aa90` ([`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md)); `67fcbd7c` ([`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md)); `ed94d504` ([`P632_ind_A_revisit_ed94d504.md`](P632_ind_A_revisit_ed94d504.md)); `5103b26b` ([`P632_ind_A_revisit_5103b26b.md`](P632_ind_A_revisit_5103b26b.md)). This file does not rewrite those freezes.  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Scope:** re-diff Independent A at current `origin/grok/phase63-ci-source-closure` vs `3b64bdfc`. Named tree deltas: Worker-put callers, BackfillPlanner `index_text`, python IR codec, premium fetch extract, jitter. Those are **not** Independent A P0s unless they reopen PIT / COMPLETE. Docs only. Detect-only.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Dataset COMPLETE 23, Phase 6.3.2 COMPLETE, or Phase 7 GO.

`git rev-list --count 3b64bdfc..242c2484` = **18**. PIT / `coverage_ledger` / `core_v1` / `research_data_profile` / JSDA `index_text` CLIs / pipeline / archive have **empty** `git diff --stat` this window. Only Independent-A-adjacent code change is `backfill_planner.py` forwarding `index_text`.

| Landing | SHA (short) | Named hole |
|---------|-------------|------------|
| daily-path both-track artifact uses Worker put | `017a43c6` | not an Independent A P0 (R2 put caller) |
| mass-eval-run fallback artifacts use Worker put | `0a8ced34` | not an Independent A P0 (R2 put caller) |
| BackfillPlanner passes `index_text` into required segments | `2cbd894d` | not an Independent A P0 (JSDA skip + omit-without-HTML still empty; does not reopen calendar COMPLETE) |
| premium retry jitter uses `crypto.getRandomValues` | `82ef0f7b` | not an Independent A P0 (retry jitter) |
| extract premium JQ fetch/retry from index | `a20d14d4` | not an Independent A P0 (Worker HTTP extract) |
| emit Evaluation IR python codec from `schema.json` | `c9764ff4` | not an Independent A P0 (codec generate; IR `n_complete` is a cell count, not Dataset COMPLETE) |

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS. STALE is **STALE**. Live STALE V2 floors are last-known, not current V3.

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 186984 (~51.9 h) |
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

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not current planner / not this SHA’s Worker-put / planner `index_text` / IR codec / premium extract):

| Dataset | Live `history_target_start` | required / complete / remaining (`backfill_status`) | `evaluated_at` |
|---------|-----------------------------|------------------------------------------------------|----------------|
| `equities_master` | **2006-08-13** | 241 / 220 / 21 | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 32 / 1 / 31 | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 200 / 1 / 199 | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 8784 / 5886 / 2898 | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not Dataset COMPLETE 23. Live 8784 is STALE calendar inventory, not a published official-index required set. PARSE_ZERO `2002-08-02` / `2002-08-05` stay PARTIAL (`PARSE_ZERO_SEAL_PROOF` empty).

Same generation as the `3b64bdfc` freeze (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 185847 → 186984. Floors and 4-PARTIAL set are unchanged. `raw_retention.complete` 18278 → 18301 is the live raw-manifest column ticking under cron — **not** Coverage COMPLETE.

---

## Scoreboard vs `3ab87d0` / `d93335b` / `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b` / `3b64bdfc`

| ID | Topic | Sev | At `3ab87d0` | At `d93335b` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` | At `3b64bdfc` | At `242c2484` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|---------------|---------------|
| IND-A-DOMAIN | Official availability vs required domain (master / AM / earnings) | P0 | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `plan_required_segments` clip unchanged) |
| IND-A-JSDA-PHANTOM | JSDA OTC calendar-day phantom required segments | P0 | OPEN | OPEN | OPEN (planner FIXED; refresh replay OPEN) | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; planner now forwards `index_text`; omit-without-HTML still empty; JSDA still skipped at `plan()`) |
| IND-A-PIT-BYPASS | PIT `as_of` / official-domain bypasses | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; PIT files unchanged) |
| IND-A-FORGED-RECEIPT | Unsigned / synthetic TRUSTED_COLLECTION COMPLETE | P0 | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | False COMPLETE / raw-only COMPLETE | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; empty-observed gate unchanged; PARSE_ZERO 2 stay PARTIAL) |
| IND-A-READY-DEPS | READY profile dependency omission | P0 | OPEN | OPEN | FIXED | FIXED | FIXED | FIXED | FIXED | FIXED | **FIXED** (not reopened; `core_v1` still includes master) |

Independent P0 remaining: **0**. Named Independent A P0s stay closed in tree. No reopen vs `3b64bdfc`. Worker-put / BackfillPlanner `index_text` / python IR codec / premium fetch extract / jitter do **not** reopen PIT or COMPLETE. Callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE. Live MCP is still **STALE** 8784. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

---

## Tree deltas after `3b64bdfc`

Window: `3b64bdfc..242c2484` (18 commits). Independent A surfaces (`packages/data_plane/pit/`, `coverage_ledger.py`, `core_v1.json`, `research_data_profile.py`, JSDA `index_text` CLIs / pipeline / archive) have **empty** `git diff --stat`. `backfill_planner.py` is the only Independent-A-adjacent code change (`+20 / -5`).

Code landings at this HEAD (not Independent A P0; do not mint COMPLETE / FRESH / READY / GO):

1. **Worker-put callers** (`017a43c6`, `0a8ced34`). `cf_daily_path_job.run_both_track_sleeve_fanout` and `cf_mass_eval_run.put_local_fallback_artifacts` now call `put_research_artifact` instead of `default_r2_put`. Remote POSTs Worker `/v1/children-then-manifest` (empty children, object as manifest). Overlay `QP_ALLOW_PYTHON_R2_PUT=1` still does not grant CLI put (`r2_io.py:69,213,278-313`). Tests stub HTTP; no live Worker. `reconstitution_evidence.py` still uses `default_r2_put` (remote still refuses CLI put). Does not publish READY. Worker `go` stays **false**.
2. **BackfillPlanner `index_text`** (`2cbd894d`). `BackfillPlanner.plan` / `_jobs_from_required_segments` forward `index_text=` into `plan_required_segments` (default `None`). Missing/blank is fail-closed empty official-index set, never a calendar-weekend walk. `plan()` still **skips** `jsda_*` (`backfill_planner.py:536-538`). Production callers `range_batch_scheduler.plan()` and `cf_premium_backfill.plan()` omit the kwarg → `None`. Tests pin omitted ≠ 8784 weekends and no `COMPLETE` job state (`test_backfill_planner.py:422-537`). Tightens a residual; does **not** reopen IND-A-JSDA-PHANTOM.
3. **python IR codec** (`c9764ff4`). `evaluation_ir_codec.generated.py` is emitted from `specs/evaluation_ir/schema.json`. Encode keys include `n_complete` as an evaluation-cell count. That is **not** Dataset COMPLETE, not Coverage V2 aggregate, not READY. `verify_ci` locks the generated codec. Codec freeze, not a ledger mint.
4. **premium fetch extract** (`a20d14d4`). J-Quants Premium fetch/retry moved to `fetch_jq.ts`. `ingestOne` / `runIngestion` façade stays in `index.ts`. HTTP pagination / 429/5xx backoff extract. Does not evaluate coverage segments or emit COMPLETE.
5. **jitter** (`82ef0f7b`). `retry_jitter.ts` uses `crypto.getRandomValues`, not `Math.random`. Retry delay only. Not a PIT path and not a COMPLETE mint.

Remaining 12 commits are docs (Independent A/B/C revisits, wave-8, GATEWAY_TOKEN HOLD, residual SoT banners, §10 mixed). [`P632_wave8_status.md`](P632_wave8_status.md) reviews `3b64bdfc`; it is not this SHA’s Independent A freeze.

Feature branch is **not** merged to `origin/main` (`git merge-base --is-ancestor 242c2484 origin/main` is false). Isolation did not push `main` and did not deploy.

---

## IND-A-DOMAIN

severity: **P0**  
status: **FIXED** (not reopened; `plan_required_segments` clip unchanged this window)  
file:line: `packages/data_plane/ops/backfill_planner.py:1-9,350-430,508-578`; `packages/data_plane/storage/coverage_ledger.py:198-285`; `tests/test_backfill_planner.py:163-270,315-419`

No `3b64bdfc..242c2484` rewrite of master / AM / earnings official-domain clipping. `plan_required_segments` still loads SourceCapabilityContract and clips through `required_domain_subset_official`. Tip/snapshot policies emit one cutoff segment. Missing V3 loads as `None` and falls through to coverage JSON. All governed JQ jobs still come from `plan_required_segments` (`backfill_planner.py:557-568`). Planner now also forwards `index_text` (JQ month jobs unchanged with or without HTML). Live STALE still advertises V2 floors (master `2006-08-13`, AM 32-month / earnings 200-month inventory). Planner wire is not a published ledger. Do not claim Dataset COMPLETE 23.

---

## IND-A-JSDA-PHANTOM

severity: **P0**  
status: **FIXED** (not reopened; BackfillPlanner now forwards `index_text`; omit-without-HTML still empty)  
file:line: `packages/data_plane/storage/coverage_ledger.py:180-195,198-214,286-296,330-354,779-796,912-956,1020-1028`; `packages/data_plane/ops/backfill_planner.py:4-9,408-430,508-538,563-567`; `packages/data_plane/ingestion/jsda/archive.py:528-535`; `packages/data_plane/ingestion/pipeline.py:119-163,448-479`; `scripts/jsda_otc_seal_official.py:50-52,117-166,468-490,571`; `tests/test_backfill_planner.py:422-537`; `tests/test_jsda_otc_official_domain.py`

observed fact (HEAD vs `3b64bdfc`):

**FIXED (must stay) — planner / refresh.** Official-archive-index datasets still take `official_index_days(dataset, index_text)` (`coverage_ledger.py:286-296`). Missing `index_text` yields an **empty** required set, not a calendar walk. Inventory replay branch is still only `segment_granularity in {official_archive_day, source_time_series_file} and not _uses_official_archive_index` (`:912-917`). OTC grain in tree JSON remains `official_archive_index_day`. Empty required list evaluates PARTIAL (`evaluate_required_segments`: `statuses and all(...)` is false when empty, `:792-796`; sticky recompute `:1023-1028`). Tests still pin weekend `2002-08-03` absent and omit-without-HTML empty (`test_refresh_without_index_text_is_fail_closed_empty_not_calendar`). Ledger / CLI / pipeline / archive files are unchanged this window.

**Tightened — BackfillPlanner (`2cbd894d`).** `plan()` / `_jobs_from_required_segments` always pass `index_text=` (default `None`). JSDA datasets remain skipped (`dataset_id.startswith("jsda_")`). Asking `plan(datasets=[otc])` returns `[]`, not 8784 weekends, and no job `state=="COMPLETE"`. `_jobs_from_required_segments(..., index_text=None/""/"   ")` is empty. This is fail-closed, not a COMPLETE mint, and not a live official-index republish.

**Unchanged — remaining omit-without-HTML callers.** Pipeline persist still has no year-index HTML → `_index_text_for_plan(policy)` with none (`pipeline.py:448-450`). `snapshot_publish_policy` still omits `index_text` (`:109-111`). `range_batch_scheduler.plan()` and `cf_premium_backfill.plan()` omit the new kwarg.

**Residual (do not reopen the named P0):** callers omitting `index_text` **without HTML** remain fail-closed empty, not weekend COMPLETE.

| Caller | `index_text` at `242c2484` |
|--------|----------------------------|
| `packages/data_plane/ingestion/jsda/archive.py:528-535` | fetched year-index HTML; empty fetch → `None` |
| `scripts/refresh_coverage_ledger.py` | `--index-text PATH` or omitted `None` |
| `scripts/write_collection_receipts.py` | `--index-text` / `QP_INDEX_TEXT` or omitted `None` |
| `scripts/publish_ops_projection.py` | `--otc-index-html` or omitted/`OSError`/`blank` → `None` |
| `scripts/jsda_otc_seal_official.py` | passed (local HTML or `None`) |
| `scripts/issue_receipts_parallel.py` | passed (local HTML or `None`) |
| `scripts/issue_signed_receipts_for_segments.py` | passed (local HTML or `None`) |
| `packages/data_plane/ingestion/pipeline.py:450,456,479` | passed; persist has no held HTML → `None` |
| `packages/data_plane/ops/backfill_planner.py:430,566` | **new this window** — forwarded; default `None`; JSDA skipped at `plan()` |
| `packages/data_plane/ops/range_batch_scheduler.py:463` | **omitted** (JQ dry plan; OTC skipped) |
| `scripts/ops/cf_premium_backfill.py:250-254` | **omitted** (JQ backfill; OTC skipped) |
| `packages/research_runtime/paper_runtime/snapshot_publish_policy.py:109-111` | **omitted** (jquants READY path; OTC empty if included) |

A live refresh that omits `index_text` / has no HTML would DELETE the STALE 8784 calendar rows and write **0** required (PARTIAL / empty). That is fail-closed, not a COMPLETE mint, and not a published official-index rebuild. Live MCP is still 8784 under STALE V2. Canonical inventory / `endpoint_status` still advertise `coverage_segment_granularity=official_archive_day`.

why it still matters: claiming OTC Dataset COMPLETE from this SHA would ignore STALE 8784 live inventory, PARSE_ZERO publication days, and the unpublished refresh. Completing weekend ids against the live STALE set still invents COMPLETE. Empty refresh is not Dataset COMPLETE either. Passing local HTML in tests / CLIs is not a live official-index republish. Worker-put / IR codec / premium extract / jitter do not republish the OTC required set.

structural fix (still in tree): refresh required set = official index days when `index_text` is supplied. Do not COMPLETE empty non-index days. Do not treat omitted-`index_text` empty as FRESH. Do not treat this SHA as OTC Dataset COMPLETE.

---

## IND-A-PIT-BYPASS

severity: **P0**  
status: **FIXED** (not reopened; ingest-time `available_at` residual is fail-safe, not look-ahead)  
file:line: `packages/data_plane/pit/api.py:268-303`; `packages/data_plane/pit/query.py:175-191`; `packages/product/research/eval_loaders_sidecars.py:404-427`; `packages/research_runtime/core/universe.py:15-19,32`; `packages/research_runtime/features/runtime.py:108-124`

No PIT file changes `3b64bdfc..242c2484`. Named bypasses remain gated (`get_equity_master` official clamp; eval sqlite `as_of` + `available_at <= as_of`; `fixed_universe` proof; FeatureContext official island). `pit.query.run_query` still AND-gates `available_at <= as_of`. `QP_ALLOW_FIXED_UNIVERSE=1` remains a research escape, not GO. Worker-put / IR codec / premium extract / jitter do not open a PIT read path.

---

## IND-A-FORGED-RECEIPT

severity: **P0**  
status: **FIXED** (not reopened)  
file:line: `packages/data_plane/storage/__init__.py:34`; `packages/data_plane/storage/coverage_ledger.py:365-372,1423-1432,1439`

No production change in this window re-exports `build_synthetic_complete_receipt`. COMPLETE still requires `is_complete_eligible_receipt` (Ed25519) before evaluate. Residual API hygiene (fixture object shape; `coverage_ledger` still imports the builder) is unchanged and is not a live COMPLETE mint. Worker-put `go: false` is R2 put authority, not a receipt COMPLETE mint.

---

## IND-A-FALSE-COMPLETE

severity: **P0**  
status: **FIXED** (named holes closed; genuine fins event-zero COMPLETE remains by design)  
file:line: `packages/data_plane/storage/coverage_ledger.py:127-138,330-354,357-434`; `scripts/jsda_otc_seal_official.py:50-52,138-141`; `tests/test_phase61_coverage_v2.py:126-251`

No `3b64bdfc..242c2484` change to `_empty_observed_forbids_complete`. Tip / archive-index empty SUCCESS stays PARTIAL even if `event_driven` (`:338-342`, `:397-400`). Genuine `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date` windows still COMPLETE on empty exhausted signed receipts — Coverage V2 event-zero rule, not earnings/AM monthly shells and not OTC weekends. Live `ops_status.raw_retention.complete=18301` is the raw-manifest column’s historical COMPLETE count — **not** Dataset COMPLETE. Evaluation IR generated codec field `n_complete` is a cell count — **not** Dataset COMPLETE. PARSE_ZERO days `2002-08-02` / `2002-08-05` stay PARTIAL: `PARSE_ZERO_SEAL_PROOF: dict[str, tuple[str, int]] = {}` (no in-repo digest+count). Do not invent Dataset COMPLETE 23. Do not seal PARSE_ZERO. Do not treat cron `datasetCount=23` as Coverage COMPLETE.

---

## IND-A-READY-DEPS

severity: **P0**  
status: **FIXED** (`core_v1` includes `equities_master`; not reopened)  
file:line: `specs/research_profiles/core_v1.json:5-12`; `packages/product/research/research_data_profile.py:55-66,143-201,367-382`

No `3b64bdfc..242c2484` omission of master from core. `profile_ready` still ANDs official-mode COMPLETE over Deps including master. Live evidence is STALE + master PARTIAL + `applied_cursor` null + missing V3 on non-master core datasets → predicate **false**. Live READY snapshot is **null**. Worker-put callers / IR codec / premium extract / jitter do not publish READY. This review does not publish READY.

---

## Named tree deltas (not Independent A P0)

severity: not scored as Independent A P0  
status: **landed** at `242c2484`; do not reopen named A holes  
file:line: `packages/product/research/cf_daily_path_job.py:529-535`; `packages/product/research/cf_mass_eval_run.py:40,162-165`; `packages/product/research/r2_io.py:69,213,278-313`; `packages/data_plane/ops/backfill_planner.py:4-9,408-430,508-538`; `packages/product/research/evaluation_ir_codec.generated.py:1-29`; `platform/workers/ingestion-premium/src/fetch_jq.ts:1-24`; `platform/workers/ingestion-premium/src/retry_jitter.ts:1-17`; `tests/test_immutable_artifact.py`; `tests/test_backfill_planner.py:422-537`

- Remote research artifacts POST Worker children-then-manifest. Overlay never CLI-puts. `go` stays **false**.
- BackfillPlanner `index_text` default `None` is fail-closed empty for official-index, not 8784 weekends. JSDA skipped at `plan()`.
- Python IR codec is generated from `schema.json`. `n_complete` is not Coverage COMPLETE.
- Premium fetch extract + jitter are HTTP retry presentation. They do not evaluate segments.

These are R2 put authority / planner residual tightening / codec generate / Worker HTTP extract, not a PIT bypass, not an official-domain reopen, and not READY.

---

## What this review does not claim

- Planner / PIT / profile / OTC-`index_text` / Worker-put / IR codec wires are a live Coverage remeasure. Live MCP is **STALE**; READY is **null**; B0 is **UNKNOWN**.
- Dataset COMPLETE is **23**. Last-known-good remains **22 / 4**. Cron/validation `datasetCount=23` is not Coverage COMPLETE. IR `n_complete` is not Coverage COMPLETE.
- JSDA 23-col parse = COMPLETE. Adapter is parse-only.
- Live OTC required set = official index days. Tree refresh is wired; published projection is still 8784 calendar ids.
- BackfillPlanner `index_text` rebuilt production D1. Isolation did not run live JSDA fetch or seal. JSDA remains skipped at `plan()`.
- Receipt CLIs `--index-text` rebuilt production D1. Isolation did not run live JSDA fetch or seal.
- Pipeline persist with no held HTML rebuilt the live ledger. Persist is fail-closed empty for OTC, not weekend COMPLETE, and not FRESH.
- Caller `snapshot_publish_policy` / `range_batch_scheduler` / `cf_premium_backfill` omitting `index_text` rebuilt the live ledger. They remain fail-closed empty if OTC is included, not weekend COMPLETE.
- Worker-put callers republished READY or Mass. They did not. Worker `go` is **false**.
- Premium fetch extract / jitter sealed PARSE_ZERO or minted COMPLETE. They did not.
- Ed25519 COMPLETE eligibility remains FIXED at evaluate.
- `pit.get_*` still requires `as_of` and AND-gates `available_at`.
- PARSE_ZERO `2002-08-02` / `2002-08-05` are sealed. `PARSE_ZERO_SEAL_PROOF` is empty.
- This file is not a seal, densify, floor bump, Mass ON, Phase 6.3.2 COMPLETE, or Phase 7 GO.

## Blocked / unverified

- Live MCP remeasure of 22/4 was fetched this turn and is **STALE** (`refresh_success=false`, READY **null**). Counts are last-known-good under that generation, not the wired V3 planner or an OTC index required set published from `242c2484`.
- Worker D1/R2 production receipts were not pulled. Forged-receipt FIXED is from Python evaluate remaining in tree. Raw `ACQUIRED` is from Worker source + unit tests; live `raw_retention.complete=18301` still counts historical `completeness=COMPLETE` strings.
- `BackfillPlanner.plan(index_text=...)` / remaining receipt CLIs / pipeline `index_text` were confirmed from source + unit tests at HEAD; they were not executed against a live DB in this isolation worktree (would need official index HTML / JSDA fetch / coverage sqlite).
- Production omit callers (`snapshot_publish_policy`, `range_batch_scheduler`, `cf_premium_backfill`) were not run. Omit-without-HTML empty behavior is pinned by `test_refresh_without_index_text_is_fail_closed_empty_not_calendar` and `test_planner_omitted_index_text_is_not_weekend_complete`.
- Publication-calendar `available_at` (next-business-day after 17:30 JST) is still JSON-only. Not re-audited as a look-ahead bypass.
- Discovery receipt `expected_scope` (no `segment_granularity`; `expected_item_unit=official_archive_file`) vs planner scope (`segment_granularity=official_archive_index_day`; `source_query`) remains an identity-mismatch residual: fail-closed PARTIAL, not a COMPLETE mint.
- Worker-put callers, IR codec generate, premium fetch extract, and jitter were confirmed from source + unit tests; they were not executed against a live Worker / R2 / J-Quants in this isolation worktree.
- `reconstitution_evidence.py` still calls `default_r2_put`; remote path still refuses CLI put. Not scored as Independent A P0.
