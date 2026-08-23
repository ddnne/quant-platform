# Phase 6.3.1 brief leak register vs current tree

**Brief:** Phase 6.3.1 Reproducibility & Authority Closure → 6.4 Live Evidence Closure → Phase 7 Controlled Pilot prep.  
**Named review SHA in brief:** `96264f0` — **not** the freeze (brief forbids pinning it).  
**`origin/main` at this audit:** `03cd1b1` (`docs: record coverage-gap audit; four PARTIAL stay uninvented`).  
**Local HEAD audited:** `e927b97` (six commits ahead of `origin/main`; not pushed).  
**Wave-1 freeze docs:** `docs/reviews/` remaining-audit files are dated at `03cd1b1`; several items below moved after that freeze. **This file is the re-diff vs current tree.**

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.1 COMPLETE, or Phase 7 GO.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.1 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

6.3.1 §19 still fails: Edge hard budget is a stub (`DEFERRED`); catalog is still 2254 expanded rows (`OPEN`); fabricated `catalog_path` remains (`OPEN`); Python R2 put is TOCTOU (`OPEN`); independent P0 unresolved ≠ 0; clean-venv pytest / Worker typecheck+build not proven at this HEAD; `origin/main` SHA does not match local HEAD.

6.4 §19 fails on live evidence: 22 COMPLETE held / **4 PARTIAL**; Projection **STALE**; B0 **UNKNOWN**; READY **null**; applied pin **unpinned**.

Phase 7 foundation types exist and stay **OFF**. That is not GO.

---

## A–X vs current tree

### A. Clean Python tests (tmp sqlite, tmp Ed25519, no production keys)

**status: OPEN** (fixtures FIXED; host PEM isolation and fresh-venv proof not closed)

| Sub-item | Status | Evidence |
|----------|--------|----------|
| `test_eval_loaders` tmp sqlite | **FIXED** | `tests/test_eval_loaders.py:9-11` writes `tmp_path / "ingestion.sqlite"`. Commit `4cc0a47`. |
| Receipt tests tmp Ed25519 | **FIXED** | `tests/conftest.py:183-221` `receipt_ed25519_keys` + `QUANT_RECEIPT_VERIFY_KEYS`; never the repo registry. `3e46c97`. |
| phase61 coverage tmp keys | **FIXED** | `tests/test_phase61_coverage_v2.py:68-75` autouse tmp registry. `3b933ec`. |
| JSDA COMPLETE injects tmp signer | **FIXED** | `tests/test_jsda_governed.py:245-256`, `test_jsda_repo_governed.py:155-166`, `test_jsda_corrections.py:121-132`. Fail-closed unsigned paths stay (`test_jsda_governed.py:329`). `5a168c7`. |
| Ambient proxy isolated | **FIXED** | `packages/data_plane/ingestion/common/http.py:24-28` `_http_trust_env()` default False. `331f3c4`. |
| Host PEM never read in pytest | **OPEN** | `packages/data_plane/storage/receipt_crypto.py:27-28,148-149` still loads `~/.config/quant-platform/receipt_signing_key.pem`. Readiness HMAC falls back to that PEM (`packages/product/research/readiness.py:112-124`). Tests that omit the fixture can still sign with operator material. A01 freeze (`docs/reviews/A01_python_clean_tests.md`) still describes this. |
| Fresh venv `pip install -e ".[dev]" && pytest -q` | **OPEN** | Brief §4 completion condition. Not executed at `e927b97`. `scripts/verify_all.sh` requires an existing `.venv` (`19-31`, `87-89`) and does not create one. |

Wave-1 P0-A1/A2 must not be re-opened. Residual is host private-key sandbox + unproven clean clone.

---

### B. 3 Workers `npm ci` without `--legacy-peer-deps`

**status: FIXED** (lockfiles) / **OPEN** (brief completion = ci + test + typecheck + build)

- Lockfiles regenerated without `--legacy-peer-deps`: `992ff41`. Ban remains in `scripts/verify_all.sh:3,9-10,80` and `scripts/README.md:17`.
- Workers: `platform/workers/research-mass-eval`, `research-ai-gateway`, `quant-ops-mcp`. Each has `typecheck` / `test` / `build` (dry-run deploy) in `package.json`.
- `verify_all.sh:67-84` runs `npm test` if `node_modules` exists; `npm ci` only when `VERIFY_NPM_CI=1`; **never** typecheck/build. Brief §5 completion not proven at this HEAD.

`--legacy-peer-deps` is not the remaining hole. Default pre-push does not exercise the full npm matrix.

---

### C. Receipt authority as transaction (verify before structured mutation)

**status: FIXED**

- JSDA: `require_jsda_receipt_authority()` at run start (`packages/data_plane/ingestion/jsda/archive.py:312`); structured `registrar.register` only after `authority is None` raises (`archive.py:452-466`). Same pattern: `jsda/corrections.py:320`, `jsda/repo_archive.py:289`. SUCCESS path requires authority (`jsda/receipts.py:20-28,50-56`). `5f95b8f`.
- JQ: `packages/data_plane/ingestion/pipeline.py:361-387` verifies `require_signed_receipt_authority()` **before** `reg.register`; missing authority returns `registered=0`.
- Raw-only recovery is a separate path; empty-raw SUCCESS is forbidden (`jsda/receipts.py:51-52`; JQ `jquants/receipts.py:74-75`).

---

### D. Pilot construct `require_valid`, no duck `bound=True`

**status: FIXED** (construct) — live B0/READY remain 6.4 **OPEN**

- `packages/product/research/phase7_pilot.py:75-84` type-checks `VerifiedResearchReadiness` then `require_valid(expected_snapshot_id=…)`. Duck `SimpleNamespace(bound=True)` is rejected (`tests/test_phase7_pilot_construct.py:136-146`). `AuthorizedEvaluationService` only from `bind_authorized_evaluation_service` (`phase7_pilot.py:33-47`). `24d7902`.
- Construct still requires `ResearchBudgetCapability`, `ExperimentPlan.ready_snapshot_id`, `ImmutableArtifactStore.create_if_absent` (`phase7_pilot.py:122-136`). `operator_override` cannot substitute (`117-120`).
- Live B0 PASS / READY digest on Cloudflare is **not** this lane. Residual: B0 **UNKNOWN**, READY **null**.

---

### E. Gateway typed decode + budget (no raw fallback). Edge DO budget ledger?

**status: FIXED** (typed decode) / **DEFERRED** (Edge DO ledger)

- Strict decode, no raw text fallback: `platform/workers/research-ai-gateway/src/index.ts:127-149` `decodeGatewayRequest` then `decodeTypedArtifact`; decode failure returns 400. `ccf486a`. Schemas: `schema.ts:11-18` (ResearchMemo / FeatureProposal / StrategySpec / SelectionDecision / Insight).
- `budget_id` required: `schema.ts:146-150,186-187` — “Fail-closed budget stub. A persistent Durable Object ledger is not in this commit.” Presence of `budget_id` is **not** reserve/reconcile.
- Mass-eval still sends `GATEWAY_TOKEN` (`research-mass-eval/src/ai_gateway_client.ts:23-47`) even with service binding `AI_GATEWAY` (`wrangler.toml:39-42`). Brief wanted internal caller capability, not shared bearer. Residual coupling **OPEN**; bind itself is **HUMAN** (item S).

6.3.1 §19 “Edge hard budget reserve/reconcile” is **not** met.

---

### F. Artifact two-phase commit (children then manifest). Python R2 TOCTOU?

**status: FIXED** (Worker) / **OPEN** (Python CLI TOCTOU)

- Worker: `putChildrenThenManifest` (`platform/workers/research-mass-eval/src/http.ts:176-209`) writes children then create-only manifest. Used from `index.ts:20,269,440`. Tests: `http.test.ts:114`. `4d0180f`.
- Python: `packages/product/research/r2_io.py:50-57,84-85` documents head-then-put **TOCTOU**; “Python CLI put is not the immutable authority.” Tests pin that (`tests/test_immutable_artifact.py:56-63`). Brief §9: do **not** treat “TOCTOU recorded in tests” as done.

---

### G. Catalog factorize not expand n. n=2254 expanded rows still?

**status: OPEN** (factorize) / compiled-n bug **FIXED**

- Manifest still expanded: `specs/research_catalog/manifest.json` `n: 2254`, `yaml_still_present: false`. `migration.jsonl` is **2254 lines**. Freeze: `packages/product/research/eval_flags.py:8-11` `CATALOG_AND_PLUS_N_STOPPED` + `CATALOG_YAML_COUNT_AT_STOP = 2254`.
- `n_logic_ids == 0` after YAML delete: **FIXED** — `unique_logic/catalog.py:151-171` `n` / `n_compiled` from compiled map (`e8bdf17`). Tests: `tests/test_unique_logic_catalog.py:176-178`.
- Factorize to family + template + parameter matrix: **not done**. `migration.jsonl` is still runtime load SoT (`catalog.py:180-211`). Brief §10 forbids counting expanded rows as the product.
- Combo +N expansion **HOLD** (identity freeze; `docs/reviews/A11_waste.md` A11-COMBO-PLUS-N-HOLD-IDENTITY). Do not unfreeze without a dated brief.

---

### H. Evaluation IR single authority + `golden.jsonl`

**status: OPEN** (single generated authority) / golden **FIXED**

- Shared golden: `specs/evaluation_ir/golden.jsonl` (10 vectors). Python `packages/product/research/evaluation_ir.py:11-20`; Worker `platform/workers/research-mass-eval/src/evaluation_ir.ts:7-14`. Both call `job_candidate_grade` / `jobCandidateGrade`. `7f2dc12`.
- Dual codecs remain (Python + TypeScript). Brief §11 recommended JSON Schema → generated types. Grade predicate is shared; encode/decode are still two implementations. Not “one unbypassable generated authority.”

---

### I. Ops projection/sync honesty (CURRENT never with `applied_cursor=null`; coverage UNKNOWN without active gen)

**status: FIXED** (semantics) / live pin **OPEN** (6.4)

- `platform/workers/quant-ops-mcp/src/domain.js:84-97` `applied == null` → `EXPORT_CURRENT_APPLY_UNPINNED` / `LAGGING_APPLY_UNPINNED` / `APPLY_UNPINNED`, **never CURRENT**. `domain.js:755-756,799`.
- No active generation → coverage **UNKNOWN**, last-known-good is not current COMPLETE (`domain.js:286-312,326`). Test: `test/domain-d1.test.mjs:296`.
- Live residual (`docs/phase62_residual_status.md:26-30,69`): Projection **STALE**; sync `applied_cursor=null`. Honesty of the code path is FIXED; the pin is not remote (item R).

---

### J. 4 coverage gaps honest (no floor bump)

**status: OPEN** (gaps remain PARTIAL) / floor-bump **HOLD** (forbidden)

Floors not shortened:

| Dataset | `history_target_start` | File |
|---------|------------------------|------|
| `equities_bars_daily_am` | `2024-01-04` | `collection_coverage.json:27-28` |
| `equities_earnings_calendar` | `2010-01-04` | `collection_coverage.json:59-60` |
| `equities_master` | `2006-08-13` | `collection_coverage.json:13-14` |
| `jsda_otc_bond_reference_prices` | `2002-08-02` | `collection_coverage.json:157-159` |

Live: 22 COMPLETE held / **4 PARTIAL** (`docs/phase62_residual_status.md:27-29`; `docs/reviews/A10_coverage_gaps.md`). Do not invent COMPLETE 23. Grain ADRs (snapshot vs month; official-index days) are 6.4 work, not a floor bump. POL-FLOOR-005 remains policy HOLD.

---

### K. `scripts/verify_all.sh`

**status: FIXED** (exists, fail-closed) / **OPEN** vs brief matrix

- Present: `scripts/verify_all.sh` (`e8e65ee`). Pytest + catalog freeze + worker `npm test`. Bans `--legacy-peer-deps`. No `wrangler deploy`. Missing `.venv` fails closed (`87-89`). Tests: `tests/test_verify_all_script.py`.
- Brief §16 also asked: Python **clean install**, schema/codegen drift, each Worker **npm ci + typecheck + dry-run build**. Those are not in the script. Optional `VERIFY_NPM_CI=1` is not default.

---

### L. Phase 7 pilot foundation OFF

**status: FIXED** (OFF)

- `packages/product/research/pilot_loop.py:1-8,49-57,110-148` — all execution routes raise `MassResearchDisabledError`; `go` never true. `61c88a0`.
- Worker: `platform/workers/research-mass-eval/wrangler.toml:48-51` `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"`.
- Python deny-by-default: `packages/product/research/research_capabilities.py:13-51` (`granted = False`, `go: False`).
- Foundation types are not a GO switch. Brief §17: “Foundation実装済みでもPilotはNO-GO.”

---

### M. `catalog_path` fabricated to missing YAML

**status: OPEN**

- `packages/product/research/unique_logic/catalog.py:191-208` sets `catalog_path` to `catalog_dir / f"{lid}.yaml"` with `catalog_present: False`. File does not exist.
- Tests pin the lie: `tests/test_unique_logic_catalog.py:188-191` `path.stem == lid` and `path.is_file() is False`.
- Combo self-check still names compiled params “YAML”: `unique_logic/event_combos.py:125,148-151`.

`e8bdf17` kept stem identity on purpose. Brief §10 lists this as a known semantic bug to fix.

---

### N. occupancy `yaml_remains_sot`

**status: FIXED**

- `packages/product/research/occupancy_audit.py:367-378` emits `yaml_still_present: False`; no `yaml_remains_sot`.
- `tests/test_occupancy_audit.py:30-31` asserts `yaml_still_present is False` and `"yaml_remains_sot" not in out`.
- Combo dump: `tests/test_unique_logic_catalog.py:162`.
- Commit `6381960`. Freeze docs `A07_catalog.md` / `A11_waste.md` still describe the `03cd1b1` OPEN; do not re-open the code.

---

### O. unused `cells_candidate_counts`

**status: FIXED**

- Helper removed from `packages/product/research/candidate_policy.py` (file now only `job_candidate_grade`, lines 12-28). `f82f371`.
- Repo grep: only leftover mentions in freeze `docs/reviews/A11_waste.md` / `README.md`. Live grade path is counts → `job_candidate_grade`.

---

### P. unique22 park YAML wording

**status: FIXED** (residual) / freeze A13 still stale

- Current residual HOLD line: `docs/phase62_residual_status.md:69` — “unique22 park leftover occupancy (`UNIQUE22_PARK_REASONS` / `daily_path.ts`; YAML gone, `yaml_still_present: false`)”. `359b766`.
- `docs/reviews/A13_docs_claims.md` A13-UNIQUE22-PARK-YAML still records the `03cd1b1` wording. Residual SoT is `phase62_residual_status.md`, not that freeze file.

---

### Q. GitHub `.github` absent / check runs 0

**status: HOLD** (no GHA by policy) / check-runs **observed 0**

- `.github/` does not exist (audit `ls`). Policy: `docs/architecture.md:28` “GitHub Actions には載せない”; ADR non-goal `docs/architecture/adr_llm_friendly_refactor.md:107`.
- GitHub `ddnne/quant-platform` commit `03cd1b1`: check-runs **total 0**.
- Empty GHA is not a missing pipeline to add. Operators run `scripts/verify_all.sh`. Cloudflare deploy is not a GitHub check.

---

### R. `0007_ops_applied_pins` not remote

**status: OPEN** (live unpinned) / apply **HUMAN**

- Schema in repo: `platform/workers/quant-ops-mcp/migrations/0007_ops_applied_pins.sql:1-5` — “Do not apply this migration remotely from this change set — schema only.” Tests: `tests/test_ops_applied_pins.py:64`.
- Residual: “Ops projector can emit `ops_applied_pins` from local `sync_change_state`; CURRENT stays impossible while the pin is NULL (0007 schema, not applied remote)” (`phase62_residual_status.md:69`).
- Remote D1 apply is an operator action. Code already refuses CURRENT with a null pin (item I).

---

### S. `GATEWAY_TOKEN` / HMAC human bind

**status: HUMAN**

- Gateway fail-closed if unbound: `research-ai-gateway/src/index.ts:36-42`; wrangler comment `research-ai-gateway/wrangler.toml:4-6` `npx wrangler secret put GATEWAY_TOKEN`.
- Readiness HMAC: `QUANT_READINESS_HMAC_SECRET` or `~/.config/quant-platform/readiness_hmac_secret` or SHA-256 of host receipt PEM (`readiness.py:112-125`). Agent must not mint. Bind is operator.
- Mass-eval `MASS_EVAL_TOKEN` is a different secret (`index.ts:14-15`); tests pin that (`index.test.ts:17-31`).

---

### T. reconstitution human pending

**status: HUMAN**

- `packages/product/research/eval_flags.py:12` `RECONSTITUTION_APPLY: bool = False`.
- Detect-only pack: `packages/product/research/reconstitution_pending.py:10-40` `human_choice_required`, `do_not_auto_choose`, does not flip apply.
- Pending ids: `basket_theme_fund`, `basket_event_fund` (`docs/phase63_reconstitution_pending.md:20-29`). Residual: “reconstitution **apply false** (human pending… do not auto-choose drop_parents vs drop_children)” (`phase62_residual_status.md:69`).

---

### U. leftover occupancy HOLD in `daily_path.ts`

**status: HOLD**

- Unique-22 leftover (no `params.gates`): `platform/workers/research-mass-eval/src/daily_path.ts:522`.
- Leftover CS books occupancy, not `comboCsGateOk`: `daily_path.ts:913-915` — “Do not drop without occupancy-equal re-eval. Parked leftover stay non-candidate.”
- Residual HOLD: cost_models / options_225 / daily_path leftover occupancy (`phase62_residual_status.md:69`). Do not unify leftover occupancy with `comboEventGateOk`.

---

### V. `workers_dev=true` kept

**status: HOLD** (kept)

All six wrangler configs:

- `platform/workers/ingestion-jsda/wrangler.toml:7`
- `platform/workers/ingestion-premium/wrangler.toml:27`
- `platform/workers/ingestion-secrets/wrangler.toml:6`
- `platform/workers/quant-ops-mcp/wrangler.toml:7`
- `platform/workers/research-ai-gateway/wrangler.toml:11`
- `platform/workers/research-mass-eval/wrangler.toml:26`

Brief E allowed disabling AI Gateway `workers_dev` if unneeded. Standing constraint: do not disable without replacing `DEFAULT_WORKER_URL`. A14 freeze listed this as OPEN-to-disable; this register treats **kept** as HOLD, not a 6.3.1 leak to flip.

---

### W. `MASS_RESEARCH` not GO

**status: FIXED** (NO-GO)

- Worker var: `research-mass-eval/wrangler.toml:48` `MASS_RESEARCH = "NO-GO"`.
- Capability snapshot denies unless `mass == "GO"` **and** other grants — grants stay false (`research_capabilities.py:24-50`).
- Tests refuse a GO env as sufficient (`tests/test_research_capabilities.py:119`; `tests/test_pilot_loop.py:118`).
- Do not set `MASS_RESEARCH=GO`.

---

### X. Independent review of 6.3.1 vs repo

**status: OPEN** (this file; P0 unresolved ≠ 0)

- Brief §1 / §22: independent Grok, not the implementer context. Wave-1 findings + remaining-audit lanes exist under `docs/reviews/` (`P631_wave1_findings.md`, `A01`, `A07`, `A10`, `A11`, `A13`, `A14`). Those freeze at `069913c` / `03cd1b1`.
- This register is the §22 re-diff vs `e927b97`. Unresolved P0-class vs 6.3.1 completion: Edge DO budget; catalog factorization; fabricated `catalog_path`; Python R2 TOCTOU; host PEM in pytest; unproven clean-venv / Worker typecheck+build; unpushed main (`origin/main` ≠ local HEAD).
- Independent P0 unresolved = 0 is a 6.3.1 GO condition. **Not met.**

---

## Mechanism vs thesis

None of the remaining leaks is a new thesis YAML. Do not add YAML. `CATALOG_AND_PLUS_N_STOPPED` holds n=2254.

| Concern | Mechanism (gate / capability / contract) | Not a thesis |
|---------|------------------------------------------|--------------|
| Receipt / COMPLETE | `SignedReceiptAuthority` before structured mutation | not a logic_id |
| Pilot / Phase 7 | `require_valid` + factory-issued services + `PHASE7=OFF` | not a catalog row |
| LLM spend | Gateway typed decode + future Edge DO reserve | not a strategy |
| Artifact immutability | Worker create-only children-then-manifest; Python CLI is not authority | not a family |
| Catalog identity | compiled `migration.jsonl` + freeze n=2254 | factorize templates; **do not expand n** |
| Candidate grade | `job_candidate_grade` (Python + Worker) + IR golden | not a new evaluator |
| Sync CURRENT | applied pin required; null → never CURRENT | not coverage COMPLETE |
| 4 PARTIAL | keep `history_target_start`; grain ADR later | not COMPLETE 23 |
| unique22 leftover | occupancy park in `daily_path.ts` / `UNIQUE22_PARK_REASONS` | not YAML unpark |
| Mass | `MASS_RESEARCH=NO-GO` + deny-by-default capabilities | not GO |
| Reconstitution | `RECONSTITUTION_APPLY=False` until dated human brief | not auto-choose |
| Secrets | operator `GATEWAY_TOKEN` / HMAC bind | not in git |
| CI | `verify_all.sh` local; no GitHub Actions | not a workflow YAML |

Gates and capabilities close authority. New thesis YAML would be a product expansion and is forbidden in this phase.

---

## 6.3.1 §19 checklist (current tree)

| Criterion | Status |
|-----------|--------|
| clean Python install/test green | **OPEN** (unproven at HEAD; host PEM) |
| 3 Workers normal `npm ci` green | lockfiles **FIXED**; full ci/typecheck/build **OPEN** |
| receipt authority before transaction | **FIXED** |
| Pilot readiness re-validates signature/expiry/snapshot | **FIXED** (construct) |
| AI output strict typed | **FIXED** |
| Edge hard budget reserve/reconcile | **DEFERRED** |
| artifact manifest-last commit | Worker **FIXED**; Python TOCTOU **OPEN** |
| catalog wrong YAML semantics gone | compiled-n / `yaml_remains_sot` **FIXED**; `catalog_path` / yaml_* names **OPEN**; factorize **OPEN** |
| independent Grok P0 unresolved = 0 | **OPEN** |

## 6.4 §19 (live; not invented)

| Criterion | Live |
|-----------|------|
| governed 26 Coverage COMPLETE | **NO** — 22 held / 4 PARTIAL |
| projection FRESH | **STALE** |
| B0 PASS | **UNKNOWN** |
| applied sync generation pinned/current | **unpinned** (`applied_cursor=null`) |
| immutable READY ≥ 1 | **null** |
| AM SLA live evidence | **PROJECTION_STALE** |
| Remote MCP vs docs | residual table is last-known under STALE; MCP without active gen is UNKNOWN |

## Human actions (not agent)

1. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env (S).
2. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only (T). Do not flip `RECONSTITUTION_APPLY` from an agent.
3. Apply `0007_ops_applied_pins` to remote D1 when the operator is ready to pin (R). Until then CURRENT stays impossible — that is correct.
4. Push: local `e927b97` is **ahead of** `origin/main` `03cd1b1`. This isolation worktree does **not** push.

---

## Commits already on local main (parent of this register)

Not pushed. Listed so the leak status is not re-litigated against `03cd1b1` freeze docs.

| SHA | Purpose |
|-----|---------|
| `6381960` | occupancy `yaml_remains_sot` removed (N) |
| `f82f371` | delete `cells_candidate_counts` (O) |
| `3b933ec` | phase61 tmp Ed25519 (A) |
| `5a168c7` | JSDA tests inject tmp signer (A) |
| `359b766` | unique22 park leftover occupancy wording (P) |
| `e927b97` | persist remaining-audit findings (freeze docs) |
