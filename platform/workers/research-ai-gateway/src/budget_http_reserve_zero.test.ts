import { describe, expect, it } from "vitest";
import {
  MemoryBudgetStorage,
  handleBudgetRequest,
  zeroCounters,
} from "./budget_do";

/**
 * POST /reserve without amounts is zero occupancy, not a consume.
 * A zero-amount reservation record may exist in-memory; that is not cap
 * consumption, not budget_exhausted, and not GO. Live Edge occupancy unproven.
 */

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

describe("handleBudgetRequest POST /reserve without amounts", () => {
  it("POST /reserve JSON { idempotency_key: k1 } with no amounts is ok true zero occupancy not a consume", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/reserve", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ idempotency_key: "k1" }),
    });
    expect(res.status).not.toBe(429);
    expect(res.status).toBe(200);
    const payload = (await res.json()) as {
      ok?: boolean;
      error?: string;
      lease?: unknown;
      reservation?: { amounts?: Record<string, number> };
    };
    expect(payload.ok).toBe(true);
    expect(payload.error).not.toBe("budget_exhausted");
    expect(payload.lease).toBeNull();
    if (payload.reservation?.amounts !== undefined) {
      expect(payload.reservation.amounts).toEqual(zeroCounters());
    }

    const snap = await dispatch(storage, "GET", "/snapshot");
    expect(snap.status).toBe(200);
    const after = (await snap.json()) as {
      ok?: boolean;
      auto_promotion?: boolean;
      used?: Record<string, number>;
      reserved?: Record<string, number>;
      active_leases?: number;
    };
    expect(after.ok).toBe(true);
    expect(after.auto_promotion).toBe(false);
    expect(after.used).toEqual(zeroCounters());
    expect(after.reserved).toEqual(zeroCounters());
    expect(after.active_leases).toBe(0);
  });

  it("GET /reserve is 405 POST required", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "GET", "/reserve");
    expect(res.status).toBe(405);
    expect(await res.json()).toEqual({ ok: false, error: "POST required" });
  });
});
