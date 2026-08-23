/** Budget HTTP dispatcher. Occupancy algebra stays in budget_do. Presence of budget_id is not a reserve. */

import {
  createBudget,
  heartbeatLease,
  reconcileBudget,
  recoverExpiredLeases,
  releaseBudget,
  reserveBudget,
  snapshotBudget,
  type BudgetResult,
  type BudgetStorage,
} from "./budget_do";
import { json } from "./http_json";

class DurableObjectBudgetStorage implements BudgetStorage {
  constructor(private readonly storage: DurableObjectStorage) {}

  get<T>(key: string): Promise<T | undefined> {
    return this.storage.get<T>(key);
  }

  put(key: string, value: unknown): Promise<void> {
    return this.storage.put(key, value);
  }

  async delete(key: string): Promise<void> {
    await this.storage.delete(key);
  }

  async list(prefix: string): Promise<Map<string, unknown>> {
    return (await this.storage.list({ prefix })) as Map<string, unknown>;
  }
}

function errorStatus(error: string): number {
  if (error === "budget_exhausted") return 429;
  if (error === "reservation_not_found" || error === "lease_not_active") return 409;
  return 400;
}

export async function handleBudgetRequest(
  storage: BudgetStorage,
  request: Request,
  now = Date.now(),
): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
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
          acquire_lease: rec.acquire_lease === true,
        },
        now,
      );
      break;
    case "/reconcile":
      result = await reconcileBudget(
        storage,
        {
          idempotency_key: String(rec.idempotency_key ?? ""),
          amounts: rec.amounts,
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
export class BudgetLedger {
  private readonly storage: BudgetStorage;

  constructor(state: DurableObjectState, _env: unknown) {
    this.storage = new DurableObjectBudgetStorage(state.storage);
  }

  fetch(request: Request): Promise<Response> {
    return handleBudgetRequest(this.storage, request);
  }
}
