# Repo layout dependency inventory (P0 reorg)

> **Historical (2026-08-12 snapshot).** Live layout SoT is
> [`llm_nav_map.md`](./llm_nav_map.md) and
> [`repo_layout_migration.md`](./repo_layout_migration.md). Packaging `where`
> is `packages/{edge,data_plane,research_runtime,product}` in current
> `pyproject.toml`. This file still lists pre-migration paths
> (`jquants/fetch`, `where = ["."]`). Do not treat it as the current tree.
> Do not launch Mass / READY / Phase 7 from this inventory.

**Purpose:** read-only dependency map for structural reorganization.  
**No mass moves in this doc.** Inventory only.  
**Tip surveyed:** `b76996ddf0bc24107b5d9fce65ddf05dd86ae6fb`  
**Generated:** 2026-08-12

---

## 1. `pyproject.toml` — `packages.find` / packaging

```toml
[tool.setuptools.packages.find]
where = ["."]
include = [
  "ingestion*",
  "storage*",
  "pit*",
  "core*",
  "features*",
  "strategies*",
  "paper_runtime*",
  "cf_platform*",
  "data_contracts*",
  "agents*",
  "risk*",
  "data_access*",
  "mcp_servers*",
]
exclude = ["tests*", "scripts*", "data*", "docs*"]

[tool.setuptools]
py-modules = ["price_basis"]

[tool.setuptools.package-data]
data_contracts = ["*.json"]
```

| Item | Value |
|------|--------|
| Project name | `quant-platform` |
| Requires Python | `>=3.11` |
| Runtime deps | `httpx`, `cryptography` |
| Optional | `xlsx` / `xls` / `jsda` / `dev` (pytest + spreadsheet) |
| Pytest | `testpaths = ["tests"]` |

### Packaged vs present but **not** in `include`

| Status | Top-level package dirs |
|--------|-------------------------|
| **In `include`** | `ingestion`, `storage`, `pit`, `core`, `features`, `strategies`, `paper_runtime`, `cf_platform`, `data_contracts`, `agents`, `risk`, `data_access`, `mcp_servers` |
| **py-module** | `price_basis` |
| **Has `__init__.py` but NOT packaged** | `execution`, `gateway`, `knowledge`, `ops`, `research`, `selection` |
| **Not a Python package** | `platform/` (Workers + wrangler only; name collides with stdlib `platform`) |
| **Excluded explicitly** | `tests*`, `scripts*`, `data*`, `docs*` |

**Reorg note:** moving any `include` package requires `pyproject.toml` + any editable-install consumers. Unlisted packages rely on repo-root `sys.path` (conftest / scripts).

**Stale egg-info:** `quant_platform.egg-info/top_level.txt` still lists only `ingestion`, `pit`, `storage` — regenerate after reorg (`pip install -e .`).

---

## 2. Top-level Python packages and primary modules

### 2.1 Packaged (setuptools)

| Package | Role | Primary modules |
|---------|------|-----------------|
| `ingestion/` | Fetch / normalize / pipeline | `pipeline`, `runtime_authority`, `common/{http,paths,retry,rate_limit,secrets,timeutil,available_at}`, `jquants/{catalog,client,fetch,normalize,parallel,bulk,receipts}`, `jsda/{fetch,parse,normalize,adapters,archive,corrections,r2_parse,repo_archive,urls}` |
| `storage/` | SQLite store, receipts, coverage ledger | `sqlite_store`, `schema`, `migrations`, `coverage_ledger`, `trusted_receipt`, `receipt_crypto`, `immutable_artifact`, `migrate_jquants_keys` |
| `pit/` | Point-in-time sole read path for facts | `api`, `query`, `models`, `errors` |
| `core/` | Backtest engine | `engine`, `execution`, `costs`, `metrics`, `result`, `universe`, `strategy_protocol`, `strategies/buy_hold` |
| `features/` | Feature registry / runtime | `registry`, `runtime`, `types`, `v0` |
| `strategies/` | Spec + paper runners | `spec/{schema,interpreter}`, `paper/{runner,store,types}`, `examples/{momentum,return_1d}` |
| `paper_runtime/` | READY / coherence / snapshots | `snapshot`, `ready_policy`, `coherence`, `execution`, `experiment_index`, `code_fingerprints` |
| `cf_platform/` | Python mirrors of CF Worker logic | `live_gates`, `ingest_premium/{availability,coverage,matrix,natural_key,validate}` |
| `data_contracts/` | JSON SoT + loaders | `loader`, `canonical`, `coverage`, `identity`, `inventory`, `jsda` + `*.json` package data |
| `agents/` | Multi-agent paper pipeline | `pipeline`, `roles`, `runtime`, `mass_research`, `isolated_runner`, role modules (`pm`, `quant`, `trader`, …) |
| `risk/` | Risk store | `store` |
| `data_access/` | Read-domain service | `service`, `adapter` |
| `mcp_servers/` | Local stdio MCP façade | `quant_data/{server,__main__}` |
| `price_basis` | Root py-module | `price_basis.py` |

### 2.2 First-party but **not** in setuptools `include`

| Package | Role | Modules |
|---------|------|---------|
| `execution/` | Paper execution service | `paper_service` |
| `gateway/` | AI gateway | `ai` |
| `knowledge/` | Knowledge store | `store` |
| `ops/` | Ops helpers | `backfill_planner`, `projection_meta` |
| `research/` | Research artifacts / readiness | `artifacts`, `occupancy_audit`, `readiness`, `scheduler` |
| `selection/` | Screening / budget | `screen`, `decision`, `budget_ledger` |

### 2.3 Non-package layout nodes

| Path | Notes |
|------|--------|
| `platform/workers/*` | Cloudflare Workers (TS/JS) + `wrangler.toml`; **not** importable as Python |
| `scripts/` | CLI drivers; bootstrap repo root onto `sys.path` |
| `tests/` | pytest suite; root + local conftest path hacks |
| `data/` | raw / structured / reports / paper (runtime data; excluded from package) |
| `docs/` | architecture + runbooks |
| `conftest.py` | **repo-root** pytest path bootstrap |
| `fof/` | README only (placeholder) |
| `raw/` | local JSDA raw mirror path |

### 2.4 First-party import graph (high signal)

Most imported **by tests:** `ingestion` (79), `storage` (62), `pit` (18), `agents` (17), `data_contracts` / `core` / `selection` (13 each).

**Production edges (non-test):**

```
ingestion → storage, data_contracts
storage → data_contracts, ingestion, cf_platform
pit → ingestion, storage
core → pit, features, price_basis
features → pit, price_basis
strategies → core, paper_runtime, features, price_basis
paper_runtime → data_contracts, storage, strategies, features, cf_platform
cf_platform → data_contracts, ingestion
data_access → data_contracts, pit, features, paper_runtime, storage
mcp_servers → data_access
agents → strategies, selection, research, execution, risk
execution → strategies, features, agents, paper_runtime
gateway → agents, strategies, selection
ops → data_contracts
research → selection, paper_runtime
knowledge → storage
risk → agents
```

---

## 3. `tests/` — top-level package imports

Counts = number of `from X …` / `import X` statements under `tests/**/*.py` (stdlib/third-party filtered).

| Count | Package | Test files |
|------:|---------|----------:|
| 79 | `ingestion` | 30 |
| 62 | `storage` | 32 |
| 18 | `pit` | 14 |
| 17 | `agents` | 5 |
| 13 | `data_contracts` | 11 |
| 13 | `core` | 5 |
| 13 | `selection` | 8 |
| 12 | `features` | 7 |
| 10 | `cf_platform` | 6 |
| 10 | `strategies` | 7 |
| 10 | `_coreseed` (tests helper) | 8 |
| 9 | `paper_runtime` | 7 |
| 6 | `scripts` | 4 |
| 5 | `tests` (self) | 4 |
| 4 | `gateway` | 3 |
| 4 | `research` | 2 |
| 3 | `data_access` | 3 |
| 3 | `ops` | 3 |
| 2 | `knowledge` | 2 |
| 2 | `mcp_servers` | 2 |
| 1 | `risk` | 1 |
| 1 | `execution` | 1 |

**Also loaded via path, not import name:**

| Mechanism | Targets |
|-----------|---------|
| `importlib.util.spec_from_file_location` | `scripts/sync_d1_to_sqlite.py`, `publish_ops_projection.py`, `export_ops_projection.py`, `run_phase4_accept.py`, `run_ingestion_once.py`, `run_phase35_validation.py` |
| `from scripts.…` | `run_ingestion_once`, `export_ops_projection`, `publish_ops_projection` |
| Hardcoded `platform/workers/...` paths | migrations SQL, `catalog.ts`, `availability.ts`, `identity.ts`, `index.ts`, `governed.js` parity |

---

## 4. `scripts/` — `sys.path` / `_REPO_ROOT` patterns

### 4.1 Pattern families

| Pattern | Meaning | Scripts |
|---------|---------|---------|
| **A.** `ROOT = Path(__file__).resolve().parents[1]` + `sys.path.insert(0, ROOT)` | Script lives in `scripts/`; parent = repo root | majority |
| **B.** `_REPO_ROOT = dirname(dirname(abspath(__file__)))` + `sys.path.insert` | Same depth, `os.path` style | `run_paper_once`, `run_agents_paper_once`, `run_ingestion_once`, `run_phase35_validation`, `run_phase4_accept`, `sync_d1_to_sqlite` |
| **C.** `ROOT = Path(__file__).resolve().parents[2]` | Script under `scripts/ops/` | `ops/cf_premium_backfill.py` |
| **D.** `ROOT = parents[1]` **without** `sys.path` | Path for subprocess/data only | `ops_reeval_freshness.py`, `run_historical_backfill.py` |
| **E.** No ROOT bootstrap | standalone | `report_d1_local_sync_lag.py` |

### 4.2 Per-script inventory

| Script | Bootstrap | Notable hard paths / deps |
|--------|-----------|---------------------------|
| `backfill_status_report.py` | A | `data_contracts`, `storage`; default `data/structured` |

| `export_ops_projection.py` | A | `paper_runtime`; publisher string |
| `generate_governed_js.py` | A | writes `platform/workers/quant-ops-mcp/src/governed.js` |
| `issue_signed_receipts_for_segments.py` | A | `storage` |
| `ops/cf_premium_backfill.py` | C (`parents[2]`) | CF premium backfill |
| `ops_reeval_freshness.py` | D | wrangler bin under `ingestion-premium/node_modules/.bin`; `--config=…/ingestion-premium/wrangler.toml`; `cwd=ROOT` |
| `ops_status.py` | A | `paper_runtime`, `storage` |
| `parse_jsda_from_r2_mirror.py` | A | `ingestion.jsda`; default `data/raw`, `data/structured` |
| `publish_ops_projection.py` | A | **`from scripts.export_ops_projection`**; wrangler cwd `quant-ops-mcp` or ROOT; config points at premium `wrangler.toml` |
| `rebuild_paper_index.py` | A | `strategies.paper`; default `data/paper` |
| `refresh_coverage_ledger.py` | A | `cf_platform.ingest_premium.coverage` |
| `report_d1_local_sync_lag.py` | E | docs/default DB strings only |
| `restore_local_complete_from_receipt.py` | A | storage/receipts |
| `run_agents_paper_once.py` | B | agents/paper |
| `run_historical_backfill.py` | D | ROOT for logs/DB defaults |
| `run_ingestion_once.py` | B | ingestion CLI |
| `run_paper_once.py` | B | paper once |
| `run_phase35_validation.py` | B | `cf_platform`; default `data/reports` |
| `run_phase4_accept.py` | B | `cf_platform.live_gates`; reports dir |
| `sync_d1_to_sqlite.py` | B | invokes sibling `publish_ops_projection.py` by path |
| `verify_governed_js_drift.py` | A | reads `platform/workers/quant-ops-mcp/src/governed.js` |
| `write_collection_receipts.py` | A | mentions premium migrations path in messages |

**Shell:** `cron_publish_ops.sh` — path-sensitive wrapper (same tree). `ops/cf_premium_backfill.py` is the backfill driver.

**Reorg rule:** any move of `scripts/` depth or of a package consumed only via `sys.path` breaks Pattern A/B/C. Prefer installing packages over path hacks long-term; short-term keep `parents[N]` consistent with new depth.

---

## 5. `conftest.py` path manipulation

### 5.1 Repo-root `/conftest.py`

```text
_REPO_ROOT = dirname(abspath(__file__))   # == repo root
sys.path.insert(0, _REPO_ROOT)
```

- Ensures `ingestion` / `storage` / all first-party packages import without editable install.
- Fixture `jsda_sample_text` opens `_REPO_ROOT / "tests/fixtures/jsda_sample.csv"`.
- Defines `FakeHttpClient` (uses `ingestion.common.http.HttpResponse`).

### 5.2 `tests/conftest.py`

```text
_REPO = Path(__file__).resolve().parents[1]   # repo root
_SYNC = _REPO / "scripts" / "sync_d1_to_sqlite.py"
# loaded via importlib.util.spec_from_file_location("sync_d1_to_sqlite", _SYNC)
```

- Session fixture `sync_module` dynamically loads the sync script (not an installed package).
- CF D1 export row fixtures for premium Worker shape.

### 5.3 Ad-hoc test path inserts

| File | Behavior |
|------|----------|
| `tests/test_features_compute.py` | inserts `tests/` onto `sys.path` for `_coreseed` |
| `tests/test_features_data_boundary.py` | inserts `tests/` parent for helper import |
| `tests/test_ops_projection_publish_guard.py` | inserts repo root; `from scripts.publish_ops_projection …` |

**Reorg rule:** root `conftest.py` must stay where pytest discovers it **or** pytest config must be updated. Moving `scripts/sync_d1_to_sqlite.py` breaks `tests/conftest.py` and several `spec_from_file_location` tests.

---

## 6. `platform/workers` ↔ `cf_platform` / `mcp_servers` cross-refs

### 6.1 Architecture split

| Plane | Location | Language | Role |
|-------|----------|----------|------|
| Live CF ingestion | `platform/workers/ingestion-premium` | TS | R2 + D1 closed loop, cron, export API |
| JSDA raw worker | `platform/workers/ingestion-jsda` | TS | public HTTP → R2; structured parse stays Python |
| Secrets proxy | `platform/workers/ingestion-secrets` | TS | secret-backed proxy |
| Ops Read MCP (remote) | `platform/workers/quant-ops-mcp` | JS | OAuth MCP, 12 read tools, ops projection tables |
| Python CF helpers | `cf_platform/` | Python | validation / natural_key / coverage / B0 gates (local DB) |
| Local research MCP | `mcp_servers.quant_data` | Python | stdio MCP over `data_access` (dev/test only) |

Naming: `cf_platform` exists because **`platform` is stdlib** and `platform/` on disk is not a package (`cf_platform/__init__.py` documents this).

### 6.2 Python → CF helpers

| Consumer | Import |
|----------|--------|
| `storage/coverage_ledger.py` | `cf_platform.ingest_premium.coverage` |
| `paper_runtime/snapshot.py` | `cf_platform.ingest_premium.coverage` |
| `scripts/refresh_coverage_ledger.py` | same |
| `scripts/run_phase35_validation.py` | coverage |
| `scripts/run_phase4_accept.py` | `cf_platform.live_gates.b0_pass` |
| Tests (phase35/4/61) | `availability`, `natural_key`, `validate`, `matrix`, `coverage`, `live_gates` |

### 6.3 Python ↔ Worker **file path** coupling (parity / codegen)

| Python side | Worker side | Coupling |
|-------------|-------------|----------|
| `cf_platform/ingest_premium/availability.py` | `ingestion-premium/src/availability.ts` | documented mirror; tests compare |
| `cf_platform/ingest_premium/natural_key.py` | `identity.ts` / catalog natural_key fields | parity tests |
| `data_contracts/*.json` | `catalog.ts` + premium set tests | contract SoT vs TS catalog |
| `scripts/generate_governed_js.py` | `quant-ops-mcp/src/governed.js` | **codegen** from `data_contracts.coverage` |
| `scripts/verify_governed_js_drift.py` | same `governed.js` | drift gate |
| `mcp_servers.quant_data` | docs in `quant-ops-mcp/README.md` | parallel read surface (local vs remote) |
| SQL migrations | `ingestion-premium/migrations/*`, `quant-ops-mcp/migrations/*` | tests apply SQL from these paths |

### 6.4 `mcp_servers` graph

```
mcp_servers.quant_data.server
  └── data_access (QuantDataAccess / QuantReadDomainService)
        ├── data_contracts
        ├── pit
        ├── features
        ├── paper_runtime
        └── storage
```

Tests: `test_phase6_data_access.py`, `test_phase61_read_service.py`.  
Run: `python -m mcp_servers.quant_data` (scripts README / quant_data_access docs).

### 6.5 Direction of dependencies (safe move order)

```
data_contracts  ←── many (JSON SoT; move carefully with package-data)
ingestion / storage / pit  ←── core research path
cf_platform  ←── storage, paper_runtime, scripts, tests  (not imported by Workers)
mcp_servers  ←── only tests + CLI  (depends on data_access)
platform/workers  ←── path strings from tests/scripts/docs; no Python import
```

Workers do **not** import Python. Coupling is path strings, mirrored algorithms, generated JS, and shared D1 schema.

---

## 7. `wrangler.toml` — cwd / deploy assumptions

Four configs (all under `platform/workers/<name>/wrangler.toml`):

| Worker dir | `name` | `main` | Deploy / secret patterns observed |
|------------|--------|--------|-----------------------------------|
| `ingestion-premium` | `quant-platform-ingestion-premium` | `src/index.ts` | **Dual:** (1) repo-root with `-c platform/workers/ingestion-premium/wrangler.toml`; (2) `cd platform/workers/ingestion-premium` then bare `npx wrangler deploy` |
| `ingestion-jsda` | `quant-platform-ingestion-jsda` | `src/index.ts` | Docs: **`cd platform/workers/ingestion-jsda`** then `npx wrangler deploy` |
| `ingestion-secrets` | `quant-platform-ingestion-secrets` | `src/index.ts` | Docs: **cd into worker dir**; also `-c platform/workers/ingestion-secrets/wrangler.toml` from root |
| `quant-ops-mcp` | `quant-platform-ops-read-mcp` | `src/index.js` | Docs/runbooks: **`cd platform/workers/quant-ops-mcp`** then deploy / `d1 execute` |

### 7.1 Shared D1

All three data workers + ops MCP bind D1 **`quant-ingest`** (`database_id = be6fdcf8-…`).  
Relative paths in wrangler (`main = "src/…"`, `migrations/`) resolve **relative to the wrangler config file’s directory**, not the shell cwd — but many runbooks still `cd` into the worker so local `node_modules/.bin/wrangler` and relative `--file=migrations/…` work.

### 7.2 Automation cwd (scripts)

| Script | wrangler binary | config | subprocess `cwd` |
|--------|-----------------|--------|------------------|
| `ops_reeval_freshness.py` | `platform/workers/ingestion-premium/node_modules/.bin/wrangler` | premium `wrangler.toml` via `--config=` | **repo root** |
| `publish_ops_projection.py` (probe) | same local bin if present else `npx wrangler` | premium config via `--config=` | local bin → `quant-ops-mcp`; else **repo root** |
| `publish_ops_projection.py` (apply) | `npx wrangler` style | via cwd | **`platform/workers/quant-ops-mcp`** |

### 7.3 Reorg rules for Workers

1. Keep each worker’s `wrangler.toml` **co-located** with `src/` and `migrations/` **or** update every `-c`, `cd`, and script hard path.
2. Prefer **repo-root** invocations with absolute/relative `-c` / `--config=` after reorg so automation does not depend on shell cwd.
3. Local wrangler binary currently assumed under **`ingestion-premium/node_modules`** — moving that tree breaks `ops_reeval_freshness` / publish probe unless paths update.
4. Do not rename D1 binding casually; remote MCP + ingest share `quant-ingest`.

---

## 8. Move-fragile hotspots (top 20)

Ranked by breakage blast radius (import graph + hardcoded paths + deploy/ops).

| # | Hotspot | Why fragile | Touch points |
|---|---------|-------------|--------------|
| 1 | **`conftest.py` (repo root) `sys.path`** | Entire offline test suite assumes root on path | all tests without editable install |
| 2 | **`scripts/` path bootstrap (`parents[1]` / dirname×2)** | ~20 CLIs; depth-sensitive | every ops/paper/ingest driver |
| 3 | **`scripts/sync_d1_to_sqlite.py`** | Loaded by `tests/conftest.py` via `spec_from_file_location`; production sync CLI | tests fixtures, phase35/6 sync tests |
| 4 | **`platform/workers/ingestion-premium/`** | Deploy config, migrations SQL, TS catalog/availability/identity parity, local wrangler bin | tests `test_phase35_*`, `test_identity_*`, `test_phase6_history_sync`, scripts wrangler paths, runbooks |
| 5 | **`platform/workers/quant-ops-mcp/`** | Ops projection migrations; generated `governed.js`; deploy cwd | `test_ops_projection_*`, `generate_governed_js`, `verify_governed_js_drift`, publish script |
| 6 | **`data_contracts/` + `*.json` package-data** | SoT for governed sets, loaders use `Path(__file__).with_name(...)` | ingestion, storage, cf_platform, ops, scripts, Workers catalog parity |
| 7 | **`cf_platform/`** | Imported by storage/paper_runtime/scripts; mirrors Worker algorithms | coverage ledger, READY snapshot, B0 gates |
| 8 | **`storage/`** | Hub package (ingestion, pit, paper_runtime, knowledge, data_access, scripts, tests) | largest production fan-in after tests |
| 9 | **`ingestion/`** | Most-tested package; common HTTP used by root conftest | 30 test files, pipeline CLIs |
| 10 | **`scripts/publish_ops_projection.py` + `export_ops_projection.py`** | Cross-import `from scripts.…`; wrangler cwd matrix; publisher string literals | lane-e / ops projection tests |
| 11 | **`scripts/generate_governed_js.py` ↔ `governed.js`** | Codegen path hardcoded; drift test | ops MCP domain import of GOVERNED_* |
| 12 | **Hardcoded `platform/workers/...` in tests** | String paths, not imports | `test_phase35_availability`, `premium_set`, `identity_runtime_parity`, `phase61_coverage_v2`, `ops_projection_publish`, … |
| 13 | **Unpackaged first-party packages** (`selection`, `ops`, `research`, `execution`, `gateway`, `knowledge`) | Only work via repo-root `sys.path`; easy to “lose” in packaging reorg | agents, gateway, research, scripts, tests |
| 14 | **`pit/` sole-read boundary** | core/features/data_access depend on it; architecture invariant | any namespace move needs doc + import fix |
| 15 | **`paper_runtime/`** | Bridges storage, contracts, cf_platform, strategies | READY / ops projection / paper scripts |
| 16 | **`mcp_servers/` + `data_access/`** | CLI module path `python -m mcp_servers.quant_data`; docs/README | phase6/61 tests, quant_data_access.md |
| 17 | **`price_basis` py-module** | Root-level module listed in setuptools; imported by core/features/strategies | pyproject `py-modules` |
| 18 | **Default data paths `data/structured`, `data/raw`, `data/reports`, `data/paper`** | Dozens of CLI defaults and docs | scripts, runbooks — not code layout but ops coupling |
| 19 | **`scripts/ops/cf_premium_backfill.py` (`parents[2]`)** | Nested depth different from sibling scripts | easy off-by-one if scripts reparented |
| 20 | **Dual wrangler invocation styles** (cd-into-worker vs `-c` from root) | Runbooks disagree; automation uses both | phase35/61/62 runbooks, worker READMEs |

### Secondary watchlist

- `tests/_coreseed.py` + tests-dir `sys.path` inserts.
- `storage/receipt_crypto.py` / `ops/backfill_planner.py` pathing into `data_contracts/`.
- egg-info stale top_level (install metadata drift).
- `import scripts.*` from tests — `scripts` is not a package entry in setuptools; depends on root path.

---

## 9. Suggested reorg constraints (inventory conclusions)

1. **Do not move** `platform/workers/*` without a single coordinated path rewrite (tests + scripts + docs + wrangler automation).
2. **Keep** `data_contracts` JSON co-located with loader modules **or** switch fully to `importlib.resources`.
3. **Either** add currently unpackaged dirs to `packages.find.include` **or** keep root `sys.path` bootstrap forever.
4. **Collapse** script bootstrap to one helper (`_REPO_ROOT` module) before directory depth changes.
5. **Separate** “Python import tree” moves from “Worker tree” moves — different coupling mechanisms.
6. **Mass ON / mass research** remains out of scope for layout work; do not touch mass gates while reorging.

---

## 10. Quick reference — absolute layout (repo root)

```text
quant-platform/
  conftest.py                 # sys.path → repo root
  price_basis.py              # setuptools py-module
  pyproject.toml
  agents/  cf_platform/  core/  data_access/  data_contracts/
  execution/  features/  gateway/  ingestion/  knowledge/
  mcp_servers/  ops/  paper_runtime/  pit/  research/
  risk/  selection/  storage/  strategies/
  platform/workers/
    ingestion-premium/   wrangler.toml + src/ + migrations/
    ingestion-jsda/
    ingestion-secrets/
    quant-ops-mcp/       wrangler.toml + src/ + migrations/
  scripts/   (+ scripts/ops/)
  tests/     (+ tests/conftest.py, fixtures/)
  data/  docs/  fof/  raw/
```
