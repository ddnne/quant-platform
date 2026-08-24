import { describe, expect, it } from "vitest";
import {
  PILOT_BUDGET_CAPS,
  MemoryBudgetStorage,
  createBudget,
  heartbeatLease,
  reconcileBudget,
  recoverExpiredLeases,
  releaseBudget,
  reserveBudget,
  snapshotBudget,
} from "./budget_do";

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
});
