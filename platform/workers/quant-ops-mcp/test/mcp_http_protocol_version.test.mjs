import assert from "node:assert/strict";
import test from "node:test";

import { handleMcpHttp, MCP_PROTOCOL_VERSION } from "../src/mcp.js";

assert.equal(MCP_PROTOCOL_VERSION, "2025-06-18");

const UNSUPPORTED_PROTOCOL_VERSION = "2024-11-05";
assert.notEqual(UNSUPPORTED_PROTOCOL_VERSION, MCP_PROTOCOL_VERSION);

const INITIALIZE = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: MCP_PROTOCOL_VERSION,
    capabilities: {},
    clientInfo: { name: "t", version: "0" },
  },
};

/** Protocol-version gate must not touch D1. */
function unusedDb() {
  return {
    prepare() {
      throw new Error("D1 must not be used for MCP-Protocol-Version gate");
    },
  };
}

/**
 * Streamable HTTP POST /mcp. Header-only protocol version; CF-Worker is not
 * auth. Query-string tokens are not a transport.
 * @param {string} body
 */
function postMcp(body) {
  return new Request("https://ops.test/mcp", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "MCP-Protocol-Version": UNSUPPORTED_PROTOCOL_VERSION,
    },
    body,
  });
}

test("POST /mcp unsupported MCP-Protocol-Version is 400 header gate not invalid JSON", async () => {
  const res = await handleMcpHttp(postMcp(JSON.stringify(INITIALIZE)), unusedDb());
  assert.equal(res.status, 400);
  const raw = await res.text();
  const body = JSON.parse(raw);
  assert.deepEqual(body, { error: "unsupported MCP protocol version" });
  assert.equal(body.jsonrpc, undefined);
  assert.notEqual(body.error, "Parse error");
  assert.doesNotMatch(raw, /-32700/);
  assert.doesNotMatch(raw, /\bParse error\b/);
  assert.doesNotMatch(raw, /\bCOMPLETE\b/);
  assert.doesNotMatch(raw, /\bREADY\b/);
});

test("POST /mcp unsupported MCP-Protocol-Version with invalid JSON is still protocol 400", async () => {
  const res = await handleMcpHttp(postMcp("{"), unusedDb());
  assert.equal(res.status, 400);
  const raw = await res.text();
  const body = JSON.parse(raw);
  assert.deepEqual(body, { error: "unsupported MCP protocol version" });
  assert.equal(body.jsonrpc, undefined);
  assert.notEqual(body.error?.code, -32700);
  assert.doesNotMatch(raw, /\bParse error\b/);
  assert.doesNotMatch(raw, /\bCOMPLETE\b/);
  assert.doesNotMatch(raw, /\bREADY\b/);
});
