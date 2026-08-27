# packages/data_plane

Contracts → ingest → store → PIT read → ops meta.

## Leaf packages (import names = leaf; **not** `data_plane.*`)

| Import | Role |
|--------|------|
| `data_contracts` | JSON contracts, coverage identity, governed sets (CF-adjacent SoT) |
| `ingestion` | **Only** external market network plane (J-Quants / JSDA) |
| `storage` | Structured write, receipts, coverage ledger |
| `pit` | **Sole** structured fact read path (`as_of` required) |
| `data_access` | Ops/research read façade (shared adapter; may bridge to features/paper_runtime) |
| `ops` | Backfill planner, projection meta helpers |

## Allowed deps (plane)

- Within `data_plane` leaves as documented in ADR §5.1
- `storage` / `cf_platform` helpers (edge) for coverage measurement reuse
- **Exception:** `data_access` → `features`, `paper_runtime` (intentional read-domain bridge)

## Forbidden

- Import `product.*` (`agents`, `gateway`, `selection`, …)
- `pit` / `ingestion` must not import `core` / `features` / `strategies`
- Market HTTP outside `ingestion`
- Fabricating COMPLETE or arming Mass/READY

## Public entrypoints (prefer)

| Package | Prefer |
|---------|--------|
| `pit` | `get_equity_bars_daily`, `get_equity_master`, `get_jquants_records`, `get_*` |
| `storage` | coverage ledger, receipt authority, schema/store writers |
| `ingestion` | `pipeline`, `jquants.catalog`, clients (root is namespace-light) |
| `data_contracts` | `loader` / `coverage` / `identity` + JSON package data |
| `data_access` | `QuantDataAccess`, ops/research read services |
| `ops` | `backfill_planner`, `projection_meta` |

## Operator CLIs (data_plane-facing)

| Script | Role |
|--------|------|
| `scripts/issue_receipts_parallel.py` | A3: seal months with **usable raw + structured** (empty-raw ban; no backfill) |
| `scripts/publish_ops_projection.py` | Export + fail-closed remote apply (`local COMPLETE ≥ remote`) |
| `scripts/ops_reeval_observed_window.py` | Receipt-plane `observed_*` reeval (no segment rewrite) |

## Policy

- **Import stability (B1):** leaf top-level names; Batch Z (`quant_platform.*`) **DEFER**
- Static guard: `tests/test_plane_import_boundaries.py`
- Live residual: `docs/phase62_residual_status.md` (Mass/READY/Phase7 **NO-GO / OFF**)
- Sticky COMPLETE: day-roll must not demote eligible SUCCESS (`storage/coverage_ledger.py`)
- Details: `docs/architecture/adr_llm_friendly_refactor.md`, `docs/architecture/llm_nav_map.md`
