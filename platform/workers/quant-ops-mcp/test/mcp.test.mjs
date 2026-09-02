import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { OPS_TOOLS, callOpsTool } from "../src/domain.js";
import { handleHealthRequest } from "../src/health.js";
import { handleJsonRpc, handleMcpHttp, MCP_PROTOCOL_VERSION } from "../src/mcp.js";
import {
  ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
  opsToolSchemaDigest,
} from "../src/tool_schema_digest.js";

const acceptedToolSchema = JSON.parse(readFileSync(
  new URL("../../../../specs/ops_projection/mcp_tool_schema_acceptance.json", import.meta.url),
  "utf8",
));

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
  for (const path of ["/health", "/healthz", "/health/ready"]) {
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
  for (const path of ["/health", "/healthz", "/health/ready"]) {
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
  assert.equal(acceptedToolSchema.tool_count, listed.result.tools.length);
  assert.deepEqual(
    acceptedToolSchema.tool_names,
    listed.result.tools.map((tool) => tool.name),
  );
  assert.equal(
    acceptedToolSchema.schema_digest,
    ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
  );
  assert.equal(
    listed.result._meta["quant-platform/tool-schema-digest"],
    ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
  );
  assert.equal(
    await opsToolSchemaDigest(listed.result.tools),
    ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
  );
  const renamed = listed.result.tools.map((tool, index) => (
    index === 0
      ? { ...tool, description: `${tool.description} (drift)` }
      : tool
  ));
  assert.notEqual(
    await opsToolSchemaDigest(renamed),
    ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
  );
  const names = listed.result.tools.map((tool) => tool.name);
  for (const tool of listed.result.tools) {
    assert.equal(tool.inputSchema.type, "object", tool.name);
    assert.equal(tool.inputSchema.additionalProperties, false, tool.name);
    assert.equal(tool.outputSchema.type, "object", tool.name);
    assert.equal(tool.outputSchema.additionalProperties, false, tool.name);
  }
  for (const banned of ["ingest", "delete", "publish", "run_ingestion"]) {
    assert.ok(!names.includes(banned));
  }
});

test("ops_status returns structured current-plane output without projection", async () => {
  const value = await callOpsTool(mockDb(), "ops_status", {});
  assert.ok(value);
  assert.equal(value.status, "NOT_PROJECTED");
  assert.equal(value.projection_generation, null);
  assert.match(value.reason, /active Ops Projection generation/);
});
