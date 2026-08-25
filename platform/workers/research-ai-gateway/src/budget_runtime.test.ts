import { env, exports as workerExports } from "cloudflare:workers";
import { afterEach, describe, expect, it } from "vitest";
import { evictDurableObject, reset } from "cloudflare:test";
import { CONTROL_PLANE_LEDGER_NAME } from "./budget_do";
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
});
