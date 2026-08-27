import { describe, expect, it } from "vitest";
import { authorized } from "./authorized";
import worker, { type GatewayEnv } from "./index";

describe("authorized token separation", () => {
  const env: GatewayEnv = {
    GATEWAY_TOKEN: "gateway-secret",
  };

  it("accepts X-Gateway-Token matching GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": "gateway-secret" },
    });
    expect(await authorized(req, env)).toBe(true);
  });

  it("does not accept X-Mass-Eval-Token as GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Mass-Eval-Token": "gateway-secret" },
    });
    expect(await authorized(req, env)).toBe(false);
  });

  it("denies unbound GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": "gateway-secret" },
    });
    expect(await authorized(req, {})).toBe(false);
  });
});

function dispatchEnv(): { env: GatewayEnv; aiCalls: { count: number } } {
  const aiCalls = { count: 0 };
  const env: GatewayEnv = {
    GATEWAY_TOKEN: "gateway-secret",
    AI: {
      run: async () => {
        aiCalls.count += 1;
        throw new Error("live Workers AI must not be called");
      },
    } as NonNullable<GatewayEnv["AI"]>,
  };
  return { env, aiCalls };
}

describe("fetch dispatcher health method and 404", () => {
  it("GET /health is 200 with service name and is not a GO", async () => {
    const { env, aiCalls } = dispatchEnv();
    const res = await worker.fetch(new Request("https://gw.test/health"), env);
    expect(res.status).toBe(200);
    const raw = await res.text();
    const payload = JSON.parse(raw) as {
      ok?: boolean;
      service?: string;
      go?: boolean;
      status?: string;
    };
    expect(payload.ok).toBe(true);
    expect(payload.service).toBe("quant-platform-research-ai-gateway");
    expect(payload.go).not.toBe(true);
    expect(payload.status).not.toBe("READY");
    expect(payload.status).not.toBe("COMPLETE");
    expect(raw).not.toMatch(/"go"\s*:\s*true/);
    expect(raw).not.toContain("COMPLETE");
    expect(raw).not.toMatch(/Coverage COMPLETE/);
    expect(aiCalls.count).toBe(0);
  });

  it("POST /health is 405 GET required and does not call AI", async () => {
    const { env, aiCalls } = dispatchEnv();
    const res = await worker.fetch(
      new Request("https://gw.test/health", { method: "POST" }),
      env,
    );
    expect(res.status).toBe(405);
    const raw = await res.text();
    expect(JSON.parse(raw)).toEqual({ error: "GET required" });
    expect(raw).not.toContain("COMPLETE");
    expect(aiCalls.count).toBe(0);
  });

  it("GET /v1/complete is 405 POST required and does not call AI", async () => {
    const { env, aiCalls } = dispatchEnv();
    const res = await worker.fetch(
      new Request("https://gw.test/v1/complete", {
        method: "GET",
        headers: {
          "X-Gateway-Token": "gateway-secret",
          "CF-Worker": "research-mass-eval",
        },
      }),
      env,
    );
    expect(res.status).toBe(405);
    const raw = await res.text();
    expect(JSON.parse(raw)).toEqual({ error: "POST required" });
    expect(raw).not.toContain("COMPLETE");
    expect(aiCalls.count).toBe(0);
  });

  it("GET /nope is 404 not found", async () => {
    const { env, aiCalls } = dispatchEnv();
    const res = await worker.fetch(new Request("https://gw.test/nope"), env);
    expect(res.status).toBe(404);
    const raw = await res.text();
    expect(JSON.parse(raw)).toEqual({ error: "not found" });
    expect(raw).not.toContain("COMPLETE");
    expect(aiCalls.count).toBe(0);
  });
});
