import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createTestHarness, type TestHarness } from "wrangler";

let server: TestHarness;

beforeAll(async () => {
  server = createTestHarness({
    root: process.cwd(),
    workers: [{ configPath: "./wrangler.test.toml" }],
  });
  await server.listen();
});

afterAll(async () => {
  await server.close();
});

describe("Ops MCP production module boundary", () => {
  it("keeps MCP unavailable without an OAuth bearer while metadata stays public", async () => {
    const metadata = await server.fetch(
      "/.well-known/oauth-protected-resource/mcp",
    );
    expect(metadata.status).toBe(200);
    await expect(metadata.json()).resolves.toMatchObject({
      scopes_supported: ["quant.read.ops"],
      bearer_methods_supported: ["header"],
    });

    const denied = await server.fetch("/mcp", {
      method: "POST",
      headers: {
        accept: "application/json, text/event-stream",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "tools/list",
      }),
    });
    expect(denied.status).toBe(401);
    expect(denied.headers.get("www-authenticate")).toContain("Bearer");
  });
});
