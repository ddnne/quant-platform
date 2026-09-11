import assert from "node:assert/strict";
import test from "node:test";

import { handleMcpHttp } from "../src/mcp.js";

const encoder = new TextEncoder();
const JSON_TYPE = "application/json";
const VALID_ACCEPT = "application/json, text/event-stream";

const JSONRPC_PING = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" });
const JSONRPC_OPS_STATUS = JSON.stringify({
  jsonrpc: "2.0",
  id: 1,
  method: "tools/call",
  params: { name: "ops_status", arguments: {} },
});

/** Uint8Array body avoids Request(string) inserting text/plain. */
/** @param {string} body @param {HeadersInit} [headers] */
function postMcp(body, headers) {
  return new Request("https://ops.test/mcp", {
    method: "POST",
    headers,
    body: encoder.encode(body),
  });
}

function unusedDb() {
  const db = {
    prepareCount: 0,
    prepare() {
      db.prepareCount += 1;
      throw new Error("D1 must not be used before MCP HTTP admission");
    },
  };
  return db;
}

const HTTP_PREADMISSION = [
  {
    name: "absent Content-Type is 415",
    headers: { accept: VALID_ACCEPT },
    status: 415,
    json: { error: "application/json required" },
  },
  {
    name: "wrong Content-Type is 415",
    headers: { "content-type": "text/plain", accept: VALID_ACCEPT },
    status: 415,
    json: { error: "application/json required" },
  },
  {
    name: "wrong Content-Type and wrong Accept is 415",
    headers: { "content-type": "text/plain", accept: "text/html" },
    status: 415,
    json: { error: "application/json required" },
  },
  {
    name: "missing Accept is 406",
    headers: { "content-type": JSON_TYPE },
    status: 406,
    json: { error: "Accept must include application/json and text/event-stream" },
  },
  {
    name: "wildcard Accept */* is 406",
    headers: { "content-type": JSON_TYPE, accept: "*/*" },
    status: 406,
    json: { error: "Accept must include application/json and text/event-stream" },
  },
  {
    name: "JSON-only Accept is 406",
    headers: { "content-type": JSON_TYPE, accept: "application/json" },
    status: 406,
    json: { error: "Accept must include application/json and text/event-stream" },
  },
  {
    name: "SSE-only Accept is 406",
    headers: { "content-type": JSON_TYPE, accept: "text/event-stream" },
    status: 406,
    json: { error: "Accept must include application/json and text/event-stream" },
  },
  {
    name: "unsupported protocol with valid JSON is 400",
    headers: {
      "content-type": JSON_TYPE,
      accept: VALID_ACCEPT,
      "MCP-Protocol-Version": "2024-11-05",
    },
    status: 400,
    json: { error: "unsupported MCP protocol version" },
  },
  {
    name: "unsupported protocol with invalid JSON is 400",
    headers: {
      "content-type": JSON_TYPE,
      accept: VALID_ACCEPT,
      "MCP-Protocol-Version": "2024-11-05",
    },
    body: "{",
    status: 400,
    json: { error: "unsupported MCP protocol version" },
  },
];

for (const spec of HTTP_PREADMISSION) {
  test(`POST /mcp ${spec.name}`, async () => {
    const db = unusedDb();
    const res = await handleMcpHttp(
      postMcp(spec.body ?? JSONRPC_OPS_STATUS, spec.headers),
      db,
    );
    assert.equal(res.status, spec.status);
    assert.deepEqual(await res.json(), spec.json);
    assert.equal(db.prepareCount, 0);
  });
}

test("POST /mcp ping with valid JSON and Accept is JSON-RPC pong", async () => {
  const db = unusedDb();
  const res = await handleMcpHttp(
    postMcp(JSONRPC_PING, {
      "content-type": JSON_TYPE,
      accept: VALID_ACCEPT,
    }),
    db,
  );
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { jsonrpc: "2.0", id: 1, result: {} });
  assert.equal(db.prepareCount, 0);
});
