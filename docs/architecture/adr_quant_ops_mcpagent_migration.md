# ADR: Feature-freeze Quant Ops McpAgent and migrate statelessly

| Field | Value |
|-------|-------|
| **Status** | **Accepted — compatibility hold, migration pending** |
| **Date** | 2026-08-28 |
| **Scope** | `platform/workers/quant-ops-mcp` |
| **Related** | [`adr_worker_dependency_isolation.md`](./adr_worker_dependency_isolation.md), [`../operations/current_production_runbook.md`](../operations/current_production_runbook.md) |

## Context

Cloudflare's current Agents SDK documents `McpAgent` as deprecated and
feature-frozen and recommends the stateless `createMcpHandler` API for new MCP
servers. Quant Ops still serves both streamable HTTP at `/mcp` and the legacy
SSE transport at `/sse`. There is no authoritative inventory proving that no
legacy client uses the stateful/SSE route, so deleting the Durable Object or
`/sse` immediately would be an unreviewed compatibility break.

There is also a narrower security issue to contain during the transition. The
Agents constructor copies framework methods onto the application prototype.
Cloudflare Durable Object RPC exposure follows runtime prototype behavior, not
TypeScript intent, so reviewing only the product-owned `init` method understates
the surface.

## Decision

`McpAgent` is feature-frozen in this repository. No new product behavior may be
added through its inherited RPC surface. Until migration completes:

- `agents` is pinned to exact `0.17.4` and installed with `npm ci`;
- the raw package-lock SHA-256, resolved version, tarball URL and npm integrity
  are part of the machine-readable active binding manifest;
- workerd constructs a real `QuantOpsMcpAgent` and freezes the canonical
  prototype chain as owner/order/name/kind plus descriptor flags, exact counts
  and SHA-256 digests;
- reserved runtime specials (`fetch`, `alarm` and the three WebSocket handlers)
  are inventoried separately from ordinary methods;
- `MCP_OBJECT` is a self-only namespace and the Worker receives no Service
  Binding; another Worker may not receive this namespace or a stub to the Ops
  Worker;
- public HTTP and MCP JSON-RPC tests reject generic forwarding of inherited
  `sql`, `agent` and `server` members and prove no agent SQLite change;
- exact live module bytes, when collected by deployment acceptance, must match
  the reviewed build. The module embeds the binding-manifest schema and digest,
  connecting those bytes to this inventory.

The lockfile is not a Cloudflare live observation. Its guarantee is transitive:
exact lock bytes and npm integrity select the dependency, workerd validates the
resulting runtime surface, and deployment acceptance compares the resulting
module bytes. Source tests do not assert that an undeployed candidate is live.

## Migration sequence

1. Inventory authenticated clients and distinguish `/mcp` users from `/sse`
   sessions. Absence of an inventory is not evidence that `/sse` is unused.
2. Implement the reviewed server registration with stateless
   `createMcpHandler`, preserving the closed 17-tool schema and OAuth boundary.
3. Migrate `/mcp` to the stateless handler and verify authorized/unauthorized
   behavior, quotas and exact tool/schema parity in staging, then production.
4. Keep `/sse` on the feature-frozen legacy handler while observed sessions and
   explicitly identified legacy clients drain.
5. After an evidence-backed drain window, remove `/sse`, the `MCP_OBJECT`
   binding/migration and the `agents` dependency in one reviewed release.

Rollback during steps 2–4 restores the prior `/mcp` route without changing the
legacy `/sse` path. No step enables READY, Controlled Pilot, Mass Research or
any write/admin tool.
