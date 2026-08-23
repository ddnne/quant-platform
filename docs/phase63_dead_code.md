# Phase 6.3 — unused-module audit (real vs false-positive)

**Lane:** dead-code / D-dead (B1-c follow-up)  
**HEAD base:** `41003a5` (`origin/main`)  
**Worktree:** `p63/lane-dead-code`  
**Mass / READY / Phase 7 / GO:** unchanged (NO-GO / not declared / OFF).  
**Dataset COMPLETE:** not this lane (do not invent).

This note classifies **modules**, not “zero `import pkg.mod` grep hits”.
Relative imports (`from .engine import run_backtest`) and
`from pkg import name` aliases are resolved. Naive absolute-import greps
are **false-positive** on this tree (ADR §8 / nav map B1-c).

Prefer consolidating tests over deleting production math. Protected
surfaces were not edited.

---

## Method

1. AST-walk every `*.py` under `packages/`, `scripts/`, `tests/`, plus
   `qp_paths.py` / `conftest.py`.
2. Resolve `Import` / `ImportFrom` including **relative** levels against
   the importer’s package (`__init__.py` keeps the package; modules drop
   the leaf). Record `from pkg import name` as `pkg.name`.
3. A production module is **used** if any *other* module imports it (or
   a name under it). Package `__init__.py` re-exports count (this is how
   `from core import engine` keeps `core.engine` alive).
4. String-scan `*.py` / `*.ts` / `*.mjs` / `*.md` / `*.json` for the five
   zero-AST names (docs, Worker mirrors, `python -m` entry points).
5. Dynamic: `research.unique_logic.__getattr__` →
   `import_module("research.unique_logic.{name}")` for
   `adaptive|cross_section|cs_overlays|event|event_filters|event_sides`.
6. `python -m` entry points (`mcp_servers.quant_data`,
   `research.unique_logic`) are not AST-imported; they are live CLIs.

**Not a deletion signal:** tests-only import of fail-closed / parity /
catalog / example-strategy modules; script-only ingest/ops writers;
Worker Python mirrors (`cf_platform.ingest_premium.*`).

---

## Keep / delete table

Legend: **Keep** = leave in tree. **Delete** = removed this lane or
eligible under §8.3. **Unsure** = document only.

### Production modules with zero AST importers

| Module | Bytes | Class | Action | Why |
|--------|------:|-------|--------|-----|
| `ingestion.jquants.bulk` | 1 762 | D-deferred mapping | **Keep** | No importers, no tests. Maps confirmed `/v2/bulk/equities/bars/{daily,minute}`. Cited in `docs/phase35_cf_ingest.md`. Docstring is a later-phase hook, not a husk. Deleting loses the bulk URL SoT. |
| `ingestion.jsda.adapters` | 4 041 | Formal surface | **Keep** | Unwired into fetch/parse. Nav map + ADR B1-c already: **not D-dead**. Adapter specs (OTC / repo / corp). |
| `paper_runtime.execution` | 1 668 | D-name-collision husk | **Keep (unsure)** | Zero importers; `paper_runtime.__init__` does not re-export. Live choke point is `execution.paper_service` + `agents.types.AuthorizedPaperExecutionRequest`. ADR §8.2: keep all three `execution` modules. Do not delete production paper math. |
| `mcp_servers.quant_data.__main__` | 51 | Entry point | **Keep** | `python -m mcp_servers.quant_data` (docs / scripts README). |
| `research.unique_logic.__main__` | 297 | Retired fail-closed stub | **Keep** | `python -m research.unique_logic` must still exit non-zero. `test_unique_logic_cli_is_retired` subprocesses it. Occupancy SoT is CF `daily_path`, not this CLI. |

**Production modules deleted this lane: 0.**

### Protected surfaces (lane constraint — never delete / rewrite)

| Surface | Production import? | Action |
|---------|--------------------|--------|
| `research.baseline_catalog` | Tests only (`test_baseline_catalog`) | **Keep.** Rejected S1–S5; Mass/READY false. |
| `research.cost_models` | Yes (`offline.*`, `cost_repo`, mass thicken) | **Keep.** Do not rewrite. Split tests stay split. |
| `research.options_225_vol_series` | Yes (`eval_loaders_sidecars`, `offline.factory_eval_data`) | **Keep.** Do not rewrite. |
| daily_path leftover occupancy | Worker `combo_gates.test.ts` + YAML leftover vs `params.gates` | **Keep.** Unique-22 leftover (`event_pre_mom_agree_hold` uses `entryIdx`, not combo `pre_mom`). |
| unique22 park YAML / `UNIQUE22_PARK_REASONS` | `worker_bodies`, `occupancy_audit`, `eval_summary` | **Keep.** Do not delete park YAML. |

`test_unique_logic_event_filters.py::test_worker_leftover_pre_mom_uses_entryidx_not_combo_pre_mom`
has a Worker `daily_path.ts` grep that **echoes** `combo_gates.test.ts`.
YAML leftover-vs-lifted is unique. This lane **did not** drop either half.

### Test-only production modules (not D-dead)

These have no `packages/` importer besides themselves, but they are
public contracts, fail-closed gates, or Py↔TS mirrors. Tests are the
importers **on purpose**.

| Module | Tests | Action |
|--------|-------|--------|
| `agents.mass_research` | `test_mass_research_gate`, `test_research_freezes` | **Keep** G0 Mass fail-closed |
| `agents.isolated_runner` | `test_process_isolated_runner` | **Keep** allowlisted binaries |
| `gateway` / `gateway.ai` | `test_gateway_fail_closed` | **Keep** G0 |
| `research.baseline_catalog` | `test_baseline_catalog` | **Keep** (protected) |
| `research.catalog_compiler` | `test_catalog_compiler` | **Keep** closed-DSL; YAML not deleted |
| `research.catalog_family` | `test_catalog_family` | **Keep** flow-gate ≠ flow family |
| `research.evaluation_ir` | `test_evaluation_ir` | **Keep** |
| `research.research_capabilities` | `test_research_capabilities` | **Keep** deny-by-default |
| `research.phase7_pilot` | `test_phase7_pilot_construct` | **Keep** construct-gated; Phase 7 OFF |
| `research.cf_cost_verify` | `test_cf_cost_verify` | **Keep** |
| `research.occupancy_audit` | `test_occupancy_audit` | **Keep** leftover / unique22 park |
| `research.paper_candidate_adapt` | adapter + freezes | **Keep** unarmed |
| `research.r2_feature_context` | `test_r2_feature_context` | **Keep** |
| `research.eval_summary` | catalog / combo / eval_registry | **Keep** |
| `cf_platform.ingest_premium.availability` | `test_phase35_availability` | **Keep D-mirror** |
| `cf_platform.ingest_premium.natural_key` | `test_phase35_natural_key` | **Keep D-mirror** |
| `data_contracts.inventory` | `test_phase62_inventory_phase7` | **Keep** governed inventory |
| `ingestion.jsda.r2_parse` | `test_phase623_receipt_signature` | **Keep** receipt path |
| `knowledge` / `knowledge.store` | inventory / knowledge tests | **Keep** placeholder package |
| `core.strategies` / `core.strategies.buy_hold` | engine / paper tests | **Keep** documented public example (`core/__init__.py`) |

### Script-only production (ingest / ops writers)

| Module | Importers | Action |
|--------|-----------|--------|
| `ingestion.jsda.archive` | `scripts.run_ingestion_once` + JSDA tests | **Keep** |
| `ingestion.jsda.corrections` | same | **Keep** |
| `ingestion.jsda.repo_archive` | same | **Keep** |
| `ops.projection_meta` | export + publish scripts | **Keep** |
| `storage.sqlite_store` | ingest/ops scripts + 35 tests | **Keep** (not re-exported from `storage.__init__`; that is **not** unused) |

### False-positive class (do not mass-delete)

Heuristic greps for `import core.engine` / `from core.engine import`
miss:

| Pattern | Example | Resolved as |
|---------|---------|-------------|
| Relative re-export | `core/__init__.py`: `from .engine import run_backtest` | `core.engine` used by `core` |
| Leaf alias | `from core import engine` | `core.engine` |
| Lazy unique_logic | `from research.unique_logic import event` | `import_module("research.unique_logic.event")` |
| `python -m` | `python -m mcp_servers.quant_data` | `__main__` entry |
| Docstring-only public API | `from core.strategies.buy_hold import BuyHold` | example strategy; tests import the module |

B1-c (2026-08-13) already warned: zero-ref scans false-positive on
`from core import engine`. This scan implements that resolution.
`jsda.adapters` remains the documented unwired surface, not a delete.

---

## Tests — consolidate vs delete

Lane 17 (`docs/phase63_test_audit.md`) left `test_ops_projection_meta.py`
as a merge candidate (2 tests: `MISSING` / `DEGRADED_REFRESH_FAILED`).
Those assertions are **not** a restatement of publish-SQL tests; they hit
`ops.projection_meta.build_projection_metadata` directly.

| Candidate | Class | Action | Rationale |
|-----------|-------|--------|-----------|
| `tests/test_ops_projection_meta.py` | Representative husk | **Deleted this lane** (merged) | Assertions moved into `test_ops_projection_publish.py`. Same invariants, one file. |
| `test_unique_logic_event_filters` Worker leftover grep | Dual-runtime echo | **Keep** | Lane constraint: daily_path leftover occupancy. YAML leftover-vs-lifted stays. |
| `test_catalog_yaml_parity` 2 254-file `family:`/`theme:` walks | Freeze file-count | **Document only** | Identity set-equality is invariant. |
| `test_research_capabilities::test_job_candidate_grade_false_on_partial` | Mild overlap with `test_evaluation_ir` | **Keep both** | Direct function vs IR encode path (`n_collapsed`). |
| cost_models / complete21 / phase35 splits | Split-monolith | **Keep split** | Prefer not re-merging math tests. |
| `tests/README.md` `unittest tests.test_smoke` | Nav bug | **Document** | Module absent at this tip (Lane 17). Not a test to add. |

PIT / `available_at` / receipts / false-COMPLETE / immutable READY /
`test_baseline_catalog.py` / G0 guards / Worker `combo_gates`: **never
delete**.

---

## Actions this lane

**Did**

- AST + relative-import unused-module audit of 229 production modules.
- Merged `test_ops_projection_meta.py` → `test_ops_projection_publish.py`
  (keep MISSING / DEGRADED_REFRESH_FAILED).
- Recorded keep reasons for the five zero-AST production files.

**Did not**

- Delete any production module
- Flip GO / Mass / READY / Phase 7
- Add YAML / delete unique22 park YAML
- Invent Dataset COMPLETE
- Rewrite `cost_models` / `options_225_vol_series`
- Edit `research-mass-eval` production `src/`
- Drop leftover occupancy tests

---

## Counts

| Metric | Before (`41003a5`) | After | Δ |
|--------|-------------------:|------:|--:|
| Production `packages/**/*.py` | 228 | 228 | 0 |
| Production modules deleted | — | **0** | 0 |
| `tests/` files (no `__pycache__`) | 150 | 149 | −1 |
| `tests/*.py` | 138 | 137 | −1 |
| `tests/test_*.py` | 131 | 130 | −1 |
| `tests/` bytes | 1 034 176 | 1 034 049 | **−127** |

Pytest subset (8 publish tests including the two moved rows, plus
publish-guard / phase61 export / lane-E / plane-import / leftover
event-filters / baseline_catalog / cost_models liquidity / options_225 /
occupancy_audit): **passed**.

That subset is the proof that (a) nothing imported the deleted test
module, and (b) protected production math still loads.
