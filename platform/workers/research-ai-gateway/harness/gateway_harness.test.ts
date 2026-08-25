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

describe("Wrangler test harness", () => {
  it("boots the production module shape and keeps HTTP completion closed", async () => {
    const health = await server.fetch("/health");
    expect(health.status).toBe(200);
    await expect(health.json()).resolves.toMatchObject({
      ok: true,
      service: "quant-platform-research-ai-gateway",
    });

    const denied = await server.fetch("/v1/complete", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(denied.status).toBe(401);
    await expect(denied.json()).resolves.toEqual({ error: "unauthorized" });
  });
});
