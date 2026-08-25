import { describe, expect, it } from "vitest";
import { CONTROL_PLANE_LEDGER_NAME, MemoryBudgetStorage, snapshotBudget } from "./budget_do";
import { handleBudgetRequest } from "./budget_http";
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

const insightBody = {
  model: ALLOWED_MODELS[2],
  messages: [{ role: "user", content: "hi" }],
  max_tokens: 16,
  budget_id: "gw-budget-1",
  expected_schema: "Insight",
};

const insightArtifact = {
  role: "quant",
  task: "t",
  summary: "x",
  schema_version: "insight/v1",
};

function completeWithBudget(init: { headers?: Record<string, string>; body?: unknown } = {}): Request {
  return new Request("https://gw.test/v1/complete", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Gateway-Token": GATEWAY_TOKEN,
      ...(init.headers || {}),
    },
    body: JSON.stringify(init.body ?? insightBody),
  });
}

function memoryLedger(): {
  BUDGET_LEDGER: DurableObjectNamespace;
  storage: MemoryBudgetStorage;
  names: string[];
} {
  const storage = new MemoryBudgetStorage();
  const names: string[] = [];
  const BUDGET_LEDGER = {
    idFromName(name: string) {
      names.push(name);
      if (name === "gw-budget-1") {
        throw new Error("caller budget_id is not occupancy");
      }
      return { toString: () => name } as DurableObjectId;
    },
    get() {
      return {
        fetch(request: Request) {
          return handleBudgetRequest(storage, request);
        },
      };
    },
  } as unknown as DurableObjectNamespace;
  return { BUDGET_LEDGER, storage, names };
}

describe("POST /v1/complete control-plane occupancy", () => {
  it("reserves the control-plane ledger, not caller budget_id", async () => {
    const { BUDGET_LEDGER, names } = memoryLedger();
    const calls: unknown[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async (...args: unknown[]) => {
          calls.push(args);
          return { response: JSON.stringify(insightArtifact), usage: { prompt_tokens: 4, completion_tokens: 3 } };
        },
      } as unknown as Ai,
    };
    const res = await worker.fetch(completeWithBudget(), env);
    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      ok?: boolean;
      budget_id?: string;
      budget_run_id?: string;
    };
    expect(payload.ok).toBe(true);
    expect(payload.budget_id).toBe("gw-budget-1");
    expect(payload.budget_run_id).toBeTruthy();
    expect(payload.budget_run_id).not.toBe("gw-budget-1");
    expect(names.length).toBeGreaterThan(0);
    expect(names.every((n) => n === CONTROL_PLANE_LEDGER_NAME)).toBe(true);
    expect(names).not.toContain("gw-budget-1");
    expect(calls).toHaveLength(1);
  });

  it("duplicate digest returns cached success and does not re-call AI", async () => {
    const { BUDGET_LEDGER } = memoryLedger();
    const calls: unknown[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async (...args: unknown[]) => {
          calls.push(args);
          return { response: JSON.stringify(insightArtifact), usage: { prompt_tokens: 4, completion_tokens: 3 } };
        },
      } as unknown as Ai,
    };
    const first = await worker.fetch(completeWithBudget(), env);
    const second = await worker.fetch(completeWithBudget(), env);
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    const a = (await first.json()) as { budget_run_id?: string; output_digest?: string };
    const b = (await second.json()) as { budget_run_id?: string; output_digest?: string };
    expect(b.budget_run_id).toBe(a.budget_run_id);
    expect(b.output_digest).toBe(a.output_digest);
    expect(calls).toHaveLength(1);
  });

  it("schema reject charges actual and does not return a success artifact", async () => {
    const { BUDGET_LEDGER, storage } = memoryLedger();
    const calls: unknown[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async (...args: unknown[]) => {
          calls.push(args);
          return {
            response: JSON.stringify({ ...insightArtifact, smuggled: true }),
            usage: { prompt_tokens: 8, completion_tokens: 2 },
          };
        },
      } as unknown as Ai,
    };
    const res = await worker.fetch(completeWithBudget(), env);
    expect(res.status).toBe(400);
    const payload = (await res.json()) as {
      ok?: boolean;
      error?: string;
      artifact?: unknown;
      schema?: string;
    };
    expect(payload.ok).toBe(false);
    expect(payload.error).toContain("unknown field");
    expect(payload.artifact).toBeUndefined();
    expect(payload.schema).toBeUndefined();
    expect(calls).toHaveLength(1);
    const snap = await snapshotBudget(storage);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.used.model_calls).toBe(1);
      expect(snap.used.input_tokens).toBe(8);
      expect(snap.used.output_tokens).toBe(2);
      expect(snap.reserved.model_calls).toBe(0);
      expect(snap.active_leases).toBe(0);
      expect(snap.auto_promotion).toBe(false);
    }
    const state = await storage.get<{
      reservations: Record<
        string,
        {
          settlement: {
            outcome: string;
            usage_source: string;
            actual_input_tokens: number;
            actual_output_tokens: number;
            actual_cached_tokens: number;
            estimated_cost_usd: number;
            actual_cost_usd: number;
          };
        }
      >;
    }>("ledger");
    const reservations = state?.reservations ?? {};
    const receipt = reservations[Object.keys(reservations)[0]];
    expect(receipt?.settlement).toMatchObject({
      outcome: "schema_reject",
      usage_source: "provider",
      actual_input_tokens: 8,
      actual_output_tokens: 2,
      actual_cached_tokens: 0,
    });
    expect(receipt?.settlement.estimated_cost_usd).toBeGreaterThanOrEqual(
      receipt?.settlement.actual_cost_usd ?? 0,
    );
  });

  it("provider failure settles the reservation and records estimated usage", async () => {
    const { BUDGET_LEDGER, storage } = memoryLedger();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async () => {
          throw new Error("provider unavailable");
        },
      } as unknown as Ai,
    };
    const res = await worker.fetch(completeWithBudget(), env);
    expect(res.status).toBe(502);
    const payload = (await res.json()) as { error?: string; budget_run_id?: string };
    expect(payload.error).toBe("ai_run_failed");
    expect(payload.budget_run_id).toBeTruthy();
    const snap = await snapshotBudget(storage);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved.model_calls).toBe(0);
      expect(snap.active_leases).toBe(0);
      expect(snap.used.model_calls).toBe(1);
      expect(snap.used.input_tokens).toBeGreaterThan(0);
      expect(snap.used.output_tokens).toBe(0);
    }
    const state = await storage.get<{
      reservations: Record<
        string,
        { settlement: { outcome: string; usage_source: string; actual_cost_usd: null } }
      >;
    }>("ledger");
    const reservations = state?.reservations ?? {};
    const receipt = reservations[Object.keys(reservations)[0]];
    expect(receipt?.settlement).toMatchObject({
      outcome: "provider_error",
      usage_source: "estimated_no_provider_usage",
      actual_cost_usd: null,
    });
  });

  it("finalize failure after provider does not return the success artifact", async () => {
    const names: string[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          names.push(name);
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          return {
            fetch: async (request: Request) => {
              const url = new URL(request.url);
              if (url.pathname === "/reserve") {
                return new Response(
                  JSON.stringify({
                    ok: true,
                    existing: false,
                    budget_run_id: "run-1",
                    reservation: { reservation_id: "run-1", status: "reserved", cached_result: null },
                    lease: { lease_id: "lease-1" },
                  }),
                  { headers: { "content-type": "application/json" } },
                );
              }
              return new Response(
                JSON.stringify({ ok: false, error: "budget_frozen" }),
                { status: 409, headers: { "content-type": "application/json" } },
              );
            },
          };
        },
      } as unknown as DurableObjectNamespace,
      AI: {
        run: async () => ({
          response: JSON.stringify(insightArtifact),
          usage: { prompt_tokens: 4, completion_tokens: 3 },
        }),
      } as unknown as Ai,
    };
    const res = await worker.fetch(completeWithBudget(), env);
    expect(names).toEqual([CONTROL_PLANE_LEDGER_NAME, CONTROL_PLANE_LEDGER_NAME]);
    expect(res.status).toBe(409);
    const payload = (await res.json()) as { ok?: boolean; error?: string; artifact?: unknown };
    expect(payload.ok).toBe(false);
    expect(payload.error).toBe("budget_frozen");
    expect(payload.artifact).toBeUndefined();
  });
});
