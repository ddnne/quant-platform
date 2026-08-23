import { describe, expect, it } from "vitest";
import {
  MemoryBudgetStorage,
  handleBudgetRequest,
  zeroCounters,
} from "./budget_do";

/** POST /release HTTP pin. In-memory only; live Edge occupancy unproven. */

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

describe("handleBudgetRequest POST /release", () => {
  it("POST /release JSON {} is fail-closed lease_or_idempotency_key required and does not create occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/release", {
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).not.toBe(200);
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({
      ok: false,
      error: "lease_or_idempotency_key required",
    });

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

  it("GET /release is 405 POST required", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "GET", "/release");
    expect(res.status).toBe(405);
    expect(await res.json()).toEqual({ ok: false, error: "POST required" });
  });
});
