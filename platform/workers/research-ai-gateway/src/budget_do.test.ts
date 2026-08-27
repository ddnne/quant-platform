import { describe, expect, expectTypeOf, it } from "vitest";
import {
  PILOT_BUDGET_CAPS,
  CONTROL_PLANE_LEDGER_NAME,
  MemoryBudgetStorage,
  MAX_IDEMPOTENCY_KEY_BYTES,
  MAX_MUTABLE_LEDGER_STATE_BYTES,
  MAX_OWNER_CANCELLATION_TOMBSTONES,
  MAX_SERIALIZED_LEDGER_STATE_BYTES,
  OWNER_CANCELLATION_QUARANTINE_HEADROOM_BYTES,
  OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
  bindIdempotencyKey,
  cancelPreProviderReservation,
  createBudget,
  finalizeBudget,
  heartbeatLease,
  markProviderStarted,
  recoverExpiredLeases,
  releaseBudget,
  reserveBudget,
  reserveOwnedBudget,
  settleUncertainBudget,
  snapshotBudget,
  zeroCounters,
  type PublicReservation,
  type Reservation,
} from "./budget_do";
import {
  AI_GATEWAY_PRICING_POLICY_DIGEST,
  AI_GATEWAY_PRICING_POLICY_ID,
} from "./pricing_policy";

/** In-memory ledger algebra. Live Cloudflare Durable Object occupancy is unproven. */

const T0 = 1_700_000_000_000;
const OWNER_A = "a".repeat(64);
const OWNER_B = "b".repeat(64);

function testDigest(label: string): string {
  const seed = Array.from(
    new TextEncoder().encode(label),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("") || "0";
  return seed.repeat(Math.ceil(64 / seed.length)).slice(0, 64);
}

function leased(
  idempotency_key: string,
  amounts: unknown,
  request_digest = testDigest(idempotency_key),
): {
  idempotency_key: string;
  request_digest: string;
  amounts: unknown;
  acquire_lease: true;
} {
  return { idempotency_key, request_digest, amounts, acquire_lease: true };
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

async function fillOwnerCancellationTombstoneCapacity(
  storage: MemoryBudgetStorage,
  createdAt: number,
): Promise<void> {
  const state = await storage.get<Record<string, any>>("ledger");
  if (!state) throw new Error("ledger");
  state.owner_cancellation_tombstones = Object.fromEntries(
    Array.from({ length: MAX_OWNER_CANCELLATION_TOMBSTONES }, (_, index) => {
      const ownerHash = index.toString(16).padStart(64, "0");
      const suffix = `-${index}`;
      return [
        ownerHash,
        {
          owner_capability_hash: ownerHash,
          idempotency_key:
            "i".repeat(MAX_IDEMPOTENCY_KEY_BYTES - suffix.length) + suffix,
          request_digest: testDigest(`capacity-${index}`),
          created_at: createdAt,
          expires_at: createdAt + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
        },
      ];
    }),
  );
  await storage.commit(
    "ledger",
    state,
    createdAt + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
  );
  const persisted = await storage.get("ledger");
  const bytes = new TextEncoder().encode(JSON.stringify(persisted)).byteLength;
  expect(bytes).toBeLessThanOrEqual(MAX_MUTABLE_LEDGER_STATE_BYTES);
}

describe("PILOT_BUDGET_CAPS", () => {
  it("is the pilot hard cap set", () => {
    expect(PILOT_BUDGET_CAPS).toEqual({
      max_experiment_plans: 4,
      max_parallel_experiments: 2,
      max_generations: 1,
      max_model_calls: 16,
      max_input_tokens: 400_000,
      max_output_tokens: 80_000,
      max_cached_tokens: 400_000,
      max_paper_runs: 8,
      max_cost_usd: 20,
      lease_ttl_seconds: 1800,
      auto_promotion: false,
    });
  });

  it("keeps the transitional whole-state value below the platform ceiling", () => {
    expect(MAX_OWNER_CANCELLATION_TOMBSTONES).toBe(512);
    expect(OWNER_CANCELLATION_QUARANTINE_HEADROOM_BYTES).toBeGreaterThanOrEqual(
      16 * 1024,
    );
    expect(MAX_MUTABLE_LEDGER_STATE_BYTES).toBe(
      MAX_SERIALIZED_LEDGER_STATE_BYTES -
        OWNER_CANCELLATION_QUARANTINE_HEADROOM_BYTES,
    );
    expect(MAX_SERIALIZED_LEDGER_STATE_BYTES).toBeLessThanOrEqual(1_572_864);
  });
});

describe("budget ledger algebra", () => {
  it("create is idempotent and never auto-promotes", async () => {
    const storage = new MemoryBudgetStorage();
    const first = await createBudget(storage, T0);
    const second = await createBudget(storage, T0 + 1);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    if (first.ok && second.ok) {
      expect(first.created).toBe(true);
      expect(second.created).toBe(false);
      expect(first.caps.auto_promotion).toBe(false);
    }
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (snap.ok) expect(snap.auto_promotion).toBe(false);
  });

  it("created ledger has zero occupancy; budget_id presence is not a reserve", async () => {
    const storage = new MemoryBudgetStorage();
    const created = await createBudget(storage, T0);
    expect(created.ok).toBe(true);
    const before = await snapshotBudget(storage, T0);
    expect(before.ok).toBe(true);
    if (before.ok) {
      expect(before.created).toBe(true);
      expect(before.reserved).toEqual(zeroCounters());
      expect(before.used).toEqual(zeroCounters());
      expect(before.active_leases).toBe(0);
    }
    const reserved = await reserveBudget(
      storage,
      leased("k-create-not-grant", { model_calls: 1 }),
      T0,
    );
    expect(reserved.ok).toBe(true);
    const after = await snapshotBudget(storage, T0);
    expect(after.ok).toBe(true);
    if (after.ok) {
      expect(after.reserved.model_calls).toBe(1);
      expect(after.used.model_calls).toBe(0);
    }
  });

  it("reserve fails closed when insufficient and does not mutate counters", async () => {
    const storage = new MemoryBudgetStorage();
    const fill = await reserveBudget(
      storage,
      leased("fill", { model_calls: 16 }),
      T0,
    );
    expect(fill.ok).toBe(true);
    const denied = await reserveBudget(
      storage,
      leased("next", { model_calls: 1 }),
      T0,
    );
    expect(denied.ok).toBe(false);
    if (!denied.ok) expect(denied.error).toBe("budget_exhausted");
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved.model_calls).toBe(16);
      expect(snap.used.model_calls).toBe(0);
    }
  });

  it("rejects cached reservation overclaim and malformed persisted uncertain charge", async () => {
    const storage = new MemoryBudgetStorage();
    const invalid = await reserveBudget(
      storage,
      leased("cached-reserve-overclaim", {
        model_calls: 1,
        input_tokens: 4,
        cached_tokens: 5,
      }),
      T0,
    );
    expect(invalid).toEqual({
      ok: false,
      error: "cached_tokens must be a subset of input_tokens",
    });
    expect(await snapshotBudget(storage, T0)).toMatchObject({
      ok: true,
      used: { model_calls: 0, input_tokens: 0, cached_tokens: 0 },
      reserved: { model_calls: 0, input_tokens: 0, cached_tokens: 0 },
    });

    const digest = testDigest("cached-persisted-overclaim");
    const reserved = await reserveBudget(
      storage,
      leased(
        "cached-persisted-overclaim",
        {
          model_calls: 1,
          input_tokens: 4,
          cached_tokens: 4,
        },
        digest,
      ),
      T0 + 1,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "cached-persisted-overclaim",
        request_digest: digest,
        lease_id: reserved.lease.lease_id,
      },
      T0 + 2,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("start");

    const persisted = await storage.get<Record<string, any>>("ledger");
    if (!persisted) throw new Error("ledger");
    persisted.reservations["cached-persisted-overclaim"].amounts.cached_tokens = 5;
    persisted.reserved.cached_tokens = 5;
    await storage.commit("ledger", persisted, null);

    await expect(
      settleUncertainBudget(
        storage,
        {
          idempotency_key: "cached-persisted-overclaim",
          request_digest: digest,
          lease_id: reserved.lease.lease_id,
          settlement_capability: started.settlement_capability,
          reason: "provider_error",
        },
        T0 + 3,
      ),
    ).rejects.toThrow(
      /persisted_budget_state_invalid:ledger\.reserved:cached_tokens_not_input_subset/,
    );
  });

  it("same idempotency key returns the same reservation without double-spend", async () => {
    const storage = new MemoryBudgetStorage();
    const a = await reserveBudget(
      storage,
      leased("k1", { model_calls: 1, input_tokens: 10 }),
      T0,
    );
    const b = await reserveBudget(
      storage,
      leased("k1", { model_calls: 1, input_tokens: 10 }),
      T0 + 5,
    );
    expect(a.ok && b.ok).toBe(true);
    if (a.ok && b.ok) {
      expect(b.existing).toBe(true);
      expect(b.reservation.reservation_id).toBe(a.reservation.reservation_id);
    }
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (snap.ok) expect(snap.reserved.model_calls).toBe(1);
  });

  it("exact finalize is idempotent and converts reserved into used", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "k1",
        request_digest: testDigest("k1"),
        amounts: { model_calls: 1, input_tokens: 40, output_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "k1",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("k1"),
      },
      T0 + 1,
    );
    expect(started.ok).toBe(true);
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const first = await finalizeBudget(
      storage,
      {
        idempotency_key: "k1",
        request_digest: testDigest("k1"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 12, output_tokens: 7 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 2,
    );
    const second = await finalizeBudget(
      storage,
      {
        idempotency_key: "k1",
        request_digest: testDigest("k1"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 99, output_tokens: 99 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 3,
    );
    expect(first.ok && second.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 4);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.used.model_calls).toBe(1);
      expect(snap.used.input_tokens).toBe(12);
      expect(snap.used.output_tokens).toBe(7);
      expect(snap.reserved.model_calls).toBe(0);
    }
  });

  it.each([
    [
      "missing policy identity",
      {
        cost_source: "pricing_policy_estimate",
        provider_model: "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        pricing_policy_id: null,
        pricing_policy_digest: null,
        input_tokens: 1_000,
        cost_usd: 0.0003,
      },
    ],
    [
      "wrong canonical policy cost",
      {
        cost_source: "pricing_policy_estimate",
        provider_model: "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        pricing_policy_id: AI_GATEWAY_PRICING_POLICY_ID,
        pricing_policy_digest: AI_GATEWAY_PRICING_POLICY_DIGEST,
        input_tokens: 1_000,
        cost_usd: 0.25,
      },
    ],
    [
      "policy metadata on provider cost",
      {
        cost_source: "provider",
        pricing_policy_id: AI_GATEWAY_PRICING_POLICY_ID,
        pricing_policy_digest: AI_GATEWAY_PRICING_POLICY_DIGEST,
      },
    ],
    [
      "cached tokens outside input tokens",
      { input_tokens: 4, cached_tokens: 5 },
    ],
  ])("fails closed for %s usage provenance", async (_label, overrides) => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("usage-provenance", {
        model_calls: 1,
        input_tokens: 2_000,
        output_tokens: 10,
        cost_usd: 1,
      }),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "usage-provenance",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("usage-provenance"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("capability");
    const finalized = await finalizeBudget(
      storage,
      {
        idempotency_key: "usage-provenance",
        request_digest: testDigest("usage-provenance"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage(overrides),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 2,
    );
    expect(finalized).toMatchObject({ ok: false, error: "provider_usage_invalid" });
    const snapshot = await snapshotBudget(storage, T0 + 3);
    expect(snapshot).toMatchObject({
      ok: true,
      frozen: true,
      reserved: { model_calls: 0 },
      used: { model_calls: 1, input_tokens: 2_000, cost_usd: 1 },
    });
  });

  it("atomically caps concurrent leases at max_parallel_experiments=2", async () => {
    const storage = new MemoryBudgetStorage();
    const attempts = await Promise.all(
      ["l1", "l2", "l3"].map((key) =>
        reserveBudget(storage, leased(key, { model_calls: 1 }), T0),
      ),
    );
    const accepted = attempts.filter((result) => result.ok);
    const rejected = attempts.filter((result) => !result.ok);
    expect(accepted).toHaveLength(2);
    expect(rejected).toHaveLength(1);
    expect(rejected[0]).toMatchObject({
      ok: false,
      error: "budget_exhausted",
      detail: expect.stringContaining("concurrent_experiments"),
    });
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.active_leases).toBe(2);
      expect(snap.reserved.model_calls).toBe(2);
    }
  });

  it("heartbeat extends TTL by 1800s", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("hb", { model_calls: 1 }),
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    expect(reserved.lease.expires_at).toBe(T0 + 1800 * 1000);
    const beat = await heartbeatLease(storage, reserved.lease.lease_id, T0 + 60_000);
    expect(beat.ok).toBe(true);
    if (beat.ok) {
      expect(beat.lease.last_heartbeat_at).toBe(T0 + 60_000);
      expect(beat.lease.expires_at).toBe(T0 + 60_000 + 1800 * 1000);
    }
  });

  it("release frees reserved capacity and the lease slot", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("rel", { model_calls: 4 }),
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const released = await releaseBudget(
      storage,
      { lease_id: reserved.lease.lease_id, idempotency_key: "rel" },
      T0 + 1,
    );
    expect(released.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 1);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved.model_calls).toBe(0);
      expect(snap.active_leases).toBe(0);
    }
  });

  it("allows a same-digest retry only after a pre-provider release", async () => {
    const storage = new MemoryBudgetStorage();
    const first = await reserveBudget(
      storage,
      {
        idempotency_key: "retry-pre-provider",
        request_digest: testDigest("retry"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0,
    );
    if (!first.ok || !first.lease) throw new Error("lease");
    await releaseBudget(
      storage,
      {
        idempotency_key: "retry-pre-provider",
        lease_id: first.lease.lease_id,
      },
      T0 + 1,
    );
    const retry = await reserveBudget(
      storage,
      {
        idempotency_key: "retry-pre-provider",
        request_digest: testDigest("retry"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0 + 2,
    );
    expect(retry.ok).toBe(true);
    if (retry.ok) {
      expect(retry.existing).toBe(false);
      expect(retry.budget_run_id).not.toBe(first.budget_run_id);
    }
  });

  it("rejects a mismatched lease and reservation key without releasing either", async () => {
    const storage = new MemoryBudgetStorage();
    const first = await reserveBudget(
      storage,
      leased("mismatch-a", { model_calls: 1 }),
      T0,
    );
    const second = await reserveBudget(
      storage,
      leased("mismatch-b", { model_calls: 1 }),
      T0,
    );
    if (!first.ok || !first.lease || !second.ok) throw new Error("leases");
    const mismatch = await releaseBudget(
      storage,
      { idempotency_key: "mismatch-b", lease_id: first.lease.lease_id },
      T0 + 1,
    );
    expect(mismatch).toMatchObject({ ok: false, error: "lease_reservation_mismatch" });
    const snap = await snapshotBudget(storage, T0 + 2);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.reserved.model_calls).toBe(2);
    expect(snap.active_leases).toBe(2);
  });

  it("expired lease recovery returns capacity before a later reserve", async () => {
    const storage = new MemoryBudgetStorage();
    const first = await reserveBudget(
      storage,
      leased("old", { model_calls: 8 }),
      T0,
    );
    expect(first.ok).toBe(true);
    const recovered = await recoverExpiredLeases(storage, T0 + 1800 * 1000 + 1);
    expect(recovered.ok).toBe(true);
    if (recovered.ok) expect(recovered.recovered).toBe(1);
    const again = await reserveBudget(
      storage,
      leased("new", { model_calls: 8 }),
      T0 + 1800 * 1000 + 2,
    );
    expect(again.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 1800 * 1000 + 2);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved.model_calls).toBe(8);
      expect(snap.active_leases).toBe(1);
    }
  });

  it("charges the reserved maximum and freezes when a provider-started lease expires", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "uncertain-expiry",
        request_digest: testDigest("uncertain-expiry"),
        amounts: {
          model_calls: 1,
          input_tokens: 200,
          output_tokens: 20,
          cached_tokens: 200,
          cost_usd: 0.5,
        },
        acquire_lease: true,
      },
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    expect(await storage.getAlarm()).toBe(reserved.lease.expires_at);
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "uncertain-expiry",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("uncertain-expiry"),
      },
      T0 + 1,
    );
    expect(started.ok).toBe(true);

    const recovered = await recoverExpiredLeases(
      storage,
      T0 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 1,
    );
    expect(recovered).toMatchObject({ ok: true, recovered: 1 });
    const snap = await snapshotBudget(
      storage,
      T0 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 2,
    );
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved).toEqual(zeroCounters());
      expect(snap.active_leases).toBe(0);
      expect(snap.frozen).toBe(true);
      expect(snap.used).toMatchObject({
        model_calls: 1,
        input_tokens: 200,
        output_tokens: 20,
        cached_tokens: 200,
        cost_usd: 0.5,
      });
    }
    expect(await storage.getAlarm()).toBeNull();
    const state = await storage.get<{
      audit: Array<{ kind: string; reason?: string }>;
      reservations: Record<string, { cached_result: { http_status: number } | null }>;
    }>("ledger");
    expect(state?.audit).toContainEqual(
      expect.objectContaining({ kind: "uncertain_provider_charge", reason: "lease_expired" }),
    );
    expect(state?.reservations["uncertain-expiry"].cached_result?.http_status).toBe(500);
  });

  it("never releases a provider-started reservation at zero", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "no-zero-release",
        request_digest: testDigest("no-zero-release"),
        amounts: { model_calls: 1, input_tokens: 100, output_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    await markProviderStarted(
      storage,
      {
        idempotency_key: "no-zero-release",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("no-zero-release"),
      },
      T0 + 1,
    );
    const released = await releaseBudget(
      storage,
      { idempotency_key: "no-zero-release", lease_id: reserved.lease.lease_id },
      T0 + 2,
    );
    expect(released).toMatchObject({ ok: false, error: "provider_usage_uncertain" });
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved.model_calls).toBe(0);
      expect(snap.used.model_calls).toBe(1);
      expect(snap.used.input_tokens).toBe(100);
      expect(snap.used.output_tokens).toBe(10);
      expect(snap.frozen).toBe(true);
    }
  });

  it("uncertain settlement is idempotent and leaves no phantom reservation", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "uncertain-idempotent",
        request_digest: testDigest("uncertain"),
        amounts: { model_calls: 1, input_tokens: 50, output_tokens: 5, cached_tokens: 50 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "uncertain-idempotent",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("uncertain"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const first = await settleUncertainBudget(
      storage,
      {
        idempotency_key: "uncertain-idempotent",
        reason: "finalize_failed",
        request_digest: testDigest("uncertain"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
      },
      T0 + 2,
    );
    const second = await settleUncertainBudget(
      storage,
      {
        idempotency_key: "uncertain-idempotent",
        reason: "finalize_failed",
        request_digest: testDigest("uncertain"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
      },
      T0 + 3,
    );
    expect(first.ok && second.ok).toBe(true);
    const duplicate = await reserveBudget(
      storage,
      {
        idempotency_key: "uncertain-idempotent",
        request_digest: testDigest("uncertain"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0 + 4,
    );
    expect(duplicate.ok).toBe(true);
    if (duplicate.ok) {
      expect(duplicate.existing).toBe(true);
      expect(duplicate.reservation.cached_result?.http_status).toBe(500);
    }
    const snap = await snapshotBudget(storage, T0 + 5);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.used.model_calls).toBe(1);
    expect(snap.reserved).toEqual(zeroCounters());
    expect(snap.active_leases).toBe(0);
  });

  it("a freeze prevents a second reserved request from crossing the provider boundary", async () => {
    const storage = new MemoryBudgetStorage();
    const first = await reserveBudget(
      storage,
      {
        idempotency_key: "freeze-first",
        request_digest: testDigest("freeze-first"),
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    const second = await reserveBudget(
      storage,
      {
        idempotency_key: "freeze-second",
        request_digest: testDigest("freeze-second"),
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    if (!first.ok || !first.lease || !second.ok || !second.lease) {
      throw new Error("leases");
    }
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "freeze-first",
        lease_id: first.lease.lease_id,
        request_digest: testDigest("freeze-first"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    await settleUncertainBudget(
      storage,
      {
        idempotency_key: "freeze-first",
        reason: "provider_error",
        request_digest: testDigest("freeze-first"),
        lease_id: first.lease.lease_id,
        settlement_capability: started.settlement_capability,
      },
      T0 + 2,
    );
    const denied = await markProviderStarted(
      storage,
      {
        idempotency_key: "freeze-second",
        lease_id: second.lease.lease_id,
        request_digest: testDigest("freeze-second"),
      },
      T0 + 3,
    );
    expect(denied).toMatchObject({ ok: false, error: "budget_frozen" });
    const released = await releaseBudget(
      storage,
      { idempotency_key: "freeze-second", lease_id: second.lease.lease_id },
      T0 + 4,
    );
    expect(released.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 5);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.used.model_calls).toBe(1);
    expect(snap.reserved.model_calls).toBe(0);
    expect(snap.active_leases).toBe(0);
  });

  it("reserve recovers expired leases inline", async () => {
    const storage = new MemoryBudgetStorage();
    await reserveBudget(
      storage,
      leased("a", { model_calls: 1 }),
      T0,
    );
    await reserveBudget(
      storage,
      leased("b", { model_calls: 1 }),
      T0,
    );
    const third = await reserveBudget(
      storage,
      leased("c", { model_calls: 1 }),
      T0 + 1800 * 1000 + 1,
    );
    expect(third.ok).toBe(true);
  });

  it("cost cap is enforced in USD", async () => {
    const storage = new MemoryBudgetStorage();
    const fill = await reserveBudget(
      storage,
      leased("cost", { cost_usd: 20 }),
      T0,
    );
    expect(fill.ok).toBe(true);
    const denied = await reserveBudget(
      storage,
      leased("cost2", { cost_usd: 0.01 }),
      T0,
    );
    expect(denied.ok).toBe(false);
    if (!denied.ok) expect(denied.detail).toContain("cost_usd");
  });

  it("issues an opaque budget_run_id; caller key is not occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("client-label", { model_calls: 1 }),
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok) throw new Error("reserve");
    expect(reserved.budget_run_id).toBe(reserved.reservation.reservation_id);
    expect(reserved.budget_run_id).not.toBe("client-label");
    expect(CONTROL_PLANE_LEDGER_NAME).toBe("pilot-control-plane");
  });

  it("same digest-bound key does not double-spend; digest mismatch conflicts", async () => {
    const storage = new MemoryBudgetStorage();
    const a = await reserveBudget(
      storage,
      {
        idempotency_key: "k-dup",
        request_digest: testDigest("a"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0,
    );
    const dup = await reserveBudget(
      storage,
      {
        idempotency_key: "k-dup",
        request_digest: testDigest("a"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0 + 1,
    );
    const clash = await reserveBudget(
      storage,
      {
        idempotency_key: "k-dup",
        request_digest: testDigest("b"),
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0 + 2,
    );
    expect(a.ok && dup.ok).toBe(true);
    if (a.ok && dup.ok) {
      expect(dup.existing).toBe(true);
      expect(dup.budget_run_id).toBe(a.budget_run_id);
    }
    expect(clash.ok).toBe(false);
    if (!clash.ok) expect(clash.error).toBe("idempotency_digest_conflict");
    const snap = await snapshotBudget(storage, T0 + 2);
    expect(snap.ok).toBe(true);
    if (snap.ok) expect(snap.reserved.model_calls).toBe(1);
  });

  it("schema-reject finalize charges actual and closes the lease", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "schema-reject",
        request_digest: testDigest("schema-reject"),
        amounts: { model_calls: 1, input_tokens: 40, output_tokens: 16 },
        acquire_lease: true,
      },
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "schema-reject",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("schema-reject"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const charged = await finalizeBudget(
      storage,
      {
        idempotency_key: "schema-reject",
        request_digest: testDigest("schema-reject"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 12, output_tokens: 4 }),
        terminal_result: { http_status: 400, body: { ok: false, error: "Insight.unknown field" } },
      },
      T0 + 2,
    );
    expect(charged.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(snap.ok).toBe(true);
    if (snap.ok && charged.ok) {
      expect(snap.used.model_calls).toBe(1);
      expect(snap.used.input_tokens).toBe(12);
      expect(snap.used.output_tokens).toBe(4);
      expect(snap.reserved.model_calls).toBe(0);
      expect(snap.active_leases).toBe(0);
      expect(charged.reservation.cached_result?.http_status).toBe(400);
    }
  });

  it("actual over reserved records full spend, releases reserve, and freezes", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "over",
        request_digest: testDigest("over"),
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "over",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("over"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const over = await finalizeBudget(
      storage,
      {
        idempotency_key: "over",
        request_digest: testDigest("over"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 11 }),
      },
      T0 + 2,
    );
    expect(over.ok).toBe(false);
    if (!over.ok) expect(over.error).toBe("actual_exceeds_reserved");
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.frozen).toBe(true);
      expect(snap.used.input_tokens).toBe(11);
      expect(snap.reserved.input_tokens).toBe(0);
      expect(snap.auto_promotion).toBe(false);
    }
    const next = await reserveBudget(
      storage,
      leased("after-freeze", { model_calls: 1 }),
      T0 + 2,
    );
    expect(next.ok).toBe(false);
    if (!next.ok) expect(next.error).toBe("budget_frozen");
  });

  it("unstarted finalize cannot charge zero or persist forged success", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "unstarted",
        request_digest: testDigest("unstarted"),
        amounts: { model_calls: 1, cost_usd: 1 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const denied = await finalizeBudget(
      storage,
      {
        idempotency_key: "unstarted",
        request_digest: testDigest("unstarted"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: "0".repeat(64),
        usage: actualUsage({ model_calls: 0, cost_usd: 0 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 1,
    );
    expect(denied).toMatchObject({ ok: false, error: "provider_not_started" });
    const snap = await snapshotBudget(storage, T0 + 2);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.used).toEqual(zeroCounters());
      expect(snap.reserved.model_calls).toBe(1);
      expect(snap.active_leases).toBe(1);
      expect(snap.frozen).toBe(false);
    }
  });

  it("forged, replayed, and cross-bound settlement capabilities fail closed", async () => {
    const storage = new MemoryBudgetStorage();
    const first = await reserveBudget(
      storage,
      {
        idempotency_key: "cap-a",
        request_digest: testDigest("a"),
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    const second = await reserveBudget(
      storage,
      {
        idempotency_key: "cap-b",
        request_digest: testDigest("b"),
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    if (!first.ok || !first.lease || !second.ok || !second.lease) {
      throw new Error("leases");
    }
    const startedA = await markProviderStarted(
      storage,
      {
        idempotency_key: "cap-a",
        lease_id: first.lease.lease_id,
        request_digest: testDigest("a"),
      },
      T0 + 1,
    );
    const startedB = await markProviderStarted(
      storage,
      {
        idempotency_key: "cap-b",
        lease_id: second.lease.lease_id,
        request_digest: testDigest("b"),
      },
      T0 + 1,
    );
    if (!startedA.ok || !startedA.settlement_capability) throw new Error("cap-a");
    if (!startedB.ok || !startedB.settlement_capability) throw new Error("cap-b");

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: testDigest("a"),
          lease_id: first.lease.lease_id,
          settlement_capability: "ff".repeat(32),
          usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: testDigest("b"),
          lease_id: first.lease.lease_id,
          settlement_capability: startedA.settlement_capability,
          usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "request_digest_mismatch" });

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: testDigest("a"),
          lease_id: second.lease.lease_id,
          settlement_capability: startedA.settlement_capability,
          usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "lease_mismatch" });

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: testDigest("a"),
          lease_id: first.lease.lease_id,
          settlement_capability: startedB.settlement_capability,
          usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });

    const committed = await finalizeBudget(
      storage,
      {
        idempotency_key: "cap-a",
        request_digest: testDigest("a"),
        lease_id: first.lease.lease_id,
        settlement_capability: startedA.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        terminal_result: { http_status: 200, body: { ok: true, artifact: "kept" } },
      },
      T0 + 3,
    );
    expect(committed.ok).toBe(true);
    const replay = await finalizeBudget(
      storage,
      {
        idempotency_key: "cap-a",
        request_digest: testDigest("a"),
        lease_id: first.lease.lease_id,
        settlement_capability: startedA.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
      },
      T0 + 4,
    );
    expect(replay.ok).toBe(true);
    if (replay.ok) {
      expect(replay.reservation.actual?.input_tokens).toBe(4);
      expect(replay.used.input_tokens).toBe(4);
    }
  });

  it("rejects caller-authored amounts, result, and settlement claims", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "inject",
        request_digest: testDigest("inject"),
        amounts: { model_calls: 1, input_tokens: 20, cost_usd: 1 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "inject",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("inject"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const injected = await finalizeBudget(
      storage,
      {
        idempotency_key: "inject",
        request_digest: testDigest("inject"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 8, cost_usd: 0.2 }),
        amounts: { model_calls: 0, cost_usd: 0 },
        result: { http_status: 200, body: { ok: true, smuggled: true } },
        settlement: {
          outcome: "success",
          usage_source: "provider",
          estimated_cost_usd: 0,
          actual_cost_usd: 0,
          billed_cost_usd: 0,
          actual_input_tokens: 0,
          actual_output_tokens: 0,
          actual_cached_tokens: 0,
          provider_model: null,
          pricing_policy_id: null,
          pricing_policy_digest: null,
        },
      },
      T0 + 2,
    );
    expect(injected).toMatchObject({ ok: false, error: "caller_settlement_rejected" });
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.used).toEqual(zeroCounters());
      expect(snap.reserved.model_calls).toBe(1);
      expect(snap.frozen).toBe(false);
    }
  });

  it("omitted request_digest or lease_id cannot skip provider-start or settlement comparison", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "binding-required",
        request_digest: testDigest("binding"),
        amounts: { model_calls: 1, input_tokens: 8 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    expect(
      await markProviderStarted(
        storage,
        { idempotency_key: "binding-required", lease_id: reserved.lease.lease_id },
        T0 + 1,
      ),
    ).toMatchObject({ ok: false, error: "request_digest required" });
    expect(
      await markProviderStarted(
        storage,
        {
          idempotency_key: "binding-required",
          lease_id: reserved.lease.lease_id,
          request_digest: "   ",
        },
        T0 + 1,
      ),
    ).toMatchObject({ ok: false, error: "request_digest required" });
    expect(
      await markProviderStarted(
        storage,
        {
          idempotency_key: "binding-required",
          lease_id: "",
          request_digest: testDigest("binding"),
        },
        T0 + 1,
      ),
    ).toMatchObject({ ok: false, error: "lease_id required" });
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "binding-required",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("binding"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    expect(started.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(started.reservation).not.toHaveProperty("settlement_capability_hash");
    expect(started.reservation).not.toHaveProperty("settlement_capability");
    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "binding-required",
          request_digest: "",
          lease_id: reserved.lease.lease_id,
          settlement_capability: started.settlement_capability,
          usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "request_digest required" });
    expect(
      await settleUncertainBudget(
        storage,
        {
          idempotency_key: "binding-required",
          reason: "timeout",
          lease_id: reserved.lease.lease_id,
          settlement_capability: started.settlement_capability,
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "request_digest required" });
    expect(
      await settleUncertainBudget(
        storage,
        {
          idempotency_key: "binding-required",
          reason: "timeout",
          request_digest: testDigest("binding"),
          settlement_capability: started.settlement_capability,
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "lease_id required" });
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.used).toEqual(zeroCounters());
      expect(snap.reserved.model_calls).toBe(1);
      expect(JSON.stringify(snap)).not.toContain(started.settlement_capability);
    }
  });

  it("provider-start retry returns the same one-shot capability until consumed", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        idempotency_key: "start-retry",
        request_digest: testDigest("start-retry"),
        amounts: { model_calls: 1, input_tokens: 6 },
        acquire_lease: true,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const first = await markProviderStarted(
      storage,
      {
        idempotency_key: "start-retry",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("start-retry"),
      },
      T0 + 1,
    );
    const lostResponseRetry = await markProviderStarted(
      storage,
      {
        idempotency_key: "start-retry",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("start-retry"),
      },
      T0 + 2,
    );
    expect(first.ok && lostResponseRetry.ok).toBe(true);
    if (!first.ok || !lostResponseRetry.ok) throw new Error("start");
    expect(lostResponseRetry.settlement_capability).toBe(first.settlement_capability);
    expect(first.settlement_capability).toEqual(expect.any(String));
    const committed = await finalizeBudget(
      storage,
      {
        idempotency_key: "start-retry",
        request_digest: testDigest("start-retry"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: lostResponseRetry.settlement_capability as string,
        usage: actualUsage({ model_calls: 1, input_tokens: 3 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 3,
    );
    expect(committed.ok).toBe(true);
    const afterConsume = await markProviderStarted(
      storage,
      {
        idempotency_key: "start-retry",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("start-retry"),
      },
      T0 + 4,
    );
    expect(afterConsume).toMatchObject({ ok: false, error: "reservation_reconciled" });
  });

  it("rejects a missing request_digest and creates no occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const omitted = await reserveBudget(
      storage,
      { idempotency_key: "missing-digest", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    const blank = await reserveBudget(
      storage,
      {
        idempotency_key: "blank-digest",
        request_digest: "   ",
        amounts: { model_calls: 1 },
        acquire_lease: true,
      },
      T0,
    );
    expect(omitted).toMatchObject({ ok: false, error: "request_digest required" });
    expect(blank).toMatchObject({ ok: false, error: "request_digest required" });
    expect(omitted).not.toHaveProperty("reservation");
    expect(blank).not.toHaveProperty("reservation");
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.reserved).toEqual(zeroCounters());
    expect(snap.used).toEqual(zeroCounters());
    expect(snap.active_leases).toBe(0);
  });

  it("rejects a no-lease reserve and leaves no phantom occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const omitted = await reserveBudget(
      storage,
      {
        idempotency_key: "no-lease",
        request_digest: testDigest("no-lease"),
        amounts: { model_calls: 1 },
      },
      T0,
    );
    const disabled = await reserveBudget(
      storage,
      {
        idempotency_key: "no-lease-false",
        request_digest: testDigest("no-lease-false"),
        amounts: { model_calls: 1 },
        acquire_lease: false,
      },
      T0,
    );
    expect(omitted).toMatchObject({ ok: false, error: "lease_required" });
    expect(disabled).toMatchObject({ ok: false, error: "lease_required" });
    expect(omitted).not.toHaveProperty("reservation");
    expect(disabled).not.toHaveProperty("reservation");
    expect(await storage.getAlarm()).toBeNull();
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.reserved).toEqual(zeroCounters());
    expect(snap.active_leases).toBe(0);
    const state = await storage.get<{ reservations: Record<string, unknown> }>("ledger");
    expect(state?.reservations["no-lease"]).toBeUndefined();
    expect(state?.reservations["no-lease-false"]).toBeUndefined();
  });

  it("replay requires exact digest equality and returns no reservation payload", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("replay-digest", { model_calls: 1 }, testDigest("replay")),
      T0,
    );
    expect(reserved.ok).toBe(true);
    const omitted = await reserveBudget(
      storage,
      { idempotency_key: "replay-digest", amounts: { model_calls: 1 }, acquire_lease: true },
      T0 + 1,
    );
    const wrong = await reserveBudget(
      storage,
      leased("replay-digest", { model_calls: 1 }, testDigest("other")),
      T0 + 2,
    );
    expect(omitted).toMatchObject({ ok: false, error: "request_digest required" });
    expect(wrong).toMatchObject({ ok: false, error: "idempotency_digest_conflict" });
    expect(omitted).not.toHaveProperty("reservation");
    expect(wrong).not.toHaveProperty("reservation");
    expect(JSON.stringify(omitted)).not.toMatch(/cached_result|settlement_capability/);
    expect(JSON.stringify(wrong)).not.toMatch(/cached_result|settlement_capability/);
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.reserved.model_calls).toBe(1);
      expect(snap.active_leases).toBe(1);
    }
  });

  it("reserve replay after provider-start never includes the secret or hash", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("replay-secret", { model_calls: 1, input_tokens: 8 }, testDigest("replay-secret")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "replay-secret",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("replay-secret"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const secret = started.settlement_capability;
    const ledger = await storage.get<{
      reservations: Record<
        string,
        { settlement_capability_hash: string | null; settlement_capability_secret: string | null }
      >;
    }>("ledger");
    const hash = ledger?.reservations["replay-secret"].settlement_capability_hash;
    expect(hash).toEqual(expect.any(String));
    expect(ledger?.reservations["replay-secret"].settlement_capability_secret).toBe(secret);

    const replay = await reserveBudget(
      storage,
      leased("replay-secret", { model_calls: 1, input_tokens: 8 }, testDigest("replay-secret")),
      T0 + 2,
    );
    expect(replay.ok).toBe(true);
    if (!replay.ok) throw new Error("replay");
    expect(replay.existing).toBe(true);
    expect(replay.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(replay.reservation).not.toHaveProperty("settlement_capability_hash");
    expect(replay.reservation).not.toHaveProperty("settlement_capability");
    const encoded = JSON.stringify(replay);
    expect(encoded).not.toContain(secret);
    expect(encoded).not.toContain(hash as string);
    const snap = await snapshotBudget(storage, T0 + 3);
    expect(JSON.stringify(snap)).not.toContain(secret);
    expect(JSON.stringify(snap)).not.toContain(hash as string);
  });

  it("exact mark-start retry returns the same capability and never via reserve", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("mark-retry", { model_calls: 1 }, testDigest("mark-retry")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const first = await markProviderStarted(
      storage,
      {
        idempotency_key: "mark-retry",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("mark-retry"),
      },
      T0 + 1,
    );
    const retry = await markProviderStarted(
      storage,
      {
        idempotency_key: "mark-retry",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("mark-retry"),
      },
      T0 + 2,
    );
    expect(first.ok && retry.ok).toBe(true);
    if (!first.ok || !retry.ok) throw new Error("start");
    expect(retry.settlement_capability).toBe(first.settlement_capability);
    expect(first.settlement_capability).toEqual(expect.any(String));
    expect(first.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(first.reservation).not.toHaveProperty("settlement_capability_hash");
    const reserveReplay = await reserveBudget(
      storage,
      leased("mark-retry", { model_calls: 1 }, testDigest("mark-retry")),
      T0 + 3,
    );
    expect(reserveReplay.ok).toBe(true);
    if (!reserveReplay.ok) throw new Error("reserve replay");
    expect(JSON.stringify(reserveReplay)).not.toContain(first.settlement_capability);
    expect(reserveReplay).not.toHaveProperty("settlement_capability");
  });

  it("expiry releases a pre-provider reservation and leaves no phantom occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("pre-provider-expiry", { model_calls: 3, input_tokens: 30 }, testDigest("pre-provider-expiry")),
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    expect(await storage.getAlarm()).toBe(reserved.lease.expires_at);
    const recovered = await recoverExpiredLeases(
      storage,
      T0 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 1,
    );
    expect(recovered).toMatchObject({ ok: true, recovered: 1 });
    expect(await storage.getAlarm()).toBeNull();
    const snap = await snapshotBudget(
      storage,
      T0 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 2,
    );
    expect(snap.ok).toBe(true);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.reserved).toEqual(zeroCounters());
    expect(snap.used).toEqual(zeroCounters());
    expect(snap.active_leases).toBe(0);
    expect(snap.frozen).toBe(false);
    const state = await storage.get<{
      reservations: Record<string, { status: string; provider_started_at: number | null }>;
      leases: Record<string, { released_at: number | null }>;
    }>("ledger");
    expect(state?.reservations["pre-provider-expiry"].status).toBe("released");
    expect(state?.reservations["pre-provider-expiry"].provider_started_at).toBeNull();
    expect(state?.leases[reserved.lease.lease_id].released_at).toEqual(expect.any(Number));
    const retry = await reserveBudget(
      storage,
      leased("pre-provider-expiry", { model_calls: 3 }, testDigest("pre-provider-expiry")),
      T0 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 3,
    );
    expect(retry.ok).toBe(true);
    if (retry.ok) {
      expect(retry.existing).toBe(false);
      expect(retry.budget_run_id).not.toBe(reserved.budget_run_id);
      expect(retry.lease?.expires_at).toBe(
        T0 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000 + 3 + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000,
      );
    }
  });

  it("bindIdempotencyKey uses digest when the client key is absent", () => {
    const digest = testDigest("abc");
    const bound = bindIdempotencyKey(undefined, digest);
    expect(bound.ok).toBe(true);
    if (bound.ok) {
      expect(bound.idempotency_key).toBe(`digest:${digest}`);
      expect(bound.request_digest).toBe(digest);
    }
    const named = bindIdempotencyKey("k1", digest);
    expect(named.ok).toBe(true);
    if (named.ok) expect(named.idempotency_key).toBe("k1");
    expect(bindIdempotencyKey("界".repeat(86), digest)).toMatchObject({
      ok: false,
      error: "idempotency_key too long",
    });

    for (const invalid of ["abc", "A".repeat(64), "g".repeat(64)]) {
      expect(bindIdempotencyKey(undefined, invalid)).toMatchObject({
        ok: false,
        error: "request_digest must be lowercase sha256 hex",
      });
    }
  });
});

function assertNoCapabilityLeak(payload: unknown, secret: string, hash: string): void {
  const encoded = JSON.stringify(payload);
  expect(encoded).not.toContain(secret);
  expect(encoded).not.toContain(hash);
  expect(encoded).not.toMatch(/settlement_capability_secret|settlement_capability_hash/);
}

describe("P0 terminal replay and capability isolation", () => {
  it("rejects an unowned reservation on the production Gateway reserve surface", async () => {
    const storage = new MemoryBudgetStorage();
    const denied = await reserveOwnedBudget(
      storage,
      leased("unowned-production", { model_calls: 1 }) as Parameters<
        typeof reserveOwnedBudget
      >[1],
      T0,
    );
    expect(denied).toEqual({
      ok: false,
      error: "reserve_owner_capability invalid",
    });
    expect(await snapshotBudget(storage, T0)).toMatchObject({
      ok: true,
      reserved: { model_calls: 0 },
      active_leases: 0,
    });
  });

  it("public DTO has no sensitive capability fields", () => {
    expectTypeOf<Reservation>().toHaveProperty("settlement_capability_secret");
    expectTypeOf<Reservation>().toHaveProperty("settlement_capability_hash");
    expectTypeOf<PublicReservation>().not.toHaveProperty("settlement_capability");
    expectTypeOf<PublicReservation>().not.toHaveProperty("settlement_capability_secret");
    expectTypeOf<PublicReservation>().not.toHaveProperty("settlement_capability_hash");
    type Sensitive = Extract<
      keyof PublicReservation,
      "settlement_capability" | "settlement_capability_secret" | "settlement_capability_hash"
    >;
    const publicDtoHasNoSensitive: Sensitive extends never ? true : never = true;
    expect(publicDtoHasNoSensitive).toBe(true);
  });

  it("active and reconciled reserve replay with missing/false acquire_lease rejects", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-lease", { model_calls: 1, input_tokens: 8 }, testDigest("p0-lease")),
      T0,
    );
    expect(reserved.ok).toBe(true);
    if (!reserved.ok || !reserved.lease) throw new Error("lease");

    for (const [label, acquire] of [
      ["active omitted", undefined],
      ["active false", false],
    ] as const) {
      const denied = await reserveBudget(
        storage,
        {
          idempotency_key: "p0-lease",
          request_digest: testDigest("p0-lease"),
          amounts: { model_calls: 1, input_tokens: 8 },
          ...(acquire === false ? { acquire_lease: false } : {}),
        },
        T0 + 1,
      );
      expect(denied, label).toMatchObject({ ok: false, error: "lease_required" });
      expect(denied).not.toHaveProperty("reservation");
      expect(JSON.stringify(denied)).not.toMatch(/cached_result|settlement_capability/);
    }

    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-lease",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("p0-lease"),
      },
      T0 + 2,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const finalized = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-lease",
        request_digest: testDigest("p0-lease"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 3 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 3,
    );
    expect(finalized.ok).toBe(true);

    for (const acquire of [undefined, false] as const) {
      const denied = await reserveBudget(
        storage,
        {
          idempotency_key: "p0-lease",
          request_digest: testDigest("p0-lease"),
          amounts: { model_calls: 1, input_tokens: 8 },
          ...(acquire === false ? { acquire_lease: false } : {}),
        },
        T0 + 4,
      );
      expect(denied).toMatchObject({ ok: false, error: "lease_required" });
      expect(denied).not.toHaveProperty("reservation");
      expect(JSON.stringify(denied)).not.toMatch(/cached_result|settlement_capability/);
    }

    const exactReplay = await reserveBudget(
      storage,
      leased("p0-lease", { model_calls: 1, input_tokens: 8 }, testDigest("p0-lease")),
      T0 + 5,
    );
    expect(exactReplay.ok).toBe(true);
    if (!exactReplay.ok) throw new Error("replay");
    expect(exactReplay.existing).toBe(true);
    expect(exactReplay.budget_run_id).toBe(reserved.budget_run_id);
    expect(exactReplay.reservation.cached_result?.http_status).toBe(200);
    const snap = await snapshotBudget(storage, T0 + 6);
    if (!snap.ok) throw new Error("snapshot");
    expect(snap.used.model_calls).toBe(1);
    expect(snap.reserved).toEqual(zeroCounters());
    expect(snap.active_leases).toBe(0);
  });

  it("nested object and array bodies cannot persist or return capability material", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-smuggle", { model_calls: 1, input_tokens: 8 }, testDigest("p0-smuggle")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-smuggle",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("p0-smuggle"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const secret = started.settlement_capability;
    const ledger = await storage.get<{
      reservations: Record<
        string,
        { settlement_capability_hash: string | null; cached_result: unknown }
      >;
    }>("ledger");
    const hash = ledger?.reservations["p0-smuggle"].settlement_capability_hash;
    expect(hash).toEqual(expect.any(String));

    const nestedObject = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-smuggle",
        request_digest: testDigest("p0-smuggle"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        terminal_result: {
          http_status: 200,
          body: {
            ok: true,
            artifact: {
              nested: {
                settlement_capability: secret,
                settlement_capability_secret: secret,
                settlement_capability_hash: hash,
              },
            },
          },
        },
      },
      T0 + 2,
    );
    expect(nestedObject.ok).toBe(false);
    if (!nestedObject.ok) {
      expect(nestedObject.error).toMatch(/cached_result_capability_/);
    }
    expect(nestedObject).not.toHaveProperty("reservation");

    const nestedArray = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-smuggle",
        request_digest: testDigest("p0-smuggle"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        terminal_result: {
          http_status: 200,
          body: {
            ok: true,
            artifact: [{ token: secret }, hash, { items: [hash, { k: secret }] }],
          },
        },
      },
      T0 + 3,
    );
    expect(nestedArray.ok).toBe(false);
    if (!nestedArray.ok) {
      expect(nestedArray.error).toMatch(/cached_result_capability_/);
    }

    const afterReject = await storage.get<{
      reservations: Record<
        string,
        {
          status: string;
          cached_result: unknown;
          settlement_capability_secret: string | null;
          settlement_capability_consumed: boolean;
        }
      >;
    }>("ledger");
    expect(afterReject?.reservations["p0-smuggle"].status).toBe("reserved");
    expect(afterReject?.reservations["p0-smuggle"].cached_result).toBeNull();
    expect(afterReject?.reservations["p0-smuggle"].settlement_capability_secret).toBe(secret);
    expect(afterReject?.reservations["p0-smuggle"].settlement_capability_consumed).toBe(false);

    const reserveReplay = await reserveBudget(
      storage,
      leased("p0-smuggle", { model_calls: 1, input_tokens: 8 }, testDigest("p0-smuggle")),
      T0 + 4,
    );
    expect(reserveReplay.ok).toBe(true);
    assertNoCapabilityLeak(reserveReplay, secret, hash as string);

    const committed = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-smuggle",
        request_digest: testDigest("p0-smuggle"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        terminal_result: { http_status: 200, body: { ok: true, artifact: { summary: "safe" } } },
      },
      T0 + 6,
    );
    expect(committed.ok).toBe(true);
    if (!committed.ok) throw new Error("commit");
    assertNoCapabilityLeak(committed, secret, hash as string);

    const cachedReplay = await reserveBudget(
      storage,
      leased("p0-smuggle", { model_calls: 1, input_tokens: 8 }, testDigest("p0-smuggle")),
      T0 + 7,
    );
    expect(cachedReplay.ok).toBe(true);
    if (!cachedReplay.ok) throw new Error("cached replay");
    expect(cachedReplay.reservation.cached_result?.body).toMatchObject({
      ok: true,
      artifact: { summary: "safe" },
    });
    assertNoCapabilityLeak(cachedReplay, secret, hash as string);

    const released = await releaseBudget(
      storage,
      { idempotency_key: "p0-smuggle", lease_id: reserved.lease.lease_id },
      T0 + 8,
    );
    expect(released.ok).toBe(true);
    assertNoCapabilityLeak(released, secret, hash as string);
    const persisted = await storage.get<{
      reservations: Record<string, { cached_result: { body: unknown } | null }>;
    }>("ledger");
    expect(JSON.stringify(persisted?.reservations["p0-smuggle"].cached_result)).not.toContain(
      secret,
    );
    expect(JSON.stringify(persisted?.reservations["p0-smuggle"].cached_result)).not.toContain(
      hash as string,
    );
  });

  it("nested strings cannot persist capability or hash as a substring", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-substr", { model_calls: 1, input_tokens: 8 }, testDigest("p0-substr")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const leaseId = reserved.lease.lease_id;
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-substr",
        lease_id: leaseId,
        request_digest: testDigest("p0-substr"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const secret = started.settlement_capability;
    const beforeLedger = await storage.get<{
      reservations: Record<
        string,
        {
          status: string;
          amounts: unknown;
          lease_id: string | null;
          cached_result: unknown;
          settlement_capability_secret: string | null;
          settlement_capability_consumed: boolean;
          settlement_capability_hash: string | null;
        }
      >;
    }>("ledger");
    const hash = beforeLedger?.reservations["p0-substr"].settlement_capability_hash;
    expect(hash).toEqual(expect.any(String));
    const before = await snapshotBudget(storage, T0 + 2);
    if (!before.ok) throw new Error("before");
    const wraps: Array<{ name: string; wrap: (token: string) => string }> = [
      { name: "prefix", wrap: (token) => `${token}=tail` },
      { name: "suffix", wrap: (token) => `secret=${token}` },
      { name: "wrapped", wrap: (token) => `pre-${token}-post` },
    ];
    const placements: Array<{ name: string; body: Record<string, unknown> }> = [];
    for (const { name, wrap } of wraps) {
      placements.push({
        name: `${name} secret nested object`,
        body: { ok: true, artifact: { nested: { note: wrap(secret) } } },
      });
      placements.push({
        name: `${name} secret nested array`,
        body: { ok: true, artifact: [{ items: [wrap(secret)] }] },
      });
      placements.push({
        name: `${name} hash nested object`,
        body: { ok: true, artifact: { nested: { digest: wrap(hash as string) } } },
      });
      placements.push({
        name: `${name} hash nested array`,
        body: { ok: true, artifact: [{ items: [wrap(hash as string)] }] },
      });
    }

    let now = T0 + 3;
    for (const placement of placements) {
      const denied = await finalizeBudget(
        storage,
        {
          idempotency_key: "p0-substr",
          request_digest: testDigest("p0-substr"),
          lease_id: leaseId,
          settlement_capability: secret,
          usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
          terminal_result: { http_status: 200, body: placement.body },
        },
        now,
      );
      now += 1;
      expect(denied.ok, placement.name).toBe(false);
      if (!denied.ok) {
        expect(denied.error, placement.name).toMatch(/cached_result_capability_/);
      }
      expect(denied).not.toHaveProperty("reservation");
      assertNoCapabilityLeak(denied, secret, hash as string);

      const snap = await snapshotBudget(storage, now);
      now += 1;
      expect(snap.ok).toBe(true);
      if (snap.ok) {
        expect(snap.used).toEqual(before.used);
        expect(snap.reserved).toEqual(before.reserved);
        expect(snap.active_leases).toBe(before.active_leases);
        expect(snap.frozen).toBe(false);
      }
      assertNoCapabilityLeak(snap, secret, hash as string);

      const afterReject = await storage.get<{
        reservations: Record<
          string,
          {
            status: string;
            amounts: unknown;
            lease_id: string | null;
            cached_result: unknown;
            settlement_capability_secret: string | null;
            settlement_capability_consumed: boolean;
          }
        >;
      }>("ledger");
      const row = afterReject?.reservations["p0-substr"];
      expect(row?.status, placement.name).toBe("reserved");
      expect(row?.cached_result, placement.name).toBeNull();
      expect(row?.settlement_capability_secret, placement.name).toBe(secret);
      expect(row?.settlement_capability_consumed, placement.name).toBe(false);
      expect(row?.lease_id, placement.name).toBe(leaseId);
      expect(row?.amounts, placement.name).toEqual(
        beforeLedger?.reservations["p0-substr"].amounts,
      );
    }

    const benignBody = {
      ok: true,
      artifact: {
        summary: "benign-note",
        notes: ["unrelated-token", "plain-text"],
        nested: { items: ["still-safe", { k: "unchanged" }] },
      },
      model: "safe-model",
    };
    const committed = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-substr",
        request_digest: testDigest("p0-substr"),
        lease_id: leaseId,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        terminal_result: { http_status: 200, body: benignBody },
      },
      now,
    );
    now += 1;
    expect(committed.ok).toBe(true);
    if (!committed.ok) throw new Error("commit");
    expect(committed.reservation.cached_result?.body).toEqual(benignBody);
    assertNoCapabilityLeak(committed, secret, hash as string);

    const retry = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-substr",
        request_digest: testDigest("p0-substr"),
        lease_id: leaseId,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
        terminal_result: { http_status: 200, body: benignBody },
      },
      now,
    );
    now += 1;
    expect(retry.ok).toBe(true);
    if (!retry.ok) throw new Error("retry");
    expect(retry.reservation.cached_result?.body).toEqual(benignBody);
    expect(retry.reservation.actual?.input_tokens).toBe(2);
    assertNoCapabilityLeak(retry, secret, hash as string);

    const cachedReplay = await reserveBudget(
      storage,
      leased("p0-substr", { model_calls: 1, input_tokens: 8 }, testDigest("p0-substr")),
      now,
    );
    now += 1;
    expect(cachedReplay.ok).toBe(true);
    if (!cachedReplay.ok) throw new Error("cached replay");
    expect(cachedReplay.reservation.cached_result?.body).toEqual(benignBody);
    assertNoCapabilityLeak(cachedReplay, secret, hash as string);

    const released = await releaseBudget(
      storage,
      { idempotency_key: "p0-substr", lease_id: leaseId },
      now,
    );
    now += 1;
    expect(released.ok).toBe(true);
    assertNoCapabilityLeak(released, secret, hash as string);

    const snap = await snapshotBudget(storage, now);
    expect(snap.ok).toBe(true);
    if (snap.ok) {
      expect(snap.used.model_calls).toBe(1);
      expect(snap.reserved).toEqual(zeroCounters());
      expect(snap.active_leases).toBe(0);
    }
    assertNoCapabilityLeak(snap, secret, hash as string);

    const persisted = await storage.get<{
      reservations: Record<string, { cached_result: { body: unknown } | null }>;
    }>("ledger");
    expect(persisted?.reservations["p0-substr"].cached_result?.body).toEqual(benignBody);
    expect(JSON.stringify(persisted?.reservations["p0-substr"].cached_result)).not.toContain(
      secret,
    );
    expect(JSON.stringify(persisted?.reservations["p0-substr"].cached_result)).not.toContain(
      hash as string,
    );
  });

  it("exact finalized retry succeeds; wrong or omitted digest/lease/cap fails", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-finalize", { model_calls: 1, input_tokens: 10 }, testDigest("p0-finalize")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const leaseId = reserved.lease.lease_id;
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-finalize",
        lease_id: leaseId,
        request_digest: testDigest("p0-finalize"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const cap = started.settlement_capability;
    const first = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-finalize",
        request_digest: testDigest("p0-finalize"),
        lease_id: leaseId,
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 4 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 2,
    );
    expect(first.ok).toBe(true);

    const attacks: Array<{ name: string; input: Parameters<typeof finalizeBudget>[1]; error: string }> =
      [
        {
          name: "wrong digest",
          input: {
            idempotency_key: "p0-finalize",
            request_digest: testDigest("other"),
            lease_id: leaseId,
            settlement_capability: cap,
            usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
          },
          error: "request_digest_mismatch",
        },
        {
          name: "omitted digest",
          input: {
            idempotency_key: "p0-finalize",
            request_digest: "",
            lease_id: leaseId,
            settlement_capability: cap,
            usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
          },
          error: "request_digest required",
        },
        {
          name: "wrong lease",
          input: {
            idempotency_key: "p0-finalize",
            request_digest: testDigest("p0-finalize"),
            lease_id: "00000000-0000-4000-8000-000000000000",
            settlement_capability: cap,
            usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
          },
          error: "lease_mismatch",
        },
        {
          name: "omitted lease",
          input: {
            idempotency_key: "p0-finalize",
            request_digest: testDigest("p0-finalize"),
            lease_id: "",
            settlement_capability: cap,
            usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
          },
          error: "lease_id required",
        },
        {
          name: "wrong capability",
          input: {
            idempotency_key: "p0-finalize",
            request_digest: testDigest("p0-finalize"),
            lease_id: leaseId,
            settlement_capability: "ff".repeat(32),
            usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
          },
          error: "settlement_capability_invalid",
        },
        {
          name: "omitted capability",
          input: {
            idempotency_key: "p0-finalize",
            request_digest: testDigest("p0-finalize"),
            lease_id: leaseId,
            settlement_capability: "",
            usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
          },
          error: "settlement_capability_required",
        },
      ];
    for (const attack of attacks) {
      const denied = await finalizeBudget(storage, attack.input, T0 + 3);
      expect(denied, attack.name).toMatchObject({ ok: false, error: attack.error });
      expect(denied).not.toHaveProperty("reservation");
      expect(JSON.stringify(denied)).not.toMatch(/cached_result/);
      expect(JSON.stringify(denied)).not.toContain(cap);
    }

    const retry = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-finalize",
        request_digest: testDigest("p0-finalize"),
        lease_id: leaseId,
        settlement_capability: cap,
        usage: actualUsage({ model_calls: 1, input_tokens: 99 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 4,
    );
    expect(retry.ok).toBe(true);
    if (!retry.ok) throw new Error("retry");
    expect(retry.reservation.actual?.input_tokens).toBe(4);
    expect(retry.used.input_tokens).toBe(4);
    expect(retry.reservation.cached_result?.http_status).toBe(200);
  });

  it("exact uncertain retry is idempotent; wrong or omitted each field fails", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-uncertain", { model_calls: 1, input_tokens: 12 }, testDigest("p0-uncertain")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const leaseId = reserved.lease.lease_id;
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-uncertain",
        lease_id: leaseId,
        request_digest: testDigest("p0-uncertain"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const cap = started.settlement_capability;
    const first = await settleUncertainBudget(
      storage,
      {
        idempotency_key: "p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("p0-uncertain"),
        lease_id: leaseId,
        settlement_capability: cap,
      },
      T0 + 2,
    );
    expect(first.ok).toBe(true);

    const attacks: Array<{
      name: string;
      input: Parameters<typeof settleUncertainBudget>[1];
      error: string;
    }> = [
      {
        name: "wrong digest",
        input: {
          idempotency_key: "p0-uncertain",
          reason: "timeout",
          request_digest: testDigest("other"),
          lease_id: leaseId,
          settlement_capability: cap,
        },
        error: "request_digest_mismatch",
      },
      {
        name: "omitted digest",
        input: {
          idempotency_key: "p0-uncertain",
          reason: "timeout",
          lease_id: leaseId,
          settlement_capability: cap,
        },
        error: "request_digest required",
      },
      {
        name: "wrong lease",
        input: {
          idempotency_key: "p0-uncertain",
          reason: "timeout",
          request_digest: testDigest("p0-uncertain"),
          lease_id: "00000000-0000-4000-8000-000000000000",
          settlement_capability: cap,
        },
        error: "lease_mismatch",
      },
      {
        name: "omitted lease",
        input: {
          idempotency_key: "p0-uncertain",
          reason: "timeout",
          request_digest: testDigest("p0-uncertain"),
          settlement_capability: cap,
        },
        error: "lease_id required",
      },
      {
        name: "wrong capability",
        input: {
          idempotency_key: "p0-uncertain",
          reason: "timeout",
          request_digest: testDigest("p0-uncertain"),
          lease_id: leaseId,
          settlement_capability: "aa".repeat(32),
        },
        error: "settlement_capability_invalid",
      },
      {
        name: "omitted capability",
        input: {
          idempotency_key: "p0-uncertain",
          reason: "timeout",
          request_digest: testDigest("p0-uncertain"),
          lease_id: leaseId,
        },
        error: "settlement_capability_required",
      },
    ];
    for (const attack of attacks) {
      const denied = await settleUncertainBudget(storage, attack.input, T0 + 3);
      expect(denied, attack.name).toMatchObject({ ok: false, error: attack.error });
      expect(denied).not.toHaveProperty("reservation");
      expect(JSON.stringify(denied)).not.toMatch(/cached_result/);
      expect(JSON.stringify(denied)).not.toContain(cap);
    }

    const retry = await settleUncertainBudget(
      storage,
      {
        idempotency_key: "p0-uncertain",
        reason: "timeout",
        request_digest: testDigest("p0-uncertain"),
        lease_id: leaseId,
        settlement_capability: cap,
      },
      T0 + 4,
    );
    expect(retry.ok).toBe(true);
    if (!retry.ok) throw new Error("retry");
    expect(retry.reservation.cached_result?.http_status).toBe(504);
    expect(retry.used.input_tokens).toBe(12);
  });

  it("terminal replay does not change counters, charge twice, reopen a lease, or expose secrets", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-replay-state", { model_calls: 1, input_tokens: 9, cost_usd: 0.2 }, testDigest("p0-replay-state")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const leaseId = reserved.lease.lease_id;
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-replay-state",
        lease_id: leaseId,
        request_digest: testDigest("p0-replay-state"),
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const secret = started.settlement_capability;
    const hash = (
      await storage.get<{
        reservations: Record<string, { settlement_capability_hash: string | null }>;
      }>("ledger")
    )?.reservations["p0-replay-state"].settlement_capability_hash as string;

    const first = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-replay-state",
        request_digest: testDigest("p0-replay-state"),
        lease_id: leaseId,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 5, cost_usd: 0.1 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 2,
    );
    expect(first.ok).toBe(true);
    const before = await snapshotBudget(storage, T0 + 3);
    if (!before.ok) throw new Error("before");

    const replay = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-replay-state",
        request_digest: testDigest("p0-replay-state"),
        lease_id: leaseId,
        settlement_capability: secret,
        usage: actualUsage({ model_calls: 1, input_tokens: 99, cost_usd: 9 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 4,
    );
    expect(replay.ok).toBe(true);
    if (!replay.ok) throw new Error("replay");
    expect(replay.used).toEqual(before.used);
    expect(replay.reservation.actual?.input_tokens).toBe(5);
    expect(replay.reservation).not.toHaveProperty("settlement_capability_secret");
    expect(replay.reservation).not.toHaveProperty("settlement_capability_hash");
    assertNoCapabilityLeak(replay, secret, hash);

    const after = await snapshotBudget(storage, T0 + 5);
    if (!after.ok) throw new Error("after");
    expect(after.used).toEqual(before.used);
    expect(after.reserved).toEqual(zeroCounters());
    expect(after.active_leases).toBe(0);
    expect(JSON.stringify(after)).not.toContain(secret);
    expect(JSON.stringify(after)).not.toContain(hash);

    const heartbeat = await heartbeatLease(storage, leaseId, T0 + 6);
    expect(heartbeat).toMatchObject({ ok: false, error: "lease_not_active" });
  });

  it("lost mark-start response recovers capability only through exact mark-start retry", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("p0-lost-start", { model_calls: 1, input_tokens: 7 }, testDigest("p0-lost-start")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const leaseId = reserved.lease.lease_id;
    const first = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-lost-start",
        lease_id: leaseId,
        request_digest: testDigest("p0-lost-start"),
      },
      T0 + 1,
    );
    if (!first.ok || !first.settlement_capability) throw new Error("cap");
    const secret = first.settlement_capability;

    const viaReserve = await reserveBudget(
      storage,
      leased("p0-lost-start", { model_calls: 1, input_tokens: 7 }, testDigest("p0-lost-start")),
      T0 + 2,
    );
    expect(viaReserve.ok).toBe(true);
    expect(viaReserve).not.toHaveProperty("settlement_capability");
    expect(JSON.stringify(viaReserve)).not.toContain(secret);

    const wrongDigest = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-lost-start",
        lease_id: leaseId,
        request_digest: testDigest("other"),
      },
      T0 + 3,
    );
    expect(wrongDigest).toMatchObject({ ok: false, error: "request_digest_mismatch" });
    expect(JSON.stringify(wrongDigest)).not.toContain(secret);

    const retried = await markProviderStarted(
      storage,
      {
        idempotency_key: "p0-lost-start",
        lease_id: leaseId,
        request_digest: testDigest("p0-lost-start"),
      },
      T0 + 4,
    );
    expect(retried.ok).toBe(true);
    if (!retried.ok) throw new Error("retry start");
    expect(retried.settlement_capability).toBe(secret);
    expect(retried.reservation).not.toHaveProperty("settlement_capability_secret");

    const finalized = await finalizeBudget(
      storage,
      {
        idempotency_key: "p0-lost-start",
        request_digest: testDigest("p0-lost-start"),
        lease_id: leaseId,
        settlement_capability: retried.settlement_capability as string,
        usage: actualUsage({ model_calls: 1, input_tokens: 3 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 5,
    );
    expect(finalized.ok).toBe(true);
    if (!finalized.ok) throw new Error("finalize");
    expect(finalized.used.input_tokens).toBe(3);
    expect(JSON.stringify(finalized)).not.toContain(secret);
  });

  it("rejects cyclic and non-JSON terminal bodies without consuming settlement authority", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("bounded-body", { model_calls: 1, input_tokens: 8 }, testDigest("bounded-body")),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(storage, {
      idempotency_key: "bounded-body",
      request_digest: testDigest("bounded-body"),
      lease_id: reserved.lease.lease_id,
    }, T0 + 1);
    if (!started.ok || !started.settlement_capability) throw new Error("capability");
    const cyclic: Record<string, unknown> = { ok: true };
    cyclic.artifact = cyclic;

    for (const body of [
      cyclic,
      { ok: true, artifact: { unsupported: () => 1 } },
      { ok: true, artifact: { unsupported: 1n } },
    ]) {
      await expect(finalizeBudget(storage, {
        idempotency_key: "bounded-body",
        request_digest: testDigest("bounded-body"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
        terminal_result: { http_status: 200, body },
      }, T0 + 2)).resolves.toMatchObject({ ok: false, error: "cached_result_invalid" });
    }

    const committed = await finalizeBudget(storage, {
      idempotency_key: "bounded-body",
      request_digest: testDigest("bounded-body"),
      lease_id: reserved.lease.lease_id,
      settlement_capability: started.settlement_capability,
      usage: actualUsage({ model_calls: 1, input_tokens: 2 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    }, T0 + 3);
    expect(committed.ok).toBe(true);
  });

  it("rejects terminal envelope accessors and hostile proxies without throwing", async () => {
    const envelopeFactories: Array<[string, () => unknown]> = [
      [
        "status-getter",
        () => Object.defineProperty({}, "http_status", {
          enumerable: true,
          get() {
            throw new Error("status getter must not run");
          },
        }),
      ],
      [
        "body-getter",
        () => Object.defineProperties({}, {
          http_status: { enumerable: true, value: 200 },
          body: {
            enumerable: true,
            get() {
              throw new Error("body getter must not run");
            },
          },
        }),
      ],
      [
        "hostile-proxy",
        () => new Proxy(
          { http_status: 200, body: { ok: true } },
          {
            getPrototypeOf() {
              throw new Error("proxy trap must be contained");
            },
          },
        ),
      ],
    ];
    for (const [label, makeEnvelope] of envelopeFactories) {
      const storage = new MemoryBudgetStorage();
      const key = `terminal-${label}`;
      const reserved = await reserveBudget(
        storage,
        leased(key, { model_calls: 1, input_tokens: 8 }, testDigest(key)),
        T0,
      );
      if (!reserved.ok || !reserved.lease) throw new Error("lease");
      const started = await markProviderStarted(storage, {
        idempotency_key: key,
        request_digest: testDigest(key),
        lease_id: reserved.lease.lease_id,
      }, T0 + 1);
      if (!started.ok || !started.settlement_capability) throw new Error("capability");
      await expect(finalizeBudget(storage, {
        idempotency_key: key,
        request_digest: testDigest(key),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ input_tokens: 2 }),
        terminal_result: makeEnvelope() as never,
      }, T0 + 2), label).resolves.toMatchObject({
        ok: false,
        error: "cached_result_invalid",
      });
    }
  });

  it.each([
    ["non-numeric", (state: Record<string, any>) => {
      state.used.input_tokens = "0";
    }],
    ["missing", (state: Record<string, any>) => {
      delete state.reserved.model_calls;
    }],
    ["fractional", (state: Record<string, any>) => {
      state.used.output_tokens = 0.5;
    }],
  ])("fails closed for %s persisted occupancy instead of coercing it to zero", async (_label, mutate) => {
    const storage = new MemoryBudgetStorage();
    await createBudget(storage, T0);
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger missing");
    mutate(state);
    await storage.commit("ledger", state, null);

    await expect(snapshotBudget(storage, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid/,
    );
    const persisted = await storage.get<Record<string, any>>("ledger");
    expect(persisted).toEqual(state);
  });

  it("fails closed for a malformed persisted lease instead of releasing occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("corrupt-lease", { model_calls: 1, input_tokens: 100 }),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("reservation missing");
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger missing");
    state.leases[reserved.lease.lease_id].expires_at = "expired";
    await storage.commit("ledger", state, null);

    await expect(recoverExpiredLeases(storage, T0 + 10_000_000)).rejects.toThrow(
      /persisted_budget_state_invalid:lease_identity_invalid/,
    );
    const persisted = await storage.get<Record<string, any>>("ledger");
    expect(persisted?.reserved.input_tokens).toBe(100);
  });

  it("fails closed when valid-looking aggregate counters do not reconcile to reservations", async () => {
    const storage = new MemoryBudgetStorage();
    await reserveBudget(
      storage,
      leased("counter-divergence", { model_calls: 1, input_tokens: 100 }),
      T0,
    );
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger missing");
    state.reserved.input_tokens = 0;
    await storage.commit("ledger", state, null);

    await expect(snapshotBudget(storage, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid:ledger_occupancy_not_reconciled/,
    );
  });

  it("fails closed when a reservation points outside its persisted lease authority", async () => {
    const storage = new MemoryBudgetStorage();
    await reserveBudget(
      storage,
      leased("lease-divergence", { model_calls: 1, input_tokens: 100 }),
      T0,
    );
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger missing");
    state.reservations["lease-divergence"].lease_id = "missing-lease";
    await storage.commit("ledger", state, null);

    await expect(snapshotBudget(storage, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid:reservation_lease_link_invalid/,
    );
  });

  it("downgrades legacy provider-cost claims to unattributed instead of inventing actual cost", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("legacy-cost", { model_calls: 1, input_tokens: 10, cost_usd: 1 }),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(storage, {
      idempotency_key: "legacy-cost",
      request_digest: testDigest("legacy-cost"),
      lease_id: reserved.lease.lease_id,
    }, T0 + 1);
    if (!started.ok || !started.settlement_capability) throw new Error("capability");
    const finalized = await finalizeBudget(storage, {
      idempotency_key: "legacy-cost",
      request_digest: testDigest("legacy-cost"),
      lease_id: reserved.lease.lease_id,
      settlement_capability: started.settlement_capability,
      usage: actualUsage({ input_tokens: 2, cost_usd: 0.1 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    }, T0 + 2);
    expect(finalized.ok).toBe(true);

    const legacy = await storage.get<Record<string, any>>("ledger");
    if (!legacy) throw new Error("ledger missing");
    delete legacy.reservations["legacy-cost"].settlement.provider_model;
    delete legacy.reservations["legacy-cost"].settlement.pricing_policy_id;
    delete legacy.reservations["legacy-cost"].settlement.pricing_policy_digest;
    await storage.commit("ledger", legacy, null);

    await expect(snapshotBudget(storage, T0 + 3)).resolves.toMatchObject({ ok: true });
    const migrated = await storage.get<Record<string, any>>("ledger");
    expect(migrated?.reservations["legacy-cost"].settlement).toMatchObject({
      usage_source: "legacy_unattributed",
      actual_cost_usd: null,
      billed_cost_usd: 0.1,
      provider_model: null,
      pricing_policy_id: null,
      pricing_policy_digest: null,
    });
  });

  it("fails closed when persisted settlement tokens diverge from billed occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      leased("settlement-divergence", { model_calls: 1, input_tokens: 10, cost_usd: 1 }),
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("lease");
    const started = await markProviderStarted(storage, {
      idempotency_key: "settlement-divergence",
      request_digest: testDigest("settlement-divergence"),
      lease_id: reserved.lease.lease_id,
    }, T0 + 1);
    if (!started.ok || !started.settlement_capability) throw new Error("capability");
    await finalizeBudget(storage, {
      idempotency_key: "settlement-divergence",
      request_digest: testDigest("settlement-divergence"),
      lease_id: reserved.lease.lease_id,
      settlement_capability: started.settlement_capability,
      usage: actualUsage({ input_tokens: 2, cost_usd: 0.1 }),
      terminal_result: { http_status: 200, body: { ok: true } },
    }, T0 + 2);
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger missing");
    state.reservations["settlement-divergence"].settlement.actual_input_tokens = 3;
    await storage.commit("ledger", state, null);

    await expect(snapshotBudget(storage, T0 + 3)).rejects.toThrow(
      /persisted_budget_state_invalid:settlement_counter_binding_invalid/,
    );
  });

  it("binds active reserve replay and cancellation to one invocation owner", async () => {
    const storage = new MemoryBudgetStorage();
    const input = {
      ...leased("owner-bound", { model_calls: 1, input_tokens: 20 }),
      reserve_owner_capability: OWNER_A,
    };
    const first = await reserveBudget(storage, input, T0);
    expect(first).toMatchObject({ ok: true, existing: false, owner_recovered: false });
    if (!first.ok || !first.lease) throw new Error("owner reserve");

    const replay = await reserveBudget(storage, input, T0 + 1);
    expect(replay).toMatchObject({
      ok: true,
      existing: true,
      owner_recovered: true,
      budget_run_id: first.budget_run_id,
    });
    const other = await reserveBudget(
      storage,
      { ...input, reserve_owner_capability: OWNER_B },
      T0 + 2,
    );
    expect(other).toEqual({
      ok: false,
      error: "reservation_owned_by_other_invocation",
    });

    const wrongCancel = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "owner-bound",
        request_digest: testDigest("owner-bound"),
        reserve_owner_capability: OWNER_B,
      },
      T0 + 3,
    );
    expect(wrongCancel).toEqual({
      ok: false,
      error: "reserve_owner_capability_invalid",
    });
    expect(await snapshotBudget(storage, T0 + 3)).toMatchObject({
      ok: true,
      reserved: { model_calls: 1, input_tokens: 20 },
      active_leases: 1,
    });

    const cancelled = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "owner-bound",
        request_digest: testDigest("owner-bound"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 4,
    );
    expect(cancelled).toMatchObject({ ok: true, cancelled: true });
    const cancelReplay = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "owner-bound",
        request_digest: testDigest("owner-bound"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 5,
    );
    expect(cancelReplay).toMatchObject({ ok: true, cancelled: false });
    expect(await snapshotBudget(storage, T0 + 5)).toMatchObject({
      ok: true,
      reserved: { model_calls: 0, input_tokens: 0 },
      used: { model_calls: 0, input_tokens: 0 },
      active_leases: 0,
    });

    const delayedSameOwner = await reserveBudget(storage, input, T0 + 6);
    expect(delayedSameOwner).toEqual({ ok: false, error: "reservation_released" });
    expect(await snapshotBudget(storage, T0 + 6)).toMatchObject({
      ok: true,
      reserved: { model_calls: 0, input_tokens: 0 },
      active_leases: 0,
    });

    const freshOwner = await reserveBudget(
      storage,
      { ...input, reserve_owner_capability: OWNER_B },
      T0 + 7,
    );
    expect(freshOwner).toMatchObject({ ok: true, existing: false });
    if (!freshOwner.ok) throw new Error("fresh owner reserve");
    expect(freshOwner.budget_run_id).not.toBe(first.budget_run_id);
    await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "owner-bound",
        request_digest: testDigest("owner-bound"),
        reserve_owner_capability: OWNER_B,
      },
      T0 + 8,
    );

    const persisted = await storage.get<Record<string, any>>("ledger");
    const persistedOwnerHash = String(
      persisted?.reservations["owner-bound"].reserve_owner_capability_hash || "",
    );
    expect(persistedOwnerHash).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.stringify(persisted)).not.toContain(OWNER_A);
    expect(JSON.stringify(first)).not.toContain(OWNER_A);
    expect(JSON.stringify(first)).not.toContain(persistedOwnerHash);
    expect(first.reservation).not.toHaveProperty("reserve_owner_capability_hash");
  });

  it("persists cancellation authority before reserve and rejects the delayed same owner", async () => {
    const storage = new MemoryBudgetStorage();
    const cancelledFirst = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "cancel-before-reserve",
        request_digest: testDigest("cancel-before-reserve"),
        reserve_owner_capability: OWNER_A,
      },
      T0,
    );
    expect(cancelledFirst).toEqual({
      ok: true,
      cancelled: false,
      tombstoned: true,
      reservation: null,
      budget_run_id: null,
    });
    expect(await storage.getAlarm()).toBe(
      T0 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    const persisted = await storage.get<Record<string, any>>("ledger");
    expect(Object.values(persisted?.owner_cancellation_tombstones ?? {})).toHaveLength(1);
    expect(JSON.stringify(persisted)).not.toContain(OWNER_A);

    const delayedSameOwner = await reserveOwnedBudget(
      storage,
      {
        ...leased("cancel-before-reserve", { model_calls: 1 }),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 1,
    );
    expect(delayedSameOwner).toEqual({ ok: false, error: "reservation_released" });
    expect(await snapshotBudget(storage, T0 + 1)).toMatchObject({
      ok: true,
      reserved: { model_calls: 0 },
      active_leases: 0,
    });

    const differentOwner = await reserveOwnedBudget(
      storage,
      {
        ...leased("cancel-before-reserve", { model_calls: 1 }),
        reserve_owner_capability: OWNER_B,
      },
      T0 + 2,
    );
    expect(differentOwner).toMatchObject({ ok: true, existing: false });
  });

  it("migrates legacy state and removes expired owner cancellation tombstones", async () => {
    const legacyStorage = new MemoryBudgetStorage();
    await createBudget(legacyStorage, T0);
    const legacy = await legacyStorage.get<Record<string, any>>("ledger");
    if (!legacy) throw new Error("legacy ledger");
    delete legacy.owner_cancellation_tombstones;
    delete legacy.owner_cancellation_quarantine_until;
    await legacyStorage.commit("ledger", legacy, null);
    expect(await snapshotBudget(legacyStorage, T0 + 1)).toMatchObject({ ok: true });
    const migrated = await legacyStorage.get<Record<string, any>>("ledger");
    expect(migrated?.owner_cancellation_tombstones).toEqual({});
    expect(migrated?.owner_cancellation_quarantine_until).toBeNull();

    const storage = new MemoryBudgetStorage();
    await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "expiring-cancel",
        request_digest: testDigest("expiring-cancel"),
        reserve_owner_capability: OWNER_A,
      },
      T0,
    );
    const afterExpiry = await reserveOwnedBudget(
      storage,
      {
        ...leased("expiring-cancel", { model_calls: 1 }),
        reserve_owner_capability: OWNER_A,
      },
      T0 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    expect(afterExpiry).toMatchObject({ ok: true, existing: false });
    const cleaned = await storage.get<Record<string, any>>("ledger");
    expect(cleaned?.owner_cancellation_tombstones).toEqual({});

    const corrupt = new MemoryBudgetStorage();
    await cancelPreProviderReservation(
      corrupt,
      {
        idempotency_key: "corrupt-cancel",
        request_digest: testDigest("corrupt-cancel"),
        reserve_owner_capability: OWNER_A,
      },
      T0,
    );
    const corruptState = await corrupt.get<Record<string, any>>("ledger");
    if (!corruptState) throw new Error("corrupt ledger");
    const tombstone = Object.values(
      corruptState.owner_cancellation_tombstones,
    )[0] as Record<string, unknown>;
    tombstone.expires_at = T0 - 1;
    await corrupt.commit("ledger", corruptState, null);
    await expect(snapshotBudget(corrupt, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid:owner_cancellation_tombstone_invalid/,
    );

    const corruptQuarantine = new MemoryBudgetStorage();
    await createBudget(corruptQuarantine, T0);
    const corruptQuarantineState = await corruptQuarantine.get<
      Record<string, any>
    >("ledger");
    if (!corruptQuarantineState) throw new Error("corrupt quarantine ledger");
    corruptQuarantineState.owner_cancellation_quarantine_until = "later";
    await corruptQuarantine.commit("ledger", corruptQuarantineState, null);
    await expect(snapshotBudget(corruptQuarantine, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid:owner_cancellation_quarantine_until_invalid/,
    );
  });

  it("fails closed when persisted cancellation tombstones exceed bounded capacity", async () => {
    const storage = new MemoryBudgetStorage();
    await createBudget(storage, T0);
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger");
    state.owner_cancellation_tombstones = Object.fromEntries(
      Array.from(
        { length: MAX_OWNER_CANCELLATION_TOMBSTONES + 1 },
        (_, index) => {
          const ownerHash = index.toString(16).padStart(64, "0");
          return [
            ownerHash,
            {
              owner_capability_hash: ownerHash,
              idempotency_key: `bounded-${index}`,
              request_digest: testDigest(`bounded-${index}`),
              created_at: T0,
              expires_at: T0 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
            },
          ];
        },
      ),
    );
    await storage.commit("ledger", state, null);
    await expect(snapshotBudget(storage, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid:owner_cancellation_tombstones_over_capacity/,
    );
  });

  it("spends reserved headroom on durable quarantine before near-limit occupancy can reappear", async () => {
    const storage = new MemoryBudgetStorage();
    await createBudget(storage, T0);
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger");

    // Model a pre-row-migration ledger whose retained history is already just
    // beyond the new mutable byte budget. The unbounded history layout remains a known
    // residual; this correction makes its failure mode explicit and closed.
    state.frozen_reason = "";
    const withoutPadding = new TextEncoder().encode(JSON.stringify(state)).byteLength;
    const legacyBytes = MAX_MUTABLE_LEDGER_STATE_BYTES + 1024;
    state.frozen_reason = "x".repeat(
      legacyBytes - withoutPadding,
    );
    expect(new TextEncoder().encode(JSON.stringify(state)).byteLength).toBe(
      legacyBytes,
    );
    await storage.commit("ledger", state, null);

    const digest = testDigest("near-limit-cancel");
    const cancelled = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "near-limit-cancel",
        request_digest: digest,
        reserve_owner_capability: OWNER_A,
      },
      T0 + 1,
    );
    expect(cancelled).toEqual({
      ok: false,
      error: "owner_cancellation_tombstone_capacity_exhausted",
    });

    const quarantined = await storage.get<Record<string, any>>("ledger");
    expect(quarantined?.owner_cancellation_tombstones).toEqual({});
    expect(quarantined?.owner_cancellation_quarantine_until).toBe(
      T0 + 1 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    expect(new TextEncoder().encode(JSON.stringify(quarantined)).byteLength).toBeLessThanOrEqual(
      MAX_SERIALIZED_LEDGER_STATE_BYTES,
    );

    const delayedReserve = await reserveOwnedBudget(
      storage,
      {
        ...leased("near-limit-cancel", { model_calls: 1 }, digest),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 2,
    );
    expect(delayedReserve).toEqual({
      ok: false,
      error: "budget_frozen",
      detail: "owner_cancellation_tombstone_capacity_exhausted",
    });
  });

  it("fails closed on a pre-existing whole-state value beyond the safe limit", async () => {
    const storage = new MemoryBudgetStorage();
    await createBudget(storage, T0);
    const state = await storage.get<Record<string, any>>("ledger");
    if (!state) throw new Error("ledger");
    state.frozen_reason = "x".repeat(MAX_SERIALIZED_LEDGER_STATE_BYTES);
    await storage.commit("ledger", state, null);

    await expect(snapshotBudget(storage, T0 + 1)).rejects.toThrow(
      /persisted_budget_state_invalid:ledger_serialized_size_exceeds_safe_limit/,
    );
  });

  it("durably quarantines fresh occupancy when cancellation capacity is full", async () => {
    const storage = new MemoryBudgetStorage();
    await createBudget(storage, T0);
    await fillOwnerCancellationTombstoneCapacity(storage, T0);

    const saturatedCancel = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "capacity-cancel-before-reserve",
        request_digest: testDigest("capacity-cancel-before-reserve"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 1,
    );
    expect(saturatedCancel).toEqual({
      ok: false,
      error: "owner_cancellation_tombstone_capacity_exhausted",
    });
    const quarantined = await storage.get<Record<string, any>>("ledger");
    expect(quarantined?.owner_cancellation_quarantine_until).toBe(
      T0 + 1 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    const quarantinedBytes = new TextEncoder().encode(
      JSON.stringify(quarantined),
    ).byteLength;
    expect(quarantinedBytes).toBeLessThanOrEqual(
      MAX_SERIALIZED_LEDGER_STATE_BYTES,
    );
    expect(await storage.getAlarm()).toBe(
      T0 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );

    for (const input of [
      {
        ...leased("capacity-cancel-before-reserve", { model_calls: 1 }),
        reserve_owner_capability: OWNER_A,
      },
      {
        ...leased("capacity-fresh-owner", { model_calls: 1 }),
        reserve_owner_capability: OWNER_B,
      },
    ]) {
      const denied = await reserveOwnedBudget(storage, input, T0 + 2);
      expect(denied).toEqual({
        ok: false,
        error: "budget_frozen",
        detail: "owner_cancellation_tombstone_capacity_exhausted",
      });
    }
    expect(await snapshotBudget(storage, T0 + 2)).toMatchObject({
      ok: true,
      reserved: { model_calls: 0 },
      active_leases: 0,
      owner_cancellation_quarantined: true,
      owner_cancellation_quarantine_until:
        T0 + 1 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    });

    await recoverExpiredLeases(
      storage,
      T0 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    expect(await storage.getAlarm()).toBe(
      T0 + 1 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    const stillDenied = await reserveOwnedBudget(
      storage,
      {
        ...leased("capacity-after-tombstone-expiry", { model_calls: 1 }),
        reserve_owner_capability: OWNER_B,
      },
      T0 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    expect(stillDenied).toMatchObject({ ok: false, error: "budget_frozen" });

    const afterQuarantine = await reserveOwnedBudget(
      storage,
      {
        ...leased("capacity-after-quarantine", { model_calls: 1 }),
        reserve_owner_capability: OWNER_B,
      },
      T0 + 1 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    );
    expect(afterQuarantine).toMatchObject({ ok: true, existing: false });
    expect(await snapshotBudget(
      storage,
      T0 + 1 + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
    )).toMatchObject({
      ok: true,
      owner_cancellation_quarantined: false,
      owner_cancellation_quarantine_until: null,
    });
  });

  it("quarantines active recovery but preserves exact reconciled terminal replay", async () => {
    const storage = new MemoryBudgetStorage();
    const terminalInput = {
      ...leased("terminal-before-capacity", { model_calls: 1, input_tokens: 4 }),
      reserve_owner_capability: OWNER_A,
    };
    const terminalReserve = await reserveOwnedBudget(storage, terminalInput, T0);
    if (!terminalReserve.ok || !terminalReserve.lease) {
      throw new Error("terminal reserve");
    }
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: terminalInput.idempotency_key,
        request_digest: terminalInput.request_digest,
        lease_id: terminalReserve.lease.lease_id,
        reserve_owner_capability: OWNER_A,
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) {
      throw new Error("terminal start");
    }
    const finalized = await finalizeBudget(
      storage,
      {
        idempotency_key: terminalInput.idempotency_key,
        request_digest: terminalInput.request_digest,
        lease_id: terminalReserve.lease.lease_id,
        reserve_owner_capability: OWNER_A,
        settlement_capability: started.settlement_capability,
        usage: actualUsage({ input_tokens: 2 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 2,
    );
    expect(finalized).toMatchObject({ ok: true });

    const activeInput = {
      ...leased("active-before-capacity", { model_calls: 1, input_tokens: 3 }),
      reserve_owner_capability: OWNER_A,
    };
    const active = await reserveOwnedBudget(storage, activeInput, T0 + 3);
    expect(active).toMatchObject({ ok: true, existing: false });
    await fillOwnerCancellationTombstoneCapacity(storage, T0 + 3);

    const saturatedCancel = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: activeInput.idempotency_key,
        request_digest: activeInput.request_digest,
        reserve_owner_capability: OWNER_A,
      },
      T0 + 4,
    );
    expect(saturatedCancel).toMatchObject({
      ok: false,
      error: "owner_cancellation_tombstone_capacity_exhausted",
    });
    const delayedActiveRecovery = await reserveOwnedBudget(
      storage,
      activeInput,
      T0 + 5,
    );
    expect(delayedActiveRecovery).toEqual({
      ok: false,
      error: "budget_frozen",
      detail: "owner_cancellation_tombstone_capacity_exhausted",
    });

    const terminalReplayFromDifferentOwner = await reserveOwnedBudget(
      storage,
      { ...terminalInput, reserve_owner_capability: OWNER_B },
      T0 + 5,
    );
    expect(terminalReplayFromDifferentOwner).toMatchObject({
      ok: true,
      existing: true,
      owner_recovered: false,
      budget_run_id: terminalReserve.budget_run_id,
      reservation: { status: "reconciled" },
    });
    expect(await snapshotBudget(storage, T0 + 5)).toMatchObject({
      ok: true,
      reserved: { model_calls: 1, input_tokens: 3 },
      used: { model_calls: 1, input_tokens: 2 },
      active_leases: 1,
      owner_cancellation_quarantined: true,
    });
  });

  it("requires the reserve owner at provider start and refuses cancellation after start", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        ...leased("owner-start", { model_calls: 1, input_tokens: 9 }),
        reserve_owner_capability: OWNER_A,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("owner reserve");

    for (const capability of [undefined, OWNER_B]) {
      const denied = await markProviderStarted(
        storage,
        {
          idempotency_key: "owner-start",
          request_digest: testDigest("owner-start"),
          lease_id: reserved.lease.lease_id,
          reserve_owner_capability: capability,
        },
        T0 + 1,
      );
      expect(denied).toEqual({
        ok: false,
        error: "reserve_owner_capability_invalid",
      });
    }
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "owner-start",
        request_digest: testDigest("owner-start"),
        lease_id: reserved.lease.lease_id,
        reserve_owner_capability: OWNER_A,
      },
      T0 + 2,
    );
    expect(started.ok).toBe(true);

    const cancelStarted = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "owner-start",
        request_digest: testDigest("owner-start"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 3,
    );
    expect(cancelStarted).toEqual({
      ok: false,
      error: "reservation_not_cancellable",
    });
    const releaseWithoutOwner = await releaseBudget(
      storage,
      {
        idempotency_key: "owner-start",
        lease_id: reserved.lease.lease_id,
      },
      T0 + 4,
    );
    expect(releaseWithoutOwner).toEqual({
      ok: false,
      error: "reservation_not_cancellable",
    });
    const releaseWithOwner = await releaseBudget(
      storage,
      {
        idempotency_key: "owner-start",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("owner-start"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 4,
    );
    expect(releaseWithOwner).toEqual({
      ok: false,
      error: "reservation_not_cancellable",
    });
    expect(await snapshotBudget(storage, T0 + 4)).toMatchObject({
      ok: true,
      reserved: { model_calls: 1, input_tokens: 9 },
      active_leases: 1,
    });
  });

  it("requires the owner for settlement and rejects owner material in the terminal cache", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      {
        ...leased("owner-settle", { model_calls: 1, input_tokens: 9 }),
        reserve_owner_capability: OWNER_A,
      },
      T0,
    );
    if (!reserved.ok || !reserved.lease) throw new Error("owner reserve");
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "owner-settle",
        request_digest: testDigest("owner-settle"),
        lease_id: reserved.lease.lease_id,
        reserve_owner_capability: OWNER_A,
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("owner start");

    for (const capability of [undefined, OWNER_B]) {
      const denied = await finalizeBudget(
        storage,
        {
          idempotency_key: "owner-settle",
          request_digest: testDigest("owner-settle"),
          lease_id: reserved.lease.lease_id,
          settlement_capability: started.settlement_capability,
          reserve_owner_capability: capability,
          usage: actualUsage({ input_tokens: 2 }),
          terminal_result: { http_status: 200, body: { ok: true } },
        },
        T0 + 2,
      );
      expect(denied).toEqual({
        ok: false,
        error: "reserve_owner_capability_invalid",
      });
    }

    const smuggled = await finalizeBudget(
      storage,
      {
        idempotency_key: "owner-settle",
        request_digest: testDigest("owner-settle"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        reserve_owner_capability: OWNER_A,
        usage: actualUsage({ input_tokens: 2 }),
        terminal_result: {
          http_status: 200,
          body: { ok: true, artifact: { nested: { owner: OWNER_A } } },
        },
      },
      T0 + 3,
    );
    expect(smuggled).toEqual({
      ok: false,
      error: "cached_result_capability_material",
    });
    const afterReject = await storage.get<Record<string, any>>("ledger");
    expect(afterReject?.reservations["owner-settle"]).toMatchObject({
      status: "reserved",
      cached_result: null,
      settlement_capability_consumed: false,
    });
    expect(JSON.stringify(afterReject)).not.toContain(OWNER_A);

    const finalized = await finalizeBudget(
      storage,
      {
        idempotency_key: "owner-settle",
        request_digest: testDigest("owner-settle"),
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        reserve_owner_capability: OWNER_A,
        usage: actualUsage({ input_tokens: 2 }),
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 4,
    );
    expect(finalized.ok).toBe(true);
    const terminalBefore = JSON.stringify(await storage.get("ledger"));
    const cancelTerminal = await cancelPreProviderReservation(
      storage,
      {
        idempotency_key: "owner-settle",
        request_digest: testDigest("owner-settle"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 5,
    );
    expect(cancelTerminal).toEqual({ ok: false, error: "reservation_not_cancellable" });
    const releaseTerminal = await releaseBudget(
      storage,
      {
        idempotency_key: "owner-settle",
        lease_id: reserved.lease.lease_id,
        request_digest: testDigest("owner-settle"),
        reserve_owner_capability: OWNER_A,
      },
      T0 + 5,
    );
    expect(releaseTerminal).toEqual({ ok: false, error: "reservation_not_cancellable" });
    expect(JSON.stringify(await storage.get("ledger"))).toBe(terminalBefore);
  });
});
