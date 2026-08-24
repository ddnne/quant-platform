import { describe, expect, it } from "vitest";
import worker, { authorized, type GatewayEnv } from "./index";

const GATEWAY_TOKEN = "gateway-secret";

function dispatchEnv(): { env: GatewayEnv; aiCalls: { count: number } } {
  const aiCalls = { count: 0 };
  const env: GatewayEnv = {
    GATEWAY_TOKEN,
    AI: {
      run: async () => {
        aiCalls.count += 1;
        throw new Error("live Workers AI must not be called");
      },
    } as NonNullable<GatewayEnv["AI"]>,
  };
  return { env, aiCalls };
}

describe("POST /v1/complete ignores query token", () => {
  it("authorized is false for matching ?token= with no X-Gateway-Token", async () => {
    const { env } = dispatchEnv();
    expect(
      await authorized(
        new Request("https://gw.test/v1/complete?token=gateway-secret", {
          method: "POST",
        }),
        env,
      ),
    ).toBe(false);
  });

  it("POST /v1/complete?token=gateway-secret with no header is 401 and does not call AI", async () => {
    const { env, aiCalls } = dispatchEnv();
    const req = new Request("https://gw.test/v1/complete?token=gateway-secret", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{",
    });
    expect(req.headers.get("X-Gateway-Token")).toBeNull();
    const res = await worker.fetch(req, env);
    expect(res.status).toBe(401);
    const raw = await res.text();
    expect(JSON.parse(raw)).toEqual({ error: "unauthorized" });
    expect(raw).not.toContain(GATEWAY_TOKEN);
    expect(raw).not.toContain("COMPLETE");
    expect(raw).not.toContain("READY");
    expect(aiCalls.count).toBe(0);
  });
});
