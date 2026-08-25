import { describe, expect, it } from "vitest";
import {
  PILOT_BUDGET_CAPS,
  CONTROL_PLANE_LEDGER_NAME,
  MemoryBudgetStorage,
  bindIdempotencyKey,
  createBudget,
  finalizeBudget,
  heartbeatLease,
  reconcileBudget,
  recoverExpiredLeases,
  releaseBudget,
  reserveBudget,
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

  it("reconcile is idempotent and converts reserved into used", async () => {
    const storage = new MemoryBudgetStorage();
    await reserveBudget(
      storage,
      { idempotency_key: "k1", amounts: { model_calls: 1, input_tokens: 40, output_tokens: 10 } },
      T0,
    );
    const first = await reconcileBudget(
      storage,
      { idempotency_key: "k1", amounts: { model_calls: 1, input_tokens: 12, output_tokens: 7 } },
      T0 + 1,
    );
    const second = await reconcileBudget(
      storage,
      { idempotency_key: "k1", amounts: { model_calls: 1, input_tokens: 99, output_tokens: 99 } },
      T0 + 2,
    );
    expect(first.ok && second.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 2);
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
        amounts: { model_calls: 1, input_tokens: 40, output_tokens: 16 },
        acquire_lease: true,
      },
      T0,
    );
    expect(reserved.ok).toBe(true);
    const charged = await finalizeBudget(
      storage,
      {
        idempotency_key: "schema-reject",
        amounts: { model_calls: 1, input_tokens: 12, output_tokens: 4 },
        result: { http_status: 400, body: { ok: false, error: "Insight.unknown field" } },
      },
      T0 + 1,
    );
    expect(charged.ok).toBe(true);
    const snap = await snapshotBudget(storage, T0 + 1);
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
    await reserveBudget(
      storage,
      { idempotency_key: "over", amounts: { model_calls: 1, input_tokens: 10 } },
      T0,
    );
    const over = await finalizeBudget(
      storage,
      { idempotency_key: "over", amounts: { model_calls: 1, input_tokens: 11 } },
      T0 + 1,
    );
    expect(over.ok).toBe(false);
    if (!over.ok) expect(over.error).toBe("actual_exceeds_reserved");
    const snap = await snapshotBudget(storage, T0 + 1);
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
