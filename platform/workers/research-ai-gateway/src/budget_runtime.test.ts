import { env, exports as workerExports } from "cloudflare:workers";
import { afterEach, describe, expect, it } from "vitest";
import {
  evictDurableObject,
  reset,
  runDurableObjectAlarm,
  runInDurableObject,
} from "cloudflare:test";
import { CONTROL_PLANE_LEDGER_NAME, type LedgerState } from "./budget_do";
import { BudgetLedger } from "./budget_http";
import type { GatewayEnv } from "./index";

const runtimeEnv = env as GatewayEnv;

async function within<T>(stage: string, promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error(`runtime stage timed out: ${stage}`)),
          2_000,
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

type BudgetLedgerRpcStub = DurableObjectStub & {
  markProviderStarted(input: {
    idempotency_key: string;
    lease_id: string;
    request_digest?: string;
  }): Promise<{
    ok: boolean;
    error?: string;
    settlement_capability?: string | null;
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
    reservation?: { actual?: { input_tokens?: number } };
    used?: { input_tokens?: number };
  }>;
};

afterEach(async () => {
  await reset();
});

describe("BudgetLedger in the Workers runtime", () => {
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
          request_digest: `digest-${idempotencyKey}`,
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
        request_digest: `digest-${row.idempotencyKey}`,
      });
      expect(started.ok).toBe(true);
      expect(started.settlement_capability).toEqual(expect.any(String));
      const finalized = await rpc.finalizeExact({
        idempotency_key: row.idempotencyKey,
        request_digest: `digest-${row.idempotencyKey}`,
        lease_id: row.leaseId,
        settlement_capability: started.settlement_capability as string,
        usage: { model_calls: 1, input_tokens: 7, output_tokens: 3 },
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
  }, 15_000);

  it("alarm conservatively settles provider-started expiry", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const reservedResponse = await within("uncertain reserve", post(stub, "/reserve", {
      idempotency_key: "runtime-uncertain",
      request_digest: "digest-runtime-uncertain",
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
        request_digest: "digest-runtime-uncertain",
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
      request_digest: "digest-runtime-restart-uncertain",
      acquire_lease: true,
      amounts: { model_calls: 1, input_tokens: 70, output_tokens: 7, cached_tokens: 70 },
    }));
    const reserved = (await reservedResponse.json()) as { lease: { lease_id: string } };
    const started = await within(
      "restart provider marker",
      (stub as BudgetLedgerRpcStub).markProviderStarted({
        idempotency_key: "runtime-restart-uncertain",
        lease_id: reserved.lease.lease_id,
        request_digest: "digest-runtime-restart-uncertain",
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
    });
  }, 15_000);

  it("direct HTTP finalize, reconcile, provider-start, and mint are not settlement authority", async () => {
    const namespace = runtimeEnv.BUDGET_LEDGER;
    if (!namespace) throw new Error("BUDGET_LEDGER test binding missing");
    const stub = namespace.get(namespace.idFromName(CONTROL_PLANE_LEDGER_NAME));
    const reservedResponse = await post(stub, "/reserve", {
      idempotency_key: "runtime-http-bypass",
      request_digest: "digest-runtime-http-bypass",
      acquire_lease: true,
      amounts: { model_calls: 1, cost_usd: 1 },
    });
    expect(reservedResponse.status).toBe(200);
    await reservedResponse.text();
    for (const path of [
      "/finalize",
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
      request_digest: "digest-runtime-rpc-auth",
      acquire_lease: true,
      amounts: { model_calls: 1, input_tokens: 20 },
    });
    const reserved = (await reservedResponse.json()) as { lease: { lease_id: string } };
    const unstarted = await rpc.finalizeExact({
      idempotency_key: "runtime-rpc-auth",
      request_digest: "digest-runtime-rpc-auth",
      lease_id: reserved.lease.lease_id,
      settlement_capability: "aa".repeat(32),
      usage: { model_calls: 0, input_tokens: 0 },
    });
    expect(unstarted).toMatchObject({ ok: false, error: "provider_not_started" });

    const started = await rpc.markProviderStarted({
      idempotency_key: "runtime-rpc-auth",
      lease_id: reserved.lease.lease_id,
      request_digest: "digest-runtime-rpc-auth",
    });
    expect(started.ok).toBe(true);
    const cap = started.settlement_capability as string;

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-rpc-auth",
        request_digest: "digest-runtime-rpc-auth",
        lease_id: reserved.lease.lease_id,
        settlement_capability: "ff".repeat(32),
        usage: { model_calls: 1, input_tokens: 4 },
      }),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-rpc-auth",
        request_digest: "digest-other",
        lease_id: reserved.lease.lease_id,
        settlement_capability: cap,
        usage: { model_calls: 1, input_tokens: 4 },
      }),
    ).toMatchObject({ ok: false, error: "request_digest_mismatch" });

    expect(
      await rpc.finalizeExact({
        idempotency_key: "runtime-rpc-auth",
        request_digest: "digest-runtime-rpc-auth",
        lease_id: reserved.lease.lease_id,
        settlement_capability: cap,
        usage: { model_calls: 1, input_tokens: 4 },
        amounts: { model_calls: 0 },
        result: { http_status: 200, body: { ok: true } },
        settlement: { outcome: "success" },
      }),
    ).toMatchObject({ ok: false, error: "caller_settlement_rejected" });

    const committed = await rpc.finalizeExact({
      idempotency_key: "runtime-rpc-auth",
      request_digest: "digest-runtime-rpc-auth",
      lease_id: reserved.lease.lease_id,
      settlement_capability: cap,
      usage: { model_calls: 1, input_tokens: 6 },
      terminal_result: { http_status: 200, body: { ok: true } },
    });
    expect(committed.ok).toBe(true);
    const replay = await rpc.finalizeExact({
      idempotency_key: "runtime-rpc-auth",
      request_digest: "digest-runtime-rpc-auth",
      lease_id: reserved.lease.lease_id,
      settlement_capability: cap,
      usage: { model_calls: 1, input_tokens: 99 },
    });
    expect(replay.ok).toBe(true);
    expect(replay.used?.input_tokens).toBe(6);
  }, 15_000);
});
