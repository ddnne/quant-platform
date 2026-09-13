import { canonicalJson, isRecord, sha256Digest } from "./controlled_pilot_json";

export const READY_MANIFEST_V2_FORMAT = "ready-manifest/v2";
const RECEIPT_NATIVE_SOURCE_KIND = "governed-receipt-candidate";
const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const D1_CURSOR_FIELDS = [
  "source_generation",
  "applied_sync_generation",
  "export_cursor",
  "applied_cursor",
] as const;

const READY_MANIFEST_V2_FIELDS = new Set([
  "format", "snapshot_id", "publication_scope", "profile_id", "profile_version", "profile_digest",
  "plan_ids", "plan_set_digest", "dependency_closure_digest", "universe_rule_digest",
  "resolved_universe_digest", "dataset_ids", "dataset_membership_digest", "coverage_policy_version",
  "coverage_policy_digest", "coverage_proof_digest", "raw_proof_digest", "receipt_proof_digest",
  "validation_proof_digest", "b0_proof_digest", "b4_proof_digest", "source", "pit_contract_digests",
  "feature_generation", "catalog_generation", "created_at", "published_at", "identity",
  "fill_contract_digest", "manifest_digest",
]);

const RECEIPT_NATIVE_SOURCE_FIELDS = new Set([
  "kind", "environment", "authority_instance_digest", "physical_digest",
  "observation_policy", "observed_through", "compiled_scope_proof_digest",
  "receipt_runset_digest",
]);

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_RE.test(value);
}

function isProofOrMissing(value: unknown): boolean {
  return value === "MISSING" || value === "UNKNOWN" || isSha256(value);
}

function closedUniqueStringArray(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string" || !item || seen.has(item)) return false;
    seen.add(item);
  }
  return true;
}

export function receiptNativeV2WireError(
  manifest: Record<string, unknown>,
): string | null {
  for (const field of D1_CURSOR_FIELDS) {
    if (field in manifest) {
      return "receipt-native ReadyManifest forbids D1 cursor fields";
    }
  }
  const keys = Object.keys(manifest);
  if (
    keys.length !== READY_MANIFEST_V2_FIELDS.size ||
    keys.some((key) => !READY_MANIFEST_V2_FIELDS.has(key))
  ) {
    return "ReadyManifest v2 fields are not closed";
  }
  if (manifest.format !== READY_MANIFEST_V2_FORMAT) {
    return "ReadyManifest format is invalid";
  }
  if (manifest.publication_scope !== "PILOT" && manifest.publication_scope !== "MASS") {
    return "ReadyManifest publication_scope is invalid";
  }
  for (const field of [
    "identity",
    "profile_id",
    "profile_version",
    "coverage_policy_version",
  ]) {
    if (typeof manifest[field] !== "string" || !manifest[field]) {
      return `ReadyManifest ${field} is invalid`;
    }
  }
  if (!closedUniqueStringArray(manifest.plan_ids)) {
    return "ReadyManifest plan_ids is invalid";
  }
  if (!closedUniqueStringArray(manifest.dataset_ids)) {
    return "ReadyManifest dataset_ids is invalid";
  }
  if (!isSha256(manifest.snapshot_id)) return "ReadyManifest snapshot_id mismatch";
  if (!isRecord(manifest.source)) return "receipt-native source is missing";
  const source = manifest.source;
  const sourceKeys = Object.keys(source);
  if (
    sourceKeys.length !== RECEIPT_NATIVE_SOURCE_FIELDS.size ||
    sourceKeys.some((key) => !RECEIPT_NATIVE_SOURCE_FIELDS.has(key))
  ) {
    return "receipt-native source fields are not closed";
  }
  if (source.kind !== RECEIPT_NATIVE_SOURCE_KIND) {
    return "receipt-native source kind is invalid";
  }
  if (source.environment !== "production" && source.environment !== "staging") {
    return "receipt-native source environment is not pinned";
  }
  if (source.observation_policy !== "max_verified_claims_checked_at") {
    return "receipt-native source observation policy is invalid";
  }
  if (typeof source.observed_through !== "string" || !source.observed_through) {
    return "receipt-native source observed_through is missing";
  }
  for (const field of [
    "authority_instance_digest",
    "physical_digest",
    "compiled_scope_proof_digest",
    "receipt_runset_digest",
  ]) {
    if (!isSha256(source[field])) {
      return `receipt-native source ${field} is not a digest`;
    }
  }
  const proofs = [
    "coverage_proof_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "validation_proof_digest",
    "b0_proof_digest",
    "b4_proof_digest",
    "resolved_universe_digest",
    "profile_digest",
    "plan_set_digest",
    "dependency_closure_digest",
    "universe_rule_digest",
    "dataset_membership_digest",
    "coverage_policy_digest",
    "fill_contract_digest",
  ];
  for (const field of proofs) {
    const value = manifest[field];
    if (value !== "MISSING" && value !== "UNKNOWN" && !isSha256(value)) {
      return `ReadyManifest ${field} is invalid`;
    }
  }
  if (
    !isRecord(manifest.pit_contract_digests) ||
    Object.keys(manifest.pit_contract_digests).length < 1
  ) {
    return "ReadyManifest pit_contract_digests missing";
  }
  for (const value of Object.values(manifest.pit_contract_digests)) {
    if (!isProofOrMissing(value)) {
      return "ReadyManifest pit_contract_digests missing";
    }
  }
  for (const field of ["feature_generation", "catalog_generation"]) {
    if (typeof manifest[field] !== "string" || !manifest[field]) {
      return `ReadyManifest ${field} is invalid`;
    }
  }
  if (typeof manifest.created_at !== "string" || !manifest.created_at) {
    return "ReadyManifest created_at is invalid";
  }
  if (typeof manifest.published_at !== "string" || !manifest.published_at) {
    return "ReadyManifest published_at is invalid";
  }
  if (!isSha256(manifest.manifest_digest)) {
    return "ReadyManifest manifest_digest mismatch";
  }
  return null;
}

export async function receiptNativeManifestBodyDigest(
  manifest: Record<string, unknown>,
): Promise<string> {
  const unsigned: Record<string, unknown> = { ...manifest };
  delete unsigned.manifest_digest;
  return sha256Digest(canonicalJson(unsigned));
}

export async function receiptNativeSnapshotId(
  source: Record<string, unknown>,
): Promise<string> {
  return sha256Digest(canonicalJson({ source }));
}
