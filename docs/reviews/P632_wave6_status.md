# Phase 6.3.2 Wave-6 status — leak register vs `ed94d504` (not a GO)

**Isolation worktree:** `/private/tmp/qp-p632-wave6-status` on `grok/p632-wave6-status` (do not push `main`).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`), [`P632_wave4_status.md`](P632_wave4_status.md) (A–S freeze vs `40d1aa90`), or [`P632_wave5_status.md`](P632_wave5_status.md) (A–S freeze vs `67fcbd7c`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `ed94d504` (`ed94d5041969c3630b35c93927dcd1bb42f85c74`) — `test: missing-V3 BackfillPlanner pin does not import deleted helper`.  
**Window:** 17 commits after `67fcbd7c` (`67fcbd7cd56847a9fc0fba7bcefbd743b43fc106`). Count: `git rev-list --count 67fcbd7c..ed94d504` = **17**.  
**`origin/main`:** `b5c326a` (feature branch is **not** an ancestor of `main`; not merged).  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `ed94d504`.

**HUMAN bottleneck:** live `quant-platform-ci-aggregate` Worker **absent** (Wrangler deployments/versions **10007**; secrets “not found”; `workers.dev` `/health` HTTP **404** / error **1042**). Isolation does not deploy it.

Earlier freezes (cite, do not rewrite):

| Freeze | SHA | File |
|--------|-----|------|
| Wave-0 live remeasure | `61b773a` | [`P632_wave0_live.md`](P632_wave0_live.md) |
| Wave-1 A–S register | `3ab87d0` | [`P632_brief_leaks.md`](P632_brief_leaks.md) |
| Wave-2 after P0 code closes | `07b4435` | [`P632_wave2_status.md`](P632_wave2_status.md) |
| Wave-3 after 30 commits | `f224e7e` | [`P632_wave3_status.md`](P632_wave3_status.md) |
| Wave-4 after 20 commits | `40d1aa90` | [`P632_wave4_status.md`](P632_wave4_status.md) |
| Wave-5 after 17 commits | `67fcbd7c` | [`P632_wave5_status.md`](P632_wave5_status.md) |
| Wave-6 (this file) | `ed94d504` | this re-diff |

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN / PARTIAL**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`. Live Cloudflare is Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`).

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 184051 (~51.1h)
  active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
  projection_source_generation: 2026-08-21T12:28:33.345482+00:00
  refresh_attempt: true
  refresh_success: false
  last_known_good.not_fresh: true

B0: UNKNOWN  (snapshot quality/B0 projection is unavailable)

READY: null  (no published READY generation is bound to this Worker)

Sync: applied_feed_cursor: null
  latest_change_seq: 2890664
  CURRENT datasets: 0
  typical dataset state: LAGGING_APPLY_UNPINNED
  indices_bars_daily_topix: EXPORT_CURRENT_APPLY_UNPINNED (lag 0, pin still null → never CURRENT)

Coverage: 22 COMPLETE / 4 PARTIAL  (policy_version collection-coverage/v2)
  equities_master PARTIAL history_target_start 2006-08-13
    backfill 241 / 220 / 21  observed 2008-05-01 → 2026-08-12
  equities_bars_daily_am PARTIAL history_target_start 2024-01-04
    backfill 32 / 1 / 31  observed 2026-08-01 → 2026-08-11
  equities_earnings_calendar PARTIAL history_target_start 2010-01-04
    backfill 200 / 1 / 199  observed 2010-01-04 → 2026-08-14
  jsda_otc_bond_reference_prices PARTIAL history_target_start 2002-08-02
    backfill 8784 / 5886 / 2898  observed 2002-08-06 → 2026-08-20

Inventory: 26 governed / 5 experimental / 31
Ops last_run: id 14318 PASS (jquants, 2026-08-24T00:15:01+09:00)
Raw: manifests 20493 / complete 18278
  live ops_status.raw_retention still emits complete (no acquired key)
  tree b96d60bd adds acquired + deprecated complete alias; live Worker not that SHA
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api`, not invented):

```text
commits/ed94d504/check-runs  total_count: 0
commits/ed94d504/status      state: pending, total_count: 0
PR #1                       statusCheckRollup: [], mergeState BLOCKED
                            headRefOid: ed94d5041969c3630b35c93927dcd1bb42f85c74
Actions workflows           total_count: 0
main protection             required_status_checks.contexts=["ci-aggregate"]
                            app_id: null, strict: true, enforce_admins: true
                            allow_force_pushes: false
origin/main check-runs      total_count: 0
.git/ ls-files .github      0
```

Live Cloudflare producer (this turn; Wrangler, not invented):

```text
wrangler deployments list --name quant-platform-ci-aggregate
  GET /accounts/11233bca…/workers/scripts/quant-platform-ci-aggregate/deployments
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler versions list --name quant-platform-ci-aggregate
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler secret list --name quant-platform-ci-aggregate
  Worker "quant-platform-ci-aggregate" not found.

GET  https://quant-platform-ci-aggregate.taku-haga.workers.dev/health
  HTTP 404  error code: 1042
```

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY. Local `verify_ci` at `67fcbd7c` is **not** a posted GitHub context.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Wave-6 **tree** honesty (BackfillPlanner `plan_required_segments`, tip/index event-zero **PARTIAL**, IR encode-keys lock, OTC sealer `index_text`, ops_status `acquired` alias) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate; **ci-aggregate Worker absent**).

**HUMAN bottleneck named:** `quant-platform-ci-aggregate` Worker **absent**. Branch protection requires a context that has no producer on the account. Isolation must not deploy, bind secrets, or PAT-mint `ci-aggregate`.

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `bcd52f47` | BackfillPlanner month-chunks bounded history via `plan_required_segments` | Q §10.3.1 non-tip inventory. Bars/fins stay calendar_month jobs from required segments, not an independent calendar walk. | live MCP still V2 STALE. Jobs are pending/fail, never COMPLETE. |
| `b7ea539a` / `ed94d504` | missing V3 does not invent BackfillPlanner official domain | missing SourceCapability → `None`; coverage JSON start; evaluate without receipt **PARTIAL**. Pin does not import deleted `_official_domain_start`. | 22 governed datasets still have no V3 file. Not Dataset COMPLETE. |
| `6abfb085` | event-zero COMPLETE does not apply to tip or archive-index | `evaluate_segment` stays **PARTIAL** on empty SUCCESS for `recent_snapshot` / `next_business_day_snapshot` / `official_archive_index` even when `expected_frequency` is `event_driven`. | genuine `fins_*` event_driven windows keep event-zero COMPLETE (intended). Live READY **null**. |
| `574ff1be` | Evaluation IR encode keys locked to `schema.json` properties | delete hand-written `CANONICAL_FIELDS`. Worker encode keys must equal generated `ALLOWED_FIELDS`. `verify_ci` fails Python/Worker encode-key drift. Decode still rejects unknown fields / version ≠ `evaluation-ir/v1`. | hand-written TS codec **OPEN**. Not generated Python+TS types. |
| `2ec8f572` | OTC sealer `--index-text PATH` into coverage refresh | local HTML only. Omitted/blank → fail-closed empty, not calendar COMPLETE. Grain default `official_archive_index_day`. | does not fetch live HTML. `PARSE_ZERO_SEAL_PROOF` **empty** → `2002-08-02` / `05` stay PARTIAL. Live inventory still **8784 / 5886**. |
| `b96d60bd` | ops_status `raw_retention.acquired`; `complete` deprecated alias | canonical SUM of `ACQUIRED`\|legacy `completeness=COMPLETE`. Alias is **not** Dataset COMPLETE. | live MCP this turn still emits only `complete: 18278` (Worker not this SHA). Not a publish. |
| `caace9da` | nested SourceCapability evidence maps stay open | extra nested evidence keys do not fail load. Dataset-level unknown keys stay fail-closed. Missing V3 JSON is `None`. | nested maps remain **OPEN** by design. |
| `ba7ddff6` | fetch/upsert stay together as ingestion façade | HOLD keep-together; not an extract. | not a GO. |

This isolation did **not** re-run `scripts/verify_ci.sh` at `ed94d504`. The `67fcbd7c` local PASS ([`P632_verify_ci_67fcbd7c.md`](P632_verify_ci_67fcbd7c.md): **1444 passed / 4 skipped**) is nine commits earlier than this window’s code landings and is **not** merge-gate.

---

## The 17 commits after `67fcbd7c`

| SHA | Landing | Lane |
|-----|---------|------|
| `d3c4b2d5` | 6.3.2 P test inventory at `67fcbd7c` | docs (P) |
| `09c0bcb4` | review index names HEAD `67fcbd7c` vs `origin/main` `b5c326a` | docs |
| `ba7ddff6` | fetch/upsert stay together as ingestion façade | Q HOLD |
| `687e2ec2` | independent review A revisit at `67fcbd7c` | docs (A freeze) |
| `9adb746d` | independent review B revisit at `67fcbd7c` | docs (B freeze) |
| `bbfa1c1f` | wave-5 status after 17 commits vs `67fcbd7c` | docs (wave-5 freeze) |
| `10eb0d30` | independent review C catalog/pilot revisit at `67fcbd7c` | docs (C freeze) |
| `675a2ba9` | remaining extracts vs HOLD at `67fcbd7c` | docs (Q freeze) |
| `77133986` | P632 `verify_ci` code-lane PASS at `67fcbd7c` | docs (C; not merge-gate) |
| `b96d60bd` | ops_status `raw_retention.acquired`; `complete` deprecated alias | J / FALSE-COMPLETE |
| `caace9da` | nested SourceCapability evidence maps stay open | D |
| `6abfb085` | event-zero COMPLETE does not apply to tip or archive-index | F / G / H / FALSE-COMPLETE |
| `b7ea539a` | missing V3 does not invent BackfillPlanner official domain | D / Q |
| `574ff1be` | lock Evaluation IR encode keys to schema properties | O / C |
| `2ec8f572` | OTC sealer passes local `index_text` into coverage refresh | H |
| `bcd52f47` | BackfillPlanner month-chunks bounded history via required segments | Q / E / F / G |
| `ed94d504` | missing-V3 BackfillPlanner pin does not import deleted helper | D / Q |

Docs commits in this window (`d3c4b2d5`, `09c0bcb4`, `687e2ec2`, `9adb746d`, `bbfa1c1f`, `10eb0d30`, `675a2ba9`, `77133986`) are freezes / operator notes, not live GO. `675a2ba9` remaining-extracts freeze is authored vs `67fcbd7c` and does **not** yet name the wave-6 code closes.

---

## A–S vs `ed94d504` (after the 17)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`; [`P632_wave4_status.md`](P632_wave4_status.md) vs `40d1aa90`; [`P632_wave5_status.md`](P632_wave5_status.md) vs `67fcbd7c`. This table is the wave-6 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker **code** + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags + IR encode-key freeze in repo) / **OPEN** (live check never posted; **Worker absent**) / **HUMAN** (`quant-platform-ci-aggregate` first deploy + token bind)

| Sub-item | At `67fcbd7c` | After wave-6 |
|----------|---------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code). Live Worker **absent**. | **FIXED** (code). Live Worker **absent** — deployments **10007**, secrets not found, `/health` **404**. Named **HUMAN** bottleneck. |
| `verify_ci` covers gate Worker | **FIXED** (7th Worker + types `--check` + IR schema + `ALLOWED_FIELDS`) | **FIXED** + encode keys must match `schema.json` (`574ff1be`). Local PASS documented at `67fcbd7c`, not this SHA, not GitHub. |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`67fcbd7c` `total_count: 0`) | **OPEN** — this turn `ed94d504` `total_count: 0`; `/status` `pending` / `0`. PR #1 `statusCheckRollup: []`, **BLOCKED**. |
| Fail/pass merge smoke | **OPEN** | **OPEN** — cannot smoke a producer that does not exist |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint; nothing to bind until Worker exists |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`) / **OPEN** (clean-checkout proof at this HEAD; retry jitter still `Math.random`)

Unchanged vs wave-5 except: local `verify_ci` PASS is now **documented** at `67fcbd7c` ([`P632_verify_ci_67fcbd7c.md`](P632_verify_ci_67fcbd7c.md): 7 workers including `ci-aggregate` 13 tests; **1444 passed / 4 skipped**). That is a different SHA. Clean-checkout matrix **not** executed at `ed94d504` in this isolation. Residual `Math.random()` is retry/jitter only (`ingestion-premium` `index.ts:171,181`, `persist_records.ts:36`) — not identity (`crypto.randomUUID` still FIXED). `ba7ddff6` keeps fetch/upsert as one façade (HOLD), not a build-matrix close.

Do not invent PASS at `ed94d504`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, encode-key lock, types flags, **local PASS at `67fcbd7c`**) / **OPEN** (merge gate is live GitHub context; producer Worker **absent**)

- Authoritative: `scripts/verify_ci.sh`. `WORKERS` still includes `platform/workers/ci-aggregate`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- `574ff1be`: `assert_evaluation_ir_encode_keys_match_schema()` plus generated `ALLOWED_FIELDS` freeze. Comment still says `evaluation_ir.ts` is a **hand-written** codec; encode keys must match `schema.json` properties.
- Local PASS at `67fcbd7c`: 1444 passed / 4 skipped; wall 193.62s; `verify_ci: ok`. **Not** merge-gate. **Not** this HEAD. This isolation did not re-run the script after the 8 code landings.
- Residual: does **not** create a fresh venv (requires existing `.venv` 3.11+). Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, and that POST host **does not exist**.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed + OTC grain token + nested-open pin) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design (`caace9da`: extra nested keys do not fail load; dataset-level unknown keys fail-closed; missing V3 JSON is `None`, not invented).

Planner **does** clip through SourceCapability SoT. BackfillPlanner missing V3 does **not** invent official domain (`b7ea539a` / `ed94d504`). That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + PIT clamp + `jquants_records` island + BackfillPlanner required-segments) / **OPEN** (live STALE still V2 `2006-08-13`)

Repo official start `2008-05-07`. `bcd52f47`: non-tip jobs come from `plan_required_segments` (calendar_month), not an independent walk. Master still starts `2008-05-07` in-tree. Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13` (`backfill_status` 241 / 220 / 21). Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner + empty receipt PARTIAL + READY fixture honesty + **event-zero tip PARTIAL**) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Planner yields **1** cutoff snapshot, not 200 months. `6abfb085`: earnings is `event_driven` **and** `next_business_day_snapshot`; empty SUCCESS stays **PARTIAL** (`test_earnings_event_driven_empty_is_not_event_zero_complete`). Do not empty past months into COMPLETE. Live `backfill_status` 200 / 1 / 199.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner + empty receipt PARTIAL + **event-zero tip PARTIAL**) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. `6abfb085`: `recent_snapshot` stays PARTIAL on empty even if labeled `event_driven`. `collection_sla_status(equities_bars_daily_am)` this turn: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Live `backfill_status` 32 / 1 / 31. Do not invent AM SLA PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner + HTML index SoT + refresh wire + CLI `index_text` + JSON grain + **sealer `index_text`**) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed; some callers still omit HTML)

Wave-6 tree vs wave-5:

- `jsda_otc_seal_official --index-text PATH` (`2ec8f572`). Local HTML only. Omitted/blank → empty required set (fail-closed), **not** 8784 weekends. Grain default `official_archive_index_day`. Does **not** fetch live JSDA HTML.
- `PARSE_ZERO_SEAL_PROOF: dict[str, tuple[str, int]] = {}` — `2002-08-02` / `2002-08-05` stay **PARTIAL** without in-repo digest+count.
- `6abfb085`: official-archive-index empty SUCCESS is **PARTIAL** even if `expected_frequency` is `event_driven`.

Still omitted (fail-closed empty, not weekend COMPLETE): `scripts/issue_receipts_parallel.py:598`, `scripts/issue_signed_receipts_for_segments.py:288`.

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts + tip/index event-zero PARTIAL) / **OPEN** (live READY **null**)

Unchanged vs wave-5 live. `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

### J. Projection / sync operational closure

**status: OPEN** (live) — presentation honesty **FIXED** (do not re-open)

| Criterion | Live (this turn) |
|-----------|------------------|
| `projection_status` | **STALE** |
| `refresh_success` | **false** |
| `applied_feed_cursor` | **null** |
| CURRENT datasets | **0** |
| B0 | **UNKNOWN** |
| READY | **null** |

`applied == null` still never CURRENT. Last-known-good is **not** FRESH (`last_known_good.not_fresh: true`). `0007_ops_applied_pins` remote apply is **HUMAN**.

`b96d60bd` canonicalizes `ops_status.raw_retention.acquired` (SUM of `ACQUIRED`\|legacy `COMPLETE`); `complete` is a **deprecated alias of that sum**, not Dataset COMPLETE. Live MCP this turn still returns only `complete: 18278` — the deployed ops-mcp Worker is **not** this SHA. Tree honesty is not a publish. See [`P632_projection_stale.md`](P632_projection_stale.md) and [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo + create≠reserve pin) / **OPEN** (live Edge unproven)

Unchanged vs wave-5. Caps unchanged (`auto_promotion: false`). Live occupancy / double-spend under production traffic: **not** measured this wave. String `budget_id` is still not the reserve.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented) / **HUMAN** (secret bind)

Unchanged vs wave-5: production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN** (mass-eval `ai_gateway_client.ts` still sends `GATEWAY_TOKEN` as `X-Gateway-Token`). Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

`ci-aggregate` `workers_dev=true` is moot until the Worker exists.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + Python overlay fail-closed + Worker-client stub) / **OPEN** (no HTTP client; TOCTOU remains if overlay `=1`) / **HOLD** (overlay identity)

Unchanged vs wave-5. Worker children-then-manifest `onlyIf` remains immutable authority. `put_children_then_manifest_via_worker` still has **no HTTP client**. `QP_ALLOW_PYTHON_R2_PUT=1` is still head-then-put TOCTOU. `authoritative=True` still refused. Do not treat “stub exists” as Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n)

Unchanged vs wave-5 / Independent C at `67fcbd7c` ([`P632_ind_C_revisit_67fcbd7c.md`](P632_ind_C_revisit_67fcbd7c.md)): YAML n = **0**; compiled freeze n = **2254**; `yaml_overlay_allowed()` **False**; `go: false`. Compact `family + template + parameter matrix` **not** implemented.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS` + **encode-key lock**) / **OPEN** (hand-written TS codec remains)

`574ff1be`: delete hand-written `CANONICAL_FIELDS`. Worker `assertEncodeKeys` requires encode keys equal generated `ALLOWED_FIELDS` (schema properties). Python `assert_evaluation_ir_encode_keys_match_schema`. Decode still uses generated set; rejects unknown fields and `version !== evaluation-ir/v1`. Encode still calls `jobCandidateGrade`.

Worker `evaluation_ir.ts` is still a **hand-written** TS codec (does not load a JSON Schema engine). Brief asked generated Python+TS types. **Not** done.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + collect freezes + digest identity + READY fixture honesty + event-zero tip/index pins)

See [`P632_test_inventory.md`](P632_test_inventory.md) (`3ab87d0`, collected **1353**), [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (`07b4435`, **1379**), [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md) (**1426**), [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md) (**1448** collected; `tests/test_*.py` **148**; Worker first-party **20**; YAML **0**). Local `verify_ci` at `67fcbd7c` reported **1444 passed, 4 skipped**.

This HEAD `git ls-files tests/test_*.py` = **149**. Worker first-party test files still **20**. This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`. Count growth is not a consolidation win.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is still authored vs `67fcbd7c` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md); `675a2ba9`). Wave-6 landings vs that freeze:

| §10.3 later | At `67fcbd7c` | After wave-6 |
|-------------|---------------|--------------|
| 1 BackfillPlanner vs `plan_required_segments` | PARTIAL (tip snapshots + OTC refresh + `index_text` CLIs; **remaining:** bounded-history month chunks) | **PARTIAL** — non-tip now consumes `plan_required_segments` (`bcd52f47`); missing V3 does not invent official domain (`b7ea539a`). Month-chunks remain ops dispatch of required `calendar_month` grains, not an independent walk. Live MCP still V2 STALE. |
| 2 Python `r2_io.py` TOCTOU | PARTIAL (Worker-client stub; no HTTP; overlay TOCTOU if `=1`) | **PARTIAL** — unchanged |
| 3 hand-written `evaluation_ir.ts` | PARTIAL (`ALLOWED_FIELDS` generated; codec hand-written) | **PARTIAL** — encode keys locked to schema (`574ff1be`); codec still hand-written; generated TS types **OPEN** |
| 4 MCP frozen “Coverage V2” strings | FIXED (Worker + Python echo stored `policy_version`) | **FIXED** + `raw_retention.acquired` / deprecated `complete` alias (`b96d60bd`). Live MCP still emits `complete` only. |
| 5 `verify_all` vs `verify_ci` | HOLD (keep both) | **HOLD** (local PASS at `67fcbd7c` is not merge-gate; encode-key freeze added) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. `ba7ddff6` keeps fetch/upsert as ingestion façade (HOLD keep-together). Coverage V2 JSON vs V3 contracts: planner + OTC grain + `index_text` CLIs + sealer + BackfillPlanner required-segments wired for 4 datasets; live MCP still V2 STALE.

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Independent C at `67fcbd7c`: catalog/pilot P0 unresolved **0** (no live arming); that is not Phase 7 GO.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `67fcbd7c` (wave-5) | After wave-6 (`ed94d504`) |
|----|------------------------|---------------------------|
| IND-A-DOMAIN | **FIXED**. Live STALE still V2 `2006-08-13`. | **FIXED** (not reopened). BackfillPlanner required-segments + missing-V3 fail-closed. Live still STALE. |
| IND-A-JSDA-PHANTOM | **FIXED** (tree) + CLI/`archive.py` `index_text` + grain token. Live still **8784 / 5886**. | **FIXED** (tree) + sealer `index_text` (`2ec8f572`). Live still **8784 / 5886**. PARSE_ZERO stays gap. |
| IND-A-PIT-BYPASS | **FIXED** | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** — READY fixture tip receipts FIXED; genuine `event_driven` event-zero COMPLETE remains | **PARTIAL** → tip/index empty SUCCESS **PARTIAL** (`6abfb085`). Genuine `fins_*` event-zero COMPLETE **remains intended** (`test_event_zero_successful_exhausted_raw_receipt_is_complete`). ops_status `acquired` alias **FIXED** in tree; live MCP still `complete`. |
| IND-A-READY-DEPS | **FIXED**. Live READY **null**. | **FIXED**. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** — local PASS at `40d1aa90`; live merge gate is GitHub `ci-aggregate` never posted; producer Worker **absent** | **PARTIAL** — local PASS at `67fcbd7c` documented; encode-key freeze; live merge gate still not `verify_ci`; producer Worker **absent** |
| P632B-02 live `ci-aggregate` posted | **OPEN** — Worker **absent** (10007). **HUMAN** create. Check-runs **0**. | **OPEN** — Worker **absent** (10007). **HUMAN** create. Check-runs still **0**. |
| P632B-03 `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | **OPEN** (mass-eval still sends `GATEWAY_TOKEN`) | **OPEN** (empty diff on that path) |
| P632B-05 Python R2 TOCTOU | **PARTIAL** — Worker stub fail-closed without HTTP; overlay `=1` still TOCTOU | **PARTIAL** — unchanged |
| C-YAML load overlay | **FIXED**. +N **HOLD**. Independent C P0 unresolved **0** (no live arming). | **FIXED**. +N **HOLD**. |

Independent P0 unresolved ≠ 0 (live CI never posted; **ci-aggregate Worker absent**). `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree JSDA sealer / BackfillPlanner / event-zero tip-index close is not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker **absent** (10007); live check-runs **0**. HUMAN deploy. |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); local PASS at `67fcbd7c` **FIXED** (docs); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed; OTC grain token **FIXED** |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh + `index_text` CLIs + grain + sealer + BackfillPlanner required-segments; live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; fixture tip receipts; tip/index event-zero PARTIAL; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code + create≠reserve pin) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; Python overlay fail-closed **PARTIAL**; Worker stub **PARTIAL** (no HTTP); TOCTOU if overlay **OPEN** |
| AI_Gateway_Typed | **FIXED** (6.3.1; still true) |
| PaperExecution_Authoritative | not re-opened; Mass/paper still unarmed |
| IndependentReview_P0_Zero | **OPEN** |

## 6.4 live (not invented)

| Criterion | Live |
|-----------|------|
| governed Coverage COMPLETE (official mode) | **NO** — 22 held / **4 PARTIAL** last-known under STALE V2 |
| projection FRESH | **STALE** |
| B0 PASS | **UNKNOWN** |
| applied sync generation pinned/current | **unpinned** (`applied_feed_cursor=null`) |
| immutable READY ≥ 1 | **null** |
| AM SLA live evidence | **PROJECTION_STALE** — not PASS |

---

## Human actions (not agent)

1. **Bottleneck:** create `quant-platform-ci-aggregate` on account `11233bca08d134a9b738eaa46b9751d9`. Bind `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. Isolation worktree does **not** do that. Do not PAT-mint the required context.
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`, passing official-index HTML (`--otc-index-html` / `--index-text`). Tree honesty is not a publish. Live still **8784 / 5886**. Redeploy ops-mcp if `raw_retention.acquired` should be live.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts from a **deployed** Worker.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), [`P632_wave3_status.md`](P632_wave3_status.md), [`P632_wave4_status.md`](P632_wave4_status.md), or [`P632_wave5_status.md`](P632_wave5_status.md).
- A live Coverage remeasure. Planner, sealer, BackfillPlanner, and `index_text` CLIs are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `ed94d504`. Local PASS at `67fcbd7c` is not this SHA and is not merge-gate.
- A deploy of `quant-platform-ci-aggregate`. The Worker is **absent**. That is the HUMAN bottleneck.

Wave-6 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
