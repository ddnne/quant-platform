import { describe, expect, it } from "vitest";
import {
  MemoryBudgetStorage,
  handleBudgetRequest,
  zeroCounters,
} from "./budget_do";

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
});
