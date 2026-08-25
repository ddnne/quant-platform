/** Durable Object hard budget occupancy algebra. Presence of budget_id is not a reserve. */

import controlledPilotPolicy from "../../../../specs/policy/controlled_pilot_policy.json";

export const PILOT_BUDGET_CAPS = {
  max_experiment_plans: controlledPilotPolicy.plans_exactly,
  max_parallel_experiments: controlledPilotPolicy.max_parallel_experiments,
  max_generations: controlledPilotPolicy.max_generations,
  max_model_calls: controlledPilotPolicy.max_model_calls,
  max_input_tokens: controlledPilotPolicy.max_input_tokens,
  max_output_tokens: controlledPilotPolicy.max_output_tokens,
  max_paper_runs: controlledPilotPolicy.max_paper_runs,
  max_cost_usd: controlledPilotPolicy.max_cost_usd,
  lease_ttl_seconds: controlledPilotPolicy.lease_ttl_seconds,
  auto_promotion: controlledPilotPolicy.automatic_promotion,
} as const;

/** Single control-plane ledger name. Caller budget_id is not occupancy. */
export const CONTROL_PLANE_LEDGER_NAME = "pilot-control-plane";

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

export type CachedBudgetResult = {
  http_status: number;
  body: unknown;
};

export type BudgetSettlement = {
  outcome: "success" | "schema_reject" | "provider_error" | "timeout";
  usage_source: "provider" | "estimated_no_provider_usage";
  estimated_cost_usd: number;
  actual_cost_usd: number | null;
  billed_cost_usd: number;
  actual_input_tokens: number | null;
  actual_output_tokens: number | null;
  actual_cached_tokens: number | null;
};

export type BudgetAuditRecord = {
  kind: "actual_exceeds_reserved";
  reservation_id: string;
  reserved: Counters;
  actual: Counters;
  at: number;
};

export type Reservation = {
  idempotency_key: string;
  /** Opaque Budget Run ID issued by reserve. Not a caller-invented occupancy id. */
  reservation_id: string;
  amounts: Counters;
  actual: Counters | null;
  status: ReservationStatus;
  lease_id: string | null;
  created_at: number;
  reconciled_at: number | null;
  released_at: number | null;
  request_digest: string | null;
  cached_result: CachedBudgetResult | null;
  finalize_error: string | null;
  settlement: BudgetSettlement | null;
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
  frozen: boolean;
  frozen_at: number | null;
  frozen_reason: string | null;
  audit: BudgetAuditRecord[];
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
    frozen: false,
    frozen_at: null,
    frozen_reason: null,
    audit: [],
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

/** Bind a caller Idempotency-Key to a request digest. Missing key uses the digest. */
export function bindIdempotencyKey(
  clientKey: string | undefined | null,
  requestDigest: string,
): BudgetResult<{ idempotency_key: string; request_digest: string }> {
  const digest = typeof requestDigest === "string" ? requestDigest.trim() : "";
  if (!digest) return { ok: false, error: "request_digest required" };
  const client = typeof clientKey === "string" ? clientKey.trim() : "";
  if (client) {
    if (client.length > 256) return { ok: false, error: "idempotency_key too long" };
    return { ok: true, idempotency_key: client, request_digest: digest };
  }
  return { ok: true, idempotency_key: `digest:${digest}`, request_digest: digest };
}

function counterGreater(name: CounterName, left: number, right: number): boolean {
  if (name === "cost_usd") return usdMicros(left) > usdMicros(right);
  return left > right;
}

export function exceedsReserved(
  reserved: Counters,
  actual: Counters,
): { name: CounterName; reserved: number; actual: number } | null {
  for (const name of COUNTERS) {
    if (counterGreater(name, actual[name], reserved[name])) {
      return { name, reserved: reserved[name], actual: actual[name] };
    }
  }
  return null;
}

function coerceReservation(raw: Reservation): Reservation {
  return {
    ...raw,
    request_digest: raw.request_digest ?? null,
    cached_result: raw.cached_result ?? null,
    finalize_error: raw.finalize_error ?? null,
    settlement: raw.settlement ?? null,
  };
}

function coerceState(state: LedgerState): LedgerState {
  state.frozen = state.frozen === true;
  state.frozen_at = state.frozen_at ?? null;
  state.frozen_reason = state.frozen_reason ?? null;
  state.audit = Array.isArray(state.audit) ? state.audit : [];
  const reservations: Record<string, Reservation> = {};
  for (const [k, v] of Object.entries(state.reservations || {})) {
    reservations[k] = coerceReservation(v);
  }
  state.reservations = reservations;
  return state;
}

function closeReservationLease(state: LedgerState, reservation: Reservation, now: number): void {
  if (!reservation.lease_id) return;
  const lease = state.leases[reservation.lease_id];
  if (lease && lease.released_at === null) lease.released_at = now;
}

function freezeForOverage(
  state: LedgerState,
  reservation: Reservation,
  actual: Counters,
  now: number,
): void {
  state.frozen = true;
  state.frozen_at = now;
  state.frozen_reason = "actual_exceeds_reserved";
  state.audit.push({
    kind: "actual_exceeds_reserved",
    reservation_id: reservation.reservation_id,
    reserved: amountsFromCounters(reservation.amounts),
    actual: amountsFromCounters(actual),
    at: now,
  });
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
  return existing ? coerceState(existing) : emptyLedger(now);
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
  input: {
    idempotency_key: string;
    amounts: unknown;
    acquire_lease?: boolean;
    request_digest?: string;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: Reservation;
    lease: Lease | null;
    existing: boolean;
    budget_run_id: string;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const parsed = parseAmounts(input.amounts);
  if (!parsed.ok) return parsed;
  const amounts = parsed.amounts;
  const digest =
    typeof input.request_digest === "string" && input.request_digest.trim()
      ? input.request_digest.trim()
      : null;

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  ensureCreated(state, now);

  if (state.frozen) {
    await saveState(storage, state);
    return {
      ok: false,
      error: "budget_frozen",
      detail: state.frozen_reason || "actual_exceeds_reserved",
    };
  }

  const existing = state.reservations[key.idempotency_key];
  if (existing && existing.status !== "released") {
    if (digest && existing.request_digest && existing.request_digest !== digest) {
      await saveState(storage, state);
      return { ok: false, error: "idempotency_digest_conflict" };
    }
    const lease = existing.lease_id ? state.leases[existing.lease_id] ?? null : null;
    await saveState(storage, state);
    return {
      ok: true,
      reservation: structuredClone(existing),
      lease,
      existing: true,
      budget_run_id: existing.reservation_id,
    };
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
    request_digest: digest,
    cached_result: null,
    finalize_error: null,
    settlement: null,
  };
  state.reserved = applyDelta(state.reserved, reservation.amounts, 1);
  state.reservations[key.idempotency_key] = reservation;
  await saveState(storage, state);
  return {
    ok: true,
    reservation,
    lease,
    existing: false,
    budget_run_id: reservation.reservation_id,
  };
}

function applyCachedResult(
  reservation: Reservation,
  result: CachedBudgetResult | undefined,
): void {
  if (!result) return;
  const status = Number(result.http_status);
  reservation.cached_result = {
    http_status: Number.isInteger(status) && status > 0 ? status : 500,
    body: result.body,
  };
}

export async function reconcileBudget(
  storage: BudgetStorage,
  input: { idempotency_key: string; amounts: unknown },
  now = Date.now(),
): Promise<BudgetResult<{ reservation: Reservation; used: Counters }>> {
  const finalized = await finalizeBudget(
    storage,
    { idempotency_key: input.idempotency_key, amounts: input.amounts },
    now,
  );
  if (!finalized.ok) return finalized;
  return { ok: true, reservation: finalized.reservation, used: finalized.used };
}

export async function finalizeBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    amounts: unknown;
    result?: CachedBudgetResult;
    settlement?: BudgetSettlement;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: Reservation;
    used: Counters;
    frozen: boolean;
    budget_run_id: string;
  }>
> {
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
    if (!reservation.cached_result) applyCachedResult(reservation, input.result);
    await saveState(storage, state);
    if (reservation.finalize_error) {
      return {
        ok: false,
        error: reservation.finalize_error,
        detail: state.frozen_reason || undefined,
      };
    }
    return {
      ok: true,
      reservation,
      used: amountsFromCounters(state.used),
      frozen: state.frozen,
      budget_run_id: reservation.reservation_id,
    };
  }
  if (reservation.status === "released") {
    return { ok: false, error: "reservation_released" };
  }

  const over = exceedsReserved(reservation.amounts, actual);
  state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
  // Release the estimate in full, then record billed spend exactly.  If the
  // estimate was too low, freeze future work without clipping audit history.
  state.used = applyDelta(state.used, actual, 1);
  reservation.status = "reconciled";
  reservation.actual = amountsFromCounters(actual);
  reservation.settlement = input.settlement ?? null;
  reservation.reconciled_at = now;
  applyCachedResult(reservation, input.result);
  closeReservationLease(state, reservation, now);
  if (over) {
    freezeForOverage(state, reservation, actual, now);
    reservation.finalize_error = "actual_exceeds_reserved";
    await saveState(storage, state);
    return {
      ok: false,
      error: "actual_exceeds_reserved",
      detail: `${over.name}: actual=${over.actual} reserved=${over.reserved}`,
    };
  }
  reservation.finalize_error = null;
  await saveState(storage, state);
  return {
    ok: true,
    reservation,
    used: amountsFromCounters(state.used),
    frozen: false,
    budget_run_id: reservation.reservation_id,
  };
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
    frozen: boolean;
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
    frozen: state.frozen === true,
  };
}
