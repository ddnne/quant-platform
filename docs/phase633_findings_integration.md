# Independent Integration review — SHA `58133512`

**Lane:** Phase 6.3.3 independent Integration (1 of 4). Not Data/PIT, not Cloudflare/CI, not Architecture/Test.  
**Reviewed SHA:** `58133512e1e896f1e811d1fb597337aa8f53d965` (`docs: review index names HEAD cb9916e0 vs origin/main b5c326a`)  
**origin/main:** `b5c326a7f612563f2da4a84f08063a307ec38e0a` (`test: propose route reads http_routes; PIT jobs inject tmp receipt keys`)  
**Merge-base:** `b5c326a7` — `origin/main` is an ancestor of the SHA; the SHA is **not** an ancestor of `origin/main`. Feature is **not** on `main`.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 (`grok/phase63-ci-source-closure` → `main`)  
**Fetched this review:** GitHub protection / PR / check-runs / statuses; Wrangler `quant-platform-ci-aggregate`; live `quant-mcp` (projection, READY, B0, sync, coverage_gaps, ops, AM SLA).

**Mass / production READY / Phase 7 Controlled Pilot:** **NO-GO / null / OFF**.  
**Phase 6.3.3 COMPLETE?** **NOT COMPLETE.**  
**Phase 6.4 COMPLETE?** **NOT COMPLETE.**  
This file is not a GO and does not mint Coverage COMPLETE, Projection FRESH, B0 PASS, or READY.

Status vocabulary: **OPEN**. P0 = merge-gate or published contract can lie. P1 = residual coupling that is not a GO. P2 = noise that hides the gate.

Do **not** add `docs/reviews` wave / Independent A/B/C revisit files. Do **not** force-push PR #1.

---

## Scoreboard

| ID | Topic | Sev | Status |
|----|-------|-----|--------|
| Issue 1 | PR #1 unreviewable; `origin/main` lacks feature; replacement stack required | P0 | **OPEN** |
| Issue 2 | Live merge gate `ci-aggregate` has no producer | P0 | **OPEN** |
| Issue 3 | Live 6.3.3 residual vs merge (STALE / READY null / B0 UNKNOWN / `applied_cursor` null) | P0 | **OPEN** |
| Issue 4 | Schema / interface / migration order split-brain | P0 | **OPEN** |
| Issue 5 | Four independent reviews required; this is Integration only | P0 | **OPEN** |
| Issue 6 | Even a posted `ci-aggregate` would skip `verify_ci` (Python / catalog / IR) | P1 | **OPEN** |
| Issue 7 | Review-doc flood (89 `docs/reviews` files) drowns the gate | P2 | **OPEN** |

**Unresolved P0 count: 5** (Issues 1–5). Do not merge.

---

## Live measurements (this review)

```text
PR #1
  base: b5c326a7  head: 58133512
  commits: 450   files: 421   +59166 / -3417
  mergeable: true   mergeStateStatus: BLOCKED
  reviews: 0   review comments: 0   statusCheckRollup: []
  GitHub Actions workflows: 0

GitHub main protection
  required_status_checks.strict: true
  contexts: ["ci-aggregate"]   checks[0].app_id: null
  enforce_admins: true   allow_force_pushes: false
  required_approving_review_count: 0

HEAD 58133512
  check-runs total_count: 0
  /status state: pending  total_count: 0

origin/main b5c326a
  check-runs total_count: 0

Wrangler account 11233bca08d134a9b738eaa46b9751d9
  deployments list --name quant-platform-ci-aggregate
    code: 10007  "This Worker does not exist on your account."

quant-mcp (live)
  projection_status: STALE
    active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
    generated_at: 2026-08-21T12:30:49.152421+00:00
    refresh_attempt: true   refresh_success: false
    last_known_good.not_fresh: true
    projection_version: ops_projection/v3
  latest_ready_snapshot: snapshot=null
    reason: no published READY generation is bound to this Worker
  b0_status: UNKNOWN
    reason: snapshot quality/B0 projection is unavailable
  sync_status: applied_feed_cursor=null
    typical dataset state: LAGGING_APPLY_UNPINNED
    indices_bars_daily_topix: EXPORT_CURRENT_APPLY_UNPINNED (lag 0, pin still null → never CURRENT)
  coverage_gaps: 22 COMPLETE / 4 PARTIAL  policy_version collection-coverage/v2
    PARTIAL: equities_bars_daily_am · equities_earnings_calendar · equities_master · jsda_otc_bond_reference_prices
    equities_master.history_target_start live: 2006-08-13  (tree JSON at SHA: 2008-05-07)
  ops last_run: id 14339  2026-08-24T20:15:01+09:00  jquants cron pass  (not READY)
  AM SLA: PROJECTION_STALE
```

Cron PASS, raw-retention growth, and last-known 22 COMPLETE under STALE are **not** Coverage COMPLETE, Projection FRESH, B0 PASS, or READY.

---

## Issue 1 P0 — PR #1 is unreviewable; replacement stack required

**severity:** P0  
**affected:** GitHub PR #1; `origin/main` `b5c326a7`; SHA `58133512`  
**status:** **OPEN**

### Observed

`origin/main..58133512` is **450 commits / 421 files / +59166 / −3417**. Mix in one PR:

| Area | Files |
|------|-------|
| `platform/` (Workers) | 162 |
| `docs/` | 96 (of which `docs/reviews/` **89**) |
| `tests/` | 73 |
| `packages/` | 64 |
| `scripts/` | 14 |
| `specs/` | 10 |

Feature-only paths absent from `origin/main` include the entire `platform/workers/ci-aggregate/` tree, `scripts/verify_ci.sh`, `specs/source_capability/*`, `specs/coverage_v3/*`, `packages/data_plane/data_contracts/source_capability.py`, and `packages/data_plane/data_contracts/source_capability.schema.json`.

`git merge-base --is-ancestor 58133512 origin/main` is **false**. `main` does not contain this feature. PR #1 `mergeStateStatus` is **BLOCKED** with **0** reviews and **0** check-runs.

PR title still says “Phase 6.3.2 Wave 1”. The body already lists “Independent review P0=0” and “Controlled Pilot” as still open. That is not a reviewable 6.3.3 closure.

### Why this is P0

An Integration reviewer cannot honestly sign 421 files spanning CI producer, V3 contracts, D1/SQLite migrations, Worker extracts, catalog, IR codecs, and 89 historical review freezes as one merge. A green squash into `main` would publish an un-audited contract and an un-produced merge gate.

### Replacement stack (do **not** force-push)

`allow_force_pushes` on `main` is **false**. This review does **not** demand rewriting `58133512` or force-pushing PR #1.

Required replacement: **new stacked PRs onto `origin/main` `b5c326a7`**, each small enough that one independent lane can reject it. Suggested cut (names are slices, not a GO):

1. CI producer only (`ci-aggregate` deploy + bound tokens + fail/pass SHA posts context `ci-aggregate`).
2. Authoritative local CI (`verify_ci.sh` as the receipt command, including the gate Worker).
3. SourceCapability / coverage V3 **ledger migration** (not JSON-in-git only).
4. Dual-plane schema migrations (SQLite + D1) with runbook order that matches the files.
5. Remainder only after (1)–(4) have independent P0 = 0.

Leave PR #1 **open and BLOCKED** as a historical bundle. Copy commits forward as new PRs; do not rewrite the 450-commit history onto `main`.

---

## Issue 2 P0 — Live merge gate `ci-aggregate` has no producer

**severity:** P0  
**affected:** GitHub `main` protection; PR #1; `platform/workers/ci-aggregate/`; `docs/ci/workers_builds.md`; `scripts/verify_ci.sh`  
**status:** **OPEN**

### Observed

`main` requires context **`ci-aggregate`** (`strict: true`, `enforce_admins: true`, `app_id: null`).

At SHA `58133512` and at `origin/main` `b5c326a7`:

- check-runs **0**
- commit statuses **0** / `pending`
- Actions workflows **0** (correct by policy; do not add GHA)

Tree implements `platform/workers/ci-aggregate` (`name = "quant-platform-ci-aggregate"`, `workers_dev = true`). Live Wrangler:

```text
GET …/workers/scripts/quant-platform-ci-aggregate/deployments
  code: 10007  This Worker does not exist on your account.
```

`CI_LANE_TOKEN` / `GITHUB_STATUS_TOKEN` therefore have **no Worker to bind**. `docs/ci/workers_builds.md` already names first-deploy as HUMAN. `scripts/ci_aggregate_first_deploy.sh` is print-only; it is not a producer.

`scripts/verify_ci.sh` lists seven Workers including `ci-aggregate`. GitHub does not run `verify_ci.sh`. Local PASS of that script (not claimed by this review) would still not post the required context.

### Why this is P0

The only required check has **never posted**. BLOCKED-because-missing is not a passing CI receipt. Merging without a producer would require dropping protection or forging the context. Integration cannot treat tree-level Worker source as a live gate.

---

## Issue 3 P0 — Live 6.3.3 residual vs merge gate

**severity:** P0  
**affected:** live `quant-mcp`; `docs/phase62_residual_status.md` (flags only); READY / B0 / sync / coverage publication  
**status:** **OPEN**

Phase 6.3.3 merge is an AND with live residual. This turn’s MCP:

| Gate | Live |
|------|------|
| Projection | **STALE** (`refresh_success=false`, `last_known_good.not_fresh=true`, generation `projgen-ef18b4f86ee946048161d25e2a30a2a8` from 2026-08-21) |
| READY | **null** (no published generation bound) |
| B0 | **UNKNOWN** (quality/B0 projection unavailable) |
| `applied_cursor` / `applied_feed_cursor` | **null** — never CURRENT; `EXPORT_CURRENT_APPLY_UNPINNED` still unpinned |
| Coverage | last-known **22 COMPLETE / 4 PARTIAL** under **collection-coverage/v2** and STALE (not FRESH, not COMPLETE 23) |
| AM SLA | **PROJECTION_STALE** |
| last_run | **14339** cron 2026-08-24T20:15:01+09:00 — not READY |

`ci-aggregate` **absent** (Issue 2) is the GitHub leg of the same conjunction.

### Why this is P0

Merging SHA `58133512` into `main` would put V3 planner / SourceCapability / IR / catalog extracts on the default branch while live publication is STALE, unpinned, READY-null, B0-UNKNOWN, and CI-dark. That is a false 6.3.3 closure. Do not treat last-known 22 COMPLETE as live V3.

---

## Issue 4 P0 — Schema / interface / migration order

**severity:** P0  
**affected:** `packages/data_plane/data_contracts/collection_coverage.json`; `specs/source_capability/*`; `specs/coverage_v3/*`; `packages/data_plane/storage/migrations.py` (SQLite 9); `platform/workers/ingestion-premium/migrations/0010_raw_acquisition_status.sql`; `platform/workers/quant-ops-mcp/migrations/0007_ops_applied_pins.sql`; `docs/phase61_production_runbook.md`; `packages/data_plane/ops/backfill_planner.py`; D1 vs SQLite vs MCP  
**status:** **OPEN**

Four independent order bugs. Any one is enough to lie COMPLETE / CURRENT / ACQUIRED if this SHA is merged and then applied in the wrong plane first.

### 4a. Mixed coverage contract vs live V2 ledger

At SHA `58133512`, `collection_coverage.json` still has:

```json
"schema_version": 2,
"policy_version": "collection-coverage/v2"
```

Three datasets override `policy_version` to `"collection-coverage/v3"` (`equities_master`, `equities_bars_daily_am`, `equities_earnings_calendar`). Master `history_target_start` in-tree is **2008-05-07**. Live MCP `coverage_gaps` still advertises **collection-coverage/v2** and master start **2006-08-13**.

`specs/coverage_v3/*.json` exist only on the feature SHA. `specs/source_capability/*.json` (`source-capability/v3`) exist only on the feature SHA. `BackfillPlanner` loads `source_capability_contract_or_none` and clips official domain in Python; missing V3 is supposed to fail closed rather than invent official domain. Live required-set publication is still the STALE V2 projection.

Official-domain correction in git **≠** live required-set migration. Publishing the mixed JSON without a FRESH V3 ledger would hide V2 PARTIAL months as “excluded” without a published mapping.

### 4b. Dual-plane `raw_retention_manifests` rebuild (SQLite 9 vs D1 0010)

Same CHECK widen (`COMPLETE`/`FAILED` → `ACQUIRED`/`FAILED`/`COMPLETE`), two rebuilds, two version numbers:

| Plane | File | Temp table |
|-------|------|------------|
| Local SQLite | `storage/migrations.py` Migration **9** `phase632_raw_acquisition_status` | `raw_retention_manifests__v9` (DROP + rename) |
| Remote D1 | `ingestion-premium/migrations/0010_raw_acquisition_status.sql` | `raw_retention_manifests__v10` (DROP + rename) |

`origin/main` already has D1 `0008` / `0009`; it does **not** have `0010` or SQLite 9. `SqliteStore` applies every unapplied local migration on open (`apply_schema_migrations`). Opening a local DB with this SHA writes `ACQUIRED` before D1 `0010` exists. Remote CHECK on `0006` still forbids `ACQUIRED` → export/sync fail-closed or silent drop, depending on caller. Reverse order (D1 `0010` then old Python) rejects `ACQUIRED` on local open.

### 4c. Runbook order does not match files

`docs/phase61_production_runbook.md` §2 still loops only premium `000{1,2,3,4,5,6,7}_*.sql`, then Ops MCP `0001` + `0002`. At this SHA (and already on `origin/main`) premium has `0008` / `0009`; this SHA adds `0010`. Ops MCP has `0003`–`0007`. An operator following the runbook **skips** later D1 files. Comment “all migration files are idempotent, but do not reorder them” does not list the files that now exist.

Natural-key v2 rebuild (`/v1/admin/rebuild-natural-keys-v2` until `natural_key_migration.state == READY`) is still documented **before** ingest. Mixing that gate with skipped `0008`–`0010` and unpublished V3 coverage is an order hazard.

### 4d. `0007_ops_applied_pins` vs null pin

`quant-ops-mcp/migrations/0007_ops_applied_pins.sql` says do **not** apply remotely from the change set — schema only. `last_applied_change_seq NULL` is unpinned; CURRENT requires a non-null pin; never coerce null to 0.

Live `applied_feed_cursor` is **null**. Projector can emit `ops_applied_pins` from local `sync_change_state`. Applying the pin while projection is STALE would mint CURRENT on a not-fresh generation. Leaving the pin null forever makes Issue 3 unclosable. Integration cannot close either path from this SHA.

### Why this is P0

Interface SoT is split across (1) live MCP V2 ledger, (2) mixed v2/v3 JSON in git, (3) V3 specs not on `main`, (4) SQLite vs D1 rebuilds with different numbers, (5) a runbook that stops at `0007`. Merge-then-migrate in any of those orders can invent COMPLETE, CURRENT, or ACQUIRED.

---

## Issue 5 P0 — Four independent reviews required before merge

**severity:** P0  
**affected:** merge AND-gate for Phase 6.3.3  
**status:** **OPEN** (this file is Integration only)

Four independent reviews must all report **unresolved P0 = 0** on a **reviewable replacement stack** (Issue 1), not on PR #1’s 421-file bundle:

1. **Data / PIT**
2. **Cloudflare / CI**
3. **Architecture / Test**
4. **Integration** (this document)

This review is **(4)** only. It does not accept (1)–(3). GitHub PR #1 `reviews: []`. Independent P0 unresolved on this lane is **5**, so the AND-product is already false.

Do not treat a single Integration file, a historical 6.3.2 A/B/C freeze, or an empty finding table as four reviews. Do not merge because this file exists.

---

## Issue 6 P1 — Posted `ci-aggregate` would still skip `verify_ci`

**severity:** P1  
**affected:** `platform/workers/ci-aggregate/src/receipts_gate.ts`; `scripts/verify_ci.sh`; `docs/ci/workers_builds.md`  
**status:** **OPEN**

`REQUIRED_WORKERS` is the six product lanes. Receipt `command` is lane `npm ci && npm test`. The aggregate Worker is **not** in its own required set. Python, catalog freeze, Evaluation IR schema/codecs, `wrangler types --check`, and dry-run are **not** in the GitHub batch.

`scripts/verify_ci.sh` is the no-skip local authority (seven Workers). Docs say merge requires `ci-aggregate` **and** `verify_ci`. Live GitHub requires only the former, and the former has no producer (Issue 2).

This is P1 while the producer is absent (the missing producer is already P0). It becomes P0 on any SHA that posts a green `ci-aggregate` built from six `npm test` receipts.

---

## Issue 7 P2 — Review-doc flood

**severity:** P2  
**affected:** `docs/reviews/*` (89 files in this diff); PR #1 body  
**status:** **OPEN**

Wave / Independent A/B/C files at prior SHAs are historical freezes. They are not live Integration SoT. Carrying 89 of them in the same PR as `ci-aggregate` source and V3 specs makes Issue 1 worse. Do not add more wave files. This Integration review is `docs/phase633_findings_integration.md` only.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.3 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Merge PR #1 at `58133512`? | **NO** |
| Replacement stack required? | **YES** (new PRs onto `origin/main`; **do not force-push**) |
| Four independent reviews P0=0? | **NO** (Integration unresolved P0 = **5**; other three not this file) |
| Live Projection / READY / B0 / pin / `ci-aggregate` | STALE / null / UNKNOWN / null / **absent** |
| Mass / Phase 7 | **NO-GO / OFF** |

**Unresolved P0 count: 5.**

Do not declare Phase 6.3.3 or 6.4 complete from this review.
