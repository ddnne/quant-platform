import { describe, expect, it } from "vitest";
import worker, { type GatewayEnv } from "./index";
import { ALLOWED_MODELS } from "./schema";

const GATEWAY_TOKEN = "gateway-secret";

/** Minimal body that decodeGatewayRequest accepts. budget_id is not occupancy. */
const completeBody = {
  model: ALLOWED_MODELS[2],
  messages: [{ role: "user", content: "hi" }],
  max_tokens: 16,
  budget_id: "gw-budget-1",
  expected_schema: "Insight",
};

function spyAi(): { AI: Ai; calls: unknown[] } {
  const calls: unknown[] = [];
  const AI = {
    run: async (...args: unknown[]) => {
      calls.push(args);
      throw new Error("Workers AI must not be called");
    },
  } as unknown as Ai;
  return { AI, calls };
}

describe("POST /v1/complete CF-Worker is not GATEWAY_TOKEN auth", () => {
  it("CF-Worker research-mass-eval without X-Gateway-Token is 401 and does not call AI", async () => {
    const { AI, calls } = spyAi();
    const env: GatewayEnv = { GATEWAY_TOKEN, AI };
    const req = new Request("https://gw.test/v1/complete", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "CF-Worker": "research-mass-eval",
      },
      body: JSON.stringify(completeBody),
    });
    expect(req.headers.get("X-Gateway-Token")).toBeNull();
    const res = await worker.fetch(req, env);
    expect(res.status).toBe(401);
    const raw = await res.text();
    expect(JSON.parse(raw)).toEqual({ error: "unauthorized" });
    expect(raw).not.toContain("COMPLETE");
    expect(calls).toEqual([]);
  });
});
