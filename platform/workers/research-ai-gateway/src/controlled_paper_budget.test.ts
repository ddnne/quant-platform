import { describe, expect, it } from "vitest";
import { MemoryBudgetStorage, createBudget } from "./budget_do";
import {
  CONTROLLED_PAPER_BUDGET_AMOUNTS,
  cancelControlledPaper,
  finalizeControlledPaper,
  queryControlledPaper,
  reserveControlledPaper,
} from "./controlled_paper_budget";

const T0 = 1_700_000_000_000;
const OWNER = "a".repeat(64);

function digest(label: string): string {
  const seed = Array.from(new TextEncoder().encode(label), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return seed.repeat(Math.ceil(64 / seed.length)).slice(0, 64);
}

async function primed(): Promise<MemoryBudgetStorage> {
  const storage = new MemoryBudgetStorage();
  await createBudget(storage, T0);
  return storage;
}

describe("controlled paper budget wrapper", () => {
  it("reserves zero provider amounts", async () => {
    const storage = await primed();
    const reserved = await reserveControlledPaper(storage, {
      idempotency_key: "controlled-paper-1",
      request_digest: digest("controlled-paper-1"),
      reserve_owner_capability: OWNER,
    });
    expect(reserved.ok).toBe(true);
    if (!reserved.ok) return;
    expect(reserved.reservation.amounts).toMatchObject(CONTROLLED_PAPER_BUDGET_AMOUNTS);
    expect(CONTROLLED_PAPER_BUDGET_AMOUNTS.paper_runs).toBe(4);
    expect(CONTROLLED_PAPER_BUDGET_AMOUNTS.model_calls).toBe(0);
    expect(CONTROLLED_PAPER_BUDGET_AMOUNTS.cost_usd).toBe(0);
  });

  it("finalizes actual paper occupancy without a provider start", async () => {
    const storage = await primed();
    const input = {
      idempotency_key: "controlled-paper-success",
      request_digest: digest("controlled-paper-success"),
      reserve_owner_capability: OWNER,
    };
    const reserved = await reserveControlledPaper(storage, input);
    expect(reserved.ok).toBe(true);
    if (!reserved.ok) return;
    const finalized = await finalizeControlledPaper(storage, {
      ...input,
      lease_id: reserved.lease.lease_id,
    });
    expect(finalized.ok).toBe(true);
    if (!finalized.ok) return;
    expect(finalized.reservation.settlement?.provider_model).toBeNull();
    expect(finalized.reservation.actual?.model_calls).toBe(0);
    expect(finalized.reservation.actual?.paper_runs).toBe(4);
  });

  it("cancels schema reject, container error, and timeout before provider start", async () => {
    for (const suffix of ["schema", "error", "timeout"]) {
      const storage = await primed();
      const input = {
        idempotency_key: `controlled-paper-${suffix}`,
        request_digest: digest(`controlled-paper-${suffix}`),
        reserve_owner_capability: OWNER,
      };
      const reserved = await reserveControlledPaper(storage, input);
      expect(reserved.ok).toBe(true);
      const cancelled = await cancelControlledPaper(storage, input);
      expect(cancelled.ok).toBe(true);
    }
  });

  it("replays the same reservation for an identical retry", async () => {
    const storage = await primed();
    const input = {
      idempotency_key: "controlled-paper-retry",
      request_digest: digest("controlled-paper-retry"),
      reserve_owner_capability: OWNER,
    };
    const first = await reserveControlledPaper(storage, input);
    const second = await reserveControlledPaper(storage, input);
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    if (!first.ok || !second.ok) return;
    expect(second.existing).toBe(true);
    expect(second.reservation.reservation_id).toBe(first.reservation.reservation_id);
  });

  it("query never creates a reservation", async () => {
    const storage = await primed();
    const input = {
      idempotency_key: "controlled-paper-query",
      request_digest: digest("controlled-paper-query"),
      reserve_owner_capability: OWNER,
    };
    const missing = await queryControlledPaper(storage, input);
    expect(missing.ok).toBe(false);
    if (missing.ok) return;
    expect(missing.error).toBe("reservation_not_found");
    const reserved = await reserveControlledPaper(storage, input);
    expect(reserved.ok).toBe(true);
    const queried = await queryControlledPaper(storage, input);
    expect(queried.ok).toBe(true);
    if (!reserved.ok || !queried.ok) return;
    expect(queried.reservation.reservation_id).toBe(reserved.reservation.reservation_id);
  });
});
