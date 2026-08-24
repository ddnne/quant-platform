import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// OAuthProvider / agents/mcp import cloudflare:workers; stub them so node --test
// can load the Worker fetch handler without a CF runtime.
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@cloudflare/workers-oauth-provider") {
      return {
        shortCircuit: true,
        url:
          "data:text/javascript," +
          encodeURIComponent(`
            export default class OAuthProvider {
              constructor() {}
              fetch() { return new Response("oauth-stub", { status: 404 }); }
            }
          `),
      };
    }
    if (specifier === "agents/mcp") {
      return {
        shortCircuit: true,
        url:
          "data:text/javascript," +
          encodeURIComponent(`
            export class McpAgent {
              static serve() { return {}; }
              static serveSSE() { return {}; }
            }
          `),
      };
    }
    return nextResolve(specifier, context);
  },
});

const worker = (await import("../src/index.js")).default;

const WELL_KNOWN_PATHS = [
  "/.well-known/oauth-protected-resource",
  "/.well-known/oauth-protected-resource/mcp",
];

function dummyEnv() {
  return {};
}

function dummyCtx() {
  return {
    waitUntil() {},
    passThroughOnException() {},
  };
}

test("oauth protected-resource metadata advertises header-only bearer", async () => {
  for (const path of WELL_KNOWN_PATHS) {
    const res = await worker.fetch(
      new Request(`https://ops-mcp.test${path}`),
      dummyEnv(),
      dummyCtx(),
    );
    assert.equal(res.status, 200);
    const contentType = res.headers.get("content-type") || "";
    assert.ok(contentType.includes("application/json"));
    const raw = await res.text();
    const body = JSON.parse(raw);
    assert.deepEqual(body.bearer_methods_supported, ["header"]);
    assert.ok(!body.bearer_methods_supported.includes("query"));
    assert.ok(body.scopes_supported.includes("quant.read.ops"));
    assert.ok(body.resource.endsWith("/mcp"));
    assert.doesNotMatch(raw, /\bCOMPLETE\b/);
    assert.doesNotMatch(raw, /\bREADY\b/);
    assert.doesNotMatch(raw, /\bquery\b/i);
  }
});

test("src pin: bearer_methods_supported is header, not query", () => {
  const src = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../src/index.js"),
    "utf8",
  );
  assert.match(src, /bearer_methods_supported:\s*\[\s*"header"\s*\]/);
  assert.doesNotMatch(src, /bearer_methods_supported:\s*"query"/);
  assert.doesNotMatch(src, /bearer_methods_supported:[^\n]*query/);
});
