import { describe, expect, it } from "vitest";
import { MemoryBudgetStorage, zeroCounters } from "./budget_do";
import { handleBudgetRequest } from "./budget_http";

/** In-memory HTTP algebra for POST /finalize. Live Edge occupancy is unproven. */

const T0 = 1_700_000_000_000;
const BASE = "https://budget.test";

function dispatch(
  storage: MemoryBudgetStorage,
  method: string,
  path: string,
  init: { headers?: HeadersInit; body?: BodyInit } = {},
): Promise<Response> {
  return handleBudgetRequest(
    storage,
    new Request(`${BASE}${path}`, { method, ...init }),
    T0,
  );
}

describe("handleBudgetRequest POST /finalize", () => {
  it("POST /finalize JSON {} is 404 and does not create occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/finalize", {
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).not.toBe(200);
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ ok: false, error: "not found" });

    const snap = await dispatch(storage, "GET", "/snapshot");
    expect(snap.status).toBe(200);
    const payload = (await snap.json()) as {
      ok?: boolean;
      auto_promotion?: boolean;
      frozen?: boolean;
      used?: Record<string, number>;
      reserved?: Record<string, number>;
      active_leases?: number;
    };
    expect(payload.ok).toBe(true);
    expect(payload.auto_promotion).toBe(false);
    expect(payload.frozen).toBe(false);
    expect(payload.used).toEqual(zeroCounters());
    expect(payload.reserved).toEqual(zeroCounters());
    expect(payload.active_leases).toBe(0);
  });

  it("GET /finalize is 404 not found", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "GET", "/finalize");
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ ok: false, error: "not found" });
  });

  it("direct HTTP finalize after reserve cannot settle or charge zero", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await dispatch(storage, "POST", "/reserve", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        idempotency_key: "http-finalize",
        request_digest: "a".repeat(64),
        acquire_lease: true,
        amounts: { model_calls: 1, cost_usd: 1 },
      }),
    });
    expect(reserved.status).toBe(200);
    const res = await dispatch(storage, "POST", "/finalize", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        idempotency_key: "http-finalize",
        amounts: { model_calls: 0, cost_usd: 0 },
        settlement: { outcome: "success", usage_source: "provider" },
        result: { http_status: 200, body: { ok: true } },
      }),
    });
    expect(res.status).toBe(404);
    const snap = await dispatch(storage, "GET", "/snapshot");
    const payload = (await snap.json()) as {
      used?: Record<string, number>;
      reserved?: Record<string, number>;
      frozen?: boolean;
      active_leases?: number;
    };
    expect(payload.used).toEqual(zeroCounters());
    expect(payload.reserved?.model_calls).toBe(1);
    expect(payload.frozen).toBe(false);
    expect(payload.active_leases).toBe(1);
  });
});
