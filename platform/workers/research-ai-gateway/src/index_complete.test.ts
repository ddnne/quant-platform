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

function completeRequest(): Request {
  return new Request("https://gw.test/v1/complete", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Gateway-Token": GATEWAY_TOKEN,
    },
    body: JSON.stringify(completeBody),
  });
}

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

describe("POST /v1/complete unbound bindings", () => {
  it("returns 503 budget_ledger_unbound when BUDGET_LEDGER is missing and does not call AI", async () => {
    const { AI, calls } = spyAi();
    const env: GatewayEnv = { GATEWAY_TOKEN, AI };
    const res = await worker.fetch(completeRequest(), env);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ ok: false, error: "budget_ledger_unbound" });
    expect(calls).toEqual([]);
  });

  it("returns 503 ai_binding_unbound when BUDGET_LEDGER is bound and AI is missing", async () => {
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName() {
          throw new Error("budget_id string is not occupancy authority");
        },
        get() {
          throw new Error("budget_id string is not occupancy authority");
        },
      } as unknown as DurableObjectNamespace,
    };
    const res = await worker.fetch(completeRequest(), env);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ ok: false, error: "ai_binding_unbound" });
  });
});