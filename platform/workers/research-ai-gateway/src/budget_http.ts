/** Budget HTTP dispatcher. Occupancy algebra stays in budget_do. Presence of budget_id is not a reserve. */

import { DurableObject } from "cloudflare:workers";

import {
  createBudget,
  createBudgetCoordinator,
  finalizeBudget,
  heartbeatLease,
  markProviderStarted,
  recoverExpiredLeases,
  releaseBudget,
  reserveBudget,
  settleUncertainBudget,
  snapshotBudget,
  type BudgetResult,
  type AtomicBudgetStorage,
  type BudgetStorage,
} from "./budget_do";
import { json } from "./http_json";

class DurableObjectBudgetStorage implements BudgetStorage {
  constructor(private readonly storage: DurableObjectStorage) {}

  get<T>(key: string): Promise<T | undefined> {
    return this.storage.get<T>(key);
  }

  async commit(key: string, value: unknown, nextAlarm: number | null): Promise<void> {
    await this.storage.transaction(async (txn) => {
      await txn.put(key, value);
      if (nextAlarm === null) {
        await txn.deleteAlarm();
      } else {
        await txn.setAlarm(nextAlarm);
      }
    });
  }

  runAtomic<T>(work: (storage: AtomicBudgetStorage) => Promise<T>): Promise<T> {
    return this.storage.transaction(async (transaction) => {
      const atomicStorage: AtomicBudgetStorage = {
        get: <V>(key: string) => transaction.get<V>(key),
        commit: async (key: string, value: unknown, nextAlarm: number | null) => {
          await transaction.put(key, value);
          if (nextAlarm === null) {
            await transaction.deleteAlarm();
          } else {
            await transaction.setAlarm(nextAlarm);
          }
        },
      };
      return work(atomicStorage);
    });
  }
}

function errorStatus(error: string): number {
  if (error === "budget_exhausted") return 429;
  if (
    error === "reservation_not_found" ||
    error === "lease_not_active" ||
    error === "lease_reservation_mismatch" ||
    error === "budget_frozen" ||
    error === "actual_exceeds_reserved" ||
    error === "provider_usage_uncertain" ||
    error === "provider_not_started" ||
    error === "idempotency_digest_conflict" ||
    error === "reservation_released" ||
    error === "settlement_capability_required" ||
    error === "settlement_capability_invalid" ||
    error === "settlement_capability_consumed" ||
    error === "request_digest_mismatch" ||
    error === "lease_mismatch" ||
    error === "caller_settlement_rejected" ||
    error === "provider_usage_invalid" ||
    error === "reservation_changed_retry"
  ) {
    return 409;
  }
  return 400;
}

export async function handleBudgetRequest(
  storage: BudgetStorage,
  request: Request,
  now = Date.now(),
): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (
    path === "/finalize" ||
    path === "/reconcile" ||
    path === "/provider-started" ||
    path === "/settle-uncertain" ||
    path === "/mint" ||
    path === "/mint-settlement-capability"
  ) {
    return json({ ok: false, error: "not found" }, 404);
  }
  if (request.method === "GET" && (path === "/snapshot" || path === "/")) {
    return json(await snapshotBudget(storage, now));
  }
  if (request.method !== "POST") return json({ ok: false, error: "POST required" }, 405);

  let body: unknown = {};
  const contentType = request.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      body = await request.json();
    } catch {
      return json({ ok: false, error: "invalid JSON body" }, 400);
    }
  }
  const rec = body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : {};

  let result: BudgetResult<unknown>;
  switch (path) {
    case "/create":
      result = await createBudget(storage, now);
      break;
    case "/reserve":
      result = await reserveBudget(
        storage,
        {
          idempotency_key: String(rec.idempotency_key ?? ""),
          amounts: rec.amounts,
          acquire_lease: true,
          request_digest: typeof rec.request_digest === "string" ? rec.request_digest : undefined,
        },
        now,
      );
      break;
    case "/heartbeat":
      result = await heartbeatLease(storage, String(rec.lease_id ?? ""), now);
      break;
    case "/release":
      result = await releaseBudget(
        storage,
        {
          lease_id: typeof rec.lease_id === "string" ? rec.lease_id : undefined,
          idempotency_key: typeof rec.idempotency_key === "string" ? rec.idempotency_key : undefined,
        },
        now,
      );
      break;
    case "/recover":
      result = await recoverExpiredLeases(storage, now);
      break;
    default:
      return json({ ok: false, error: "not found" }, 404);
  }
  if (!result.ok) return json(result, errorStatus(result.error));
  return json(result);
}

/** Wrangler Durable Object. Algebra lives in budget_do for unit tests. */
export class BudgetLedger extends DurableObject<unknown> {
  private readonly storage: BudgetStorage;
  private readonly coordinator: ReturnType<typeof createBudgetCoordinator>;

  constructor(state: DurableObjectState, _env: unknown) {
    super(state, _env);
    this.storage = new DurableObjectBudgetStorage(state.storage);
    this.coordinator = createBudgetCoordinator(this.storage);
    state.blockConcurrencyWhile(async () => {
      // Reconstruct the recovery alarm after eviction/restart and settle any
      // provider-started lease that expired while the instance was absent.
      await recoverExpiredLeases(this.storage);
    });
  }

  fetch(request: Request): Promise<Response> {
    return handleBudgetRequest(this.storage, request);
  }

  reserve(input: Parameters<typeof reserveBudget>[1]) {
    return this.coordinator.reserve(input);
  }

  markProviderStarted(input: Parameters<typeof markProviderStarted>[1]) {
    return this.coordinator.markProviderStarted(input);
  }

  finalizeExact(input: Parameters<typeof finalizeBudget>[1]) {
    return this.coordinator.finalizeExact(input);
  }

  settleUncertain(input: Parameters<typeof settleUncertainBudget>[1]) {
    return this.coordinator.settleUncertain(input);
  }

  release(input: Parameters<typeof releaseBudget>[1]) {
    return this.coordinator.release(input);
  }

  heartbeat(leaseId: string) {
    return this.coordinator.heartbeat(leaseId);
  }

  snapshot() {
    return this.coordinator.snapshot();
  }

  async alarm(): Promise<void> {
    await recoverExpiredLeases(this.storage);
  }
}
