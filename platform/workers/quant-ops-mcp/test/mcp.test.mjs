import assert from "node:assert/strict";
import test from "node:test";

import { OPS_TOOLS } from "../src/domain.js";
import { handleJsonRpc, handleMcpHttp } from "../src/mcp.js";

function dbWith(rows = []) {
  return {
    prepare(sql) {
      return {
        bind() {
          return {
            async all() { return { results: rows }; },
            async first() { return rows[0] || null; },
          };
        },
      };
    },
  };
}

test("remote surface is Ops read-only", () => {
  const names = OPS_TOOLS.map((tool) => tool.name);
  assert.deepEqual(names, [
    "ops_status", "ingestion_last_run", "dataset_coverage", "coverage_gaps",
    "coverage_segments", "backfill_status", "validation_summary", "b0_status",
    "latest_ready_snapshot", "snapshot_quality", "raw_retention_status", "sync_status",
  ]);
  assert.equal(names.some((name) => /sql|trigger|delete|publish|approve|broker|shell|fetch_url/i.test(name)), false);
});

test("initialize and tools/list implement MCP 2025-06-18", async () => {
  const initialized = await handleJsonRpc({
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } },
  }, dbWith());
  assert.equal(initialized.result.protocolVersion, "2025-06-18");
  const listed = await handleJsonRpc({ jsonrpc: "2.0", id: 2, method: "tools/list" }, dbWith());
  assert.equal(listed.result.tools.length, 12);
});

test("malformed lifecycle and unsupported protocol headers reject", async () => {
  const malformed = await handleJsonRpc({ jsonrpc: "2.0", id: 1, method: "initialize" }, dbWith());
  assert.equal(malformed.error.code, -32602);
  const notification = await handleJsonRpc({
    jsonrpc: "2.0", method: "initialize",
    params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: {} },
  }, dbWith());
  assert.equal(notification.error.code, -32600);
  assert.equal(notification.id, null);
  const response = await handleMcpHttp(new Request("https://ops.example/mcp", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "MCP-Protocol-Version": "2024-11-05",
    },
    body: "{}",
  }), dbWith());
  assert.equal(response.status, 400);
});

test("streamable HTTP rejects an invalid Accept header", async () => {
  const response = await handleMcpHttp(new Request("https://ops.example/mcp", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize" }),
  }), dbWith());
  assert.equal(response.status, 406);
});

test("tool calls return structured current-plane output", async () => {
  const result = await handleJsonRpc({
    jsonrpc: "2.0", id: 3, method: "tools/call",
    params: { name: "ingestion_last_run", arguments: {} },
  }, dbWith([{ id: 7, status: "pass" }]));
  assert.equal(result.result.structuredContent.plane, "ops_current");
  assert.equal(result.result.structuredContent.mutable, true);
});
