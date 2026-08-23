# Repo layout migration plan

**Status:** **fully implemented** (Batches 0–E). Physical layout under `packages/*`; import names unchanged via setuptools multi-root.  
**Tip at plan authoring:** `b76996d`  
**Mass research / READY publication / Phase 7 GO:** **OFF** (this migration does not enable them).  
**Data / secrets:** `data/` stays gitignored local domain; **do not move** raw secrets or local SQLite dumps.  
**Workers:** `platform/workers/**` path frozen; only relative imports of `data_contracts` JSON were retargeted to `packages/data_plane/data_contracts/`.

---

## 1. Purpose

The repository grew phase-by-phase into a **flat root monorepo**: ~20 Python packages, 4 Cloudflare Workers, ops scripts, and tests all sit at or near the top level. Boundaries exist in code (ingestion-only network, PIT sole fact read path, Mass fail-closed), but the **filesystem no longer reflects those planes**.

This document is the **executable** migration plan:

1. freeze a target tree grouped by relationship
2. map every package `from → to` with import stability policy
3. stage moves in batches with exit criteria and tests
4. call out path hacks (wrangler, scripts, conftest, egg-info, `.venv`)

Implementation follows: **plan → staged `git mv` → import/path fixes → tests → README**.

---

## 2. Current top-level inventory and problems

### 2.1 Top-level (tip `b76996d`, non-dot)

| Path | Kind | Role today |
|------|------|------------|
| `agents/` | py package | 8 role agents + offline paper pipeline + mass gate |
| `cf_platform/` | py package | CF Premium coverage/validate/natural_key (Python SoT mirror) |
| `core/` | py package | Black-box backtest engine |
| `data/` | local domain | raw / structured / paper / reports / ops (**gitignore**) |
| `data_access/` | py package | Ops + research read adapter / domain service |
| `data_contracts/` | py package | JQ/JSDA contracts, coverage, identity, inventory JSON |
| `docs/` | docs | architecture, phase runbooks, ops |
| `execution/` | py package | Authorized paper execution service |
| `features/` | py package | Versioned feature registry (PIT-only) |
| `fof/` | placeholder | FoF layer (README only) |
| `gateway/` | py package | AI gateway stubs (fail-closed) |
| `ingestion/` | py package | J-Quants / JSDA fetch + normalize + pipeline |
| `knowledge/` | py package | Immutable knowledge artifact store |
| `mcp_servers/` | py package | Local stdio quant_data MCP (dev/offline) |
| `ops/` | py package | Backfill planner, projection meta |
| `paper_runtime/` | py package | READY policy, coherence, snapshots, fingerprints |
| `pit/` | py package | PIT Data API (sole fact read path) |
| `platform/` | CF edge | Workers + secrets name list (`workers/*`) |
| `price_basis.py` | py-module | Shared price-basis helper |
| `pyproject.toml` | packaging | setuptools find + optional deps |
| `raw/` | empty local | leftover empty `raw/jsda/` (not the gitignored data plane) |
| `README.md` | docs | entrypoint |
| `research/` | py package | Ideas, evaluation, scheduler, readiness |
| `risk/` | py package | Immutable risk audit store |
| `scripts/` | CLI | Ingest/sync/validation/paper/ops CLIs |
| `selection/` | py package | Budget ledger, screen, selection decision |
| `storage/` | py package | SQLite schema, receipts, coverage ledger |
| `strategies/` | py package | Paper runner, StrategySpec, examples |
| `tests/` | tests | ~88 offline unit/integration modules |
| `conftest.py` | pytest | Root `sys.path` + FakeHttpClient |

Also present locally (not migration targets): `.venv/`, `quant_platform.egg-info/`, `node_modules/` under workers, `.wrangler/`, `.glm-logs/`.

### 2.2 Problems

1. **Flat root noise** — product, data plane, research runtime, and edge helpers compete for the same directory level; onboarding requires tribal knowledge (README table is incomplete vs actual packages).
2. **Packaging drift** — `pyproject.toml` `packages.find.include` omits live packages that tests import: `research`, `selection`, `ops`, `execution`, `gateway`, `knowledge`. Install currently relies on root `conftest.py` / script `sys.path` hacks. Stale `quant_platform.egg-info/top_level.txt` only lists `ingestion`, `pit`, `storage`.
3. **Relationship is invisible** — e.g. `cf_platform` (Python) is far from `platform/workers` (TS); `mcp_servers` (local) is far from `quant-ops-mcp` (remote); `ops` vs `scripts` vs `data_access` are easy to confuse.
4. **Path fragility** — many modules assume “package is one level under repo root” via `Path(__file__).parents[1]`. Any depth change without a `repo_root()` helper breaks:
   - `storage/receipt_crypto.py` → `data_contracts/receipt_verify_public_keys.json`
   - `ops/backfill_planner.py` → `data_contracts/jquants_premium_core.json`
   - `paper_runtime/code_fingerprints.py` → git root
   - ~25 scripts and many tests
5. **Hard-coded `platform/workers/...` paths** — scripts (`publish_ops_projection.py`, `generate_governed_js.py`, `ops_reeval_freshness.py`, …) and runbooks depend on **stable** Worker tree paths. Moving Workers without a coordinated wrangler/docs pass is high risk.
6. **Empty / ambiguous dirs** — root `raw/` duplicates the concept of `data/raw/` and confuses operators.
7. **Cross-plane coupling is real but undocumented in layout** — graph (source packages only):

| Package | Depends on (same-repo packages) |
|---------|----------------------------------|
| `ingestion` | `data_contracts`, `storage` |
| `storage` | `cf_platform`, `data_contracts`, `ingestion` |
| `pit` | `ingestion`, `storage` |
| `cf_platform` | `data_contracts`, `ingestion` |
| `data_access` | `data_contracts`, `features`, `paper_runtime`, `pit`, `storage` |
| `ops` | `data_contracts` |
| `core` | `features`, `pit`, `price_basis` |
| `features` | `pit`, `price_basis` |
| `strategies` | `core`, `features`, `paper_runtime`, `price_basis` |
| `paper_runtime` | `cf_platform`, `data_contracts`, `storage`, `strategies` |
| `agents` | `execution`, `research`, `risk`, `selection`, `strategies` |
| `execution` | `agents`, `features`, `paper_runtime`, `strategies` |
| `research` | `selection` |
| `knowledge` | `storage` |
| `mcp_servers` | `data_access` |
| `gateway` / `selection` / `risk` | (minimal / self) |

---

## 3. Design principles

1. **Group by plane / relationship**, not by phase number or author.
2. **Import stability first** — physical moves must not force a repo-wide import rewrite in the same change series (see §5).
3. **Do not break Cloudflare deploy paths** — keep `platform/workers/<name>/wrangler.toml` at the current relative location unless a dedicated Worker-path batch is explicitly approved.
4. **Do not move `data/`** — local raw/structured/paper/reports stay put; gitignore domain.
5. **No Mass / READY / Phase 7 enablement** as part of layout work.
6. **One batch = one reversible PR-sized unit** with green offline pytest exit criteria.
7. Prefer **`git mv`** to preserve history.

---

## 4. Target tree (decided)

```
quant-platform/
├── README.md
├── pyproject.toml
├── conftest.py                 # thin: repo_root on path + shared fixtures only
├── docs/
│   └── architecture/
│       ├── repo_layout_migration.md   # this file
│       └── repo_layout_mapping.json   # machine-readable mapping
├── tests/                      # stays at root (pytest testpaths)
├── data/                       # UNMOVED — local gitignored domain
├── scripts/                    # CLI entrypoints (internal subfolders optional later)
│   └── ops/
├── platform/                   # CF edge — PATH FROZEN for wrangler / scripts
│   ├── README.md
│   ├── secrets.example.md
│   └── workers/
│       ├── ingestion-jsda/
│       ├── ingestion-premium/  # migrations/, src/, wrangler.toml
│       ├── ingestion-secrets/
│       └── quant-ops-mcp/
└── packages/                   # library code only (import names unchanged)
    ├── edge/                   # CF-adjacent Python + local MCP
    │   ├── cf_platform/
    │   └── mcp_servers/
    ├── data_plane/             # contracts → ingest → store → read → ops meta
    │   ├── data_contracts/
    │   ├── ingestion/
    │   ├── storage/
    │   ├── pit/
    │   ├── data_access/
    │   └── ops/
    ├── research_runtime/       # compute stack (no external network)
    │   ├── core/
    │   ├── features/
    │   ├── strategies/
    │   ├── paper_runtime/
    │   ├── risk/
    │   └── price_basis.py      # keep as top-level module via package-dir
    └── product/                # orchestration + product surfaces
        ├── agents/
        ├── research/
        ├── selection/
        ├── execution/
        ├── knowledge/
        ├── gateway/
        └── fof/
```

### 4.1 Why this split (vs alternatives)

| Option | Verdict |
|--------|---------|
| **A. `packages/{edge,data_plane,research_runtime,product}` + frozen `platform/`** | **Adopted.** Clear planes; Workers path stable; import names preservable via setuptools `where` / `package-dir`. |
| B. Nested `src/quant_platform/*` with new imports | Rejected for now — forces full import rewrite + doc/script churn; high blast radius. Deferred as optional Batch Z. |
| C. Only rename folders at root (`data_plane_ingestion/`) | Rejected — worse names, still flat, breaks imports without benefit. |
| D. Move Workers under `packages/edge/workers` | Rejected for P0 series — breaks wrangler `-c` paths, deploy muscle memory, and many runbooks. Revisit only with a Worker-path batch. |

### 4.2 Explicit non-moves

| Path | Reason |
|------|--------|
| `data/**` | Local secrets-adjacent dumps, SQLite, receipts cache; gitignore domain |
| `platform/workers/**` | wrangler.toml, migrations, `npx wrangler -c` conventions, scripts hardcodes |
| `docs/**` | Stay; only add layout docs + later path-table updates |
| `tests/**` | Stay at root (`testpaths = ["tests"]`); fix internal path joins per batch |
| `.venv/`, `*.egg-info/`, `node_modules/` | Regenerated artifacts; never `git mv` |

### 4.3 Cleanup (non-code)

| Path | Action |
|------|--------|
| `raw/` (empty) | Delete in Batch F or document as deprecated; operators use `data/raw/` |
| Stale `quant_platform.egg-info/` | Regenerate via `pip install -e ".[dev]"` after each packaging batch (gitignored) |

---

## 5. Packaging / import policy (**recommended: stabilize imports**)

### 5.1 Decision

**Recommended: physical layout under `packages/*` + setuptools multi-root discovery so Python import paths stay identical** (`import ingestion`, `import pit`, …).

**Not recommended now:** wholesale rewrite to `quant_platform.data_plane.ingestion` etc.

### 5.2 Rationale

1. **~200+ import sites** across packages, scripts, and tests; rewrite is a multi-day merge hazard concurrent with live ops scripts.
2. **Boundary tests** and agent isolation already key on short top-level names.
3. Large monorepos commonly separate *disk layout* from *import layout* (`package-dir` / multi-`where`).
4. Deferred namespace rewrite (Batch Z) remains possible once layout is stable and fingerprint/path helpers no longer assume depth.

### 5.3 Target `pyproject.toml` shape (illustrative)

```toml
[tool.setuptools.packages.find]
where = [
  "packages/edge",
  "packages/data_plane",
  "packages/research_runtime",
  "packages/product",
]
include = [
  "cf_platform*",
  "mcp_servers*",
  "data_contracts*",
  "ingestion*",
  "storage*",
  "pit*",
  "data_access*",
  "ops*",
  "core*",
  "features*",
  "strategies*",
  "paper_runtime*",
  "risk*",
  "agents*",
  "research*",
  "selection*",
  "execution*",
  "knowledge*",
  "gateway*",
]
exclude = ["tests*", "scripts*", "data*", "docs*", "platform*"]

[tool.setuptools]
py-modules = ["price_basis"]

[tool.setuptools.package-dir]
# Map top-level module name → directory that *contains* price_basis.py
price_basis = "packages/research_runtime"

[tool.setuptools.package-data]
data_contracts = ["*.json"]
```

Notes:

- With multi-root `where`, package **import names** remain the leaf directory names (`ingestion`, not `data_plane.ingestion`).
- **Batch 0** should add currently missing includes (`research*`, `selection*`, `ops*`, `execution*`, `gateway*`, `knowledge*`) **before** any move so editable install matches reality.
- After moves: always `pip install -e ".[dev]"` and delete stale egg-info if needed.

### 5.4 `sys.path` and editable installs

| Mechanism | During migration | End state |
|-----------|------------------|-----------|
| `pip install -e ".[dev]"` | Required after every packaging/move batch | Primary |
| Root `conftest.py` `sys.path.insert(repo_root)` | Keep temporarily for uninstalled modules | Keep as safety net for scripts run without install |
| Per-script `sys.path.insert(ROOT)` | Keep; `ROOT` must remain repo root (`parents[1]` for `scripts/*.py`) | Prefer install; hacks optional |
| `parents[1]` inside moved packages | **Must change** — use `repo_root()` helper | Required |

### 5.5 Introduce `repo_root()` early (Batch 0)

Add a tiny root-stable helper used by packages that currently do `Path(__file__).parents[1]`:

```python
# suggested: packages stay import-stable; helper can live as
# price_basis-adjacent or a new py-module `qp_paths.py` at repo root
# OR under packages/data_plane once moved — prefer root py-module for Batch 0:

# qp_paths.py (repo root, listed in py-modules) — optional name
def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").is_file() and (parent / "tests").is_dir():
            return parent
    raise RuntimeError("quant-platform repo root not found")
```

**Rule:** any code that needs repo-root paths (contracts JSON sibling, platform/workers, git commit) must use `repo_root()`, never a fixed `parents[N]` depth, **before** that package is moved.

---

## 6. Package move mapping table

| ID | from (disk) | to (disk) | plane | import name changes? | setuptools today | notes |
|----|-------------|-----------|-------|----------------------|------------------|-------|
| M01 | `data_contracts/` | `packages/data_plane/data_contracts/` | data_plane | **no** (`data_contracts`) | included | JSON package-data |
| M02 | `ingestion/` | `packages/data_plane/ingestion/` | data_plane | **no** | included | largest py tree |
| M03 | `storage/` | `packages/data_plane/storage/` | data_plane | **no** | included | fix `receipt_crypto` root |
| M04 | `pit/` | `packages/data_plane/pit/` | data_plane | **no** | included | |
| M05 | `data_access/` | `packages/data_plane/data_access/` | data_plane | **no** | included | |
| M06 | `ops/` | `packages/data_plane/ops/` | data_plane | **no** | **missing include** | add in Batch 0; fix planner path |
| M07 | `core/` | `packages/research_runtime/core/` | research_runtime | **no** | included | |
| M08 | `features/` | `packages/research_runtime/features/` | research_runtime | **no** | included | |
| M09 | `strategies/` | `packages/research_runtime/strategies/` | research_runtime | **no** | included | tests join `…/strategies` |
| M10 | `paper_runtime/` | `packages/research_runtime/paper_runtime/` | research_runtime | **no** | included | fix `git_commit` root |
| M11 | `risk/` | `packages/research_runtime/risk/` | research_runtime | **no** | included | |
| M12 | `price_basis.py` | `packages/research_runtime/price_basis.py` | research_runtime | **no** | py-modules | package-dir map |
| M13 | `agents/` | `packages/product/agents/` | product | **no** | included | tests join `…/agents` |
| M14 | `research/` | `packages/product/research/` | product | **no** | **missing include** | add Batch 0 |
| M15 | `selection/` | `packages/product/selection/` | product | **no** | **missing include** | add Batch 0 |
| M16 | `execution/` | `packages/product/execution/` | product | **no** | **missing include** | add Batch 0 |
| M17 | `knowledge/` | `packages/product/knowledge/` | product | **no** | **missing include** | add Batch 0 |
| M18 | `gateway/` | `packages/product/gateway/` | product | **no** | **missing include** | add Batch 0 |
| M19 | `fof/` | `packages/product/fof/` | product | n/a (no package yet) | n/a | README only |
| M20 | `cf_platform/` | `packages/edge/cf_platform/` | edge | **no** | included | not Workers |
| M21 | `mcp_servers/` | `packages/edge/mcp_servers/` | edge | **no** | included | local stdio only |
| — | `platform/` | **stay** | edge (CF) | n/a | excluded | frozen |
| — | `scripts/` | **stay** (optional internal regroup) | tooling | n/a | excluded | see Batch F |
| — | `tests/` | **stay** | qa | n/a | excluded | path joins per batch |
| — | `docs/` | **stay** | docs | n/a | excluded | |
| — | `data/` | **stay** | local | n/a | excluded | |
| — | `raw/` | **delete** (Batch F) | clutter | n/a | n/a | empty |

Machine-readable twin: [`repo_layout_mapping.json`](./repo_layout_mapping.json).

---

## 7. Staged batches

### Batch 0 — Packaging hygiene + path helper (no moves)

**Goal:** Make install truth match the tree; harden path resolution before any `git mv`.

**Actions:**

1. Extend `pyproject.toml` `packages.find.include` with: `research*`, `selection*`, `ops*`, `execution*`, `gateway*`, `knowledge*` (and keep existing).
2. Add `repo_root()` helper (root `qp_paths.py` **or** inline shared helper imported by hot spots). Preferred: small root py-module listed in `py-modules` so it survives later moves.
3. Replace fixed `parents[1]` **only** in modules that will move later and load repo-relative files:
   - `storage/receipt_crypto.py`
   - `ops/backfill_planner.py`
   - `paper_runtime/code_fingerprints.py`
4. Optionally introduce tests helper constant `tests/_repo.py` with `REPO_ROOT = Path(__file__).resolve().parents[1]` for tests (tests stay at root so depth is stable).
5. `pip install -e ".[dev]"`; refresh egg-info locally.
6. Create empty target dirs with `.gitkeep` + one-line README per plane (`packages/edge/README.md`, …) describing intent — **no package moves yet**.

**Exit criteria:**

- [ ] `python -c "import research, selection, ops, execution, gateway, knowledge, ingestion, storage, pit"` succeeds under editable install **without** relying solely on cwd hacks
- [ ] Offline pytest subset green (see §9 Batch 0 set)
- [ ] No `data/` or `platform/workers` changes
- [ ] Mass/READY/Phase7 still fail-closed (spot-check `test_mass_research_gate.py`)

**Rollback:** revert pyproject + helper commit.

---

### Batch A — Data plane physical move

**Moves:** M01–M06 (`data_contracts`, `ingestion`, `storage`, `pit`, `data_access`, `ops`).

**Actions:**

1. `git mv` each tree into `packages/data_plane/`.
2. Update `pyproject.toml` `where` to include `packages/data_plane` (and keep other roots pointing at remaining top-level packages **or** temporarily list both old and new — prefer single cut with full where list for still-top-level packages via additional `where = ["."]` **only if needed**; cleaner: move only this plane and set:

   ```toml
   where = [".", "packages/data_plane"]
   ```

   with `include` filters so packages are not double-discovered. **Avoid double discovery:** once moved, they must not remain at root.

3. Confirm `data_contracts` package-data still ships `*.json`.
4. Grep for hardcoded path joins to `data_contracts/`, `ingestion/`, `storage/` from repo root in tests/scripts/docs that open files by path (not import).
5. Known file-path consumers:
   - `tests/test_phase35_premium_set.py` → contract JSON + catalog.ts (workers path unchanged)
   - `tests/test_identity_runtime_parity.py`
   - scripts that only **import** packages: no change if install works
   - `scripts/generate_governed_js.py` imports `data_contracts` — OK if installed

**Exit criteria:**

- [ ] No top-level `ingestion/`, `storage/`, `pit/`, `data_contracts/`, `data_access/`, `ops/`
- [ ] `import ingestion, storage, pit, data_contracts, data_access, ops` works
- [ ] Batch A pytest set green (§9)
- [ ] `platform/workers/**` untouched
- [ ] `data/**` untouched

**Rollback:** reverse `git mv` + pyproject.

---

### Batch B — Research runtime physical move

**Moves:** M07–M12 (`core`, `features`, `strategies`, `paper_runtime`, `risk`, `price_basis.py`).

**Actions:**

1. `git mv` into `packages/research_runtime/`.
2. Ensure `package-dir` for `price_basis` and `py-modules = ["price_basis"]`.
3. Fix tests that do `Path(repo) / "strategies"` or `…/strategies/spec` (e.g. `test_strategies_static_boundaries.py`, `test_strategy_spec_schema.py`) to resolve via `importlib.util.find_spec("strategies")` or `Path(strategies.__file__).parent`.
4. Re-verify paper fingerprint tests (git commit resolution).

**Exit criteria:**

- [ ] `import core, features, strategies, paper_runtime, risk, price_basis` works
- [ ] Batch B pytest set green
- [ ] Strategy static boundary tests still point at the real strategies package tree

---

### Batch C — Product / orchestration physical move

**Moves:** M13–M19 (`agents`, `research`, `selection`, `execution`, `knowledge`, `gateway`, `fof`).

**Actions:**

1. `git mv` into `packages/product/`.
2. Fix tests that path-join `agents/` (`test_agents_roles.py`).
3. Confirm circular import surface `agents ↔ execution` still loads (existing design).

**Exit criteria:**

- [ ] Product imports work; Batch C pytest set green
- [ ] `test_mass_research_gate.py` still fail-closed (Mass OFF)

---

### Batch D — Edge Python physical move (not Workers)

**Moves:** M20–M21 (`cf_platform`, `mcp_servers`).

**Actions:**

1. `git mv` into `packages/edge/`.
2. `where` gains `packages/edge`; remove any residual root discovery.
3. Final `pyproject.toml` matches §5.3 (only `packages/*` roots + `price_basis` map).
4. Drop temporary `where = ["."]` if still present.

**Exit criteria:**

- [ ] `import cf_platform, mcp_servers` works
- [ ] Phase 3.5 / coverage tests green
- [ ] **`platform/workers` paths unchanged**; wrangler deploy docs still valid
- [ ] Full offline pytest green (§9 full set)

---

### Batch E — Path-consumer sweep + docs table

**Goal:** eliminate remaining root-relative assumptions; update human docs.

**Actions:**

1. Repo-wide search for string paths `"ingestion/"`, `"storage/"`, `"agents/"`, etc. in tests/scripts that open files.
2. Update `README.md` directory table to the target tree.
3. Update `docs/architecture.md` with a short “repository layout” pointer to this doc.
4. Keep phase runbooks’ `platform/workers/...` paths **as-is**.
5. Ensure root `conftest.py` comment reflects multi-root packages.

**Exit criteria:**

- [ ] README table matches disk
- [ ] Full offline pytest green
- [ ] No broken links to moved package paths in README/architecture (phase historical docs may still mention old paths — annotate or leave as historical)

---

### Batch F — Scripts hygiene + empty `raw/` removal (optional, low risk)

**Goal:** group CLIs without breaking operator muscle memory more than necessary.

**Suggested internal layout (scripts only; still not installed as packages):**

```
scripts/
├── ingest/          # run_ingestion_once, historical_backfill, parse_jsda_*, rebuild_receipts*
├── sync/            # sync_d1_to_sqlite, restore_local_complete*, report_d1_*
├── coverage/        # write_collection_receipts, refresh_coverage_ledger, issue_signed_*
├── paper/           # later deleted: run_paper_once, run_agents_paper_once, rebuild_paper_index
├── validation/      # run_phase35_validation, run_phase4_accept
├── ops/             # existing ops/ + publish_ops_projection, export_ops_projection, ops_status, …
└── codegen/         # generate_governed_js, verify_governed_js_drift
```

**If and only if** scripts move deeper:

- Fix `ROOT = Path(__file__).resolve().parents[N]` (N increases by nesting).
- Prefer a shared `scripts/_root.py` that walks to `pyproject.toml`.
- Update tests that `importlib` load scripts by path (`tests/conftest.py` → `scripts/sync_d1_to_sqlite.py`, phase CLI tests).

**Also:** delete empty root `raw/`.

**Exit criteria:**

- [ ] Documented CLI paths in README/scripts README updated
- [ ] Full offline pytest green
- [ ] Cron/operator notes updated if any external scheduler calls scripts by path

**Alternative (acceptable):** leave all scripts flat; only delete `raw/` and add `scripts/README.md` grouping table without moves.

---

### Batch Z — Optional future import namespace (out of scope for P0 execution)

If desired later:

- Introduce `quant_platform.*` packages and re-export shims at old names for 1–2 releases.
- Then delete shims.
- Requires fingerprint / StrategySpec stability review (source paths in manifests).

**Not part of the P0 series.**

---

## 8. Risks and mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **wrangler paths** | Critical | **Never move** `platform/workers/**` in Batches 0–F. Scripts hardcode `ROOT / "platform/workers/..."`. Deploy runbooks use `cd platform/workers/ingestion-premium`. |
| **Script path hacks** | High | Keep `scripts/` at repo root until Batch F; use `repo_root()`; after nesting, fix `parents[N]`. |
| **conftest `sys.path`** | Medium | Root conftest inserts repo root — **does not** auto-find packages under `packages/*` unless editable install or explicit path. **Editable install is mandatory after Batch A.** |
| **Stale egg-info / `.venv`** | Medium | gitignored; after each batch: `pip install -e ".[dev]"`. Old `.venv` may cache wrong locations — reinstall if imports fail. |
| **Double package discovery** | High | Do not leave package both at root and under `packages/`; do not list overlapping `where` roots that re-find the same name. |
| **`Path(__file__).parents[1]`** | High | Batch 0 helper before moves; grep for `parents[` after each batch. |
| **Tests joining package dirs** | Medium | Prefer `Path(importlib.util.find_spec(name).origin).parent` over repo-relative joins. |
| **Worker `node_modules`** | Low | Local only; never move; if Worker tree ever moves, re-`npm install` in place. |
| **Governed JS codegen** | Medium | `generate_governed_js.py` writes to `platform/workers/quant-ops-mcp/src/governed.js` — path must stay valid. |
| **Paper code fingerprints** | Medium | Uses git root + source inspection; fix `git_commit()` root; hashes should remain stable if source bytes unchanged. |
| **Mass / Phase7 gates** | Process | Layout PRs must not touch fail-closed defaults; include `test_mass_research_gate.py` in every full set. |
| **Docs drift** | Low | Batch E README; historical phase docs may keep old paths (add note at top of this file as SoT for layout). |
| **Concurrent feature work** | High | Land batches serially on `main`; avoid parallel large moves. |

---

## 9. Test strategy

### 9.1 Global rules

- Default: **offline** `python -m pytest tests/ -q` (no `QP_LIVE=1`).
- Do **not** require network, J-Quants keys, or live D1 for layout exit criteria.
- After every batch: re-editable install, then run the batch set, then (from Batch D onward) full suite.
- Collection errors (import failures) count as batch failure.

### 9.2 Minimum pytest sets

**Batch 0 (packaging / helpers)**

```text
tests/test_smoke.py
tests/test_mass_research_gate.py
tests/test_phase623_receipt_signature.py
tests/test_backfill_planner.py
tests/test_paper_code_fingerprints.py
```

**Batch A (data plane)**

```text
tests/test_smoke.py
tests/test_http_client.py
tests/test_jquants_client.py
tests/test_jquants_catalog.py
tests/test_jquants_normalize.py
tests/test_jsda_parse.py
tests/test_jsda_governed.py
tests/test_pipeline_reports.py
tests/test_pit_as_of.py
tests/test_pit_lookahead.py
tests/test_pit_coverage.py
tests/test_natural_keys.py
tests/test_immutable_artifact.py
tests/test_phase623_receipt_signature.py
tests/test_phase61_coverage_v2.py
tests/test_phase6_data_access.py
tests/test_backfill_planner.py
tests/test_identity_runtime_parity.py
```

**Batch B (research runtime)**

```text
tests/test_core_engine.py
tests/test_core_data_boundary.py
tests/test_features_compute.py
tests/test_features_data_boundary.py
tests/test_strategy_spec_schema.py
tests/test_strategies_static_boundaries.py
tests/test_paper_pipeline.py
tests/test_paper_snapshot.py
tests/test_paper_store.py
tests/test_ready_policy.py
tests/test_paper_code_fingerprints.py
tests/test_phase4_accept_script.py
```

**Batch C (product)**

```text
tests/test_agents_roles.py
tests/test_agents_pipeline.py
tests/test_paper_execution_service.py
tests/test_selection_decision.py
tests/test_research_budget_ledger.py
tests/test_mass_research_gate.py
tests/test_phase7_gateway.py
tests/test_phase7_knowledge.py
tests/test_phase7_selection.py
tests/test_phase7_pipeline_budget.py
tests/test_phase622_remainder.py
```

**Batch D / E / F (full offline)**

```text
python -m pytest tests/ -q
python -m unittest tests.test_smoke -v
```

**Optional smoke (not required for merge if credentials absent):**

```text
# never enable Mass; do not publish READY as part of layout work
python scripts/ops_status.py   # if env allows
```

### 9.3 Manual checks per batch

1. `pip install -e ".[dev]"` succeeds.
2. `python -c "import <moved packages>"` for that batch.
3. `test_mass_research_gate.py` still denies Mass without readiness.
4. Spot-check: `ls platform/workers/*/wrangler.toml` unchanged (`git diff --stat platform/workers` empty).
5. `git status data/` shows no intentional renames (local untracked noise OK).

---

## 10. Execution checklist (implementer)

```text
[ ] Read this doc + repo_layout_mapping.json
[ ] Branch per batch (or serial commits on main if that is house style)
[ ] Batch 0 → tests → commit
[ ] Batch A → tests → commit
[ ] Batch B → tests → commit
[ ] Batch C → tests → commit
[ ] Batch D → full pytest → commit
[ ] Batch E docs → commit
[ ] Batch F optional
[ ] Push; if conflict: git pull --rebase origin main && git push
[ ] Do NOT: move data/, move platform/workers, enable Mass/READY/Phase7
```

Commit message pattern:

```text
chore(layout): batch A — move data plane under packages/data_plane
```

---

## 11. Success definition

Migration is **done** when:

1. Disk layout matches §4 target tree (except optional Batch F script regroup).
2. All historical import names still work without a compatibility shim package.
3. `pip install -e ".[dev]"` + full offline pytest is green.
4. `platform/workers/**` and `data/**` are bit-for-bit path-stable (no renames).
5. README directory table describes the new layout.
6. Mass research remains fail-closed; no READY publication or Phase 7 GO changes.

---

## 12. References

- [`../architecture.md`](../architecture.md) — plane boundaries (PIT, ops vs research read)
- [`../quant_data_access.md`](../quant_data_access.md) — MCP read domains
- [`../../platform/README.md`](../../platform/README.md) — Worker inventory
- [`./repo_layout_mapping.json`](./repo_layout_mapping.json) — machine-readable mapping
- `pyproject.toml` — setuptools discovery (update per batch)
