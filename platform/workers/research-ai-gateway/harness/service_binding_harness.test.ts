import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createTestHarness, type TestHarness } from "wrangler";

type GatewayBinding = {
  complete(body: unknown): Promise<{ http_status: number; body: unknown }>;
};

let server: TestHarness;

beforeAll(async () => {
  server = createTestHarness({
    root: process.cwd(),
    workers: [
      { configPath: "./wrangler.test.toml" },
      { configPath: "../research-mass-eval/wrangler.test.toml" },
      {
        config: {
          name: "quant-platform-ingestion-secrets-governed-page-test",
          main: "harness/governed_page_target.ts",
          compatibility_date: "2026-08-01",
          workers_dev: false,
          preview_urls: false,
        },
      },
    ],
  });
  await server.listen();
});

afterAll(async () => {
  await server.close();
});

describe("Gateway HTTP and Mass Service Binding", () => {
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

  it("calls the named RPC entrypoint without a shared bearer token", async () => {
    const mass = server.getWorker<{ AI_GATEWAY: GatewayBinding }>(
      "quant-platform-research-mass-eval-test",
    );
    const massEnv = await mass.getEnv();
    const result = await massEnv.AI_GATEWAY.complete({});
    expect(result.http_status).toBe(400);
    expect(result.body).toMatchObject({
      ok: false,
      error: expect.stringContaining("model"),
    });
  });
});
