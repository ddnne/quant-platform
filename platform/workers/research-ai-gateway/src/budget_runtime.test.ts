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
    const successfulKeys = idempotencyKeys.filter(
      (_key, index) => attempts[index].status === 200,
    );
    await Promise.all(attempts.map((response) => response.text()));

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

    for (const idempotencyKey of successfulKeys) {
      const finalized = await post(stub, "/finalize", {
        idempotency_key: idempotencyKey,
        amounts: { model_calls: 1, input_tokens: 7, output_tokens: 3 },
        settlement: {
          outcome: "success",
          usage_source: "provider",
          estimated_cost_usd: 0.1,
          actual_cost_usd: 0.05,
          billed_cost_usd: 0.05,
          actual_input_tokens: 7,
          actual_output_tokens: 3,
          actual_cached_tokens: 0,
        },
      });
      expect(finalized.status).toBe(200);
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
    const started = await within("provider marker", post(stub, "/provider-started", {
      idempotency_key: "runtime-uncertain",
      lease_id: reserved.lease.lease_id,
    }));
    expect(started.status).toBe(200);

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
    const started = await within("restart provider marker", post(stub, "/provider-started", {
      idempotency_key: "runtime-restart-uncertain",
      lease_id: reserved.lease.lease_id,
    }));
    expect(started.status).toBe(200);
    await started.text();

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
    });
  }, 15_000);
});
