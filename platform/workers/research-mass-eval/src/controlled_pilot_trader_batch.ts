import {
  CONTROLLED_FILL_CONTRACT_DIGEST,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_PILOT_PLAN_COUNT,
  CONTROLLED_TRADER_BATCH_FORMAT,
  EXACT_FOUR_BINDING_DIGEST,
  EXACT_FOUR_BUDGET_SCOPE_DIGEST,
  EXACT_FOUR_EXECUTION_LIMIT_SET_DIGEST,
  EXACT_FOUR_PLAN_BINDING_DIGESTS,
  EXACT_FOUR_PLAN_IDS,
  EXACT_FOUR_POLICY_DIGEST,
  EXACT_FOUR_STRATEGY_BY_PLAN,
  EXACT_FOUR_STRATEGY_SPEC_HASHES,
  EXACT_FOUR_STRATEGY_SPEC_VERSIONS,
  type ControlledPilotRequest,
} from "./controlled_pilot_contract";
import {
  canonicalJson,
  decodeStrictJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
  StrictJsonError,
} from "./controlled_pilot_json";
import { keyUsableAt, type PinnedVerifyKey } from "./controlled_pilot_registries";

const MIN_TTL_MS = 60_000;
const MAX_TTL_MS = 86_400_000;
const TRADER_FIELDS = [
  "format", "schema_version", "purpose", "algorithm", "identity", "environment", "authority_instance_id",
  "request_digest", "idempotency_key", "ready_attestation_id", "ready_manifest_digest", "snapshot_id",
  "immutable_db_digest", "snapshot_key", "snapshot_size", "profile_digest", "dependency_closure_digest",
  "exact_four_binding_digest", "policy_digest", "budget_scope_digest", "execution_limit_set_digest",
  "resolved_universe_digest", "fill_contract_digest", "rows", "issued_at", "expires_at", "key_id", "issuer",
] as const;
const TRADER_ROW_FIELDS = new Set([
  "ordinal", "plan_id", "plan_binding_digest", "strategy_spec_id", "strategy_spec_version", "strategy_spec_hash",
]);

export type TraderReadyBind = {
  environment: string;
  ready_manifest_digest: string;
  snapshot_id: string;
  immutable_db_digest: string;
  physical: { key: string; size: number };
  profile_digest: string;
  dependency_closure_digest: string;
  resolved_universe_digest: string;
};

export type TraderVerifierClock = { now(): number };

function closedShape(value: Record<string, unknown>, fields: Set<string> | readonly string[]): boolean {
  const expected = fields instanceof Set ? fields : new Set(fields);
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function decodeSignature(signature: unknown): Uint8Array | null {
  if (typeof signature !== "string" || !signature.startsWith("ed25519:")) return null;
  try {
    const raw = atob(signature.slice("ed25519:".length));
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

async function verifyEd25519(
  publicKey: Uint8Array,
  signature: Uint8Array,
  message: Uint8Array,
): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey("raw", publicKey, "Ed25519", false, ["verify"]);
    return crypto.subtle.verify("Ed25519", key, signature, message);
  } catch {
    return false;
  }
}

export function exactFourTraderRows(): Array<Record<string, unknown>> {
  return EXACT_FOUR_PLAN_IDS.map((planId, index) => {
    const strategyId = EXACT_FOUR_STRATEGY_BY_PLAN[planId];
    return {
      ordinal: index + 1,
      plan_id: planId,
      plan_binding_digest: EXACT_FOUR_PLAN_BINDING_DIGESTS[planId],
      strategy_spec_id: strategyId,
      strategy_spec_version: EXACT_FOUR_STRATEGY_SPEC_VERSIONS[planId],
      strategy_spec_hash: EXACT_FOUR_STRATEGY_SPEC_HASHES[strategyId!],
    };
  });
}

export async function verifyTraderAuthorizationBatch(
  document: unknown,
  request: ControlledPilotRequest,
  ready: TraderReadyBind,
  requestDigest: string,
  keys: readonly PinnedVerifyKey[],
  clock: TraderVerifierClock = { now: () => Date.now() },
): Promise<{ ok: true; authorization_digest: string } | { ok: false; error: string }> {
  if (!isRecord(document) || !("signature" in document)) {
    return { ok: false, error: "trader authorization must be an object" };
  }
  const traderBody = { ...document };
  delete traderBody.signature;
  if (!closedShape(traderBody, TRADER_FIELDS)) {
    return { ok: false, error: "trader authorization must be an object" };
  }
  if (document.format !== CONTROLLED_TRADER_BATCH_FORMAT) {
    return { ok: false, error: "trader authorization format is invalid" };
  }
  if (keys.length === 0) return { ok: false, error: "trader authorization issuer is unprovisioned" };
  if (keys.length !== 1) return { ok: false, error: "trader authorization permits exactly one ACTIVE key" };
  const issuedAt = parseCanonicalUtc(document.issued_at);
  const traderKey = keys[0]!;
  if (traderKey.environment && traderKey.environment !== ready.environment) {
    return { ok: false, error: "trader key environment denied" };
  }
  if (traderKey.not_before && !keyUsableAt(traderKey, issuedAt)) {
    return { ok: false, error: "trader key window denied" };
  }
  if (traderKey.key_id !== String(document.key_id || "")) {
    return { ok: false, error: "trader authorization issuer is untrusted" };
  }
  if (
    document.schema_version !== 2 ||
    document.purpose !== "controlled_trader_authorization_verification" ||
    document.algorithm !== "Ed25519" ||
    document.identity !== CONTROLLED_PILOT_IDENTITY ||
    document.environment !== ready.environment ||
    document.authority_instance_id !== `trader-authority/${ready.environment}/v1` ||
    document.request_digest !== requestDigest ||
    document.idempotency_key !== request.idempotency_key ||
    document.ready_attestation_id !== request.ready_attestation_id ||
    document.ready_manifest_digest !== ready.ready_manifest_digest ||
    document.snapshot_id !== ready.snapshot_id ||
    document.immutable_db_digest !== ready.immutable_db_digest ||
    document.snapshot_key !== ready.physical.key ||
    document.snapshot_size !== ready.physical.size ||
    document.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST ||
    document.profile_digest !== ready.profile_digest ||
    document.dependency_closure_digest !== ready.dependency_closure_digest ||
    document.resolved_universe_digest !== ready.resolved_universe_digest ||
    document.exact_four_binding_digest !== EXACT_FOUR_BINDING_DIGEST ||
    document.policy_digest !== EXACT_FOUR_POLICY_DIGEST ||
    document.budget_scope_digest !== EXACT_FOUR_BUDGET_SCOPE_DIGEST ||
    document.execution_limit_set_digest !== EXACT_FOUR_EXECUTION_LIMIT_SET_DIGEST ||
    document.issuer !== "ControlledTraderAuthorizationService/v1"
  ) {
    return { ok: false, error: "trader authorization does not bind the request" };
  }
  const rows = document.rows;
  if (!Array.isArray(rows) || rows.length !== CONTROLLED_PILOT_PLAN_COUNT) {
    return { ok: false, error: "trader authorization must cover the canonical four" };
  }
  for (let index = 0; index < rows.length; index += 1) {
    const raw = rows[index];
    if (!isRecord(raw) || !closedShape(raw, TRADER_ROW_FIELDS)) {
      return { ok: false, error: "trader authorization row is invalid" };
    }
    const expectedPlan = EXACT_FOUR_PLAN_IDS[index]!;
    const strategyId = EXACT_FOUR_STRATEGY_BY_PLAN[expectedPlan];
    if (
      raw.ordinal !== index + 1 ||
      raw.plan_id !== expectedPlan ||
      raw.strategy_spec_id !== strategyId ||
      raw.strategy_spec_version !== EXACT_FOUR_STRATEGY_SPEC_VERSIONS[expectedPlan] ||
      raw.strategy_spec_hash !== EXACT_FOUR_STRATEGY_SPEC_HASHES[strategyId!] ||
      raw.plan_binding_digest !== EXACT_FOUR_PLAN_BINDING_DIGESTS[expectedPlan]
    ) {
      return { ok: false, error: "trader authorization plan sequence is not the canonical ordered four" };
    }
  }
  const issued = parseCanonicalUtc(document.issued_at);
  const expires = parseCanonicalUtc(document.expires_at);
  const ttl = expires - issued;
  if (
    !Number.isFinite(issued) ||
    !Number.isFinite(expires) ||
    ttl < MIN_TTL_MS ||
    ttl > MAX_TTL_MS ||
    clock.now() > expires
  ) {
    return { ok: false, error: "trader authorization is expired" };
  }
  const key = keys.find((item) => item.key_id === String(document.key_id || ""));
  if (!key) return { ok: false, error: "trader authorization issuer is untrusted" };
  const signature = decodeSignature(document.signature);
  if (!signature) return { ok: false, error: "trader authorization signature is invalid" };
  const body = { ...document };
  delete body.signature;
  if (!(await verifyEd25519(key.public_key, signature, new TextEncoder().encode(canonicalJson(body))))) {
    return { ok: false, error: "trader authorization signature is invalid" };
  }
  return {
    ok: true,
    authorization_digest: await sha256Digest(canonicalJson(document)),
  };
}

export async function verifyTraderAuthorizationBatchBytes(
  bytes: Uint8Array,
  request: ControlledPilotRequest,
  ready: TraderReadyBind,
  requestDigest: string,
  keys: readonly PinnedVerifyKey[],
  clock: TraderVerifierClock = { now: () => Date.now() },
): Promise<{ ok: true; authorization_digest: string } | { ok: false; error: string }> {
  try {
    return await verifyTraderAuthorizationBatch(
      decodeStrictJson(bytes),
      request,
      ready,
      requestDigest,
      keys,
      clock,
    );
  } catch (error) {
    const detail = error instanceof StrictJsonError ? error.message : "trader JSON is invalid";
    return { ok: false, error: detail };
  }
}
