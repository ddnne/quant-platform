import { describe, expect, it } from "vitest";
import worker, { type GatewayEnv } from "./index";
import { ALLOWED_MODELS } from "./schema";

const GATEWAY_TOKEN = "gateway-secret";

/** HTTP missing budget_id is decode 400, not occupancy. Live Edge occupancy unproven. */
const completeBodyWithoutBudget = {
  model: ALLOWED_MODELS[2],
  messages: [{ role: "user", content: "hi" }],
  max_tokens: 16,
  expected_schema: "Insight",
};

function completeRequest(): Request {
  return new Request("https://gw.test/v1/complete", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Gateway-Token": GATEWAY_TOKEN,
    },
    body: JSON.stringify(completeBodyWithoutBudget),
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

function throwingLedger(): DurableObjectNamespace {
  return {
    idFromName() {
      throw new Error("BUDGET_LEDGER.idFromName must not run; budget_id is not occupancy");
    },
    get() {
      throw new Error("BUDGET_LEDGER.get must not run; budget_id is not occupancy");
    },
  } as unknown as DurableObjectNamespace;
}

function assertMissingBudgetId400(raw: string): void {
  const payload = JSON.parse(raw) as {
    ok?: boolean;
    error?: string;
    go?: boolean;
    status?: string;
  };
  expect(payload.ok).toBe(false);
  expect(payload.error).toContain("budget_id required");
  expect(payload.go).not.toBe(true);
  expect(payload.status).not.toBe("COMPLETE");
  expect(payload.status).not.toBe("READY");
  expect(raw).not.toContain("COMPLETE");
  expect(raw).not.toMatch(/"go"\s*:\s*true/);
  expect(raw).not.toMatch(/Coverage COMPLETE/);
}

describe("POST /v1/complete missing budget_id", () => {
  it("is 400, does not call AI, and is not occupancy when BUDGET_LEDGER is omitted", async () => {
    const { AI, calls } = spyAi();
    const env: GatewayEnv = { GATEWAY_TOKEN, AI };
    const res = await worker.fetch(completeRequest(), env);
    expect(res.status).toBe(400);
    const raw = await res.text();
    assertMissingBudgetId400(raw);
    expect(calls).toEqual([]);
  });

  it("is 400 and does not run BUDGET_LEDGER.idFromName when the ledger is bound", async () => {
    const { AI, calls } = spyAi();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      AI,
      BUDGET_LEDGER: throwingLedger(),
    };
    const res = await worker.fetch(completeRequest(), env);
    expect(res.status).toBe(400);
    const raw = await res.text();
    assertMissingBudgetId400(raw);
    expect(calls).toEqual([]);
  });
});
