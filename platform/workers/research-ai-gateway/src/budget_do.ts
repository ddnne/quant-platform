/** Durable Object hard budget occupancy algebra. Presence of budget_id is not a reserve. */

import controlledPilotPolicy from "../../../../specs/policy/controlled_pilot_policy.json";

export const PILOT_BUDGET_CAPS = {
  max_experiment_plans: controlledPilotPolicy.plans_exactly,
  max_parallel_experiments: controlledPilotPolicy.max_parallel_experiments,
  max_generations: controlledPilotPolicy.max_generations,
  max_model_calls: controlledPilotPolicy.max_model_calls,
  max_input_tokens: controlledPilotPolicy.max_input_tokens,
  max_output_tokens: controlledPilotPolicy.max_output_tokens,
  max_cached_tokens: controlledPilotPolicy.max_cached_tokens,
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
  | "cached_tokens"
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
  usage_source: "provider" | "reserved_max_uncertain";
  estimated_cost_usd: number;
  actual_cost_usd: number | null;
  billed_cost_usd: number;
  actual_input_tokens: number | null;
  actual_output_tokens: number | null;
  actual_cached_tokens: number | null;
};

export type BudgetAuditRecord =
  | {
      kind: "actual_exceeds_reserved";
      reservation_id: string;
      reserved: Counters;
      actual: Counters;
      at: number;
    }
  | {
      kind: "uncertain_provider_charge";
      reservation_id: string;
      charged: Counters;
      reason: string;
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
  /** Persisted before invoking Workers AI. Null proves no provider side effect was started. */
  provider_started_at: number | null;
  uncertainty_reason: string | null;
  /** SHA-256 of the one-shot settlement capability bound to this reservation. */
  settlement_capability_hash: string | null;
  settlement_capability_consumed: boolean;
  /** Private one-shot secret. Never present on PublicReservation. */
  settlement_capability_secret: string | null;
};

/**
 * Closed public reservation DTO. Settlement secret/hash fields are absent, not
 * redacted placeholders. Callers must not treat this as the sensitive Reservation.
 */
export type PublicReservation = {
  idempotency_key: string;
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
  provider_started_at: number | null;
  uncertainty_reason: string | null;
  settlement_capability_consumed: boolean;
};

type SensitiveCapabilityField =
  | "settlement_capability"
  | "settlement_capability_secret"
  | "settlement_capability_hash";

type PublicReservationSensitive = Extract<keyof PublicReservation, SensitiveCapabilityField>;
const _publicReservationHasNoSensitiveFields: PublicReservationSensitive extends never
  ? true
  : never = true;
void _publicReservationHasNoSensitiveFields;

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
  /** Atomically persist ledger state and its one recovery alarm. */
  commit(key: string, value: unknown, nextAlarm: number | null): Promise<void>;
}

const STATE_KEY = "ledger";
const COUNTERS: CounterName[] = [
  "experiment_plans",
  "generations",
  "model_calls",
  "input_tokens",
  "output_tokens",
  "cached_tokens",
  "paper_runs",
  "cost_usd",
];

const CAP_FOR: Record<CounterName, number> = {
  experiment_plans: PILOT_BUDGET_CAPS.max_experiment_plans,
  generations: PILOT_BUDGET_CAPS.max_generations,
  model_calls: PILOT_BUDGET_CAPS.max_model_calls,
  input_tokens: PILOT_BUDGET_CAPS.max_input_tokens,
  output_tokens: PILOT_BUDGET_CAPS.max_output_tokens,
  cached_tokens: PILOT_BUDGET_CAPS.max_cached_tokens,
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
    cached_tokens: 0,
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
  private alarm: number | null = null;

  async get<T>(key: string): Promise<T | undefined> {
    if (!this.data.has(key)) return undefined;
    return structuredClone(this.data.get(key)) as T;
  }

  async commit(key: string, value: unknown, nextAlarm: number | null): Promise<void> {
    this.data.set(key, structuredClone(value));
    this.alarm = nextAlarm;
  }

  async getAlarm(): Promise<number | null> {
    return this.alarm;
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

function coerceCounters(raw: Partial<Counters> | null | undefined): Counters {
  const out = zeroCounters();
  for (const name of COUNTERS) {
    const value = Number(raw?.[name] ?? 0);
    out[name] = Number.isFinite(value) && value >= 0
      ? name === "cost_usd"
        ? usdMicros(value) / 1_000_000
        : Math.floor(value)
      : 0;
  }
  return out;
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
    amounts: coerceCounters(raw.amounts),
    actual: raw.actual ? coerceCounters(raw.actual) : null,
    request_digest: raw.request_digest ?? null,
    cached_result: raw.cached_result ?? null,
    finalize_error: raw.finalize_error ?? null,
    settlement: raw.settlement ?? null,
    provider_started_at: raw.provider_started_at ?? null,
    uncertainty_reason: raw.uncertainty_reason ?? null,
    settlement_capability_hash: raw.settlement_capability_hash ?? null,
    settlement_capability_consumed: raw.settlement_capability_consumed === true,
    settlement_capability_secret:
      typeof raw.settlement_capability_secret === "string" && raw.settlement_capability_secret
        ? raw.settlement_capability_secret
        : null,
  };
}

function coerceState(state: LedgerState): LedgerState {
  state.caps = { ...PILOT_BUDGET_CAPS };
  state.used = coerceCounters(state.used);
  state.reserved = coerceCounters(state.reserved);
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

function freezeForUncertainty(
  state: LedgerState,
  reservation: Reservation,
  reason: UncertainProviderReason,
  now: number,
): void {
  state.frozen = true;
  state.frozen_at = now;
  state.frozen_reason = `provider_usage_uncertain:${reason}`;
  state.audit.push({
    kind: "uncertain_provider_charge",
    reservation_id: reservation.reservation_id,
    charged: amountsFromCounters(reservation.amounts),
    reason,
    at: now,
  });
}

function chargeUncertainReservation(
  state: LedgerState,
  reservation: Reservation,
  reason: UncertainProviderReason,
  now: number,
): void {
  state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
  state.used = applyDelta(state.used, reservation.amounts, 1);
  reservation.status = "reconciled";
  reservation.actual = amountsFromCounters(reservation.amounts);
  reservation.reconciled_at = now;
  reservation.uncertainty_reason = reason;
  reservation.finalize_error = "provider_usage_uncertain";
  reservation.settlement = {
    outcome: reason === "timeout" || reason === "lease_expired" ? "timeout" : "provider_error",
    usage_source: "reserved_max_uncertain",
    estimated_cost_usd: reservation.amounts.cost_usd,
    actual_cost_usd: null,
    billed_cost_usd: reservation.amounts.cost_usd,
    actual_input_tokens: null,
    actual_output_tokens: null,
    actual_cached_tokens: null,
  };
  reservation.cached_result = uncertainResult(reservation, reason);
  reservation.settlement_capability_secret = null;
  reservation.settlement_capability_consumed = true;
  closeReservationLease(state, reservation, now);
  freezeForUncertainty(state, reservation, reason, now);
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
    if (reservation.provider_started_at === null) {
      state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
      reservation.status = "released";
      reservation.released_at = now;
      continue;
    }
    // Once the provider side effect starts, an expired lease is not evidence
    // of zero usage. Charge the full reservation and freeze future work until
    // an operator audits provider billing.
    chargeUncertainReservation(state, reservation, "lease_expired", now);
  }
  return recovered;
}

async function loadState(storage: BudgetStorage, now: number): Promise<LedgerState> {
  const existing = await storage.get<LedgerState>(STATE_KEY);
  return existing ? coerceState(existing) : emptyLedger(now);
}

async function saveState(storage: BudgetStorage, state: LedgerState): Promise<void> {
  let nextAlarm: number | null = null;
  for (const lease of Object.values(state.leases)) {
    if (lease.released_at !== null) continue;
    nextAlarm = nextAlarm === null ? lease.expires_at : Math.min(nextAlarm, lease.expires_at);
  }
  await storage.commit(STATE_KEY, state, nextAlarm);
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
    reservation: PublicReservation;
    lease: Lease | null;
    existing: boolean;
    budget_run_id: string;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const boundDigest = requireNonemptyRequestDigest(input.request_digest);
  if (!boundDigest.ok) return boundDigest;
  const digest = boundDigest.request_digest;
  const parsed = parseAmounts(input.amounts);
  if (!parsed.ok) return parsed;
  const amounts = parsed.amounts;

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  ensureCreated(state, now);

  // Production reserve always takes the canonical 1800s lease, including
  // replay of an active or terminal idempotency key. Missing/false must not
  // return a cached reservation, capability, or occupancy mutation.
  if (input.acquire_lease !== true) {
    await saveState(storage, state);
    return { ok: false, error: "lease_required" };
  }

  const existing = state.reservations[key.idempotency_key];
  if (existing) {
    if (existing.request_digest !== digest) {
      await saveState(storage, state);
      return { ok: false, error: "idempotency_digest_conflict" };
    }
    if (existing.status !== "released") {
      const lease = existing.lease_id ? state.leases[existing.lease_id] ?? null : null;
      await saveState(storage, state);
      return {
        ok: true,
        reservation: publicReservation(existing),
        lease,
        existing: true,
        budget_run_id: existing.reservation_id,
      };
    }
    // A released reservation provably never crossed the provider marker, so a
    // same-digest retry may obtain a fresh run. Provider-started work is never
    // represented by the released status.
  }

  // A frozen ledger still serves terminal idempotent results above, but never
  // authorizes a new provider side effect.
  if (state.frozen) {
    await saveState(storage, state);
    return {
      ok: false,
      error: "budget_frozen",
      detail: state.frozen_reason || "actual_exceeds_reserved",
    };
  }

  const over = insufficient(state, amounts);
  if (over) {
    await saveState(storage, state);
    return {
      ok: false,
      error: "budget_exhausted",
      detail: `${over.name}: used=${over.used} reserved=${over.reserved} delta=${over.delta} limit=${over.limit}`,
    };
  }

  const active = activeLeaseCount(state);
  if (active >= PILOT_BUDGET_CAPS.max_parallel_experiments) {
    await saveState(storage, state);
    return {
      ok: false,
      error: "budget_exhausted",
      detail: `concurrent_experiments: active=${active} limit=${PILOT_BUDGET_CAPS.max_parallel_experiments}`,
    };
  }
  const leaseId = crypto.randomUUID();
  const lease: Lease = {
    lease_id: leaseId,
    reservation_key: key.idempotency_key,
    acquired_at: now,
    expires_at: now + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000,
    last_heartbeat_at: now,
    released_at: null,
  };
  state.leases[leaseId] = lease;

  const reservation: Reservation = {
    idempotency_key: key.idempotency_key,
    reservation_id: crypto.randomUUID(),
    amounts: amountsFromCounters(amounts),
    actual: null,
    status: "reserved",
    lease_id: lease.lease_id,
    created_at: now,
    reconciled_at: null,
    released_at: null,
    request_digest: digest,
    cached_result: null,
    finalize_error: null,
    settlement: null,
    provider_started_at: null,
    uncertainty_reason: null,
    settlement_capability_hash: null,
    settlement_capability_consumed: false,
    settlement_capability_secret: null,
  };
  state.reserved = applyDelta(state.reserved, reservation.amounts, 1);
  state.reservations[key.idempotency_key] = reservation;
  await saveState(storage, state);
  return {
    ok: true,
    reservation: publicReservation(reservation),
    lease,
    existing: false,
    budget_run_id: reservation.reservation_id,
  };
}

const FORBIDDEN_CAPABILITY_KEYS = new Set<SensitiveCapabilityField>([
  "settlement_capability",
  "settlement_capability_secret",
  "settlement_capability_hash",
]);

/** Closed Gateway success envelope. Nested artifact contents are still deep-scanned. */
const PUBLIC_SUCCESS_BODY_KEYS = new Set([
  "ok",
  "schema",
  "schema_version",
  "artifact",
  "model",
  "input_tokens",
  "output_tokens",
  "cached_tokens",
  "monetary_cost_usd",
  "prompt_digest",
  "output_digest",
  "ready_snapshot_id",
  "experiment_id",
  "budget_id",
  "budget_run_id",
]);

const PUBLIC_ERROR_BODY_KEYS = new Set(["ok", "error", "detail", "budget_run_id"]);

function capabilityMaterialSet(
  reservation: Reservation,
  submittedCapability?: string,
): Set<string> {
  const material = new Set<string>();
  if (reservation.settlement_capability_hash) {
    material.add(reservation.settlement_capability_hash);
  }
  if (reservation.settlement_capability_secret) {
    material.add(reservation.settlement_capability_secret);
  }
  const submitted =
    typeof submittedCapability === "string" ? submittedCapability.trim() : "";
  if (submitted) material.add(submitted);
  return material;
}

function capabilityMaterialTokens(material: Set<string>): string[] {
  return [...material].filter((token) => token.length > 0);
}

function publicJsonText(value: unknown): string | null {
  try {
    const encoded = JSON.stringify(value);
    return typeof encoded === "string" ? encoded : null;
  } catch {
    return null;
  }
}

function textContainsCapabilityMaterial(text: string, tokens: string[]): boolean {
  for (const token of tokens) {
    if (text.includes(token)) return true;
  }
  return false;
}

/**
 * True when the current settlement capability or stored hash occurs in public
 * JSON/string text. Tokens are hex-safe, but both the decoded string and its
 * canonical JSON encoding are searched so prefix/suffix/wrapped values cannot
 * persist or return.
 */
function valueContainsCapabilityMaterial(value: unknown, material: Set<string>): boolean {
  const tokens = capabilityMaterialTokens(material);
  if (!tokens.length) return false;
  if (typeof value === "string") {
    if (textContainsCapabilityMaterial(value, tokens)) return true;
    const encoded = publicJsonText(value);
    return encoded !== null && textContainsCapabilityMaterial(encoded, tokens);
  }
  const encoded = publicJsonText(value);
  if (encoded === null) return true;
  return textContainsCapabilityMaterial(encoded, tokens);
}

function rejectCapabilityMaterial(
  value: unknown,
  material: Set<string>,
): BudgetErr | null {
  if (typeof value === "string" && valueContainsCapabilityMaterial(value, material)) {
    return { ok: false, error: "cached_result_capability_material" };
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = rejectCapabilityMaterial(item, material);
      if (nested) return nested;
    }
    return null;
  }
  if (value && typeof value === "object") {
    for (const [key, nestedValue] of Object.entries(value as Record<string, unknown>)) {
      if (FORBIDDEN_CAPABILITY_KEYS.has(key as SensitiveCapabilityField)) {
        return { ok: false, error: "cached_result_capability_field" };
      }
      if (valueContainsCapabilityMaterial(key, material)) {
        return { ok: false, error: "cached_result_capability_material" };
      }
      const nested = rejectCapabilityMaterial(nestedValue, material);
      if (nested) return nested;
    }
  }
  return null;
}

function canonicalizeCachedResult(
  result: CachedBudgetResult | undefined,
  material: Set<string>,
): BudgetResult<{ value: CachedBudgetResult | undefined }> {
  if (!result) return { ok: true, value: undefined };
  const status = Number(result.http_status);
  if (!Number.isInteger(status) || status < 200 || status > 599) {
    return { ok: false, error: "cached_result_invalid" };
  }
  const body = result.body;
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { ok: false, error: "cached_result_invalid" };
  }
  const rec = body as Record<string, unknown>;
  if (rec.ok === true) {
    const extra = Object.keys(rec).filter((key) => !PUBLIC_SUCCESS_BODY_KEYS.has(key));
    if (extra.length) return { ok: false, error: "cached_result_invalid" };
  } else if (rec.ok === false) {
    const extra = Object.keys(rec).filter((key) => !PUBLIC_ERROR_BODY_KEYS.has(key));
    if (extra.length) return { ok: false, error: "cached_result_invalid" };
    if (typeof rec.error !== "string" || !rec.error) {
      return { ok: false, error: "cached_result_invalid" };
    }
  } else {
    return { ok: false, error: "cached_result_invalid" };
  }
  const leaked = rejectCapabilityMaterial(rec, material);
  if (leaked) return leaked;
  if (valueContainsCapabilityMaterial(rec, material)) {
    return { ok: false, error: "cached_result_capability_material" };
  }
  return {
    ok: true,
    value: { http_status: status, body: structuredClone(rec) },
  };
}

function scrubPublicValue(value: unknown, material: Set<string>): unknown {
  if (typeof value === "string") {
    return valueContainsCapabilityMaterial(value, material) ? null : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => scrubPublicValue(item, material));
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
      if (FORBIDDEN_CAPABILITY_KEYS.has(key as SensitiveCapabilityField)) continue;
      if (valueContainsCapabilityMaterial(key, material)) continue;
      out[key] = scrubPublicValue(nested, material);
    }
    return out;
  }
  return value;
}

function publicCachedResult(
  cached: CachedBudgetResult | null,
  material: Set<string>,
): CachedBudgetResult | null {
  if (!cached) return null;
  const body = scrubPublicValue(cached.body, material);
  if (valueContainsCapabilityMaterial(body, material)) return null;
  return {
    http_status: cached.http_status,
    body,
  };
}

function publicReservation(reservation: Reservation): PublicReservation {
  const material = capabilityMaterialSet(reservation);
  return {
    idempotency_key: reservation.idempotency_key,
    reservation_id: reservation.reservation_id,
    amounts: amountsFromCounters(reservation.amounts),
    actual: reservation.actual ? amountsFromCounters(reservation.actual) : null,
    status: reservation.status,
    lease_id: reservation.lease_id,
    created_at: reservation.created_at,
    reconciled_at: reservation.reconciled_at,
    released_at: reservation.released_at,
    request_digest: reservation.request_digest,
    cached_result: publicCachedResult(reservation.cached_result, material),
    finalize_error: reservation.finalize_error,
    settlement: reservation.settlement,
    provider_started_at: reservation.provider_started_at,
    uncertainty_reason: reservation.uncertainty_reason,
    settlement_capability_consumed: reservation.settlement_capability_consumed === true,
  };
}

function requireNonemptyRequestDigest(raw: unknown): BudgetResult<{ request_digest: string }> {
  if (typeof raw !== "string" || !raw.trim()) {
    return { ok: false, error: "request_digest required" };
  }
  return { ok: true, request_digest: raw.trim() };
}

function requireExactLeaseAndDigest(
  input: { request_digest?: string; lease_id?: string },
  reservation: Reservation,
): BudgetErr | null {
  const digest = typeof input.request_digest === "string" ? input.request_digest.trim() : "";
  if (!digest) return { ok: false, error: "request_digest required" };
  if (typeof reservation.request_digest !== "string" || !reservation.request_digest.trim()) {
    return { ok: false, error: "request_digest required" };
  }
  if (reservation.request_digest !== digest) {
    return { ok: false, error: "request_digest_mismatch" };
  }
  const leaseId = typeof input.lease_id === "string" ? input.lease_id.trim() : "";
  if (!leaseId) return { ok: false, error: "lease_id required" };
  if (typeof reservation.lease_id !== "string" || !reservation.lease_id.trim()) {
    return { ok: false, error: "lease_id required" };
  }
  if (reservation.lease_id !== leaseId) {
    return { ok: false, error: "lease_mismatch" };
  }
  return null;
}

async function sha256HexUtf8(text: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function settlementCapabilityMaterial(
  capability: string,
  reservation: Reservation,
): string {
  return [
    capability,
    reservation.idempotency_key,
    reservation.reservation_id,
    reservation.lease_id ?? "",
    reservation.request_digest ?? "",
  ].join(":");
}

async function hashSettlementCapability(
  capability: string,
  reservation: Reservation,
): Promise<string> {
  return sha256HexUtf8(settlementCapabilityMaterial(capability, reservation));
}

function mintSettlementCapabilitySecret(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function markProviderStarted(
  storage: BudgetStorage,
  input: { idempotency_key: string; lease_id: string; request_digest?: string },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: PublicReservation;
    budget_run_id: string;
    settlement_capability: string | null;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const leaseId = typeof input.lease_id === "string" ? input.lease_id.trim() : "";
  if (!leaseId) return { ok: false, error: "lease_id required" };
  const digest = typeof input.request_digest === "string" ? input.request_digest.trim() : "";
  if (!digest) return { ok: false, error: "request_digest required" };

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  const reservation = state.reservations[key.idempotency_key];
  if (!reservation) {
    await saveState(storage, state);
    return { ok: false, error: "reservation_not_found" };
  }
  if (reservation.status !== "reserved") {
    await saveState(storage, state);
    return { ok: false, error: `reservation_${reservation.status}` };
  }
  if (state.frozen && reservation.provider_started_at === null) {
    await saveState(storage, state);
    return {
      ok: false,
      error: "budget_frozen",
      detail: state.frozen_reason || "provider usage audit required",
    };
  }
  const bound = requireExactLeaseAndDigest(
    { request_digest: digest, lease_id: leaseId },
    reservation,
  );
  if (bound) {
    await saveState(storage, state);
    return bound;
  }
  const lease = state.leases[leaseId];
  if (
    reservation.lease_id !== leaseId ||
    !lease ||
    lease.reservation_key !== key.idempotency_key ||
    lease.released_at !== null
  ) {
    await saveState(storage, state);
    return { ok: false, error: "lease_not_active" };
  }
  if (reservation.provider_started_at !== null) {
    const replayed =
      !reservation.settlement_capability_consumed && reservation.settlement_capability_secret
        ? reservation.settlement_capability_secret
        : null;
    await saveState(storage, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      budget_run_id: reservation.reservation_id,
      settlement_capability: replayed,
    };
  }
  const capability = mintSettlementCapabilitySecret();
  reservation.provider_started_at = now;
  reservation.settlement_capability_hash = await hashSettlementCapability(
    capability,
    reservation,
  );
  reservation.settlement_capability_consumed = false;
  reservation.settlement_capability_secret = capability;
  await saveState(storage, state);
  return {
    ok: true,
    reservation: publicReservation(reservation),
    budget_run_id: reservation.reservation_id,
    settlement_capability: capability,
  };
}

export type UncertainProviderReason =
  | "timeout"
  | "provider_error"
  | "usage_unavailable"
  | "finalize_failed"
  | "worker_interrupted"
  | "lease_expired";

const UNCERTAIN_PROVIDER_REASONS = new Set<UncertainProviderReason>([
  "timeout",
  "provider_error",
  "usage_unavailable",
  "finalize_failed",
  "worker_interrupted",
  "lease_expired",
]);

function uncertainResult(
  reservation: Reservation,
  reason: UncertainProviderReason,
): CachedBudgetResult {
  const httpStatus = reason === "timeout" ? 504 : reason === "provider_error" ? 502 : 500;
  const error =
    reason === "timeout"
      ? "ai_run_timeout"
      : reason === "provider_error"
        ? "ai_run_failed"
        : "budget_settlement_uncertain";
  return {
    http_status: httpStatus,
    body: {
      ok: false,
      error,
      budget_run_id: reservation.reservation_id,
    },
  };
}

/**
 * Exact identity/capability check used before first settle and before every
 * terminal replay. The one-way hash remains valid after consume; the secret is
 * never returned. Does not mutate reservation state.
 */
async function verifySettlementAuthority(
  reservation: Reservation,
  input: {
    settlement_capability?: string;
    request_digest?: string;
    lease_id?: string;
  },
): Promise<BudgetErr | null> {
  const bound = requireExactLeaseAndDigest(input, reservation);
  if (bound) return bound;
  const capability =
    typeof input.settlement_capability === "string"
      ? input.settlement_capability.trim()
      : "";
  if (!capability || !reservation.settlement_capability_hash) {
    return { ok: false, error: "settlement_capability_required" };
  }
  const expected = await hashSettlementCapability(capability, reservation);
  if (expected !== reservation.settlement_capability_hash) {
    return { ok: false, error: "settlement_capability_invalid" };
  }
  return null;
}

function consumeVerifiedCapability(reservation: Reservation): void {
  reservation.settlement_capability_consumed = true;
  reservation.settlement_capability_secret = null;
}

/**
 * Exact idempotency for terminal settlement:
 * - Digest, lease id, and capability hash are verified before every replay.
 * - An exact retry after response loss returns the persisted terminal result
 *   without recharging, recomputing, or reopening the lease.
 * - Wrong or omitted digest, lease, idempotency identity, or capability fails
 *   closed and returns no cached result or reservation.
 * - Cross-operation replay (finalize vs uncertain) with the same identity
 *   returns the already persisted terminal state and never turns wrong
 *   authority into success.
 */
export async function settleUncertainBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    reason: UncertainProviderReason;
    request_digest?: string;
    lease_id?: string;
    settlement_capability?: string;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: PublicReservation;
    used: Counters;
    frozen: boolean;
    budget_run_id: string;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  if (!UNCERTAIN_PROVIDER_REASONS.has(input.reason)) {
    return { ok: false, error: "uncertainty_reason invalid" };
  }

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  const reservation = state.reservations[key.idempotency_key];
  if (!reservation) {
    await saveState(storage, state);
    return { ok: false, error: "reservation_not_found" };
  }
  if (reservation.status === "reconciled") {
    const verified = await verifySettlementAuthority(reservation, input);
    if (verified) {
      await saveState(storage, state);
      return verified;
    }
    reservation.settlement_capability_secret = null;
    await saveState(storage, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      used: amountsFromCounters(state.used),
      frozen: state.frozen,
      budget_run_id: reservation.reservation_id,
    };
  }
  if (reservation.status === "released") {
    await saveState(storage, state);
    return { ok: false, error: "reservation_released" };
  }
  if (reservation.provider_started_at === null) {
    await saveState(storage, state);
    return { ok: false, error: "provider_not_started" };
  }
  const verified = await verifySettlementAuthority(reservation, input);
  if (verified) {
    await saveState(storage, state);
    return verified;
  }
  if (reservation.settlement_capability_consumed) {
    await saveState(storage, state);
    return { ok: false, error: "settlement_capability_consumed" };
  }
  consumeVerifiedCapability(reservation);
  chargeUncertainReservation(state, reservation, input.reason, now);
  await saveState(storage, state);
  return {
    ok: true,
    reservation: publicReservation(reservation),
    used: amountsFromCounters(state.used),
    frozen: true,
    budget_run_id: reservation.reservation_id,
  };
}

function applyCachedResult(
  reservation: Reservation,
  result: CachedBudgetResult | undefined,
): void {
  if (!result) return;
  reservation.cached_result = result;
}

export async function reconcileBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    request_digest: string;
    lease_id: string;
    settlement_capability: string;
    usage: unknown;
    terminal_result?: CachedBudgetResult;
  },
  now = Date.now(),
): Promise<BudgetResult<{ reservation: PublicReservation; used: Counters }>> {
  const finalized = await finalizeBudget(storage, input, now);
  if (!finalized.ok) return finalized;
  return { ok: true, reservation: finalized.reservation, used: finalized.used };
}

function deriveExactSettlement(
  reservation: Reservation,
  usage: Counters,
  terminalResult: CachedBudgetResult | undefined,
): BudgetSettlement {
  const httpStatus = Number(terminalResult?.http_status);
  const outcome: BudgetSettlement["outcome"] =
    httpStatus === 200 ? "success" : "schema_reject";
  return {
    outcome,
    usage_source: "provider",
    estimated_cost_usd: reservation.amounts.cost_usd,
    actual_cost_usd: usage.cost_usd,
    billed_cost_usd: usage.cost_usd,
    actual_input_tokens: usage.input_tokens,
    actual_output_tokens: usage.output_tokens,
    actual_cached_tokens: usage.cached_tokens,
  };
}

export async function finalizeBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    request_digest: string;
    lease_id: string;
    settlement_capability: string;
    usage: unknown;
    terminal_result?: CachedBudgetResult;
    amounts?: unknown;
    result?: CachedBudgetResult;
    settlement?: BudgetSettlement;
  },
  // amounts/result/settlement are accepted only so caller-authored claims can
  // be rejected as non-authority instead of silently charging.
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: PublicReservation;
    used: Counters;
    frozen: boolean;
    budget_run_id: string;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  if (
    input.settlement !== undefined ||
    input.amounts !== undefined ||
    input.result !== undefined
  ) {
    return { ok: false, error: "caller_settlement_rejected" };
  }
  const parsed = parseAmounts(input.usage);
  if (!parsed.ok) return parsed;
  const actual = parsed.amounts;

  const state = await loadState(storage, now);
  recoverExpired(state, now);
  const reservation = state.reservations[key.idempotency_key];
  if (!reservation) return { ok: false, error: "reservation_not_found" };
  if (reservation.status === "reconciled") {
    const verified = await verifySettlementAuthority(reservation, input);
    if (verified) {
      await saveState(storage, state);
      return verified;
    }
    reservation.settlement_capability_secret = null;
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
      reservation: publicReservation(reservation),
      used: amountsFromCounters(state.used),
      frozen: state.frozen,
      budget_run_id: reservation.reservation_id,
    };
  }
  if (reservation.status === "released") {
    return { ok: false, error: "reservation_released" };
  }
  if (reservation.provider_started_at === null) {
    await saveState(storage, state);
    return { ok: false, error: "provider_not_started" };
  }
  const verified = await verifySettlementAuthority(reservation, input);
  if (verified) {
    await saveState(storage, state);
    return verified;
  }
  const canonical = canonicalizeCachedResult(
    input.terminal_result,
    capabilityMaterialSet(reservation, input.settlement_capability),
  );
  if (!canonical.ok) {
    await saveState(storage, state);
    return canonical;
  }
  if (reservation.settlement_capability_consumed) {
    await saveState(storage, state);
    return { ok: false, error: "settlement_capability_consumed" };
  }
  consumeVerifiedCapability(reservation);

  const over = exceedsReserved(reservation.amounts, actual);
  state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
  // Release the estimate in full, then record billed spend exactly.  If the
  // estimate was too low, freeze future work without clipping audit history.
  state.used = applyDelta(state.used, actual, 1);
  reservation.status = "reconciled";
  reservation.actual = amountsFromCounters(actual);
  reservation.settlement = deriveExactSettlement(
    reservation,
    actual,
    canonical.value,
  );
  reservation.reconciled_at = now;
  applyCachedResult(reservation, canonical.value);
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
    reservation: publicReservation(reservation),
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
): Promise<
  BudgetResult<{ released: boolean; lease: Lease | null; reservation: PublicReservation | null }>
> {
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
  if (
    lease &&
    reservation &&
    (lease.reservation_key !== reservation.idempotency_key ||
      reservation.lease_id !== lease.lease_id)
  ) {
    await saveState(storage, state);
    return { ok: false, error: "lease_reservation_mismatch" };
  }

  if (lease && lease.released_at === null) {
    lease.released_at = now;
  }
  if (reservation && reservation.status === "reserved") {
    if (reservation.provider_started_at !== null) {
      chargeUncertainReservation(state, reservation, "worker_interrupted", now);
      await saveState(storage, state);
      return {
        ok: false,
        error: "provider_usage_uncertain",
        detail: "provider side effect was already started; reservation charged at maximum",
      };
    }
    state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
    reservation.status = "released";
    reservation.released_at = now;
  }
  await saveState(storage, state);
  return {
    ok: true,
    released: true,
    lease,
    reservation: reservation ? publicReservation(reservation) : null,
  };
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

export function createBudgetCoordinator(storage: BudgetStorage) {
  return {
    reserve(
      input: Parameters<typeof reserveBudget>[1],
      now?: number,
    ): ReturnType<typeof reserveBudget> {
      return reserveBudget(storage, input, now);
    },
    markProviderStarted(
      input: Parameters<typeof markProviderStarted>[1],
      now?: number,
    ): ReturnType<typeof markProviderStarted> {
      return markProviderStarted(storage, input, now);
    },
    finalizeExact(
      input: Parameters<typeof finalizeBudget>[1],
      now?: number,
    ): ReturnType<typeof finalizeBudget> {
      return finalizeBudget(storage, input, now);
    },
    settleUncertain(
      input: Parameters<typeof settleUncertainBudget>[1],
      now?: number,
    ): ReturnType<typeof settleUncertainBudget> {
      return settleUncertainBudget(storage, input, now);
    },
    release(
      input: Parameters<typeof releaseBudget>[1],
      now?: number,
    ): ReturnType<typeof releaseBudget> {
      return releaseBudget(storage, input, now);
    },
    heartbeat(
      leaseId: string,
      now?: number,
    ): ReturnType<typeof heartbeatLease> {
      return heartbeatLease(storage, leaseId, now);
    },
    snapshot(now?: number): ReturnType<typeof snapshotBudget> {
      return snapshotBudget(storage, now);
    },
  };
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
