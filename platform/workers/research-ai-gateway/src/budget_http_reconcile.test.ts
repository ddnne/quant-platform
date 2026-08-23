import { describe, expect, it } from "vitest";
import {
  MemoryBudgetStorage,
  handleBudgetRequest,
  zeroCounters,
} from "./budget_do";

/** In-memory HTTP algebra for POST /reconcile. Live Edge occupancy is unproven. */

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

describe("handleBudgetRequest POST /reconcile", () => {
  it("POST /reconcile JSON {} is 400 idempotency_key required and does not create occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/reconcile", {
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).not.toBe(200);
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ ok: false, error: "idempotency_key required" });

    const snap = await dispatch(storage, "GET", "/snapshot");
    expect(snap.status).toBe(200);
    const payload = (await snap.json()) as {
      ok?: boolean;
      auto_promotion?: boolean;
      used?: Record<string, number>;
      reserved?: Record<string, number>;
      active_leases?: number;
    };
    expect(payload.ok).toBe(true);
    expect(payload.auto_promotion).toBe(false);
    expect(payload.used).toEqual(zeroCounters());
    expect(payload.reserved).toEqual(zeroCounters());
    expect(payload.active_leases).toBe(0);
  });

  it("GET /reconcile is 405 POST required", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "GET", "/reconcile");
    expect(res.status).toBe(405);
    expect(await res.json()).toEqual({ ok: false, error: "POST required" });
  });

  it("POST /reconcile invalid JSON is 400 invalid JSON body", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/reconcile", {
      headers: { "content-type": "application/json" },
      body: "{",
    });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ ok: false, error: "invalid JSON body" });
  });
});
