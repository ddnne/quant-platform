# Phase 6.3.2 Wave-9 status — leak register vs current HEAD (not a GO)

**Isolation worktree:** `/Users/taku/tmp/qp-p632-wave9-status` on `grok/p632-wave9-status` (do not push `main`).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`), [`P632_wave4_status.md`](P632_wave4_status.md) (A–S freeze vs `40d1aa90`), [`P632_wave5_status.md`](P632_wave5_status.md) (A–S freeze vs `67fcbd7c`), [`P632_wave6_status.md`](P632_wave6_status.md) (A–S freeze vs `ed94d504`), [`P632_wave7_status.md`](P632_wave7_status.md) (A–S freeze vs `5103b26b`), or [`P632_wave8_status.md`](P632_wave8_status.md) (A–S freeze vs `3b64bdfc`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `242c2484` (`242c2484e9307f9163b13fc603ad90f67c6a0919`) — `docs: §10 remaining mixed at c9764ff4 after python IR codec`.  
**Window:** 18 commits after `3b64bdfc` (`3b64bdfc9a41be76a6e4e881aaea1ff9751443ed`). Count: `git rev-list --count 3b64bdfc..242c2484` = **18**.  
**`origin/main`:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`) — feature branch is **not** an ancestor of `main`; **not merged**. `main` is an ancestor of this HEAD.  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `242c2484`.

**HUMAN bottleneck:** live `quant-platform-ci-aggregate` Worker **absent** (Wrangler deployments/versions **10007**; secrets “not found”; `workers.dev` `/health` HTTP **404** / error **1042**). Print-only `scripts/ci_aggregate_first_deploy.sh` does **not** create it. Isolation does not deploy it. **ci-aggregate create remains the bottleneck.**

Earlier freezes (cite, do not rewrite):

| Freeze | SHA | File |
|--------|-----|------|
| Wave-0 live remeasure | `61b773a` | [`P632_wave0_live.md`](P632_wave0_live.md) |
| Wave-1 A–S register | `3ab87d0` | [`P632_brief_leaks.md`](P632_brief_leaks.md) |
| Wave-2 after P0 code closes | `07b4435` | [`P632_wave2_status.md`](P632_wave2_status.md) |
| Wave-3 after 30 commits | `f224e7e` | [`P632_wave3_status.md`](P632_wave3_status.md) |
| Wave-4 after 20 commits | `40d1aa90` | [`P632_wave4_status.md`](P632_wave4_status.md) |
| Wave-5 after 17 commits | `67fcbd7c` | [`P632_wave5_status.md`](P632_wave5_status.md) |
| Wave-6 after 17 commits | `ed94d504` | [`P632_wave6_status.md`](P632_wave6_status.md) |
| Wave-7 after 17 commits | `5103b26b` | [`P632_wave7_status.md`](P632_wave7_status.md) |
| Wave-8 after 16 commits | `3b64bdfc` | [`P632_wave8_status.md`](P632_wave8_status.md) |
| Wave-9 (this file) | `242c2484` | this re-diff |

Status vocabulary: **OPEN / FIXED / PARTIAL / HOLD / HUMAN**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`. Live Cloudflare is Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`).

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 187020 (~52.0h)
  active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
  projection_source_generation: 2026-08-21T12:28:33.345482+00:00
  refresh_attempt: true
  refresh_success: false
  last_known_good.not_fresh: true

B0: UNKNOWN  (snapshot quality/B0 projection is unavailable)

READY: null  (no published READY generation is bound to this Worker)

Sync: applied_feed_cursor: null
  latest_change_seq: 2890669
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
Ops last_run: id 14319 PASS (jquants, 2026-08-24T01:15:01+09:00)
Raw: manifests 20516 / complete 18301
  live ops_status.raw_retention still emits complete (no acquired key)
  live Worker is not this SHA
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api` / `gh pr view`, not invented):

```text
commits/242c2484/check-runs  total_count: 0
commits/242c2484/status      state: pending, total_count: 0
PR #1                       mergeable: MERGEABLE
                            mergeStateStatus: BLOCKED
                            statusCheckRollup: []
                            headRefOid: 242c2484e9307f9163b13fc603ad90f67c6a0919
                            baseRefOid: b5c326a7f612563f2da4a84f08063a307ec38e0a
Actions workflows           total_count: 0
main protection             required_status_checks.contexts=["ci-aggregate"]
                            app_id: null, strict: true, enforce_admins: true
                            allow_force_pushes: false
origin/main check-runs      total_count: 0
.git/ ls-files .github      0
```

Live Cloudflare producer (this turn; Wrangler 4.125.0, not invented):

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

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY. Local `verify_ci` at `3b64bdfc` is **not** a posted GitHub context. Print-only first-deploy is **not** a producer. Same generation as wave-8 (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 185866 → 187020. Floors and 4-PARTIAL set are unchanged.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Wave-9 **tree** honesty (Worker-put remaining job artifacts, BackfillPlanner `index_text`, premium jitter `getRandomValues`, fetch extract, python IR codec, GATEWAY HOLD pointer, independent A–C revisits) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate; **ci-aggregate Worker absent**).

**HUMAN bottleneck named:** `quant-platform-ci-aggregate` Worker **absent**. Branch protection requires a context that has no producer on the account. Isolation must not deploy, bind secrets, or PAT-mint `ci-aggregate`. `scripts/ci_aggregate_first_deploy.sh` prints operator commands and refuses `--apply` without `CONFIRM_CI_AGGREGATE_CREATE=1`; even then it is still print-only. **ci-aggregate create remains the bottleneck.**

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `017a43c6` | daily-path both-track artifact uses Worker put | `cf_daily_path_job` remote put is `put_research_artifact` (Worker children-then-manifest). Wave-8 named this as a remaining `default_r2_put` caller. | Live mass-eval POST unproven. Overlay helper still exists (**HOLD**). |
| `0a8ced34` | mass-eval-run fallback artifacts use Worker put | `put_local_fallback_artifacts` defaults to `put_research_artifact`. Wave-8 named this as the other remaining remote `default_r2_put` caller. | Live POST unproven. `reconstitution_evidence` still `default_r2_put` dry-run-only. |
| `2cbd894d` | BackfillPlanner passes `index_text` into required segments | `plan()` / `_jobs_from_required_segments` forward `index_text` into `plan_required_segments`. Omitted/blank is fail-closed empty official-index days, not a calendar-weekend COMPLETE. Wave-8 named “BackfillPlanner still has no `index_text`”. | Live MCP still V2 STALE **8784 / 5886**. PARSE_ZERO stays empty. Not Dataset COMPLETE. |
| `82ef0f7b` | premium retry jitter uses `crypto.getRandomValues` | Residual `Math.random` on retry/jitter in `ingestion-premium` `index.ts` / `persist_records.ts` is gone. `retry_jitter.ts` is the SoT. Identity stays `crypto.randomUUID`. | Not merge-gate. Not a posted `ci-aggregate`. Clean-checkout matrix at this HEAD **not** run. |
| `a20d14d4` | extract premium JQ fetch/retry from index | Fetch/retry lives in `fetch_jq.ts` (297). `index.ts` is the ingest façade (678). Jitter import stays `retry_jitter.ts`. | Façade handlers remain. Not a live ingest GO. |
| `c9764ff4` | emit Evaluation IR python codec from schema.json | `evaluation_ir_codec.generated.py` (184) is encode/decode SoT. Façade loads it. `verify_ci` freeze-calls `assert_evaluation_ir_codec_py_frozen()`. Wave-8 named Python encode/decode still hand-written. | TypedDict/`EvaluationIR` dataclass still hand-written. Worker decode still not a JSON Schema engine. Not merge-gate. |
| `7221c588` | GATEWAY_TOKEN service-binding residual remains HOLD | Independent B P632B-03 **HOLD** pointer: mass-eval still sends `GATEWAY_TOKEN` as `X-Gateway-Token`. No production auth change. | Dual bearer **OPEN**. Not a secret bind. Empty diff on `ai_gateway_client.ts` vs `3b64bdfc`. |
| independent revisits | A at `3b64bdfc`; B at `3b64bdfc`; C at `0a8ced34` | Operator notes. A tree P0 = 0; B live P0 = 2; C catalog/pilot P0 = 0 (not Phase 7 GO). | Not live GO. A/B freeze SHAs are `3b64bdfc`, before Worker-put / planner `index_text` / jitter / fetch / python codec. C freeze SHA is `0a8ced34`; catalog identity is an empty diff `0a8ced34..242c2484`. |

This isolation did **not** re-run `scripts/verify_ci.sh` at `242c2484`. The `3b64bdfc` local PASS ([`P632_verify_ci_3b64bdfc.md`](P632_verify_ci_3b64bdfc.md): **1499 passed / 4 skipped**) is the wave-8 reviewed SHA, not this HEAD, and is **not** merge-gate. Prior `5103b26b` PASS (**1492 passed / 4 skipped**) is still not this SHA.

---

## The 18 commits after `3b64bdfc`

| SHA | Landing | Lane |
|-----|---------|------|
| `017a43c6` | daily-path both-track artifact uses Worker put | M / Q |
| `0a8ced34` | mass-eval-run fallback artifacts use Worker put | M / Q |
| `2cbd894d` | BackfillPlanner passes `index_text` into required segments | H / Q |
| `82ef0f7b` | premium retry jitter uses `crypto.getRandomValues` | B |
| `a20d14d4` | extract premium JQ fetch/retry from index | Q |
| `7221c588` | GATEWAY_TOKEN service-binding residual remains HOLD | L / P632B-03 HOLD |
| `247d32a4` | independent review A revisit at `3b64bdfc` | docs (A freeze) |
| `36397dc9` | independent review B revisit at `3b64bdfc` | docs (B freeze) |
| `07f98f40` | independent review C catalog/pilot revisit at `0a8ced34` | docs (C freeze) |
| `0ee4716b` | wave-8 status after commits vs `5103b26b` | docs (wave-8 freeze) |
| `5863d559` | 6.3.2 P test inventory at `3b64bdfc` | docs (P) |
| `9107d776` | P632 `verify_ci` code-lane result at `3b64bdfc` | docs (C; not merge-gate) |
| `505051a2` | banner original-plan-gap register still holds at `0a8ced34` | docs |
| `afbbb8cd` | residual SoT banner HEAD `0a8ced34` vs `origin/main` `b5c326a` | docs |
| `d123c37a` | §10.3 mixed authority remaining at `0a8ced34` | docs (Q freeze) |
| `e39edde8` | review index names HEAD `0a8ced34` vs `origin/main` `b5c326a` | docs |
| `c9764ff4` | emit Evaluation IR python codec from schema.json | O / C |
| `242c2484` | §10 remaining mixed at `c9764ff4` after python IR codec | docs (Q freeze) |

Docs commits in this window (`7221c588`, `247d32a4`, `36397dc9`, `07f98f40`, `0ee4716b`, `5863d559`, `9107d776`, `505051a2`, `afbbb8cd`, `d123c37a`, `e39edde8`, `242c2484`) are freezes / operator notes, not live GO. Independent A/B revisits are authored vs `3b64bdfc` and do **not** yet name Worker-put / planner `index_text` / jitter / fetch extract / python IR codec. Independent C is authored vs `0a8ced34` (Worker-put in; python codec not yet). `d123c37a` remaining-extracts freeze is authored vs `0a8ced34`; `242c2484` rebases that freeze onto `c9764ff4`.

---

## A–S vs `242c2484` (after the 18)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`; [`P632_wave4_status.md`](P632_wave4_status.md) vs `40d1aa90`; [`P632_wave5_status.md`](P632_wave5_status.md) vs `67fcbd7c`; [`P632_wave6_status.md`](P632_wave6_status.md) vs `ed94d504`; [`P632_wave7_status.md`](P632_wave7_status.md) vs `5103b26b`; [`P632_wave8_status.md`](P632_wave8_status.md) vs `3b64bdfc`. This table is the wave-9 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker **code** + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags + IR codec freeze + freeze-**call** pin + python codec freeze + print-only first-deploy helper named in operator map) / **OPEN** (live check never posted; **Worker absent**) / **HUMAN** (`quant-platform-ci-aggregate` first deploy + token bind)

| Sub-item | At `3b64bdfc` (wave-8) | After wave-9 |
|----------|------------------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code) + helper named. Live Worker **absent**. | **FIXED** (code; empty diff). Live Worker **absent** — deployments **10007**, secrets not found, `/health` **404**. Named **HUMAN** bottleneck. Helper does not wrangler deploy. |
| `verify_ci` covers gate Worker | **FIXED** + freeze-**call** pin. Local PASS documented at `5103b26b`, not `3b64bdfc`. | **FIXED** + python codec freeze (`c9764ff4` `assert_evaluation_ir_codec_py_frozen()`). Local PASS now documented at `3b64bdfc` ([`P632_verify_ci_3b64bdfc.md`](P632_verify_ci_3b64bdfc.md)), not this HEAD, not GitHub. |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`3b64bdfc` `total_count: 0`) | **OPEN** — this turn `242c2484` `total_count: 0`; `/status` `pending` / `0`. PR #1 `MERGEABLE` / `BLOCKED`; `statusCheckRollup: []`. |
| Fail/pass merge smoke | **OPEN** | **OPEN** — cannot smoke a producer that does not exist |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint; nothing to bind until Worker exists; helper never puts secret values |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`; retry jitter `crypto.getRandomValues`) / **OPEN** (clean-checkout proof at this HEAD)

Wave-8 residual `Math.random()` on retry/jitter (`ingestion-premium` `index.ts:171,181`, `persist_records.ts:36`) is **FIXED** in tree (`82ef0f7b`; `retry_jitter.ts` uses `crypto.getRandomValues`). Identity stays `crypto.randomUUID` (not reopened). Production `Math.random` greps under `platform/workers` are comments/tests only.

Local `verify_ci` PASS is now **documented** at `3b64bdfc` ([`P632_verify_ci_3b64bdfc.md`](P632_verify_ci_3b64bdfc.md): 7 workers including `ci-aggregate` 13 tests; **1499 passed / 4 skipped**). That is a different SHA than this HEAD. Clean-checkout matrix **not** executed at `242c2484` in this isolation.

Do not invent PASS at `242c2484`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, encode-key lock, generated TS codec freeze, freeze-**call** pin, generated Python codec freeze, types flags, **local PASS at `3b64bdfc`**, print-only first-deploy helper named) / **OPEN** (merge gate is live GitHub context; producer Worker **absent**)

- Authoritative: `scripts/verify_ci.sh`. `WORKERS` still includes `platform/workers/ci-aggregate`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- `c9764ff4`: `verify_ci.sh` now invokes `assert_evaluation_ir_codec_py_frozen()` next to the TS freeze calls. Tests pin the invocation.
- Local PASS at `3b64bdfc`: 1499 passed / 4 skipped; wall 206.65s; `verify_ci: ok`. **Not** merge-gate. **Not** this HEAD. This isolation did not re-run the script after the wave-9 code landings (`017a43c6`, `0a8ced34`, `2cbd894d`, `82ef0f7b`, `a20d14d4`, `c9764ff4`).
- Print-only operator helper still does **not** create a fresh venv (requires existing `.venv` 3.11+). Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, and that POST host **does not exist**.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed + OTC grain token + nested-open pin) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design. Missing V3 JSON is `None`, not invented.

Planner **does** clip through SourceCapability SoT. That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors. Empty diff vs wave-8 on the four files.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + PIT clamp + `jquants_records` island + BackfillPlanner required-segments) / **OPEN** (live STALE still V2 `2006-08-13`)

Repo official start `2008-05-07`. Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13` (`backfill_status` 241 / 220 / 21). Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner + empty receipt PARTIAL + READY fixture honesty + event-zero tip PARTIAL) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Planner yields **1** cutoff snapshot, not 200 months. Do not empty past months into COMPLETE. Live `backfill_status` 200 / 1 / 199.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner + empty receipt PARTIAL + event-zero tip PARTIAL) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. `collection_sla_status(equities_bars_daily_am)` this turn: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Live `backfill_status` 32 / 1 / 31. Do not invent AM SLA PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner + HTML index SoT + refresh wire + CLI `index_text` + JSON grain + sealer `index_text` + `issue_*` `--index-text` + pipeline held HTML + **BackfillPlanner `index_text`**) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

Wave-9 vs wave-8: `2cbd894d` forwards `index_text` through BackfillPlanner into `plan_required_segments`. Omitted/blank is fail-closed empty official-index days, not a calendar-weekend COMPLETE. Tests pin the default `None` and the OTC-omit-is-not-weekend-COMPLETE case.

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration.

- `PARSE_ZERO_SEAL_PROOF` stays empty — `2002-08-02` / `2002-08-05` stay **PARTIAL** without in-repo digest+count.

Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts + tip/index event-zero PARTIAL) / **OPEN** (live READY **null**)

Unchanged vs wave-8 live. `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

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

Live MCP this turn still returns only `complete: 18301` on `ops_status.raw_retention` — the deployed ops-mcp Worker is **not** this SHA. Tree honesty is not a publish. See [`P632_projection_stale.md`](P632_projection_stale.md) and [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo + create≠reserve pin) / **OPEN** (live Edge unproven)

Unchanged vs wave-8. Caps unchanged (`auto_promotion: false`). Live occupancy / double-spend under production traffic: **not** measured this wave. String `budget_id` is still not the reserve.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented; GATEWAY service-binding residual) / **HUMAN** (secret bind)

Unchanged vs wave-8 production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN** / **HOLD** (`7221c588`; mass-eval `ai_gateway_client.ts` still sends `GATEWAY_TOKEN` as `X-Gateway-Token`; empty diff vs `3b64bdfc`). Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

`ci-aggregate` `workers_dev=true` is moot until the Worker exists. Unbound mass-eval token on children-then-manifest stays **503**; that is fail-closed, not a secret bind.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + overlay never CLI-put + Worker POST client + research-artifact POST + unbound token 503 + daily-path Worker put + mass-eval-run Worker put) / **OPEN** (live POST unproven) / **HOLD** (overlay identity helper still exists; reconstitution dry-run still `default_r2_put`)

Wave-9 vs wave-8:

- `017a43c6`: `cf_daily_path_job` both-track artifact uses `put_research_artifact` (Worker POST). Wave-8 remaining remote `default_r2_put` caller is gone.
- `0a8ced34`: `cf_mass_eval_run.put_local_fallback_artifacts` defaults to `put_research_artifact`. Wave-8 remaining remote `default_r2_put` caller is gone.

Remaining `default_r2_put` production caller: `reconstitution_evidence` dry-run-only (`default_r2_put(..., dry_run=True)`). `put_research_artifact` still stages locally via `default_r2_put` when `dry_run=True`. `python_r2_put_allowed()` still exists and is still `=1`-only; it is **not** consulted by `default_r2_put`. Overlay identity **HOLD**.

Do not treat “HTTP client exists” or “CLI put deleted” as live Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases + leftover occupancy HOLD **pointer**) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n / leftover occupancy)

Independent C at `0a8ced34` ([`P632_ind_C_revisit_0a8ced34.md`](P632_ind_C_revisit_0a8ced34.md)): YAML n = **0**; compiled freeze n = **2254**; `yaml_overlay_allowed()` **False**; `go: false`. Compact `family + template + parameter matrix` **not** implemented. Catalog identity is an empty diff `0a8ced34..242c2484`.

unique22 leftover still **22** (17 parked + 5 occupancy-equal lifts). Leftover occupancy HOLD pointer (`046ae438`) unchanged. Do not unify with `comboEventGateOk`. Do not extract.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS` + encode-key lock + generated TS codec body + freeze-**call** pin + **generated Python codec body**) / **OPEN** (TypedDict/`EvaluationIR` dataclass still hand-written; TS decode does not load a JSON Schema engine)

`c9764ff4` emits `evaluation_ir_codec.generated.py` (184) from `schema.json`. Façade `evaluation_ir.py` (1224) loads encode/decode from that artifact (`encode_evaluation_ir = _CODEC_PY.encode_evaluation_ir`). `verify_ci` freeze-checks the generated Python body. Encode object keys remain schema properties; grade remains `jobCandidateGrade` / `job_candidate_grade`. Unknown fields still fail; version stays `evaluation-ir/v1`.

Wave-8 named Python encode/decode still hand-written (1076). That body is now generated. Façade still owns schema load, TS/Python emitters, freeze checks, and the hand-written `EvaluationIR` dataclass. Decode on the Worker still uses generated `ALLOWED_FIELDS`, not a JSON Schema engine. Façade `evaluation_ir.ts` (39); generated TS codec (239).

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + collect freezes + digest identity + READY fixture honesty + event-zero tip/index pins)

See [`P632_test_inventory.md`](P632_test_inventory.md) (`3ab87d0`, collected **1353**), [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (`07b4435`, **1379**), [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md) (**1426**), [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md) (**1448**), [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md) (**1470**), [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md) (**1496**), [`P632_test_inventory_3b64bdfc.md`](P632_test_inventory_3b64bdfc.md) (**1503** collected; `tests/test_*.py` **153**; Worker first-party **20**; YAML **0**). Local `verify_ci` at `3b64bdfc` reported **1499 passed, 4 skipped**.

This HEAD `git ls-files tests/test_*.py` = **153** (unchanged file count vs `3b64bdfc`). Worker first-party test files now **22** (`fetch_jq.test.ts`, `retry_jitter.test.ts` added). Wave-9 grew existing Python modules (`test_backfill_planner.py`, `test_evaluation_ir.py`, `test_immutable_artifact.py`, `test_verify_ci_script.py`). This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`. Count growth is not a consolidation win.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is authored vs `c9764ff4` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md); `242c2484`). Prior freeze `d123c37a` was vs `0a8ced34`. Wave-9 landings vs the wave-8 remaining-extracts freeze (`6447a3fa` vs `5103b26b`, plus wave-8 tree closes):

| §10.3 later | At `3b64bdfc` (wave-8) | After wave-9 |
|-------------|------------------------|--------------|
| 1 BackfillPlanner vs `plan_required_segments` | **DONE** (JQ jobs from required segments; pipeline held OTC HTML; `issue_*` `--index-text`). BackfillPlanner still had no `index_text`. | **DONE** — BackfillPlanner `index_text` (`2cbd894d`). Live MCP still V2 STALE. |
| 2 Python `r2_io.py` TOCTOU | **PARTIAL** — overlay never CLI-put; research artifacts POST; unbound token 503. Remaining remote `default_r2_put` callers: `cf_daily_path_job`, `cf_mass_eval_run`. Overlay helper **HOLD**. `r2_io.py` **431**. | **PARTIAL** — `cf_daily_path_job` Worker put (`017a43c6`); `cf_mass_eval_run` Worker put (`0a8ced34`). Remaining `default_r2_put` caller: `reconstitution_evidence` dry_run only. Overlay helper still exists (**HOLD**). `r2_io.py` still **431**. Live POST unproven. |
| 3 hand-written `evaluation_ir.ts` | **PARTIAL** — freeze-**call** pin; Python encode/decode still hand-written (1076) | **PARTIAL** — Python codec body generated (`c9764ff4`, 184). Façade `evaluation_ir.py` 1224. TypedDict/`EvaluationIR` dataclass still hand-written. TS decode still not a JSON Schema engine. |
| 4 MCP frozen “Coverage V2” strings | **FIXED** (not reopened). Live MCP still emits `complete` only. | **FIXED** (not reopened). Live MCP still emits `complete` only. |
| 5 `verify_all` vs `verify_ci` | **HOLD** (local PASS at `5103b26b` is not merge-gate) | **HOLD** (local PASS at `3b64bdfc` is not merge-gate; python codec freeze added; print-only first-deploy still does not create the producer) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. Coverage V2 JSON vs V3 contracts: planner + OTC grain + `index_text` CLIs + sealer + pipeline held HTML + `issue_*` + BackfillPlanner `index_text` wired for 4 datasets; live MCP still V2 STALE.

Premium fetch/retry extract **DONE** (`a20d14d4`; `fetch_jq.ts` 297; `index.ts` façade 678). Retry jitter extract **DONE** (`82ef0f7b`; `retry_jitter.ts`). GATEWAY residual stays **HOLD** (`7221c588`).

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply. Reconstitution evidence stays dry-run-only (`default_r2_put` local stage). Empty diff vs `3b64bdfc` on `reconstitution_evidence.py`.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Independent C at `0a8ced34`: catalog/pilot P0 unresolved **0** (no live arming); that is not Phase 7 GO. Catalog identity empty vs this HEAD.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `3b64bdfc` (wave-8) | After wave-9 (`242c2484`) |
|----|------------------------|---------------------------|
| IND-A-DOMAIN | **FIXED**. Live STALE still V2 `2006-08-13`. | **FIXED** (not reopened). Live still STALE. |
| IND-A-JSDA-PHANTOM | **FIXED** (tree) + `issue_*` `--index-text` + pipeline held HTML. Live still **8784 / 5886**. PARSE_ZERO stays gap. BackfillPlanner had no `index_text`. | **FIXED** (tree) + BackfillPlanner `index_text` (`2cbd894d`). Live still **8784 / 5886**. PARSE_ZERO stays gap. Independent A freeze file is still vs `3b64bdfc`. |
| IND-A-PIT-BYPASS | **FIXED** | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** — JQ-without-`index_text` is not OTC weekend COMPLETE. Genuine `fins_*` event-zero COMPLETE **remains intended**. Live MCP still `complete`. | **PARTIAL** (planner now forwards `index_text`; omit still not weekend COMPLETE). Live MCP still `complete`. |
| IND-A-READY-DEPS | **FIXED**. Live READY **null**. | **FIXED**. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** — local PASS at `5103b26b`; freeze-**call** pin; live merge gate still not `verify_ci`; producer Worker **absent** | **PARTIAL** — local PASS at `3b64bdfc` documented; python codec freeze; live merge gate still not `verify_ci`; producer Worker **absent** |
| P632B-02 live `ci-aggregate` posted | **OPEN** — Worker **absent** (10007). Print-only helper is not a create. **HUMAN** create. Check-runs **0**. | **OPEN** — Worker **absent** (10007). Helper still print-only. **HUMAN** create. Check-runs still **0**. |
| P632B-03 `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | **OPEN** (mass-eval still sends `GATEWAY_TOKEN`) | **OPEN** / **HOLD** (`7221c588` pointer; empty diff on `ai_gateway_client.ts`). Unbound mass-eval token on children-then-manifest stays **503**. |
| P632B-05 Python R2 TOCTOU | **PARTIAL** — overlay never CLI-put (**FIXED** tree); research artifacts POST; unbound 503. Live POST unproven. Remaining remote `default_r2_put` callers fail-closed. Overlay helper **HOLD**. | **PARTIAL** — daily-path + mass-eval-run Worker put. Remaining `default_r2_put` caller: reconstitution dry_run only. Live POST unproven. Overlay helper **HOLD**. |
| C-YAML load overlay | **FIXED**. +N **HOLD**. Independent C P0 unresolved **0** (no live arming). Leftover occupancy HOLD pointer. | **FIXED**. +N **HOLD**. Independent C freeze now at `0a8ced34` (P0 unresolved **0**; not Phase 7 GO). Catalog identity empty vs this HEAD. |

Independent P0 unresolved ≠ 0 (live CI never posted; **ci-aggregate Worker absent**). Independent A tree P0 = 0. Independent B live P0 = **2**. Independent C catalog/pilot P0 = 0. `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree Worker-put / planner `index_text` / jitter / fetch extract / python IR codec is not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker **absent** (10007); live check-runs **0**. Print-only helper. HUMAN deploy. Conjunction **fails**. |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); retry jitter `getRandomValues` **FIXED** (tree); local PASS at `3b64bdfc` **FIXED** (docs); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed; OTC grain token **FIXED** |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh + `index_text` CLIs + grain + sealer + pipeline held HTML + `issue_*` + BackfillPlanner `index_text`; live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; fixture tip receipts; tip/index event-zero PARTIAL; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code + create≠reserve pin) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; overlay never CLI-put **FIXED** (tree); Worker POST client **PARTIAL** (live unproven); daily-path + mass-eval-run Worker put **FIXED** (tree); reconstitution dry_run `default_r2_put` **HOLD** |
| AI_Gateway_Typed | **FIXED** (6.3.1; still true). Dual `GATEWAY_TOKEN` on service-binding **HOLD** (`7221c588`) |
| PaperExecution_Authoritative | not re-opened; Mass/paper still unarmed |
| IndependentReview_P0_Zero | **OPEN** |

Brief §8 `Pilot_GO` is a conjunction. Live legs still fail. Do not invent GO.

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

1. **Bottleneck:** create `quant-platform-ci-aggregate` on account `11233bca08d134a9b738eaa46b9751d9`. Bind `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. `scripts/ci_aggregate_first_deploy.sh` is print-only; Isolation worktree does **not** do that. Do not PAT-mint the required context. **ci-aggregate create remains the bottleneck.**
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values. Unbound mass-eval token stays **503** on children-then-manifest; that is fail-closed, not a bind. P632B-03 service-binding residual stays HOLD until a documented unspoofable caller identity exists.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`, passing official-index HTML (`--otc-index-html` / `--index-text`). Tree honesty is not a publish. Live still **8784 / 5886**. Redeploy ops-mcp if `raw_retention.acquired` should be live.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts from a **deployed** Worker.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), [`P632_wave3_status.md`](P632_wave3_status.md), [`P632_wave4_status.md`](P632_wave4_status.md), [`P632_wave5_status.md`](P632_wave5_status.md), [`P632_wave6_status.md`](P632_wave6_status.md), [`P632_wave7_status.md`](P632_wave7_status.md), or [`P632_wave8_status.md`](P632_wave8_status.md).
- A live Coverage remeasure. Worker-put, planner `index_text`, jitter, fetch extract, and python IR codec are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `242c2484`. Local PASS at `3b64bdfc` is not this SHA and is not merge-gate.
- A deploy of `quant-platform-ci-aggregate`. The print-only helper does not create the Worker. The Worker is **absent**. That is the HUMAN bottleneck.

Wave-9 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
