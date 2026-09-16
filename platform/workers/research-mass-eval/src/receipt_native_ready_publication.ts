import {
  CONTROLLED_FILL_CONTRACT_DIGEST,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT,
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_COVERAGE_POLICY_DIGEST,
  EXACT_FOUR_COVERAGE_POLICY_VERSION,
  EXACT_FOUR_DATASET_IDS,
  EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST,
  EXACT_FOUR_PLAN_IDS,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  EXACT_FOUR_PROFILE_ID,
  EXACT_FOUR_PROFILE_VERSION,
  EXACT_FOUR_UNIVERSE_RULE_DIGEST,
  exactFourUniversePeriod,
} from "./controlled_pilot_contract";
import {
  canonicalJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
} from "./controlled_pilot_json";
import {
  keyUsableAt,
  loadPinnedReadyKeys,
} from "./controlled_pilot_registries";
import { personalReceiptCandidatePhysicalKey } from "./personal_receipt_candidate_contract";
import {
  deriveReceiptNativeSessionScope,
  type ControlledSessionScope,
} from "./ops_projection_ready";
import {
  READY_MANIFEST_V2_FORMAT,
  receiptNativeSnapshotId,
  receiptNativeV2WireError,
} from "./ready_manifest_v2";

export const PINNED_RECEIPT_REGISTRY_SCOPE = {
  production: {
    authority_instance_digest:
      "sha256:e6d7df1b9000481d15b8987f5ffda7f3a0b0c051a43cf0051d04a38e58e372a6",
  },
  staging: {
    authority_instance_digest:
      "sha256:5104b2d3b85ddbbd44fb9e4ddc2689898232c2e6e175727c71c1ce2cb6ec9bff",
  },
} as const;

const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const READINESS_ATTESTATION_FORMAT = "verified-readiness-attestation/v1";
const MIN_TTL_MS = 60_000;
const MAX_TTL_MS = 86_400_000;
const FIVE_MINUTES_MS = 5 * 60_000;

const ENVELOPE_NATIVE_FIELDS = new Set([
  "format", "identity", "environment", "job_id", "admitted_native_digest",
  "attestation", "ready_manifest", "physical",
  "dependency_scope_evidence", "controlled_session_scope",
]);
const PHYSICAL_FIELDS = new Set(["key", "digest", "size"]);
const ATTESTATION_NATIVE_FIELDS = [
  "format", "attestation_id", "environment", "authority_instance_id", "authority_resource_digest",
  "readiness_scope", "identity", "snapshot_id", "profile_id",
  "profile_version", "profile_digest", "plan_ids", "plan_set_digest", "dependency_closure_digest",
  "universe_rule_digest", "resolved_universe_digest", "dataset_ids", "ready_state", "ready_manifest_digest",
  "immutable_db_digest", "coverage_policy_version", "coverage_policy_digest", "coverage_proof_digest",
  "governed_membership_digest", "raw_proof_digest", "receipt_proof_digest", "validation_proof_digest",
  "b0_quality_proof_digest", "b4_quality_proof_digest",
  "verified_at", "expires_at", "evidence_digest", "key_id", "signature", "issuer", "fill_contract_digest",
] as const;
const ATTESTATION_NATIVE_MANIFEST_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ["profile_id", "profile_id"],
  ["profile_version", "profile_version"],
  ["profile_digest", "profile_digest"],
  ["plan_ids", "plan_ids"],
  ["plan_set_digest", "plan_set_digest"],
  ["dependency_closure_digest", "dependency_closure_digest"],
  ["universe_rule_digest", "universe_rule_digest"],
  ["resolved_universe_digest", "resolved_universe_digest"],
  ["dataset_ids", "dataset_ids"],
  ["ready_manifest_digest", "manifest_digest"],
  ["coverage_policy_version", "coverage_policy_version"],
  ["coverage_policy_digest", "coverage_policy_digest"],
  ["coverage_proof_digest", "coverage_proof_digest"],
  ["governed_membership_digest", "dataset_membership_digest"],
  ["raw_proof_digest", "raw_proof_digest"],
  ["receipt_proof_digest", "receipt_proof_digest"],
  ["validation_proof_digest", "validation_proof_digest"],
  ["b0_quality_proof_digest", "b0_proof_digest"],
  ["b4_quality_proof_digest", "b4_proof_digest"],
  ["fill_contract_digest", "fill_contract_digest"],
];
const ATTESTATION_NATIVE_DIGEST_FIELDS = [
  "authority_resource_digest",
  "profile_digest",
  "plan_set_digest",
  "dependency_closure_digest",
  "universe_rule_digest",
  "resolved_universe_digest",
  "ready_manifest_digest",
  "immutable_db_digest",
  "coverage_policy_digest",
  "coverage_proof_digest",
  "governed_membership_digest",
  "raw_proof_digest",
  "receipt_proof_digest",
  "validation_proof_digest",
  "b0_quality_proof_digest",
  "b4_quality_proof_digest",
  "evidence_digest",
  "fill_contract_digest",
] as const;

export type VerifiedReceiptNativePublication = {
  format: typeof CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT;
  job_id: string;
  attestation_id: string;
  snapshot_id: string;
  immutable_db_digest: string;
  physical: { key: string; digest: string; size: number };
  admitted_native_digest: string;
  ready_manifest_digest: string;
  identity: string;
  environment: string;
  session_scope: ControlledSessionScope;
  envelope: Record<string, unknown>;
};

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_RE.test(value);
}

function jsonEqual(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

function closedShape(value: Record<string, unknown>, fields: Set<string> | readonly string[]): boolean {
  const expected = fields instanceof Set ? fields : new Set(fields);
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function equalStringArrays(left: unknown, right: readonly string[]): boolean {
  return Array.isArray(left) && left.length === right.length && left.every((item, index) => item === right[index]);
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

export function verifyControlledPilotBinding(manifest: Record<string, unknown>): string | null {
  if (manifest.identity !== CONTROLLED_PILOT_IDENTITY) {
    return "ReadyManifest identity is invalid";
  }
  if (manifest.publication_scope !== "PILOT") return "ReadyManifest scope is not PILOT";
  if (manifest.profile_id !== EXACT_FOUR_PROFILE_ID) return "profile_id mismatch";
  if (manifest.profile_version !== EXACT_FOUR_PROFILE_VERSION) {
    return "profile_version mismatch";
  }
  if (manifest.profile_digest !== EXACT_FOUR_PROFILE_DIGEST) return "profile_digest mismatch";
  if (!equalStringArrays(manifest.plan_ids, EXACT_FOUR_PLAN_IDS)) return "plan_ids mismatch";
  if (manifest.plan_set_digest !== EXACT_FOUR_PLAN_SET_DIGEST) {
    return "plan_set_digest mismatch";
  }
  if (manifest.dependency_closure_digest !== EXACT_FOUR_CLOSURE_DIGEST) {
    return "dependency_closure_digest mismatch";
  }
  if (manifest.universe_rule_digest !== EXACT_FOUR_UNIVERSE_RULE_DIGEST) {
    return "universe_rule_digest mismatch";
  }
  if (!equalStringArrays(manifest.dataset_ids, EXACT_FOUR_DATASET_IDS)) {
    return "dataset_ids mismatch";
  }
  if (manifest.dataset_membership_digest !== EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST) {
    return "dataset membership mismatch";
  }
  if (manifest.coverage_policy_version !== EXACT_FOUR_COVERAGE_POLICY_VERSION) {
    return "coverage policy version mismatch";
  }
  if (manifest.coverage_policy_digest !== EXACT_FOUR_COVERAGE_POLICY_DIGEST) {
    return "coverage policy digest mismatch";
  }
  if (manifest.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST) {
    return "fill contract digest mismatch";
  }
  return null;
}

const B0_RECEIPT_MEASURES = [
  { name: "B0_master", gate: 3000 },
  { name: "B0_bars_issuers", gate: 3000 },
  { name: "B0_bars_latest_day", gate: 3000 },
] as const;
const B0_ROW_FIELDS = ["name", "ok", "value", "gate", "detail"] as const;
const CHECK_ROW_FIELDS = ["check_id", "dataset", "status", "detail", "metrics"] as const;
const RECEIPT_NATIVE_C8_SERIES = [
  "equities_bars_daily",
  "indices_bars_daily_topix",
  "markets_calendar",
] as const;
const C8_BOUND_WINDOW_DAYS = 7;

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isoDateDay(value: unknown): string | null {
  if (typeof value !== "string" || value.length < 10) return null;
  const day = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const parsed = Date.parse(`${day}T00:00:00Z`);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 10) !== day) {
    return null;
  }
  return day;
}

function calendarDaysBetween(startDay: string, endDay: string): number | null {
  const start = Date.parse(`${startDay}T00:00:00Z`);
  const end = Date.parse(`${endDay}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return (end - start) / 86_400_000;
}

function receiptNativeC8Datasets(): string[] {
  return RECEIPT_NATIVE_C8_SERIES.filter((dataset) =>
    (EXACT_FOUR_DATASET_IDS as readonly string[]).includes(dataset),
  );
}

export function verifyReceiptNativePeriod(
  periodStart: unknown,
  periodEnd: unknown,
): string | null {
  const period = exactFourUniversePeriod();
  if (!period) return "exact-four plans do not share one governed universe period";
  if (periodStart !== period.period_start || periodEnd !== period.period_end) {
    return "period is not the canonical exact-four universe period";
  }
  return null;
}

export function verifyReceiptNativeSnapshotQuality(
  quality: Record<string, unknown>,
  native: Record<string, unknown>,
  physicalDigest: string,
): string | null {
  if (quality.kind !== "receipt-candidate-snapshot-quality/v1") {
    return "snapshot quality kind is invalid";
  }
  if (!isRecord(native.source)) return "snapshot quality payload is missing";
  if (
    quality.physical_digest !== physicalDigest ||
    quality.profile_digest !== EXACT_FOUR_PROFILE_DIGEST ||
    quality.plan_set_digest !== EXACT_FOUR_PLAN_SET_DIGEST ||
    quality.dependency_closure_digest !== EXACT_FOUR_CLOSURE_DIGEST ||
    quality.receipt_runset_digest !== native.source.receipt_runset_digest ||
    quality.observation_policy !== "max_verified_claims_checked_at" ||
    quality.observed_through !== native.source.observed_through
  ) {
    return "snapshot quality does not bind this physical/profile/runset/observation";
  }
  const periodError = verifyReceiptNativePeriod(quality.period_start, quality.period_end);
  if (periodError) return `snapshot quality ${periodError}`;
  if (!Array.isArray(quality.b0) || quality.b0.length !== B0_RECEIPT_MEASURES.length) {
    return "snapshot quality B0 measures are incomplete";
  }
  for (let index = 0; index < B0_RECEIPT_MEASURES.length; index += 1) {
    const row = quality.b0[index];
    const expected = B0_RECEIPT_MEASURES[index]!;
    if (!isRecord(row) || !closedShape(row, B0_ROW_FIELDS)) {
      return "snapshot quality B0 measures are incomplete";
    }
    if (
      row.name !== expected.name ||
      !finiteNumber(row.value) ||
      !finiteNumber(row.gate) ||
      row.gate !== expected.gate ||
      typeof row.ok !== "boolean" ||
      row.ok !== row.value >= row.gate ||
      row.ok !== true
    ) {
      return "snapshot quality B0 measures are not PASS";
    }
  }
  if (!Array.isArray(quality.b4) || quality.b4.length !== 1) {
    return "snapshot quality B4 measures are incomplete";
  }
  const b4 = quality.b4[0];
  if (!isRecord(b4) || !closedShape(b4, CHECK_ROW_FIELDS) || !isRecord(b4.metrics)) {
    return "snapshot quality B4 measures are incomplete";
  }
  const b4Metrics = b4.metrics;
  if (
    b4.check_id !== "B4" ||
    b4.dataset !== "equities_bars_daily" ||
    b4.status !== "pass" ||
    !finiteNumber(b4Metrics.bar_dates) ||
    !finiteNumber(b4Metrics.trading_days_in_window) ||
    !finiteNumber(b4Metrics.gap_rate) ||
    !finiteNumber(b4Metrics.missing_day_count) ||
    b4Metrics.bar_dates < 1 ||
    b4Metrics.trading_days_in_window < 1 ||
    b4Metrics.bar_dates < b4Metrics.trading_days_in_window ||
    b4Metrics.gap_rate !== 0 ||
    b4Metrics.missing_day_count !== 0 ||
    !Array.isArray(b4Metrics.missing_days_sample) ||
    b4Metrics.missing_days_sample.length !== 0
  ) {
    return "snapshot quality B4 measures are not PASS";
  }
  const c8Datasets = receiptNativeC8Datasets();
  if (!Array.isArray(quality.c8) || quality.c8.length !== c8Datasets.length) {
    return "snapshot quality C8 measures are incomplete";
  }
  const seenC8 = new Set<string>();
  for (const raw of quality.c8) {
    if (!isRecord(raw) || !closedShape(raw, CHECK_ROW_FIELDS) || !isRecord(raw.metrics)) {
      return "snapshot quality C8 measures are incomplete";
    }
    if (
      raw.check_id !== "C8" ||
      typeof raw.dataset !== "string" ||
      !c8Datasets.includes(raw.dataset) ||
      seenC8.has(raw.dataset) ||
      raw.status !== "pass"
    ) {
      return "snapshot quality C8 measures are not PASS";
    }
    seenC8.add(raw.dataset);
    const metrics = raw.metrics;
    const latestDay = isoDateDay(metrics.latest_event_time);
    const referenceDay = isoDateDay(metrics.reference);
    const lagged =
      latestDay && referenceDay ? calendarDaysBetween(latestDay, referenceDay) : null;
    if (
      !finiteNumber(metrics.days_lag) ||
      metrics.max_days !== C8_BOUND_WINDOW_DAYS ||
      referenceDay !== String(quality.period_end) ||
      latestDay == null ||
      lagged == null ||
      metrics.days_lag !== lagged ||
      metrics.days_lag < 0 ||
      metrics.days_lag > C8_BOUND_WINDOW_DAYS
    ) {
      return "snapshot quality C8 measures are not PASS";
    }
  }
  if (seenC8.size !== c8Datasets.length) {
    return "snapshot quality C8 measures are incomplete";
  }
  if (
    quality.b0_status !== "PASS" ||
    quality.b4_status !== "PASS" ||
    quality.c8_status !== "PASS"
  ) {
    return "snapshot quality B0/B4/C8 is not PASS";
  }
  return null;
}

export function pinReceiptNativeSource(
  source: Record<string, unknown>,
  environment: string,
): string | null {
  if (environment !== "production" && environment !== "staging") {
    return "receipt-native source environment is not pinned";
  }
  if (source.environment !== environment) {
    return "receipt-native source environment does not match publication environment";
  }
  if (
    source.authority_instance_digest !==
      PINNED_RECEIPT_REGISTRY_SCOPE[environment].authority_instance_digest
  ) {
    return "receipt-native source authority pin mismatch";
  }
  return null;
}

export async function verifyReceiptNativeReadyPublication(
  document: unknown,
  snapshotId: string,
  environment: string,
  clock: { now(): number } = { now: () => Date.now() },
): Promise<
  { ok: true; publication: VerifiedReceiptNativePublication } | { ok: false; error: string }
> {
  if (!isRecord(document) || !closedShape(document, ENVELOPE_NATIVE_FIELDS) ||
      document.format !== CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT) {
    return { ok: false, error: "READY envelope shape is invalid" };
  }
  const keys = await loadPinnedReadyKeys(environment);
  if (keys.length === 0) return { ok: false, error: "CONTROLLED_AUTHORITY_UNPROVISIONED" };
  const active = keys.filter((key) => key.status === "active");
  if (active.length !== 1 && keys.filter((key) => keyUsableAt(key, clock.now())).length === 0) {
    return { ok: false, error: "CONTROLLED_AUTHORITY_UNPROVISIONED" };
  }
  if (
    document.identity !== CONTROLLED_PILOT_IDENTITY ||
    document.environment !== environment ||
    typeof document.job_id !== "string" ||
    !isSha256(document.admitted_native_digest)
  ) {
    return { ok: false, error: "READY envelope identity or environment is invalid" };
  }
  const physical = document.physical;
  const manifest = document.ready_manifest;
  const attestation = document.attestation;
  const dependencyScope = document.dependency_scope_evidence;
  const sessionScope = document.controlled_session_scope;
  if (!isRecord(physical) || !closedShape(physical, PHYSICAL_FIELDS) ||
      !isRecord(manifest) || !isRecord(attestation) ||
      !closedShape(attestation, ATTESTATION_NATIVE_FIELDS) ||
      !isRecord(dependencyScope) || !isRecord(sessionScope)) {
    return { ok: false, error: "READY attestation sidecar shape is invalid" };
  }
  const digest = String(physical.digest || "");
  const key = String(physical.key || "");
  const size = physical.size;
  const rawHex = digest.startsWith("sha256:") ? digest.slice("sha256:".length) : "";
  if (
    !isSha256(digest) ||
    digest === snapshotId ||
    typeof size !== "number" ||
    !Number.isSafeInteger(size) ||
    size < 1 ||
    key !== personalReceiptCandidatePhysicalKey(rawHex)
  ) {
    return { ok: false, error: "READY envelope physical snapshot identity is invalid" };
  }
  if (manifest.format !== READY_MANIFEST_V2_FORMAT) {
    return { ok: false, error: "embedded ReadyManifest is not receipt-native v2" };
  }
  const wire = receiptNativeV2WireError(manifest);
  if (wire) return { ok: false, error: wire };
  const binding = verifyControlledPilotBinding(manifest);
  if (binding) return { ok: false, error: binding };
  if (!isSha256(manifest.feature_generation) || !isSha256(manifest.catalog_generation)) {
    return { ok: false, error: "embedded ReadyManifest has missing proof digests" };
  }
  if (!isRecord(manifest.source)) {
    return { ok: false, error: "READY envelope source is missing" };
  }
  const pin = pinReceiptNativeSource(manifest.source, environment);
  if (pin) return { ok: false, error: pin };
  if (manifest.source.physical_digest !== digest) {
    return { ok: false, error: "READY envelope source physical digest mismatch" };
  }
  const expectedSnapshot = await receiptNativeSnapshotId(manifest.source);
  if (expectedSnapshot !== snapshotId || manifest.snapshot_id !== snapshotId) {
    return { ok: false, error: "READY envelope snapshot_id does not match source" };
  }
  const manifestBody = { ...manifest };
  delete manifestBody.manifest_digest;
  const expectedManifestDigest = await sha256Digest(canonicalJson(manifestBody));
  if (!isSha256(manifest.manifest_digest) || manifest.manifest_digest !== expectedManifestDigest) {
    return { ok: false, error: "embedded ReadyManifest digest is invalid" };
  }
  const created = parseCanonicalUtc(manifest.created_at);
  const published = parseCanonicalUtc(manifest.published_at);
  if (!Number.isFinite(created) || !Number.isFinite(published) || published < created) {
    return { ok: false, error: "embedded ReadyManifest timestamps are time-incoherent" };
  }
  if (
    attestation.format !== READINESS_ATTESTATION_FORMAT ||
    attestation.identity !== CONTROLLED_PILOT_IDENTITY ||
    attestation.readiness_scope !== "PILOT" ||
    attestation.ready_state !== "READY" ||
    attestation.environment !== environment ||
    attestation.authority_instance_id !== `ready-authority/${environment}/v1` ||
    attestation.snapshot_id !== snapshotId ||
    attestation.immutable_db_digest !== digest ||
    attestation.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST ||
    attestation.issuer !== "ReadyPublicationService/v3"
  ) {
    return { ok: false, error: "READY attestation identity or artifact binding is invalid" };
  }
  if (
    ATTESTATION_NATIVE_MANIFEST_PAIRS.some(
      ([attestationField, manifestField]) =>
        !jsonEqual(attestation[attestationField], manifest[manifestField]),
    )
  ) {
    return { ok: false, error: "READY attestation does not bind the embedded ReadyManifest" };
  }
  if (ATTESTATION_NATIVE_DIGEST_FIELDS.some((field) => !isSha256(attestation[field]))) {
    return { ok: false, error: "READY attestation has missing proof digests" };
  }
  if (
    dependencyScope.profile_digest !== manifest.profile_digest ||
    dependencyScope.plan_set_digest !== manifest.plan_set_digest ||
    dependencyScope.dependency_closure_digest !== manifest.dependency_closure_digest ||
    dependencyScope.universe_rule_digest !== manifest.universe_rule_digest ||
    dependencyScope.resolved_universe_digest !== manifest.resolved_universe_digest
  ) {
    return { ok: false, error: "READY dependency scope does not bind the native manifest" };
  }
  const periodError = verifyReceiptNativePeriod(
    dependencyScope.period_start,
    dependencyScope.period_end,
  );
  if (periodError) {
    return { ok: false, error: `READY dependency scope ${periodError}` };
  }
  const expectedAuthority = await sha256Digest(
    canonicalJson({
      format: "ready-authority-resource/receipt-native/v1",
      environment,
      authority_instance_id: `ready-authority/${environment}/v1`,
      job_id: document.job_id,
      snapshot_id: snapshotId,
      immutable_db_digest: digest,
      unsigned_native_digest: document.admitted_native_digest,
      compiled_scope_proof_digest: dependencyScope.proof_digest,
    }),
  );
  if (attestation.authority_resource_digest !== expectedAuthority) {
    return { ok: false, error: "READY attestation authority resource digest is invalid" };
  }
  if (attestation.attestation_id !== `ready-${expectedAuthority.slice("sha256:".length)}`) {
    return { ok: false, error: "READY attestation content identity is invalid" };
  }
  const expectedEvidence = await sha256Digest(
    canonicalJson({ manifest, immutable_db_digest: digest }),
  );
  if (attestation.evidence_digest !== expectedEvidence) {
    return { ok: false, error: "READY attestation evidence digest is invalid" };
  }
  const derived = await deriveReceiptNativeSessionScope(
    dependencyScope,
    digest,
    String(manifest.source.observed_through),
  );
  if (!derived || !jsonEqual(sessionScope, derived)) {
    return { ok: false, error: "READY controlled session scope does not match dependency proof" };
  }
  if (
    !isRecord(manifest.pit_contract_digests) ||
    manifest.pit_contract_digests.dependency_scope !== derived.dependency_scope_proof_digest ||
    manifest.source.compiled_scope_proof_digest !== derived.dependency_scope_proof_digest ||
    dependencyScope.proof_digest !== derived.dependency_scope_proof_digest
  ) {
    return { ok: false, error: "READY dependency scope digest is invalid" };
  }
  const verifiedAt = parseCanonicalUtc(attestation.verified_at);
  const expires = parseCanonicalUtc(attestation.expires_at);
  const ttl = expires - verifiedAt;
  const now = clock.now();
  if (
    !Number.isFinite(verifiedAt) ||
    !Number.isFinite(expires) ||
    expires < verifiedAt ||
    ttl < MIN_TTL_MS ||
    ttl > MAX_TTL_MS ||
    published > verifiedAt ||
    verifiedAt > now + FIVE_MINUTES_MS ||
    now > expires
  ) {
    return { ok: false, error: "READY attestation is expired or time-incoherent" };
  }
  const keyRow = keys.find((item) => item.key_id === String(attestation.key_id || ""));
  if (!keyRow) return { ok: false, error: "READY attestation issuer is not trusted" };
  if (keyRow.environment && keyRow.environment !== environment) {
    return { ok: false, error: "READY key environment denied" };
  }
  if (!keyUsableAt(keyRow, verifiedAt)) {
    return { ok: false, error: "READY key window denied" };
  }
  const signature = decodeSignature(attestation.signature);
  if (!signature) return { ok: false, error: "READY attestation signature is invalid" };
  const body = { ...attestation };
  delete body.signature;
  if (!(await verifyEd25519(keyRow.public_key, signature, new TextEncoder().encode(canonicalJson(body))))) {
    return { ok: false, error: "READY attestation signature is invalid" };
  }
  return {
    ok: true,
    publication: {
      format: CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT,
      job_id: String(document.job_id),
      attestation_id: String(attestation.attestation_id),
      snapshot_id: snapshotId,
      immutable_db_digest: digest,
      physical: { key, digest, size },
      admitted_native_digest: String(document.admitted_native_digest),
      ready_manifest_digest: String(attestation.ready_manifest_digest),
      identity: CONTROLLED_PILOT_IDENTITY,
      environment,
      session_scope: structuredClone(derived),
      envelope: document,
    },
  };
}
