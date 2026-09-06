/** Durable Object hard budget occupancy algebra. Presence of budget_id is not a reserve. */

import controlledPilotPolicy from "../../../../specs/policy/controlled_pilot_policy.json";
import {
  AI_GATEWAY_PRICING_POLICY_DIGEST,
  AI_GATEWAY_PRICING_POLICY_ID,
  estimateCostUsd,
} from "./pricing_policy";

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
  usage_source:
    | "provider"
    | "provider_tokens_estimated_cost"
    | "legacy_unattributed"
    | "reserved_max_uncertain";
  estimated_cost_usd: number;
  actual_cost_usd: number | null;
  billed_cost_usd: number;
  actual_input_tokens: number | null;
  actual_output_tokens: number | null;
  actual_cached_tokens: number | null;
  provider_model: string | null;
  pricing_policy_id: string | null;
  pricing_policy_digest: string | null;
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
  /**
   * SHA-256 of the Gateway-invocation-private reserve owner capability.
   * The capability itself is never persisted or returned. A legacy/internal
   * reservation may be unowned (null) and cannot use owner recovery/cancel.
   */
  reserve_owner_capability_hash: string | null;
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
  | "owner_capability_hash"
  | "reserve_owner_capability"
  | "reserve_owner_capability_hash"
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

/** Keep response-reordering cancellation authority for one canonical lease window. */
export const OWNER_CANCELLATION_TOMBSTONE_TTL_MS =
  PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000;

/**
 * A ledger is currently persisted as one Durable Object storage value. Keep
 * this transitional representation far below the 2 MiB per-value ceiling:
 * 1.5 MiB leaves 512 KiB for storage-encoding overhead, and the mutable limit
 * reserves a further 16 KiB so cancellation quarantine can always be written.
 * This guard fails closed; it does not replace the pending row-per-reservation
 * migration needed for indefinitely retained terminal history.
 */
export const MAX_SERIALIZED_LEDGER_STATE_BYTES = 1_572_864;
export const OWNER_CANCELLATION_QUARANTINE_HEADROOM_BYTES = 16 * 1024;
export const MAX_MUTABLE_LEDGER_STATE_BYTES =
  MAX_SERIALIZED_LEDGER_STATE_BYTES -
  OWNER_CANCELLATION_QUARANTINE_HEADROOM_BYTES;

/** Bounded so worst-case canonical tombstones remain well inside one value. */
export const MAX_OWNER_CANCELLATION_TOMBSTONES = 512;
export const MAX_IDEMPOTENCY_KEY_BYTES = 256;
const REQUEST_DIGEST_RE = /^[0-9a-f]{64}$/;

export type OwnerCancellationTombstone = {
  owner_capability_hash: string;
  idempotency_key: string;
  request_digest: string;
  created_at: number;
  expires_at: number;
};

export type LedgerState = {
  created: boolean;
  created_at: number;
  caps: typeof PILOT_BUDGET_CAPS;
  used: Counters;
  reserved: Counters;
  reservations: Record<string, Reservation>;
  leases: Record<string, Lease>;
  owner_cancellation_tombstones: Record<string, OwnerCancellationTombstone>;
  /**
   * Fail-closed window used only when a cancellation cannot obtain a bounded
   * tombstone slot. No reserve may start/recover occupancy until it expires.
   */
  owner_cancellation_quarantine_until: number | null;
  frozen: boolean;
  frozen_at: number | null;
  frozen_reason: string | null;
  audit: BudgetAuditRecord[];
};

export type BudgetErr = { ok: false; error: string; detail?: string };
export type BudgetOk<T> = { ok: true } & T;
export type BudgetResult<T> = BudgetOk<T> | BudgetErr;

export class PersistedBudgetStateError extends Error {
  constructor(detail: string) {
    super(`persisted_budget_state_invalid:${detail}`);
    this.name = "PersistedBudgetStateError";
  }
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function serializedLedgerStateBytes(value: unknown): number {
  try {
    const encoded = JSON.stringify(value);
    if (typeof encoded !== "string") {
      throw new PersistedBudgetStateError("ledger_not_serializable");
    }
    return utf8ByteLength(encoded);
  } catch (error) {
    if (error instanceof PersistedBudgetStateError) throw error;
    throw new PersistedBudgetStateError("ledger_not_serializable");
  }
}

function requireLedgerStateWithinAbsoluteValueLimit(state: LedgerState): number {
  const bytes = serializedLedgerStateBytes(state);
  if (bytes > MAX_SERIALIZED_LEDGER_STATE_BYTES) {
    throw new PersistedBudgetStateError("ledger_serialized_size_exceeds_safe_limit");
  }
  return bytes;
}

function requireLedgerStateWithinCommitLimit(state: LedgerState): void {
  const bytes = requireLedgerStateWithinAbsoluteValueLimit(state);
  if (
    state.owner_cancellation_quarantine_until === null &&
    bytes > MAX_MUTABLE_LEDGER_STATE_BYTES
  ) {
    throw new PersistedBudgetStateError("ledger_serialized_size_exhausts_quarantine_headroom");
  }
}

export interface AtomicBudgetStorage {
  get<T>(key: string): Promise<T | undefined>;
  /** Atomically persist ledger state and its one recovery alarm. */
  commit(key: string, value: unknown, nextAlarm: number | null): Promise<void>;
}

export interface BudgetStorage extends AtomicBudgetStorage {
  /**
   * Run one read/transition/write cycle as a storage transaction. The callback
   * may await storage operations only; randomness and WebCrypto must be
   * completed before entering it.
   */
  runAtomic<T>(work: (storage: AtomicBudgetStorage) => Promise<T>): Promise<T>;
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
    owner_cancellation_tombstones: {},
    owner_cancellation_quarantine_until: null,
    frozen: false,
    frozen_at: null,
    frozen_reason: null,
    audit: [],
  };
}

export class MemoryBudgetStorage implements BudgetStorage {
  private data = new Map<string, unknown>();
  private alarm: number | null = null;
  private transactionTail: Promise<void> = Promise.resolve();

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

  async runAtomic<T>(work: (storage: AtomicBudgetStorage) => Promise<T>): Promise<T> {
    let unlock!: () => void;
    const previous = this.transactionTail;
    this.transactionTail = new Promise<void>((resolve) => {
      unlock = resolve;
    });
    await previous;
    const stagedData = structuredClone(this.data);
    let stagedAlarm = this.alarm;
    const transaction: AtomicBudgetStorage = {
      get: async <V>(key: string) => {
        if (!stagedData.has(key)) return undefined;
        return structuredClone(stagedData.get(key)) as V;
      },
      commit: async (key: string, value: unknown, nextAlarm: number | null) => {
        stagedData.set(key, structuredClone(value));
        stagedAlarm = nextAlarm;
      },
    };
    try {
      const result = await work(transaction);
      this.data = stagedData;
      this.alarm = stagedAlarm;
      return result;
    } finally {
      unlock();
    }
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
    if (!Object.prototype.hasOwnProperty.call(obj, name)) continue;
    const rawValue = obj[name];
    if (typeof rawValue !== "number" || !Number.isFinite(rawValue) || rawValue < 0) {
      return { ok: false, error: `${name} must be a finite number >= 0` };
    }
    if (name !== "cost_usd" && !Number.isSafeInteger(rawValue)) {
      return { ok: false, error: `${name} must be an integer >= 0` };
    }
    amounts[name] =
      name === "cost_usd" ? usdMicros(rawValue) / 1_000_000 : rawValue;
  }
  if (amounts.cached_tokens > amounts.input_tokens) {
    return { ok: false, error: "cached_tokens must be a subset of input_tokens" };
  }
  return { ok: true, amounts };
}

type ExactUsageEvidence = {
  amounts: Counters;
  reported_cost_usd: number;
  cost_source: "provider" | "pricing_policy_estimate";
  provider_model: string;
  pricing_policy_id: string | null;
  pricing_policy_digest: string | null;
};

function parseActualUsage(raw: unknown): BudgetResult<ExactUsageEvidence> {
  const required = [
    "model_calls",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "cost_usd",
    "cost_source",
    "provider_model",
    "pricing_policy_id",
    "pricing_policy_digest",
  ] as const;
  let values: Record<string, unknown>;
  try {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
      return { ok: false, error: "usage must be a closed object" };
    }
    const prototype = Object.getPrototypeOf(raw);
    if (prototype !== Object.prototype && prototype !== null) {
      return { ok: false, error: "usage must be a closed object" };
    }
    const ownKeys = Reflect.ownKeys(raw);
    if (ownKeys.some((key) => typeof key !== "string")) {
      return { ok: false, error: "usage contains an unknown field" };
    }
    const stringKeys = ownKeys as string[];
    const unknown = stringKeys.find(
      (key) => !required.includes(key as (typeof required)[number]),
    );
    if (unknown) return { ok: false, error: `unknown usage field: ${unknown}` };
    const missing = required.find((key) => !stringKeys.includes(key));
    if (missing) return { ok: false, error: `missing usage field: ${missing}` };
    const descriptors = Object.getOwnPropertyDescriptors(raw);
    values = {};
    for (const key of required) {
      const descriptor = descriptors[key];
      if (!descriptor?.enumerable || !("value" in descriptor)) {
        return { ok: false, error: `usage field must be plain data: ${key}` };
      }
      values[key] = descriptor.value;
    }
  } catch {
    return { ok: false, error: "usage must be a closed object" };
  }

  if (values.model_calls !== 1) {
    return { ok: false, error: "model_calls must equal 1" };
  }
  for (const name of ["input_tokens", "output_tokens", "cached_tokens"] as const) {
    const value = values[name];
    if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
      return { ok: false, error: `${name} must be an integer >= 0` };
    }
  }
  if ((values.cached_tokens as number) > (values.input_tokens as number)) {
    return { ok: false, error: "cached_tokens must be a subset of input_tokens" };
  }
  const cost = values.cost_usd;
  if (
    typeof cost !== "number" ||
    !Number.isFinite(cost) ||
    cost < 0 ||
    !Number.isSafeInteger(usdMicros(cost))
  ) {
    return { ok: false, error: "cost_usd must be a finite number >= 0" };
  }
  const costSource = values.cost_source;
  if (costSource !== "provider" && costSource !== "pricing_policy_estimate") {
    return { ok: false, error: "cost_source must identify provider or pricing policy" };
  }
  const providerModel = values.provider_model;
  if (typeof providerModel !== "string" || !providerModel || providerModel.length > 256) {
    return { ok: false, error: "provider_model must be a bounded non-empty string" };
  }
  const pricingPolicyId = values.pricing_policy_id;
  const pricingPolicyDigest = values.pricing_policy_digest;
  if (costSource === "provider") {
    if (pricingPolicyId !== null || pricingPolicyDigest !== null) {
      return { ok: false, error: "provider cost must not claim a pricing policy" };
    }
  } else {
    if (
      pricingPolicyId !== AI_GATEWAY_PRICING_POLICY_ID ||
      pricingPolicyDigest !== AI_GATEWAY_PRICING_POLICY_DIGEST
    ) {
      return { ok: false, error: "pricing policy identity mismatch" };
    }
    const expected = estimateCostUsd(
      providerModel,
      values.input_tokens as number,
      values.output_tokens as number,
    );
    if (usdMicros(cost) !== usdMicros(expected)) {
      return { ok: false, error: "pricing policy cost mismatch" };
    }
  }
  const amounts = zeroCounters();
  amounts.model_calls = 1;
  amounts.input_tokens = values.input_tokens as number;
  amounts.output_tokens = values.output_tokens as number;
  amounts.cached_tokens = values.cached_tokens as number;
  amounts.cost_usd = usdMicros(cost) / 1_000_000;
  return {
    ok: true,
    amounts,
    reported_cost_usd: cost,
    cost_source: costSource,
    provider_model: providerModel,
    pricing_policy_id: pricingPolicyId as string | null,
    pricing_policy_digest: pricingPolicyDigest as string | null,
  };
}

function amountsFromCounters(c: Counters): Counters {
  return { ...c };
}

function requirePersistedCounters(raw: unknown, label: string): Counters {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new PersistedBudgetStateError(`${label}:counters_not_object`);
  }
  const values = raw as Record<string, unknown>;
  const keys = Object.keys(values);
  if (
    keys.length !== COUNTERS.length ||
    keys.some((key) => !COUNTERS.includes(key as CounterName))
  ) {
    throw new PersistedBudgetStateError(`${label}:counter_fields_not_closed`);
  }
  const out = zeroCounters();
  for (const name of COUNTERS) {
    const value = values[name];
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      value < 0 ||
      (name !== "cost_usd" && !Number.isSafeInteger(value)) ||
      (name === "cost_usd" && !Number.isSafeInteger(usdMicros(value)))
    ) {
      throw new PersistedBudgetStateError(`${label}:${name}_invalid`);
    }
    out[name] = name === "cost_usd" ? usdMicros(value) / 1_000_000 : value;
  }
  if (out.cached_tokens > out.input_tokens) {
    throw new PersistedBudgetStateError(
      `${label}:cached_tokens_not_input_subset`,
    );
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
  if (utf8ByteLength(key) > MAX_IDEMPOTENCY_KEY_BYTES) {
    return { ok: false, error: "idempotency_key too long" };
  }
  return { ok: true, idempotency_key: key };
}

/** Bind a caller Idempotency-Key to a request digest. Missing key uses the digest. */
export function bindIdempotencyKey(
  clientKey: string | undefined | null,
  requestDigest: string,
): BudgetResult<{ idempotency_key: string; request_digest: string }> {
  const boundedDigest = requireNonemptyRequestDigest(requestDigest);
  if (!boundedDigest.ok) return boundedDigest;
  const digest = boundedDigest.request_digest;
  const client = typeof clientKey === "string" ? clientKey.trim() : "";
  if (client) {
    const boundedKey = requireIdempotencyKey(client);
    if (!boundedKey.ok) return boundedKey;
    return { ok: true, idempotency_key: boundedKey.idempotency_key, request_digest: digest };
  }
  return { ok: true, idempotency_key: `digest:${digest}`, request_digest: digest };
}

const OWNER_CAPABILITY_RE = /^[0-9a-f]{64}$/;

function requireReserveOwnerCapability(
  raw: unknown,
): BudgetResult<{ reserve_owner_capability: string }> {
  if (typeof raw !== "string" || !OWNER_CAPABILITY_RE.test(raw)) {
    return { ok: false, error: "reserve_owner_capability invalid" };
  }
  return { ok: true, reserve_owner_capability: raw };
}

async function hashReserveOwnerCapability(
  capability: string,
  idempotencyKey: string,
  requestDigest: string,
): Promise<string> {
  return sha256HexUtf8(
    JSON.stringify([
      "budget-reserve-owner/v1",
      capability,
      idempotencyKey,
      requestDigest,
    ]),
  );
}

function timingSafeEqualHex(left: string, right: string): boolean {
  if (!OWNER_CAPABILITY_RE.test(left) || !OWNER_CAPABILITY_RE.test(right)) {
    return false;
  }
  let different = 0;
  for (let i = 0; i < left.length; i += 1) {
    different |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return different === 0;
}

function reserveOwnerMatches(
  reservation: Reservation,
  submittedHash: string | null,
): boolean {
  return Boolean(
    submittedHash &&
      reservation.reserve_owner_capability_hash &&
      timingSafeEqualHex(submittedHash, reservation.reserve_owner_capability_hash),
  );
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

function requireNullableUsageToken(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new PersistedBudgetStateError(`${label}_invalid`);
  }
  return value;
}

function requirePersistedSettlement(
  raw: unknown,
  reservedAmounts: Counters,
  actualAmounts: Counters | null,
): BudgetSettlement | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    throw new PersistedBudgetStateError("settlement_not_object");
  }
  const settlement = raw as Record<string, unknown>;
  const outcome = settlement.outcome;
  if (!(["success", "schema_reject", "provider_error", "timeout"] as const).includes(
    outcome as BudgetSettlement["outcome"],
  )) {
    throw new PersistedBudgetStateError("settlement_outcome_invalid");
  }
  const estimated = settlement.estimated_cost_usd;
  const actual = settlement.actual_cost_usd;
  const billed = settlement.billed_cost_usd;
  if (
    typeof estimated !== "number" ||
    !Number.isFinite(estimated) ||
    estimated < 0 ||
    (actual !== null &&
      (typeof actual !== "number" || !Number.isFinite(actual) || actual < 0)) ||
    typeof billed !== "number" ||
    !Number.isFinite(billed) ||
    billed < 0
  ) {
    throw new PersistedBudgetStateError("settlement_cost_invalid");
  }
  const input = requireNullableUsageToken(
    settlement.actual_input_tokens,
    "settlement_input_tokens",
  );
  const output = requireNullableUsageToken(
    settlement.actual_output_tokens,
    "settlement_output_tokens",
  );
  const cached = requireNullableUsageToken(
    settlement.actual_cached_tokens,
    "settlement_cached_tokens",
  );
  const source = settlement.usage_source;
  const hasAttribution = ["provider_model", "pricing_policy_id", "pricing_policy_digest"].every(
    (key) => Object.prototype.hasOwnProperty.call(settlement, key),
  );
  if (source === "provider" && !hasAttribution) {
    if (
      actualAmounts === null ||
      usdMicros(billed) !== usdMicros(actualAmounts.cost_usd)
    ) {
      throw new PersistedBudgetStateError("settlement_legacy_counter_binding_invalid");
    }
    return {
      outcome: outcome as BudgetSettlement["outcome"],
      usage_source: "legacy_unattributed",
      estimated_cost_usd: estimated,
      actual_cost_usd: null,
      billed_cost_usd: billed,
      actual_input_tokens: input,
      actual_output_tokens: output,
      actual_cached_tokens: cached,
      provider_model: null,
      pricing_policy_id: null,
      pricing_policy_digest: null,
    };
  }
  const providerModel = settlement.provider_model;
  const pricingPolicyId = settlement.pricing_policy_id;
  const pricingPolicyDigest = settlement.pricing_policy_digest;
  if (source === "provider" || source === "provider_tokens_estimated_cost") {
    if (
      typeof providerModel !== "string" ||
      !providerModel ||
      providerModel.length > 256 ||
      input === null ||
      output === null ||
      cached === null
    ) {
      throw new PersistedBudgetStateError("settlement_usage_attribution_invalid");
    }
    if (
      actualAmounts === null ||
      input !== actualAmounts.input_tokens ||
      output !== actualAmounts.output_tokens ||
      cached !== actualAmounts.cached_tokens ||
      usdMicros(billed) !== usdMicros(actualAmounts.cost_usd) ||
      usdMicros(estimated) !==
        usdMicros(
          estimateCostUsd(
            providerModel,
            reservedAmounts.input_tokens,
            reservedAmounts.output_tokens,
          ),
        )
    ) {
      throw new PersistedBudgetStateError("settlement_counter_binding_invalid");
    }
    if (source === "provider") {
      if (actual === null || pricingPolicyId !== null || pricingPolicyDigest !== null) {
        throw new PersistedBudgetStateError("settlement_provider_cost_invalid");
      }
    } else if (
      actual !== null ||
      pricingPolicyId !== AI_GATEWAY_PRICING_POLICY_ID ||
      pricingPolicyDigest !== AI_GATEWAY_PRICING_POLICY_DIGEST ||
      usdMicros(billed) !== usdMicros(estimateCostUsd(providerModel, input, output))
    ) {
      throw new PersistedBudgetStateError("settlement_pricing_policy_invalid");
    }
  } else if (source === "reserved_max_uncertain") {
    if (
      actual !== null ||
      input !== null ||
      output !== null ||
      cached !== null ||
      (hasAttribution &&
        (providerModel !== null || pricingPolicyId !== null || pricingPolicyDigest !== null))
    ) {
      throw new PersistedBudgetStateError("settlement_uncertain_usage_invalid");
    }
    if (
      actualAmounts === null ||
      !persistedCountersEqual(actualAmounts, reservedAmounts) ||
      usdMicros(estimated) !== usdMicros(reservedAmounts.cost_usd) ||
      usdMicros(billed) !== usdMicros(reservedAmounts.cost_usd)
    ) {
      throw new PersistedBudgetStateError("settlement_uncertain_counter_binding_invalid");
    }
  } else if (source === "legacy_unattributed") {
    if (
      actual !== null ||
      actualAmounts === null ||
      usdMicros(billed) !== usdMicros(actualAmounts.cost_usd) ||
      (hasAttribution &&
        (providerModel !== null || pricingPolicyId !== null || pricingPolicyDigest !== null))
    ) {
      throw new PersistedBudgetStateError("settlement_legacy_attribution_invalid");
    }
  } else {
    throw new PersistedBudgetStateError("settlement_usage_source_invalid");
  }
  return {
    outcome: outcome as BudgetSettlement["outcome"],
    usage_source: source,
    estimated_cost_usd: estimated,
    actual_cost_usd: actual as number | null,
    billed_cost_usd: billed,
    actual_input_tokens: input,
    actual_output_tokens: output,
    actual_cached_tokens: cached,
    provider_model: typeof providerModel === "string" ? providerModel : null,
    pricing_policy_id: typeof pricingPolicyId === "string" ? pricingPolicyId : null,
    pricing_policy_digest: typeof pricingPolicyDigest === "string" ? pricingPolicyDigest : null,
  };
}

function coerceReservation(raw: Reservation): Reservation {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new PersistedBudgetStateError("reservation_not_object");
  }
  const boundedKey = requireIdempotencyKey(raw.idempotency_key);
  const boundedDigest =
    raw.request_digest === null || raw.request_digest === undefined
      ? null
      : requireNonemptyRequestDigest(raw.request_digest);
  if (
    !boundedKey.ok ||
    boundedKey.idempotency_key !== raw.idempotency_key ||
    (boundedDigest !== null &&
      (!boundedDigest.ok || boundedDigest.request_digest !== raw.request_digest)) ||
    typeof raw.reservation_id !== "string" ||
    !raw.reservation_id ||
    !(["reserved", "reconciled", "released"] as const).includes(raw.status) ||
    (raw.lease_id !== null && (typeof raw.lease_id !== "string" || !raw.lease_id)) ||
    !Number.isFinite(raw.created_at) ||
    (raw.reconciled_at !== null && !Number.isFinite(raw.reconciled_at)) ||
    (raw.released_at !== null && !Number.isFinite(raw.released_at))
  ) {
    throw new PersistedBudgetStateError("reservation_identity_invalid");
  }
  const amounts = requirePersistedCounters(raw.amounts, "reservation.amounts");
  const actual =
    raw.actual === null
      ? null
      : requirePersistedCounters(raw.actual, "reservation.actual");
  const ownerHash = raw.reserve_owner_capability_hash ?? null;
  if (ownerHash !== null && !OWNER_CAPABILITY_RE.test(ownerHash)) {
    throw new PersistedBudgetStateError("reservation_owner_capability_hash_invalid");
  }
  return {
    ...raw,
    amounts,
    actual,
    request_digest: raw.request_digest ?? null,
    cached_result: raw.cached_result ?? null,
    finalize_error: raw.finalize_error ?? null,
    settlement: requirePersistedSettlement(raw.settlement, amounts, actual),
    provider_started_at: raw.provider_started_at ?? null,
    uncertainty_reason: raw.uncertainty_reason ?? null,
    reserve_owner_capability_hash: ownerHash,
    settlement_capability_hash: raw.settlement_capability_hash ?? null,
    settlement_capability_consumed: raw.settlement_capability_consumed === true,
    settlement_capability_secret:
      typeof raw.settlement_capability_secret === "string" && raw.settlement_capability_secret
        ? raw.settlement_capability_secret
        : null,
  };
}

function requirePersistedLease(raw: unknown, key: string): Lease {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new PersistedBudgetStateError("lease_not_object");
  }
  const lease = raw as Lease;
  if (
    lease.lease_id !== key ||
    (lease.reservation_key !== null &&
      (typeof lease.reservation_key !== "string" || !lease.reservation_key)) ||
    !Number.isFinite(lease.acquired_at) ||
    !Number.isFinite(lease.expires_at) ||
    !Number.isFinite(lease.last_heartbeat_at) ||
    lease.expires_at < lease.acquired_at ||
    lease.last_heartbeat_at < lease.acquired_at ||
    lease.last_heartbeat_at > lease.expires_at ||
    (lease.released_at !== null &&
      (!Number.isFinite(lease.released_at) || lease.released_at < lease.acquired_at))
  ) {
    throw new PersistedBudgetStateError("lease_identity_invalid");
  }
  return { ...lease };
}

function requirePersistedOwnerCancellationTombstone(
  raw: unknown,
  key: string,
): OwnerCancellationTombstone {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new PersistedBudgetStateError("owner_cancellation_tombstone_not_object");
  }
  const tombstone = raw as OwnerCancellationTombstone;
  const boundedKey = requireIdempotencyKey(tombstone.idempotency_key);
  const boundedDigest = requireNonemptyRequestDigest(tombstone.request_digest);
  if (
    !OWNER_CAPABILITY_RE.test(key) ||
    tombstone.owner_capability_hash !== key ||
    !boundedKey.ok ||
    boundedKey.idempotency_key !== tombstone.idempotency_key ||
    !boundedDigest.ok ||
    boundedDigest.request_digest !== tombstone.request_digest ||
    !Number.isSafeInteger(tombstone.created_at) ||
    !Number.isSafeInteger(tombstone.expires_at) ||
    tombstone.expires_at !==
      tombstone.created_at + OWNER_CANCELLATION_TOMBSTONE_TTL_MS
  ) {
    throw new PersistedBudgetStateError("owner_cancellation_tombstone_invalid");
  }
  return { ...tombstone };
}

function persistedCountersEqual(left: Counters, right: Counters): boolean {
  return COUNTERS.every((name) =>
    name === "cost_usd"
      ? usdMicros(left[name]) === usdMicros(right[name])
      : left[name] === right[name],
  );
}

function requirePersistedOccupancyClosure(state: LedgerState): void {
  let derivedUsed = zeroCounters();
  let derivedReserved = zeroCounters();
  for (const [key, reservation] of Object.entries(state.reservations)) {
    const lease = reservation.lease_id ? state.leases[reservation.lease_id] : undefined;
    if (!lease || lease.reservation_key !== key) {
      throw new PersistedBudgetStateError("reservation_lease_link_invalid");
    }
    if (reservation.status === "reserved") {
      if (
        reservation.actual !== null ||
        reservation.settlement !== null ||
        reservation.reconciled_at !== null ||
        reservation.released_at !== null ||
        lease.released_at !== null
      ) {
        throw new PersistedBudgetStateError("reserved_lifecycle_invalid");
      }
      derivedReserved = applyDelta(derivedReserved, reservation.amounts, 1);
      continue;
    }
    if (lease.released_at === null) {
      throw new PersistedBudgetStateError("terminal_lease_still_active");
    }
    if (reservation.status === "reconciled") {
      if (
        reservation.actual === null ||
        reservation.settlement === null ||
        reservation.reconciled_at === null
      ) {
        throw new PersistedBudgetStateError("reconciled_lifecycle_invalid");
      }
      derivedUsed = applyDelta(derivedUsed, reservation.actual, 1);
      continue;
    }
    if (
      reservation.actual !== null ||
      reservation.settlement !== null ||
      reservation.reconciled_at !== null ||
      reservation.released_at === null ||
      reservation.provider_started_at !== null
    ) {
      throw new PersistedBudgetStateError("released_lifecycle_invalid");
    }
  }
  if (
    !persistedCountersEqual(state.used, derivedUsed) ||
    !persistedCountersEqual(state.reserved, derivedReserved)
  ) {
    throw new PersistedBudgetStateError("ledger_occupancy_not_reconciled");
  }
}

function coerceState(state: LedgerState): LedgerState {
  if (state === null || typeof state !== "object" || Array.isArray(state)) {
    throw new PersistedBudgetStateError("ledger_not_object");
  }
  if (typeof state.created !== "boolean" || !Number.isFinite(state.created_at)) {
    throw new PersistedBudgetStateError("ledger_creation_identity_invalid");
  }
  state.caps = { ...PILOT_BUDGET_CAPS };
  state.used = requirePersistedCounters(state.used, "ledger.used");
  state.reserved = requirePersistedCounters(state.reserved, "ledger.reserved");
  if (typeof state.frozen !== "boolean") {
    throw new PersistedBudgetStateError("ledger_frozen_flag_invalid");
  }
  state.frozen_at = state.frozen_at ?? null;
  state.frozen_reason = state.frozen_reason ?? null;
  if (!Array.isArray(state.audit)) {
    throw new PersistedBudgetStateError("ledger_audit_invalid");
  }
  if (
    state.reservations === null ||
    typeof state.reservations !== "object" ||
    Array.isArray(state.reservations)
  ) {
    throw new PersistedBudgetStateError("ledger_reservations_invalid");
  }
  if (
    state.leases === null ||
    typeof state.leases !== "object" ||
    Array.isArray(state.leases)
  ) {
    throw new PersistedBudgetStateError("ledger_leases_invalid");
  }
  const reservations: Record<string, Reservation> = {};
  for (const [k, v] of Object.entries(state.reservations)) {
    const reservation = coerceReservation(v);
    if (reservation.idempotency_key !== k) {
      throw new PersistedBudgetStateError("reservation_key_mismatch");
    }
    reservations[k] = reservation;
  }
  state.reservations = reservations;
  const leases: Record<string, Lease> = {};
  for (const [k, v] of Object.entries(state.leases)) {
    leases[k] = requirePersistedLease(v, k);
  }
  state.leases = leases;
  const rawTombstones = state.owner_cancellation_tombstones ?? {};
  if (
    rawTombstones === null ||
    typeof rawTombstones !== "object" ||
    Array.isArray(rawTombstones)
  ) {
    throw new PersistedBudgetStateError("owner_cancellation_tombstones_invalid");
  }
  const tombstoneEntries = Object.entries(rawTombstones);
  if (tombstoneEntries.length > MAX_OWNER_CANCELLATION_TOMBSTONES) {
    throw new PersistedBudgetStateError("owner_cancellation_tombstones_over_capacity");
  }
  const tombstones: Record<string, OwnerCancellationTombstone> = {};
  for (const [key, value] of tombstoneEntries) {
    tombstones[key] = requirePersistedOwnerCancellationTombstone(value, key);
  }
  state.owner_cancellation_tombstones = tombstones;
  const quarantineUntil = state.owner_cancellation_quarantine_until ?? null;
  if (
    quarantineUntil !== null &&
    (!Number.isSafeInteger(quarantineUntil) || quarantineUntil < 0)
  ) {
    throw new PersistedBudgetStateError(
      "owner_cancellation_quarantine_until_invalid",
    );
  }
  state.owner_cancellation_quarantine_until = quarantineUntil;
  requirePersistedOccupancyClosure(state);
  return state;
}

function cleanupOwnerCancellationTombstones(state: LedgerState, now: number): number {
  let removed = 0;
  for (const [ownerHash, tombstone] of Object.entries(
    state.owner_cancellation_tombstones,
  )) {
    if (tombstone.expires_at > now) continue;
    delete state.owner_cancellation_tombstones[ownerHash];
    removed += 1;
  }
  return removed;
}

function cleanupOwnerCancellationQuarantine(
  state: LedgerState,
  now: number,
): boolean {
  const quarantineUntil = state.owner_cancellation_quarantine_until;
  if (quarantineUntil === null || quarantineUntil > now) return false;
  state.owner_cancellation_quarantine_until = null;
  return true;
}

function ownerCancellationTombstoneMatches(
  state: LedgerState,
  ownerHash: string | null,
  idempotencyKey: string,
  requestDigest: string,
): boolean {
  if (!ownerHash) return false;
  const tombstone = state.owner_cancellation_tombstones[ownerHash];
  return Boolean(
    tombstone &&
      tombstone.idempotency_key === idempotencyKey &&
      tombstone.request_digest === requestDigest,
  );
}

async function persistOwnerCancellationQuarantine(
  storage: AtomicBudgetStorage,
  state: LedgerState,
  now: number,
): Promise<BudgetErr> {
  state.owner_cancellation_quarantine_until = Math.max(
    state.owner_cancellation_quarantine_until ?? 0,
    now + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
  );
  // Await the state write inside the same storage transaction before returning
  // the saturation error. A delayed reserve therefore cannot be admitted
  // between learning that its owner tombstone was lost and quarantine commit.
  await saveState(storage, state);
  return { ok: false, error: "owner_cancellation_tombstone_capacity_exhausted" };
}

async function persistOwnerCancellationTombstone(
  storage: AtomicBudgetStorage,
  state: LedgerState,
  ownerHash: string,
  idempotencyKey: string,
  requestDigest: string,
  now: number,
): Promise<BudgetErr | null> {
  const existing = state.owner_cancellation_tombstones[ownerHash];
  if (existing) {
    if (
      existing.idempotency_key !== idempotencyKey ||
      existing.request_digest !== requestDigest
    ) {
      return { ok: false, error: "owner_cancellation_tombstone_conflict" };
    }
    return null;
  }
  if (
    Object.keys(state.owner_cancellation_tombstones).length >=
    MAX_OWNER_CANCELLATION_TOMBSTONES
  ) {
    // The exact owner cannot be recorded without exceeding the bounded map.
    return persistOwnerCancellationQuarantine(storage, state, now);
  }
  state.owner_cancellation_tombstones[ownerHash] = {
    owner_capability_hash: ownerHash,
    idempotency_key: idempotencyKey,
    request_digest: requestDigest,
    created_at: now,
    expires_at: now + OWNER_CANCELLATION_TOMBSTONE_TTL_MS,
  };
  if (serializedLedgerStateBytes(state) > MAX_MUTABLE_LEDGER_STATE_BYTES) {
    // Whole-state history may consume the transitional mutable budget before
    // the tombstone-count cap. Remove the uncommitted tombstone and spend only
    // the reserved headroom on a fail-closed global quarantine.
    delete state.owner_cancellation_tombstones[ownerHash];
    return persistOwnerCancellationQuarantine(storage, state, now);
  }
  return null;
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
    provider_model: null,
    pricing_policy_id: null,
    pricing_policy_digest: null,
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
  cleanupOwnerCancellationTombstones(state, now);
  cleanupOwnerCancellationQuarantine(state, now);
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

async function loadState(storage: AtomicBudgetStorage, now: number): Promise<LedgerState> {
  const existing = await storage.get<LedgerState>(STATE_KEY);
  if (existing === undefined) return emptyLedger(now);
  const state = coerceState(existing);
  // Legacy whole-state values inside the absolute safety ceiling remain
  // readable so a cancellation can transition them into quarantine. The
  // mutable/headroom threshold is enforced only before a new write.
  requireLedgerStateWithinAbsoluteValueLimit(state);
  return state;
}

async function saveState(storage: AtomicBudgetStorage, state: LedgerState): Promise<void> {
  // This preflight is the enforcement point for every whole-value write,
  // including the Durable Object adapter's transaction.put below this layer.
  requireLedgerStateWithinCommitLimit(state);
  let nextAlarm: number | null = null;
  for (const lease of Object.values(state.leases)) {
    if (lease.released_at !== null) continue;
    nextAlarm = nextAlarm === null ? lease.expires_at : Math.min(nextAlarm, lease.expires_at);
  }
  for (const tombstone of Object.values(state.owner_cancellation_tombstones)) {
    nextAlarm =
      nextAlarm === null
        ? tombstone.expires_at
        : Math.min(nextAlarm, tombstone.expires_at);
  }
  if (state.owner_cancellation_quarantine_until !== null) {
    nextAlarm =
      nextAlarm === null
        ? state.owner_cancellation_quarantine_until
        : Math.min(nextAlarm, state.owner_cancellation_quarantine_until);
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
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const created = ensureCreated(state, now);
    await saveState(transaction, state);
    return { ok: true, created, caps: state.caps };
  });
}

export async function reserveBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    amounts: unknown;
    acquire_lease?: boolean;
    request_digest?: string;
    /** Gateway-internal. Omitted only by legacy/internal callers. */
    reserve_owner_capability?: string;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: PublicReservation;
    lease: Lease | null;
    existing: boolean;
    owner_recovered: boolean;
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
  let ownerHash: string | null = null;
  if (input.reserve_owner_capability !== undefined) {
    const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
    if (!owner.ok) return owner;
    ownerHash = await hashReserveOwnerCapability(
      owner.reserve_owner_capability,
      key.idempotency_key,
      digest,
    );
  }
  const leaseId = crypto.randomUUID();
  const reservationId = crypto.randomUUID();

  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    ensureCreated(state, now);

    // Production reserve always takes the canonical 1800s lease, including
    // replay of an active or terminal idempotency key. Missing/false must not
    // return a cached reservation, capability, or occupancy mutation.
    if (input.acquire_lease !== true) {
      await saveState(transaction, state);
      return { ok: false, error: "lease_required" };
    }

    if (
      ownerCancellationTombstoneMatches(
        state,
        ownerHash,
        key.idempotency_key,
        digest,
      )
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_released" };
    }

    const existing = state.reservations[key.idempotency_key];
    if (existing) {
      if (existing.request_digest !== digest) {
        await saveState(transaction, state);
        return { ok: false, error: "idempotency_digest_conflict" };
      }
      if (existing.status === "reconciled") {
        const lease = existing.lease_id ? state.leases[existing.lease_id] ?? null : null;
        await saveState(transaction, state);
        return {
          ok: true,
          reservation: publicReservation(existing),
          lease,
          existing: true,
          owner_recovered: reserveOwnerMatches(existing, ownerHash),
          budget_run_id: existing.reservation_id,
        };
      }
      if (existing.status === "reserved") {
        // Unlike a terminal replay, returning an active owner recovery can let
        // a provider start. Quarantine it exactly like fresh occupancy.
        if (state.owner_cancellation_quarantine_until !== null) {
          await saveState(transaction, state);
          return {
            ok: false,
            error: "budget_frozen",
            detail: "owner_cancellation_tombstone_capacity_exhausted",
          };
        }
        const ownerRecovered = reserveOwnerMatches(existing, ownerHash);
        if (
          existing.reserve_owner_capability_hash !== null &&
          !ownerRecovered
        ) {
          await saveState(transaction, state);
          return { ok: false, error: "reservation_owned_by_other_invocation" };
        }
        const lease = existing.lease_id ? state.leases[existing.lease_id] ?? null : null;
        await saveState(transaction, state);
        return {
          ok: true,
          reservation: publicReservation(existing),
          lease,
          existing: true,
          owner_recovered: ownerRecovered,
          budget_run_id: existing.reservation_id,
        };
      }
      // Cancellation is a durable tombstone for the invocation that owned the
      // reservation. A delayed reserve response/retry from that same invocation
      // must not resurrect occupancy. A different, freshly minted owner may
      // intentionally begin a new run for the same client idempotency key.
      if (existing.reserve_owner_capability_hash !== null) {
        if (ownerHash === null) {
          await saveState(transaction, state);
          return { ok: false, error: "reserve_owner_capability_invalid" };
        }
        if (reserveOwnerMatches(existing, ownerHash)) {
          await saveState(transaction, state);
          return { ok: false, error: "reservation_released" };
        }
      }
      // Legacy unowned released reservations retain their historical replay
      // behavior. Provider-started work is never represented by released.
    }

    // Capacity saturation means one cancelled owner could not be represented
    // in the bounded tombstone map. Terminal/released replay above is safe, but
    // fresh occupancy must wait for the canonical delay window to close.
    if (state.owner_cancellation_quarantine_until !== null) {
      await saveState(transaction, state);
      return {
        ok: false,
        error: "budget_frozen",
        detail: "owner_cancellation_tombstone_capacity_exhausted",
      };
    }

    // A frozen ledger still serves terminal idempotent results above, but never
    // authorizes a new provider side effect.
    if (state.frozen) {
      await saveState(transaction, state);
      return {
        ok: false,
        error: "budget_frozen",
        detail: state.frozen_reason || "actual_exceeds_reserved",
      };
    }

    const over = insufficient(state, amounts);
    if (over) {
      await saveState(transaction, state);
      return {
        ok: false,
        error: "budget_exhausted",
        detail: `${over.name}: used=${over.used} reserved=${over.reserved} delta=${over.delta} limit=${over.limit}`,
      };
    }

    const active = activeLeaseCount(state);
    if (active >= PILOT_BUDGET_CAPS.max_parallel_experiments) {
      await saveState(transaction, state);
      return {
        ok: false,
        error: "budget_exhausted",
        detail: `concurrent_experiments: active=${active} limit=${PILOT_BUDGET_CAPS.max_parallel_experiments}`,
      };
    }
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
      reservation_id: reservationId,
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
      reserve_owner_capability_hash: ownerHash,
      settlement_capability_hash: null,
      settlement_capability_consumed: false,
      settlement_capability_secret: null,
    };
    state.reserved = applyDelta(state.reserved, reservation.amounts, 1);
    state.reservations[key.idempotency_key] = reservation;
    await saveState(transaction, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      lease,
      existing: false,
      owner_recovered: false,
      budget_run_id: reservation.reservation_id,
    };
  });
}

/**
 * Production Gateway reserve surface. The lower-level reserveBudget function
 * remains available only for legacy HTTP recovery and algebra migration tests;
 * a Gateway service-binding call cannot create an unowned reservation.
 */
export async function reserveOwnedBudget(
  storage: BudgetStorage,
  input: Parameters<typeof reserveBudget>[1] & {
    reserve_owner_capability: string;
  },
  now = Date.now(),
): ReturnType<typeof reserveBudget> {
  if (!input || typeof input !== "object") {
    return { ok: false, error: "reserve_owner_capability invalid" };
  }
  const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
  if (!owner.ok) return owner;
  return reserveBudget(storage, input, now);
}

/** Lookup only. Never creates occupancy or a lease. */
export async function queryOwnedBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    request_digest: string;
    reserve_owner_capability: string;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{
    reservation: PublicReservation;
    lease: Lease | null;
    existing: true;
    owner_recovered: boolean;
    budget_run_id: string;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const boundDigest = requireNonemptyRequestDigest(input.request_digest);
  if (!boundDigest.ok) return boundDigest;
  const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
  if (!owner.ok) return owner;
  const ownerHash = await hashReserveOwnerCapability(
    owner.reserve_owner_capability,
    key.idempotency_key,
    boundDigest.request_digest,
  );
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const existing = state.reservations[key.idempotency_key];
    if (!existing) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_found" };
    }
    if (existing.request_digest !== boundDigest.request_digest) {
      await saveState(transaction, state);
      return { ok: false, error: "request_digest_mismatch" };
    }
    if (
      existing.reserve_owner_capability_hash !== null &&
      !reserveOwnerMatches(existing, ownerHash)
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_owned_by_other_invocation" };
    }
    const lease = existing.lease_id ? state.leases[existing.lease_id] ?? null : null;
    await saveState(transaction, state);
    return {
      ok: true,
      reservation: publicReservation(existing),
      lease,
      existing: true,
      owner_recovered: reserveOwnerMatches(existing, ownerHash),
      budget_run_id: existing.reservation_id,
    };
  });
}

const FORBIDDEN_CAPABILITY_KEYS = new Set<SensitiveCapabilityField>([
  "owner_capability_hash",
  "reserve_owner_capability",
  "reserve_owner_capability_hash",
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
  "monetary_cost_source",
  "pricing_policy_id",
  "pricing_policy_digest",
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
  ...submittedCapabilities: unknown[]
): Set<string> {
  const material = new Set<string>();
  if (reservation.reserve_owner_capability_hash) {
    material.add(reservation.reserve_owner_capability_hash);
  }
  if (reservation.settlement_capability_hash) {
    material.add(reservation.settlement_capability_hash);
  }
  if (reservation.settlement_capability_secret) {
    material.add(reservation.settlement_capability_secret);
  }
  for (const submittedCapability of submittedCapabilities) {
    const submitted =
      typeof submittedCapability === "string" ? submittedCapability.trim() : "";
    if (submitted) material.add(submitted);
  }
  return material;
}

function capabilityMaterialTokens(material: Set<string>): string[] {
  return [...material].filter((token) => token.length > 0);
}

function textContainsCapabilityMaterial(text: string, tokens: string[]): boolean {
  for (const token of tokens) {
    if (text.includes(token)) return true;
  }
  return false;
}

const MAX_CACHED_RESULT_BYTES = 64 * 1024;
const MAX_CACHED_RESULT_DEPTH = 32;
const MAX_CACHED_RESULT_NODES = 4_096;

type JsonCloneContext = {
  readonly capabilityTokens: string[];
  readonly ancestors: Set<object>;
  nodes: number;
};

/**
 * Copy only bounded JSON data. This deliberately rejects cycles, accessors,
 * exotic prototypes, non-finite numbers, and structured-clone-only values so
 * a terminal response can never throw while being persisted or replayed.
 */
function cloneBoundedPublicJson(
  value: unknown,
  context: JsonCloneContext,
  depth = 0,
): BudgetResult<{ value: unknown }> {
  context.nodes += 1;
  if (context.nodes > MAX_CACHED_RESULT_NODES || depth > MAX_CACHED_RESULT_DEPTH) {
    return { ok: false, error: "cached_result_invalid" };
  }
  if (value === null || typeof value === "boolean") {
    return { ok: true, value };
  }
  if (typeof value === "number") {
    return Number.isFinite(value)
      ? { ok: true, value }
      : { ok: false, error: "cached_result_invalid" };
  }
  if (typeof value === "string") {
    return textContainsCapabilityMaterial(value, context.capabilityTokens)
      ? { ok: false, error: "cached_result_capability_material" }
      : { ok: true, value };
  }
  if (typeof value !== "object") {
    return { ok: false, error: "cached_result_invalid" };
  }
  if (context.ancestors.has(value)) {
    return { ok: false, error: "cached_result_invalid" };
  }

  context.ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      const out: unknown[] = [];
      for (const item of value) {
        const nested = cloneBoundedPublicJson(item, context, depth + 1);
        if (!nested.ok) return nested;
        out.push(nested.value);
      }
      return { ok: true, value: out };
    }

    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      return { ok: false, error: "cached_result_invalid" };
    }
    const ownKeys = Reflect.ownKeys(value);
    if (ownKeys.some((key) => typeof key !== "string")) {
      return { ok: false, error: "cached_result_invalid" };
    }
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const out: Record<string, unknown> = {};
    for (const key of ownKeys as string[]) {
      const descriptor = descriptors[key];
      if (!descriptor?.enumerable) continue;
      if (!("value" in descriptor)) {
        return { ok: false, error: "cached_result_invalid" };
      }
      if (FORBIDDEN_CAPABILITY_KEYS.has(key as SensitiveCapabilityField)) {
        return { ok: false, error: "cached_result_capability_field" };
      }
      if (textContainsCapabilityMaterial(key, context.capabilityTokens)) {
        return { ok: false, error: "cached_result_capability_material" };
      }
      const nested = cloneBoundedPublicJson(descriptor.value, context, depth + 1);
      if (!nested.ok) return nested;
      out[key] = nested.value;
    }
    return { ok: true, value: out };
  } catch {
    return { ok: false, error: "cached_result_invalid" };
  } finally {
    context.ancestors.delete(value);
  }
}

function boundedPublicJson(
  value: unknown,
  material: Set<string>,
): BudgetResult<{ value: unknown }> {
  const cloned = cloneBoundedPublicJson(value, {
    capabilityTokens: capabilityMaterialTokens(material),
    ancestors: new Set<object>(),
    nodes: 0,
  });
  if (!cloned.ok) return cloned;
  try {
    const encoded = JSON.stringify(cloned.value);
    if (
      typeof encoded !== "string" ||
      new TextEncoder().encode(encoded).byteLength > MAX_CACHED_RESULT_BYTES
    ) {
      return { ok: false, error: "cached_result_invalid" };
    }
  } catch {
    return { ok: false, error: "cached_result_invalid" };
  }
  return cloned;
}

function canonicalizeCachedResult(
  result: CachedBudgetResult | undefined,
  material: Set<string>,
): BudgetResult<{ value: CachedBudgetResult | undefined }> {
  if (result === undefined) return { ok: true, value: undefined };
  const clonedEnvelope = boundedPublicJson(result, material);
  if (!clonedEnvelope.ok) return clonedEnvelope;
  if (
    !clonedEnvelope.value ||
    typeof clonedEnvelope.value !== "object" ||
    Array.isArray(clonedEnvelope.value)
  ) {
    return { ok: false, error: "cached_result_invalid" };
  }
  const envelope = clonedEnvelope.value as Record<string, unknown>;
  const envelopeKeys = Object.keys(envelope);
  if (
    envelopeKeys.length !== 2 ||
    !Object.prototype.hasOwnProperty.call(envelope, "http_status") ||
    !Object.prototype.hasOwnProperty.call(envelope, "body")
  ) {
    return { ok: false, error: "cached_result_invalid" };
  }
  const status = envelope.http_status;
  if (typeof status !== "number" || !Number.isInteger(status) || status < 200 || status > 599) {
    return { ok: false, error: "cached_result_invalid" };
  }
  const body = envelope.body;
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
  return {
    ok: true,
    value: { http_status: status, body: rec },
  };
}

function publicCachedResult(
  cached: CachedBudgetResult | null,
  material: Set<string>,
): CachedBudgetResult | null {
  if (!cached) return null;
  const body = boundedPublicJson(cached.body, material);
  if (!body.ok) return null;
  return {
    http_status: cached.http_status,
    body: body.value,
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
  const digest = raw.trim();
  if (!REQUEST_DIGEST_RE.test(digest)) {
    return { ok: false, error: "request_digest must be lowercase sha256 hex" };
  }
  return { ok: true, request_digest: digest };
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
  input: {
    idempotency_key: string;
    lease_id: string;
    request_digest?: string;
    reserve_owner_capability?: string;
  },
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
  let ownerHash: string | null = null;
  if (input.reserve_owner_capability !== undefined) {
    const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
    if (!owner.ok) return owner;
    ownerHash = await hashReserveOwnerCapability(
      owner.reserve_owner_capability,
      key.idempotency_key,
      digest,
    );
  }

  // Randomness and WebCrypto happen before the transaction. The transaction
  // re-reads and validates the latest state, so concurrent calls can persist
  // only one capability and exact retries recover that same secret.
  const initialState = await loadState(storage, now);
  const initialReservation = initialState.reservations[key.idempotency_key];
  const candidateCapability = initialReservation?.provider_started_at === null
    ? mintSettlementCapabilitySecret()
    : null;
  const candidateHash = candidateCapability && initialReservation
    ? await hashSettlementCapability(candidateCapability, initialReservation)
    : null;

  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const reservation = state.reservations[key.idempotency_key];
    if (!reservation) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_found" };
    }
    if (reservation.status !== "reserved") {
      await saveState(transaction, state);
      return { ok: false, error: `reservation_${reservation.status}` };
    }
    if (state.frozen && reservation.provider_started_at === null) {
      await saveState(transaction, state);
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
      await saveState(transaction, state);
      return bound;
    }
    if (
      reservation.reserve_owner_capability_hash !== null &&
      !reserveOwnerMatches(reservation, ownerHash)
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "reserve_owner_capability_invalid" };
    }
    const lease = state.leases[leaseId];
    if (
      reservation.lease_id !== leaseId ||
      !lease ||
      lease.reservation_key !== key.idempotency_key ||
      lease.released_at !== null
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "lease_not_active" };
    }
    if (reservation.provider_started_at !== null) {
      const replayed =
        !reservation.settlement_capability_consumed && reservation.settlement_capability_secret
          ? reservation.settlement_capability_secret
          : null;
      await saveState(transaction, state);
      return {
        ok: true,
        reservation: publicReservation(reservation),
        budget_run_id: reservation.reservation_id,
        settlement_capability: replayed,
      };
    }
    if (
      !candidateCapability ||
      !candidateHash ||
      initialReservation?.reservation_id !== reservation.reservation_id
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_changed_retry" };
    }
    reservation.provider_started_at = now;
    reservation.settlement_capability_hash = candidateHash;
    reservation.settlement_capability_consumed = false;
    reservation.settlement_capability_secret = candidateCapability;
    await saveState(transaction, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      budget_run_id: reservation.reservation_id,
      settlement_capability: candidateCapability,
    };
  });
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
function verifySettlementAuthority(
  reservation: Reservation,
  input: {
    settlement_capability?: string;
    request_digest?: string;
    lease_id?: string;
  },
  submittedCapabilityHash: string | null,
): BudgetErr | null {
  const bound = requireExactLeaseAndDigest(input, reservation);
  if (bound) return bound;
  const capability =
    typeof input.settlement_capability === "string"
      ? input.settlement_capability.trim()
      : "";
  if (!capability || !reservation.settlement_capability_hash) {
    return { ok: false, error: "settlement_capability_required" };
  }
  if (!submittedCapabilityHash || submittedCapabilityHash !== reservation.settlement_capability_hash) {
    return { ok: false, error: "settlement_capability_invalid" };
  }
  return null;
}

async function prepareSettlementCapabilityHash(
  storage: BudgetStorage,
  idempotencyKey: string,
  capability: unknown,
  now: number,
): Promise<string | null> {
  const submitted = typeof capability === "string" ? capability.trim() : "";
  if (!submitted) return null;
  const state = await loadState(storage, now);
  const reservation = state.reservations[idempotencyKey];
  return reservation ? hashSettlementCapability(submitted, reservation) : null;
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
    reserve_owner_capability?: string;
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

  const submittedCapabilityHash = await prepareSettlementCapabilityHash(
    storage,
    key.idempotency_key,
    input.settlement_capability,
    now,
  );
  const digest =
    typeof input.request_digest === "string" ? input.request_digest.trim() : "";
  let submittedOwnerHash: string | null = null;
  if (input.reserve_owner_capability !== undefined) {
    const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
    if (!owner.ok) return owner;
    if (!digest) return { ok: false, error: "request_digest required" };
    submittedOwnerHash = await hashReserveOwnerCapability(
      owner.reserve_owner_capability,
      key.idempotency_key,
      digest,
    );
  }
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const reservation = state.reservations[key.idempotency_key];
    if (!reservation) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_found" };
    }
    if (
      reservation.reserve_owner_capability_hash !== null &&
      !reserveOwnerMatches(reservation, submittedOwnerHash)
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "reserve_owner_capability_invalid" };
    }
    if (reservation.status === "reconciled") {
      const verified = verifySettlementAuthority(
        reservation,
        input,
        submittedCapabilityHash,
      );
      if (verified) {
        await saveState(transaction, state);
        return verified;
      }
      reservation.settlement_capability_secret = null;
      await saveState(transaction, state);
      return {
        ok: true,
        reservation: publicReservation(reservation),
        used: amountsFromCounters(state.used),
        frozen: state.frozen,
        budget_run_id: reservation.reservation_id,
      };
    }
    if (reservation.status === "released") {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_released" };
    }
    if (reservation.provider_started_at === null) {
      await saveState(transaction, state);
      return { ok: false, error: "provider_not_started" };
    }
    const verified = verifySettlementAuthority(
      reservation,
      input,
      submittedCapabilityHash,
    );
    if (verified) {
      await saveState(transaction, state);
      return verified;
    }
    if (reservation.settlement_capability_consumed) {
      await saveState(transaction, state);
      return { ok: false, error: "settlement_capability_consumed" };
    }
    consumeVerifiedCapability(reservation);
    chargeUncertainReservation(state, reservation, input.reason, now);
    await saveState(transaction, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      used: amountsFromCounters(state.used),
      frozen: true,
      budget_run_id: reservation.reservation_id,
    };
  });
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
  usage: ExactUsageEvidence,
  terminalResult: CachedBudgetResult | undefined,
): BudgetSettlement {
  const httpStatus = Number(terminalResult?.http_status);
  const outcome: BudgetSettlement["outcome"] =
    httpStatus === 200 ? "success" : "schema_reject";
  return {
    outcome,
    usage_source:
      usage.cost_source === "provider" ? "provider" : "provider_tokens_estimated_cost",
    estimated_cost_usd: estimateCostUsd(
      usage.provider_model,
      reservation.amounts.input_tokens,
      reservation.amounts.output_tokens,
    ),
    actual_cost_usd: usage.cost_source === "provider" ? usage.reported_cost_usd : null,
    billed_cost_usd: usage.amounts.cost_usd,
    actual_input_tokens: usage.amounts.input_tokens,
    actual_output_tokens: usage.amounts.output_tokens,
    actual_cached_tokens: usage.amounts.cached_tokens,
    provider_model: usage.provider_model,
    pricing_policy_id: usage.pricing_policy_id,
    pricing_policy_digest: usage.pricing_policy_digest,
  };
}

export async function finalizeBudget(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    request_digest: string;
    lease_id: string;
    settlement_capability: string;
    reserve_owner_capability?: string;
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
  const parsed = parseActualUsage(input.usage);
  const submittedCapabilityHash = await prepareSettlementCapabilityHash(
    storage,
    key.idempotency_key,
    input.settlement_capability,
    now,
  );
  let submittedOwnerHash: string | null = null;
  if (input.reserve_owner_capability !== undefined) {
    const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
    if (!owner.ok) return owner;
    submittedOwnerHash = await hashReserveOwnerCapability(
      owner.reserve_owner_capability,
      key.idempotency_key,
      input.request_digest.trim(),
    );
  }

  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const reservation = state.reservations[key.idempotency_key];
    if (!reservation) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_found" };
    }
    if (
      reservation.reserve_owner_capability_hash !== null &&
      !reserveOwnerMatches(reservation, submittedOwnerHash)
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "reserve_owner_capability_invalid" };
    }
    if (reservation.status === "reconciled") {
      const verified = verifySettlementAuthority(
        reservation,
        input,
        submittedCapabilityHash,
      );
      if (verified) {
        await saveState(transaction, state);
        return verified;
      }
      reservation.settlement_capability_secret = null;
      await saveState(transaction, state);
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
      await saveState(transaction, state);
      return { ok: false, error: "reservation_released" };
    }
    if (reservation.provider_started_at === null) {
      await saveState(transaction, state);
      return { ok: false, error: "provider_not_started" };
    }
    const verified = verifySettlementAuthority(
      reservation,
      input,
      submittedCapabilityHash,
    );
    if (verified) {
      await saveState(transaction, state);
      return verified;
    }
    if (reservation.settlement_capability_consumed) {
      await saveState(transaction, state);
      return { ok: false, error: "settlement_capability_consumed" };
    }
    if (!parsed.ok) {
      consumeVerifiedCapability(reservation);
      chargeUncertainReservation(state, reservation, "usage_unavailable", now);
      await saveState(transaction, state);
      return {
        ok: false,
        error: "provider_usage_invalid",
        detail: parsed.error,
      };
    }
    const actual = parsed.amounts;
    const canonical = canonicalizeCachedResult(
      input.terminal_result,
      capabilityMaterialSet(
        reservation,
        input.settlement_capability,
        input.reserve_owner_capability,
      ),
    );
    if (!canonical.ok) {
      await saveState(transaction, state);
      return canonical;
    }
    consumeVerifiedCapability(reservation);

    const over = exceedsReserved(reservation.amounts, actual);
    state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
    // Release the estimate in full, then record billed spend exactly. If the
    // estimate was too low, freeze future work without clipping audit history.
    state.used = applyDelta(state.used, actual, 1);
    reservation.status = "reconciled";
    reservation.actual = amountsFromCounters(actual);
    reservation.settlement = deriveExactSettlement(
      reservation,
      parsed,
      canonical.value,
    );
    reservation.reconciled_at = now;
    applyCachedResult(reservation, canonical.value);
    closeReservationLease(state, reservation, now);
    if (over) {
      freezeForOverage(state, reservation, actual, now);
      reservation.finalize_error = "actual_exceeds_reserved";
      await saveState(transaction, state);
      return {
        ok: false,
        error: "actual_exceeds_reserved",
        detail: `${over.name}: actual=${over.actual} reserved=${over.reserved}`,
      };
    }
    reservation.finalize_error = null;
    await saveState(transaction, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      used: amountsFromCounters(state.used),
      frozen: false,
      budget_run_id: reservation.reservation_id,
    };
  });
}

export async function heartbeatLease(
  storage: BudgetStorage,
  leaseId: string,
  now = Date.now(),
): Promise<BudgetResult<{ lease: Lease }>> {
  if (typeof leaseId !== "string" || !leaseId.trim()) {
    return { ok: false, error: "lease_id required" };
  }
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const lease = state.leases[leaseId.trim()];
    if (!lease || lease.released_at !== null) {
      await saveState(transaction, state);
      return { ok: false, error: "lease_not_active" };
    }
    lease.last_heartbeat_at = now;
    lease.expires_at = now + PILOT_BUDGET_CAPS.lease_ttl_seconds * 1000;
    await saveState(transaction, state);
    return { ok: true, lease };
  });
}

/**
 * Cancel only a pre-provider reservation owned by this exact Gateway
 * invocation. The raw owner capability is never persisted or returned. This
 * RPC is the safe recovery path when reserve may have committed but its
 * response was lost; a duplicate client invocation has a different capability
 * and cannot release another invocation's occupancy.
 */

export async function finalizeOwnedPaperReservation(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    request_digest: string;
    reserve_owner_capability: string;
    lease_id: string;
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
  const boundDigest = requireNonemptyRequestDigest(input.request_digest);
  if (!boundDigest.ok) return boundDigest;
  const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
  if (!owner.ok) return owner;
  const ownerHash = await hashReserveOwnerCapability(
    owner.reserve_owner_capability,
    key.idempotency_key,
    boundDigest.request_digest,
  );
  const leaseId = typeof input.lease_id === "string" ? input.lease_id.trim() : "";
  if (!leaseId) return { ok: false, error: "lease_id required" };

  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const reservation = state.reservations[key.idempotency_key];
    if (!reservation) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_found" };
    }
    if (!reserveOwnerMatches(reservation, ownerHash)) {
      await saveState(transaction, state);
      return { ok: false, error: "reserve_owner_capability_invalid" };
    }
    const bound = requireExactLeaseAndDigest(
      { request_digest: boundDigest.request_digest, lease_id: leaseId },
      reservation,
    );
    if (bound) {
      await saveState(transaction, state);
      return bound;
    }
    if (reservation.provider_started_at !== null) {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_cancellable" };
    }
    if (reservation.status === "reconciled") {
      await saveState(transaction, state);
      return {
        ok: true,
        reservation: publicReservation(reservation),
        used: amountsFromCounters(state.used),
        frozen: state.frozen,
        budget_run_id: reservation.reservation_id,
      };
    }
    if (reservation.status === "released") {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_released" };
    }
    if (
      reservation.amounts.model_calls !== 0 ||
      reservation.amounts.input_tokens !== 0 ||
      reservation.amounts.output_tokens !== 0 ||
      reservation.amounts.cached_tokens !== 0 ||
      reservation.amounts.cost_usd !== 0
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "caller_settlement_rejected" };
    }
    const actual = zeroCounters();
    actual.paper_runs = reservation.amounts.paper_runs;
    actual.experiment_plans = reservation.amounts.experiment_plans;
    actual.generations = reservation.amounts.generations;
    state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
    state.used = applyDelta(state.used, actual, 1);
    reservation.status = "reconciled";
    reservation.actual = amountsFromCounters(actual);
    reservation.settlement = {
      outcome: "success",
      usage_source: "legacy_unattributed",
      estimated_cost_usd: 0,
      actual_cost_usd: 0,
      billed_cost_usd: 0,
      actual_input_tokens: 0,
      actual_output_tokens: 0,
      actual_cached_tokens: 0,
      provider_model: null,
      pricing_policy_id: null,
      pricing_policy_digest: null,
    };
    reservation.reconciled_at = now;
    reservation.finalize_error = null;
    closeReservationLease(state, reservation, now);
    await saveState(transaction, state);
    return {
      ok: true,
      reservation: publicReservation(reservation),
      used: amountsFromCounters(state.used),
      frozen: false,
      budget_run_id: reservation.reservation_id,
    };
  });
}

export async function cancelPreProviderReservation(
  storage: BudgetStorage,
  input: {
    idempotency_key: string;
    request_digest: string;
    reserve_owner_capability: string;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{
    cancelled: boolean;
    tombstoned: boolean;
    reservation: PublicReservation | null;
    budget_run_id: string | null;
  }>
> {
  const key = requireIdempotencyKey(input.idempotency_key);
  if (!key.ok) return key;
  const boundDigest = requireNonemptyRequestDigest(input.request_digest);
  if (!boundDigest.ok) return boundDigest;
  const owner = requireReserveOwnerCapability(input.reserve_owner_capability);
  if (!owner.ok) return owner;
  const ownerHash = await hashReserveOwnerCapability(
    owner.reserve_owner_capability,
    key.idempotency_key,
    boundDigest.request_digest,
  );

  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    const reservation = state.reservations[key.idempotency_key];
    if (!reservation) {
      const tombstoneError = await persistOwnerCancellationTombstone(
        transaction,
        state,
        ownerHash,
        key.idempotency_key,
        boundDigest.request_digest,
        now,
      );
      if (tombstoneError) {
        return tombstoneError;
      }
      await saveState(transaction, state);
      return {
        ok: true,
        cancelled: false,
        tombstoned: true,
        reservation: null,
        budget_run_id: null,
      };
    }
    if (reservation.request_digest !== boundDigest.request_digest) {
      await saveState(transaction, state);
      return { ok: false, error: "request_digest_mismatch" };
    }
    if (!reserveOwnerMatches(reservation, ownerHash)) {
      await saveState(transaction, state);
      return { ok: false, error: "reserve_owner_capability_invalid" };
    }
    if (reservation.provider_started_at !== null || reservation.status === "reconciled") {
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_cancellable" };
    }
    const tombstoneError = await persistOwnerCancellationTombstone(
      transaction,
      state,
      ownerHash,
      key.idempotency_key,
      boundDigest.request_digest,
      now,
    );
    if (tombstoneError) {
      return tombstoneError;
    }
    if (reservation.status === "released") {
      await saveState(transaction, state);
      return {
        ok: true,
        cancelled: false,
        tombstoned: true,
        reservation: publicReservation(reservation),
        budget_run_id: reservation.reservation_id,
      };
    }

    state.reserved = applyDelta(state.reserved, reservation.amounts, -1);
    reservation.status = "released";
    reservation.released_at = now;
    closeReservationLease(state, reservation, now);
    await saveState(transaction, state);
    return {
      ok: true,
      cancelled: true,
      tombstoned: true,
      reservation: publicReservation(reservation),
      budget_run_id: reservation.reservation_id,
    };
  });
}

export async function releaseBudget(
  storage: BudgetStorage,
  input: {
    lease_id?: string;
    idempotency_key?: string;
    request_digest?: string;
    reserve_owner_capability?: string;
  },
  now = Date.now(),
): Promise<
  BudgetResult<{ released: boolean; lease: Lease | null; reservation: PublicReservation | null }>
> {
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
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
      await saveState(transaction, state);
      return { ok: false, error: "lease_or_idempotency_key required" };
    }
    if (
      lease &&
      reservation &&
      (lease.reservation_key !== reservation.idempotency_key ||
        reservation.lease_id !== lease.lease_id)
    ) {
      await saveState(transaction, state);
      return { ok: false, error: "lease_reservation_mismatch" };
    }
    if (reservation && reservation.reserve_owner_capability_hash !== null) {
      // Owner-bound reservations have one cancellation authority only:
      // cancelPreProviderReservation. Keeping generic release incapable of
      // mutating them prevents both post-provider release and terminal-state
      // lifecycle bypasses, even when a lease id or owner secret is supplied.
      await saveState(transaction, state);
      return { ok: false, error: "reservation_not_cancellable" };
    }

    if (lease && lease.released_at === null) {
      lease.released_at = now;
    }
    if (reservation && reservation.status === "reserved") {
      if (reservation.provider_started_at !== null) {
        chargeUncertainReservation(state, reservation, "worker_interrupted", now);
        await saveState(transaction, state);
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
    await saveState(transaction, state);
    return {
      ok: true,
      released: true,
      lease,
      reservation: reservation ? publicReservation(reservation) : null,
    };
  });
}

export async function recoverExpiredLeases(
  storage: BudgetStorage,
  now = Date.now(),
): Promise<BudgetResult<{ recovered: number }>> {
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    const recovered = recoverExpired(state, now);
    await saveState(transaction, state);
    return { ok: true, recovered };
  });
}

export function createBudgetCoordinator(storage: BudgetStorage) {
  return {
    reserve(
      input: Parameters<typeof reserveBudget>[1],
      now?: number,
    ): ReturnType<typeof reserveBudget> {
      return reserveBudget(storage, input, now);
    },
    reserveOwned(
      input: Parameters<typeof reserveOwnedBudget>[1],
      now?: number,
    ): ReturnType<typeof reserveOwnedBudget> {
      return reserveOwnedBudget(storage, input, now);
    },
    queryOwned(
      input: Parameters<typeof queryOwnedBudget>[1],
      now?: number,
    ): ReturnType<typeof queryOwnedBudget> {
      return queryOwnedBudget(storage, input, now);
    },
    cancelPreProvider(
      input: Parameters<typeof cancelPreProviderReservation>[1],
      now?: number,
    ): ReturnType<typeof cancelPreProviderReservation> {
      return cancelPreProviderReservation(storage, input, now);
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
    finalizeOwnedPaper(
      input: Parameters<typeof finalizeOwnedPaperReservation>[1],
      now?: number,
    ): ReturnType<typeof finalizeOwnedPaperReservation> {
      return finalizeOwnedPaperReservation(storage, input, now);
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
    owner_cancellation_quarantined: boolean;
    owner_cancellation_quarantine_until: number | null;
  }>
> {
  return storage.runAtomic(async (transaction) => {
    const state = await loadState(transaction, now);
    recoverExpired(state, now);
    await saveState(transaction, state);
    return {
      ok: true,
      created: state.created,
      used: amountsFromCounters(state.used),
      reserved: amountsFromCounters(state.reserved),
      active_leases: activeLeaseCount(state),
      caps: state.caps,
      auto_promotion: false,
      frozen: state.frozen === true,
      owner_cancellation_quarantined:
        state.owner_cancellation_quarantine_until !== null,
      owner_cancellation_quarantine_until:
        state.owner_cancellation_quarantine_until,
    };
  });
}
