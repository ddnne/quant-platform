import assert from "node:assert/strict";
import test from "node:test";

import { OPS_TOOLS, callOpsTool } from "../src/domain.js";
import { handleHealthRequest } from "../src/health.js";
import { handleJsonRpc, handleMcpHttp, MCP_PROTOCOL_VERSION } from "../src/mcp.js";

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
    "ingest",
    "publish",
    "delete",
    "sql",
  ]) {
    assert.ok(!names.includes(banned));
  }
});

test("POST /health and /healthz are 405 GET, HEAD only", async () => {
  for (const path of ["/health", "/healthz"]) {
    const res = handleHealthRequest(
      new Request(`https://ops.test${path}`, { method: "POST" }),
    );
    assert.ok(res);
    assert.equal(res.status, 405);
    assert.equal(res.headers.get("Allow"), "GET, HEAD");
    const raw = await res.text();
    assert.equal(raw, "");
    assert.doesNotMatch(raw, /\bREADY\b/);
    assert.doesNotMatch(raw, /\bCOMPLETE\b/);
    assert.doesNotMatch(raw, /\bFRESH\b/);
  }
  assert.equal(
    handleHealthRequest(new Request("https://ops.test/mcp", { method: "POST" })),
    null,
  );
});

test("GET /health is liveness ok not READY", async () => {
  for (const path of ["/health", "/healthz"]) {
    const res = handleHealthRequest(new Request(`https://ops.test${path}`));
    assert.ok(res);
    assert.equal(res.status, 200);
    const raw = await res.text();
    const body = JSON.parse(raw);
    assert.equal(body.ok, true);
    assert.equal(body.service, "quant-ops-read-mcp");
    assert.notEqual(body.status, "READY");
    assert.notEqual(body.status, "COMPLETE");
    assert.notEqual(body.status, "FRESH");
    assert.doesNotMatch(raw, /\bREADY\b/);
    assert.doesNotMatch(raw, /\bCOMPLETE\b/);
    assert.doesNotMatch(raw, /\bFRESH\b/);
    const head = handleHealthRequest(
      new Request(`https://ops.test${path}`, { method: "HEAD" }),
    );
    assert.ok(head);
    assert.equal(head.status, 200);
    assert.equal(await head.text(), "");
  }
});

test("GET /mcp is 405 POST-only", async () => {
  const res = await handleMcpHttp(
    new Request("https://ops.test/mcp", { method: "GET" }),
    mockDb(),
  );
  assert.equal(res.status, 405);
  assert.equal(res.headers.get("Allow"), "POST");
  const body = await res.json();
  assert.equal(body.error, "GET event stream is not offered; use Streamable HTTP POST");
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
  const names = listed.result.tools.map((tool) => tool.name);
  for (const banned of ["ingest", "delete", "publish", "run_ingestion"]) {
    assert.ok(!names.includes(banned));
  }
});

test("ops_status returns structured current-plane output without projection", async () => {
  const value = await callOpsTool(mockDb(), "ops_status", {});
  assert.ok(value);
  // Absent tables/projection → UNKNOWN-style payloads, never silent empty success
  // for governed catalog (exact shape is domain-defined).
  assert.ok(typeof value === "object");
  assert.equal(value.raw_retention.acquired, 0);
  // deprecated alias of acquired; not Dataset COMPLETE
  assert.equal(value.raw_retention.complete, 0);
});
