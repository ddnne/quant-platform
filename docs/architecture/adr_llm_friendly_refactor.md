# ADR: LLM-friendly whole-repo refactor (post layout migration)

| Field | Value |
|-------|--------|
| **Status** | **Accepted (Grok 2026-08-12)** |
| **Track** | **B1** (docs hub + plane import guards; Batch Z still **DEFER**) |
| **Date** | 2026-08-12 |
| **Tip at authoring** | `666510d` (layout migration Batches 0–E landed; import names unchanged) |
| **Accepted after** | `8638936` (Track A dry-run landed; residual SoT live-synced in B1) |
| **Supersedes** | Nothing (extends `repo_layout_migration.md` success criteria) |
| **Related** | [`repo_layout_migration.md`](./repo_layout_migration.md), [`repo_layout_inventory.md`](./repo_layout_inventory.md), [`phase7_fail_closed.md`](./phase7_fail_closed.md), [`../phase62_residual_status.md`](../phase62_residual_status.md), [`llm_nav_map.md`](./llm_nav_map.md) |

**Hard process constraints (non-negotiable for B0 and all B1 batches):**

- **Mass Autonomous Research / production READY publication / Phase 7 switch ON: NO-GO.**  
  Do not claim, enable, or imply them. Residual SoT remains `docs/phase62_residual_status.md`.
- **Honest evidence only.** Do not invent COMPLETE segments, live B0 pass, or `PHASE62_FULL_DONE`.
- **CF SoT preserved.** Contracts / natural keys / governed sets: Python + Worker mirrors stay dual-language SoT with parity tests; Workers path frozen.
- **fail-closed defaults** for Mass, gateway, synthetic COMPLETE mint, operator override.
- This ADR **does not** change live data, D1 schema, or wrangler deploy topology.

---

## 1. Context

### 1.1 Where we are

Physical library layout is already plane-grouped:

```text
packages/
  edge/              cf_platform, mcp_servers
  data_plane/        data_contracts, ingestion, storage, pit, data_access, ops
  research_runtime/  core, features, strategies, paper_runtime, risk, price_basis
  product/           agents, research, selection, execution, knowledge, gateway, fof
platform/workers/**  path-frozen CF Workers (TS/JS)
scripts/             flat-ish CLI drivers
tests/               ~88 offline modules (~15k LOC)
docs/                architecture + many phase*/status/proof shards
```

Import names remain **leaf top-level** (`import ingestion`, `import pit`, …) via setuptools multi-root `where = packages/{edge,data_plane,research_runtime,product}`. `qp_paths.repo_root()` and root `conftest.py` plane-path inserts keep uninstalled checkouts working.

Layout migration (`repo_layout_migration.md` Batches 0–E) solved **filesystem plane visibility**. It did **not** solve:

1. **LLM / agent cognitive load** — 80+ top-level docs, ~88 tests, ~24 scripts, thin plane READMEs, phase-numbered filenames that encode *history* more than *current truth*.
2. **Public API opacity** — some packages re-export carefully (`pit`, `core`, `agents`, `storage`); others export almost nothing (`ingestion` only `__version__`) while scripts/tests import deep submodules ad hoc.
3. **Doc multi-SoT** — residual / status / checklist / final_report / phase62x shards can disagree if an agent reads the wrong file.
4. **Residual path fragility** — many scripts still `sys.path.insert` + dual ROOT patterns; at least one `parents[N]` remains inside packages (`paper_runtime/code_fingerprints.py`).
5. **Duplicate conceptual modules** — e.g. `agents/artifacts.py` vs `research/artifacts.py`; `core/execution.py` vs `paper_runtime/execution.py` vs `product/execution/`; `live_gates` lives in `cf_platform` (correct) but naming collides with mental model of “feature gates”.
6. **Test suite shape** — strong boundary tests exist, but several modules are large combinatorial matrices (e.g. `test_phase35_coverage_matrix.py` ~1.2k LOC) that slow LLM-local iteration and blur “what invariant must never break”.
7. **Optional future namespace** — Batch Z (`quant_platform.*`) was deferred; agents still need a written policy so they do not “helpfully” rewrite imports mid-feature.

### 1.2 Who this ADR is for

| Consumer | Need |
|----------|------|
| **Human implementer (B1)** | Executable batches with exit criteria, file touch lists, and rollback |
| **LLM coding agents** | Single entry map, allowed import graph, “do not touch” list, reading order ≤ N docs |
| **Grok review** | Clear decisions + open questions; no hidden Mass/READY claims |
| **Operators** | Zero change to wrangler paths, data domain, or live GO gates |

### 1.3 Trigger

After layout migration, onboarding and multi-file agent edits still require tribal knowledge. Track B0 captures the **design** for a second-pass, LLM-friendly refactor. **B1 lands only after Grok review agreement** on this ADR.

---

## 2. Decision drivers

| Driver | Weight | Notes |
|--------|--------|-------|
| **Preserve architectural spirit** | Critical | CF SoT, PIT sole fact read, ingestion-only network, fail-closed Mass, honest COMPLETE |
| **Import stability** | Critical | Do not force repo-wide import rewrite in B1 unless Grok explicitly chooses Batch Z path |
| **Agent locality** | High | An agent should edit one plane without loading the whole monorepo into context |
| **Docs single source of truth** | High | One residual map; historical phase docs demoted to archive pointers |
| **Test signal density** | High | Guard/static boundary tests first; matrix tests second; live markers remain opt-in |
| **Deploy path freeze** | Critical | `platform/workers/**`, `data/**` unmoved |
| **Reversibility** | High | Each B1 sub-batch is one revert unit; no mixed “rename + behavior change” |
| **Honesty over polish** | Critical | No COMPLETE/READY/Mass/Phase7 enablement as a side effect |

---

## 3. Goals / Non-goals

### 3.1 Goals (B1 series, after approval)

1. **Stable mental model for agents** — planes, import rules, and “read these 5 docs first” are machine- and human-navigable.
2. **Explicit package public API surface** — each leaf package documents `__all__` / preferred entry modules; deep imports discouraged for new code.
3. **Docs navigation consolidation** — residual / phase / proof / operations mapped; current-truth docs ≤ a small set; history clearly labeled.
4. **Dead code & name collision hygiene** — remove or quarantine unused shims; disambiguate duplicate module basenames in docs and (where cheap) renames with shims.
5. **Guard-first test policy** — catalog and protect boundary tests; shrink or split pure combinatorial suites without losing invariant coverage.
6. **Script bootstrap unification** — one ROOT helper pattern; reduce copy-pasted `sys.path.insert` blocks.
7. **Naming consistency policy** — written rules for packages, modules, scripts, docs filenames, and status vocabulary (`DONE` / `DEFER` / `NO-GO` / `OFF`).

### 3.2 Non-goals (explicit)

| Non-goal | Rationale |
|----------|-----------|
| Mass ON / mass research autonomy | fail-closed; residual NO-GO |
| Production READY publication | ops evidence, not layout/LLM refactor |
| Phase 7 switch ON / production LLM loops | foundation-only remains |
| Fabricating COMPLETE segments or live B0 | honest evidence only |
| Moving `platform/workers/**` or `data/**` | deploy + secrets adjacency |
| Wholesale import rewrite to `quant_platform.*` in B1 | Batch Z optional later; high blast radius |
| Changing Coverage V2 / receipt crypto / D1 schema semantics | separate ADR if ever needed |
| Adding GitHub Actions CI | project policy: CF-side CI |
| FoF / live broker execution thickness | roadmap Phases 8–9 |
| “Make README claim Phase 6.2 live complete” | residual status remains NO-GO for Mass/READY |

### 3.3 Spirit invariants (must survive every B1 batch)

```text
1. Ingestion is the only external network plane for market data.
2. pit.get_* is the sole structured fact read path for research compute
   (as_of required; available_at <= as_of; mode=ro).
3. core / features / strategies do not open SQLite or HTTP for facts.
4. data_contracts JSON (+ Worker catalog/identity mirrors) are CF-adjacent SoT;
   governed JS is generated, not hand-drifted.
5. Mass research requires VerifiedResearchReadiness; operator_override rejected.
6. Synthetic COMPLETE mint is not a production export; publish is fail-closed.
7. Live claims require docs/proof/* + residual status — never ADR prose alone.
```

---

## 4. Decision summary (Accepted)

| ID | Decision | B1 batch |
|----|----------|----------|
| D1 | Keep **import names as leaf top-level** for entire B1 series; Batch Z (`quant_platform.*`) remains **optional future**, not default | B1-a docs; Z separate |
| D2 | Treat `packages/*` planes as **hard dependency direction** (documented allow-list); add/extend static import-boundary tests where missing | B1-b |
| D3 | Establish **public API policy** per leaf package (`__all__` + README “entrypoints” section); new code imports public surface first | B1-b |
| D4 | **Docs SoT map**: residual status one file; architecture hub; archive index for phase62x historical shards; agent read order | B1-a |
| D5 | **Dead/duplicate policy**: delete only with proof (no importers + tests); else quarantine / rename-with-shim | B1-c |
| D6 | **Tests**: guard pack mandatory; matrix tests may be split/param-reduced but not deleted without mapping each invariant | B1-d |
| D7 | **Scripts**: introduce `scripts/_bootstrap.py` (or use `qp_paths`) and migrate scripts incrementally; optional regroup deferred | B1-e |
| D8 | **Naming glossary** in nav map; status vocabulary enforced in new docs | B1-a |
| D9 | No Mass/READY/Phase7 code paths armed; every batch re-runs `test_mass_research_gate.py` + gateway fail-closed | all |
| D10 | Workers + `data/` frozen; only docs/comments may mention their paths | all |

---

## 5. `packages/*` boundaries and public API policy

### 5.1 Plane dependency direction (allow-list)

Arrows mean “may import”. Reverse edges are **bugs** unless listed under exceptions.

```text
edge (cf_platform, mcp_servers)
  ← may import — data_plane (data_contracts, …) ; mcp_servers → data_access
  ✗ must not import — research_runtime product strategies agents (except documented)

data_plane (data_contracts, ingestion, storage, pit, data_access, ops)
  ← data_contracts: no first-party runtime deps (stdlib + json only preferred)
  ← ingestion → data_contracts, storage
  ← storage → data_contracts, ingestion, cf_platform (coverage helpers)
  ← pit → ingestion, storage
  ← data_access → data_contracts, pit, features, paper_runtime, storage
  ← ops → data_contracts
  ✗ data_plane must not import product.* (agents, gateway, selection, …)
  ✗ pit/ingestion must not import core/features/strategies

research_runtime (core, features, strategies, paper_runtime, risk, price_basis)
  ← core → pit, features, price_basis
  ← features → pit, price_basis   (no sqlite3 / no cf_platform)
  ← strategies → core, features, paper_runtime, price_basis
  ← paper_runtime → data_contracts, storage, strategies, features, cf_platform
  ← risk → (minimal; store only — avoid product cycles)
  ✗ research_runtime must not import agents/gateway/selection/execution
  ✗ core/features must not import storage or open DB except via pit

product (agents, research, selection, execution, knowledge, gateway, fof)
  ← agents → strategies, selection, research, execution, risk
  ← execution → strategies, features, agents, paper_runtime   # known cycle agents↔execution
  ← research → selection, paper_runtime
  ← knowledge → storage
  ← gateway → agents, strategies, selection (fail-closed stubs)
  ✗ product must not import ingestion HTTP clients for market fetch
  ✗ product must not mint Coverage COMPLETE or bypass Mass readiness

platform/workers/** (not a Python package)
  ← path coupling only; no Python import
  ↔ parity: data_contracts JSON, cf_platform.ingest_premium.*, governed.js codegen
```

**Known accepted cycles / soft edges (document, do not “fix” blindly in B1):**

| Edge | Status | Policy |
|------|--------|--------|
| `agents` ↔ `execution` | Existing design | Keep; prefer types-only imports if a future split is needed |
| `data_access` → `features`, `paper_runtime` | Cross-plane read façade | Allowed; data_access is the **read domain** bridge, not a pure data_plane leaf in the strict sense — keep under `data_plane/` physically, document as **shared read adapter** |
| `storage` / `paper_runtime` → `cf_platform` | Coverage / B0 measurement reuse | Allowed; cf_platform stays algorithm mirror, not Worker runtime |
| `risk` → `agents` (types) | Inventory graph | Prefer moving shared types to neutral module if B1-c proves pain; not mandatory |

### 5.2 Public API policy (per leaf package)

**Rule P1 — Preferred entry:**  
New production code and new tests should import from package root or an explicitly documented submodule (e.g. `from pit import get_equity_bars_daily`, `from core import run_backtest`).

**Rule P2 — Deep imports:**  
`from ingestion.jquants.catalog import DATASETS` remains valid (catalog is intentional API). Deep imports of *private* helpers (`_apply_strict_live_gates`, module-private `_foo`) are test-only.

**Rule P3 — `__all__`:**  
Every leaf package `__init__.py` either:

- re-exports the stable surface and sets `__all__`, **or**
- documents “import submodules directly; root is namespace only” (current `ingestion` style) in `packages/<plane>/<pkg>/README.md`.

**Rule P4 — No silent behavior in `__init__`:**  
Package import must stay side-effect light (no network, no DB open, no env arming Mass).

#### Target public surfaces (inventory for B1-b; not a rewrite mandate)

| Package | Preferred public surface (keep / clarify) | Avoid for new code |
|---------|-------------------------------------------|--------------------|
| `data_contracts` | `loader`, `coverage`, `identity`, `inventory`, `canonical`, `jsda` + JSON via package data | Ad-hoc path opens; use `importlib.resources` / package paths |
| `ingestion` | `pipeline`, `runtime_authority`, `jquants.catalog`, `jquants.client`, `jsda.*` fetch/parse | Direct secrets; non-ingestion HTTP from other planes |
| `storage` | Existing `__all__` (coverage ledger, receipts, …) + `sqlite_store` / `schema` for writers | Re-exporting synthetic COMPLETE builders |
| `pit` | Existing `__all__` `get_*` + errors | Opening SQLite outside `pit` |
| `data_access` | `QuantDataAccess` / service + adapter types | SQL strings to callers |
| `ops` | `backfill_planner`, `projection_meta` | Wrangler side effects inside library |
| `cf_platform` | `ingest_premium.{availability,coverage,natural_key,validate,matrix}`, `live_gates` | Importing Workers |
| `mcp_servers` | `python -m mcp_servers.quant_data` | Production remote path (Ops MCP is Worker) |
| `core` | `run_backtest`, costs, execution modes, `Strategy` protocol | Direct pit bypass |
| `features` | registry / runtime / `v0` feature defs | sqlite3, HTTP |
| `strategies` | `spec.schema`, `spec.interpreter`, `paper.*` | eval/exec, dynamic import |
| `paper_runtime` | `ready_policy`, `snapshot`, `coherence`, fingerprints, experiment index | Forging READY without proof |
| `agents` | pipeline, roles, types, mass_research (fail-closed), runtime policy | operator_override Mass |
| `gateway` | fail-closed AI stubs only | “real” LLM loop enablement in B1 |
| `selection` / `research` / `execution` / `knowledge` | keep current modules; document entrypoints | Budget without readiness |

### 5.3 Cross-plane “who owns X?”

| Concern | Owner package | Notes |
|---------|---------------|-------|
| Dataset contract JSON | `data_contracts` | SoT; Workers catalog must stay in parity tests |
| Fetch / normalize | `ingestion` | Only network egress for market data |
| Structured write + receipts | `storage` | available_at mandatory |
| Fact read | `pit` | sole path |
| Ops vs research read domains | `data_access` + remote Ops MCP | see `quant_data_access.md` |
| Coverage evaluation helpers | `cf_platform.ingest_premium.coverage` + `storage.coverage_ledger` | ledger persists; cf_platform measures |
| Backtest | `core` | black box |
| Features | `features` | PIT-only |
| StrategySpec | `strategies.spec` | whitelist interpreter |
| Paper persist | `strategies.paper` + `paper_runtime` | READY policy separate from paper JSON |
| Role agents | `agents` | structured messages only |
| Mass gate | `agents.mass_research` + `research.readiness` | fail-closed |
| Local MCP | `mcp_servers` | dev/offline |
| Remote Ops MCP | `platform/workers/quant-ops-mcp` | path frozen |

---

## 6. Import policy

### 6.1 B1 default: **stabilize current import names**

```text
import ingestion
import pit
from pit import get_equity_bars_daily
from core import run_backtest
from data_contracts.coverage import ...
```

**Rationale (unchanged from layout migration §5):**

- Hundreds of import sites across packages, scripts, tests.
- Boundary tests and agent isolation key on short top-level names.
- Disk layout already encodes planes; import layout need not duplicate them yet.
- Fingerprints / StrategySpec / paper metadata may embed source path concepts — rewrite needs a dedicated review.

### 6.2 Future optional: `quant_platform.*` (Batch Z — out of B1)

If Grok later approves Batch Z:

1. Introduce `quant_platform.data_plane.ingestion` etc. as real packages **or** namespace packages.
2. Ship **re-export shims** at old top-level names for ≥1 release.
3. Migrate scripts/tests gradually; keep Workers path coupling unchanged.
4. Re-verify `paper_runtime.code_fingerprints` and any path-hash consumers.
5. Only then delete shims.

**B1 must not** partially introduce `quant_platform.*` for a subset of packages (split-brain imports).

### 6.3 Runtime path policy

| Mechanism | Policy |
|-----------|--------|
| `pip install -e ".[dev]"` | **Primary** for humans and CI-like local runs |
| Root `conftest.py` plane `sys.path` inserts | Keep as safety net; do not remove in B1 without proving editable-only green |
| `qp_paths.repo_root()` / `package_dir()` | Mandatory for repo-relative file loads inside packages |
| `Path(__file__).parents[N]` inside `packages/**` | **Forbidden** for new code; fix stragglers in B1-e |
| Script `sys.path.insert` | Migrate to shared bootstrap in B1-e; behavior-equivalent |

### 6.4 Import lint direction (B1-b, lightweight)

Prefer **pytest static guards** (existing style in `test_core_data_boundary.py`, `test_features_data_boundary.py`, `test_strategies_static_boundaries.py`) over heavy import-linter config unless Grok requests tooling.

**Proposed additional guards (implement in B1-b, not B0):**

| Guard test | Asserts |
|------------|---------|
| `test_plane_import_boundaries.py` (new) | AST/grep: `core`/`features` do not import `storage`/`ingestion.common.http`; `agents` does not import `ingestion.jquants.client`; `gateway` does not open sockets |
| Existing mass / gateway tests | Unchanged fail-closed |
| `test_mass_research_gate.py` | Every full batch |

Do **not** encode `data_access → features` as illegal (it is intentional).

---

## 7. Docs single source of truth (residual / phase scatter)

### 7.1 Problem

Under `docs/` today (non-exhaustive):

| Cluster | Examples | Risk if agent reads only these |
|---------|----------|--------------------------------|
| **Current residual** | `phase62_residual_status.md` | Correct live residual SoT |
| **Phase status shards** | deleted (`phase62*_status.md`, `phase62_final_report.md`) | Use residual + R2/D1 |
| **Runbooks** | `phase61_production_runbook.md`, `phase62_production_runbook.md`, `operations/*` | Operationally valid but long |
| **Proof** | `docs/proof/*` | Evidence snapshots — dated; must not override residual without new proof |
| **Architecture** | `architecture.md`, `architecture/*` | Boundaries; layout SoT |
| **Domain** | `pit_api.md`, `core_engine.md`, `features.md`, `paper.md`, `agents.md`, `quant_data_access.md` | Stable contracts |

### 7.2 Decision: layered SoT

```text
Layer 0 — ALWAYS READ FIRST (agent entry)
  README.md
  docs/architecture/llm_nav_map.md          # this series' map
  docs/phase62_residual_status.md           # live residual + Mass NO-GO
  docs/architecture.md                      # plane boundaries
  docs/architecture/adr_llm_friendly_refactor.md  # when doing B1

Layer 1 — DOMAIN CONTRACTS (as needed by task)
  docs/pit_api.md | core_engine.md | features.md | paper.md | agents.md
  docs/quant_data_access.md | data_sources.md
  docs/architecture/phase7_fail_closed.md

Layer 2 — OPERATIONS (when running live tooling)
  docs/operations/* , phase*_*runbook.md
  platform/workers/*/README.md

Layer 3 — EVIDENCE (cite, do not “upgrade” status from these alone)
  docs/proof/*

Layer 4 — HISTORICAL / ARCHIVE (do not treat as current GO)
  pre_phase7_full_code_review.md (snapshot review)
```

### 7.3 B1-a concrete doc actions

1. **Land** `docs/architecture/llm_nav_map.md` (draft in same B0 PR; README link in B1-a).
2. **Add** `docs/architecture/DOC_TRUTH_MAP.md` **or** a section inside `llm_nav_map.md` (prefer single nav file to avoid yet another hub) listing every `docs/phase*.md` with tag: `current` | `runbook` | `historical` | `proof-index`.
3. **Header stamp** on historical phase status files (B1-a, mechanical):

   ```markdown
   > **Historical snapshot** — not current residual SoT.
   > Current residual: [phase62_residual_status.md](../phase62_residual_status.md).
   > Mass / READY / Phase7: **NO-GO / OFF** unless residual says otherwise.
   ```

4. **Do not delete** historical status files in B1-a (link equity / audit trail). Optional later move to `docs/archive/phase62/` only if Grok wants less top-level noise — as a dedicated micro-batch.
5. **README** gains a short “Agent / LLM entry” blurb pointing at `llm_nav_map.md` (B1-a).
6. **Residual file remains the only place** that summarizes live COMPLETE counts / Mass NO-GO for agents.

### 7.4 Vocabulary (status words)

| Word | Meaning | Who may set |
|------|---------|-------------|
| **DONE** | Work item completed with evidence | residual / proof |
| **DEFER** | Explicitly postponed | residual |
| **NO-GO** | Must not enable / claim | residual + code gates |
| **OFF** | Switch closed (Phase 7 foundation) | phase7_fail_closed + code |
| **code-complete** | Implementation present; not live GO | README / residual |
| **live verified** | Remote/live check with dated proof | residual + `docs/proof/*` |
| **Proposed** | ADR awaiting review | (historical) |
| **Accepted** | ADR reviewed; B1 may land | this document |

**Forbidden in B1 commits without residual+proof update:**  
`PHASE62_FULL_DONE`, “Mass ON”, “READY≥1 production”, “Phase 7 GO”, inventing COMPLETE counts.

---

## 8. Duplication and dead-code removal policy

### 8.1 Classification

| Class | Definition | Action |
|-------|------------|--------|
| **D-dead** | No importers in packages/scripts/tests; not public `__all__` | Delete in B1-c with test green |
| **D-shim** | Thin re-export kept for compat | Keep until callers migrated; mark in README |
| **D-mirror** | Intentional dual implementation (Py ↔ TS) | **Never delete one side**; parity tests stay |
| **D-name-collision** | Same basename, different roles | Document in nav map; rename only with shim if high confusion |
| **D-doc-dup** | Two docs claim current status | Stamp historical; single residual SoT |
| **D-script-dup** | Two CLIs overlapping | Prefer one entry + flags; deprecate via README first |

### 8.2 Known collision inventory (for B1-c triage)

| Paths | Roles | Proposed disposition |
|-------|-------|----------------------|
| `agents/artifacts.py` vs `research/artifacts.py` | Agent envelopes vs research idea artifacts | **Keep both**; document names in nav map (`Agent` vs `Research` artifact). Optional rename `research/idea_artifacts.py` only with shim |
| `core/execution.py` vs `paper_runtime/execution.py` vs `product/execution/` | Backtest fill timing vs paper runtime exec helper vs authorized paper service | **Keep**; glossary: “fill timing” / “paper runtime exec” / “authorized execution service” |
| `cf_platform/live_gates.py` | B0 order-of-magnitude gates (sqlite measurement) | **Keep name** (widely imported); document that it is **not** feature flags and **not** Mass GO |
| Empty / placeholder `fof/` | README only | Keep placeholder; no fake code |
| Root empty `raw/` (if still present) | Confuses with `data/raw/` | Delete if empty (layout Batch F leftover) in B1-c |
| Stale egg-info | gitignored | Document reinstall; never commit |

### 8.3 Deletion protocol (mandatory)

```text
1. rg / pytest collection proves zero imports (packages, scripts, tests).
2. If symbol is in __all__ or docs examples, demote docs first.
3. Prefer one commit: "chore: remove unused X" with reason in body.
4. Full offline pytest green.
5. Never delete: data_contracts JSON, Worker sources, receipt crypto,
   mass_research fail-closed paths, publish guards, parity fixtures.
```

### 8.4 What B1 will **not** “dedupe”

- Python `cf_platform.ingest_premium.*` vs TS Worker algorithms (mirrors).
- Local `mcp_servers` vs remote `quant-ops-mcp` (different trust domains).
- Coverage logic split between `storage.coverage_ledger` and `cf_platform...coverage` (persist vs measure).

---

## 9. Test strategy (guard-first, reduce excess combinatorics)

### 9.1 Principles

1. **Guards encode architecture** — if a guard fails, stop the batch.
2. **Behavior tests encode contracts** — PIT look-ahead, StrategySpec reject, receipt signature.
3. **Matrix / combinatorial tests encode catalogs** — valuable, but must be navigable and not the only place an invariant lives.
4. **Live tests stay opt-in** — `@pytest.mark.live` / `QP_LIVE=1`; never required for B1 merge.
5. **No test may enable Mass or publish READY** as a side effect.

### 9.2 Guard pack (must stay green every B1 batch)

```text
tests/test_smoke.py
tests/test_mass_research_gate.py
tests/test_gateway_fail_closed.py
tests/test_core_data_boundary.py
tests/test_features_data_boundary.py
tests/test_strategies_static_boundaries.py
tests/test_phase7_gateway.py          # foundation fail-closed
tests/test_ops_projection_publish_guard.py
# plus any new test_plane_import_boundaries.py from B1-b
```

**Command:**

```bash
python -m pytest \
  tests/test_smoke.py \
  tests/test_mass_research_gate.py \
  tests/test_gateway_fail_closed.py \
  tests/test_core_data_boundary.py \
  tests/test_features_data_boundary.py \
  tests/test_strategies_static_boundaries.py \
  tests/test_phase7_gateway.py \
  tests/test_ops_projection_publish_guard.py \
  -q
```

### 9.3 Suite tiers

| Tier | When | Scope |
|------|------|-------|
| **G0 Guard** | Every commit in B1 | Guard pack above |
| **G1 Plane** | After touches in one plane | Layout migration §9 plane sets (A/B/C/D) |
| **G2 Full offline** | End of each B1 sub-batch | `pytest tests/ -q` + `unittest tests.test_smoke` |
| **G3 Live** | Never required for B1 | `QP_LIVE=1` operator only |

### 9.4 Combinatorial reduction policy (B1-d)

**Target example:** `tests/test_phase35_coverage_matrix.py` (~1.2k LOC).

Allowed techniques:

1. **Split by concern** — availability vs natural_key vs validate vs matrix row presence (multiple files, shared fixtures).
2. **Parametrize from contract JSON** — one test function × datasets from `data_contracts`, not hand-duplicated blocks per dataset when the assertion is identical.
3. **Keep one explicit golden test per invariant class** — e.g. “unknown dataset fails closed”, “addon excluded from premium schedule”.
4. **Do not drop** parity assertions against Worker `catalog.ts` / `availability.ts` without replacement.

Disallowed:

- Deleting matrix coverage because “tests are slow” without invariant map.
- Merging unrelated assertions into mega-tests that fail opaquely.
- Marking offline catalog tests as `live`.

### 9.5 Test naming / placement conventions (new tests)

```text
tests/test_<area>_<concern>.py
# area: pit | core | features | agents | coverage | ops | phase35 | ...
# concern: boundary | gate | schema | parse | publish | ...
```

Prefer extending an existing area file over creating `test_misc_*.py`.

### 9.6 Evidence tests vs unit tests

| Kind | Location | May claim live COMPLETE? |
|------|----------|---------------------------|
| Unit / offline | `tests/` | No |
| Operator proof | `docs/proof/*.md` + residual | Only with dated remote evidence |
| ADR / nav | `docs/architecture/` | Never |

---

## 10. Agent entry documentation (reading order)

### 10.1 Default read order (hard budget: ~5 files before code)

1. [`README.md`](../../README.md) — orientation + layout map  
2. [`docs/architecture/llm_nav_map.md`](./llm_nav_map.md) — where to go next by task  
3. [`docs/phase62_residual_status.md`](../phase62_residual_status.md) — live residual; Mass **NO-GO**  
4. [`docs/architecture.md`](../architecture.md) — PIT / coverage / MCP boundaries  
5. Task-specific domain doc (one of: `pit_api.md`, `core_engine.md`, `agents.md`, `quant_data_access.md`, …)

**If the task is this refactor:** also read this ADR.

**If the task touches Workers:** add `platform/README.md` + the specific worker README; do not move paths.

### 10.2 Task → start file cheat sheet

| Task | Start code | Start docs |
|------|------------|------------|
| Ingest / normalize | `packages/data_plane/ingestion/` | `data_sources.md` |
| Contracts / governed sets | `packages/data_plane/data_contracts/` | contracts README + coverage JSON |
| Coverage ledger / receipts | `packages/data_plane/storage/` | residual + phase61 runbook |
| PIT read | `packages/data_plane/pit/` | `pit_api.md` |
| Features | `packages/research_runtime/features/` | `features.md` |
| Backtest | `packages/research_runtime/core/` | `core_engine.md` |
| Paper / READY policy | `strategies/paper`, `paper_runtime` | `paper.md`, residual (READY NO-GO) |
| Agents / StrategySpec | `packages/product/agents/`, `strategies/spec` | `agents.md` |
| Mass gate | `agents/mass_research.py` | residual + `phase7_fail_closed.md` |
| Ops projection publish | `scripts/publish_ops_projection.py` | `operations/projection_publish_guard.md` |
| Local MCP | `mcp_servers/quant_data` | `quant_data_access.md` |
| CF Premium Worker | `platform/workers/ingestion-premium/` | `phase35_cf_ingest.md` |
| Layout / packaging | `pyproject.toml`, `qp_paths.py` | `repo_layout_migration.md` |

### 10.3 Agent “do not do” list (copy into nav map)

```text
- Do not set Mass / READY / Phase7 GO flags or claim them in docs without residual+proof.
- Do not move platform/workers/** or data/**.
- Do not introduce quant_platform.* imports in B1.
- Do not open SQLite from core/features/strategies for facts (use pit).
- Do not call external market APIs outside ingestion.
- Do not commit secrets, data/*.sqlite, .venv, egg-info, node_modules.
- Do not delete parity mirrors (Py/TS) or receipt verification keys casually.
- Do not treat historical phase62*_status.md as current residual SoT.
```

---

## 11. Naming consistency

### 11.1 Packages and modules

| Kind | Convention | Examples |
|------|------------|----------|
| Leaf import package | short `snake_case`, stable | `pit`, `data_contracts`, `paper_runtime` |
| Plane directory | `snake_case`, **not** imported | `data_plane`, `research_runtime` |
| CF Python helpers | `cf_platform` (avoid stdlib `platform`) | required |
| Workers dir | `platform/workers/<service>` | frozen paths |
| Private helpers | leading `_` | `_apply_strict_live_gates` |
| JSON contracts | descriptive `snake_case.json` | `jquants_premium_core.json` |

### 11.2 Scripts

| Pattern | Use |
|---------|-----|
| `run_*.py` | User-facing one-shot drivers (ingest, paper, agents, validation) |
| `*_status.py` / `ops_*.py` | Ops diagnostics |
| `publish_*` / `export_*` | Projection pipeline (fail-closed publish) |
| `generate_*` / `verify_*` | Codegen + drift gates |
| `rebuild_*` / `refresh_*` | Derived indexes / ledgers |

B1-e may document grouping without forcing directory moves (layout Batch F optional).

### 11.3 Docs filenames

| Pattern | Use |
|---------|-----|
| `docs/architecture/*.md` | lasting decisions, layout, ADR |
| `docs/operations/*.md` | runbooks |
| `docs/proof/*_YYYYMMDD.md` | dated evidence |
| `docs/phaseNN_*.md` | phase-scoped; stamp historical when superseded |
| `docs/<domain>.md` | stable domain contracts (`pit_api`, `agents`, …) |

### 11.4 Status & gate names

- **B0** in `cf_platform.live_gates` = order-of-magnitude data volume gates (master/bars counts).  
  **≠** Track B0 (this design track). Nav map must disambiguate.
- **READY** = research snapshot publication policy (`paper_runtime.ready_policy`) — production READY remains residual-gated.
- **COMPLETE** = Coverage V2 segment/dataset state — only with receipts + inventory; never synthetic in production export paths.

---

## 12. Implementation batches (B1-*) — after Grok approval only

> **B0:** ADR + nav map draft (landed). **Accepted (Grok 2026-08-12)** unlocks B1.

### B1-a — Documentation hub & honesty stamps — **DONE (2026-08-12)**

**Intent:** Make agents land on current truth without reading 30 phase files.

**Actions:**

1. Finalize `docs/architecture/llm_nav_map.md` (from B0 draft).
2. Link it from `README.md` (“LLM 向けナビゲーション地図”).
3. Stamp historical `docs/phase62*_status.md`, `phase621_*`, `phase622_*`, `phase623_*`, and completion/final reports with historical banner → residual SoT.
4. Sync `docs/phase62_residual_status.md` live numbers (COMPLETE 404, OTC 5, Track A dry-run).
5. Doc truth table remains inside nav map §7 (no extra hub file).

**Touches:** `docs/**`, `README.md` (B1-a); plane READMEs + guards with B1-b.

**Exit criteria:**

- [x] Nav map lists read order + task cheat sheet + do-not list
- [x] Historical banners on phase status shards
- [x] README links nav map
- [x] Residual still says Mass/READY/Phase7 NO-GO/OFF

**Rollback:** revert docs commit.

---

### B1-b — Plane boundaries & public API documentation — **DONE (2026-08-12)**

**Intent:** Encode allow-list imports; clarify `__all__` / entrypoints without mass renames.

**Actions:**

1. Add thin leaf `packages/**/README.md` where missing (public entry + forbidden imports).
2. Keep leaf package `__init__.py` exports as-is (no mass rewrite).
3. Add `tests/test_plane_import_boundaries.py` (static allow-list + plane hard bans).
4. Document ADR exceptions: `data_access` → features/paper_runtime; `paper_runtime`/`storage` → cf_platform.

**Exit criteria:**

- [x] G0 guard pack green
- [x] New plane boundary test green
- [x] Plane READMEs exist for previously missing leaves
- [x] Mass gate still fail-closed
- [x] Full offline pytest green

**Rollback:** revert commit(s); tests prove restore.

---

### B1-c — Dead code, empty dirs, name-collision docs

**Intent:** Reduce noise without semantic risk.

**Actions:**

1. Inventory D-dead via import graph; delete only per §8.3.
2. Remove empty confusing dirs (e.g. root `raw/` if empty).
3. Document name collisions in nav map glossary (no forced renames unless trivial+shim).
4. Quarantine clearly obsolete scripts only if README + zero tests reference them.

**Exit criteria:**

- [ ] Deletion list in commit message
- [ ] G0 + G2 green
- [ ] No Worker/data moves
- [ ] No removal of parity mirrors or fail-closed gates

**Rollback:** revert; re-add deleted paths if needed.

---

### B1-d — Test guard catalog & matrix navigation

**Intent:** Faster, clearer offline suite for humans and LLMs.

**Actions:**

1. Add `tests/README.md` with G0/G1/G2 tiers and guard pack list.
2. Split or parametrize the heaviest matrix module(s) per §9.4; keep invariant map in the PR body.
3. Ensure each architectural invariant has a **named** test function (not only buried matrix rows).

**Exit criteria:**

- [ ] `tests/README.md` present
- [ ] G0 runtime acceptable on developer laptop (document approximate duration if known)
- [ ] G2 full offline green
- [ ] No live credentials required

**Rollback:** revert test-only commit.

---

### B1-e — Script bootstrap & package path stragglers

**Intent:** One way to find repo root; eliminate fragile `parents[N]` in packages.

**Actions:**

1. Add `scripts/_bootstrap.py` (or document `from qp_paths import repo_root` usage) that: finds root, inserts root + plane paths if needed.
2. Migrate scripts in small groups (ingest / ops / paper) to shared bootstrap — behavior-equivalent CLIs.
3. Fix remaining `parents[N]` inside `packages/**` (e.g. fingerprints) to `qp_paths.repo_root()`.
4. **Do not** force layout Batch F script directory regroup unless Grok explicitly wants it (can be B1-e.1 later).

**Exit criteria:**

- [ ] Spot-check: `python scripts/ops_status.py --help` (or equivalent) works
- [ ] Tests that `importlib` load scripts still pass
- [ ] G2 green
- [ ] No wrangler path changes

**Rollback:** revert bootstrap migration per script group.

---

### B1-f — Optional polish (only if a–e done and review OK)

- Script regroup under `scripts/{ingest,sync,coverage,paper,validation,ops,codegen}/` (layout Batch F)
- `docs/archive/phase62/` physical move of historical shards (update links)
- Stronger import-linter config
- **Not** Batch Z import namespace

**Exit criteria:** G2 green + link check for moved docs + scripts README updated.

---

### Batch Z — Optional future (explicit non-B1)

`quant_platform.*` namespace + shims — requires separate ADR amendment and fingerprint review. See §6.2.

---

## 13. Risks and rollback

| Risk | Severity | Mitigation |
|------|----------|------------|
| Agent rewrites imports to `quant_platform.*` spontaneously | High | D1 + do-not list; reject in review |
| Docs stamp missed → agent trusts stale “final_report” | High | B1-a banners + residual sole live summary |
| Boundary test too strict breaks `data_access` bridge | Medium | Allow-list exceptions in §5.1 |
| Script bootstrap changes break `spec_from_file_location` tests | Medium | Migrate with those tests in G1 set; keep path stable |
| Dead-code deletion removes “unused” codegen helper | High | §8.3 protocol; grepping scripts/docs |
| Combinatorial test split drops Worker parity row | High | Invariant map in B1-d PR; keep catalog.ts asserts |
| Accidental Mass/READY wording in README polish | Critical | Vocabulary §7.4; residual cross-read |
| Touching Workers “while here” | Critical | Frozen path rule; empty `git diff platform/workers` |
| Commit `data/*.sqlite` / secrets | Critical | `.gitignore`; pre-commit human check |
| Parallel B1 batches on main conflict | Medium | Serial B1-a→… on main; one author stream |

### 13.1 Rollback strategy

- **Docs-only (B1-a):** single revert commit.
- **Tests-only (B1-d):** single revert; no prod impact.
- **API export tweaks (B1-b):** revert; keep new tests if still valid.
- **Script bootstrap (B1-e):** revert per group; CLIs remain callable via old pattern until migrated.
- **Never** rollback by “temporarily enabling” Mass or weakening publish guards.

### 13.2 Success definition (entire B1 series)

1. Agent can start from **5 files** and find the correct plane/module for common tasks.
2. Residual SoT is unambiguous; historical phase docs cannot be mistaken for GO.
3. Guard pack is documented and green; full offline suite green.
4. Import names still leaf top-level; no partial Batch Z.
5. `platform/workers/**` and `data/**` path-stable.
6. Mass research remain fail-closed; no READY production publication; Phase 7 OFF.
7. This ADR status can move to **Accepted** only after Grok review; then to **Implemented** when B1 exit criteria land.

---

## 14. Grok review decisions (2026-08-12)

| # | Question | Decision |
|---|----------|----------|
| 1 | Batch Z timeline | **DEFER** indefinitely relative to B1; separate ADR amendment if ever scheduled |
| 2 | Physical `docs/archive/` move | **Banners-only** in B1-a; physical archive optional later |
| 3 | Script directory regroup (Batch F) | **Optional / last** — not required for B1 exit |
| 4 | `test_plane_import_boundaries` strictness | Allow `paper_runtime → storage` / `data_access → features|paper_runtime`; forbid product→ingestion market clients |
| 5 | Rename collisions | **Docs-only** in B1 (glossary); no shim churn |
| 6 | `data_access` plane label | **Keep** under `data_plane/`; document as shared read adapter |
| 7 | G0 runtime budget | Prefer guard pack fast; no hard SLA enforced in ADR |
| 8 | Extra frozen paths | Workers + `data/` remain the hard freeze |

---

## 15. References

| Doc | Role |
|-----|------|
| [`repo_layout_migration.md`](./repo_layout_migration.md) | Physical layout SoT (implemented) |
| [`repo_layout_inventory.md`](./repo_layout_inventory.md) | Pre-move inventory (historical but useful coupling map) |
| [`repo_layout_mapping.json`](./repo_layout_mapping.json) | Machine-readable from→to |
| [`../architecture.md`](../architecture.md) | PIT / coverage / MCP boundaries |
| [`../phase62_residual_status.md`](../phase62_residual_status.md) | **Live residual SoT** |
| [`./phase7_fail_closed.md`](./phase7_fail_closed.md) | Phase 7 OFF |
| [`../quant_data_access.md`](../quant_data_access.md) | Ops vs research read domains |
| [`./llm_nav_map.md`](./llm_nav_map.md) | Agent entry map (B1 live) |
| `pyproject.toml` | multi-root setuptools discovery |
| `qp_paths.py` | `repo_root()` / `package_dir()` |

---

## 16. Changelog (ADR document)

| Date | Change |
|------|--------|
| 2026-08-12 | B0 Proposed: initial full ADR for LLM-friendly refactor; no implementation |
| 2026-08-12 | **Accepted** (Grok review): Batch Z DEFER; leaf imports; residual single SoT; scripts optional; Mass/READY/Phase7 NO-GO. B1 may implement. |
