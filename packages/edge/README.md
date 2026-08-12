# packages/edge

CF-adjacent Python helpers and local MCP. Import names stay leaf top-level.

## Leaf packages

| Import | Role |
|--------|------|
| `cf_platform` | Python SoT mirror for Premium coverage / validate / natural_key / live_gates (volume B0 ≠ Track B0) |
| `mcp_servers` | Local stdio quant_data MCP (dev/offline only) |

## Allowed deps

- `data_contracts`, `ingestion` (algorithm / catalog parity)
- `mcp_servers` → `data_access`

## Forbidden

- Import `research_runtime` / `product` compute stacks
- Import or move Cloudflare Workers (`platform/workers/**` is path-frozen)
- Treat local MCP as production Ops MCP (remote is Worker)

## Public entrypoints

| Package | Prefer |
|---------|--------|
| `cf_platform` | `ingest_premium.*`, `live_gates.measure_b0` |
| `mcp_servers` | `python -m mcp_servers.quant_data` |

## Policy

- Workers stay under `platform/workers/` (wrangler / deploy / runbooks hardcode paths)
- Batch Z import rewrite **DEFER**
- Guard: `tests/test_plane_import_boundaries.py`
- Nav: `docs/architecture/llm_nav_map.md`
