/** Durable Object hard budget. Presence of budget_id is not a reserve. */

import { json } from "./http_json";

export const PILOT_BUDGET_CAPS = {
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
} as const;

export type CounterName =
  | "experiment_plans"
  | "generations"
  | "model_calls"
  | "input_tokens"
  | "output_tokens"
  | "paper_runs"
  | "cost_usd";

export type Counters = Record<CounterName, number>;
export type BudgetAmounts = Partial<Record<CounterName, number>>;

export type ReservationStatus = "reserved" | "reconciled" | "released";

export type Reservation = {
  idempotency_key: string;
  reservation_id: string;
  amounts: Counters;
  actual: Counters | null;
  status: ReservationStatus;
  lease_id: string | null;
  created_at: number;
  reconciled_at: number | null;
  released_at: number | null;
};

export type Lease = {
  lease_id: string;
  reservation_key: string | null;
  acquired_at: number;
  expires_at: number;
  last_heartbeat_at: number;
  released_at: number | null;
};

export type LedgerState = {
  created: boolean;
  created_at: number;
  caps: typeof PILOT_BUDGET_CAPS;
  used: Counters;
  reserved: Counters;
  reservations: Record<string, Reservation>;
  leases: Record<string, Lease>;
};

export type BudgetErr = { ok: false; error: string; detail?: string };
export type BudgetOk<T> = { ok: true } & T;
export type BudgetResult<T> = BudgetOk<T> | BudgetErr;

export interface BudgetStorage {
  get<T>(key: string): Promise<T | undefined>;
  put(key: string, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
  list(prefix: string): Promise<Map<string, unknown>>;
}

const STATE_KEY = "ledger";
const COUNTERS: CounterName[] = [
  "experiment_plans",
  "generations",
  "model_calls",
  "input_tokens",
  "output_tokens",
  "paper_runs",
  "cost_usd",
];

const CAP_FOR: Record<CounterName, number> = {
  experiment_plans: PILOT_BUDGET_CAPS.max_experiment_plans,
  generations: PILOT_BUDGET_CAPS.max_generations,
  model_calls: PILOT_BUDGET_CAPS.max_model_calls,
  input_tokens: PILOT_BUDGET_CAPS.max_input_tokens,
  output_tokens: PILOT_BUDGET_CAPS.max_output_tokens,
  paper_runs: PILOT_BUDGET_CAPS.max_paper_runs,
  cost_usd: PILOT_BUDGET_CAPS.max_cost_usd,
};

export function zeroCounters(): Counters {
  return {
    experiment_plans: 0,
    generations: 0,
    model_calls: 0,
    input_tokens: 0,
    output_tokens: 0,
    paper_runs: 0,
    cost_usd: 0,
  };
}

export function emptyLedger(now: number): LedgerState {
  return {
    created: false,
    created_at: now,
    caps: { ...PILOT_BUDGET_CAPS },
    used: zeroCounters(),
    reserved: zeroCounters(),
    reservations: {},
    leases: {},
  };
}

export class MemoryBudgetStorage implements BudgetStorage {
  private readonly data = new Map<string, unknown>();

  async get<T>(key: string): Promise<T | undefined> {
    if (!this.data.has(key)) return undefined;
    return structuredClone(this.data.get(key)) as T;
  }

  async put(key: string, value: unknown): Promise<void> {
    this.data.set(key, structuredClone(value));
  }

  async delete(key: string): Promise<void> {
    this.data.delete(key);
  }

  async list(prefix: string): Promise<Map<string, unknown>> {
    const out = new Map<string, unknown>();
    for (const [k, v] of this.data) {
      if (k.startsWith(prefix)) out.set(k, structuredClone(v));
    }
    return out;
  }
}

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

function usdMicros(usd: number): number {
  return Math.round(usd * 1_000_000);
}

function addUsd(a: number, b: number): number {
  return usdMicros(a + b) / 1_000_000;
}

function occupancy(used: number, reserved: number, isCost: boolean): number {
  return isCost ? usdMicros(used) + usdMicros(reserved) : used + reserved;
}

function capMicrosOrUnits(name: CounterName): number {
  const cap = CAP_FOR[name];
  return name === "cost_usd" ? usdMicros(cap) : cap;
}

function addCounter(name: CounterName, left: number, right: number): number {
  if (name === "cost_usd") return addUsd(left, right);
  return left + right;
}

function subCounter(name: CounterName, left: number, right: number): number {
  if (name === "cost_usd") return Math.max(0, addUsd(left, -right));
  return Math.max(0, left - right);
}

export function parseAmounts(raw: unknown): BudgetResult<{ amounts: Counters }> {
  if (raw === undefined || raw === null) {
    return { ok: true, amounts: zeroCounters() };
  }
  if (typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false, error: "amounts must be an object" };
  }
  const obj = raw as Record<string, unknown>;
  for (const key of Object.keys(obj)) {
    if (!COUNTERS.includes(key as CounterName)) {
      return { ok: false, error: `unknown amount: ${key}` };
    }
  }
  const amounts = zeroCounters();
  for (const name of COUNTERS) {
    if (obj[name] === undefined) continue;
    const n = Number(obj[name]);
    if (!Number.isFinite(n) || n < 0) {
      return { ok: false, error: `${name} must be a finite number >= 0` };
    }
    if (name !== "cost_usd" && (!Number.isInteger(n) || n !== Number(obj[name]))) {
      return { ok: false, error: `${name} must be an integer >= 0` };
    }
    amounts[name] = name === "cost_usd" ? usdMicros(n) / 1_000_000 : n;
  }
  return { ok: true, amounts };
}

function amountsFromCounters(c: Counters): Counters {
  return { ...c };
}

function insufficient(
  state: LedgerState,
  delta: Counters,
): { name: CounterName; used: number; reserved: number; delta: number; limit: number } | null {
  for (const name of COUNTERS) {
    const extra = name === "cost_usd" ? usdMicros(delta[name]) : delta[name];
    if (extra === 0) continue;
    const usedOcc = occupancy(state.used[name], state.reserved[name], name === "cost_usd");
    if (usedOcc + extra > capMicrosOrUnits(name)) {
      return {
        name,
        used: state.used[name],
        reserved: state.reserved[name],
        delta: delta[name],
        limit: CAP_FOR[name],
      };
    }
  }
  return null;
}

function applyDelta(counters: Counters, delta: Counters, sign: 1 | -1): Counters {
  const next = amountsFromCounters(counters);
  for (const name of COUNTERS) {
    next[name] =
      sign === 1
        ? addCounter(name, next[name], delta[name])
        : subCounter(name, next[name], delta[name]);
  }
  return next;
}

function requireIdempotencyKey(raw: unknown): BudgetResult<{ idempotency_key: string }> {
  if (typeof raw !== "string" || !raw.trim()) {
    return { ok: false, error: "idempotency_key required" };
  }
  const key = raw.trim();
  if (key.length > 256) return { ok: false, error: "idempotency_key too long" };
  return { ok: true, idempotency_key: key };
}

function activeLeaseCount(state: LedgerState): number {
  let n = 0;
  for (const lease of Object.values(state.leases)) {
    if (lease.released_at === null) n += 1;
  }
  return n;
}

export function recoverExpired(state: LedgerState, now: number): number {
  let recovered = 0;
  for (const lease of Object.values(state.leases)) {
    if (lease.released_at !== null) continue;
    if (lease.expires_at > now) continue;
    lease.released_at = now;
    recovered += 1;
    if (!lease.reservation_key) continue;
    const reservation = state.reservations[lease.reservation_key];
    if (!reservation || reservation.status !== "reserved") continue;
    state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
    reservation.status = "released";
    reservation.released_at = now;
  }
  return recovered;
}

async function loadState(storage: BudgetStorage, now: number): Promise<LedgerState> {
  const existing = await storage.get<LedgerState>(STATE_KEY);
  return existing ? existing : emptyLedger(now);
}

async function saveState(storage: BudgetStorage, state: LedgerState): Promise<void> {
  await storage.put(STATE_KEY, state);
}

function ensureCreated(state: LedgerState, now: number): boolean {
  if (state.created) return false;
  state.created = true;
  state.created_at = now;
  state.caps = { ...PILOT_BUDGET_CAPS };
  return true;
}

export async function createBudget(
  storage: BudgetStorage,
  now = Date.now(),
): Promise<BudgetResult<{ created: boolean; caps: typeof PILOT_BUDGET_CAPS }>> {
  const state = await loadState(storage, now);
  recoverExpired(state, now);
  const created = ensureCreated(state, now);
  await saveState(storage, state);
  return { ok: true, created, caps: state.caps };
}

export async function reserveBudget(
  storage: BudgetStorage,
  input: { idempotency_key: string; amounts: unknown; acquire_lease?: boolean },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: Reservation;
    lease: Lease | null;
    existing: boolean;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const parsed = parseAmounts(input.amounts);
  if (!parsed.ok) return parsed;
  const amounts = parsed.amounts;

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  ensureCreated(state, now);

  const existing = state.reservations[key.idempotency_key];
  if (existing && existing.status !== "released") {
    const lease = existing.lease_id ? state.leases[existing.lease_id] ?? null : null;
    await saveState(storage, state);
    return { ok: true, reservation: structuredClone(existing), lease, existing: true };
  }

  const over = insufficient(state, amounts);
  if (over) {
    return {
      ok: false,
      error: "budget_exhausted",
      detail: `${over.name}: used=${over.used} reserved=${over.reserved} delta=${over.delta} limit=${over.limit}`,
    };
  }

  let lease: Lease | null = null;
  if (input.acquire_lease) {
    const active = activeLeaseCount(state);
    if (active >= PILOT_BUDGET_CAPS.max_parallel_experiments) {
      return {
        ok: false,
        error: "budget_exhausted",
        detail: `concurrent_experiments: active=${active} limit=${PILOT_BUDGET_CAPS.max_parallel_experiments}`,
      };
    }
    const leaseId = crypto.randomUUID();
    lease = {
      lease_id: leaseId,
      reservation_key: key.idempotency_key,
      acquired_at: now,
      expires_at: now + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000,
      last_heartbeat_at: now,
      released_at: null,
    };
    state.leases[leaseId] = lease;
  }

  const reservation: Reservation = {
    idempotency_key: key.idempotency_key,
    reservation_id: crypto.randomUUID(),
    amounts: amountsFromCounters(amounts),
    actual: null,
    status: "reserved",
    lease_id: lease?.lease_id ?? null,
    created_at: now,
    reconciled_at: null,
    released_at: null,
  };
  state.reserved = applyDelta(state.reserved, reservation.amounts, 1);
  state.reservations[key.idempotency_key] = reservation;
  await saveState(storage, state);
  return { ok: true, reservation, lease, existing: false };
}

export async function reconcileBudget(
  storage: BudgetStorage,
  input: { idempotency_key: string; amounts: unknown },
  now = Date.now(),
): Promise<BudgetResult<{ reservation: Reservation; used: Counters }>> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const parsed = parseAmounts(input.amounts);
  if (!parsed.ok) return parsed;
  const actual = parsed.amounts;

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  const reservation = state.reservations[key.idempotency_key];
  if (!reservation) return { ok: false, error: "reservation_not_found" };
  if (reservation.status === "reconciled") {
    return { ok: true, reservation, used: amountsFromCounters(state.used) };
  }
  if (reservation.status === "released") {
    return { ok: false, error: "reservation_released" };
  }

  state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
  state.used = applyDelta(state.used, actual, 1);
  reservation.status = "reconciled";
  reservation.actual = amountsFromCounters(actual);
  reservation.reconciled_at = now;
  await saveState(storage, state);
  return { ok: true, reservation, used: amountsFromCounters(state.used) };
}

export async function heartbeatLease(
  storage: BudgetStorage,
  leaseId: string,
  now = Date.now(),
): Promise<BudgetResult<{ lease: Lease }>> {
  if (typeof leaseId !== "string" || !leaseId.trim()) {
    return { ok: false, error: "lease_id required" };
  }
  const state = await loadState(storage, now);
  recoverExpired(state, now);
  const lease = state.leases[leaseId.trim()];
  if (!lease || lease.released_at !== null) {
    return { ok: false, error: "lease_not_active" };
  }
  lease.last_heartbeat_at = now;
  lease.expires_at = now + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000;
  await saveState(storage, state);
  return { ok: true, lease };
}

export async function releaseBudget(
  storage: BudgetStorage,
  input: { lease_id?: string; idempotency_key?: string },
  now = Date.now(),
): Promise<BudgetResult<{ released: boolean; lease: Lease | null; reservation: Reservation | null }>> {
  const state = await loadState(storage, now);
  recoverExpired(state, now);
  let lease: Lease | null = null;
  let reservation: Reservation | null = null;

  if (typeof input.lease_id === "string" && input.lease_id.trim()) {
    lease = state.leases[input.lease_id.trim()] ?? null;
  }
  if (typeof input.idempotency_key === "string" && input.idempotency_key.trim()) {
    reservation = state.reservations[input.idempotency_key.trim()] ?? null;
  }
  if (!reservation && lease?.reservation_key) {
    reservation = state.reservations[lease.reservation_key] ?? null;
  }
  if (!lease && reservation?.lease_id) {
    lease = state.leases[reservation.lease_id] ?? null;
  }
  if (!lease && !reservation) {
    return { ok: false, error: "lease_or_idempotency_key required" };
  }

  if (lease && lease.released_at === null) {
    lease.released_at = now;
  }
  if (reservation && reservation.status === "reserved") {
    state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
    reservation.status = "released";
    reservation.released_at = now;
  }
  await saveState(storage, state);
  return { ok: true, released: true, lease, reservation };
}

export async function recoverExpiredLeases(
  storage: BudgetStorage,
  now = Date.now(),
): Promise<BudgetResult<{ recovered: number }>> {
  const state = await loadState(storage, now);
  const recovered = recoverExpired(state, now);
  await saveState(storage, state);
  return { ok: true, recovered };
}

export async function snapshotBudget(
  storage: BudgetStorage,
  now = Date.now(),
): Promise<
  BudgetResult<{
    created: boolean;
    used: Counters;
    reserved: Counters;
    active_leases: number;
    caps: typeof PILOT_BUDGET_CAPS;
    auto_promotion: false;
  }>
> {
  const state = await loadState(storage, now);
  recoverExpired(state, now);
  await saveState(storage, state);
  return {
    ok: true,
    created: state.created,
    used: amountsFromCounters(state.used),
    reserved: amountsFromCounters(state.reserved),
    active_leases: activeLeaseCount(state),
    caps: state.caps,
    auto_promotion: false,
  };
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

/** Wrangler Durable Object. Algebra lives in the functions above for unit tests. */
export class BudgetLedger {
  private readonly storage: BudgetStorage;

  constructor(state: DurableObjectState, _env: unknown) {
    this.storage = new DurableObjectBudgetStorage(state.storage);
  }

  fetch(request: Request): Promise<Response> {
    return handleBudgetRequest(this.storage, request);
  }
}


