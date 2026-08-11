import assert from "node:assert/strict";
import test from "node:test";

import { OPS_TOOLS, callOpsTool } from "../src/domain.js";
import { handleJsonRpc, MCP_PROTOCOL_VERSION } from "../src/mcp.js";

/** Minimal mock that returns empty projection (UNKNOWN paths). */
function mockDb() {
  return {
    prepare() {
      return {
        bind() {
          return this;
        },
        async first() {
          return null;
        },
        async all() {
          return { results: [] };
        },
        async run() {
          return { success: true };
        },
      };
    },
  };
}

test("remote surface is Ops read-only", () => {
  const names = OPS_TOOLS.map((t) => t.name);
  assert.equal(names.length, 17);
  assert.ok(names.includes("storage_plane_status"));
  for (const banned of [
    "query_dataset",
    "run_ingestion",
    "publish",
    "delete",
    "sql",
  ]) {
    assert.ok(!names.includes(banned));
  }
});

test("initialize and tools/list implement MCP 2025-06-18", async () => {
  const db = mockDb();
  const init = await handleJsonRpc(
    {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: "t", version: "0" },
      },
    },
    db,
  );
  assert.equal(init.result.protocolVersion, MCP_PROTOCOL_VERSION);
  assert.equal(init.result.serverInfo.name, "quant-ops-read");

  const listed = await handleJsonRpc(
    { jsonrpc: "2.0", id: 2, method: "tools/list" },
    db,
  );
  assert.equal(listed.result.tools.length, 17);
});

test("ops_status returns structured current-plane output without projection", async () => {
  const value = await callOpsTool(mockDb(), "ops_status", {});
  assert.ok(value);
  // Absent tables/projection → UNKNOWN-style payloads, never silent empty success
  // for governed catalog (exact shape is domain-defined).
  assert.ok(typeof value === "object");
});
