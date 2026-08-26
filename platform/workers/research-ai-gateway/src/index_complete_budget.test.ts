import { describe, expect, it, vi } from "vitest";
import {
  CONTROL_PLANE_LEDGER_NAME,
  createBudgetCoordinator,
  MemoryBudgetStorage,
  PILOT_BUDGET_CAPS,
  recoverExpiredLeases,
  snapshotBudget,
} from "./budget_do";
import { handleBudgetRequest } from "./budget_http";
import worker, { type GatewayEnv } from "./index";
import { AI_CALL_TIMEOUT_MS } from "./runtime_policy";
import { ALLOWED_MODELS, providerInputBounds } from "./schema";
import {
  AI_GATEWAY_PRICING_POLICY_DIGEST,
  AI_GATEWAY_PRICING_POLICY_ID,
} from "./pricing_policy";
import { sha256Hex } from "./sha256";

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
        ...createBudgetCoordinator(storage),
        fetch(request: Request) {
          return handleBudgetRequest(storage, request);
        },
      };
    },
  } as unknown as DurableObjectNamespace;
  return { BUDGET_LEDGER, storage, names };
}

describe("POST /v1/complete control-plane occupancy", () => {
  it("rejects a caller-forged prompt digest before ledger or provider access", async () => {
    const calls: unknown[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: throwingLedger(),
      AI: {
        run: async (...args: unknown[]) => {
          calls.push(args);
          throw new Error("provider must not run");
        },
      } as unknown as Ai,
    };
    const res = await worker.fetch(
      completeWithBudget({
        body: {
          ...insightBody,
          prompt_digest: `sha256:${"0".repeat(64)}`,
        },
      }),
      env,
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({
      ok: false,
      error: "prompt_digest mismatch",
    });
    expect(calls).toEqual([]);
  });

  it("canonicalizes an omitted or matching prompt digest to one idempotent call", async () => {
    const { BUDGET_LEDGER } = memoryLedger();
    const calls: unknown[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async (...args: unknown[]) => {
          calls.push(args);
          return {
            response: JSON.stringify(insightArtifact),
            usage: { prompt_tokens: 4, completion_tokens: 3 },
          };
        },
      } as unknown as Ai,
    };
    const measured = `sha256:${await sha256Hex(
      JSON.stringify(insightBody.messages),
    )}`;
    const first = await worker.fetch(completeWithBudget(), env);
    const second = await worker.fetch(
      completeWithBudget({
        body: { ...insightBody, prompt_digest: measured },
      }),
      env,
    );
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    const firstBody = (await first.json()) as {
      prompt_digest?: string;
      budget_run_id?: string;
    };
    const secondBody = (await second.json()) as {
      prompt_digest?: string;
      budget_run_id?: string;
    };
    expect(firstBody.prompt_digest).toBe(measured);
    expect(secondBody.prompt_digest).toBe(measured);
    expect(secondBody.budget_run_id).toBe(firstBody.budget_run_id);
    expect(calls).toHaveLength(1);
  });

  it("rejects hard request bounds before touching the ledger or provider", async () => {
    const calls: unknown[] = [];
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: throwingLedger(),
      AI: {
        run: async (...args: unknown[]) => {
          calls.push(args);
          throw new Error("provider must not run");
        },
      } as unknown as Ai,
    };
    const res = await worker.fetch(
      completeWithBudget({
        body: {
          ...insightBody,
          messages: Array.from({ length: 17 }, () => ({ role: "user", content: "x" })),
        },
      }),
      env,
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toMatchObject({
      ok: false,
      error: expect.stringContaining("messages[] exceeds hard limit"),
    });
    expect(calls).toEqual([]);
  });

  it("reserves the control-plane ledger, not caller budget_id", async () => {
    const { BUDGET_LEDGER, names, storage } = memoryLedger();
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
      monetary_cost_source?: string;
      pricing_policy_id?: string | null;
      pricing_policy_digest?: string | null;
    };
    expect(payload.ok).toBe(true);
    expect(payload.budget_id).toBe("gw-budget-1");
    expect(payload.budget_run_id).toBeTruthy();
    expect(payload.budget_run_id).not.toBe("gw-budget-1");
    expect(payload.monetary_cost_source).toBe("pricing_policy_estimate");
    expect(payload.pricing_policy_id).toBe(AI_GATEWAY_PRICING_POLICY_ID);
    expect(payload.pricing_policy_digest).toBe(AI_GATEWAY_PRICING_POLICY_DIGEST);
    expect(names.length).toBeGreaterThan(0);
    expect(names.every((n) => n === CONTROL_PLANE_LEDGER_NAME)).toBe(true);
    expect(names).not.toContain("gw-budget-1");
    expect(calls).toHaveLength(1);
    const state = await storage.get<{
      reservations: Record<string, {
        amounts: { input_tokens: number; cached_tokens: number };
        settlement: {
          usage_source: string;
          actual_cost_usd: number | null;
          billed_cost_usd: number;
          pricing_policy_id: string | null;
          pricing_policy_digest: string | null;
        };
      }>;
    }>("ledger");
    const reservation = Object.values(state?.reservations ?? {})[0];
    const inputUpperBound = providerInputBounds(insightBody.messages).token_upper_bound;
    expect(reservation?.amounts.input_tokens).toBe(inputUpperBound);
    expect(reservation?.amounts.cached_tokens).toBe(inputUpperBound);
    expect(reservation?.settlement).toMatchObject({
      usage_source: "provider_tokens_estimated_cost",
      actual_cost_usd: null,
      pricing_policy_id: AI_GATEWAY_PRICING_POLICY_ID,
      pricing_policy_digest: AI_GATEWAY_PRICING_POLICY_DIGEST,
    });
    expect(reservation?.settlement.billed_cost_usd).toBeGreaterThanOrEqual(0);
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
            usage: { prompt_tokens: 8, completion_tokens: 2, cost_usd: 0.00000104 },
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
            billed_cost_usd: number;
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
      actual_cost_usd: 0.00000104,
      billed_cost_usd: 0.000001,
    });
    expect(receipt?.settlement.estimated_cost_usd).toBeGreaterThanOrEqual(
      receipt?.settlement.actual_cost_usd ?? 0,
    );
  });

  it("provider failure charges the reserved maximum, freezes, and leaves no phantom reserve", async () => {
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
      expect(snap.used.output_tokens).toBe(insightBody.max_tokens);
      expect(snap.used.cached_tokens).toBe(snap.used.input_tokens);
      expect(snap.frozen).toBe(true);
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
      usage_source: "reserved_max_uncertain",
      actual_cost_usd: null,
    });
  });

  it("missing provider usage is conservatively settled instead of using text heuristics", async () => {
    const { BUDGET_LEDGER, storage } = memoryLedger();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async () => ({ response: JSON.stringify(insightArtifact) }),
      } as unknown as Ai,
    };
    const res = await worker.fetch(completeWithBudget(), env);
    expect(res.status).toBe(500);
    expect(await res.json()).toMatchObject({
      ok: false,
      error: "budget_settlement_uncertain",
    });
    const snap = await snapshotBudget(storage);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.frozen).toBe(true);
    expect(snap.reserved).toEqual(expect.objectContaining({
      model_calls: 0,
      input_tokens: 0,
      output_tokens: 0,
      cached_tokens: 0,
    }));
    expect(snap.used.output_tokens).toBe(insightBody.max_tokens);
    expect(snap.used.cached_tokens).toBe(snap.used.input_tokens);
  });

  it("treats explicitly malformed provider token and cost fields as uncertain", async () => {
    for (const usage of [
      { prompt_tokens: false, completion_tokens: 3, cost_usd: 0.01 },
      { prompt_tokens: 4, completion_tokens: null, cost_usd: 0.01 },
      { prompt_tokens: "4", completion_tokens: 3, cost_usd: 0.01 },
      { prompt_tokens: 4, completion_tokens: 3, cost_usd: false },
      { prompt_tokens: 4, completion_tokens: 3, cost_usd: Number.NaN },
      {
        prompt_tokens: 0,
        input_tokens: false,
        completion_tokens: 0,
        output_tokens: false,
        cost_usd: 0,
        monetary_cost_usd: false,
      },
      { prompt_tokens: 4, completion_tokens: 3, total_tokens: 99 },
      { prompt_tokens: 4, completion_tokens: 3, unexpected: 1 },
      { prompt_tokens: 4, cost_usd: 0.01 },
      {
        prompt_tokens: 4,
        completion_tokens: 3,
        cached_tokens: 1,
        prompt_tokens_details: { cached_tokens: 1 },
      },
      { prompt_tokens: 4, completion_tokens: 3, cached_tokens: 5 },
      {
        prompt_tokens: 4,
        completion_tokens: 3,
        prompt_tokens_details: { cached_tokens: 5 },
      },
    ]) {
      const { BUDGET_LEDGER, storage } = memoryLedger();
      const env: GatewayEnv = {
        GATEWAY_TOKEN,
        BUDGET_LEDGER,
        AI: {
          run: async () => ({ response: JSON.stringify(insightArtifact), usage }),
        } as unknown as Ai,
      };
      const res = await worker.fetch(completeWithBudget(), env);
      expect(res.status).toBe(500);
      expect(await res.json()).toMatchObject({
        ok: false,
        error: "budget_settlement_uncertain",
      });
      const snap = await snapshotBudget(storage);
      if (!snap.ok) throw new Error("snapshot");
      expect(snap).toMatchObject({
        frozen: true,
        used: { model_calls: 1 },
        reserved: { model_calls: 0 },
        active_leases: 0,
      });
    }
  });

  it("accepts one complete provider alias set and validates total/cached details", async () => {
    const { BUDGET_LEDGER, storage } = memoryLedger();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER,
      AI: {
        run: async () => ({
          response: JSON.stringify(insightArtifact),
          usage: {
            prompt_tokens: 4,
            completion_tokens: 3,
            total_tokens: 7,
            prompt_tokens_details: { cached_tokens: 2 },
          },
        }),
      } as unknown as Ai,
    };
    const res = await worker.fetch(completeWithBudget(), env);
    expect(res.status).toBe(200);
    const snap = await snapshotBudget(storage);
    expect(snap).toMatchObject({
      ok: true,
      frozen: false,
      used: {
        model_calls: 1,
        input_tokens: 4,
        output_tokens: 3,
        cached_tokens: 2,
      },
      reserved: { model_calls: 0 },
      active_leases: 0,
    });
  });

  it("charges the maximum on timeout and ignores a late provider completion", async () => {
    vi.useFakeTimers();
    try {
      const { BUDGET_LEDGER, storage } = memoryLedger();
      let providerCalls = 0;
      let providerStarted!: () => void;
      const started = new Promise<void>((resolve) => {
        providerStarted = resolve;
      });
      let resolveProvider!: (value: unknown) => void;
      const lateProvider = new Promise<unknown>((resolve) => {
        resolveProvider = resolve;
      });
      const env: GatewayEnv = {
        GATEWAY_TOKEN,
        BUDGET_LEDGER,
        AI: {
          run: async () => {
            providerCalls += 1;
            providerStarted();
            return lateProvider;
          },
        } as unknown as Ai,
      };
      const pending = worker.fetch(completeWithBudget(), env);
      await started;
      await vi.advanceTimersByTimeAsync(AI_CALL_TIMEOUT_MS);
      const timedOut = await pending;
      expect(timedOut.status).toBe(504);
      expect(await timedOut.json()).toMatchObject({ ok: false, error: "ai_run_timeout" });

      resolveProvider({
        response: JSON.stringify(insightArtifact),
        usage: { prompt_tokens: 4, completion_tokens: 3 },
      });
      await Promise.resolve();
      const snap = await snapshotBudget(storage);
      if (!snap.ok) throw new Error("snapshot");
      expect(snap.frozen).toBe(true);
      expect(snap.reserved.model_calls).toBe(0);
      expect(snap.used.output_tokens).toBe(insightBody.max_tokens);

      const retry = await worker.fetch(completeWithBudget(), env);
      expect(retry.status).toBe(504);
      expect(providerCalls).toBe(1);
      const afterRetry = await snapshotBudget(storage);
      if (!afterRetry.ok) throw new Error("snapshot");
      expect(afterRetry.used).toEqual(snap.used);
    } finally {
      vi.useRealTimers();
    }
  });

  it("finalize RPC throw after provider charges maximum and returns a safe 500", async () => {
    const names: string[] = [];
    const storage = new MemoryBudgetStorage();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          names.push(name);
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          const coordinator = createBudgetCoordinator(storage);
          return {
            ...coordinator,
            fetch: (request: Request) => handleBudgetRequest(storage, request),
            finalizeExact: async () => {
              throw new Error("RPC transport interrupted after provider side effect");
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
    expect(names).toEqual(Array(4).fill(CONTROL_PLANE_LEDGER_NAME));
    expect(res.status).toBe(500);
    const payload = (await res.json()) as { ok?: boolean; error?: string; artifact?: unknown };
    expect(payload.ok).toBe(false);
    expect(payload.error).toBe("budget_finalize_failed");
    expect(payload.artifact).toBeUndefined();
    const snap = await snapshotBudget(storage);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.reserved).toMatchObject({ model_calls: 0, input_tokens: 0, output_tokens: 0 });
    expect(snap.used.model_calls).toBe(1);
    expect(snap.used.output_tokens).toBe(insightBody.max_tokens);
    expect(snap.frozen).toBe(true);
  });

  it("alarm recovery remains durable when finalize and immediate recovery RPCs both fail", async () => {
    const storage = new MemoryBudgetStorage();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          const coordinator = createBudgetCoordinator(storage);
          return {
            ...coordinator,
            fetch: (request: Request) => handleBudgetRequest(storage, request),
            finalizeExact: async () => {
              throw new Error("ledger transport unavailable");
            },
            settleUncertain: async () => {
              throw new Error("ledger transport unavailable");
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
    expect(res.status).toBe(500);
    expect(await res.json()).toMatchObject({ ok: false, error: "budget_finalize_failed" });
    const pending = await snapshotBudget(storage);
    if (!pending.ok) throw new Error("snapshot");
    expect(pending.reserved.model_calls).toBe(1);
    expect(pending.used.model_calls).toBe(0);
    expect(pending.active_leases).toBe(1);

    const recovered = await recoverExpiredLeases(
      storage,
      Date.now() + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 1,
    );
    expect(recovered).toMatchObject({ ok: true, recovered: 1 });
    const after = await snapshotBudget(
      storage,
      Date.now() + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 2,
    );
    if (!after.ok) throw new Error("snapshot");
    expect(after.reserved.model_calls).toBe(0);
    expect(after.used.model_calls).toBe(1);
    expect(after.used.output_tokens).toBe(insightBody.max_tokens);
    expect(after.frozen).toBe(true);
  });

  it("invalid finalize response cannot leak success or double-charge a committed settlement", async () => {
    const storage = new MemoryBudgetStorage();
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          const coordinator = createBudgetCoordinator(storage);
          return {
            ...coordinator,
            fetch: (request: Request) => handleBudgetRequest(storage, request),
            finalizeExact: async (input: Parameters<typeof coordinator.finalizeExact>[0]) => {
              await coordinator.finalizeExact(input);
              return "not-json";
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
    expect(res.status).toBe(500);
    const payload = (await res.json()) as { ok?: boolean; error?: string; artifact?: unknown };
    expect(payload).toMatchObject({ ok: false, error: "budget_finalize_failed" });
    expect(payload.artifact).toBeUndefined();
    const snap = await snapshotBudget(storage);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.reserved.model_calls).toBe(0);
    expect(snap.used).toMatchObject({ model_calls: 1, input_tokens: 4, output_tokens: 3 });
    expect(snap.frozen).toBe(false);
  });

  it("recovers an owner-bound reserve when commit succeeds but the first RPC response is lost", async () => {
    const storage = new MemoryBudgetStorage();
    let reserveCalls = 0;
    let providerCalls = 0;
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          const coordinator = createBudgetCoordinator(storage);
          return {
            ...coordinator,
            reserveOwned: async (input: Parameters<typeof coordinator.reserveOwned>[0]) => {
              reserveCalls += 1;
              const committed = await coordinator.reserveOwned(input);
              if (reserveCalls === 1) {
                throw new Error("reserve response lost after commit");
              }
              return committed;
            },
          };
        },
      } as unknown as DurableObjectNamespace,
      AI: {
        run: async () => {
          providerCalls += 1;
          return {
            response: JSON.stringify(insightArtifact),
            usage: { prompt_tokens: 4, completion_tokens: 3 },
          };
        },
      } as unknown as Ai,
    };

    const res = await worker.fetch(completeWithBudget(), env);
    expect(res.status).toBe(200);
    expect(reserveCalls).toBe(2);
    expect(providerCalls).toBe(1);
    const snap = await snapshotBudget(storage);
    expect(snap).toMatchObject({
      ok: true,
      used: { model_calls: 1, input_tokens: 4, output_tokens: 3 },
      reserved: { model_calls: 0, input_tokens: 0, output_tokens: 0 },
      active_leases: 0,
    });
  });

  it("allows only one Gateway invocation to own an in-flight idempotency key", async () => {
    const storage = new MemoryBudgetStorage();
    let providerCalls = 0;
    let providerEntered!: () => void;
    let unblockProvider!: () => void;
    const entered = new Promise<void>((resolve) => {
      providerEntered = resolve;
    });
    const blocked = new Promise<void>((resolve) => {
      unblockProvider = resolve;
    });
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          return createBudgetCoordinator(storage);
        },
      } as unknown as DurableObjectNamespace,
      AI: {
        run: async () => {
          providerCalls += 1;
          providerEntered();
          await blocked;
          return {
            response: JSON.stringify(insightArtifact),
            usage: { prompt_tokens: 4, completion_tokens: 3 },
          };
        },
      } as unknown as Ai,
    };

    const firstPending = worker.fetch(
      completeWithBudget({ headers: { "Idempotency-Key": "same-client-key" } }),
      env,
    );
    await entered;
    const second = await worker.fetch(
      completeWithBudget({ headers: { "Idempotency-Key": "same-client-key" } }),
      env,
    );
    expect(second.status).toBe(409);
    expect(await second.json()).toEqual({
      ok: false,
      error: "reservation_owned_by_other_invocation",
    });
    expect(providerCalls).toBe(1);

    unblockProvider();
    const first = await firstPending;
    expect(first.status).toBe(200);
    expect(providerCalls).toBe(1);
    expect(await snapshotBudget(storage)).toMatchObject({
      ok: true,
      used: { model_calls: 1 },
      reserved: { model_calls: 0 },
      active_leases: 0,
    });
  });

  it("tombstones cancellation when reserve RPC delivery is reordered after cancel", async () => {
    const storage = new MemoryBudgetStorage();
    const coordinator = createBudgetCoordinator(storage);
    const delayedReserveInputs: Array<
      Parameters<typeof coordinator.reserveOwned>[0]
    > = [];
    let providerCalls = 0;
    const env: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          return {
            ...coordinator,
            reserveOwned: async (
              input: Parameters<typeof coordinator.reserveOwned>[0],
            ) => {
              delayedReserveInputs.push(structuredClone(input));
              throw new Error("reserve request delivery delayed beyond response");
            },
          };
        },
      } as unknown as DurableObjectNamespace,
      AI: {
        run: async () => {
          providerCalls += 1;
          throw new Error("provider must not run");
        },
      } as unknown as Ai,
    };

    const response = await worker.fetch(
      completeWithBudget({ headers: { "Idempotency-Key": "reordered-reserve" } }),
      env,
    );
    expect(response.status).toBe(500);
    expect(providerCalls).toBe(0);
    expect(delayedReserveInputs).toHaveLength(2);

    for (const delayedInput of delayedReserveInputs) {
      await expect(coordinator.reserveOwned(delayedInput)).resolves.toEqual({
        ok: false,
        error: "reservation_released",
      });
    }
    expect(await snapshotBudget(storage)).toMatchObject({
      ok: true,
      used: { model_calls: 0 },
      reserved: { model_calls: 0 },
      active_leases: 0,
    });
  });

  it("atomically cancels two ambiguous pre-provider reserves without consuming parallel slots", async () => {
    const storage = new MemoryBudgetStorage();
    let providerCalls = 0;
    let cancelCalls = 0;
    const failingNamespace = {
      idFromName(name: string) {
        return { toString: () => name } as DurableObjectId;
      },
      get() {
        const coordinator = createBudgetCoordinator(storage);
        return {
          ...coordinator,
          reserveOwned: async (input: Parameters<typeof coordinator.reserveOwned>[0]) => {
            await coordinator.reserveOwned(input);
            throw new Error("reserve response always lost after commit");
          },
          cancelPreProvider: async (
            input: Parameters<typeof coordinator.cancelPreProvider>[0],
          ) => {
            cancelCalls += 1;
            const committed = await coordinator.cancelPreProvider(input);
            if (cancelCalls === 1) {
              throw new Error("cancel response lost after commit");
            }
            return committed;
          },
        };
      },
    } as unknown as DurableObjectNamespace;
    const failingEnv: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: failingNamespace,
      AI: {
        run: async () => {
          providerCalls += 1;
          throw new Error("provider must not run");
        },
      } as unknown as Ai,
    };
    const secondBody = {
      ...insightBody,
      messages: [{ role: "user", content: "different ambiguous reserve" }],
    };

    const responses = await Promise.all([
      worker.fetch(completeWithBudget(), failingEnv),
      worker.fetch(completeWithBudget({ body: secondBody }), failingEnv),
    ]);
    expect(responses.map((response) => response.status)).toEqual([500, 500]);
    expect(providerCalls).toBe(0);
    const afterFailures = await snapshotBudget(storage);
    expect(afterFailures).toMatchObject({
      ok: true,
      used: { model_calls: 0 },
      reserved: { model_calls: 0 },
      active_leases: 0,
    });

    const healthyEnv: GatewayEnv = {
      GATEWAY_TOKEN,
      BUDGET_LEDGER: {
        idFromName(name: string) {
          return { toString: () => name } as DurableObjectId;
        },
        get() {
          return createBudgetCoordinator(storage);
        },
      } as unknown as DurableObjectNamespace,
      AI: {
        run: async () => {
          providerCalls += 1;
          return {
            response: JSON.stringify(insightArtifact),
            usage: { prompt_tokens: 4, completion_tokens: 3 },
          };
        },
      } as unknown as Ai,
    };
    const recovered = await worker.fetch(completeWithBudget(), healthyEnv);
    expect(recovered.status).toBe(200);
    expect(providerCalls).toBe(1);
  });
});
