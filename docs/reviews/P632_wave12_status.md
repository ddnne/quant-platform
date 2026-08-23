# Phase 6.3.2 Wave-12 status — leak register vs current HEAD (not a GO)

**Isolation worktree:** `/Users/taku/tmp/qp-p632-wave12-status` on `grok/p632-wave12-status` (do not push `main`).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`), [`P632_wave4_status.md`](P632_wave4_status.md) (A–S freeze vs `40d1aa90`), [`P632_wave5_status.md`](P632_wave5_status.md) (A–S freeze vs `67fcbd7c`), [`P632_wave6_status.md`](P632_wave6_status.md) (A–S freeze vs `ed94d504`), [`P632_wave7_status.md`](P632_wave7_status.md) (A–S freeze vs `5103b26b`), [`P632_wave8_status.md`](P632_wave8_status.md) (A–S freeze vs `3b64bdfc`), [`P632_wave9_status.md`](P632_wave9_status.md) (A–S freeze vs `242c2484`), [`P632_wave10_status.md`](P632_wave10_status.md) (A–S freeze vs `2b82ec7d`), or [`P632_wave11_status.md`](P632_wave11_status.md) (A–S freeze vs `02fb6cbd`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `cf7da56c` (`cf7da56c17260da2c2693540f28af91c849bd542`) — `docs: review index names HEAD 02fb6cbd vs origin/main b5c326a`.  
**Window:** 14 commits after `02fb6cbd` (`02fb6cbd70f2039cd47bcf7a15838182842f3426`). Count: `git rev-list --count 02fb6cbd..cf7da56c` = **14**.  
**`origin/main`:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`) — feature branch is **not** an ancestor of `main`; **not merged**. `main` is an ancestor of this HEAD.  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `cf7da56c`.

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
| Wave-9 after 18 commits | `242c2484` | [`P632_wave9_status.md`](P632_wave9_status.md) |
| Wave-10 after 16 commits | `2b82ec7d` | [`P632_wave10_status.md`](P632_wave10_status.md) |
| Wave-11 after 15 commits | `02fb6cbd` | [`P632_wave11_status.md`](P632_wave11_status.md) |
| Wave-12 (this file) | `cf7da56c` | this re-diff |

Status vocabulary: **OPEN / FIXED / PARTIAL / HOLD / HUMAN**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`. Live Cloudflare is Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`).

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 189629 (~52.7h)
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
commits/cf7da56c/check-runs  total_count: 0
commits/cf7da56c/status      state: pending, total_count: 0
PR #1                       mergeable: MERGEABLE
                            mergeStateStatus: BLOCKED
                            statusCheckRollup: []
                            headRefOid: cf7da56c17260da2c2693540f28af91c849bd542
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
wrangler whoami
  logged in as taku_haga@icloud.com
  account 11233bca08d134a9b738eaa46b9751d9

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

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY. Local `verify_ci` at `02fb6cbd` is **not** a posted GitHub context. Print-only first-deploy is **not** a producer. Same generation as wave-11 (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 188717 → 189629. Floors and 4-PARTIAL set are unchanged.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Wave-12 **tree** honesty (leftover `catalog.ts` grep drop; premium `dateMode` JSON contract via Worker unit; JSDA fail-closed run-token / no invented COMPLETE; premium NK rebuild Worker unit) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate; **ci-aggregate Worker absent**).

**HUMAN bottleneck named:** `quant-platform-ci-aggregate` Worker **absent**. Branch protection requires a context that has no producer on the account. Isolation must not deploy, bind secrets, or PAT-mint `ci-aggregate`. `scripts/ci_aggregate_first_deploy.sh` prints operator commands and refuses `--apply` without `CONFIRM_CI_AGGREGATE_CREATE=1`; even then it is still print-only. **ci-aggregate create remains the bottleneck.**

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `44642dfc` | drop leftover `catalog.ts` grep; Worker `catalog.test.ts` owns identity | Python `test_typescript_catalog_matches_python` deleted. `test_contract_json_matches_premium_core_datasets` keeps JSON vs `PREMIUM_CORE_DATASETS` set-equality (not a Worker-body grep). `git grep catalog.ts tests/` is empty. | Not merge-gate. Not Dataset COMPLETE 23. Worker `toHaveLength(23)` is premium-core **paths**. |
| `2218b861` | premium `dateMode` is JSON contract via Worker unit | `catalog.test.ts` `it(` **1 → 2**: maps every JSON `date_mode` onto `spec.dateMode`, and `day_param` onto `dayParam` when present. | Not a vendor fetch. Not Dataset COMPLETE. Not merge-gate. |
| `afd94e58` | JSDA Worker fail-closed run-token and no invented COMPLETE | `ingestion-jsda/src/index.test.ts` `it(` **2 → 4**. Missing / wrong / unbound `INGESTION_RUN_TOKEN` → HTTP **401** `{error:"unauthorized"}`; no live HTML fetch; no D1/R2; body has no token leak, no `COMPLETE`, no `READY`. | Live MCP still V2 STALE **8784 / 5886**. PARSE_ZERO stays empty. Not Dataset COMPLETE. Not a secret bind. |
| `8fc9fa30` | premium NK rebuild is Worker unit not Python grep | New `natural_key_migration.test.ts` (`it(` **5**): canonical `naturalKey`, atomic swap, PENDING/REJECTED fail-closed, post-publish READY. Python dropped `test_worker_rebuild_uses_canonical_fn_atomic_swap_and_post_publish_audit`. Remaining Py tests are execution parity + SQL `0005` defer-without-mutate. | Worker-side `index.ts` string pin remains (`requireNaturalKeysV2Ready` / no `typeof row["available_at"]`). Live NK migration is not READY. Not merge-gate. |

Independent revisits / inventories at `02fb6cbd` (`eb380278` A, `a8f2eb95` B, `e79cfc3f` C, `7912001f` wave-11, `424f6dac` P, `96e94aea` `verify_ci`, `2806e5c7` original-plan-gap, `d5cb768c` residual SoT, `ef8a43b0` §10 remaining mixed, `cf7da56c` review index) are freezes / operator notes vs the wave-11 SHA, not live GO. They do **not** yet name leftover `catalog.ts` grep drop / `dateMode` Worker unit / JSDA fail-closed / NK rebuild Worker unit. Independent A/B/C freeze SHAs are `02fb6cbd`. Catalog identity (`specs/research_catalog/`, `catalog_ids.ts`, `daily_path.ts`) is an empty diff `02fb6cbd..cf7da56c`. Premium **production** `*.ts` (not tests) is also an empty diff.

This isolation did **not** re-run `scripts/verify_ci.sh` at `cf7da56c`. The `02fb6cbd` local PASS ([`P632_verify_ci_02fb6cbd.md`](P632_verify_ci_02fb6cbd.md): **1501 passed / 4 skipped**; `ingestion-premium` was **32** tests / `ingestion-jsda` was **2** at that SHA) is the wave-11 reviewed SHA, not this HEAD, and is **not** merge-gate. Prior `2b82ec7d` PASS (**1505 passed / 4 skipped**) is still not this SHA.

---

## The 14 commits after `02fb6cbd`

| SHA | Landing | Lane |
|-----|---------|------|
| `44642dfc` | drop leftover `catalog.ts` grep; Worker `catalog.test.ts` owns identity | L / P |
| `2218b861` | premium `dateMode` is JSON contract via Worker unit | L / P |
| `afd94e58` | JSDA Worker fail-closed run-token and no invented COMPLETE | L / H / P |
| `8fc9fa30` | premium NK rebuild is Worker unit not Python grep | L / P |
| `eb380278` | independent review A revisit at `02fb6cbd` | docs (A freeze) |
| `a8f2eb95` | independent review B revisit at `02fb6cbd` | docs (B freeze) |
| `e79cfc3f` | independent review C catalog/pilot revisit at `02fb6cbd` | docs (C freeze) |
| `7912001f` | wave-11 status after commits vs `2b82ec7d` | docs (wave-11 freeze) |
| `424f6dac` | 6.3.2 P test inventory at `02fb6cbd` | docs (P) |
| `96e94aea` | P632 `verify_ci` code-lane result at `02fb6cbd` | docs (C; not merge-gate) |
| `2806e5c7` | banner original-plan-gap register still holds at `02fb6cbd` | docs |
| `d5cb768c` | residual SoT banner HEAD `02fb6cbd` vs `origin/main` `b5c326a` | docs |
| `ef8a43b0` | §10 remaining mixed at `02fb6cbd` | docs (Q freeze) |
| `cf7da56c` | review index names HEAD `02fb6cbd` vs `origin/main` `b5c326a` | docs |

Docs commits in this window (`eb380278`, `a8f2eb95`, `e79cfc3f`, `7912001f`, `424f6dac`, `96e94aea`, `2806e5c7`, `d5cb768c`, `ef8a43b0`, `cf7da56c`) are freezes / operator notes, not live GO. Independent A/B/C revisits are authored vs `02fb6cbd` and do **not** yet name leftover `catalog.ts` grep drop / `dateMode` / JSDA fail-closed / NK rebuild. `ef8a43b0` remaining-extracts freeze is authored vs `02fb6cbd` (TypedDict / shared reader / premium Worker units already **DONE** in that freeze); this re-diff is vs `cf7da56c`.

---

## A–S vs `cf7da56c` (after the 14)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`; [`P632_wave4_status.md`](P632_wave4_status.md) vs `40d1aa90`; [`P632_wave5_status.md`](P632_wave5_status.md) vs `67fcbd7c`; [`P632_wave6_status.md`](P632_wave6_status.md) vs `ed94d504`; [`P632_wave7_status.md`](P632_wave7_status.md) vs `5103b26b`; [`P632_wave8_status.md`](P632_wave8_status.md) vs `3b64bdfc`; [`P632_wave9_status.md`](P632_wave9_status.md) vs `242c2484`; [`P632_wave10_status.md`](P632_wave10_status.md) vs `2b82ec7d`; [`P632_wave11_status.md`](P632_wave11_status.md) vs `02fb6cbd`. This table is the wave-12 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker **code** + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags + IR codec freeze + freeze-**call** pin + python codec freeze + python types freeze + print-only first-deploy helper named in operator map) / **OPEN** (live check never posted; **Worker absent**) / **HUMAN** (`quant-platform-ci-aggregate` first deploy + token bind)

| Sub-item | At `02fb6cbd` (wave-11) | After wave-12 |
|----------|-------------------------|---------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code) + helper named. Live Worker **absent**. | **FIXED** (code; empty diff). Live Worker **absent** — deployments **10007**, secrets not found, `/health` **404**. Named **HUMAN** bottleneck. Helper does not wrangler deploy. |
| `verify_ci` covers gate Worker | **FIXED** + python types freeze. Local PASS documented at `2b82ec7d`, not `02fb6cbd`. | **FIXED** (empty diff on `scripts/verify_ci.sh`). Local PASS now documented at `02fb6cbd` ([`P632_verify_ci_02fb6cbd.md`](P632_verify_ci_02fb6cbd.md)), not this HEAD, not GitHub. |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`02fb6cbd` `total_count: 0`) | **OPEN** — this turn `cf7da56c` `total_count: 0`; `/status` `pending` / `0`. PR #1 `MERGEABLE` / `BLOCKED`; `statusCheckRollup: []`. |
| Fail/pass merge smoke | **OPEN** | **OPEN** — cannot smoke a producer that does not exist |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint; nothing to bind until Worker exists; helper never puts secret values |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`; retry jitter `crypto.getRandomValues`) / **OPEN** (clean-checkout proof at this HEAD)

Empty diff vs `02fb6cbd` on Worker production sources for lockfiles / jitter / fetch extract. Premium + JSDA Worker **unit** tests grew in place (`44642dfc` / `2218b861` / `afd94e58` / `8fc9fa30`; first-party files **25 → 26**; premium `it(` **32 → 38**; JSDA `it(` **2 → 4**; Worker `it(` / `test(` **177 → 185**). That is test-surface honesty, not a clean-checkout matrix.

Local `verify_ci` PASS is now **documented** at `02fb6cbd` ([`P632_verify_ci_02fb6cbd.md`](P632_verify_ci_02fb6cbd.md): 7 workers including `ci-aggregate` 13 tests; **1501 passed / 4 skipped**; `ingestion-premium` was **32** tests / `ingestion-jsda` was **2** at that SHA). That is a different SHA than this HEAD. Clean-checkout matrix **not** executed at `cf7da56c` in this isolation.

Do not invent PASS at `cf7da56c`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, encode-key lock, generated TS codec freeze, freeze-**call** pin, generated Python codec freeze, generated Python types freeze, types flags, **local PASS at `02fb6cbd`**, print-only first-deploy helper named) / **OPEN** (merge gate is live GitHub context; producer Worker **absent**)

- Authoritative: `scripts/verify_ci.sh`. `WORKERS` still includes `platform/workers/ci-aggregate`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`. Empty diff vs `02fb6cbd`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- Local PASS at `02fb6cbd`: 1501 passed / 4 skipped; wall 177.94s; `verify_ci: ok`. **Not** merge-gate. **Not** this HEAD. This isolation did not re-run the script after the wave-12 code landings (`44642dfc`, `2218b861`, `afd94e58`, `8fc9fa30`).
- Print-only operator helper still does **not** create a fresh venv (requires existing `.venv` 3.11+). Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, and that POST host **does not exist**.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed + OTC grain token + nested-open pin) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design. Missing V3 JSON is `None`, not invented.

Planner **does** clip through SourceCapability SoT. That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors. Empty diff vs wave-11 on the four files.

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

**status: PARTIAL** (V3 file + planner + HTML index SoT + refresh wire + CLI `index_text` + JSON grain + sealer `index_text` + `issue_*` `--index-text` + pipeline held HTML + BackfillPlanner `index_text` + shared local HTML reader + `cf_premium_backfill --index-text` + **JSDA Worker fail-closed run-token**) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

Empty production diff vs `02fb6cbd` on planner / sealer / shared reader. Wave-12 JSDA landing (`afd94e58`) is Worker **auth** unit (401 / no fetch / no persist / no invented COMPLETE), not an official-index required-set wire.

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration.

- `PARSE_ZERO_SEAL_PROOF` stays empty — `2002-08-02` / `2002-08-05` stay **PARTIAL** without in-repo digest+count.

Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts + tip/index event-zero PARTIAL) / **OPEN** (live READY **null**)

Unchanged vs wave-11 live. `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

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

Unchanged vs wave-11. Caps unchanged (`auto_promotion: false`). Live occupancy / double-spend under production traffic: **not** measured this wave. String `budget_id` is still not the reserve. Empty diff vs `02fb6cbd` on `research-ai-gateway`.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split; secrets proxy **Worker unit**; **premium catalog / availability / identity-JST / raw-page / coverage-segment Worker unit**; **leftover `catalog.ts` grep dropped**; **premium `dateMode` JSON Worker unit**; **JSDA fail-closed run-token Worker unit**; **premium NK rebuild Worker unit**) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented; GATEWAY service-binding residual) / **HUMAN** (secret bind)

Unchanged vs wave-11 production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN** / **HOLD** (`7221c588`; mass-eval `ai_gateway_client.ts` still sends `GATEWAY_TOKEN` as `X-Gateway-Token`; empty diff vs `02fb6cbd`). Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

Wave-12 vs wave-11: leftover Python `catalog.ts` grep **dropped** (`44642dfc`); `dateMode` JSON contract is Worker unit (`2218b861`); JSDA 401 fail-closed is Worker unit (`afd94e58`); NK rebuild is Worker unit (`8fc9fa30`). That is contract-vs-unit split, **not** a secret bind. JSON vs Python `PREMIUM_CORE_DATASETS` set-equality remains (not a Worker-body grep). `tests/test_identity_runtime_parity.py` stays real Py↔TS **execution** parity.

`ci-aggregate` `workers_dev=true` is moot until the Worker exists. Unbound mass-eval token on children-then-manifest stays **503**; unbound JSDA `INGESTION_RUN_TOKEN` stays **401**; that is fail-closed, not a secret bind.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + overlay never CLI-put + Worker POST client + research-artifact POST + unbound token 503 + daily-path Worker put + mass-eval-run Worker put) / **OPEN** (live POST unproven) / **HOLD** (overlay identity helper still exists; reconstitution dry-run still `default_r2_put`)

Empty diff vs `02fb6cbd` on `r2_io.py` (431) and `reconstitution_evidence.py`. Remaining `default_r2_put` production caller: `reconstitution_evidence` dry-run-only (`default_r2_put(..., dry_run=True)`). `put_research_artifact` still stages locally via `default_r2_put` when `dry_run=True`. Overlay identity **HOLD**.

Do not treat “HTTP client exists” or “CLI put deleted” as live Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases + leftover occupancy HOLD **pointer**) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n / leftover occupancy)

Independent C at `02fb6cbd` ([`P632_ind_C_revisit_02fb6cbd.md`](P632_ind_C_revisit_02fb6cbd.md)): YAML n = **0**; compiled freeze n = **2254**; `yaml_overlay_allowed()` **False**; `go: false`. Compact `family + template + parameter matrix` **not** implemented. Catalog identity is an empty diff `02fb6cbd..cf7da56c` (`specs/research_catalog/`, `catalog_ids.ts`, `daily_path.ts`).

unique22 leftover still **22** (17 parked + 5 occupancy-equal lifts). Leftover occupancy HOLD pointer unchanged. Do not unify with `comboEventGateOk`. Do not extract.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS` + encode-key lock + generated TS codec body + freeze-**call** pin + generated Python codec body + emit extract + generated Python TypedDict) / **OPEN** (`EvaluationIR` dataclass still hand-written; TS decode does not load a JSON Schema engine)

Empty production diff vs `02fb6cbd` on IR sources. Codec bodies unchanged: generated Python codec; generated TS codec (239); Worker façade `evaluation_ir.ts` (39); emit helper `evaluation_ir_emit.py` (823); façade `evaluation_ir.py` (646); TypedDict `evaluation_ir_types.generated.py` (47). Encode object keys remain schema properties; grade remains `jobCandidateGrade` / `job_candidate_grade`. Unknown fields still fail; version stays `evaluation-ir/v1`.

**`@dataclass(frozen=True) class EvaluationIR` is still hand-written** in the façade (`evaluation_ir.py:273`). Decode on the Worker still uses generated `ALLOWED_FIELDS`, not a JSON Schema engine.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + collect freezes + digest identity + READY fixture honesty + event-zero tip/index pins + secrets Worker unit + **premium catalog / availability / identity-JST / raw-page / coverage-segment Worker unit** + **leftover `catalog.ts` grep dropped** + **premium `dateMode` Worker unit** + **JSDA fail-closed Worker unit** + **premium NK rebuild Worker unit**)

See [`P632_test_inventory.md`](P632_test_inventory.md) (`3ab87d0`, collected **1353**), [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (`07b4435`, **1379**), [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md) (**1426**), [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md) (**1448**), [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md) (**1470**), [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md) (**1496**), [`P632_test_inventory_3b64bdfc.md`](P632_test_inventory_3b64bdfc.md) (**1503**), [`P632_test_inventory_242c2484.md`](P632_test_inventory_242c2484.md) (**1506**), [`P632_test_inventory_2b82ec7d.md`](P632_test_inventory_2b82ec7d.md) (**1509**), [`P632_test_inventory_02fb6cbd.md`](P632_test_inventory_02fb6cbd.md) (**1505** collected; `tests/test_*.py` **154**; Worker first-party **25**; YAML **0**). Local `verify_ci` at `02fb6cbd` reported **1501 passed, 4 skipped**.

This HEAD `git ls-files tests/test_*.py` = **154** (no Python module add/delete). Worker first-party test **files** **25 → 26** (22 `*.test.ts` + 4 `*.test.mjs`): added `natural_key_migration.test.ts`. Premium `it(` **32 → 38**. JSDA `it(` **2 → 4**. Worker `it(` / `test(` **177 → 185**. Wave-11 inventory named leftover `catalog.ts` grep and NK rebuild Python grep **OPEN**; wave-12 dropped both and landed `dateMode` + JSDA fail-closed Worker units. Remaining Worker-body grep: `tests/test_cf_cost_verify.py` `daily_path.ts` liquidity-comment HOLD. NK Worker test still pins `index.ts` strings (`requireNaturalKeysV2Ready` / no payload `available_at`) — Worker-side pin, not a Python grep. JSON contract vs Python `PREMIUM_CORE_DATASETS` set-equality is not a Worker-body grep; keep that identity. `tests/test_identity_runtime_parity.py` is execution parity + SQL `0005`, not echo. This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`. Count growth of Worker units is a mechanism replacement, not a consolidation win, and not a GO.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is authored vs `02fb6cbd` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md); `ef8a43b0`). That freeze already records TypedDict generation **DONE**, shared official-index reader **DONE**, and premium Worker units for catalog / availability / identity / raw-page / coverage-segment. Wave-12 landings vs that freeze are **test-surface**, not a new mixed-authority extract:

| §10.3 later | At `02fb6cbd` (wave-11) | After wave-12 |
|-------------|-------------------------|---------------|
| 1 BackfillPlanner vs `plan_required_segments` | **DONE** (JQ jobs from required segments; pipeline held OTC HTML; `issue_*` `--index-text`; BackfillPlanner `index_text`; shared local HTML reader; `cf_premium_backfill --index-text`). | **DONE** — empty production diff. JSDA fail-closed is Worker auth, not a planner wire. Live MCP still V2 STALE. |
| 2 Python `r2_io.py` TOCTOU | **PARTIAL** — overlay never CLI-put; research artifacts POST; unbound token 503; daily-path + mass-eval-run Worker put. Remaining `default_r2_put` caller: reconstitution dry_run only. Overlay helper **HOLD**. `r2_io.py` **431**. | **PARTIAL** — empty diff. Remaining `default_r2_put` caller: reconstitution dry_run only. Overlay helper still exists (**HOLD**). `r2_io.py` still **431**. Live POST unproven. |
| 3 hand-written `evaluation_ir.ts` | **PARTIAL** — emit extract; Python TypedDict generated. `EvaluationIR` dataclass still hand-written. TS decode still not a JSON Schema engine. | **PARTIAL** — empty diff. `EvaluationIR` dataclass still hand-written. TS decode still not a JSON Schema engine. |
| 4 MCP frozen “Coverage V2” strings | **FIXED** (not reopened). Live MCP still emits `complete` only. | **FIXED** (not reopened). Live MCP still emits `complete` only. JSDA 401 bodies also refuse invented COMPLETE (tree). |
| 5 `verify_all` vs `verify_ci` | **HOLD** (local PASS at `2b82ec7d` is not merge-gate; python types freeze; print-only first-deploy still does not create the producer) | **HOLD** (local PASS at `02fb6cbd` is not merge-gate; print-only first-deploy still does not create the producer) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. Coverage V2 JSON vs V3 contracts: planner + OTC grain + `index_text` CLIs + sealer + pipeline held HTML + `issue_*` + BackfillPlanner `index_text` + shared reader + backfill `--index-text` wired for 4 datasets; live MCP still V2 STALE.

Premium fetch/retry extract still **DONE** (`a20d14d4`; `fetch_jq.ts`; `index.ts` façade **678**). Retry jitter extract still **DONE** (`82ef0f7b`; `retry_jitter.ts`). GATEWAY residual stays **HOLD** (`7221c588`; empty diff on `ai_gateway_client.ts`).

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply. Reconstitution evidence stays dry-run-only (`default_r2_put` local stage). Empty diff vs `02fb6cbd` on `reconstitution_evidence.py`.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Independent C at `02fb6cbd`: catalog/pilot P0 unresolved **0** (no live arming); that is not Phase 7 GO. Catalog identity empty vs this HEAD.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `02fb6cbd` (wave-11) | After wave-12 (`cf7da56c`) |
|----|-------------------------|----------------------------|
| IND-A-DOMAIN | **FIXED**. Live STALE still V2 `2006-08-13`. | **FIXED** (not reopened). Live still STALE. Independent A freeze now at `02fb6cbd`. |
| IND-A-JSDA-PHANTOM | **FIXED** (tree) + shared local HTML reader + `cf_premium_backfill --index-text`. Live still **8784 / 5886**. PARSE_ZERO stays gap. | **FIXED** (not reopened; empty production planner diff). JSDA fail-closed is 401 / no fetch, not a required-set wire. Live still **8784 / 5886**. PARSE_ZERO stays gap. Independent A freeze file is still vs `02fb6cbd`. |
| IND-A-PIT-BYPASS | **FIXED** | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** (premium raw-page retain unit still writes **ACQUIRED**, never Coverage COMPLETE). Live MCP still `complete`. Independent A freeze at `02fb6cbd` still tree P0 = 0. | **PARTIAL** (JSDA 401 bodies refuse invented COMPLETE; raw-page retain still **ACQUIRED**). Live MCP still `complete`. Independent A freeze at `02fb6cbd` still tree P0 = 0. |
| IND-A-READY-DEPS | **FIXED**. Live READY **null**. | **FIXED**. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** — local PASS at `2b82ec7d`; python types freeze; live merge gate still not `verify_ci`; producer Worker **absent** | **PARTIAL** — local PASS at `02fb6cbd` documented; live merge gate still not `verify_ci`; producer Worker **absent** |
| P632B-02 live `ci-aggregate` posted | **OPEN** — Worker **absent** (10007). Print-only helper is not a create. **HUMAN** create. Check-runs **0**. | **OPEN** — Worker **absent** (10007). Helper still print-only. **HUMAN** create. Check-runs still **0**. |
| P632B-03 `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | **OPEN** / **HOLD** (`7221c588` pointer; empty diff on `ai_gateway_client.ts`). Unbound mass-eval token on children-then-manifest stays **503**. | **OPEN** / **HOLD** (empty diff vs `02fb6cbd` on `ai_gateway_client.ts`). Unbound mass-eval token stays **503**. |
| P632B-05 Python R2 TOCTOU | **PARTIAL** — daily-path + mass-eval-run Worker put. Remaining `default_r2_put` caller: reconstitution dry_run only. Live POST unproven. Overlay helper **HOLD**. | **PARTIAL** — empty diff vs `02fb6cbd`. Remaining `default_r2_put` caller: reconstitution dry_run only. Live POST unproven. Overlay helper **HOLD**. |
| C-YAML load overlay | **FIXED**. +N **HOLD**. Independent C freeze at `2b82ec7d` (P0 unresolved **0**; not Phase 7 GO). Catalog identity empty vs `02fb6cbd`. | **FIXED**. +N **HOLD**. Independent C freeze now at `02fb6cbd` (P0 unresolved **0**; not Phase 7 GO). Catalog identity empty vs this HEAD. |

Independent P0 unresolved ≠ 0 (live CI never posted; **ci-aggregate Worker absent**). Independent A tree P0 = 0. Independent B live P0 = **2**. Independent C catalog/pilot P0 = 0. `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree Worker units are not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker **absent** (10007); live check-runs **0**. Print-only helper. HUMAN deploy. Conjunction **fails**. |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); retry jitter `getRandomValues` **FIXED** (tree); local PASS at `02fb6cbd` **FIXED** (docs); python types freeze **FIXED** (tree); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed; OTC grain token **FIXED** |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh + `index_text` CLIs + grain + sealer + pipeline held HTML + `issue_*` + BackfillPlanner `index_text` + shared reader + `cf_premium_backfill --index-text`; live MCP still V2 STALE |
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
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values. Unbound mass-eval token stays **503** on children-then-manifest; unbound JSDA `INGESTION_RUN_TOKEN` stays **401**; that is fail-closed, not a bind. P632B-03 service-binding residual stays HOLD until a documented unspoofable caller identity exists.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`, passing official-index HTML (`--otc-index-html` / `--index-text`). Tree honesty is not a publish. Live still **8784 / 5886**. Redeploy ops-mcp if `raw_retention.acquired` should be live.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts from a **deployed** Worker.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), [`P632_wave3_status.md`](P632_wave3_status.md), [`P632_wave4_status.md`](P632_wave4_status.md), [`P632_wave5_status.md`](P632_wave5_status.md), [`P632_wave6_status.md`](P632_wave6_status.md), [`P632_wave7_status.md`](P632_wave7_status.md), [`P632_wave8_status.md`](P632_wave8_status.md), [`P632_wave9_status.md`](P632_wave9_status.md), [`P632_wave10_status.md`](P632_wave10_status.md), or [`P632_wave11_status.md`](P632_wave11_status.md).
- A live Coverage remeasure. Worker units are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `cf7da56c`. Local PASS at `02fb6cbd` is not this SHA and is not merge-gate.
- A deploy of `quant-platform-ci-aggregate`. The print-only helper does not create the Worker. The Worker is **absent**. That is the HUMAN bottleneck.

Wave-12 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
