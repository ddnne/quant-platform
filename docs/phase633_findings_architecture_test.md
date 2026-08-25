# Phase 6.3.3 independent Architecture / Runtime / Test review

**Lane:** Architecture / Runtime / Test (independent; docs only; no code fix)  
**Freeze SHA:** `58133512e1e896f1e811d1fb597337aa8f53d965`  
**Parent strategy tip:** `cb9916e0` (commit subject names `HEAD cb9916e0 vs origin/main b5c326a`)  
**origin/main at freeze:** `b5c326a`  
**Mass / READY / Phase 7:** **NO-GO / not declared / OFF**. This file is not a GO.

Do **not** extract leftover occupancy from `daily_path.ts`. Do **not** split `cost_models.py` / `options_225_vol_series.py`. Size is not a split key. ADR §8.2 still **KEEP**s the three `execution` modules; the P0 is that the paper-runtime twin still *runs* paper.

Status vocabulary: **OPEN** / **HOLD** / **KEEP**. P0 = a claimed sole authority is a second live path, or a gate can be satisfied without the artifact it names. P1 = split / default / typecheck / selection honesty that is not currently a live GO. P2 = HOLD/KEEP register (do not “clean up”).

---

## Scoreboard

| ID | Topic | Sev | Status |
|----|-------|-----|--------|
| Issue 1 | Two `PaperExecutionService` / `run_paper` paths | P0 | **OPEN** |
| Issue 2 | `ProcessIsolatedRunner` defaults `sys.executable` | P1 | **OPEN** |
| Issue 3 | ReadyManifest vs publisher vs `ResearchReadinessService` | P1 | **OPEN** |
| Issue 4 | Catalog 2092 “active” as fake selection | P1 | **OPEN** |
| Issue 5 | Leftover occupancy in `daily_path.ts` | P2 | **HOLD** (do not extract) |
| Issue 6 | Live math in `cost_models.py` / `options_225_vol_series.py` | P2 | **KEEP** (do not split) |
| Issue 7 | Tests: source-string / paraphrase vs mechanism | P1 | **OPEN** |
| Issue 8 | `skipLibCheck` hiding binding mismatch | P1 | **OPEN** |
| Issue 9 | Ops MCP still JS | P1 | **OPEN** |

**Unresolved P0 count: 1** (Issue 1).

---

## Issue 1 P0 — two `PaperExecutionService` / `run_paper` paths

**severity:** P0  
**affected:** `packages/product/execution/paper_service.py`; `packages/research_runtime/paper_runtime/execution.py`; `packages/research_runtime/strategies/paper/runner.py`; `packages/product/execution/__init__.py`; `packages/research_runtime/strategies/paper/types.py`; `tests/test_paper_runtime_execution_not_armed.py`; `tests/test_paper_execution_service.py`; `tests/test_paper_pipeline.py`; `tests/test_paper_store.py`; `tests/test_paper_repo_financing_w86.py`  
**status:** **OPEN**

### Observed

There is **one** `run_paper` function (`strategies.paper.runner.run_paper`, `PAPER_RUNNER_VERSION = "0.7.0"`). There are **two** classes named `PaperExecutionService` that call it, plus a public `run_paper` import used outside the claimed choke point.

**Path A — claimed sole authority** (`execution.paper_service`):

- Package docstring: “the single positive capability that reaches the trusted paper runtime.”
- `PaperExecutionService.execute` re-derives StrategySpec hash and authorization id, optionally pins READY, resolves FeatureRefs, then calls `run_paper`.
- `PaperRunConfig.require_ready_snapshot` defaults **False** (`strategies/paper/types.py`). Empty `ready_snapshot_id` is accepted unless the caller opts in. The service still computes `data_snapshot_id(config.db_path)` from the **current** SQLite file.

**Path B — ADR §8.2 name-collision twin** (`paper_runtime.execution`):

```41:49:packages/research_runtime/paper_runtime/execution.py
    def execute(self, request: AuthorizedPaperExecutionRequest) -> PaperRunResult:
        if request.mode != "paper":
            raise ValueError("PaperExecutionService only accepts mode=paper")
        if not request.authorization_id:
            raise ValueError("authorization_id required")
        if not request.strategy_spec_hash:
            raise ValueError("strategy_spec_hash required")
        # Future: verify hash against StrategySpec, READY snapshot pin, FeatureRefs
        return run_paper(request.strategy, request.config, store=self._store)
```

Non-empty strings pass. Hash is not compared to a StrategySpec. READY pin and FeatureRefs are comments. The module defines a **second** `AuthorizedPaperExecutionRequest` (carries a live `strategy` object + `PaperRunConfig`) that is not `agents.types.AuthorizedPaperExecutionRequest`.

`paper_runtime.__init__` does not re-export the module. Production AST importers of `paper_runtime.execution` = **0** besides `tests/test_paper_runtime_execution_not_armed.py`. That test only asserts import identity and freeze flags (`CONTINUOUS_PAPER == "UNARMED"`, `helper.PaperExecutionService is not PaperExecutionService`). It never calls `helper.PaperExecutionService.execute`.

**Path C — direct `run_paper`:** `tests/test_paper_pipeline.py`, `test_paper_store.py`, and `test_paper_repo_financing_w86.py` import `strategies.paper.run_paper` and execute it. That is the engine under test. It is not an authority gate. `tests/test_paper_boundaries.py` bans HTTP/ingestion inside `strategies/paper/`; it does **not** ban a second `PaperExecutionService`.

ADR §8.2 / nav map: **KEEP** all three `execution` modules (core fill timing / paper-runtime helper / product paper service). This issue is not a delete demand. The helper is documented “not the authorized paper choke point” and then implements `execute()` as a working `run_paper` wrapper.

### Why P0

A claimed sole write-authority is false at import time. Same class name, different module, weaker gate, same `run_paper`. An agent or future caller that `from paper_runtime.execution import PaperExecutionService` skips FeatureRef governance and READY pin. Tests certify the name collision, not that Path B cannot run paper.

`require_ready_snapshot=False` on Path A is a second honesty hole (unit-test default), not a second class. Folded here: the “authorized” path can still paper-run a mutable current DB when the pin is empty.

### Structural fix (do not delete the module)

- KEEP the three `execution` files (ADR §8.2).
- Make `paper_runtime.execution.PaperExecutionService.execute` fail closed (`NotImplementedError` / `PaperExecutionRejected("not the authorized choke point")`). Do not call `run_paper` from the twin.
- Keep `run_paper` as the engine; keep Path A as the only service that reaches it from agents.
- Add a **mechanism** test: constructing the twin and calling `execute` raises; do not only assert `is not`.
- Do not treat `require_ready_snapshot=False` as production READY. If Path A is ever armed, empty pin must refuse.

---

## Issue 2 P1 — `ProcessIsolatedRunner` defaults `sys.executable`

**severity:** P1  
**affected:** `packages/product/agents/isolated_runner.py`; `tests/test_process_isolated_runner.py`; `packages/product/agents/runtime.py`  
**status:** **OPEN**

### Observed

```64:71:packages/product/agents/isolated_runner.py
        self.allowed_binaries = frozenset(
            allowed_binaries
            or (
                sys.executable,
                "/usr/bin/true",
                "/bin/true",
            )
        )
```

Default allowlist is the **host interpreter**. `run()` forbids `;`, `&&`, `||`, `|`, `` ` ``, `$(`, newline in the joined argv. It does **not** forbid `-c`. `ProcessIsolatedRunner().run([sys.executable, "-c", "open('/tmp/x','w').write('x')"])` is policy-legal (no metacharacter). Env is scrubbed; `cwd` is not; the binary is still this checkout’s Python.

Module docstring: this is **not** a Cloudflare Sandbox. `AgentCapabilityRouter` is an in-process policy router. `ProcessIsolatedRunner` has **zero** production callers (only `tests/test_process_isolated_runner.py`).

Tests always pass an explicit `allowed_binaries=(sys.executable, ...)`. They never instantiate the default. `test_rejects_shell_metacharacters` uses `print(1); import os` (semicolon) — it does not prove `-c` without `;` is rejected. `test_allowlisted_true_binary` comments “python -c is NOT allowlisted unless executable alone with safe argv”; the code does not implement that comment.

### Why P1

Isolation foundation is unused, so this is not a live escape. The default + tests would green-light a host-Python `-c` runner the moment anything constructs `ProcessIsolatedRunner()` without an allowlist. That is a runtime policy hole, not a missing extract.

### Structural fix

- Default `allowed_binaries` must not include `sys.executable` (empty frozenset, or only `/usr/bin/true` / `/bin/true`).
- If Python is ever allowlisted, refuse `-c` / `-m` unless a closed argv schema says so.
- Mechanism test: default constructor + `[sys.executable, "-c", "print(1)"]` raises `IsolationRejected`.

---

## Issue 3 P1 — ReadyManifest vs publisher vs `ResearchReadinessService`

**severity:** P1  
**affected:** `packages/research_runtime/paper_runtime/snapshot.py` (`publish_ready_snapshot`, `ReadySnapshot`); `packages/research_runtime/paper_runtime/snapshot_publish_policy.py`; `packages/research_runtime/paper_runtime/snapshot_read.py`; `packages/research_runtime/paper_runtime/ready_policy.py`; `packages/product/research/readiness.py`; `tests/test_ready_coherence_integration.py`; `tests/test_phase7_pilot_construct.py`  
**status:** **OPEN**

### Observed

There is **no** typed `ReadyManifest`. Three objects share the word READY and do not share a schema.

| Object | Role claimed | What it actually does |
|--------|----------------|------------------------|
| `publish_ready_snapshot` | Gate + persist READY artifact | Runs `_evaluate_publication_gate`, then `ReadyPublicationPolicy.evaluate(..., quality_status="PASS", raw_manifest_ok=None)`, then writes `research-snapshot-manifest/v2` **dict** (`coverage_v2_proof`, `quality` object, `manifest_digest`). No `coverage_proof_digest` / `governed_membership_digest` / `raw_proof_digest` / `b0_quality_proof_digest` / `source_generation` / `applied_sync_generation` keys. |
| `ReadyPublicationPolicy` | “Sole READY eligibility decision” | Second gate. `collect_typed_evidence` defaults `NaturalKeyEvidence` to `"READY"` when the table is missing (`nk_state = "READY"`). `ValidationEvidence` stays `"PASS"` on `sqlite3.Error`. Publisher feeds `quality_status="PASS"` after the first gate already passed. |
| `ResearchReadinessService.mint` | Attestation only from verified immutable READY | Reads `describe_snapshot` / `latest_ready_snapshot`, then requires `coverage_proof_digest` **or** `coverage_digest`, `governed_membership_digest` **or** `membership_digest`, `raw_proof_digest`, `b0_quality_proof_digest` **or** `quality_digest`, `source_generation` **or** `export_generation`, `applied_sync_generation` **or** `apply_generation`. **Zero** production or test callers of `ResearchReadinessService()` / `.mint()`. |
| `VerifiedResearchReadiness` | Mass start type | Plain dataclass + HMAC. `tests/test_phase7_pilot_construct.py` builds it with `"sha256:" + ("ab" * 32)` under `QUANT_READINESS_HMAC_SECRET`. Scheduler construct does not call the publisher or `mint()`. |

`describe_snapshot` verifies sidecar digest, immutability, and `data_snapshot_id` match. That is a real mechanism for **Path A artifacts**. It does not emit the digest names `mint()` requires. A real published snapshot would fail `mint()` (fail-closed). Tests never connect the three.

`test_ready_coherence_integration.py`: `test_policy_constructs` is `assert ReadyPublicationPolicy() is not None`. `test_publish_ready_blocked_when_coverage_partial` is the one publisher mechanism row.

### Why P1 (not P0)

Mass still cannot start: `start_mass_catalog_eval` raises; production does not call `mint()`. A forged dataclass with the HMAC secret can **construct** `MassResearchScheduler` in tests; it cannot run the 2000-catalog eval. The split is architectural: attestation schema ≠ publisher manifest ≠ policy evidence. Alias fallbacks on `mint()` are a future weakening surface.

Do not invent a fourth READY writer. Do not declare production READY.

### Structural fix

- One typed manifest (fields the publisher writes). `mint()` reads those fields only — drop alias names until the publisher emits them.
- `ReadyPublicationPolicy` must not default natural-key / validation to PASS on missing tables.
- Publisher must not pass canned `quality_status="PASS"`; pass the status `_evaluate_publication_gate` measured.
- Mechanism test: `publish_ready_snapshot` (or a fixture that is that manifest) → `ResearchReadinessService.mint()` round-trip; hand-built `VerifiedResearchReadiness` is not a substitute for that row.

---

## Issue 4 P1 — catalog 2092 active as fake selection

**severity:** P1  
**affected:** `packages/product/research/catalog_active.py`; `packages/product/research/phase7_pilot.py`; `packages/product/research/catalog_compiler.py`; `tests/test_catalog_active_legacy.py`; `tests/test_phase7_pilot_construct.py`; `specs/research_catalog/manifest.json`  
**status:** **OPEN**

### Observed (measured at this SHA)

```
compiled 2254
active   2092
legacy   162
pilot    2092   (== active)
worker   2254
park     17
summary  go=False, not_a_pass=True, n_active_is_not_a_quality_metric=True
```

`pilot_candidates()` **is** `active_logic_ids()` (`catalog_active.py:63-69`). Active = countable ∩ compiled − unique22 park − generation-disabled clones with no Worker body. That is an inventory remainder of the frozen 2254 map, not a selection.

`MassResearchScheduler.select_pilot_hypotheses` does not consult `pilot_candidates()` / `catalog_kind`. It accepts any 2–32 distinct strings:

```155:162:packages/product/research/phase7_pilot.py
    def select_pilot_hypotheses(self, hypotheses: Sequence[str]) -> tuple[str, ...]:
        ids = tuple(str(h).strip() for h in hypotheses if str(h).strip())
        if len(set(ids)) != len(ids):
            raise MassResearchDisabledError(
                "pilot hypotheses must be semantically distinct"
            )
        self._require_pilot_n(len(ids))
        return ids
```

`tests/test_phase7_pilot_construct.py` pins `select_pilot_hypotheses(["h0", … "h7"]) == tuple(ok)`. `tests/test_catalog_active_legacy.py` pins `pilots == active` and `n_pilot_candidates == n_active`. The fake selection is the **test contract**.

`generation_enabled` is False on compiled rows. `start_mass_catalog_eval` still raises. `summary()["go"]` is False. AND/+N remain stopped. Worker `catalog_ids.ts` still emits n=2254 with no `catalog_kind`.

### Why P1 (not P0)

Naming 2092 rows `pilot_candidates` does not start Mass. Wiring that helper (or treating 2092 as a quality/GO universe) would restore AND-as-product without flipping freeze flags. 08-22 product is combination/funds from simple theses, not 2092 AND rows as inventory.

### Structural fix

- Keep freeze n=2254. Do not YAML `+N`. Do not report 2092 as a product win.
- `pilot_candidates()` must not be an alias of the 2092 remainder until a dated brief factorizes family+template+params. Empty / explicit allowlist is honest; 2092 is not a pilot.
- If `select_pilot_hypotheses` stays, intersect with a real candidate set and refuse unknown / legacy / parked IDs. Tests must not pin `"h0"` or `pilots == active`.

---

## Issue 5 P2 HOLD — leftover occupancy (do not extract)

**severity:** P2 (register, not a cleanup ticket)  
**affected:** `platform/workers/research-mass-eval/src/daily_path.ts`; `packages/product/research/unique_logic/constants.py` (`UNIQUE22_PARK_REASONS`); `platform/workers/research-mass-eval/src/combo_gates.test.ts`  
**status:** **HOLD**

`daily_path.ts` is 1682 lines at this SHA. Combo-gate extract (`combo_gates.ts`) and PIT-entry extract already landed. Unique-22 leftover (`event_pre_mom_agree_hold` uses `momentumAt(entryIdx)`, not combo `pre_mom` `entryIdx-1`; month-start leftover; leftover CS books) **stays** in `daily_path.ts` under `if (!comboImpl)`.

Unifying leftover with `comboEventGateOk` **rewrites occupancy**. Extracting leftover into a new file without occupancy-equal re-eval is the same rewrite. `phase63_refactor_plan.md` lane 3 HOLD still holds.

This review does **not** demand extract. Source-string in `combo_gates.test.ts` (“unique-22 leftover keeps pre_mom occupancy and month_start dd>05”) is a HOLD detector, not a substitute for combo **mechanism** tests (those already call `comboEventGateOk("pre_mom", …)`).

---

## Issue 6 P2 KEEP — live math (do not split `cost_models`)

**severity:** P2 (register, not a cleanup ticket)  
**affected:** `packages/product/research/cost_models.py` (2210 LOC); `packages/product/research/options_225_vol_series.py` (1140 LOC); `tests/test_cost_models_liquidity_linked.py`; `tests/test_cost_models_repo_linked.py`; `tests/test_cost_models_short_cost_w85.py`  
**status:** **KEEP**

Transaction / vol / MTM / repo / short / leverage formulas stay together. Size is not a split key. Fake-splitting a numerator from its denominator is a rewrite dressed as a refactor. Tests are already split by family; production math is not.

This review does **not** demand splitting `cost_models.py`.

---

## Issue 7 P1 — tests: source-string / paraphrase vs mechanism

**severity:** P1  
**affected:** listed tests below; `docs/phase63_test_audit.md` classes  
**status:** **OPEN**

Mechanism tests exist (Path A paper execute, combo `pre_mom` boolean, catalog partition, isolated-runner unknown binary, Mass construct fail-closed). Several **named** architectural claims are only greps or paraphrases:

| Claim | What the test actually does | Mechanism missing |
|-------|-----------------------------|-------------------|
| Path B is “not armed” | `test_paper_runtime_execution_not_armed.py` import identity + freeze constants | `helper.PaperExecutionService(store).execute(...)` must raise; must not call `run_paper` |
| Isolation refuses host Python `-c` | `test_process_isolated_runner.py` rejects `print(1); import os` (semicolon) and unknown `/usr/bin/curl` | Default allowlist; `-c` without `;` |
| READY attestation from snapshot | No `ResearchReadinessService.mint` test | Publisher → mint round-trip |
| Policy is the sole READY gate | `assert ReadyPublicationPolicy() is not None` | `evaluate()` on empty/PARTIAL DB without going through publisher |
| Pilot selection | `select_pilot_hypotheses(["h0"…])`; `pilots == active` | Refuse non-catalog / legacy IDs |
| Worker leftover occupancy | `combo_gates.test.ts` `readFileSync(daily_path.ts)` string slice | Acceptable as HOLD detector; do not replace `comboEventGateOk` rows |
| Comment / CLI paraphrases | `test_pipeline_otc_index_text.py` asserts `"Does not fetch live HTML"` in source; `test_immutable_artifact.py` asserts `"does not resurrect TOCTOU"` / `"never runs that CLI sequence"`; `test_verify_ci_script.py` / `test_verify_all_script.py` substring pins; `test_worker_extracted_helpers.py` greps `*.ts` only | Comments can move; JS Ops MCP is invisible to the `*.ts` glob (Issue 9) |
| `n_active` is not a pass | `test_catalog_active_legacy.py` repeats `go is False` / `not_a_pass` / `n_active_is_not_a_quality_metric` | Honest, but pins 2092 as `pilot_candidates` (Issue 4) |

`phase63_test_audit.md`: combinatorics and dual-runtime echo are cost; named invariants (PIT, receipts, false-COMPLETE, immutable READY, Mass fail-closed) must execute. This freeze still spends assertions on comments and on the 2092 alias.

Do not add more source-string paraphrases of leftover occupancy or live math. Do not delete the combo leftover grep until a mechanism occupancy-equal test exists — and do not write that test as a reason to extract leftover (Issue 5 HOLD).

---

## Issue 8 P1 — `skipLibCheck` hiding binding mismatch

**severity:** P1  
**affected:** `platform/workers/research-mass-eval/tsconfig.json`; `platform/workers/research-mass-eval/src/types.ts`; `platform/workers/research-mass-eval/worker-configuration.d.ts`; `platform/workers/research-mass-eval/src/ai_gateway_client.ts`; `platform/workers/research-mass-eval/wrangler.toml`; `platform/workers/research-ai-gateway/src/index.ts` (`GatewayEnv`); `platform/workers/research-ai-gateway/worker-configuration.d.ts`; `platform/workers/quant-ops-mcp/tsconfig.json`; `platform/workers/quant-ops-mcp/src/cloudflare.d.ts`  
**status:** **OPEN** (P632B-03 GATEWAY_TOKEN-over-binding remains HOLD for auth design)

### Observed

Every product worker `tsconfig.json` sets `"skipLibCheck": true`.

**mass-eval**

- Hand-written `src/types.ts` `Env`: `DB?`, `AI_GATEWAY?`, `MASS_EVAL_TOKEN?`. No `GATEWAY_TOKEN`.
- Generated `worker-configuration.d.ts` (`wrangler types --include-runtime=false`): `DB` and `AI_GATEWAY` required; vars as string literals; **no** `MASS_EVAL_TOKEN`; **no** `GATEWAY_TOKEN`.
- `wrangler.toml` binds `STRUCTURED_BUCKET`, `DB`, `AI_GATEWAY`. Secrets `MASS_EVAL_TOKEN` / `GATEWAY_TOKEN` are not in the generated Env.
- `ai_gateway_client.ts` still:

```23:26:platform/workers/research-mass-eval/src/ai_gateway_client.ts
function gatewayToken(env: Env): string | undefined {
  const rec = env as Env & { GATEWAY_TOKEN?: string };
  return rec.GATEWAY_TOKEN;
}
```

Cast + `skipLibCheck` means `tsc --noEmit` cannot see that the service-binding path requires a secret the generated Env does not declare. Unbound token still fail-closes at runtime (`gateway_token_unbound`). Binding identity is still not the auth (P632B-03 HOLD).

**ai-gateway**

- `GatewayEnv` has `GATEWAY_TOKEN?`, `MASS_EVAL_TOKEN?`, `BUDGET_LEDGER?`.
- Generated Env: `AI`, `BUDGET_LEDGER` only. Token secrets absent.

**ops-mcp** (also Issue 9)

```1:15:platform/workers/quant-ops-mcp/tsconfig.json
{
  "compilerOptions": {
    "allowJs": true,
    "checkJs": false,
    "noEmit": true,
    ...
    "skipLibCheck": true
  },
  "include": ["src/**/*.js", "src/**/*.d.ts"]
}
```

`checkJs: false` + `skipLibCheck: true` → `npm run typecheck` does not typecheck production JS and does not check `worker-configuration.d.ts` / `@cloudflare/workers-types` against `src/cloudflare.d.ts` (local D1 stub vs generated `OAUTH_KV` / `OPS_DB` / `MCP_OBJECT`).

### Why P1 (not P0)

Runtime still denies unbound `GATEWAY_TOKEN`. This is not a merge-gate green-lie by itself (Independent B CI P0s are out of this lane). Typecheck cannot catch Env ↔ wrangler ↔ cast drift. Turning `skipLibCheck` off without aligning Env would surface the mismatch; leaving it on hides it.

### Structural fix

- Put secrets that code reads on the generated Env (or stop reading undeclared secrets).
- Drop the `Env & { GATEWAY_TOKEN?: string }` cast or replace it with a typed field; do not use the cast to satisfy `tsc`.
- `skipLibCheck: false` on workers that claim `npm run typecheck` as CI; fix the errors, do not re-enable to green.
- Ops MCP: `checkJs: true` or migrate (Issue 9). Local `cloudflare.d.ts` must not shadow generated bindings.

Do not close P632B-03 by guessing `CF-Worker` as auth.

---

## Issue 9 P1 — Ops MCP still JS

**severity:** P1  
**affected:** `platform/workers/quant-ops-mcp/src/*.js` (10 files; `domain.js` 939 LOC); `platform/workers/quant-ops-mcp/tsconfig.json`; `platform/workers/quant-ops-mcp/package.json`; `tests/test_worker_extracted_helpers.py`  
**status:** **OPEN**

### Observed

Production Ops MCP `main = "src/index.js"`. Sibling product workers are TypeScript. `domain_policy.js` **was** extracted (honest projection / SLA / locators). SQL presentation and tool dispatch **remain** in `domain.js` (`db.prepare(...)` throughout: projection, coverage, READY snapshot metadata, watermarks, storage-plane counts).

`package.json` `"typecheck": "tsc --noEmit"` with `checkJs: false` (Issue 8) is a no-op over the JS body. Tests are `node --test test/*.test.mjs` (auth / mcp / domain-d1 / quota) — those are mechanism tests for the JS surface, not a type boundary.

`tests/test_worker_extracted_helpers.py` globs `*/src/**/*.ts` only. Ops MCP JS cannot fail that structural suite.

Public surface stays read-only MCP. This review does not demand SQL in MCP, ingest, delete, or READY publish. Do not grow the JS worker’s authority.

### Why P1

Ops MCP is the live `workers_dev=true` OAuth callback host. It is the only product worker whose production source is untyped JS while CI advertises `typecheck`. Presentation still owns SQL after a policy extract. That is an authority-language split vs mass-eval / gateway / ingestion, not a reason to rewrite math or occupancy.

### Structural fix

- Either `checkJs: true` + real `Env` (generated types, no stub D1) **or** a typed `src/*.ts` port that preserves the read-only tool set.
- Keep `domain_policy.js` as policy; do not move SQL into it.
- Point `test_worker_extracted_helpers` at first-party JS as well, or a Worker-local test, so Ops MCP is not invisible.
- Do not add query/sql/fetch/ingest/delete/READY-publish tools.

---

## Unresolved P0 count

**1** — Issue 1 (two `PaperExecutionService` / `run_paper` paths).

Issue 5 leftover occupancy and Issue 6 live math are **HOLD / KEEP**. They are not unresolved P0s and must not be scheduled as extracts.

Mass / READY / Phase 7 remain **NO-GO / not declared / OFF**. Do not treat 2092, a green `tsc` with `skipLibCheck`, or a hand-built `VerifiedResearchReadiness` as a pass.
