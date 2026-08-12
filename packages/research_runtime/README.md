# packages/research_runtime

Compute stack (no external market network): backtest, features, strategies, paper, risk.

## Leaf packages (import names = leaf)

| Import | Role |
|--------|------|
| `core` | Black-box backtest; facts via `pit` only |
| `features` | Versioned feature registry; PIT-only facts |
| `strategies` | StrategySpec + paper runner (no direct DB/HTTP) |
| `paper_runtime` | READY policy, snapshots, coherence, fingerprints (may touch storage) |
| `risk` | Risk audit helpers (soft edge → `agents` types) |
| `price_basis` | Shared price-basis helpers |

## Allowed deps

- `core` / `features` → `pit`, `price_basis`
- `strategies` → `core`, `features`, `paper_runtime`, `price_basis`
- `paper_runtime` → `data_contracts`, `storage`, `strategies`, `features`, `cf_platform`
- **Exception:** `risk` → `agents` (soft type edge; do not expand casually)

## Forbidden

- `core` / `features` / `strategies`: no `storage`, no `ingestion` HTTP, no raw `sqlite3` for facts
- No `agents` / `gateway` / `selection` / `execution` except the documented `risk` soft edge
- No Mass ON / production READY publish from this plane

## Public entrypoints

| Package | Prefer |
|---------|--------|
| `core` | `run_backtest`, cost helpers, Strategy protocol |
| `features` | registry / `compute` / `v0` defs |
| `strategies` | `spec.schema`, `spec.interpreter`, `paper.*` |
| `paper_runtime` | `ready_policy`, snapshot APIs, `check_ready_coherence` |

## Policy

- Leaf imports only (Batch Z **DEFER**)
- Guards: `tests/test_core_data_boundary.py`, `test_features_data_boundary.py`, `test_strategies_static_boundaries.py`, `test_plane_import_boundaries.py`
- Residual: Mass / READY / Phase7 **NO-GO / OFF** — `docs/phase62_residual_status.md`
- READY / B0 production GO is **not** declared from this plane; paper_runtime READY is research machinery only
- Test navigation: `tests/README.md` (G0/G1/G2)
