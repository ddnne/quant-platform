import { describe, expect, it } from "vitest";
import { MemoryBudgetStorage, zeroCounters } from "./budget_do";
import { handleBudgetRequest } from "./budget_http";

/** HTTP dispatcher only. Live Cloudflare Durable Object occupancy is unproven. */

const T0 = 1_700_000_000_000;
const BASE = "https://budget.test";

type BudgetSnapshot = {
  ok: boolean;
  auto_promotion: boolean;
  frozen?: boolean;
  used: Record<string, number>;
  reserved: Record<string, number>;
  active_leases: number;
};

type ReserveResponse = {
  ok: boolean;
  lease?: { lease_id: string; expires_at: number } | null;
  reservation?: {
    amounts?: Record<string, number>;
    settlement_capability_secret?: unknown;
  };
};

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

async function parseSnapshot(res: Response): Promise<BudgetSnapshot> {
  expect(res.status).toBe(200);
  expect(res.headers.get("content-type")).toMatch(/application\/json/);
  const payload = (await res.json()) as BudgetSnapshot;
  expect(payload.ok).toBe(true);
  expect(payload.auto_promotion).toBe(false);
  return payload;
}

async function expectIdleSnapshot(storage: MemoryBudgetStorage): Promise<BudgetSnapshot> {
  const payload = await parseSnapshot(await dispatch(storage, "GET", "/snapshot"));
  expect(payload.used).toEqual(zeroCounters());
  expect(payload.reserved).toEqual(zeroCounters());
  expect(payload.active_leases).toBe(0);
  return payload;
}

describe("handleBudgetRequest HTTP dispatcher", () => {
  it.each(["/snapshot", "/"] as const)(
    "GET %s is 200 JSON; auto_promotion false; budget_id is not a reserve",
    async (path) => {
      const storage = new MemoryBudgetStorage();
      const payload = await parseSnapshot(await dispatch(storage, "GET", path));
      expect(payload.used).toEqual(zeroCounters());
      expect(payload.reserved).toEqual(zeroCounters());
      expect(payload.active_leases).toBe(0);
    },
  );

  it.each<{
    title: string;
    method: string;
    path: string;
    status: number;
    error: string;
    init: { headers?: HeadersInit; body?: BodyInit };
  }>([
    {
      title: "POST /snapshot is 404 not found (POST switch has no /snapshot)",
      method: "POST",
      path: "/snapshot",
      status: 404,
      error: "not found",
      init: { headers: { "content-type": "application/json" }, body: "{}" },
    },
    {
      title: "GET /create is 405 POST required",
      method: "GET",
      path: "/create",
      status: 405,
      error: "POST required",
      init: {},
    },
    {
      title: "POST /create with invalid JSON is 400 invalid JSON body",
      method: "POST",
      path: "/create",
      status: 400,
      error: "invalid JSON body",
      init: { headers: { "content-type": "application/json" }, body: "{" },
    },
    {
      title: "POST /unknown-path is 404 not found",
      method: "POST",
      path: "/unknown-path",
      status: 404,
      error: "not found",
      init: {},
    },
    {
      title: "GET /finalize is 404 not found",
      method: "GET",
      path: "/finalize",
      status: 404,
      error: "not found",
      init: {},
    },
    {
      title: "GET /heartbeat is 405 POST required",
      method: "GET",
      path: "/heartbeat",
      status: 405,
      error: "POST required",
      init: {},
    },
    {
      title: "GET /reconcile is 404 not found",
      method: "GET",
      path: "/reconcile",
      status: 404,
      error: "not found",
      init: {},
    },
    {
      title: "POST /reconcile invalid JSON is 404 not found",
      method: "POST",
      path: "/reconcile",
      status: 404,
      error: "not found",
      init: { headers: { "content-type": "application/json" }, body: "{" },
    },
    {
      title: "GET /release is 405 POST required",
      method: "GET",
      path: "/release",
      status: 405,
      error: "POST required",
      init: {},
    },
    {
      title: "GET /reserve is 405 POST required",
      method: "GET",
      path: "/reserve",
      status: 405,
      error: "POST required",
      init: {},
    },
  ])("$title", async ({ method, path, status, error, init }) => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, method, path, init);
    expect(res.status).toBe(status);
    expect(await res.json()).toEqual({ ok: false, error });
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
    await expectIdleSnapshot(storage);
  });

  it.each([
    {
      title: "POST /reserve JSON {} is 400 idempotency_key required and does not create occupancy",
      path: "/reserve",
      status: 400,
      error: "idempotency_key required",
    },
    {
      title: "POST /heartbeat JSON {} is fail-closed lease_id required and does not create occupancy",
      path: "/heartbeat",
      status: 400,
      error: "lease_id required",
    },
    {
      title: "POST /release JSON {} is fail-closed lease_or_idempotency_key required and does not create occupancy",
      path: "/release",
      status: 400,
      error: "lease_or_idempotency_key required",
    },
    {
      title: "POST /reconcile JSON {} is 404 and does not create occupancy",
      path: "/reconcile",
      status: 404,
      error: "not found",
    },
  ] as const)("$title", async ({ path, status, error }) => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", path, {
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).toBe(status);
    expect(await res.json()).toEqual({ ok: false, error });
    await expectIdleSnapshot(storage);
  });

  it("POST /finalize JSON {} is 404 and does not create occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/finalize", {
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ ok: false, error: "not found" });
    const payload = await expectIdleSnapshot(storage);
    expect(payload.frozen).toBe(false);
  });

  it("POST /recover is 200 ok without claiming Edge occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/recover");
    expect(res.status).toBe(200);
    const payload = (await res.json()) as { ok: boolean };
    expect(payload.ok).toBe(true);
    const after = await parseSnapshot(await dispatch(storage, "GET", "/snapshot"));
    expect(after.used).toEqual(zeroCounters());
    expect(after.reserved).toEqual(zeroCounters());
  });

  it("POST /reserve JSON { idempotency_key: k1 } with no amounts is ok true zero occupancy not a consume", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/reserve", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        idempotency_key: "k1",
        request_digest: "a".repeat(64),
      }),
    });
    expect(res.status).toBe(200);
    const payload = (await res.json()) as ReserveResponse;
    expect(payload.ok).toBe(true);
    expect(payload.lease?.lease_id).toEqual(expect.any(String));
    expect(payload.lease?.expires_at).toBe(T0 + 1800 * 1000);
    expect(payload.reservation?.settlement_capability_secret ?? null).toBeNull();
    if (payload.reservation?.amounts !== undefined) {
      expect(payload.reservation.amounts).toEqual(zeroCounters());
    }

    const after = await parseSnapshot(await dispatch(storage, "GET", "/snapshot"));
    expect(after.used).toEqual(zeroCounters());
    expect(after.reserved).toEqual(zeroCounters());
    expect(after.active_leases).toBe(1);
  });

  it("POST /reserve without request_digest is 400 and creates no occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const res = await dispatch(storage, "POST", "/reserve", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ idempotency_key: "k1" }),
    });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ ok: false, error: "request_digest required" });
    await expectIdleSnapshot(storage);
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
    const payload = await parseSnapshot(await dispatch(storage, "GET", "/snapshot"));
    expect(payload.used).toEqual(zeroCounters());
    expect(payload.reserved?.model_calls).toBe(1);
    expect(payload.frozen).toBe(false);
    expect(payload.active_leases).toBe(1);
  });
});
