import { env, exports as workerExports } from "cloudflare:workers";
import { afterEach, describe, expect, expectTypeOf, it } from "vitest";
import {
  evictDurableObject,
  reset,
  runDurableObjectAlarm,
  runInDurableObject,
} from "cloudflare:test";
import {
  CONTROL_PLANE_LEDGER_NAME,
  type LedgerState,
  type PublicReservation,
  type Reservation,
} from "./budget_do";
import { BudgetLedger } from "./budget_http";
import { GatewayService, type GatewayEnv } from "./index";
import bindingManifest from "../../../../specs/cloudflare/active_worker_bindings.json";

const runtimeEnv = env as GatewayEnv;
// A DO eviction forces a fresh workerd isolate. Six Worker lanes run in
// parallel in the authoritative CI, so the former 2s per-stage watchdog could
// expire during isolate startup even though the operation completed correctly.
// Keep a strict bound, but leave enough room for the runtime lifecycle rather
// than measuring host scheduler latency.
const RUNTIME_STAGE_TIMEOUT_MS = 5_000;

function testDigest(label: string): string {
  const seed = Array.from(
    new TextEncoder().encode(label),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("") || "0";
  return seed.repeat(Math.ceil(64 / seed.length)).slice(0, 64);
}

async function within<T>(stage: string, promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error(`runtime stage timed out: ${stage}`)),
          RUNTIME_STAGE_TIMEOUT_MS,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

function post(stub: DurableObjectStub, path: string, body: unknown): Promise<Response> {
  return stub.fetch(
    new Request(`https://budget${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

function actualUsage(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    model_calls: 1,
    input_tokens: 0,
    output_tokens: 0,
    cached_tokens: 0,
    cost_usd: 0,
    cost_source: "provider",
    provider_model: "@cf/meta/llama-3.1-8b-instruct-fp8",
    pricing_policy_id: null,
    pricing_policy_digest: null,
    ...overrides,
  };
}

type BudgetLedgerRpcStub = DurableObjectStub & {
  reserve(input: {
    idempotency_key: string;
    amounts: unknown;
    acquire_lease?: boolean;
    request_digest?: string;
    reserve_owner_capability?: string;
  }): Promise<{
    ok: boolean;
    error?: string;
    existing?: boolean;
    owner_recovered?: boolean;
    budget_run_id?: string;
    reservation?: Record<string, unknown>;
    lease?: { lease_id: string; expires_at: number } | null;
  }>;
  markProviderStarted(input: {
    idempotency_key: string;
    lease_id: string;
    request_digest?: string;
    reserve_owner_capability?: string;
  }): Promise<{
    ok: boolean;
    error?: string;
    settlement_capability?: string | null;
    reservation?: Record<string, unknown>;
    lease?: { lease_id: string };
  }>;
  finalizeExact(input: {
    idempotency_key: string;
    request_digest: string;
    lease_id: string;
    settlement_capability: string;
    usage: unknown;
    terminal_result?: { http_status: number; body: unknown };
    amounts?: unknown;
    result?: unknown;
    settlement?: unknown;
  }): Promise<{
    ok: boolean;
    error?: string;
    reservation?: Record<string, unknown> & { actual?: { input_tokens?: number } };
    used?: { input_tokens?: number; model_calls?: number };
    frozen?: boolean;
  }>;
  settleUncertain(input: {
    idempotency_key: string;
    reason: string;
    request_digest?: string;
    lease_id?: string;
    settlement_capability?: string;
  }): Promise<{
    ok: boolean;
    error?: string;
    reservation?: Record<string, unknown>;
    used?: { input_tokens?: number; model_calls?: number };
  }>;
  release(input: {
    lease_id?: string;
    idempotency_key?: string;
    request_digest?: string;
    reserve_owner_capability?: string;
  }): Promise<{
    ok: boolean;
    error?: string;
    reservation?: Record<string, unknown> | null;
  }>;
  cancelPreProvider(input: {
    idempotency_key: string;
    request_digest: string;
    reserve_owner_capability: string;
  }): Promise<{
    ok: boolean;
    error?: string;
    cancelled?: boolean;
    reservation?: Record<string, unknown> | null;
  }>;
};

const OWNER_A = "a".repeat(64);
const OWNER_B = "b".repeat(64);

afterEach(async () => {
  await reset();
});

describe("BudgetLedger in the Workers runtime", () => {
  it("matches the exact BudgetLedger special-handler and ordinary RPC inventory", () => {
    const rows = bindingManifest.workers["research-ai-gateway"].staging
      .durable_object_class_handlers;
    expect(rows).toHaveLength(1);
    const inventory = rows[0]!;
    expect(inventory).toEqual({
      name: "BudgetLedger",
      handlers: ["class"],
      fetch_reserved_special: true,
      alarm_reserved_special: true,
      rpc_methods: [
        "cancelPreProvider",
        "finalizeExact",
        "finalizeOwnedPaper",
        "heartbeat",
        "markProviderStarted",
        "queryOwned",
        "release",
        "reserve",
        "reserveOwned",
        "settleUncertain",
        "snapshot",
      ],
    });

    const methods = Reflect.ownKeys(BudgetLedger.prototype)
      .map(String)
      .filter((name) => name !== "constructor");
    expect(methods.includes("fetch")).toBe(inventory.fetch_reserved_special);
    expect(methods.includes("alarm")).toBe(inventory.alarm_reserved_special);
    expect(
      methods.filter((name) => name !== "fetch" && name !== "alarm").sort(),
    ).toEqual([...inventory.rpc_methods].sort());
  });

  it("matches the exact no-fetch GatewayService RPC inventory", () => {
    const rows = bindingManifest.workers["research-ai-gateway"].staging
      .worker_entrypoints;
    expect(rows).toHaveLength(1);
    const inventory = rows[0]!;
    expect(inventory).toMatchObject({
      name: "GatewayService",
      fetch_reserved_special: false,
      rpc_methods: [
        "cancelControlledPaper",
        "complete",
        "finalizeControlledPaper",
        "heartbeatControlledPaper",
        "queryControlledPaper",
        "reserveControlledPaper",
      ],
    });
    expect(
      Reflect.ownKeys(GatewayService.prototype)
        .map(String)
        .filter((name) => name !== "constructor")
        .sort(),
    ).toEqual([...inventory.rpc_methods].sort());
  });

  it("exposes the closed GatewayService RPC entrypoint without header auth", async () => {
    const service = workerExports.GatewayService as {
      complete(body: unknown): Promise<{ http_status: number; body: unknown }>;
    };
    const result = await service.complete({});
    expect(result.http_status).toBe(400);
    expect(result.body).toMatchObject({
      ok: false,
      error: expect.stringContaining("model"),
    });
  });

  it("serializes concurrent leases and persists settlement across eviction", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const idempotencyKeys = ["runtime-a", "runtime-b", "runtime-c"];
    const attempts = await within("concurrent reserve", Promise.all(
      idempotencyKeys.map((idempotencyKey) =>
        post(stub, "/reserve", {
          idempotency_key: idempotencyKey,
          request_digest: testDigest(idempotencyKey),
          acquire_lease: true,
          amounts: { model_calls: 1, input_tokens: 10, output_tokens: 5 },
        }),
      ),
    ));
    expect(attempts.map((response) => response.status).sort()).toEqual([
      200,
      200,
      429,
    ]);
    const successful = await Promise.all(
      attempts.map(async (response, index) => {
        if (response.status !== 200) {
          await response.text();
          return null;
        }
        const body = (await response.json()) as { lease: { lease_id: string } };
        return { idempotencyKey: idempotencyKeys[index], leaseId: body.lease.lease_id };
      }),
    );
    const successfulKeys = successful.filter(
      (row): row is { idempotencyKey: string; leaseId: string } => row !== null,
    );

    await within("evict", evictDurableObject(stub));
    const afterRestart = await within(
      "snapshot after restart",
      stub.fetch("https://budget/snapshot"),
    );
    const restartSnapshot = (await afterRestart.json()) as {
      reserved: { model_calls: number };
      active_leases: number;
    };
    expect(restartSnapshot.reserved.model_calls).toBe(2);
    expect(restartSnapshot.active_leases).toBe(2);

    const rpc = stub as BudgetLedgerRpcStub;
    for (const row of successfulKeys) {
      const started = await rpc.markProviderStarted({
        idempotency_key: row.idempotencyKey,
        lease_id: row.leaseId,
        request_digest: testDigest(row.idempotencyKey),
      });
      expect(started.ok).toBe(true);
      expect(started.settlement_capability).toEqual(expect.any(String));
      const finalized = await rpc.finalizeExact({
        idempotency_key: row.idempotencyKey,
        request_digest: testDigest(row.idempotencyKey),
        lease_id: row.leaseId,
        settlement_capability: started.settlement_capability as string,
        usage: actualUsage({ model_calls: 1, input_tokens: 7, output_tokens: 3 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      });
      expect(finalized.ok).toBe(true);
    }

    const after = await stub.fetch("https://budget/snapshot");
    const snapshot = (await after.json()) as {
      used: { model_calls: number; input_tokens: number; output_tokens: number };
      reserved: { model_calls: number };
      active_leases: number;
    };
    expect(snapshot.used).toMatchObject({
      model_calls: 2,
      input_tokens: 14,
      output_tokens: 6,
    });
    expect(snapshot.reserved.model_calls).toBe(0);
    expect(snapshot.active_leases).toBe(0);
  }, 20_000);

  it("alarm conservatively settles provider-started expiry", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const reservedResponse = await within("uncertain reserve", post(stub, "/reserve", {
      idempotency_key: "runtime-uncertain",
      request_digest: testDigest("runtime-uncertain"),
      acquire_lease: true,
      amounts: {
        model_calls: 1,
        input_tokens: 200,
        output_tokens: 20,
        cached_tokens: 200,
        cost_usd: 0.5,
      },
    }));
    expect(reservedResponse.status).toBe(200);
    const reserved = (await reservedResponse.json()) as {
      lease: { lease_id: string };
    };
    const started = await within(
      "provider marker",
      (stub as BudgetLedgerRpcStub).markProviderStarted({
        idempotency_key: "runtime-uncertain",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("runtime-uncertain"),
      }),
    );
    expect(started.ok).toBe(true);

    await within("seed expired alarm", runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      if (!ledger) throw new Error("ledger state missing");
      ledger.leases[reserved.lease.lease_id].expires_at = Date.now() - 1;
      await Promise.all([
        state.storage.put("ledger", ledger),
        state.storage.setAlarm(Date.now()),
      ]);
    }));
    // workerd may deliver an already-due alarm before the explicit test helper
    // observes it; either path must reach the same durable settlement.
    await within("run alarm", runDurableObjectAlarm(stub));

    const alarmSnapshotResponse = await within(
      "snapshot after alarm",
      stub.fetch("https://budget/snapshot"),
    );
    const alarmSnapshot = (await alarmSnapshotResponse.json()) as {
      frozen: boolean;
      used: { model_calls: number; input_tokens: number; output_tokens: number; cached_tokens: number };
      reserved: { model_calls: number };
      active_leases: number;
    };
    expect(alarmSnapshot).toMatchObject({
      frozen: true,
      used: { model_calls: 1, input_tokens: 200, output_tokens: 20, cached_tokens: 200 },
      reserved: { model_calls: 0 },
      active_leases: 0,
    });

  }, 15_000);

  it("persists the provider recovery marker and reservation across restart", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const reservedResponse = await within("restart reserve", post(stub, "/reserve", {
      idempotency_key: "runtime-restart-uncertain",
      request_digest: testDigest("runtime-restart-uncertain"),
      acquire_lease: true,
      amounts: { model_calls: 1, input_tokens: 70, output_tokens: 7, cached_tokens: 70 },
    }));
    const reserved = (await reservedResponse.json()) as { lease: { lease_id: string } };
    const started = await within(
      "restart provider marker",
      (stub as BudgetLedgerRpcStub).markProviderStarted({
        idempotency_key: "runtime-restart-uncertain",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("runtime-restart-uncertain"),
      }),
    );
    expect(started.ok).toBe(true);
    expect(started.settlement_capability).toEqual(expect.any(String));

    await within("evict provider marker", evictDurableObject(stub));
    const restartedResponse = await within(
      "restart recovery snapshot",
      stub.fetch("https://budget/snapshot"),
    );
    expect(await restartedResponse.json()).toMatchObject({
      frozen: false,
      used: { model_calls: 0, input_tokens: 0, output_tokens: 0, cached_tokens: 0 },
      reserved: { model_calls: 1, input_tokens: 70, output_tokens: 7, cached_tokens: 70 },
      active_leases: 1,
    });
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      expect(
        ledger?.reservations["runtime-restart-uncertain"].provider_started_at,
      ).toEqual(expect.any(Number));
      expect(
        ledger?.reservations["runtime-restart-uncertain"].settlement_capability_hash,
      ).toEqual(expect.any(String));
      expect(
        ledger?.reservations["runtime-restart-uncertain"].settlement_capability_secret,
      ).toEqual(expect.any(String));
    });
  }, 15_000);

  it("retries a lost provider-start response after eviction with the same capability", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const reservedResponse = await within(
      "lost-start reserve",
      post(stub, "/reserve", {
        idempotency_key: "runtime-lost-start",
        request_digest: testDigest("runtime-lost-start"),
        acquire_lease: true,
        amounts: { model_calls: 1, input_tokens: 12, output_tokens: 3 },
      }),
    );
    const reserved = (await reservedResponse.json()) as { lease: { lease_id: string } };
    const started = await within(
      "lost-start first mint",
      rpc.markProviderStarted({
        idempotency_key: "runtime-lost-start",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("runtime-lost-start"),
      }),
    );
    expect(started.ok).toBe(true);
    expect(started.settlement_capability).toEqual(expect.any(String));
    const snapshot = await within(
      "lost-start public snapshot",
      stub.fetch("https://budget/snapshot"),
    );
    expect(JSON.stringify(await snapshot.json())).not.toContain(
      started.settlement_capability,
    );

    await within("evict lost-start", evictDurableObject(stub));
    const retried = await within(
      "lost-start retry",
      rpc.markProviderStarted({
        idempotency_key: "runtime-lost-start",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("runtime-lost-start"),
      }),
    );
    expect(retried.ok).toBe(true);
    expect(retried.settlement_capability).toBe(started.settlement_capability);

    const omitted = await within(
      "lost-start omitted digest",
      rpc.markProviderStarted({
        idempotency_key: "runtime-lost-start",
        lease_id: reserved.lease.lease_id,
      }),
    );
    expect(omitted).toMatchObject({ ok: false, error: "request_digest required" });

    const committed = await within(
      "lost-start exact settle",
      rpc.finalizeExact({
        idempotency_key: "runtime-lost-start",
        request_digest: testDigest("runtime-lost-start"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: retried.settlement_capability as string,
        usage: actualUsage({ model_calls: 1, input_tokens: 4, output_tokens: 2 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      }),
    );
    expect(committed.ok).toBe(true);
    expect(committed.used?.input_tokens).toBe(4);
  }, 15_000);

  it("recovers and cancels an owner-bound reserve across eviction without exposing authority", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const input = {
      idempotency_key: "runtime-owner-reserve",
      request_digest: testDigest("runtime-owner-reserve"),
      reserve_owner_capability: OWNER_A,
      acquire_lease: true,
      amounts: { model_calls: 1, input_tokens: 11, output_tokens: 2 },
    } as const;
    const reserved = await within("owner reserve", rpc.reserve(input));
    expect(reserved).toMatchObject({
      ok: true,
      existing: false,
      owner_recovered: false,
    });
    expect(JSON.stringify(reserved)).not.toContain(OWNER_A);
    expect(reserved.reservation).not.toHaveProperty("reserve_owner_capability_hash");
    let persistedHash = "";
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      persistedHash =
        ledger?.reservations["runtime-owner-reserve"].reserve_owner_capability_hash ?? "";
      expect(persistedHash).toMatch(/^[0-9a-f]{64}$/);
      expect(JSON.stringify(ledger)).not.toContain(OWNER_A);
    });
    expect(JSON.stringify(reserved)).not.toContain(persistedHash);

    await within("evict owner reserve", evictDurableObject(stub));
    const recovered = await within("recover owner reserve", rpc.reserve(input));
    expect(recovered).toMatchObject({
      ok: true,
      existing: true,
      owner_recovered: true,
      budget_run_id: reserved.budget_run_id,
    });
    const other = await within(
      "reject other owner reserve",
      rpc.reserve({ ...input, reserve_owner_capability: OWNER_B }),
    );
    expect(other).toEqual({
      ok: false,
      error: "reservation_owned_by_other_invocation",
    });
    const wrongCancel = await within(
      "reject other owner cancel",
      rpc.cancelPreProvider({
        idempotency_key: input.idempotency_key,
        request_digest: input.request_digest,
        reserve_owner_capability: OWNER_B,
      }),
    );
    expect(wrongCancel).toEqual({
      ok: false,
      error: "reserve_owner_capability_invalid",
    });
    const cancelled = await within(
      "cancel owner reserve",
      rpc.cancelPreProvider({
        idempotency_key: input.idempotency_key,
        request_digest: input.request_digest,
        reserve_owner_capability: OWNER_A,
      }),
    );
    expect(cancelled).toMatchObject({ ok: true, cancelled: true });

    await within("evict cancelled owner reserve", evictDurableObject(stub));
    const cancelReplay = await within(
      "replay owner cancel",
      rpc.cancelPreProvider({
        idempotency_key: input.idempotency_key,
        request_digest: input.request_digest,
        reserve_owner_capability: OWNER_A,
      }),
    );
    expect(cancelReplay).toMatchObject({ ok: true, cancelled: false });
    const snapshot = await within("owner cancel snapshot", stub.fetch("https://budget/snapshot"));
    expect(await snapshot.json()).toMatchObject({
      reserved: { model_calls: 0, input_tokens: 0, output_tokens: 0 },
      used: { model_calls: 0, input_tokens: 0, output_tokens: 0 },
      active_leases: 0,
    });
  }, 15_000);

  it("direct HTTP finalize, reconcile, provider-start, and mint are not settlement authority", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const reservedResponse = await post(stub, "/reserve", {
      idempotency_key: "runtime-http-bypass",
      request_digest: testDigest("runtime-http-bypass"),
      acquire_lease: true,
      amounts: { model_calls: 1, cost_usd: 1 },
    });
    expect(reservedResponse.status).toBe(200);
    await reservedResponse.text();
    for (const path of [
      "/finalize",
      "/cancel-pre-provider",
      "/reconcile",
      "/provider-started",
      "/settle-uncertain",
      "/mint",
      "/mint-settlement-capability",
    ]) {
      const denied = await post(stub, path, {
        idempotency_key: "runtime-http-bypass",
        amounts: { model_calls: 0, cost_usd: 0 },
        settlement: { outcome: "success" },
        result: { http_status: 200, body: { ok: true } },
      });
      expect(denied.status).toBe(404);
      expect(await denied.json()).toMatchObject({ ok: false, error: "not found" });
    }
    const snap = await stub.fetch("https://budget/snapshot");
    expect(await snap.json()).toMatchObject({
      used: { model_calls: 0, cost_usd: 0 },
      reserved: { model_calls: 1, cost_usd: 1 },
      frozen: false,
      active_leases: 1,
    });
  }, 15_000);

  it("RPC finalize rejects unstarted, forged, cross-bound, and injected claims", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const reservedResponse = await post(stub, "/reserve", {
      idempotency_key: "runtime-rpc-auth",
      request_digest: testDigest("runtime-rpc-auth"),
      acquire_lease: true,
      amounts: { model_calls: 1, input_tokens: 20 },
    });
    const reserved = (await reservedResponse.json()) as { lease: { lease_id: string } };
    const unstarted = await rpc.finalizeExact({
      idempotency_key: "runtime-rpc-auth",
      request_digest: testDigest("runtime-rpc-auth"),
      lease_id: reserved.lease.lease_id,
      settlement_capability: "aa".repeat(32),
      usage: actualUsage({ model_calls: 0, input_tokens: 0 }),
    });
    expect(unstarted).toMatchObject({ ok: false, error: "provider_not_started" });

    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-rpc-auth",
      lease_id: reserved.lease.lease_id,
      request_digest: testDigest("runtime-rpc-auth"),
    });
    expect(started.ok).toBe(true);
    const cap = started.settlement_capability as string;

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-rpc-auth",
        request_digest: testDigest("runtime-rpc-auth"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: "ff".repeat(32),
        usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
      }),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-rpc-auth",
        request_digest: testDigest("other"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
      }),
    ).toMatchObject({ ok: false, error: "request_digest_mismatch" });

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-rpc-auth",
        request_digest: testDigest("runtime-rpc-auth"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        amounts: { model_calls: 0 },
        result: { http_status: 200, body: { ok: true } },
        settlement: { outcome: "success" },
      }),
    ).toMatchObject({ ok: false, error: "caller_settlement_rejected" });

    const committed = await rpc.finalizeExact({
      idempotency_key: "runtime-rpc-auth",
      request_digest: testDigest("runtime-rpc-auth"),
      lease_id: reserved.lease.lease_id,
      settlement_capability: cap,
      usage: actualUsage({ model_calls: 1, input_tokens: 6 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    });
    expect(committed.ok).toBe(true);
    const replay = await rpc.finalizeExact({
      idempotency_key: "runtime-rpc-auth",
      request_digest: testDigest("runtime-rpc-auth"),
      lease_id: reserved.lease.lease_id,
      settlement_capability: cap,
      usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
    });
    expect(replay.ok).toBe(true);
    expect(replay.used?.input_tokens).toBe(6);
  }, 15_000);

  it("binds reserve to digest+lease and never leaks capability material", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;

    const missingDigest = await within(
      "missing digest reserve",
      rpc.reserve({
        idempotency_key: "runtime-missing-digest",
        amounts: { model_calls: 1 },
        acquire_lease: true,
      }),
    );
    expect(missingDigest).toMatchObject({ ok: false, error: "request_digest required" });
    expect(missingDigest.reservation).toBeUndefined();

    const noLease = await within(
      "no-lease reserve",
      rpc.reserve({
        idempotency_key: "runtime-no-lease",
        request_digest: testDigest("runtime-no-lease"),
        amounts: { model_calls: 1 },
        acquire_lease: false,
      }),
    );
    expect(noLease).toMatchObject({ ok: false, error: "lease_required" });
    expect(noLease.reservation).toBeUndefined();
    expect(noLease.lease ?? null).toBeNull();

    const emptySnap = await within("empty after rejected reserves", stub.fetch("https://budget/snapshot"));
    expect(await emptySnap.json()).toMatchObject({
      reserved: { model_calls: 0 },
      used: { model_calls: 0 },
      active_leases: 0,
      frozen: false,
    });

    const reserved = await within(
      "bound reserve",
      rpc.reserve({
        idempotency_key: "runtime-bind-secret",
        request_digest: testDigest("runtime-bind-secret"),
        amounts: { model_calls: 1, input_tokens: 9 },
        acquire_lease: true,
      }),
    );
    expect(reserved.ok).toBe(true);
    expect(reserved.lease?.lease_id).toEqual(expect.any(String));

    const replayMissing = await within(
      "replay missing digest",
      rpc.reserve({
        idempotency_key: "runtime-bind-secret",
        amounts: { model_calls: 1 },
        acquire_lease: true,
      }),
    );
    const replayWrong = await within(
      "replay wrong digest",
      rpc.reserve({
        idempotency_key: "runtime-bind-secret",
        request_digest: testDigest("other"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      }),
    );
    expect(replayMissing).toMatchObject({ ok: false, error: "request_digest required" });
    expect(replayWrong).toMatchObject({ ok: false, error: "idempotency_digest_conflict" });
    expect(replayMissing.reservation).toBeUndefined();
    expect(replayWrong.reservation).toBeUndefined();
    expect(JSON.stringify(replayMissing)).not.toMatch(/cached_result|settlement_capability/);
    expect(JSON.stringify(replayWrong)).not.toMatch(/cached_result|settlement_capability/);

    const started = await within(
      "bind provider start",
      rpc.markProviderStarted({
        idempotency_key: "runtime-bind-secret",
        lease_id: reserved.lease!.lease_id,
        request_digest: testDigest("runtime-bind-secret"),
      }),
    );
    expect(started.ok).toBe(true);
    const secret = started.settlement_capability as string;
    expect(secret).toEqual(expect.any(String));
    const retriedStart = await within(
      "bind mark-start retry",
      rpc.markProviderStarted({
        idempotency_key: "runtime-bind-secret",
        lease_id: reserved.lease!.lease_id,
        request_digest: testDigest("runtime-bind-secret"),
      }),
    );
    expect(retriedStart.ok).toBe(true);
    expect(retriedStart.settlement_capability).toBe(secret);
    expect(retriedStart.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(retriedStart.reservation).not.toHaveProperty("settlement_capability_hash");

    let persistedHash = "";
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      persistedHash =
        ledger?.reservations["runtime-bind-secret"].settlement_capability_hash ?? "";
      expect(persistedHash).toEqual(expect.any(String));
      expect(ledger?.reservations["runtime-bind-secret"].settlement_capability_secret).toBe(
        secret,
      );
    });

    const reserveReplay = await within(
      "reserve replay after start",
      rpc.reserve({
        idempotency_key: "runtime-bind-secret",
        request_digest: testDigest("runtime-bind-secret"),
        amounts: { model_calls: 1, input_tokens: 9 },
        acquire_lease: true,
      }),
    );
    expect(reserveReplay.ok).toBe(true);
    expect(reserveReplay.existing).toBe(true);
    const replayText = JSON.stringify(reserveReplay);
    expect(replayText).not.toContain(secret);
    expect(replayText).not.toContain(persistedHash);
    expect(reserveReplay.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(reserveReplay.reservation).not.toHaveProperty("settlement_capability_hash");
    expect(reserveReplay).not.toHaveProperty("settlement_capability");

    const snapshot = await within("public snapshot after start", stub.fetch("https://budget/snapshot"));
    const snapshotText = JSON.stringify(await snapshot.json());
    expect(snapshotText).not.toContain(secret);
    expect(snapshotText).not.toContain(persistedHash);
  }, 15_000);

  it("alarm releases a pre-provider reservation with no phantom occupancy", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const reservedResponse = await within(
      "pre-provider reserve",
      post(stub, "/reserve", {
        idempotency_key: "runtime-pre-provider-expiry",
        request_digest: testDigest("runtime-pre-provider-expiry"),
        acquire_lease: true,
        amounts: { model_calls: 2, input_tokens: 40 },
      }),
    );
    expect(reservedResponse.status).toBe(200);
    const reserved = (await reservedResponse.json()) as { lease: { lease_id: string } };

    await within("seed pre-provider expiry", runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      if (!ledger) throw new Error("ledger state missing");
      expect(ledger.reservations["runtime-pre-provider-expiry"].provider_started_at).toBeNull();
      ledger.leases[reserved.lease.lease_id].expires_at = Date.now() - 1;
      await Promise.all([
        state.storage.put("ledger", ledger),
        state.storage.setAlarm(Date.now()),
      ]);
    }));
    await within("run pre-provider alarm", runDurableObjectAlarm(stub));

    const snap = await within("snapshot after pre-provider alarm", stub.fetch("https://budget/snapshot"));
    expect(await snap.json()).toMatchObject({
      frozen: false,
      used: { model_calls: 0, input_tokens: 0 },
      reserved: { model_calls: 0, input_tokens: 0 },
      active_leases: 0,
    });
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      expect(ledger?.reservations["runtime-pre-provider-expiry"].status).toBe("released");
      expect(ledger?.leases[reserved.lease.lease_id].released_at).toEqual(expect.any(Number));
      const active = Object.values(ledger?.reservations ?? {}).filter(
        (row) => row.status === "reserved",
      );
      expect(active).toEqual([]);
    });
  }, 15_000);

  it("public DTO has no sensitive capability fields", () => {
    expectTypeOf<Reservation>().toHaveProperty("reserve_owner_capability_hash");
    expectTypeOf<Reservation>().toHaveProperty("settlement_capability_secret");
    expectTypeOf<Reservation>().toHaveProperty("settlement_capability_hash");
    expectTypeOf<PublicReservation>().not.toHaveProperty("settlement_capability");
    expectTypeOf<PublicReservation>().not.toHaveProperty("reserve_owner_capability");
    expectTypeOf<PublicReservation>().not.toHaveProperty("reserve_owner_capability_hash");
    expectTypeOf<PublicReservation>().not.toHaveProperty("settlement_capability_secret");
    expectTypeOf<PublicReservation>().not.toHaveProperty("settlement_capability_hash");
  });

  it("rejects missing/false acquire_lease on active and reconciled reserve replay", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const reserved = await within(
      "p0 lease reserve",
      rpc.reserve({
        idempotency_key: "runtime-p0-lease",
        request_digest: testDigest("runtime-p0-lease"),
        amounts: { model_calls: 1, input_tokens: 8 },
        acquire_lease: true,
      }),
    );
    expect(reserved.ok).toBe(true);
    const omitted = await within(
      "p0 active omitted lease",
      rpc.reserve({
        idempotency_key: "runtime-p0-lease",
        request_digest: testDigest("runtime-p0-lease"),
        amounts: { model_calls: 1, input_tokens: 8 },
      }),
    );
    const disabled = await within(
      "p0 active false lease",
      rpc.reserve({
        idempotency_key: "runtime-p0-lease",
        request_digest: testDigest("runtime-p0-lease"),
        amounts: { model_calls: 1, input_tokens: 8 },
        acquire_lease: false,
      }),
    );
    expect(omitted).toMatchObject({ ok: false, error: "lease_required" });
    expect(disabled).toMatchObject({ ok: false, error: "lease_required" });
    expect(omitted.reservation).toBeUndefined();
    expect(disabled.reservation).toBeUndefined();

    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-lease",
      lease_id: reserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-lease"),
    });
    expect(started.ok).toBe(true);
    const finalized = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-lease",
      request_digest: testDigest("runtime-p0-lease"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: started.settlement_capability as string,
      usage: actualUsage({ model_calls: 1, input_tokens: 3 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    });
    expect(finalized.ok).toBe(true);
    const reconciledOmitted = await rpc.reserve({
      idempotency_key: "runtime-p0-lease",
      request_digest: testDigest("runtime-p0-lease"),
      amounts: { model_calls: 1, input_tokens: 8 },
    });
    const reconciledFalse = await rpc.reserve({
      idempotency_key: "runtime-p0-lease",
      request_digest: testDigest("runtime-p0-lease"),
      amounts: { model_calls: 1, input_tokens: 8 },
      acquire_lease: false,
    });
    expect(reconciledOmitted).toMatchObject({ ok: false, error: "lease_required" });
    expect(reconciledFalse).toMatchObject({ ok: false, error: "lease_required" });
    expect(JSON.stringify(reconciledOmitted)).not.toMatch(/cached_result|settlement_capability/);
    const exact = await rpc.reserve({
      idempotency_key: "runtime-p0-lease",
      request_digest: testDigest("runtime-p0-lease"),
      amounts: { model_calls: 1, input_tokens: 8 },
      acquire_lease: true,
    });
    expect(exact.ok).toBe(true);
    expect(exact.existing).toBe(true);
  }, 15_000);

  it("rejects nested capability smuggling and never returns secret/hash", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const reserved = await rpc.reserve({
      idempotency_key: "runtime-p0-smuggle",
      request_digest: testDigest("runtime-p0-smuggle"),
      amounts: { model_calls: 1, input_tokens: 8 },
      acquire_lease: true,
    });
    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-smuggle",
      lease_id: reserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-smuggle"),
    });
    const secret = started.settlement_capability as string;
    let hash = "";
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      hash = ledger?.reservations["runtime-p0-smuggle"].settlement_capability_hash ?? "";
    });
    expect(hash).toEqual(expect.any(String));

    const nestedObject = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-smuggle",
      request_digest: testDigest("runtime-p0-smuggle"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: secret,
      usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
      terminal_result: {
        http_status: 200,
        body: {
          ok: true,
          artifact: {
            nested: {
              settlement_capability: secret,
              settlement_capability_hash: hash,
            },
          },
        },
      },
    });
    expect(nestedObject.ok).toBe(false);
    expect(nestedObject.error).toMatch(/cached_result_capability_/);
    expect(nestedObject.reservation).toBeUndefined();

    const nestedArray = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-smuggle",
      request_digest: testDigest("runtime-p0-smuggle"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: secret,
      usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
      terminal_result: {
        http_status: 200,
        body: { ok: true, artifact: [secret, { items: [hash] }] },
      },
    });
    expect(nestedArray.ok).toBe(false);
    expect(nestedArray.error).toMatch(/cached_result_capability_/);

    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      expect(ledger?.reservations["runtime-p0-smuggle"].cached_result).toBeNull();
      expect(ledger?.reservations["runtime-p0-smuggle"].status).toBe("reserved");
    });

    const committed = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-smuggle",
      request_digest: testDigest("runtime-p0-smuggle"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: secret,
      usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
      terminal_result: { http_status: 200, body: { ok: true, artifact: { summary: "safe" } } },
    });
    expect(committed.ok).toBe(true);
    const replay = await rpc.reserve({
      idempotency_key: "runtime-p0-smuggle",
      request_digest: testDigest("runtime-p0-smuggle"),
      amounts: { model_calls: 1, input_tokens: 8 },
      acquire_lease: true,
    });
    const released = await rpc.release({
      idempotency_key: "runtime-p0-smuggle",
      lease_id: reserved.lease!.lease_id,
    });
    for (const payload of [nestedObject, nestedArray, committed, replay, released]) {
      const encoded = JSON.stringify(payload);
      expect(encoded).not.toContain(secret);
      expect(encoded).not.toContain(hash);
    }
  }, 15_000);

  it("rejects capability/hash substrings in nested object and array strings", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const reserved = await rpc.reserve({
      idempotency_key: "runtime-p0-substr",
      request_digest: testDigest("runtime-p0-substr"),
      amounts: { model_calls: 1, input_tokens: 8 },
      acquire_lease: true,
    });
    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-substr",
      lease_id: reserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-substr"),
    });
    const secret = started.settlement_capability as string;
    let hash = "";
    let beforeAmounts: unknown;
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      hash = ledger?.reservations["runtime-p0-substr"].settlement_capability_hash ?? "";
      beforeAmounts = ledger?.reservations["runtime-p0-substr"].amounts;
    });
    expect(hash).toEqual(expect.any(String));
    const snapBefore = (await (
      await stub.fetch("https://budget/snapshot")
    ).json()) as {
      used: unknown;
      reserved: unknown;
      active_leases: number;
      frozen: boolean;
    };

    const wraps: Array<(token: string) => string> = [
      (token) => `${token}=tail`,
      (token) => `secret=${token}`,
      (token) => `pre-${token}-post`,
    ];
    const bodies: Array<Record<string, unknown>> = [];
    for (const wrap of wraps) {
      bodies.push({ ok: true, artifact: { nested: { note: wrap(secret) } } });
      bodies.push({ ok: true, artifact: [{ items: [wrap(secret)] }] });
      bodies.push({ ok: true, artifact: { nested: { digest: wrap(hash) } } });
      bodies.push({ ok: true, artifact: [{ items: [wrap(hash)] }] });
    }

    const denials: unknown[] = [];
    for (const body of bodies) {
      const denied = await rpc.finalizeExact({
        idempotency_key: "runtime-p0-substr",
        request_digest: testDigest("runtime-p0-substr"),
        lease_id: reserved.lease!.lease_id,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        terminal_result: { http_status: 200, body },
      });
      expect(denied.ok).toBe(false);
      expect(denied.error).toMatch(/cached_result_capability_/);
      expect(denied.reservation).toBeUndefined();
      denials.push(denied);

      await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
        const ledger = await state.storage.get<LedgerState>("ledger");
        const row = ledger?.reservations["runtime-p0-substr"];
        expect(row?.cached_result).toBeNull();
        expect(row?.status).toBe("reserved");
        expect(row?.settlement_capability_secret).toBe(secret);
        expect(row?.settlement_capability_consumed).toBe(false);
        expect(row?.lease_id).toBe(reserved.lease!.lease_id);
        expect(row?.amounts).toEqual(beforeAmounts);
      });
    }

    const snapAfterReject = (await (
      await stub.fetch("https://budget/snapshot")
    ).json()) as {
      used: unknown;
      reserved: unknown;
      active_leases: number;
      frozen: boolean;
    };
    expect(snapAfterReject.used).toEqual(snapBefore.used);
    expect(snapAfterReject.reserved).toEqual(snapBefore.reserved);
    expect(snapAfterReject.active_leases).toBe(snapBefore.active_leases);
    expect(snapAfterReject.frozen).toBe(false);

    const benignBody = {
      ok: true,
      artifact: {
        summary: "benign-note",
        notes: ["unrelated-token", "plain-text"],
        nested: { items: ["still-safe", { k: "unchanged" }] },
      },
      model: "safe-model",
    };
    const committed = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-substr",
      request_digest: testDigest("runtime-p0-substr"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: secret,
      usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
      terminal_result: { http_status: 200, body: benignBody },
    });
    expect(committed.ok).toBe(true);
    expect(committed.reservation?.cached_result).toEqual({
      http_status: 200,
      body: benignBody,
    });

    const retry = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-substr",
      request_digest: testDigest("runtime-p0-substr"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: secret,
      usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      terminal_result: { http_status: 200, body: benignBody },
    });
    expect(retry.ok).toBe(true);
    expect(retry.reservation?.actual?.input_tokens).toBe(2);
    expect(retry.reservation?.cached_result).toEqual({
      http_status: 200,
      body: benignBody,
    });

    const replay = await rpc.reserve({
      idempotency_key: "runtime-p0-substr",
      request_digest: testDigest("runtime-p0-substr"),
      amounts: { model_calls: 1, input_tokens: 8 },
      acquire_lease: true,
    });
    expect(replay.ok).toBe(true);
    expect(replay.reservation?.cached_result).toEqual({
      http_status: 200,
      body: benignBody,
    });
    const released = await rpc.release({
      idempotency_key: "runtime-p0-substr",
      lease_id: reserved.lease!.lease_id,
    });
    const snapAfter = await (await stub.fetch("https://budget/snapshot")).json();
    await runInDurableObject(stub, async (_instance: BudgetLedger, state) => {
      const ledger = await state.storage.get<LedgerState>("ledger");
      expect(ledger?.reservations["runtime-p0-substr"].cached_result).toEqual({
        http_status: 200,
        body: benignBody,
      });
    });
    for (const payload of [...denials, committed, retry, replay, released, snapAfter, snapAfterReject]) {
      const encoded = JSON.stringify(payload);
      expect(encoded).not.toContain(secret);
      expect(encoded).not.toContain(hash);
    }
  }, 15_000);

  it("terminal finalize and uncertain replay verify digest/lease/capability", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;

    const reserved = await rpc.reserve({
      idempotency_key: "runtime-p0-finalize",
      request_digest: testDigest("runtime-p0-finalize"),
      amounts: { model_calls: 1, input_tokens: 10 },
      acquire_lease: true,
    });
    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-finalize",
      lease_id: reserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-finalize"),
    });
    const cap = started.settlement_capability as string;
    const first = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-finalize",
      request_digest: testDigest("runtime-p0-finalize"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: cap,
      usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    });
    expect(first.ok).toBe(true);
    const snapBefore = await (await stub.fetch("https://budget/snapshot")).json() as {
      used: { input_tokens: number; model_calls: number };
      reserved: { model_calls: number };
      active_leases: number;
    };

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-p0-finalize",
        request_digest: testDigest("other"),
        lease_id: reserved.lease!.lease_id,
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      }),
    ).toMatchObject({ ok: false, error: "request_digest_mismatch" });
    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-p0-finalize",
        request_digest: "",
        lease_id: reserved.lease!.lease_id,
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      }),
    ).toMatchObject({ ok: false, error: "request_digest required" });
    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-p0-finalize",
        request_digest: testDigest("runtime-p0-finalize"),
        lease_id: "00000000-0000-4000-8000-000000000000",
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      }),
    ).toMatchObject({ ok: false, error: "lease_mismatch" });
    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-p0-finalize",
        request_digest: testDigest("runtime-p0-finalize"),
        lease_id: "",
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      }),
    ).toMatchObject({ ok: false, error: "lease_id required" });
    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-p0-finalize",
        request_digest: testDigest("runtime-p0-finalize"),
        lease_id: reserved.lease!.lease_id,
        settlement_capability: "ff".repeat(32),
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      }),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });
    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-p0-finalize",
        request_digest: testDigest("runtime-p0-finalize"),
        lease_id: reserved.lease!.lease_id,
        settlement_capability: "",
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      }),
    ).toMatchObject({ ok: false, error: "settlement_capability_required" });

    const retry = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-finalize",
      request_digest: testDigest("runtime-p0-finalize"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: cap,
      usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    });
    expect(retry.ok).toBe(true);
    expect(retry.used?.input_tokens).toBe(4);
    expect(retry.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(retry.reservation).not.toHaveProperty("settlement_capability_hash");
    const snapAfter = await (await stub.fetch("https://budget/snapshot")).json() as {
      used: { input_tokens: number; model_calls: number };
      reserved: { model_calls: number };
      active_leases: number;
    };
    expect(snapAfter.used).toEqual(snapBefore.used);
    expect(snapAfter.reserved.model_calls).toBe(0);
    expect(snapAfter.active_leases).toBe(0);
    expect(JSON.stringify(retry)).not.toContain(cap);

    const uncertainReserved = await rpc.reserve({
      idempotency_key: "runtime-p0-uncertain",
      request_digest: testDigest("runtime-p0-uncertain"),
      amounts: { model_calls: 1, input_tokens: 11 },
      acquire_lease: true,
    });
    const uncertainStarted = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-uncertain",
      lease_id: uncertainReserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-uncertain"),
    });
    const uncertainCap = uncertainStarted.settlement_capability as string;
    const uncertainFirst = await rpc.settleUncertain({
      idempotency_key: "runtime-p0-uncertain",
      reason: "timeout",
      request_digest: testDigest("runtime-p0-uncertain"),
      lease_id: uncertainReserved.lease!.lease_id,
      settlement_capability: uncertainCap,
    });
    expect(uncertainFirst.ok).toBe(true);
    expect(
      await rpc.settleUncertain({
        idempotency_key: "runtime-p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("other"),
        lease_id: uncertainReserved.lease!.lease_id,
        settlement_capability: uncertainCap,
      }),
    ).toMatchObject({ ok: false, error: "request_digest_mismatch" });
    expect(
      await rpc.settleUncertain({
        idempotency_key: "runtime-p0-uncertain",
        reason: "timeout",
        lease_id: uncertainReserved.lease!.lease_id,
        settlement_capability: uncertainCap,
      }),
    ).toMatchObject({ ok: false, error: "request_digest required" });
    expect(
      await rpc.settleUncertain({
        idempotency_key: "runtime-p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("runtime-p0-uncertain"),
        lease_id: "00000000-0000-4000-8000-000000000000",
        settlement_capability: uncertainCap,
      }),
    ).toMatchObject({ ok: false, error: "lease_mismatch" });
    expect(
      await rpc.settleUncertain({
        idempotency_key: "runtime-p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("runtime-p0-uncertain"),
        settlement_capability: uncertainCap,
      }),
    ).toMatchObject({ ok: false, error: "lease_id required" });
    expect(
      await rpc.settleUncertain({
        idempotency_key: "runtime-p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("runtime-p0-uncertain"),
        lease_id: uncertainReserved.lease!.lease_id,
        settlement_capability: "aa".repeat(32),
      }),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });
    expect(
      await rpc.settleUncertain({
        idempotency_key: "runtime-p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("runtime-p0-uncertain"),
        lease_id: uncertainReserved.lease!.lease_id,
      }),
    ).toMatchObject({ ok: false, error: "settlement_capability_required" });
    const uncertainRetry = await rpc.settleUncertain({
      idempotency_key: "runtime-p0-uncertain",
      reason: "timeout",
      request_digest: testDigest("runtime-p0-uncertain"),
      lease_id: uncertainReserved.lease!.lease_id,
      settlement_capability: uncertainCap,
    });
    expect(uncertainRetry.ok).toBe(true);
    expect(
      (uncertainRetry.reservation as { actual?: { input_tokens?: number } } | undefined)?.actual
        ?.input_tokens,
    ).toBe(11);
    expect(uncertainRetry.used?.input_tokens).toBe(15);
    expect(JSON.stringify(uncertainRetry)).not.toContain(uncertainCap);
  }, 15_000);

  it("lost mark-start recovers capability only through exact retry then finalize", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const reserved = await rpc.reserve({
      idempotency_key: "runtime-p0-lost-start",
      request_digest: testDigest("runtime-p0-lost-start"),
      amounts: { model_calls: 1, input_tokens: 6 },
      acquire_lease: true,
    });
    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-lost-start",
      lease_id: reserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-lost-start"),
    });
    const secret = started.settlement_capability as string;
    await within("evict p0 lost-start", evictDurableObject(stub));
    const viaReserve = await rpc.reserve({
      idempotency_key: "runtime-p0-lost-start",
      request_digest: testDigest("runtime-p0-lost-start"),
      amounts: { model_calls: 1, input_tokens: 6 },
      acquire_lease: true,
    });
    expect(viaReserve).not.toHaveProperty("settlement_capability");
    expect(JSON.stringify(viaReserve)).not.toContain(secret);
    const retried = await rpc.markProviderStarted({
      idempotency_key: "runtime-p0-lost-start",
      lease_id: reserved.lease!.lease_id,
      request_digest: testDigest("runtime-p0-lost-start"),
    });
    expect(retried.settlement_capability).toBe(secret);
    const finalized = await rpc.finalizeExact({
      idempotency_key: "runtime-p0-lost-start",
      request_digest: testDigest("runtime-p0-lost-start"),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: retried.settlement_capability as string,
      usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    });
    expect(finalized.ok).toBe(true);
    expect(finalized.used?.input_tokens).toBe(2);
  }, 15_000);

  it("atomically mints one capability per run and preserves two concurrent finalizations", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const keys = ["runtime-atomic-a", "runtime-atomic-b"];
    const reservations = await Promise.all(keys.map((key, index) => rpc.reserve({
      idempotency_key: key,
      request_digest: testDigest(key),
      amounts: { model_calls: 1, input_tokens: 20 + index },
      acquire_lease: true,
    })));
    const starts = await Promise.all(reservations.flatMap((reservation, index) => [0, 1].map(() =>
      rpc.markProviderStarted({
        idempotency_key: keys[index],
        request_digest: testDigest(keys[index]),
        lease_id: reservation.lease!.lease_id,
      }),
    )));
    expect(starts.every((result) => result.ok)).toBe(true);
    expect(new Set(starts.slice(0, 2).map((result) => result.settlement_capability)).size).toBe(1);
    expect(new Set(starts.slice(2).map((result) => result.settlement_capability)).size).toBe(1);

    const finalized = await Promise.all(reservations.map((reservation, index) =>
      rpc.finalizeExact({
        idempotency_key: keys[index],
        request_digest: testDigest(keys[index]),
        lease_id: reservation.lease!.lease_id,
        settlement_capability: starts[index * 2].settlement_capability as string,
        usage: actualUsage({ model_calls: 1, input_tokens: 5 + index }),
        terminal_result: { http_status: 200, body: { ok: true } },
      }),
    ));
    expect(finalized.every((result) => result.ok)).toBe(true);
    expect(await (await stub.fetch("https://budget/snapshot")).json()).toMatchObject({
      used: { model_calls: 2, input_tokens: 11 },
      reserved: { model_calls: 0, input_tokens: 0 },
      active_leases: 0,
    });
  }, 15_000);

  it("serializes exact and uncertain settlement of the same provider call", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const rpc = stub as BudgetLedgerRpcStub;
    const key = "runtime-terminal-race";
    const reserved = await rpc.reserve({
      idempotency_key: key,
      request_digest: testDigest(key),
      amounts: { model_calls: 1, input_tokens: 40 },
      acquire_lease: true,
    });
    const started = await rpc.markProviderStarted({
      idempotency_key: key,
      request_digest: testDigest(key),
      lease_id: reserved.lease!.lease_id,
    });
    const authority = {
      idempotency_key: key,
      request_digest: testDigest(key),
      lease_id: reserved.lease!.lease_id,
      settlement_capability: started.settlement_capability as string,
    };
    const [exact, uncertain] = await Promise.all([
      rpc.finalizeExact({
        ...authority,
        usage: actualUsage({ model_calls: 1, input_tokens: 7 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      }),
      rpc.settleUncertain({ ...authority, reason: "timeout" }),
    ]);
    const snapshot = await (await stub.fetch("https://budget/snapshot")).json() as {
      used: { input_tokens: number };
      reserved: { input_tokens: number };
      active_leases: number;
      frozen: boolean;
    };
    expect(uncertain.ok).toBe(true);
    expect(uncertain.used?.input_tokens).toBe(snapshot.used.input_tokens);
    if (exact.ok) expect(exact.used?.input_tokens).toBe(snapshot.used.input_tokens);
    else expect(exact.error).toBe("provider_usage_uncertain");
    expect([7, 40]).toContain(snapshot.used.input_tokens);
    expect(snapshot.reserved.input_tokens).toBe(0);
    expect(snapshot.active_leases).toBe(0);
    expect(snapshot.frozen).toBe(snapshot.used.input_tokens === 40);
  }, 15_000);

  it("charges the reserved maximum and freezes on non-numeric provider usage", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    for (const [label, malformed] of [
      ["false", false],
      ["null", null],
      ["string", "3"],
      ["nan", Number.NaN],
      ["infinity", Number.POSITIVE_INFINITY],
    ] as const) {
      const stub = namespace.get(namespace.idFromName(`strict-usage-${label}`));
      const rpc = stub as BudgetLedgerRpcStub;
      const key = `strict-usage-${label}`;
      const reserved = await rpc.reserve({
        idempotency_key: key,
        request_digest: testDigest(key),
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      });
      const started = await rpc.markProviderStarted({
        idempotency_key: key,
        request_digest: testDigest(key),
        lease_id: reserved.lease!.lease_id,
      });
      expect(await rpc.finalizeExact({
        idempotency_key: key,
        request_digest: testDigest(key),
        lease_id: reserved.lease!.lease_id,
        settlement_capability: started.settlement_capability as string,
        usage: actualUsage({ model_calls: 1, input_tokens: malformed }),
        terminal_result: { http_status: 200, body: { ok: true } },
      })).toMatchObject({ ok: false, error: "provider_usage_invalid" });
      expect(await (await stub.fetch("https://budget/snapshot")).json()).toMatchObject({
        used: { model_calls: 1, input_tokens: 10 },
        reserved: { model_calls: 0, input_tokens: 0 },
        active_leases: 0,
        frozen: true,
      });
    }
  }, 15_000);

  it("rejects cached reservation overclaim before uncertain full-reservation charge", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName("cached-reservation-subset"));
    const rpc = stub as BudgetLedgerRpcStub;

    expect(await rpc.reserve({
      idempotency_key: "runtime-cached-overclaim",
      request_digest: testDigest("runtime-cached-overclaim"),
      amounts: { model_calls: 1, input_tokens: 4, cached_tokens: 5 },
      acquire_lease: true,
    })).toEqual({
      ok: false,
      error: "cached_tokens must be a subset of input_tokens",
    });

    const key = "runtime-cached-persisted-overclaim";
    const digest = testDigest(key);
    const reserved = await rpc.reserve({
      idempotency_key: key,
      request_digest: digest,
      amounts: { model_calls: 1, input_tokens: 4, cached_tokens: 4 },
      acquire_lease: true,
    });
    const started = await rpc.markProviderStarted({
      idempotency_key: key,
      request_digest: digest,
      lease_id: reserved.lease!.lease_id,
    });

    const settled = await rpc.settleUncertain({
      idempotency_key: key,
      request_digest: digest,
      lease_id: reserved.lease!.lease_id,
      settlement_capability: started.settlement_capability as string,
      reason: "provider_error",
    });
    expect(settled).toMatchObject({
      ok: true,
      used: { input_tokens: 4, model_calls: 1 },
      reservation: { actual: { input_tokens: 4, cached_tokens: 4 } },
    });
    expect(await (await stub.fetch("https://budget/snapshot")).json()).toMatchObject({
      used: { input_tokens: 4, cached_tokens: 4 },
      reserved: { input_tokens: 0, cached_tokens: 0 },
    });
  }, 15_000);

  it("charges the reserved maximum for missing, unknown, or non-unit actual usage", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const variants: Array<[string, Record<string, unknown>]> = [
      ["empty", {}],
      [
        "missing-cost",
        {
          model_calls: 1,
          input_tokens: 1,
          output_tokens: 1,
          cached_tokens: 0,
        },
      ],
      ["unknown", actualUsage({ unexpected: 1 })],
      ["model-calls-zero", actualUsage({ model_calls: 0 })],
      ["model-calls-two", actualUsage({ model_calls: 2 })],
      ["cached-outside-input", actualUsage({ input_tokens: 4, cached_tokens: 5 })],
    ];
    for (const [label, usage] of variants) {
      const stub = namespace.get(namespace.idFromName(`closed-usage-${label}`));
      const rpc = stub as BudgetLedgerRpcStub;
      const key = `closed-usage-${label}`;
      const reserved = await rpc.reserve({
        idempotency_key: key,
        request_digest: testDigest(key),
        amounts: {
          model_calls: 1,
          input_tokens: 10,
          output_tokens: 4,
          cached_tokens: 10,
          cost_usd: 0.5,
        },
        acquire_lease: true,
      });
      const started = await rpc.markProviderStarted({
        idempotency_key: key,
        request_digest: testDigest(key),
        lease_id: reserved.lease!.lease_id,
      });
      expect(await rpc.finalizeExact({
        idempotency_key: key,
        request_digest: testDigest(key),
        lease_id: reserved.lease!.lease_id,
        settlement_capability: started.settlement_capability as string,
        usage,
        terminal_result: { http_status: 200, body: { ok: true } },
      })).toMatchObject({ ok: false, error: "provider_usage_invalid" });
      expect(await (await stub.fetch("https://budget/snapshot")).json()).toMatchObject({
        used: {
          model_calls: 1,
          input_tokens: 10,
          output_tokens: 4,
          cached_tokens: 10,
          cost_usd: 0.5,
        },
        reserved: {
          model_calls: 0,
          input_tokens: 0,
          output_tokens: 0,
          cached_tokens: 0,
          cost_usd: 0,
        },
        active_leases: 0,
        frozen: true,
      });
    }
  }, 15_000);
});
