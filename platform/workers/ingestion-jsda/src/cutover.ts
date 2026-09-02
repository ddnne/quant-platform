import type { JsdaWorkerEnv } from "./env";

export type V3CutoverStatus = {
  productReady: boolean;
  cutover:
    | "V3_ACTIVE"
    | "PENDING"
    | "AUTHORITY_DISABLED"
    | "INVALID"
    | "UNKNOWN";
  activatedSourceSha: string | null;
  cutoverConfigDigest: string | null;
  drainEvidenceDigest: string | null;
};

export type V3ActivationRecord = {
  phase: string;
  activated_at: string | null;
  activated_source_sha: string | null;
  cutover_config_digest: string | null;
  drain_evidence_digest: string | null;
};

export type V3CutoverPin = {
  readonly configDigest: string;
};

/**
 * Canonical JSDA v3 cutover config identity. The compiled pin is only the
 * SHA-256 of these bytes (`cutover_config_digest`). Drain evidence is a
 * distinct content-addressed document stored in `drain_evidence_digest`.
 * `activated_source_sha` is the 40-hex merged/deployed Git SHA.
 */
export const V3_CUTOVER_PIN_CANONICAL =
  '{"kind":"jsda-v3-cutover-pin/v1","migrations":{"quant-ingest:0011_jsda_queue_v2":"sha256:4faab156820a85ef2d8b22ffd30984f50194b680a1c0df6b59af41e24a5d04ce","quant-ingest:0012_jsda_observation_identity":"sha256:2d04b72ce5cf05c57aaf805d15939b7b0cbfbbbf65b003fec46eea270c330097"},"queue_contract":"jsda-acquisition-job/v2"}';

export const PRODUCTION_V3_CUTOVER_PIN: V3CutoverPin = Object.freeze({
  configDigest:
    "sha256:2fa4e9234dc85e97cab2f972532d21cb8fb29bff2d03ce1359c5d18000e240d5",
});

const ACTIVATED_AT =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const SOURCE_SHA = /^[0-9a-f]{40}$/;
const CONFIG_DIGEST = /^sha256:[0-9a-f]{64}$/;

export function isCanonicalSourceSha(value: unknown): value is string {
  return typeof value === "string" && SOURCE_SHA.test(value);
}

export function isV3CutoverPin(value: unknown): value is V3CutoverPin {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return CONFIG_DIGEST.test(String(candidate.configDigest ?? ""));
}

function observedDigest(value: string | null | undefined): string | null {
  return CONFIG_DIGEST.test(value ?? "") ? value! : null;
}

function observedSourceSha(row: V3ActivationRecord | null | undefined): string | null {
  const value = row?.activated_source_sha ?? null;
  return isCanonicalSourceSha(value) ? value : null;
}

export async function loadV3CutoverStatus(
  db: JsdaWorkerEnv["DB"],
  pin: V3CutoverPin = PRODUCTION_V3_CUTOVER_PIN,
): Promise<V3CutoverStatus> {
  const row = await db
    .prepare(
      `SELECT phase, activated_at, activated_source_sha,
              cutover_config_digest, drain_evidence_digest
         FROM jsda_v3_cutover_control
        WHERE singleton=1`,
    )
    .first<V3ActivationRecord>();
  const activatedSourceSha = observedSourceSha(row);
  const cutoverConfigDigest = observedDigest(row?.cutover_config_digest);
  const drainEvidenceDigest = observedDigest(row?.drain_evidence_digest);
  const identities = {
    activatedSourceSha,
    cutoverConfigDigest,
    drainEvidenceDigest,
  };
  if (row?.phase === "bridge") {
    return { productReady: false, cutover: "PENDING", ...identities };
  }
  if (
    row?.phase === "v3_active" &&
    ACTIVATED_AT.test(row.activated_at ?? "") &&
    isCanonicalSourceSha(row.activated_source_sha) &&
    CONFIG_DIGEST.test(row.cutover_config_digest ?? "") &&
    CONFIG_DIGEST.test(row.drain_evidence_digest ?? "") &&
    row.cutover_config_digest !== row.drain_evidence_digest
  ) {
    if (
      isV3CutoverPin(pin) &&
      row.cutover_config_digest === pin.configDigest
    ) {
      return { productReady: true, cutover: "V3_ACTIVE", ...identities };
    }
    return { productReady: false, cutover: "AUTHORITY_DISABLED", ...identities };
  }
  return { productReady: false, cutover: "INVALID", ...identities };
}

export async function requireV3CutoverActive(
  db: JsdaWorkerEnv["DB"],
  pin: V3CutoverPin = PRODUCTION_V3_CUTOVER_PIN,
): Promise<void> {
  try {
    const status = await loadV3CutoverStatus(db, pin);
    if (status.productReady) return;
  } catch {
    // A missing/malformed migration surface is never product-ready.
  }
  throw new Error("JSDA_V3_CUTOVER_PENDING");
}
