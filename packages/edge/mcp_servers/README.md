# mcp_servers

**Local stdio** MCP adapters for offline / dev. Production remote Ops MCP is the Worker at `platform/workers/quant-ops-mcp` (path frozen).

## Public entry

```bash
python -m mcp_servers.quant_data
```

## Allowed imports

- `data_access` (and transitively its allow-list)

## Forbidden

- Replacing remote Ops MCP trust domain with local stdio in production claims
- Market HTTP outside ingestion
- Enabling Mass research

Domain doc: [docs/quant_data_access.md](../../../docs/quant_data_access.md).
