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
- Live residual / COMPLETE counts: `docs/phase62_residual_status.md` only
- **Do not** launch `scripts/ops/cf_premium_backfill.py` from residual prose alone (coordinate multi-agent)

## Related remote resources (not Python packages)

| Resource | Name | Notes |
|----------|------|-------|
| D1 | `quant-ingest` | Coverage / receipts / raw manifests SoT |
| R2 | `quant-raw` | Verbatim J-Quants pages (`raw/{dataset}/{run_id}/`) |
| R2 | `quant-structured` | High-volume structured partitions |
| Workers | `platform/workers/*` | Path-frozen; wrangler from worker dir |
