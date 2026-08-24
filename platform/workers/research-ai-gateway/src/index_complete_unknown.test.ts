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

describe("POST /v1/complete unknown field", () => {
  it("returns 400 unknown field and does not call AI", async () => {
    const { AI, calls } = spyAi();
    const env: GatewayEnv = { GATEWAY_TOKEN, AI };
    const res = await worker.fetch(
      new Request("https://gw.test/v1/complete", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Gateway-Token": GATEWAY_TOKEN,
        },
        body: JSON.stringify({ ...completeBody, extra: 1 }),
      }),
      env,
    );
    expect(res.status).toBe(400);
    const raw = await res.text();
    const payload = JSON.parse(raw) as {
      ok?: boolean;
      error?: string;
      go?: boolean;
      status?: string;
    };
    expect(payload.ok).toBe(false);
    expect(payload.error).toContain("unknown field");
    expect(calls).toEqual([]);
    expect(payload.go).not.toBe(true);
    expect(payload.status).not.toBe("COMPLETE");
    expect(raw).not.toMatch(/"go"\s*:\s*true/);
    expect(raw).not.toContain("COMPLETE");
    expect(raw).not.toMatch(/Coverage COMPLETE/);
  });
});
