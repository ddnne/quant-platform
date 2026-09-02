import {
  READY_PRODUCTION_RAW,
  READY_PRODUCTION_RAW_DIGEST,
  READY_PRODUCTION_RAW_SIZE,
  READY_STAGING_RAW,
  READY_STAGING_RAW_DIGEST,
  READY_STAGING_RAW_SIZE,
  TRADER_PRODUCTION_RAW,
  TRADER_PRODUCTION_RAW_DIGEST,
  TRADER_PRODUCTION_RAW_SIZE,
  TRADER_STAGING_RAW,
  TRADER_STAGING_RAW_DIGEST,
  TRADER_STAGING_RAW_SIZE,
} from "./controlled_pilot_registry_raw.generated";
import {
  canonicalJson,
  decodeStrictJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
} from "./controlled_pilot_json";

export type PinnedVerifyKey = {
  key_id: string;
  public_key: Uint8Array;
  algorithm: string;
  status: string;
  not_before: string;
  not_after: string;
  revoked_at: string | null;
  environment: string;
};

export const READY_DIGEST = {
  production: "sha256:8f2f7fe9353dc2082d57a0a3bd480575adf1095836e4729364b763d8b4459d84",
  staging: "sha256:30a7a04c4cca8ed96f0813423e1ceb049d4d80c36c0db62c01e327354e5c8aae",
} as const;
export const TRADER_DIGEST = {
  production: "sha256:ca52153e148fc0603a6073cd2eecb7eeaa058345eefc4dbfa882664fc1640e49",
  staging: "sha256:99333ec060ada318e65d8bb61479397cd601f127a28c3d670fc8b24435efbdd1",
} as const;
export const READY_RAW = {
  production: { digest: READY_PRODUCTION_RAW_DIGEST, size: READY_PRODUCTION_RAW_SIZE },
  staging: { digest: READY_STAGING_RAW_DIGEST, size: READY_STAGING_RAW_SIZE },
} as const;
export const TRADER_RAW = {
  production: { digest: TRADER_PRODUCTION_RAW_DIGEST, size: TRADER_PRODUCTION_RAW_SIZE },
  staging: { digest: TRADER_STAGING_RAW_DIGEST, size: TRADER_STAGING_RAW_SIZE },
} as const;

const REGISTRY_FIELDS = new Set([
  "schema_version",
  "purpose",
  "environment",
  "authority_instance_id",
  "keys",
]);
const KEY_ROW_FIELDS = new Set([
  "key_id",
  "algorithm",
  "public_key_b64",
  "status",
  "not_before",
  "not_after",
  "revoked_at",
]);

function decodeB64(raw: string): Uint8Array | null {
  try {
    const bin = atob(raw);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return bytes.byteLength === 32 ? bytes : null;
  } catch {
    return null;
  }
}

export async function digestOf(document: unknown): Promise<string> {
  return sha256Digest(canonicalJson(document));
}

function failClosed(_reason: string): PinnedVerifyKey[] {
  return [];
}

export function keyUsableAt(key: PinnedVerifyKey, signedAtMs: number): boolean {
  if (!Number.isFinite(signedAtMs)) return false;
  if (key.algorithm !== "Ed25519") return false;
  if (!new Set(["active", "retired", "revoked"]).has(key.status)) return false;
  if (key.status !== "revoked" && key.revoked_at !== null) return false;
  const notBefore = parseCanonicalUtc(key.not_before);
  const notAfter = parseCanonicalUtc(key.not_after);
  if (!Number.isFinite(notBefore) || !Number.isFinite(notAfter)) return false;
  if (signedAtMs < notBefore || signedAtMs > notAfter) return false;
  if (key.status === "revoked") {
    const revokedAt = parseCanonicalUtc(key.revoked_at);
    if (!Number.isFinite(revokedAt) || signedAtMs >= revokedAt) return false;
  }
  return true;
}

export function parseRegistry(
  document: unknown,
  environment: string,
  purpose: string,
  authorityPrefix: "ready-authority" | "trader-authority",
  expectedDigest: string,
  observedDigest: string,
  allowedStatus: ReadonlySet<string>,
): PinnedVerifyKey[] {
  if (observedDigest !== expectedDigest) return failClosed("digest");
  if (!isRecord(document)) return failClosed("object");
  const keys = Object.keys(document);
  if (keys.length !== REGISTRY_FIELDS.size || keys.some((key) => !REGISTRY_FIELDS.has(key))) {
    return failClosed("shape");
  }
  if (
    document.schema_version !== 2 ||
    document.purpose !== purpose ||
    document.environment !== environment ||
    document.authority_instance_id !== `${authorityPrefix}/${environment}/v1` ||
    !Array.isArray(document.keys)
  ) {
    return failClosed("contract");
  }
  const verificationKeys: PinnedVerifyKey[] = [];
  const seen = new Set<string>();
  for (const row of document.keys) {
    if (!isRecord(row)) return failClosed("row");
    const rowKeys = Object.keys(row);
    if (rowKeys.length !== KEY_ROW_FIELDS.size || rowKeys.some((key) => !KEY_ROW_FIELDS.has(key))) {
      return failClosed("row-shape");
    }
    if (row.algorithm !== "Ed25519") return failClosed("alg");
    if (typeof row.status !== "string" || !allowedStatus.has(row.status)) {
      return failClosed("status");
    }
    const keyId = typeof row.key_id === "string" ? row.key_id.trim() : "";
    if (!keyId || seen.has(keyId)) return failClosed("id");
    seen.add(keyId);
    if (typeof row.not_before !== "string" || typeof row.not_after !== "string") {
      return failClosed("window");
    }
    if (!Number.isFinite(parseCanonicalUtc(row.not_before)) || !Number.isFinite(parseCanonicalUtc(row.not_after))) {
      return failClosed("window-parse");
    }
    if (row.status === "revoked") {
      if (typeof row.revoked_at !== "string" || !Number.isFinite(parseCanonicalUtc(row.revoked_at))) {
        return failClosed("revoked_at");
      }
    } else if (row.revoked_at !== null) {
      return failClosed("active-revoked");
    }
    if (row.status === "pending") continue;
    const bytes = decodeB64(String(row.public_key_b64 || ""));
    if (!bytes) return failClosed("key");
    verificationKeys.push({
      key_id: keyId,
      public_key: bytes,
      algorithm: "Ed25519",
      status: row.status,
      not_before: row.not_before,
      not_after: row.not_after,
      revoked_at: row.revoked_at as string | null,
      environment,
    });
  }
  if (verificationKeys.filter((key) => key.status === "active").length > 1) {
    return failClosed("multi-active");
  }
  return verificationKeys;
}

export async function parseCommittedRegistryBytes(
  bytes: Uint8Array,
  environment: string,
  purpose: string,
  authorityPrefix: "ready-authority" | "trader-authority",
  expectedDigest: string,
  allowedStatus: ReadonlySet<string>,
  expectedRaw?: { digest: string; size: number },
): Promise<PinnedVerifyKey[]> {
  if (!expectedRaw) return [];
  const rawDigest = await sha256Digest(bytes);
  if (bytes.byteLength !== expectedRaw.size || rawDigest !== expectedRaw.digest) {
    return [];
  }
  if (expectedRaw.digest === expectedDigest) return [];
  let document: unknown;
  try {
    document = decodeStrictJson(bytes);
  } catch {
    return [];
  }
  const observed = await digestOf(document);
  if (observed === expectedRaw.digest) return [];
  return parseRegistry(
    document,
    environment,
    purpose,
    authorityPrefix,
    expectedDigest,
    observed,
    allowedStatus,
  );
}

const READY_STATUS = new Set(["active", "retired", "revoked"]);
const TRADER_STATUS = new Set(["active", "retired", "revoked", "pending"]);

const readyCache = new Map<string, PinnedVerifyKey[]>();
const traderCache = new Map<string, PinnedVerifyKey[]>();

async function loadFromRaw(
  environment: string,
  bytes: Uint8Array,
  purpose: string,
  authorityPrefix: "ready-authority" | "trader-authority",
  expectedDigest: string,
  allowedStatus: ReadonlySet<string>,
  expectedRaw: { digest: string; size: number },
  cache: Map<string, PinnedVerifyKey[]>,
): Promise<PinnedVerifyKey[]> {
  const cached = cache.get(environment);
  if (cached) return cached;
  const keys = await parseCommittedRegistryBytes(
    bytes,
    environment,
    purpose,
    authorityPrefix,
    expectedDigest,
    allowedStatus,
    expectedRaw,
  );
  cache.set(environment, keys);
  return keys;
}

export async function loadPinnedReadyKeys(environment: string): Promise<PinnedVerifyKey[]> {
  if (environment === "staging") {
    return loadFromRaw(
      environment,
      READY_STAGING_RAW,
      "readiness_attestation_verification",
      "ready-authority",
      READY_DIGEST.staging,
      READY_STATUS,
      READY_RAW.staging,
      readyCache,
    );
  }
  if (environment === "production") {
    return loadFromRaw(
      environment,
      READY_PRODUCTION_RAW,
      "readiness_attestation_verification",
      "ready-authority",
      READY_DIGEST.production,
      READY_STATUS,
      READY_RAW.production,
      readyCache,
    );
  }
  return [];
}

export async function loadPinnedTraderKeys(environment: string): Promise<PinnedVerifyKey[]> {
  if (environment === "staging") {
    return loadFromRaw(
      environment,
      TRADER_STAGING_RAW,
      "controlled_trader_authorization_verification",
      "trader-authority",
      TRADER_DIGEST.staging,
      TRADER_STATUS,
      TRADER_RAW.staging,
      traderCache,
    );
  }
  if (environment === "production") {
    return loadFromRaw(
      environment,
      TRADER_PRODUCTION_RAW,
      "controlled_trader_authorization_verification",
      "trader-authority",
      TRADER_DIGEST.production,
      TRADER_STATUS,
      TRADER_RAW.production,
      traderCache,
    );
  }
  return [];
}

export async function assertRegistryDigests(): Promise<boolean> {
  const readyProd = await digestOf(decodeStrictJson(READY_PRODUCTION_RAW));
  const readyStg = await digestOf(decodeStrictJson(READY_STAGING_RAW));
  const traderProd = await digestOf(decodeStrictJson(TRADER_PRODUCTION_RAW));
  const traderStg = await digestOf(decodeStrictJson(TRADER_STAGING_RAW));
  const readyProdRaw = await sha256Digest(READY_PRODUCTION_RAW);
  const traderProdRaw = await sha256Digest(TRADER_PRODUCTION_RAW);
  return (
    readyProd === READY_DIGEST.production &&
    readyStg === READY_DIGEST.staging &&
    traderProd === TRADER_DIGEST.production &&
    traderStg === TRADER_DIGEST.staging &&
    readyProdRaw === READY_RAW.production.digest &&
    traderProdRaw === TRADER_RAW.production.digest &&
    READY_PRODUCTION_RAW.byteLength === READY_RAW.production.size &&
    TRADER_PRODUCTION_RAW.byteLength === TRADER_RAW.production.size
  );
}

export function controlledEnvironment(env: { ENVIRONMENT?: string }): "staging" | "production" | null {
  return env.ENVIRONMENT === "staging" || env.ENVIRONMENT === "production" ? env.ENVIRONMENT : null;
}

export const COMMITTED_READY_DOCUMENTS = {
  production: READY_PRODUCTION_RAW,
  staging: READY_STAGING_RAW,
} as const;
export const COMMITTED_TRADER_DOCUMENTS = {
  production: TRADER_PRODUCTION_RAW,
  staging: TRADER_STAGING_RAW,
} as const;
