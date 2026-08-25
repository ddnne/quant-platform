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
    ],
  });
  await server.listen();
});

afterAll(async () => {
  await server.close();
});

describe("Mass to Gateway typed Service Binding", () => {
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
