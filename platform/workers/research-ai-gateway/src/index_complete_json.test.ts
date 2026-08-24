import { describe, expect, it } from "vitest";
import worker, { type GatewayEnv } from "./index";

const GATEWAY_TOKEN = "gateway-secret";

/** Worker fetch POST /v1/complete. budget_id string is not occupancy; this test does not prove Edge occupancy. */

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

describe("POST /v1/complete invalid JSON", () => {
  it("POST /v1/complete with invalid JSON is 400 invalid JSON body and does not call AI", async () => {
    const { AI, calls } = spyAi();
    const env: GatewayEnv = { GATEWAY_TOKEN, AI };
    const res = await worker.fetch(
      new Request("https://gw.test/v1/complete", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Gateway-Token": GATEWAY_TOKEN,
        },
        body: "{",
      }),
      env,
    );
    expect(res.status).toBe(400);
    const raw = await res.text();
    expect(JSON.parse(raw)).toEqual({ ok: false, error: "invalid JSON body" });
    expect(raw).not.toContain("COMPLETE");
    expect(raw).not.toMatch(/"go"\s*:\s*true/);
    expect(calls).toEqual([]);
  });
});
