# Independent review B — CI skip and authority

**Lane:** P632 independent B (CI / merge-gate / token / budget / R2 / catalog)  
**Freeze HEAD:** `a48c600a845b1e8220d299becb22d04b4d28b2ff` (`docs/p632-ind-B-ci-authority` from `grok/phase63-ci-source-closure`)  
**origin/main:** `b5c326a7f612563f2da4a84f08063a307ec38e0a`  
**Fetched live:** GitHub `ddnne/quant-platform` branch protection + commit statuses + Actions workflows; Wrangler `quant-platform-ci-aggregate` deployments  
**Mass / READY / Phase 7 Controlled Pilot:** **NO-GO / null / OFF**. This file is not a GO.

Wave-0 (`docs/reviews/P632_wave0_live.md`) saw protection **OFF** and check-runs **0**. This freeze re-measures: protection is **ON** and requires context `ci-aggregate`, but **no producer has posted that context** and the Worker named in the docs **does not exist** on the Cloudflare account.

Status vocabulary: **OPEN / FIXED**. P0 = merge-gate or write-authority can lie. P1 = residual coupling / competing writer / honesty drift that is not a GO.

---

## Scoreboard

| ID | Topic | Sev | Status |
|----|-------|-----|--------|
| P632B-01 | `verify_all` skip vs `verify_ci` authority | P0 | **OPEN** (scripts split FIXED; merge gate does not run `verify_ci`) |
| P632B-02 | Branch protection `ci-aggregate` vs actual GitHub checks | P0 | **OPEN** |
| P632B-03 | Shared `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | P1 | **OPEN** (header mix-up FIXED) |
| P632B-04 | Edge budget double-spend | P0/P1 | **FIXED** same-DO occupancy; **OPEN** P1 residuals |
| P632B-05 | R2 child 409 / Python TOCTOU writer as authority | P0/P1 | **FIXED** Worker 409; **OPEN** Python writer |
| P632B-06 | Active / Legacy catalog mix | P1 | **FIXED** Python registry; **OPEN** Worker/eval mix |
| P632B-07 | GitHub Actions presence (must be absent) | P0 | **FIXED** (absent; do not add) |

Independent P0 unresolved: **2** (P632B-01, P632B-02). Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, or READY.

---

## P632B-01 — CI skip / `verify_all` vs `verify_ci`

**severity:** P0  
**affected:** `scripts/verify_all.sh`; `scripts/verify_ci.sh`; `tests/test_verify_all_script.py`; `tests/test_verify_ci_script.py`; `docs/ci/workers_builds.md`; `scripts/README.md`; `tests/README.md`  
**status:** **OPEN** (the two scripts exist and are tested; the merge gate is not `verify_ci`)

### Observed

`scripts/verify_all.sh` is still the skippable pre-push helper:

- Workers: only `quant-ops-mcp`, `research-ai-gateway`, `research-mass-eval` (lines 18–22). The three ingestion workers are **not in the list**.
- Missing `node_modules` → `skip — node_modules missing` unless `VERIFY_NPM_CI=1` (lines 80–91).
- Typecheck / build only if `VERIFY_NPM_TYPECHECK=1` / `VERIFY_NPM_BUILD=1` (default off).
- Missing `.venv` still runs other steps, then fails closed at the end (lines 40–55, 122–125).
- Comment at line 3 correctly names `scripts/verify_ci.sh` as “Authoritative CI (mandatory, no skips)”.

`scripts/verify_ci.sh` is the no-skip script (`164f18a`, IR schema pin `83f71dc` / `a48c600`):

- Fails if `.venv` missing; **no** system-python fallback (lines 41–50).
- `pip install -e ".[dev]"`, `pytest tests/`, catalog compile + `catalog_ids` freeze, Evaluation IR golden + `schema.json` + py/ts codecs.
- All **six** product workers: `package-lock.json`, `npm ci`, `npm test`, `npm run typecheck`, `wrangler deploy --dry-run`, `wrangler types`.
- Never `--legacy-peer-deps`; never skip missing `node_modules`; no `VERIFY_*` flags.
- Tests pin that (`tests/test_verify_ci_script.py`).

The same tests **pin the hole**: `tests/test_verify_ci_script.py:58-59`

```python
assert "ci-aggregate" not in src
assert len(WORKERS) == 6
```

`platform/workers/ci-aggregate` is a seventh Worker. Authoritative CI does not typecheck, test, or dry-run the process that is supposed to post the required GitHub status.

### Why this is still P0

`docs/ci/workers_builds.md` still tells operators:

1. Local pre-push = `scripts/verify_all.sh` (line 84–86). It does **not** name `verify_ci.sh`.
2. Mandatory CI = per-lane `npm ci && npm test` + POST six receipts to `/v1/receipts` (lines 52–56, 64–73, 97–122).
3. The GitHub required context is `ci-aggregate`, not “`verify_ci.sh` exited 0”.

So three different authorities exist:

| Surface | What it runs | Skip? |
|---------|--------------|-------|
| `verify_all.sh` | pytest + 3 research workers `npm test` | yes (`VERIFY_*`, missing `node_modules`, ingestion absent) |
| `verify_ci.sh` | pytest + catalog + IR + 6 workers ci/test/typecheck/dry-run | no |
| GitHub required context | six lane **receipts** of `npm ci && npm test` (if anyone POSTs them) | Python, catalog freeze, IR, typecheck, dry-run, `ci-aggregate` itself **not in the batch** |

`tests/README.md` still documents only `scripts/verify_all.sh` as the pre-push entry. A green `verify_all` or a green `ci-aggregate` status is **not** a `verify_ci` run. That is CI skip of the Python plane and of the gate Worker.

### Structural fix

- Make the merge-gate receipt command `scripts/verify_ci.sh` (or an equivalent seventh receipt that cannot be `npm test` on one Worker).
- Cover `platform/workers/ci-aggregate` in `verify_ci.sh` (stop asserting the name is absent).
- Point `docs/ci/workers_builds.md` and `tests/README.md` at `verify_ci.sh` as mandatory CI; keep `verify_all.sh` labeled helper-only.

Do not treat “`verify_ci.sh` exists” as FIXED for merge authority.

---

## P632B-02 — Branch protection bypass / `ci-aggregate` vs actual GitHub checks

**severity:** P0  
**affected:** GitHub `ddnne/quant-platform` `main` protection; `platform/workers/ci-aggregate/`; `docs/ci/workers_builds.md`  
**status:** **OPEN**

### Live GitHub (this freeze)

```
GET /repos/ddnne/quant-platform/branches/main/protection
  required_status_checks.strict = true
  contexts = ["ci-aggregate"]
  checks = [{context: "ci-aggregate", app_id: null}]
  enforce_admins = true
  allow_force_pushes = false
  required_approving_review_count = 0
  restrictions = null

GET /repos/ddnne/quant-platform/commits/b5c326a…/status  → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/b5c326a…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/a48c600…/status → total_count: 0
GET /repos/ddnne/quant-platform/actions/workflows → total_count: 0
```

Wrangler: `quant-platform-ci-aggregate` **does not exist** on account `11233bca08d134a9b738eaa46b9751d9` (`code: 10007`).

### What the tree implements

`platform/workers/ci-aggregate/src/index.ts`:

- `REQUIRED_WORKERS` = the six product Workers (lines 4–11).
- `evaluateReceipts` fail-closed on missing / duplicate / unknown worker, SHA mismatch, or any `fail` (lines 131–183). PR comments are not inputs (`collectReceipts`, test “does not treat a PR comment as a success signal”).
- Success posts GitHub **commit status** context `ci-aggregate` via `POST /repos/{repo}/statuses/{sha}` (lines 216–254, 317–335).
- Unbound `GITHUB_STATUS_TOKEN` → HTTP **503**, nothing posted (lines 293–303). That part is fail-closed.
- **`POST /v1/receipts` has no caller authentication.** Anyone who can reach the host can submit a six-pass batch. `wrangler.toml` sets `workers_dev = true` so the host is a public `*.workers.dev` URL once deployed (`docs/ci/workers_builds.md:93-95`).

`app_id: null` on the required check means GitHub does **not** bind the context to this Worker (or any GitHub App). A PAT with `repo:status` can `POST` `state=success` `context=ci-aggregate` for any SHA **without** lane receipts. That is the bypass the required-check configuration actually enforces.

Cloudflare Workers Builds, if connected, posts **check-runs** (per-worker, watch-path skippable). Those check-runs are **not** the required context. `docs/ci/workers_builds.md:31-34,139-142` says that is intentional. Live, they are also **0**.

### Why it matters

Branch protection currently requires a context that:

1. has never been posted on `origin/main` or this freeze SHA,
2. is not produced by a deployed Worker,
3. is not an app-bound check-run,
4. can be minted by any `repo:status` token,
5. after deploy, can also be minted by an unauthenticated six-receipt POST to `workers.dev`.

`required_approving_review_count = 0` and `restrictions = null` add no second factor. `enforce_admins = true` only means admins also need that forgeable status.

This is not “CI passed”. It is a named required context with no honest producer.

### Structural fix

- Deploy `quant-platform-ci-aggregate` only after inbound auth (HMAC / CF Access / mTLS) on `/v1/receipts`.
- Bind the required check to an **app** (or stop using a raw commit-status context as the sole gate).
- Until a real `success` exists on the SHA, do not merge to `main`. Do not PAT-green the context.
- Require `verify_ci` (P632B-01), not six `npm test` strings.

---

## P632B-03 — Shared token authority (`GATEWAY_TOKEN` vs `MASS_EVAL_TOKEN`)

**severity:** P1  
**affected:** `platform/workers/research-ai-gateway/src/index.ts`; `platform/workers/research-mass-eval/src/ai_gateway_client.ts`; `platform/workers/research-ai-gateway/src/index.test.ts`; both `wrangler.toml`  
**status:** **OPEN** (cross-header substitute **FIXED**)

### FIXED

Gateway `authorized()` compares **only** `X-Gateway-Token` to `env.GATEWAY_TOKEN` (`index.ts:40-47`). Unbound token denies. Tests pin:

- `X-Mass-Eval-Token` is not accepted as the gateway header.
- `MASS_EVAL_TOKEN` value in `X-Gateway-Token` is not accepted.
- Unbound `GATEWAY_TOKEN` denies even if `MASS_EVAL_TOKEN` is set.

Mass-eval HTTP routes authorize with `env.MASS_EVAL_TOKEN` / `X-Mass-Eval-Token` only (`http_routes.ts` `/v1/*`). Different secret, different header.

### OPEN

Mass-eval still **sends** `GATEWAY_TOKEN` over the `AI_GATEWAY` service binding:

```23:52:platform/workers/research-mass-eval/src/ai_gateway_client.ts
function gatewayToken(env: Env): string | undefined {
  const rec = env as Env & { GATEWAY_TOKEN?: string };
  return rec.GATEWAY_TOKEN;
}
// ...
    "X-Gateway-Token": token,
```

`Env` in `types.ts` does not declare `GATEWAY_TOKEN`. `research-mass-eval/wrangler.toml` documents `MASS_EVAL_TOKEN` only. The client casts the extra secret in. Service binding `AI_GATEWAY` (`wrangler.toml:40-42`) already restricts the network path; the extra bearer is a **shared secret** copied onto the caller.

P631 item S called this residual coupling. It is still the same. Brief wanted internal caller capability (binding identity), not a second copy of `GATEWAY_TOKEN`.

If operators bind the **same** string to both secrets, the test-pinned header separation is cosmetic. If they do not bind `GATEWAY_TOKEN` on mass-eval, propose/gateway calls fail closed (`gateway_token_unbound`) — Mass remains NO-GO either way.

### Structural fix

Authenticate the service-binding caller (CF Worker identity / stub RPC) and **stop** reading `GATEWAY_TOKEN` inside mass-eval. Keep `MASS_EVAL_TOKEN` as the public `/v1/*` secret only.

---

## P632B-04 — Edge budget double-spend

**severity:** P0 (same-DO occupancy) **FIXED**; P1 residuals **OPEN**  
**affected:** `platform/workers/research-ai-gateway/src/budget_do.ts`; `src/index.ts`; `src/schema.ts`; `src/budget_do.test.ts`  
**status:** mixed

### FIXED (P0 occupancy)

Commit `8afe0a2` landed a Durable Object ledger. `/v1/complete` **reserves before** `env.AI.run` (`index.ts:183-220`). Presence of `budget_id` is not enough: unbound `BUDGET_LEDGER` → 503.

`budget_do.ts`:

- Occupancy = `used + reserved` (`occupancy()`, `insufficient()`).
- Same idempotency key returns the existing reservation without a second increment (test “without double-spend”).
- Exhausted reserve does not mutate counters.
- Reconcile converts reserved → used; release / expired lease returns reserved capacity.
- `auto_promotion: false` is pinned.

Same-`budget_id` concurrent spend of the pilot cap (16 model calls / $20) is no longer “string present, provider called”.

### OPEN (P1)

1. **`schema.ts` still advertises the stub.** Lines 147–151 and the missing-id error at 186:

   > “Fail-closed budget stub. A persistent Durable Object ledger is not in this commit.”  
   > “Presence of budget_id is not a transactional reserve/charge — Edge ledger is not yet transactional.”

   Codec comment contradicts `index.ts` + `budget_do.ts`. Honesty drift: a later reviewer will treat §19 as still DEFERRED **or** treat the stub comment as the SoT and skip the ledger.

2. **Caller-chosen `budget_id` = new DO = new cap.** `idFromName(budgetId)` (`index.ts:112`). `propose_thesis.ts:305-309` forwards `body.budget_id` or empty (empty fails closed). Each distinct id gets `PILOT_BUDGET_CAPS` again (`max_parallel_experiments: 2` is per-ledger, not global). That is how you double-spend the **pilot** envelope.

3. **Default idempotency is `crypto.randomUUID()`** (`index.ts:193-194`). Mass-eval `completeViaGateway` does **not** send `Idempotency-Key` (only occurrence of the header in the tree is the gateway). HTTP retries and the 3×2 propose loop mint new leases.

4. **Reconcile failure after a successful `AI.run` is ignored.** `index.ts:234-259` `await budgetRpc(..., "/reconcile", ...)` does not check `.ok`; the handler still returns `ok: true`. Lease TTL 1800s then `recoverExpired` returns reserved capacity while the provider call already happened.

5. Reconcile **adds actual usage without a cap check**. Actual > reserved can drive `used` over `PILOT_BUDGET_CAPS` after the fact.

### Structural fix

Rewrite `decodeGatewayRequest` comments/errors so the ledger is the SoT. Bind one ledger per experiment/plan (not per free-form id). Default idempotency from canonical request digest. Fail the HTTP response if reconcile fails; charge `max(reserved, actual)` under the cap.

---

## P632B-05 — R2 child conflict / Python TOCTOU writer as authority

**severity:** P0 Worker overwrite **FIXED**; P1 Python writer **OPEN**  
**affected:** `platform/workers/research-mass-eval/src/http.ts`; `src/http.test.ts`; `packages/product/research/r2_io.py`; `cf_mass_eval_run.py`; `cf_mass_eval_stage.py`; `cf_mass_eval_job.py`; `tests/test_immutable_artifact.py`  
**status:** mixed

### FIXED (Worker)

`putJsonCreateOnly` (`http.ts:113-138`): `onlyIf: { etagDoesNotMatch: "*" }`; existing key with a **different** digest → `conflict: true`, `status: 409`, no overwrite. Same digest → idempotent success.

`putChildrenThenManifest` (`http.ts:207-263`): any child `conflict` **does not mint a manifest** (`eef69ef`). Tests (`http.test.ts:107-118, 221-242`):

- different content → 409, original body kept, `putOrder` does not include a second put;
- child digest mismatch → `ok: false`, no `job/manifest.json`.

Worker `onlyIf` remains the immutable create-if-absent authority.

### OPEN (Python CLI still writes)

`packages/product/research/r2_io.py` documents head-then-put **TOCTOU** and refuses `authoritative=True` (`python_cli_put_is_not_immutable_authority = True`). Tests pin the docstring (`test_immutable_artifact.py:56-76`). P631 F said: do **not** treat “TOCTOU recorded in tests” as done.

Callers still put the **same** `research/mass_eval/job=…` keys the Worker uses:

| Caller | Keys |
|--------|------|
| `cf_mass_eval_run.put_local_fallback_artifacts` | manifest / input_plan / batch_summary / results / screens / ranking |
| `cf_mass_eval_stage` | `research/mass_eval/job={id}/panels/{period}.json` |
| `cf_mass_eval_job` | panels cache meta |

`wrangler r2 object put` has no `onlyIf`. A CLI miss-then-put **overwrites** a Worker-created object. `authoritative=False` is a flag, not a fence.

### Structural fix

Delete or dry-run-only the Python putters for job/manifest/child keys. Route all production artifact writes through the Worker create-only path. Keep `authoritative=True` refused.

---

## P632B-06 — Active / Legacy catalog mix

**severity:** P1  
**affected:** `packages/product/research/catalog_active.py`; `catalog_compiler.py`; `cf_mass_eval_job.py`; `platform/workers/research-mass-eval/src/catalog_ids.ts`; `tests/test_catalog_active_legacy.py`  
**status:** **FIXED** (Python partition); **OPEN** (Worker / eval still mixed)

### FIXED

`f9fb9a1` added an identity registry without deleting IDs and without YAML:

- Compiled freeze still **n = 2254** (`CATALOG_YAML_COUNT_AT_STOP`, `go is False`).
- Measured at this freeze: **active 2092 / legacy 162 / compiled 2254**.
- `active | legacy == compiled`, disjoint, unique-22 park is **legacy**, `pilot_candidates() == active`.
- Compiler v2 helpers re-export `catalog_active` and do **not** rewrite the v1 digest lock (`catalog_compiler.py:7-8`).

### OPEN

1. **Mass-eval Worker has no `catalog_kind` / active|legacy filter** (grep over `platform/workers/research-mass-eval` is empty). `/v1/mass-eval` will evaluate whatever `logic_id` the client sends, including the 162 legacy IDs.
2. **`catalog_ids.ts` header still locks n=2254** as the Worker emit (`catalog_ids.ts:1-4`). The active/legacy split is not in the generated file.
3. **`cf_mass_eval_job.default_logic_specs`** still does `py_by_id or yaml_by_id` over `load_catalog_specs()` (`cf_mass_eval_job.py:159-165`) — compiled remainder, not `active_logic_ids()`. Variable name `yaml_by_id` is leftover occupancy language.
4. Factorize n=2254 → family+template+params remains **OPEN** (P631 G). The v2 split classifies expanded rows; it does not unmix the freeze.

Not GO. Do not count 2092 as a new COMPLETE product.

### Structural fix

Worker and Python job builders refuse `catalog_kind == "legacy"` unless an explicit replay flag is set. Emit active-id lists next to `catalog_ids.ts` without changing the 2254 digest lock until a dated brief unfreezes n.

---

## P632B-07 — GitHub Actions presence (must be absent)

**severity:** P0 if present  
**affected:** no `.github/`; `README.md`; `docs/architecture.md`; ADR §3.2  
**status:** **FIXED** (absent)

- `git ls-files` has no `.github/` and no workflow YAML.
- `GET /repos/ddnne/quant-platform/actions/workflows` → **0**.
- Policy: CI/CD on Cloudflare, not GitHub Actions (`docs/architecture.md:28`; ADR non-goal “Adding GitHub Actions CI”).

Empty GHA is **not** a missing pipeline. Do **not** add `.github/workflows` to “fix” P632B-01/02. Those are Cloudflare + `verify_ci` + an authenticated aggregate status, not Actions.

---

## What this review does not claim

- Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Mass GO, Phase 7 Controlled Pilot ON.
- `verify_ci.sh` was executed at this HEAD (script/static tests only).
- `quant-platform-ci-aggregate` is live (Wrangler 10007: Worker does not exist).
- Independent P0 count is 0. It is **2** (P632B-01, P632B-02).

---

## Suggested close order (not work in this file)

1. P632B-02: do not merge `main` on a PAT `ci-aggregate` success. Auth the receipt POST or drop the unbound context.
2. P632B-01: required gate runs `verify_ci.sh` (including `ci-aggregate`).
3. P632B-05: stop Python TOCTOU puts on Worker keys.
4. P632B-04: schema honesty + one ledger + reconcile fail-closed.
5. P632B-03 / P632B-06: binding identity; Worker refuses legacy IDs.

Keep GitHub Actions absent (P632B-07).
