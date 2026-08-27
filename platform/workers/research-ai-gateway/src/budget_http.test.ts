import { describe, expect, it } from "vitest";
import { MemoryBudgetStorage, zeroCounters } from "./budget_do";
import { handleBudgetRequest } from "./budget_http";

/** HTTP dispatcher only. Live Cloudflare Durable Object occupancy is unproven. */

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

describe("handleBudgetRequest HTTP dispatcher", () => {
  it.each(["/snapshot", "/"] as const)(
    "GET %s is 200 JSON; auto_promotion false; budget_id is not a reserve",
    async (path) => {
      const storage = new MemoryBudgetStorage();
      const res = await dispatch(storage, "GET", path);
      expect(res.status).toBe(200);
      expect(res.headers.get("content-type")).toMatch(/application\/json/);
      const payload = (await res.json()) as {
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
    },
  );

  it("POST /snapshot is 404 not found (POST switch has no /snapshot)", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/snapshot", {
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ ok: false, error: "not found" });
  });

  it("GET /create is 405 POST required", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "GET", "/create");
    expect(res.status).toBe(405);
    expect(await res.json()).toEqual({ ok: false, error: "POST required" });
  });

  it("POST /create with invalid JSON is 400 invalid JSON body", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/create", {
      headers: { "content-type": "application/json" },
      body: "{",
    });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ ok: false, error: "invalid JSON body" });
  });

  it("POST /unknown-path is 404 not found", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/unknown-path");
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ ok: false, error: "not found" });
  });

  it.each([
    "/provider-started",
    "/settle-uncertain",
    "/mint",
    "/mint-settlement-capability",
  ] as const)("direct HTTP %s is 404 and does not mint settlement authority", async (path) => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", path, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        idempotency_key: "http-mint",
        lease_id: "lease",
        reason: "timeout",
      }),
    });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ ok: false, error: "not found" });
    const snap = await dispatch(storage, "GET", "/snapshot");
    const payload = (await snap.json()) as {
      used?: Record<string, number>;
      reserved?: Record<string, number>;
      active_leases?: number;
    };
    expect(payload.used).toEqual(zeroCounters());
    expect(payload.reserved).toEqual(zeroCounters());
    expect(payload.active_leases).toBe(0);
  });

  it("POST /reserve JSON {} is 400 idempotency_key required and does not create occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/reserve", {
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

  it("POST /recover is 200 ok without claiming Edge occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/recover");
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { ok?: boolean };
    expect(payload.ok).toBe(true);

    const snap = await dispatch(storage, "GET", "/snapshot");
    expect(snap.status).toBe(200);
    const after = (await snap.json()) as {
      reserved?: Record<string, number>;
      used?: Record<string, number>;
      auto_promotion?: boolean;
    };
    expect(after.auto_promotion).toBe(false);
    expect(after.used).toEqual(zeroCounters());
    expect(after.reserved).toEqual(zeroCounters());
  });
});
