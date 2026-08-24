import assert from "node:assert/strict";
import test from "node:test";

import { handleMcpHttp } from "../src/mcp.js";

const JSONRPC_PING = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" });

/** @param {HeadersInit} headers */
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

test("POST /mcp JSON content-type missing Accept json+sse is 406 not 415", async () => {
  const missingBoth = [
    {},
    { accept: "" },
    { accept: "text/html" },
    { accept: "*/*" },
    { accept: "application/json" },
    { accept: "text/event-stream" },
  ];
  for (const extra of missingBoth) {
    const res = await postMcp({ "content-type": "application/json", ...extra });
    assert.equal(res.status, 406, `accept=${JSON.stringify(extra.accept ?? null)}`);
    assert.notEqual(res.status, 415);
    const body = await res.json();
    assert.equal(
      body.error,
      "Accept must include application/json and text/event-stream",
    );
  }
});

test("POST /mcp without application/json content-type is 415 not 406", async () => {
  const cases = [
    { "content-type": "text/plain", accept: "application/json, text/event-stream" },
    { accept: "application/json, text/event-stream" },
    { "content-type": "text/plain" },
    {},
  ];
  for (const headers of cases) {
    const res = await postMcp(headers);
    assert.equal(res.status, 415, `headers=${JSON.stringify(headers)}`);
    assert.notEqual(res.status, 406);
    const body = await res.json();
    assert.equal(body.error, "application/json required");
  }
});
