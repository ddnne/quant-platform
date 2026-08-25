import { describe, expect, it } from "vitest";
import {
  PILOT_BUDGET_CAPS,
  CONTROL_PLANE_LEDGER_NAME,
  MemoryBudgetStorage,
  bindIdempotencyKey,
  createBudget,
  finalizeBudget,
  heartbeatLease,
  markProviderStarted,
  recoverExpiredLeases,
  releaseBudget,
  reserveBudget,
  settleUncertainBudget,
  snapshotBudget,
  zeroCounters,
} from "./budget_do";

/** In-memory ledger algebra. Live Cloudflare Durable Object occupancy is unproven. */

const T0 = 1_700_000_000_000;

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
      { idempotency_key: "k-create-not-grant", amounts: { model_calls: 1 } },
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
      { idempotency_key: "fill", amounts: { model_calls: 16 } },
      T0,
    );
    expect(fill.ok).toBe(true);
    const denied = await reserveBudget(
      storage,
      { idempotency_key: "next", amounts: { model_calls: 1 } },
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

  it("same idempotency key returns the same reservation without double-spend", async () => {
    const storage = new MemoryBudgetStorage();
    const a = await reserveBudget(
      storage,
      { idempotency_key: "k1", amounts: { model_calls: 1, input_tokens: 10 } },
      T0,
    );
    const b = await reserveBudget(
      storage,
      { idempotency_key: "k1", amounts: { model_calls: 1, input_tokens: 10 } },
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
        request_digest: "digest-k1",
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
        request_digest: "digest-k1",
      },
      T0 + 1,
    );
    expect(started.ok).toBe(true);
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const first = await finalizeBudget(
      storage,
      {
        idempotency_key: "k1",
        request_digest: "digest-k1",
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: { model_calls: 1, input_tokens: 12, output_tokens: 7 },
        terminal_result: { http_status: 200, body: { ok: true } },
      },
      T0 + 2,
    );
    const second = await finalizeBudget(
      storage,
      {
        idempotency_key: "k1",
        request_digest: "digest-k1",
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: { model_calls: 1, input_tokens: 99, output_tokens: 99 },
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

  it("concurrent leases are capped at max_parallel_experiments=2", async () => {
    const storage = new MemoryBudgetStorage();
    const a = await reserveBudget(
      storage,
      { idempotency_key: "l1", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    const b = await reserveBudget(
      storage,
      { idempotency_key: "l2", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    const c = await reserveBudget(
      storage,
      { idempotency_key: "l3", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    expect(a.ok).toBe(true);
    expect(b.ok).toBe(true);
    expect(c.ok).toBe(false);
    if (!c.ok) expect(c.detail).toContain("concurrent_experiments");
    const snap = await snapshotBudget(storage, T0);
    expect(snap.ok).toBe(true);
    if (snap.ok) expect(snap.active_leases).toBe(2);
  });

  it("heartbeat extends TTL by 1800s", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      { idempotency_key: "hb", amounts: { model_calls: 1 }, acquire_lease: true },
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
      { idempotency_key: "rel", amounts: { model_calls: 4 }, acquire_lease: true },
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
        request_digest: "digest-retry",
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
        request_digest: "digest-retry",
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
      { idempotency_key: "mismatch-a", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    const second = await reserveBudget(
      storage,
      { idempotency_key: "mismatch-b", amounts: { model_calls: 1 }, acquire_lease: true },
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
      { idempotency_key: "old", amounts: { model_calls: 8 }, acquire_lease: true },
      T0,
    );
    expect(first.ok).toBe(true);
    const recovered = await recoverExpiredLeases(storage, T0 + 1800 * 1000 + 1);
    expect(recovered.ok).toBe(true);
    if (recovered.ok) expect(recovered.recovered).toBe(1);
    const again = await reserveBudget(
      storage,
      { idempotency_key: "new", amounts: { model_calls: 8 }, acquire_lease: true },
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
        request_digest: "digest-uncertain-expiry",
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
        request_digest: "digest-uncertain-expiry",
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
        request_digest: "digest-no-zero-release",
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
        request_digest: "digest-no-zero-release",
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
        request_digest: "digest-uncertain",
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
        request_digest: "digest-uncertain",
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const first = await settleUncertainBudget(
      storage,
      {
        idempotency_key: "uncertain-idempotent",
        reason: "finalize_failed",
        request_digest: "digest-uncertain",
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
        request_digest: "digest-uncertain",
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
        request_digest: "digest-uncertain",
        amounts: { model_calls: 1 },
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
        request_digest: "digest-freeze-first",
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    const second = await reserveBudget(
      storage,
      {
        idempotency_key: "freeze-second",
        request_digest: "digest-freeze-second",
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
        request_digest: "digest-freeze-first",
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    await settleUncertainBudget(
      storage,
      {
        idempotency_key: "freeze-first",
        reason: "provider_error",
        request_digest: "digest-freeze-first",
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
        request_digest: "digest-freeze-second",
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
      { idempotency_key: "a", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    await reserveBudget(
      storage,
      { idempotency_key: "b", amounts: { model_calls: 1 }, acquire_lease: true },
      T0,
    );
    const third = await reserveBudget(
      storage,
      { idempotency_key: "c", amounts: { model_calls: 1 }, acquire_lease: true },
      T0 + 1800 * 1000 + 1,
    );
    expect(third.ok).toBe(true);
  });

  it("cost cap is enforced in USD", async () => {
    const storage = new MemoryBudgetStorage();
    const fill = await reserveBudget(
      storage,
      { idempotency_key: "cost", amounts: { cost_usd: 20 } },
      T0,
    );
    expect(fill.ok).toBe(true);
    const denied = await reserveBudget(
      storage,
      { idempotency_key: "cost2", amounts: { cost_usd: 0.01 } },
      T0,
    );
    expect(denied.ok).toBe(false);
    if (!denied.ok) expect(denied.detail).toContain("cost_usd");
  });

  it("issues an opaque budget_run_id; caller key is not occupancy", async () => {
    const storage = new MemoryBudgetStorage();
    const reserved = await reserveBudget(
      storage,
      { idempotency_key: "client-label", amounts: { model_calls: 1 } },
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
        request_digest: "digest-a",
        amounts: { model_calls: 1 },
      },
      T0,
    );
    const dup = await reserveBudget(
      storage,
      {
        idempotency_key: "k-dup",
        request_digest: "digest-a",
        amounts: { model_calls: 1 },
      },
      T0 + 1,
    );
    const clash = await reserveBudget(
      storage,
      {
        idempotency_key: "k-dup",
        request_digest: "digest-b",
        amounts: { model_calls: 1 },
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
        request_digest: "digest-schema-reject",
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
        request_digest: "digest-schema-reject",
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const charged = await finalizeBudget(
      storage,
      {
        idempotency_key: "schema-reject",
        request_digest: "digest-schema-reject",
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: { model_calls: 1, input_tokens: 12, output_tokens: 4 },
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
        request_digest: "digest-over",
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
        request_digest: "digest-over",
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const over = await finalizeBudget(
      storage,
      {
        idempotency_key: "over",
        request_digest: "digest-over",
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: { model_calls: 1, input_tokens: 11 },
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
      { idempotency_key: "after-freeze", amounts: { model_calls: 1 } },
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
        request_digest: "digest-unstarted",
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
        request_digest: "digest-unstarted",
        lease_id: reserved.lease.lease_id,
        settlement_capability: "0".repeat(64),
        usage: { model_calls: 0, cost_usd: 0 },
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
        request_digest: "digest-a",
        amounts: { model_calls: 1, input_tokens: 10 },
        acquire_lease: true,
      },
      T0,
    );
    const second = await reserveBudget(
      storage,
      {
        idempotency_key: "cap-b",
        request_digest: "digest-b",
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
        request_digest: "digest-a",
      },
      T0 + 1,
    );
    const startedB = await markProviderStarted(
      storage,
      {
        idempotency_key: "cap-b",
        lease_id: second.lease.lease_id,
        request_digest: "digest-b",
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
          request_digest: "digest-a",
          lease_id: first.lease.lease_id,
          settlement_capability: "ff".repeat(32),
          usage: { model_calls: 1, input_tokens: 4 },
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: "digest-b",
          lease_id: first.lease.lease_id,
          settlement_capability: startedA.settlement_capability,
          usage: { model_calls: 1, input_tokens: 4 },
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "request_digest_mismatch" });

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: "digest-a",
          lease_id: second.lease.lease_id,
          settlement_capability: startedA.settlement_capability,
          usage: { model_calls: 1, input_tokens: 4 },
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "lease_mismatch" });

    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "cap-a",
          request_digest: "digest-a",
          lease_id: first.lease.lease_id,
          settlement_capability: startedB.settlement_capability,
          usage: { model_calls: 1, input_tokens: 4 },
        },
        T0 + 2,
      ),
    ).toMatchObject({ ok: false, error: "settlement_capability_invalid" });

    const committed = await finalizeBudget(
      storage,
      {
        idempotency_key: "cap-a",
        request_digest: "digest-a",
        lease_id: first.lease.lease_id,
        settlement_capability: startedA.settlement_capability,
        usage: { model_calls: 1, input_tokens: 4 },
        terminal_result: { http_status: 200, body: { ok: true, artifact: "kept" } },
      },
      T0 + 3,
    );
    expect(committed.ok).toBe(true);
    const replay = await finalizeBudget(
      storage,
      {
        idempotency_key: "cap-a",
        request_digest: "digest-a",
        lease_id: first.lease.lease_id,
        settlement_capability: startedA.settlement_capability,
        usage: { model_calls: 1, input_tokens: 99 },
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
        request_digest: "digest-inject",
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
        request_digest: "digest-inject",
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    const injected = await finalizeBudget(
      storage,
      {
        idempotency_key: "inject",
        request_digest: "digest-inject",
        lease_id: reserved.lease.lease_id,
        settlement_capability: started.settlement_capability,
        usage: { model_calls: 1, input_tokens: 8, cost_usd: 0.2 },
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
        request_digest: "digest-binding",
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
          request_digest: "digest-binding",
        },
        T0 + 1,
      ),
    ).toMatchObject({ ok: false, error: "lease_id required" });
    const started = await markProviderStarted(
      storage,
      {
        idempotency_key: "binding-required",
        lease_id: reserved.lease.lease_id,
        request_digest: "digest-binding",
      },
      T0 + 1,
    );
    if (!started.ok || !started.settlement_capability) throw new Error("cap");
    expect(started.reservation.settlement_capability_secret).toBeNull();
    expect(started.reservation.settlement_capability_hash).toBe("sha256:redacted");
    expect(
      await finalizeBudget(
        storage,
        {
          idempotency_key: "binding-required",
          request_digest: "",
          lease_id: reserved.lease.lease_id,
          settlement_capability: started.settlement_capability,
          usage: { model_calls: 1, input_tokens: 2 },
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
          request_digest: "digest-binding",
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
        request_digest: "digest-start-retry",
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
        request_digest: "digest-start-retry",
      },
      T0 + 1,
    );
    const lostResponseRetry = await markProviderStarted(
      storage,
      {
        idempotency_key: "start-retry",
        lease_id: reserved.lease.lease_id,
        request_digest: "digest-start-retry",
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
        request_digest: "digest-start-retry",
        lease_id: reserved.lease.lease_id,
        settlement_capability: lostResponseRetry.settlement_capability as string,
        usage: { model_calls: 1, input_tokens: 3 },
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
        request_digest: "digest-start-retry",
      },
      T0 + 4,
    );
    expect(afterConsume).toMatchObject({ ok: false, error: "reservation_reconciled" });
  });

  it("bindIdempotencyKey uses digest when the client key is absent", () => {
    const bound = bindIdempotencyKey(undefined, "abc");
    expect(bound.ok).toBe(true);
    if (bound.ok) {
      expect(bound.idempotency_key).toBe("digest:abc");
      expect(bound.request_digest).toBe("abc");
    }
    const named = bindIdempotencyKey("k1", "abc");
    expect(named.ok).toBe(true);
    if (named.ok) expect(named.idempotency_key).toBe("k1");
  });
});
