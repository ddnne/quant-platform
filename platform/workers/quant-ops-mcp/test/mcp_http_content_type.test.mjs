import assert from "node:assert/strict";
import test from "node:test";

import { handleMcpHttp } from "../src/mcp.js";

const JSONRPC_PING = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" });

/** @param {HeadersInit} [headers] */
function postMcp(headers) {
  return handleMcpHttp(
    new Request("https://ops.test/mcp", {
      method: "POST",
      headers,
      body: JSONRPC_PING,
    }),
    {},
  );
}

function assertHttp415NotJsonRpc(body) {
  assert.equal(body.error, "application/json required");
  assert.equal(body.jsonrpc, undefined);
  assert.equal(body.id, undefined);
  assert.equal(body.result, undefined);
  assert.equal(typeof body.error, "string");
}

test("POST /mcp missing Content-Type is 415 not JSON-RPC", async () => {
  const res = await postMcp();
  assert.equal(res.status, 415);
  assertHttp415NotJsonRpc(await res.json());
});

test("POST /mcp without application/json Content-Type is 415 not JSON-RPC", async () => {
  const cases = [
    {},
    { "content-type": "text/plain" },
    { accept: "application/json, text/event-stream" },
    {
      "content-type": "text/plain",
      accept: "application/json, text/event-stream",
    },
  ];
  for (const headers of cases) {
    const res = await postMcp(headers);
    assert.equal(res.status, 415, `headers=${JSON.stringify(headers)}`);
    assertHttp415NotJsonRpc(await res.json());
  }
});
