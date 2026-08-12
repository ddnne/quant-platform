# packages/product

Orchestration and product surfaces (agents, selection, gateway stubs).

## Leaf packages (import names = leaf)

| Import | Role |
|--------|------|
| `agents` | Role pipeline, structured messages, mass_research (**fail-closed**) |
| `research` | Research readiness / evaluation helpers |
| `selection` | Screening + experiment budget |
| `execution` | Authorized paper execution service |
| `knowledge` | Content-addressed artifact store (foundation) |
| `gateway` | AI gateway stubs (**fail-closed**) |
| `fof` | Placeholder only (future FoF) |

## Allowed deps

- `agents` → `strategies`, `selection`, `research`, `execution`, `risk`
- `execution` ↔ `agents` (known cycle; prefer types-only if split later)
- `gateway` → `agents`, `strategies`, `selection`
- `knowledge` → `storage`
- `research` → `selection`, `paper_runtime`

## Forbidden

- Import `ingestion` for market fetch (product must not open market HTTP)
- Mint Coverage COMPLETE or bypass Mass readiness
- Enable Phase 7 production LLM loops / Mass ON
- Open sockets from `gateway` for “real” remote AI in B1

## Public entrypoints

| Package | Prefer |
|---------|--------|
| `agents` | pipeline, roles, `mass_research` (fail-closed) |
| `gateway` | fail-closed AI stubs only |
| `selection` | `screen`, budget ledger |
| `execution` | paper execution service |

## Policy

- Leaf imports only; Batch Z **DEFER**
- Guards: `tests/test_mass_research_gate.py`, `test_gateway_fail_closed.py`, `test_plane_import_boundaries.py`
- Residual SoT: `docs/phase62_residual_status.md` (Mass/READY/Phase7 **NO-GO / OFF**)
- Phase 7 docs: `docs/architecture/phase7_fail_closed.md`, `docs/operations/phase7_foundation_off.md`
- Product plane **never** issues Coverage COMPLETE (receipts live in data_plane/storage)
