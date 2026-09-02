import type { GatewayRpc } from "../../research-ai-gateway/src/gateway_rpc";
import { putChildrenThenManifest, putJsonCreateOnly, serializedJsonBytes } from "./http";
import { json } from "./http_json";
import {
  CONTROLLED_CHILD_COUNT,
  CONTROLLED_FILL_CONTRACT_DIGEST,
  CONTROLLED_FILL_EXECUTION_MODE,
  CONTROLLED_JOB_KEY_PREFIX,
  CONTROLLED_MAX_GROSS_WEIGHT_PPM,
  CONTROLLED_PILOT_GENERATION,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_PILOT_MAX_PARALLEL,
  CONTROLLED_PILOT_PLAN_COUNT,
  CONTROLLED_READY_ENVELOPE_FORMAT,
  CONTROLLED_TRADER_BATCH_FORMAT,
  EXACT_FOUR_BINDING_DIGEST,
  EXACT_FOUR_BUDGET_SCOPE_DIGEST,
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_COVERAGE_POLICY_DIGEST,
  EXACT_FOUR_COVERAGE_POLICY_VERSION,
  EXACT_FOUR_DATASET_IDS,
  EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST,
  EXACT_FOUR_EXECUTION_LIMIT_SET_DIGEST,
  EXACT_FOUR_PLAN_BINDING_DIGESTS,
  EXACT_FOUR_PLAN_IDS,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_POLICY_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  EXACT_FOUR_PROFILE_ID,
  EXACT_FOUR_PROFILE_VERSION,
  EXACT_FOUR_STRATEGY_BY_PLAN,
  EXACT_FOUR_STRATEGY_SPEC_HASHES,
  EXACT_FOUR_STRATEGY_SPEC_VERSIONS,
  EXACT_FOUR_UNIVERSE_RULE_DIGEST,
  CONTROLLED_PILOT_RUNNER_VERSION,
  closedControlledPilotJobSpec,
  controlledCandidateManifestKey,
  controlledContainerTerminalKey,
  controlledExecutionStageKey,
  controlledJobPrefix,
  controlledPhysicalSnapshotKey,
  controlledPilotContainerName,
  controlledPilotExecutionId,
  controlledReadyKey,
  controlledTraderAuthorizationKey,
  parseControlledPilotRequest,
  type ControlledPhysicalSnapshot,
  type ControlledPilotJobSpec,
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
import { CONTROLLED_R2_HOST } from "./controlled_pilot_r2";
import { CONTROLLED_WRITER_R2_HOST } from "./controlled_pilot_container_r2";
import * as registries from "./controlled_pilot_registries";
import type { PinnedVerifyKey } from "./controlled_pilot_registries";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";
import type { ControlledSessionScope } from "./ops_projection_ready";

export {
  canonicalJson,
  EXACT_FOUR_BINDING_DIGEST,
  EXACT_FOUR_BUDGET_SCOPE_DIGEST,
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_DATASET_IDS,
  EXACT_FOUR_EXECUTION_LIMIT_SET_DIGEST,
  EXACT_FOUR_PLAN_BINDING_DIGESTS,
  EXACT_FOUR_PLAN_IDS,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_POLICY_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  EXACT_FOUR_PROFILE_ID,
  EXACT_FOUR_STRATEGY_BY_PLAN,
  EXACT_FOUR_STRATEGY_SPEC_HASHES,
};

const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const CONTROLLED_OUTBOUND_HANDLER = "controlledPilotSnapshot";
const CONTROLLED_WRITER_OUTBOUND_HANDLER = "controlledPilotWriter";
const MIN_TTL_MS = 60_000;
const MAX_TTL_MS = 86_400_000;
const STATE_MAX_BYTES = 16 * 1024;
const TERMINAL_MAX_BYTES = 64 * 1024;
const READY_AUTH_MAX_BYTES = 64 * 1024;
const STATE_UPLOAD_SKEW_MS = 30_000;
const FIVE_MINUTES_MS = 5 * 60_000;
const READY_MANIFEST_FORMAT = "ready-manifest/v1";
const READINESS_ATTESTATION_FORMAT = "verified-readiness-attestation/v1";
const POLL_INITIAL_MS = 50;
const POLL_MAX_MS = 1_000;
const POLL_DEADLINE_MS = 120_000;

export type VerifierClock = { now(): number };
const SYSTEM_CLOCK: VerifierClock = { now: () => Date.now() };

const MANIFEST_DIGEST_FIELDS = [
  "resolved_universe_digest",
  "dataset_membership_digest",
  "coverage_policy_digest",
  "coverage_proof_digest",
  "raw_proof_digest",
  "receipt_proof_digest",
  "validation_proof_digest",
  "b0_proof_digest",
  "b4_proof_digest",
  "feature_generation",
  "catalog_generation",
] as const;

const ATTESTATION_MANIFEST_PAIRS: ReadonlyArray<readonly [string, string]> = [
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
  ["source_generation", "source_generation"],
  ["export_cursor", "export_cursor"],
  ["applied_cursor", "applied_cursor"],
  ["fill_contract_digest", "fill_contract_digest"],
];

const ATTESTATION_DIGEST_FIELDS = [
  "snapshot_id",
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
  "authority_resource_digest",
  "signed_projection_document_digest",
  "fill_contract_digest",
] as const;

const ENVELOPE_FIELDS = new Set([
  "format", "identity", "environment", "attestation", "ready_manifest", "physical",
  "dependency_scope_evidence", "signed_projection_document", "controlled_session_scope",
]);
const PHYSICAL_FIELDS = new Set(["key", "digest", "size"]);
const CONTROLLED_SESSION_ENTRY_FIELDS = new Set([
  "dataset_id", "natural_key_count", "natural_key_digest",
  "product_artifact_digests", "product_artifact_set_digest",
]);
const DEPENDENCY_SCOPE_ENTRY_FIELDS = new Set([
  ...CONTROLLED_SESSION_ENTRY_FIELDS,
  "receipt_digests", "receipt_set_digest",
]);
const MANIFEST_FIELDS = new Set([
  "format", "snapshot_id", "publication_scope", "profile_id", "profile_version", "profile_digest",
  "plan_ids", "plan_set_digest", "dependency_closure_digest", "universe_rule_digest", "resolved_universe_digest",
  "dataset_ids", "dataset_membership_digest", "coverage_policy_version", "coverage_policy_digest",
  "coverage_proof_digest", "raw_proof_digest", "receipt_proof_digest", "validation_proof_digest",
  "b0_proof_digest", "b4_proof_digest", "source_generation", "applied_sync_generation", "export_cursor",
  "applied_cursor", "pit_contract_digests", "feature_generation", "catalog_generation", "created_at",
  "published_at", "identity", "fill_contract_digest", "observed_through", "manifest_digest",
]);
const ATTESTATION_FIELDS = [
  "format", "attestation_id", "environment", "authority_instance_id", "authority_resource_digest",
  "signed_projection_document_digest", "readiness_scope", "identity", "snapshot_id", "profile_id",
  "profile_version", "profile_digest", "plan_ids", "plan_set_digest", "dependency_closure_digest",
  "universe_rule_digest", "resolved_universe_digest", "dataset_ids", "ready_state", "ready_manifest_digest",
  "immutable_db_digest", "coverage_policy_version", "coverage_policy_digest", "coverage_proof_digest",
  "governed_membership_digest", "raw_proof_digest", "receipt_proof_digest", "validation_proof_digest",
  "b0_quality_proof_digest", "b4_quality_proof_digest", "source_generation", "export_cursor", "applied_cursor",
  "verified_at", "expires_at", "evidence_digest", "key_id", "signature", "issuer", "fill_contract_digest",
] as const;
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
const CHILD_KEYS = [
  ...EXACT_FOUR_PLAN_IDS.map((_, i) => `paper/${i + 1}.json`),
  ...EXACT_FOUR_PLAN_IDS.map((_, i) => `risk/${i + 1}.json`),
  "selection.json",
  "knowledge.json",
] as const;

function closedShape(value: Record<string, unknown>, fields: Set<string> | readonly string[]): boolean {
  const expected = fields instanceof Set ? fields : new Set(fields);
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function parseTime(value: unknown): number {
  return parseCanonicalUtc(value);
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

export type VerifiedControlledReady = {
  attestation_id: string;
  snapshot_id: string;
  immutable_db_digest: string;
  physical: ControlledPhysicalSnapshot;
  identity: string;
  profile_digest: string;
  plan_set_digest: string;
  dependency_closure_digest: string;
  ready_manifest_digest: string;
  fill_contract_digest: string;
  receipt_proof_digest: string;
  coverage_proof_digest: string;
  b0_quality_proof_digest: string;
  b4_quality_proof_digest: string;
  resolved_universe_digest: string;
  environment: string;
  signed_projection_document_digest: string;
  session_scope: ControlledSessionScope;
};

function jsonEqual(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_RE.test(value);
}

export async function verifyControlledReadyEnvelope(
  document: unknown,
  snapshotId: string,
  environment: string,
  keys: readonly PinnedVerifyKey[],
  clock: VerifierClock = SYSTEM_CLOCK,
): Promise<{ ok: true; value: VerifiedControlledReady } | { ok: false; error: string }> {
  if (!isRecord(document) || !closedShape(document, ENVELOPE_FIELDS)) {
    return { ok: false, error: "READY envelope shape is invalid" };
  }
  if (keys.length === 0) return { ok: false, error: "CONTROLLED_AUTHORITY_UNPROVISIONED" };
  if (keys.length !== 1) return { ok: false, error: "READY registry must have one ACTIVE key" };
  if (
    document.format !== CONTROLLED_READY_ENVELOPE_FORMAT ||
    document.identity !== CONTROLLED_PILOT_IDENTITY ||
    document.environment !== environment
  ) {
    return { ok: false, error: "READY envelope identity or environment is invalid" };
  }
  const physical = document.physical;
  const manifest = document.ready_manifest;
  const attestation = document.attestation;
  const signedProjection = document.signed_projection_document;
  const dependencyScope = document.dependency_scope_evidence;
  const sessionScope = document.controlled_session_scope;
  if (!isRecord(physical) || !closedShape(physical, PHYSICAL_FIELDS)) {
    return { ok: false, error: "READY envelope physical snapshot identity is invalid" };
  }
  if (!isRecord(manifest) || !closedShape(manifest, MANIFEST_FIELDS)) {
    return { ok: false, error: "embedded ReadyManifest shape is invalid" };
  }
  if (!isRecord(attestation) || !closedShape(attestation, ATTESTATION_FIELDS)) {
    return { ok: false, error: "READY attestation sidecar shape is invalid" };
  }
  if (!isRecord(signedProjection) || !isRecord(dependencyScope) ||
      !isRecord(sessionScope) ||
      !closedShape(sessionScope, new Set([
        "format", "dependency_scope_proof_digest", "physical_db_digest", "observed_through", "entries",
      ])) || sessionScope.format !== "controlled-session-scope/v1" ||
      !isSha256(sessionScope.dependency_scope_proof_digest) ||
      sessionScope.physical_db_digest !== physical.digest ||
      sessionScope.observed_through !== manifest.observed_through ||
      !Array.isArray(sessionScope.entries) ||
      sessionScope.entries.length !== EXACT_FOUR_DATASET_IDS.length) {
    return { ok: false, error: "READY signed projection/session scope is invalid" };
  }
  const digest = String(physical.digest || "");
  const key = String(physical.key || "");
  const size = physical.size;
  if (
    !isSha256(digest) ||
    digest === snapshotId ||
    typeof size !== "number" ||
    !Number.isSafeInteger(size) ||
    size < 1 ||
    key !== controlledPhysicalSnapshotKey(digest)
  ) {
    return { ok: false, error: "READY envelope physical snapshot identity is invalid" };
  }
  const manifestBody = { ...manifest };
  delete manifestBody.manifest_digest;
  const expectedManifestDigest = await sha256Digest(canonicalJson(manifestBody));
  if (!isSha256(manifest.manifest_digest) || manifest.manifest_digest !== expectedManifestDigest) {
    return { ok: false, error: "embedded ReadyManifest digest is invalid" };
  }
  if (
    manifest.format !== READY_MANIFEST_FORMAT ||
    manifest.identity !== CONTROLLED_PILOT_IDENTITY ||
    manifest.snapshot_id !== snapshotId ||
    manifest.publication_scope !== "PILOT" ||
    manifest.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST ||
    manifest.profile_id !== EXACT_FOUR_PROFILE_ID ||
    manifest.profile_version !== EXACT_FOUR_PROFILE_VERSION ||
    manifest.profile_digest !== EXACT_FOUR_PROFILE_DIGEST ||
    !jsonEqual(manifest.plan_ids, [...EXACT_FOUR_PLAN_IDS]) ||
    manifest.plan_set_digest !== EXACT_FOUR_PLAN_SET_DIGEST ||
    manifest.dependency_closure_digest !== EXACT_FOUR_CLOSURE_DIGEST ||
    manifest.universe_rule_digest !== EXACT_FOUR_UNIVERSE_RULE_DIGEST ||
    !jsonEqual(manifest.dataset_ids, [...EXACT_FOUR_DATASET_IDS]) ||
    manifest.coverage_policy_version !== EXACT_FOUR_COVERAGE_POLICY_VERSION ||
    manifest.coverage_policy_digest !== EXACT_FOUR_COVERAGE_POLICY_DIGEST ||
    manifest.dataset_membership_digest !== EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST
  ) {
    return { ok: false, error: "embedded ReadyManifest is not the canonical exact-four binding" };
  }
  if (MANIFEST_DIGEST_FIELDS.some((field) => !isSha256(manifest[field]))) {
    return { ok: false, error: "embedded ReadyManifest has missing proof digests" };
  }
  const membership = await sha256Digest(canonicalJson([...EXACT_FOUR_DATASET_IDS].sort()));
  if (manifest.dataset_membership_digest !== membership) {
    return { ok: false, error: "embedded ReadyManifest dataset membership digest is invalid" };
  }
  const pit = manifest.pit_contract_digests;
  if (
    !isRecord(pit) ||
    Object.keys(pit).length === 0 ||
    Object.entries(pit).some(([pitKey, value]) => typeof pitKey !== "string" || !isSha256(value))
  ) {
    return { ok: false, error: "embedded ReadyManifest PIT proof is invalid" };
  }
  const generations = [
    manifest.source_generation,
    manifest.applied_sync_generation,
    manifest.export_cursor,
    manifest.applied_cursor,
  ];
  if (
    generations.some((value) => typeof value !== "string" || !value) ||
    new Set(generations).size !== 1
  ) {
    return { ok: false, error: "embedded ReadyManifest generation/cursor chain is not current" };
  }
  const created = parseTime(manifest.created_at);
  const published = parseTime(manifest.published_at);
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
    attestation.issuer !== "ReadyPublicationService/v3" ||
    typeof attestation.attestation_id !== "string" ||
    !String(attestation.attestation_id).trim()
  ) {
    return { ok: false, error: "READY attestation identity or artifact binding is invalid" };
  }
  if (
    ATTESTATION_MANIFEST_PAIRS.some(
      ([attestationField, manifestField]) =>
        !jsonEqual(attestation[attestationField], manifest[manifestField]),
    )
  ) {
    return { ok: false, error: "READY attestation does not bind the embedded ReadyManifest" };
  }
  if (ATTESTATION_DIGEST_FIELDS.some((field) => !isSha256(attestation[field]))) {
    return { ok: false, error: "READY attestation has missing proof digests" };
  }
  if (
    !jsonEqual(attestation.plan_ids, [...EXACT_FOUR_PLAN_IDS]) ||
    !jsonEqual(attestation.dataset_ids, [...EXACT_FOUR_DATASET_IDS])
  ) {
    return { ok: false, error: "READY attestation exact-four membership is invalid" };
  }
  const expectedEvidence = await sha256Digest(
    canonicalJson({ manifest, immutable_db_digest: digest }),
  );
  if (attestation.evidence_digest !== expectedEvidence) {
    return { ok: false, error: "READY attestation evidence digest is invalid" };
  }
  const expectedAuthority = await sha256Digest(
    canonicalJson({
      format: "ready-authority-resource/v1",
      environment,
      authority_instance_id: `ready-authority/${environment}/v1`,
      snapshot_id: snapshotId,
      immutable_db_digest: digest,
      ready_manifest_digest: attestation.ready_manifest_digest,
      signed_projection_document_digest: attestation.signed_projection_document_digest,
    }),
  );
  if (attestation.authority_resource_digest !== expectedAuthority) {
    return { ok: false, error: "READY attestation authority resource digest is invalid" };
  }
  if (attestation.attestation_id !== `ready-${expectedAuthority.slice("sha256:".length)}`) {
    return { ok: false, error: "READY attestation content identity is invalid" };
  }
  if ((await sha256Digest(canonicalJson(signedProjection))) !==
      attestation.signed_projection_document_digest) {
    return { ok: false, error: "READY signed Ops Projection document digest is invalid" };
  }
  const dependencyScopeBody = { ...dependencyScope };
  const declaredDependencyScopeDigest = dependencyScopeBody.proof_digest;
  delete dependencyScopeBody.proof_digest;
  if (!isSha256(declaredDependencyScopeDigest) ||
      declaredDependencyScopeDigest !== sessionScope.dependency_scope_proof_digest ||
      (await sha256Digest(canonicalJson(dependencyScopeBody))) !== declaredDependencyScopeDigest ||
      dependencyScope.physical_db_digest !== digest ||
      !isRecord(manifest.pit_contract_digests) ||
      manifest.pit_contract_digests.dependency_scope !==
        sessionScope.dependency_scope_proof_digest) {
    return { ok: false, error: "READY dependency scope digest is invalid" };
  }
  const dependencyEntries = dependencyScope.entries;
  if (!Array.isArray(dependencyEntries) ||
      dependencyEntries.length !== EXACT_FOUR_DATASET_IDS.length) {
    return { ok: false, error: "READY dependency scope entries are invalid" };
  }
  const expectedSessionEntries: ControlledSessionScope["entries"] = [];
  for (const datasetId of EXACT_FOUR_DATASET_IDS) {
    const matches = dependencyEntries.filter(
      (entry) => isRecord(entry) && entry.dataset_id === datasetId,
    );
    if (matches.length !== 1) {
      return { ok: false, error: "READY dependency scope entries are invalid" };
    }
    const entry = matches[0]!;
    if (!closedShape(entry, DEPENDENCY_SCOPE_ENTRY_FIELDS) ||
        !Number.isSafeInteger(entry.natural_key_count) || Number(entry.natural_key_count) < 1 ||
        !isSha256(entry.natural_key_digest) || !Array.isArray(entry.receipt_digests) ||
        entry.receipt_digests.length < 1 ||
        entry.receipt_digests.some((value: unknown) => !isSha256(value)) ||
        new Set(entry.receipt_digests).size !== entry.receipt_digests.length ||
        !isSha256(entry.receipt_set_digest) ||
        entry.receipt_set_digest !== await sha256Digest(canonicalJson(entry.receipt_digests)) ||
        !Array.isArray(entry.product_artifact_digests) ||
        entry.product_artifact_digests.length < 1 ||
        entry.product_artifact_digests.some((value: unknown) => !isSha256(value)) ||
        new Set(entry.product_artifact_digests).size !== entry.product_artifact_digests.length ||
        !isSha256(entry.product_artifact_set_digest) ||
        entry.product_artifact_set_digest !==
          await sha256Digest(canonicalJson(entry.product_artifact_digests))) {
      return { ok: false, error: "READY dependency scope entries are invalid" };
    }
    expectedSessionEntries.push({
      dataset_id: datasetId,
      natural_key_count: Number(entry.natural_key_count),
      natural_key_digest: entry.natural_key_digest,
      product_artifact_digests: [...entry.product_artifact_digests] as string[],
      product_artifact_set_digest: entry.product_artifact_set_digest,
    });
  }
  for (const entry of sessionScope.entries) {
    if (!isRecord(entry) || !closedShape(entry, CONTROLLED_SESSION_ENTRY_FIELDS) ||
      !Number.isSafeInteger(entry.natural_key_count) || Number(entry.natural_key_count) < 1 ||
      !isSha256(entry.natural_key_digest) || !Array.isArray(entry.product_artifact_digests) ||
      entry.product_artifact_digests.length < 1 ||
      entry.product_artifact_digests.some((value) => !isSha256(value)) ||
      new Set(entry.product_artifact_digests).size !== entry.product_artifact_digests.length ||
      !isSha256(entry.product_artifact_set_digest) ||
      entry.product_artifact_set_digest !== await sha256Digest(canonicalJson(entry.product_artifact_digests))) {
      return { ok: false, error: "READY controlled session scope entry is invalid" };
    }
  }
  if (!jsonEqual(sessionScope.entries, expectedSessionEntries)) {
    return { ok: false, error: "READY controlled session scope does not match dependency proof" };
  }
  const verifiedAt = parseTime(attestation.verified_at);
  const expires = parseTime(attestation.expires_at);
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
  if (keyRow.not_before && !registries.keyUsableAt(keyRow, verifiedAt)) {
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
    value: {
      attestation_id: String(attestation.attestation_id),
      snapshot_id: snapshotId,
      immutable_db_digest: digest,
      physical: { key, digest, size },
      identity: CONTROLLED_PILOT_IDENTITY,
      profile_digest: String(attestation.profile_digest),
      plan_set_digest: String(attestation.plan_set_digest),
      dependency_closure_digest: String(attestation.dependency_closure_digest),
      ready_manifest_digest: String(attestation.ready_manifest_digest),
      fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
      receipt_proof_digest: String(attestation.receipt_proof_digest),
      coverage_proof_digest: String(attestation.coverage_proof_digest),
      b0_quality_proof_digest: String(attestation.b0_quality_proof_digest),
      b4_quality_proof_digest: String(attestation.b4_quality_proof_digest),
      resolved_universe_digest: String(attestation.resolved_universe_digest),
      environment,
      signed_projection_document_digest: String(attestation.signed_projection_document_digest),
      session_scope: structuredClone(sessionScope) as ControlledSessionScope,
    },
  };
}

export async function verifyControlledReadyEnvelopeBytes(
  bytes: Uint8Array,
  snapshotId: string,
  environment: string,
  keys: readonly PinnedVerifyKey[],
  clock: VerifierClock = SYSTEM_CLOCK,
): Promise<{ ok: true; value: VerifiedControlledReady } | { ok: false; error: string }> {
  try {
    return await verifyControlledReadyEnvelope(
      decodeStrictJson(bytes),
      snapshotId,
      environment,
      keys,
      clock,
    );
  } catch (error) {
    const detail = error instanceof StrictJsonError ? error.message : "READY JSON is invalid";
    return { ok: false, error: detail };
  }
}

export async function verifyTraderAuthorizationBatch(
  document: unknown,
  request: ControlledPilotRequest,
  ready: VerifiedControlledReady,
  requestDigest: string,
  keys: readonly PinnedVerifyKey[],
  clock: VerifierClock = SYSTEM_CLOCK,
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
  if (traderKey.not_before && !registries.keyUsableAt(traderKey, issuedAt)) {
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
      raw.strategy_spec_hash !== EXACT_FOUR_STRATEGY_SPEC_HASHES[strategyId] ||
      raw.plan_binding_digest !== EXACT_FOUR_PLAN_BINDING_DIGESTS[expectedPlan]
    ) {
      return { ok: false, error: "trader authorization plan sequence is not the canonical ordered four" };
    }
  }
  const issued = parseTime(document.issued_at);
  const expires = parseTime(document.expires_at);
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
  ready: VerifiedControlledReady,
  requestDigest: string,
  keys: readonly PinnedVerifyKey[],
  clock: VerifierClock = SYSTEM_CLOCK,
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

async function requestDigest(request: ControlledPilotRequest): Promise<string> {
  return sha256Digest(
    canonicalJson({
      identity: CONTROLLED_PILOT_IDENTITY,
      idempotency_key: request.idempotency_key,
      ready_attestation_id: request.ready_attestation_id,
      snapshot_id: request.snapshot_id,
    }),
  );
}

function gatewayBody(rpc: { http_status: number; body: unknown }): Record<string, unknown> {
  return isRecord(rpc.body) ? rpc.body : {};
}

function budgetAccepted(rpc: { http_status: number; body: unknown }): boolean {
  return rpc.http_status < 300 && gatewayBody(rpc).ok === true;
}

function budgetRetryable(rpc: { http_status: number; body: unknown }): boolean {
  return rpc.http_status >= 500 || rpc.http_status === 429;
}

function budgetFailure(rpc: { http_status: number; body: unknown }, operation: string): string {
  const error = String(gatewayBody(rpc).error || "rejected").slice(0, 256);
  return `controlled budget ${operation} rejected (${rpc.http_status}): ${error}`;
}

async function loadJsonObject(
  bucket: R2Bucket,
  key: string,
  maxBytes = TERMINAL_MAX_BYTES,
): Promise<Record<string, unknown> | null> {
  const object = await bucket.get(key);
  if (!object || object.size > maxBytes) return null;
  try {
    const parsed: unknown = await object.json();
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

async function loadJsonObjectWithUploaded(
  bucket: R2Bucket,
  key: string,
  maxBytes: number,
): Promise<{ value: Record<string, unknown>; uploadedAt: number } | null> {
  const object = await bucket.get(key);
  if (!object || object.size > maxBytes) return null;
  const uploadedAt = object.uploaded instanceof Date ? object.uploaded.getTime() : Number.NaN;
  if (!Number.isFinite(uploadedAt)) return null;
  try {
    const parsed: unknown = await object.json();
    return isRecord(parsed) ? { value: parsed, uploadedAt } : null;
  } catch {
    return null;
  }
}

async function loadBytes(
  bucket: R2Bucket,
  key: string,
  maxBytes = READY_AUTH_MAX_BYTES,
): Promise<Uint8Array | null> {
  const object = await bucket.get(key);
  if (!object || object.size > maxBytes) return null;
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (bytes.byteLength > maxBytes) return null;
  return bytes;
}

async function digestObject(bucket: R2Bucket, key: string): Promise<string | null> {
  const bytes = await loadBytes(bucket, key);
  if (!bytes) return null;
  return sha256Digest(bytes);
}

type BoundContainer = {
  fetch: (request: Request) => Promise<Response>;
  setOutboundByHost: (
    hostname: string,
    method: string,
    params: unknown,
  ) => Promise<void>;
  setOutboundByHosts: (handlers: Record<string, never>) => Promise<void>;
};

async function bindPhysicalOutbound(
  env: Env,
  containerName: string,
  physical: ControlledPhysicalSnapshot,
  writer: { job_id: string; request_digest: string },
): Promise<BoundContainer> {
  const target = (await verifiedPersonalResearchContainer(env, containerName)) as BoundContainer;
  if (typeof target.setOutboundByHost !== "function" || typeof target.setOutboundByHosts !== "function") {
    throw new Error("controlled container outbound policy is unavailable");
  }
  await target.setOutboundByHost(CONTROLLED_R2_HOST, CONTROLLED_OUTBOUND_HANDLER, physical);
  try {
    await target.setOutboundByHost(
      CONTROLLED_WRITER_R2_HOST,
      CONTROLLED_WRITER_OUTBOUND_HANDLER,
      writer,
    );
  } catch (error) {
    await target.setOutboundByHosts({});
    throw error;
  }
  return target;
}

async function unbindPhysicalOutbound(target: BoundContainer | null): Promise<void> {
  if (!target) return;
  await target.setOutboundByHosts({});
}

async function releaseControlledOutbound(env: Env, jobId: string): Promise<void> {
  if (!env.PERSONAL_RESEARCH_CONTAINER) return;
  const containerName = await controlledPilotContainerName(jobId);
  const target = env.PERSONAL_RESEARCH_CONTAINER.getByName(containerName) as unknown as BoundContainer;
  if (typeof target.setOutboundByHosts !== "function") {
    throw new Error("controlled container outbound policy is unavailable");
  }
  await unbindPhysicalOutbound(target);
}

async function invokeBudget(
  gateway: GatewayRpc,
  method: "reserveControlledPaper" | "finalizeControlledPaper" | "cancelControlledPaper" | "heartbeatControlledPaper" | "queryControlledPaper",
  input: { idempotency_key: string; request_digest: string; lease_id?: string },
): Promise<{ http_status: number; body: unknown }> {
  switch (method) {
    case "reserveControlledPaper":
      return gateway.reserveControlledPaper(input);
    case "finalizeControlledPaper":
      return gateway.finalizeControlledPaper(input);
    case "cancelControlledPaper":
      return gateway.cancelControlledPaper(input);
    case "heartbeatControlledPaper":
      return gateway.heartbeatControlledPaper(input);
    case "queryControlledPaper":
      return gateway.queryControlledPaper(input);
    default: {
      const exhaustive: never = method;
      throw new Error(`budget method ${String(exhaustive)} is not on GatewayRpc`);
    }
  }
}

function childOrder(prefix: string): Array<{ key: string; kind: string; plan_id?: string }> {
  const rows: Array<{ key: string; kind: string; plan_id?: string }> = [];
  for (let index = 0; index < 4; index += 1) {
    rows.push({
      key: `${prefix}/paper/${index + 1}.json`,
      kind: "paper",
      plan_id: EXACT_FOUR_PLAN_IDS[index],
    });
  }
  for (let index = 0; index < 4; index += 1) {
    rows.push({
      key: `${prefix}/risk/${index + 1}.json`,
      kind: "risk",
      plan_id: EXACT_FOUR_PLAN_IDS[index],
    });
  }
  rows.push({ key: `${prefix}/selection.json`, kind: "selection" });
  rows.push({ key: `${prefix}/knowledge.json`, kind: "knowledge" });
  return rows;
}

type ControlledArtifactKind = "paper" | "risk" | "selection" | "knowledge";

type VerifiedSemanticArtifact = {
  kind: ControlledArtifactKind;
  body: Record<string, unknown>;
  semanticDigest: string;
  artifactId?: string;
};

type VerifiedContainerSemantics = {
  papers: VerifiedSemanticArtifact[];
  risks: VerifiedSemanticArtifact[];
  selection: VerifiedSemanticArtifact;
  knowledge: VerifiedSemanticArtifact;
};

const PAPER_SEMANTIC_FIELDS = new Set([
  "ordinal", "plan_id", "plan_binding_digest", "identity", "kind",
  "automatic_promotion", "live_orders_enabled", "mass", "snapshot_id",
  "immutable_db_digest", "snapshot_key", "snapshot_size", "authorization_digest",
  "ready_attestation_id", "fill_contract_digest", "execution_mode",
  "strategy_spec_id", "strategy_spec_hash", "strategy_spec_version", "profile_digest",
  "plan_set_digest", "dependency_closure_digest", "exact_four_binding_digest",
  "feature_refs", "lifecycle", "experiment_id", "run_id", "metrics",
  "n_equity_points", "n_trades", "resolved_universe_digest", "max_gross_weight_ppm",
  "requested_gross_weight", "realized_gross_weight", "reproducibility", "price_basis",
]);
const RISK_SEMANTIC_FIELDS = new Set([
  "ordinal", "plan_id", "plan_binding_digest", "strategy_spec_id",
  "strategy_spec_version", "strategy_spec_hash", "identity", "kind",
  "automatic_promotion", "live_orders_enabled", "mass", "snapshot_id",
  "immutable_db_digest", "snapshot_key", "snapshot_size", "authorization_digest",
  "ready_attestation_id", "fill_contract_digest", "profile_digest", "plan_set_digest",
  "dependency_closure_digest", "exact_four_binding_digest", "paper_semantic_digest",
  "audit_id", "experiment_id", "run_id", "status", "checks", "findings", "metrics",
]);
const SELECTION_SEMANTIC_FIELDS = new Set([
  "identity", "kind", "automatic_promotion", "live_orders_enabled", "mass",
  "snapshot_id", "immutable_db_digest", "fill_contract_digest", "decision", "rule",
  "selected", "rejected", "decisions", "paper_semantic_digests",
  "risk_semantic_digests", "semantic_child_set_digest", "profile_digest",
  "plan_set_digest", "dependency_closure_digest", "exact_four_binding_digest",
  "snapshot_key", "snapshot_size", "authorization_digest", "ready_attestation_id",
  "resolved_universe_digest",
]);
const KNOWLEDGE_SEMANTIC_FIELDS = new Set([
  "identity", "kind", "automatic_promotion", "live_orders_enabled", "mass",
  "snapshot_id", "immutable_db_digest", "fill_contract_digest", "selection_decision",
  "artifact_type", "schema_version", "producer_role", "selection_semantic_digest",
  "semantic_child_set_digest", "profile_digest", "plan_set_digest",
  "dependency_closure_digest", "exact_four_binding_digest", "snapshot_key",
  "snapshot_size", "authorization_digest", "n_papers", "n_selected", "payload",
]);
const PERSISTED_CHILD_FIELDS = new Set([
  "format", "identity", "kind", "semantic_body", "semantic_digest", "result_id",
  "bindings", "lineage",
]);

function assertClosedKeys(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
  label: string,
): void {
  const missing = [...allowed].filter(
    (key) => !Object.prototype.hasOwnProperty.call(value, key),
  );
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  if (missing.length > 0 || extra.length > 0) {
    lineageError(
      `${label} does not match its closed schema` +
      `${missing.length > 0 ? `; missing=${missing.join(",")}` : ""}` +
      `${extra.length > 0 ? `; extra=${extra.join(",")}` : ""}`,
    );
  }
}

async function semanticArtifact(
  kind: ControlledArtifactKind,
  payload: Record<string, unknown>,
): Promise<VerifiedSemanticArtifact> {
  const document = structuredClone(payload);
  const semanticDigest = String(document.semantic_digest || "");
  delete document.semantic_digest;
  let artifactId: string | undefined;
  if (kind === "knowledge") {
    artifactId = String(document.artifact_id || "");
    const digest = String(document.digest || "");
    delete document.artifact_id;
    delete document.digest;
    if (!isSha256(artifactId) || digest !== artifactId || semanticDigest !== artifactId) {
      lineageError("knowledge artifact_id/digest/semantic_digest are missing or inconsistent");
    }
  } else if (!isSha256(semanticDigest)) {
    lineageError(`${kind} semantic_digest is missing`);
  }
  const allowed = kind === "paper" ? PAPER_SEMANTIC_FIELDS
    : kind === "risk" ? RISK_SEMANTIC_FIELDS
      : kind === "selection" ? SELECTION_SEMANTIC_FIELDS
        : KNOWLEDGE_SEMANTIC_FIELDS;
  assertClosedKeys(document, allowed, `container ${kind}`);
  if ((await sha256Digest(canonicalJson(document))) !== semanticDigest) {
    lineageError(`${kind} semantic_digest is not canonical`);
  }
  return { kind, body: document, semanticDigest, ...(artifactId ? { artifactId } : {}) };
}

function lineageError(detail: string): never {
  throw new Error(detail);
}

function requirePlanLineage(
  row: Record<string, unknown>,
  index: number,
  kind: "paper" | "risk",
): void {
  const planId = EXACT_FOUR_PLAN_IDS[index]!;
  const strategyId = EXACT_FOUR_STRATEGY_BY_PLAN[planId];
  if (row.ordinal !== index + 1) lineageError(`${kind} ordinal is not canonical`);
  if (row.plan_id !== planId) lineageError(`${kind} plan_id is not canonical`);
  if (row.strategy_spec_id !== strategyId) lineageError(`${kind} StrategySpec id mismatch`);
  if (row.strategy_spec_version !== EXACT_FOUR_STRATEGY_SPEC_VERSIONS[planId]) {
    lineageError(`${kind} StrategySpec version mismatch`);
  }
  if (row.strategy_spec_hash !== EXACT_FOUR_STRATEGY_SPEC_HASHES[strategyId]) {
    lineageError(`${kind} StrategySpec hash mismatch`);
  }
  if (row.plan_binding_digest !== EXACT_FOUR_PLAN_BINDING_DIGESTS[planId]) {
    lineageError(`${kind} plan binding digest mismatch`);
  }
}

async function validateContainerArtifacts(
  artifacts: {
    papers: Record<string, unknown>[];
    risks: Record<string, unknown>[];
    selection: Record<string, unknown>;
    knowledge: Record<string, unknown>;
  },
  ready: VerifiedControlledReady,
): Promise<VerifiedContainerSemantics> {
  if (artifacts.papers.length !== 4 || artifacts.risks.length !== 4) {
    lineageError("controlled container did not return exactly four papers and risks");
  }
  const papers: VerifiedSemanticArtifact[] = [];
  const risks: VerifiedSemanticArtifact[] = [];
  for (let index = 0; index < 4; index += 1) {
    papers.push(await semanticArtifact("paper", artifacts.papers[index]!));
    risks.push(await semanticArtifact("risk", artifacts.risks[index]!));
  }
  const selection = await semanticArtifact("selection", artifacts.selection);
  const knowledge = await semanticArtifact("knowledge", artifacts.knowledge);
  const paperIds = papers.map((row) => String(row.body.plan_id || ""));
  const riskIds = risks.map((row) => String(row.body.plan_id || ""));
  if (new Set(paperIds).size !== 4 || new Set(riskIds).size !== 4) {
    lineageError("controlled container children are duplicated");
  }
  if (paperIds.join(",") !== EXACT_FOUR_PLAN_IDS.join(",") || riskIds.join(",") !== EXACT_FOUR_PLAN_IDS.join(",")) {
    lineageError("controlled container children are reordered or substituted");
  }
  const paperSemanticDigests: string[] = [];
  const riskSemanticDigests: string[] = [];
  for (let index = 0; index < 4; index += 1) {
    const paper = papers[index]!.body;
    const risk = risks[index]!.body;
    requirePlanLineage(paper, index, "paper");
    requirePlanLineage(risk, index, "risk");
    if (
      paper.snapshot_id !== ready.snapshot_id ||
      paper.immutable_db_digest !== ready.immutable_db_digest ||
      paper.snapshot_key !== ready.physical.key ||
      paper.snapshot_size !== ready.physical.size ||
      paper.ready_attestation_id !== ready.attestation_id ||
      paper.fill_contract_digest !== ready.fill_contract_digest ||
      paper.profile_digest !== ready.profile_digest ||
      paper.dependency_closure_digest !== ready.dependency_closure_digest ||
      paper.plan_set_digest !== ready.plan_set_digest ||
      paper.exact_four_binding_digest !== EXACT_FOUR_BINDING_DIGEST ||
      paper.resolved_universe_digest !== ready.resolved_universe_digest
    ) {
      lineageError("paper does not bind snapshot/profile/closure/binding digests");
    }
    if (
      risk.snapshot_id !== ready.snapshot_id ||
      risk.immutable_db_digest !== ready.immutable_db_digest ||
      risk.snapshot_key !== ready.physical.key ||
      risk.snapshot_size !== ready.physical.size ||
      risk.ready_attestation_id !== ready.attestation_id ||
      risk.fill_contract_digest !== ready.fill_contract_digest ||
      risk.profile_digest !== ready.profile_digest ||
      risk.dependency_closure_digest !== ready.dependency_closure_digest ||
      risk.plan_set_digest !== ready.plan_set_digest ||
      risk.exact_four_binding_digest !== EXACT_FOUR_BINDING_DIGEST
    ) {
      lineageError("risk does not bind snapshot/profile/closure/binding digests");
    }
    if (
      paper.identity !== CONTROLLED_PILOT_IDENTITY || paper.kind !== "paper" ||
      paper.lifecycle !== "Paper" || !isRecord(paper.metrics) ||
      paper.execution_mode !== CONTROLLED_FILL_EXECUTION_MODE || paper.price_basis !== "RAW" ||
      paper.automatic_promotion !== false || paper.live_orders_enabled !== false || paper.mass !== false
    ) {
      lineageError("paper semantic body violates the controlled Paper policy");
    }
    paperSemanticDigests.push(papers[index]!.semanticDigest);
    if (risk.paper_semantic_digest !== papers[index]!.semanticDigest) {
      lineageError("risk does not bind its paper semantic digest");
    }
    if (
      risk.identity !== CONTROLLED_PILOT_IDENTITY || risk.kind !== "risk" ||
      risk.automatic_promotion !== false || risk.live_orders_enabled !== false || risk.mass !== false
    ) {
      lineageError("risk semantic body violates the controlled Paper policy");
    }
    riskSemanticDigests.push(risks[index]!.semanticDigest);
  }
  const semanticChildSetDigest = await sha256Digest(canonicalJson({
    paper_semantic_digests: paperSemanticDigests,
    risk_semantic_digests: riskSemanticDigests,
  }));
  if (
    !jsonEqual(selection.body.paper_semantic_digests, paperSemanticDigests) ||
    !jsonEqual(selection.body.risk_semantic_digests, riskSemanticDigests) ||
    selection.body.semantic_child_set_digest !== semanticChildSetDigest
  ) {
    lineageError("selection does not bind the ordered semantic child set");
  }
  if (
    selection.body.identity !== CONTROLLED_PILOT_IDENTITY || selection.body.kind !== "selection" ||
    selection.body.decision !== "HOLD" || selection.body.automatic_promotion !== false ||
    selection.body.live_orders_enabled !== false || selection.body.mass !== false ||
    selection.body.snapshot_id !== ready.snapshot_id ||
    selection.body.immutable_db_digest !== ready.immutable_db_digest ||
    selection.body.snapshot_key !== ready.physical.key ||
    selection.body.snapshot_size !== ready.physical.size ||
    selection.body.ready_attestation_id !== ready.attestation_id ||
    selection.body.fill_contract_digest !== ready.fill_contract_digest ||
    selection.body.profile_digest !== ready.profile_digest ||
    selection.body.plan_set_digest !== ready.plan_set_digest ||
    selection.body.dependency_closure_digest !== ready.dependency_closure_digest ||
    selection.body.exact_four_binding_digest !== EXACT_FOUR_BINDING_DIGEST ||
    selection.body.resolved_universe_digest !== ready.resolved_universe_digest
  ) {
    lineageError("selection does not bind the controlled HOLD identity");
  }
  if (
    knowledge.body.identity !== CONTROLLED_PILOT_IDENTITY || knowledge.body.kind !== "knowledge" ||
    knowledge.body.selection_decision !== "HOLD" || knowledge.body.automatic_promotion !== false ||
    knowledge.body.live_orders_enabled !== false || knowledge.body.mass !== false ||
    knowledge.body.selection_semantic_digest !== selection.semanticDigest ||
    knowledge.body.semantic_child_set_digest !== semanticChildSetDigest ||
    knowledge.body.snapshot_id !== ready.snapshot_id ||
    knowledge.body.immutable_db_digest !== ready.immutable_db_digest ||
    knowledge.body.snapshot_key !== ready.physical.key ||
    knowledge.body.snapshot_size !== ready.physical.size ||
    knowledge.body.fill_contract_digest !== ready.fill_contract_digest ||
    knowledge.body.profile_digest !== ready.profile_digest ||
    knowledge.body.plan_set_digest !== ready.plan_set_digest ||
    knowledge.body.dependency_closure_digest !== ready.dependency_closure_digest ||
    knowledge.body.exact_four_binding_digest !== EXACT_FOUR_BINDING_DIGEST
  ) {
    lineageError("knowledge does not bind Selection and its semantic child set");
  }
  if (!isRecord(knowledge.body.payload)) {
    lineageError("knowledge payload is missing");
  }
  assertClosedKeys(knowledge.body.payload, new Set([
    "identity", "snapshot_id", "selection_decision", "paper_experiment_ids",
    "risk_audit_ids", "fill_contract_digest", "semantic_child_set_digest",
    "selection_semantic_digest",
  ]), "knowledge payload");
  if (
    knowledge.body.payload.identity !== CONTROLLED_PILOT_IDENTITY ||
    knowledge.body.payload.snapshot_id !== ready.snapshot_id ||
    knowledge.body.payload.selection_decision !== "HOLD" ||
    knowledge.body.payload.fill_contract_digest !== ready.fill_contract_digest ||
    !jsonEqual(
      knowledge.body.payload.paper_experiment_ids,
      papers.map((row) => row.body.experiment_id),
    ) ||
    !jsonEqual(
      knowledge.body.payload.risk_audit_ids,
      risks.map((row) => row.body.audit_id),
    ) ||
    knowledge.body.payload.selection_semantic_digest !== selection.semanticDigest ||
    knowledge.body.payload.semantic_child_set_digest !== semanticChildSetDigest
  ) {
    lineageError("knowledge payload does not bind the semantic chain");
  }
  return { papers, risks, selection, knowledge };
}

function persistedDocument(
  artifact: VerifiedSemanticArtifact,
  bindings: Record<string, unknown>,
  lineage: Record<string, unknown>,
): Record<string, unknown> {
  for (const [key, value] of Object.entries(bindings)) {
    if (artifact.body[key] !== undefined && !jsonEqual(artifact.body[key], value)) {
      lineageError(`container ${artifact.kind} rewrote ${key}`);
    }
  }
  return {
    format: "controlled-pilot-persisted-child/v2",
    identity: CONTROLLED_PILOT_IDENTITY,
    kind: artifact.kind,
    semantic_body: artifact.body,
    semantic_digest: artifact.semanticDigest,
    result_id: artifact.semanticDigest,
    bindings,
    lineage,
    ...(artifact.kind === "knowledge"
      ? { artifact_id: artifact.artifactId, digest: artifact.artifactId }
      : {}),
  };
}

type PersistedChildRef = {
  kind: ControlledArtifactKind;
  plan_id?: string;
  key: string;
  persisted_byte_digest: string;
  size: number;
};

class PersistedChildConflict extends Error {}

function controlledArtifactBindings(
  request: ControlledPilotRequest,
  ready: VerifiedControlledReady,
  authorizationDigest: string,
): Record<string, unknown> {
  return {
    authorization_digest: authorizationDigest,
    ready_attestation_id: ready.attestation_id,
    snapshot_id: ready.snapshot_id,
    immutable_db_digest: ready.immutable_db_digest,
    snapshot_key: ready.physical.key,
    snapshot_size: ready.physical.size,
    profile_digest: ready.profile_digest,
    plan_set_digest: ready.plan_set_digest,
    dependency_closure_digest: ready.dependency_closure_digest,
    ready_manifest_digest: ready.ready_manifest_digest,
    signed_projection_document_digest: ready.signed_projection_document_digest,
    session_scope: ready.session_scope,
    resolved_universe_digest: ready.resolved_universe_digest,
    universe_rule_digest: EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
    exact_four_binding_digest: EXACT_FOUR_BINDING_DIGEST,
    idempotency_key: request.idempotency_key,
    generation: CONTROLLED_PILOT_GENERATION,
    max_parallel: CONTROLLED_PILOT_MAX_PARALLEL,
    max_gross_weight_ppm: CONTROLLED_MAX_GROSS_WEIGHT_PPM,
    automatic_promotion: false,
    live_orders_enabled: false,
    mass: false,
  };
}

async function persistChild(
  bucket: R2Bucket,
  key: string,
  artifact: VerifiedSemanticArtifact,
  bindings: Record<string, unknown>,
  lineage: Record<string, unknown>,
  planId?: string,
): Promise<PersistedChildRef> {
  const document = persistedDocument(artifact, bindings, lineage);
  const bytes = serializedJsonBytes(document);
  const persistedByteDigest = await sha256Digest(bytes);
  const put = await putJsonCreateOnly(bucket, key, document);
  if (put.conflict || put.digest !== persistedByteDigest) {
    throw new PersistedChildConflict(`immutable ${artifact.kind} child conflicts`);
  }
  const readback = await digestObject(bucket, key);
  if (readback !== persistedByteDigest) {
    throw new PersistedChildConflict(`immutable ${artifact.kind} child readback failed`);
  }
  return {
    kind: artifact.kind,
    ...(planId ? { plan_id: planId } : {}),
    key,
    persisted_byte_digest: persistedByteDigest,
    size: bytes.byteLength,
  };
}

async function persistBoundChildren(
  bucket: R2Bucket,
  request: ControlledPilotRequest,
  ready: VerifiedControlledReady,
  authorizationDigest: string,
  artifacts: {
    papers: Record<string, unknown>[];
    risks: Record<string, unknown>[];
    selection: Record<string, unknown>;
    knowledge: Record<string, unknown>;
  },
  requestHash: string,
): Promise<{ ok: true; manifest: Record<string, unknown> } | { ok: false; conflict: boolean; error?: string }> {
  const prefix = controlledJobPrefix(request.idempotency_key);
  let verified: VerifiedContainerSemantics;
  try {
    verified = await validateContainerArtifacts(artifacts, ready);
  } catch (error) {
    return { ok: false, conflict: false, error: error instanceof Error ? error.message : "lineage" };
  }
  const bindings = controlledArtifactBindings(request, ready, authorizationDigest);
  // Close every semantic/body binding before the first immutable child write.
  // Lineage is added only after the referenced persisted bytes exist.
  try {
    for (const artifact of [
      ...verified.papers,
      ...verified.risks,
      verified.selection,
      verified.knowledge,
    ]) {
      persistedDocument(artifact, bindings, {});
    }
  } catch (error) {
    return {
      ok: false,
      conflict: false,
      error: error instanceof Error ? error.message : "container binding failure",
    };
  }
  const childRefs: PersistedChildRef[] = [];
  try {
    const paperRefs: PersistedChildRef[] = [];
    for (let index = 0; index < 4; index += 1) {
      const planId = EXACT_FOUR_PLAN_IDS[index]!;
      const ref = await persistChild(
        bucket, `${prefix}/paper/${index + 1}.json`, verified.papers[index]!, bindings, {}, planId,
      );
      paperRefs.push(ref);
      childRefs.push(ref);
    }
    const riskRefs: PersistedChildRef[] = [];
    for (let index = 0; index < 4; index += 1) {
      const planId = EXACT_FOUR_PLAN_IDS[index]!;
      const ref = await persistChild(
        bucket,
        `${prefix}/risk/${index + 1}.json`,
        verified.risks[index]!,
        bindings,
        {
          paper_semantic_digest: verified.papers[index]!.semanticDigest,
          paper_persisted_byte_digest: paperRefs[index]!.persisted_byte_digest,
        },
        planId,
      );
      riskRefs.push(ref);
      childRefs.push(ref);
    }
    const paperPersistedByteDigests = paperRefs.map((row) => row.persisted_byte_digest);
    const riskPersistedByteDigests = riskRefs.map((row) => row.persisted_byte_digest);
    const orderedChildSetDigest = await sha256Digest(canonicalJson({
      paper_persisted_byte_digests: paperPersistedByteDigests,
      risk_persisted_byte_digests: riskPersistedByteDigests,
    }));
    const selectionRef = await persistChild(
      bucket,
      `${prefix}/selection.json`,
      verified.selection,
      bindings,
      {
        paper_semantic_digests: verified.papers.map((row) => row.semanticDigest),
        risk_semantic_digests: verified.risks.map((row) => row.semanticDigest),
        paper_persisted_byte_digests: paperPersistedByteDigests,
        risk_persisted_byte_digests: riskPersistedByteDigests,
        ordered_child_set_digest: orderedChildSetDigest,
      },
    );
    childRefs.push(selectionRef);
    childRefs.push(await persistChild(
      bucket,
      `${prefix}/knowledge.json`,
      verified.knowledge,
      bindings,
      {
        selection_semantic_digest: verified.selection.semanticDigest,
        selection_persisted_byte_digest: selectionRef.persisted_byte_digest,
        ordered_child_set_digest: orderedChildSetDigest,
      },
    ));
  } catch (error) {
    return {
      ok: false,
      conflict: error instanceof PersistedChildConflict,
      error: error instanceof Error ? error.message : "persisted child failure",
    };
  }
  return {
    ok: true,
    manifest: {
      identity: CONTROLLED_PILOT_IDENTITY,
      format: "controlled-pilot-paper-bundle/v2",
      request_digest: requestHash,
      ...bindings,
      plan_ids: [...EXACT_FOUR_PLAN_IDS],
      children: childRefs,
    },
  };
}

function bindingsFromManifest(manifest: Record<string, unknown>): Record<string, unknown> {
  return {
    authorization_digest: manifest.authorization_digest,
    ready_attestation_id: manifest.ready_attestation_id,
    snapshot_id: manifest.snapshot_id,
    immutable_db_digest: manifest.immutable_db_digest,
    snapshot_key: manifest.snapshot_key,
    snapshot_size: manifest.snapshot_size,
    profile_digest: manifest.profile_digest,
    plan_set_digest: manifest.plan_set_digest,
    dependency_closure_digest: manifest.dependency_closure_digest,
    ready_manifest_digest: manifest.ready_manifest_digest,
    signed_projection_document_digest: manifest.signed_projection_document_digest,
    session_scope: manifest.session_scope,
    resolved_universe_digest: manifest.resolved_universe_digest,
    universe_rule_digest: manifest.universe_rule_digest,
    fill_contract_digest: manifest.fill_contract_digest,
    exact_four_binding_digest: manifest.exact_four_binding_digest,
    idempotency_key: manifest.idempotency_key,
    generation: manifest.generation,
    max_parallel: manifest.max_parallel,
    max_gross_weight_ppm: manifest.max_gross_weight_ppm,
    automatic_promotion: manifest.automatic_promotion,
    live_orders_enabled: manifest.live_orders_enabled,
    mass: manifest.mass,
  };
}

function restoredContainerArtifact(
  document: Record<string, unknown>,
  kind: ControlledArtifactKind,
  expectedBindings: Record<string, unknown>,
): { payload: Record<string, unknown>; lineage: Record<string, unknown> } {
  const allowed = new Set(PERSISTED_CHILD_FIELDS);
  if (kind === "knowledge") {
    allowed.add("artifact_id");
    allowed.add("digest");
  }
  if (
    Object.keys(document).length !== allowed.size ||
    [...allowed].some((field) => !(field in document))
  ) {
    lineageError(`persisted ${kind} child does not match its closed schema`);
  }
  assertClosedKeys(document, allowed, `persisted ${kind}`);
  if (
    document.format !== "controlled-pilot-persisted-child/v2" ||
    document.identity !== CONTROLLED_PILOT_IDENTITY ||
    document.kind !== kind ||
    !isRecord(document.semantic_body) ||
    !isRecord(document.bindings) ||
    !isRecord(document.lineage) ||
    !jsonEqual(document.bindings, expectedBindings)
  ) {
    lineageError(`persisted ${kind} identity or bindings are invalid`);
  }
  const semanticDigest = String(document.semantic_digest || "");
  if (
    !isSha256(semanticDigest) ||
    document.result_id !== semanticDigest ||
    (kind === "knowledge" &&
      (document.artifact_id !== semanticDigest || document.digest !== semanticDigest))
  ) {
    lineageError(`persisted ${kind} result identity is invalid`);
  }
  const payload: Record<string, unknown> = {
    ...document.semantic_body,
    semantic_digest: semanticDigest,
  };
  if (kind === "knowledge") {
    payload.artifact_id = document.artifact_id;
    payload.digest = document.digest;
  }
  return { payload, lineage: document.lineage };
}

async function reverifyManifest(
  bucket: R2Bucket,
  expectedJobId: string,
  expectedDigest: string,
  authority: ReverifiedControlledSubmission,
): Promise<boolean> {
  try {
    const manifest = await loadJsonObject(bucket, manifestKey(expectedJobId));
    const authoritativeBindings = controlledArtifactBindings(
      authority.state.request,
      authority.ready,
      authority.authorization_digest,
    );
    const manifestFields = new Set([
      "identity",
      "format",
      "request_digest",
      ...Object.keys(authoritativeBindings),
      "plan_ids",
      "children",
    ]);
    if (
      !manifest || !closedShape(manifest, manifestFields) ||
      manifest.format !== "controlled-pilot-paper-bundle/v2" ||
      manifest.request_digest !== expectedDigest || manifest.identity !== CONTROLLED_PILOT_IDENTITY ||
      authority.state.job_id !== expectedJobId ||
      authority.state.request_digest !== expectedDigest ||
      !jsonEqual(bindingsFromManifest(manifest), authoritativeBindings) ||
      !jsonEqual(manifest.plan_ids, [...EXACT_FOUR_PLAN_IDS])
    ) return false;
    const refs = manifest.children;
    const expected = childOrder(controlledJobPrefix(expectedJobId));
    if (!Array.isArray(refs) || refs.length !== CONTROLLED_CHILD_COUNT || refs.length !== expected.length) return false;
    const bindings = bindingsFromManifest(manifest);
    const restored: Array<{ payload: Record<string, unknown>; lineage: Record<string, unknown> }> = [];
    const persistedDigests: string[] = [];
    for (let index = 0; index < expected.length; index += 1) {
      const ref = refs[index];
      const want = expected[index]!;
      if (!isRecord(ref) || ref.key !== want.key || ref.kind !== want.kind) return false;
      if ((want.plan_id && ref.plan_id !== want.plan_id) || (!want.plan_id && ref.plan_id !== undefined)) return false;
      const persistedByteDigest = String(ref.persisted_byte_digest || "");
      if (!isSha256(persistedByteDigest) || !Number.isSafeInteger(ref.size) || Number(ref.size) < 1) return false;
      const head = await bucket.head(want.key);
      if (!head || head.size !== ref.size || await digestObject(bucket, want.key) !== persistedByteDigest) return false;
      const document = await loadJsonObject(bucket, want.key);
      if (!document) return false;
      restored.push(restoredContainerArtifact(document, want.kind as ControlledArtifactKind, bindings));
      persistedDigests.push(persistedByteDigest);
    }
    const container = {
      papers: restored.slice(0, 4).map((row) => row.payload),
      risks: restored.slice(4, 8).map((row) => row.payload),
      selection: restored[8]!.payload,
      knowledge: restored[9]!.payload,
    };
    const semantic = await validateContainerArtifacts(container, authority.ready);
    for (let index = 0; index < 4; index += 1) {
      if (Object.keys(restored[index]!.lineage).length !== 0) return false;
      if (!jsonEqual(restored[index + 4]!.lineage, {
        paper_semantic_digest: semantic.papers[index]!.semanticDigest,
        paper_persisted_byte_digest: persistedDigests[index],
      })) return false;
    }
    const paperPersistedByteDigests = persistedDigests.slice(0, 4);
    const riskPersistedByteDigests = persistedDigests.slice(4, 8);
    const orderedChildSetDigest = await sha256Digest(canonicalJson({
      paper_persisted_byte_digests: paperPersistedByteDigests,
      risk_persisted_byte_digests: riskPersistedByteDigests,
    }));
    if (!jsonEqual(restored[8]!.lineage, {
      paper_semantic_digests: semantic.papers.map((row) => row.semanticDigest),
      risk_semantic_digests: semantic.risks.map((row) => row.semanticDigest),
      paper_persisted_byte_digests: paperPersistedByteDigests,
      risk_persisted_byte_digests: riskPersistedByteDigests,
      ordered_child_set_digest: orderedChildSetDigest,
    })) return false;
    if (!jsonEqual(restored[9]!.lineage, {
      selection_semantic_digest: semantic.selection.semanticDigest,
      selection_persisted_byte_digest: persistedDigests[8],
      ordered_child_set_digest: orderedChildSetDigest,
    })) return false;
    return true;
  } catch {
    return false;
  }
}

type ContainerArtifacts = {
  papers: Record<string, unknown>[];
  risks: Record<string, unknown>[];
  selection: Record<string, unknown>;
  knowledge: Record<string, unknown>;
  cleaned: boolean;
};

async function callContainer(
  env: Env,
  spec: ControlledPilotJobSpec,
  containerName: string,
  options?: { skipPost?: boolean },
): Promise<
  | { ok: true; value: ContainerArtifacts; accepted: true }
  | { ok: false; error: string; timeout?: boolean; pending?: boolean; accepted?: boolean }
> {
  if (!env.PERSONAL_RESEARCH_CONTAINER) {
    return { ok: false, error: "controlled container unbound", pending: true };
  }
  let parsed: unknown = { accepted: true };
  if (!options?.skipPost) {
    let response: Response;
    try {
      const target = await verifiedPersonalResearchContainer(env, containerName);
      response = await target.fetch(
        new Request("http://container/v1/controlled-pilot", {
          method: "POST",
          headers: { "content-type": "application/json; charset=utf-8" },
          body: JSON.stringify(spec),
        }),
      );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      return { ok: false, error: detail, timeout: /timeout/i.test(detail), pending: true };
    }
    if (response.status !== 202) {
      return {
        ok: false,
        error: `controlled container POST must return 202, got ${response.status}`,
        pending: response.status >= 500,
      };
    }
    try {
      parsed = await response.json();
    } catch {
      return { ok: false, error: "controlled container returned invalid JSON", accepted: true };
    }
  }
  const jobId = spec.job_id;
  const terminal = await waitForContainerJob(env, containerName, jobId, parsed);
  if (!terminal.ok) {
    if (options?.skipPost && terminal.missing) {
      // A Container process restart loses its in-memory JobManager. Re-submit
      // the same closed spec so the persisted R2 lease can observe or take over.
      return callContainer(env, spec, containerName);
    }
    return { ...terminal, accepted: true };
  }
  parsed = terminal.value;
  if (!isRecord(parsed) || parsed.ok !== true) {
    return { ok: false, error: String(isRecord(parsed) ? parsed.error : "container_error") };
  }
  if (parsed.identity !== CONTROLLED_PILOT_IDENTITY) {
    return { ok: false, error: "controlled container identity mismatch" };
  }
  const papers = parsed.papers;
  const risks = parsed.risks;
  if (!Array.isArray(papers) || papers.length !== CONTROLLED_PILOT_PLAN_COUNT) {
    return { ok: false, error: "controlled container did not return exactly four papers" };
  }
  if (!Array.isArray(risks) || risks.length !== CONTROLLED_PILOT_PLAN_COUNT) {
    return { ok: false, error: "controlled container did not return exactly four risks" };
  }
  if (papers.some((row) => !isRecord(row)) || risks.some((row) => !isRecord(row))) {
    return { ok: false, error: "controlled container children must be objects" };
  }
  if (
    (papers as Record<string, unknown>[]).some(
      (row) =>
        row.lifecycle !== "Paper" ||
        !row.metrics ||
        row.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST ||
        row.execution_mode !== CONTROLLED_FILL_EXECUTION_MODE ||
        row.price_basis !== "RAW",
    )
  ) {
    return { ok: false, error: "controlled container did not return Paper evidence" };
  }
  if ((risks as Record<string, unknown>[]).some((row) => row.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST)) {
    return { ok: false, error: "controlled container risk evidence is missing" };
  }
  if (!isRecord(parsed.selection) || !isRecord(parsed.knowledge)) {
    return { ok: false, error: "controlled container selection/knowledge evidence is missing" };
  }
  if (parsed.selection.decision !== "HOLD" || parsed.selection.automatic_promotion === true) {
    return { ok: false, error: "automatic promotion is disabled" };
  }
  const value = {
    papers: papers as Record<string, unknown>[],
    risks: risks as Record<string, unknown>[],
    selection: parsed.selection,
    knowledge: parsed.knowledge,
    cleaned: parsed.ephemeral_cleaned === true,
  };
  try {
    await validateContainerArtifacts(value, {
      attestation_id: spec.ready_attestation_id,
      snapshot_id: spec.snapshot_id,
      immutable_db_digest: spec.immutable_db_digest,
      physical: { key: spec.snapshot_key, digest: spec.immutable_db_digest, size: spec.snapshot_size },
      identity: CONTROLLED_PILOT_IDENTITY,
      profile_digest: spec.profile_digest,
      plan_set_digest: spec.plan_set_digest,
      dependency_closure_digest: spec.dependency_closure_digest,
      ready_manifest_digest: "",
      fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
      receipt_proof_digest: "",
      coverage_proof_digest: "",
      b0_quality_proof_digest: "",
      b4_quality_proof_digest: "",
      resolved_universe_digest: spec.resolved_universe_digest,
      environment: "",
      signed_projection_document_digest: spec.signed_projection_document_digest,
      session_scope: spec.session_scope,
    });
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "child lineage is invalid" };
  }
  return { ok: true, value, accepted: true };
}

async function waitForContainerJob(
  env: Env,
  containerName: string,
  jobId: string,
  submitted: unknown,
): Promise<
  | { ok: true; value: unknown }
  | { ok: false; error: string; timeout?: boolean; pending?: boolean; missing?: boolean }
> {
  if (isRecord(submitted) && Array.isArray(submitted.papers)) {
    return { ok: false, error: "controlled container must accept with 202 and publish via GET" };
  }
  let status: Response;
  try {
    const target = await verifiedPersonalResearchContainer(env, containerName);
    status = await target.fetch(new Request(`http://container/v1/jobs/${jobId}`));
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "controlled container status unavailable",
      pending: true,
    };
  }
  let parsed: unknown;
  try {
    parsed = await status.json();
  } catch {
    return { ok: false, error: "controlled container status is invalid" };
  }
  const job = isRecord(parsed) && isRecord(parsed.job) ? parsed.job : parsed;
  if (status.status === 404 && isRecord(job) && job.error === "job_not_found") {
    return { ok: false, error: "controlled container job is missing", pending: true, missing: true };
  }
  if (isRecord(job) && job.status === "COMPLETED" && job.ok === true) {
    return { ok: true, value: job };
  }
  if (
    isRecord(job) &&
    (job.status === "FAILED" || job.ok === false) &&
    job.status !== "QUEUED" &&
    job.status !== "RUNNING" &&
    job.status !== "SUBMITTED"
  ) {
    return { ok: false, error: String(job.error || "controlled_execution_failed") };
  }
  return { ok: false, error: "controlled container still running", pending: true };
}

function stateKey(jobId: string): string {
  return `${CONTROLLED_JOB_KEY_PREFIX}${jobId}/state.json`;
}
function reservationKey(jobId: string): string {
  return `${CONTROLLED_JOB_KEY_PREFIX}${jobId}/reservation.json`;
}
function pendingKey(jobId: string): string {
  return `${CONTROLLED_JOB_KEY_PREFIX}${jobId}/pending.json`;
}
function failureKey(jobId: string): string {
  return `${CONTROLLED_JOB_KEY_PREFIX}${jobId}/failed.json`;
}
function manifestKey(jobId: string): string {
  return `${controlledJobPrefix(jobId)}/manifest.json`;
}

const SUBMITTED_STATE_FIELDS = new Set([
  "identity", "status", "job_id", "request_digest", "submitted_at",
  "admission", "spec", "ready", "request", "go", "automatic_promotion",
  "live_orders_enabled", "mass",
]);
const ADMISSION_STATE_FIELDS = new Set([
  "verified_at", "ready_key_id", "trader_key_id",
]);
const FAILURE_FIELDS = new Set([
  "identity", "status", "job_id", "request_digest", "error", "go",
  "automatic_promotion", "live_orders_enabled", "mass",
]);
const VERIFIED_READY_STATE_FIELDS = new Set([
  "attestation_id", "snapshot_id", "immutable_db_digest", "physical", "identity",
  "profile_digest", "plan_set_digest", "dependency_closure_digest",
  "ready_manifest_digest", "fill_contract_digest", "receipt_proof_digest",
  "coverage_proof_digest", "b0_quality_proof_digest", "b4_quality_proof_digest",
  "resolved_universe_digest", "environment", "signed_projection_document_digest",
  "session_scope",
]);

type ControlledPilotSubmittedState = {
  identity: typeof CONTROLLED_PILOT_IDENTITY;
  status: "SUBMITTED";
  job_id: string;
  request_digest: string;
  submitted_at: string;
  admission: {
    verified_at: string;
    ready_key_id: string;
    trader_key_id: string;
  };
  spec: ControlledPilotJobSpec;
  ready: VerifiedControlledReady;
  request: ControlledPilotRequest;
  go: false;
  automatic_promotion: false;
  live_orders_enabled: false;
  mass: false;
};

type ReverifiedControlledSubmission = {
  state: ControlledPilotSubmittedState;
  ready: VerifiedControlledReady;
  authorization_digest: string;
};

type ControlledFailure = {
  identity: typeof CONTROLLED_PILOT_IDENTITY;
  status: "FAILED";
  job_id: string;
  request_digest: string;
  error: string;
  go: false;
  automatic_promotion: false;
  live_orders_enabled: false;
  mass: false;
};

function parseProgress(
  value: unknown,
  state: ControlledPilotSubmittedState,
  kind: "pending" | "execution" | "accepted",
): Record<string, unknown> | null {
  const fields = kind === "pending"
    ? ["identity", "status", "job_id", "request_digest", "lease_id", "execution_id", "go"]
    : kind === "accepted"
      ? ["identity", "stage", "job_id", "request_digest", "execution_id", "runner_version", "go"]
      : ["identity", "stage", "job_id", "request_digest", "execution_id", "go"];
  if (!isRecord(value) || !closedShape(value, fields) ||
      value.identity !== CONTROLLED_PILOT_IDENTITY ||
      value.job_id !== state.job_id || value.request_digest !== state.request_digest ||
      value.execution_id !== state.spec.execution_id || value.go !== false) return null;
  if (kind === "pending" &&
      (value.status !== "FINALIZE_RETRY" || typeof value.lease_id !== "string" || !value.lease_id)) return null;
  if (kind === "execution" && value.stage !== "CONTAINER_COMPLETED") return null;
  if (kind === "accepted" &&
      (value.stage !== "CONTAINER_ACCEPTED" || value.runner_version !== state.spec.runner_version)) return null;
  return value;
}

function parseControlledFailure(
  value: unknown,
  state: ControlledPilotSubmittedState,
): ControlledFailure | null {
  if (!isRecord(value) || !closedShape(value, FAILURE_FIELDS) ||
      value.identity !== CONTROLLED_PILOT_IDENTITY || value.status !== "FAILED" ||
      value.job_id !== state.job_id || value.request_digest !== state.request_digest ||
      typeof value.error !== "string" || value.error.length < 1 || value.error.length > 512 ||
      value.go !== false || value.automatic_promotion !== false ||
      value.live_orders_enabled !== false || value.mass !== false) return null;
  return value as ControlledFailure;
}

async function parseStoredSessionScope(
  value: unknown,
  physicalDigest: string,
): Promise<ControlledSessionScope | null> {
  if (!isRecord(value) || !closedShape(value, new Set([
    "format", "dependency_scope_proof_digest", "physical_db_digest", "observed_through", "entries",
  ])) || value.format !== "controlled-session-scope/v1" ||
      !isSha256(value.dependency_scope_proof_digest) ||
      value.physical_db_digest !== physicalDigest ||
      typeof value.observed_through !== "string" ||
      !Number.isFinite(Date.parse(value.observed_through)) ||
      !Array.isArray(value.entries) ||
      value.entries.length !== EXACT_FOUR_DATASET_IDS.length) return null;
  const entries: ControlledSessionScope["entries"] = [];
  for (let index = 0; index < EXACT_FOUR_DATASET_IDS.length; index += 1) {
    const raw = value.entries[index];
    const datasetId = EXACT_FOUR_DATASET_IDS[index]!;
    if (!isRecord(raw) || !closedShape(raw, CONTROLLED_SESSION_ENTRY_FIELDS) ||
        raw.dataset_id !== datasetId ||
        !Number.isSafeInteger(raw.natural_key_count) || Number(raw.natural_key_count) < 1 ||
        !isSha256(raw.natural_key_digest) || !Array.isArray(raw.product_artifact_digests) ||
        raw.product_artifact_digests.length < 1 ||
        raw.product_artifact_digests.some((digest: unknown) => !isSha256(digest)) ||
        new Set(raw.product_artifact_digests).size !== raw.product_artifact_digests.length ||
        !isSha256(raw.product_artifact_set_digest) ||
        raw.product_artifact_set_digest !==
          await sha256Digest(canonicalJson(raw.product_artifact_digests))) return null;
    entries.push({
      dataset_id: datasetId,
      natural_key_count: Number(raw.natural_key_count),
      natural_key_digest: raw.natural_key_digest,
      product_artifact_digests: [...raw.product_artifact_digests] as string[],
      product_artifact_set_digest: raw.product_artifact_set_digest,
    });
  }
  const parsed: ControlledSessionScope = {
    format: "controlled-session-scope/v1",
    dependency_scope_proof_digest: value.dependency_scope_proof_digest,
    physical_db_digest: physicalDigest,
    observed_through: value.observed_through,
    entries,
  };
  return jsonEqual(value, parsed) ? parsed : null;
}

async function parseStoredVerifiedReady(
  value: unknown,
  request: ControlledPilotRequest,
  environment: string,
): Promise<VerifiedControlledReady | null> {
  if (!isRecord(value) || !closedShape(value, VERIFIED_READY_STATE_FIELDS) ||
      value.attestation_id !== request.ready_attestation_id ||
      value.snapshot_id !== request.snapshot_id || !isSha256(value.snapshot_id) ||
      !isSha256(value.immutable_db_digest) || !isRecord(value.physical) ||
      !closedShape(value.physical, PHYSICAL_FIELDS) ||
      value.physical.digest !== value.immutable_db_digest ||
      value.physical.key !== controlledPhysicalSnapshotKey(value.immutable_db_digest) ||
      !Number.isSafeInteger(value.physical.size) || Number(value.physical.size) < 1 ||
      value.identity !== CONTROLLED_PILOT_IDENTITY ||
      value.profile_digest !== EXACT_FOUR_PROFILE_DIGEST ||
      value.plan_set_digest !== EXACT_FOUR_PLAN_SET_DIGEST ||
      value.dependency_closure_digest !== EXACT_FOUR_CLOSURE_DIGEST ||
      value.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST ||
      value.environment !== environment ||
      !isSha256(value.ready_manifest_digest) || !isSha256(value.receipt_proof_digest) ||
      !isSha256(value.coverage_proof_digest) || !isSha256(value.b0_quality_proof_digest) ||
      !isSha256(value.b4_quality_proof_digest) || !isSha256(value.resolved_universe_digest) ||
      !isSha256(value.signed_projection_document_digest)) return null;
  const sessionScope = await parseStoredSessionScope(
    value.session_scope,
    value.immutable_db_digest,
  );
  if (sessionScope === null) return null;
  const ready: VerifiedControlledReady = {
    attestation_id: request.ready_attestation_id,
    snapshot_id: request.snapshot_id,
    immutable_db_digest: value.immutable_db_digest,
    physical: {
      key: value.physical.key as string,
      digest: value.immutable_db_digest,
      size: Number(value.physical.size),
    },
    identity: CONTROLLED_PILOT_IDENTITY,
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    ready_manifest_digest: value.ready_manifest_digest,
    fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
    receipt_proof_digest: value.receipt_proof_digest,
    coverage_proof_digest: value.coverage_proof_digest,
    b0_quality_proof_digest: value.b0_quality_proof_digest,
    b4_quality_proof_digest: value.b4_quality_proof_digest,
    resolved_universe_digest: value.resolved_universe_digest,
    environment,
    signed_projection_document_digest: value.signed_projection_document_digest,
    session_scope: sessionScope,
  };
  return jsonEqual(value, ready) ? ready : null;
}

async function parseControlledPilotSubmittedState(
  value: unknown,
  jobId: string,
  environment: string,
  uploadedAt: number,
): Promise<ControlledPilotSubmittedState | null> {
  const submittedAt = isRecord(value) ? parseCanonicalUtc(value.submitted_at) : Number.NaN;
  if (!isRecord(value) || !closedShape(value, SUBMITTED_STATE_FIELDS) ||
      value.identity !== CONTROLLED_PILOT_IDENTITY || value.status !== "SUBMITTED" ||
      value.job_id !== jobId || value.go !== false ||
      value.automatic_promotion !== false || value.live_orders_enabled !== false ||
      value.mass !== false || typeof value.submitted_at !== "string" ||
      !Number.isFinite(submittedAt) || !Number.isFinite(uploadedAt) ||
      Math.abs(uploadedAt - submittedAt) > STATE_UPLOAD_SKEW_MS) return null;
  const admission = value.admission;
  if (!isRecord(admission) || !closedShape(admission, ADMISSION_STATE_FIELDS) ||
      admission.verified_at !== value.submitted_at ||
      !Number.isFinite(parseCanonicalUtc(admission.verified_at)) ||
      typeof admission.ready_key_id !== "string" || admission.ready_key_id.length < 1 ||
      admission.ready_key_id.length > 128 ||
      typeof admission.trader_key_id !== "string" || admission.trader_key_id.length < 1 ||
      admission.trader_key_id.length > 128) return null;
  const parsedRequest = parseControlledPilotRequest(value.request);
  if (!parsedRequest.ok || !jsonEqual(value.request, parsedRequest.value) ||
      parsedRequest.value.idempotency_key !== jobId) return null;
  const digest = await requestDigest(parsedRequest.value);
  if (value.request_digest !== digest) return null;
  const ready = await parseStoredVerifiedReady(
    value.ready,
    parsedRequest.value,
    environment,
  );
  if (ready === null || !isRecord(value.spec) ||
      !isSha256(value.spec.authorization_digest)) return null;
  const expectedSpec = closedControlledPilotJobSpec({
    job_id: jobId,
    idempotency_key: parsedRequest.value.idempotency_key,
    ready_attestation_id: parsedRequest.value.ready_attestation_id,
    ready_manifest_digest: ready.ready_manifest_digest,
    signed_projection_document_digest: ready.signed_projection_document_digest,
    session_scope: ready.session_scope,
    snapshot_id: parsedRequest.value.snapshot_id,
    immutable_db_digest: ready.immutable_db_digest,
    snapshot_key: ready.physical.key,
    snapshot_size: ready.physical.size,
    authorization_digest: value.spec.authorization_digest,
    request_digest: digest,
    resolved_universe_digest: ready.resolved_universe_digest,
    manifest_key: controlledContainerTerminalKey(jobId),
    execution_id: await controlledPilotExecutionId(jobId, digest),
  });
  if (!jsonEqual(value.spec, expectedSpec)) return null;
  const parsed: ControlledPilotSubmittedState = {
    identity: CONTROLLED_PILOT_IDENTITY,
    status: "SUBMITTED",
    job_id: jobId,
    request_digest: digest,
    submitted_at: value.submitted_at,
    admission: {
      verified_at: admission.verified_at,
      ready_key_id: admission.ready_key_id,
      trader_key_id: admission.trader_key_id,
    },
    spec: expectedSpec,
    ready,
    request: parsedRequest.value,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
    mass: false,
  };
  return jsonEqual(value, parsed) ? parsed : null;
}

async function reverifyControlledSubmission(
  env: Env,
  jobId: string,
  expectedDigest?: string,
): Promise<ReverifiedControlledSubmission | null> {
  if (!env.STRUCTURED_BUCKET) return null;
  const environment = registries.controlledEnvironment(env);
  if (!environment) return null;
  const loadedState = await loadJsonObjectWithUploaded(
    env.STRUCTURED_BUCKET,
    stateKey(jobId),
    STATE_MAX_BYTES,
  );
  const state = await parseControlledPilotSubmittedState(
    loadedState?.value,
    jobId,
    environment,
    loadedState?.uploadedAt ?? Number.NaN,
  );
  if (state === null || (expectedDigest && state.request_digest !== expectedDigest)) {
    return null;
  }
  const readyBytes = await loadBytes(
    env.STRUCTURED_BUCKET,
    controlledReadyKey(state.request.ready_attestation_id),
  );
  if (!readyBytes) return null;
  const admissionTime = parseCanonicalUtc(state.admission.verified_at);
  const historicalClock: VerifierClock = { now: () => admissionTime };
  const readyKeys = (await registries.loadPinnedReadyKeys(environment))
    .filter((key) => key.key_id === state.admission.ready_key_id);
  const verifiedReady = await verifyControlledReadyEnvelopeBytes(
    readyBytes,
    state.request.snapshot_id,
    environment,
    readyKeys,
    historicalClock,
  );
  if (
    !verifiedReady.ok ||
    verifiedReady.value.attestation_id !== state.request.ready_attestation_id ||
    !jsonEqual(verifiedReady.value, state.ready)
  ) {
    return null;
  }
  const authorizationBytes = await loadBytes(
    env.STRUCTURED_BUCKET,
    controlledTraderAuthorizationKey(
      state.request.idempotency_key,
      state.request.ready_attestation_id,
    ),
  );
  if (!authorizationBytes) return null;
  const traderKeys = (await registries.loadPinnedTraderKeys(environment))
    .filter((key) => key.key_id === state.admission.trader_key_id);
  const verifiedAuthorization = await verifyTraderAuthorizationBatchBytes(
    authorizationBytes,
    state.request,
    verifiedReady.value,
    state.request_digest,
    traderKeys,
    historicalClock,
  );
  if (
    !verifiedAuthorization.ok ||
    verifiedAuthorization.authorization_digest !== state.spec.authorization_digest
  ) {
    return null;
  }
  return {
    state,
    ready: verifiedReady.value,
    authorization_digest: verifiedAuthorization.authorization_digest,
  };
}

async function putCreateOnly(
  bucket: R2Bucket,
  key: string,
  data: Record<string, unknown>,
): Promise<{ conflict: boolean; created: boolean }> {
  const result = await putJsonCreateOnly(bucket, key, data);
  return { conflict: result.conflict, created: result.created };
}

async function writeControlledFailure(
  bucket: R2Bucket,
  state: ControlledPilotSubmittedState,
  error: string,
): Promise<void> {
  const document: ControlledFailure = {
    identity: CONTROLLED_PILOT_IDENTITY,
    status: "FAILED",
    job_id: state.job_id,
    request_digest: state.request_digest,
    error: error.slice(0, 512) || "controlled execution failed",
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
    mass: false,
  };
  await putCreateOnly(bucket, failureKey(state.job_id), document);
}

function terminalResponse(
  jobId: string,
  status: "COMPLETED" | "FAILED" | "UNKNOWN",
  extra: Record<string, unknown> = {},
  httpStatus = status === "COMPLETED" ? 202 : 200,
): Response {
  return json({
    ok: status === "COMPLETED",
    identity: CONTROLLED_PILOT_IDENTITY,
    job_id: jobId,
    status,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
    mass: false,
    ...extra,
  }, httpStatus);
}

async function verifiedTerminal(
  env: Env,
  jobId: string,
  expectedDigest?: string,
  preverified?: ReverifiedControlledSubmission,
): Promise<
  | { status: "COMPLETED"; manifest: Record<string, unknown> }
  | { status: "FAILED" | "UNKNOWN"; error: string }
  | null
> {
  const bucket = env.STRUCTURED_BUCKET;
  if (!bucket) return null;
  const manifest = await loadJsonObject(bucket, manifestKey(jobId));
  if (!manifest) return null;
  if (expectedDigest && manifest.request_digest !== expectedDigest) {
    return { status: "FAILED", error: "idempotency conflict" };
  }
  const digest = String(manifest.request_digest || expectedDigest || "");
  const authority = preverified ?? await reverifyControlledSubmission(env, jobId, digest);
  if (!digest || !authority || !(await reverifyManifest(bucket, jobId, digest, authority))) {
    return { status: "FAILED", error: "terminal manifest failed re-verification", };
  }
  return { status: "COMPLETED", manifest };
}

export async function submitControlledPilot(
  env: Env,
  body: unknown,
  ctx?: { waitUntil(promise: Promise<unknown>): void },
  rawBytes?: Uint8Array,
): Promise<Response> {
  let parsedBody = body;
  if (rawBytes) {
    try {
      parsedBody = decodeStrictJson(rawBytes);
    } catch (error) {
      const detail = error instanceof StrictJsonError ? error.message : "invalid JSON body";
      return json({ ok: false, error: detail, go: false }, 400);
    }
  }
  const parsed = parseControlledPilotRequest(parsedBody);
  if (!parsed.ok) return json({ ok: false, error: parsed.error, go: false }, 400);
  const request = parsed.value;
  if (!env.STRUCTURED_BUCKET) return json({ ok: false, error: "STRUCTURED_BUCKET not bound", go: false }, 503);
  if (!env.AI_GATEWAY) return json({ ok: false, error: "AI_GATEWAY not bound", go: false }, 503);
  const environment = registries.controlledEnvironment(env);
  if (!environment) return json({ ok: false, error: "controlled environment is invalid", go: false }, 503);
  const admissionTime = Date.now();
  const admittedAt = new Date(admissionTime).toISOString();
  const admissionClock: VerifierClock = { now: () => admissionTime };
  const digest = await requestDigest(request);
  const jobId = request.idempotency_key;
  const existing = await verifiedTerminal(env, jobId, digest);
  if (existing) {
    if (existing.status !== "COMPLETED") {
      return terminalResponse(jobId, existing.status, { error: existing.error });
    }
    if (existing.manifest.request_digest !== digest) {
      return json({ ok: false, error: "idempotency conflict", go: false }, 409);
    }
    return terminalResponse(jobId, "COMPLETED", {
      accepted: true,
      idempotent: true,
      status_url: `/v1/controlled-pilot/${jobId}`,
      manifest: existing.manifest,
    });
  }
  const prior = await reverifyControlledSubmission(env, jobId, digest);
  if (prior) {
    const failed = parseControlledFailure(
      await loadJsonObject(env.STRUCTURED_BUCKET, failureKey(jobId), STATE_MAX_BYTES),
      prior.state,
    );
    if (failed) return terminalResponse(jobId, "FAILED", { error: failed.error });
    if (!(await scheduleControlledResume(env, request.idempotency_key, jobId))) {
      return json({ ok: false, error: "controlled resume scheduler unavailable", job_id: jobId, go: false }, 503);
    }
    return json({
      ok: true,
      accepted: true,
      idempotent: true,
      identity: CONTROLLED_PILOT_IDENTITY,
      job_id: jobId,
      status: "SUBMITTED",
      status_url: `/v1/controlled-pilot/${jobId}`,
      go: false,
      automatic_promotion: false,
      live_orders_enabled: false,
      mass: false,
    }, 202);
  }
  const readyBytes = await loadBytes(env.STRUCTURED_BUCKET, controlledReadyKey(request.ready_attestation_id));
  if (!readyBytes) return json({ ok: false, error: "READY envelope not found", go: false }, 404);
  const readyKeys = (await registries.loadPinnedReadyKeys(environment))
    .filter((key) => key.status === "active");
  const verified = await verifyControlledReadyEnvelopeBytes(
    readyBytes,
    request.snapshot_id,
    environment,
    readyKeys,
    admissionClock,
  );
  if (!verified.ok) {
    const status = verified.error === "CONTROLLED_AUTHORITY_UNPROVISIONED" ? 503 : 400;
    return json({ ok: false, error: verified.error, go: false }, status);
  }
  if (verified.value.attestation_id !== request.ready_attestation_id) {
    return json({ ok: false, error: "READY attestation id mismatch", go: false }, 400);
  }
  const authBytes = await loadBytes(
    env.STRUCTURED_BUCKET,
    controlledTraderAuthorizationKey(request.idempotency_key, request.ready_attestation_id),
  );
  if (!authBytes) return json({ ok: false, error: "trader authorization not found", go: false }, 404);
  const traderKeys = (await registries.loadPinnedTraderKeys(environment))
    .filter((key) => key.status === "active");
  const authorized = await verifyTraderAuthorizationBatchBytes(
    authBytes,
    request,
    verified.value,
    digest,
    traderKeys,
    admissionClock,
  );
  if (!authorized.ok) return json({ ok: false, error: authorized.error, go: false }, 401);
  const snapshotHead = await env.STRUCTURED_BUCKET.head(verified.value.physical.key);
  if (!snapshotHead) return json({ ok: false, error: "controlled snapshot not found", go: false }, 404);
  if (snapshotHead.size !== verified.value.physical.size) {
    return json({ ok: false, error: "controlled snapshot size mismatch", go: false }, 409);
  }
  const executionId = await controlledPilotExecutionId(jobId, digest);
  const spec = closedControlledPilotJobSpec({
    job_id: jobId,
    idempotency_key: request.idempotency_key,
    ready_attestation_id: request.ready_attestation_id,
    ready_manifest_digest: verified.value.ready_manifest_digest,
    signed_projection_document_digest: verified.value.signed_projection_document_digest,
    session_scope: verified.value.session_scope,
    snapshot_id: request.snapshot_id,
    immutable_db_digest: verified.value.immutable_db_digest,
    snapshot_key: verified.value.physical.key,
    snapshot_size: verified.value.physical.size,
    authorization_digest: authorized.authorization_digest,
    request_digest: digest,
    resolved_universe_digest: verified.value.resolved_universe_digest,
    manifest_key: controlledContainerTerminalKey(jobId),
    execution_id: executionId,
  });
  const submitted = {
    identity: CONTROLLED_PILOT_IDENTITY,
    status: "SUBMITTED",
    job_id: jobId,
    request_digest: digest,
    submitted_at: admittedAt,
    admission: {
      verified_at: admittedAt,
      ready_key_id: readyKeys[0]!.key_id,
      trader_key_id: traderKeys[0]!.key_id,
    },
    spec,
    ready: verified.value,
    request,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
    mass: false,
  };
  const wrote = await putCreateOnly(env.STRUCTURED_BUCKET, stateKey(jobId), submitted);
  if (wrote.conflict) {
    const raced = await loadJsonObjectWithUploaded(
      env.STRUCTURED_BUCKET,
      stateKey(jobId),
      STATE_MAX_BYTES,
    );
    const parsedRaced = await parseControlledPilotSubmittedState(
      raced?.value,
      jobId,
      environment,
      raced?.uploadedAt ?? Number.NaN,
    );
    const expectedRaced = parsedRaced === null
      ? null
      : {
          ...submitted,
          submitted_at: parsedRaced.submitted_at,
          admission: parsedRaced.admission,
        };
    if (parsedRaced === null || !jsonEqual(parsedRaced, expectedRaced)) {
      return json({ ok: false, error: "idempotency conflict", go: false }, 409);
    }
  }
  if (!(await scheduleControlledResume(env, request.idempotency_key, jobId))) {
    return json({ ok: false, error: "controlled resume scheduler unavailable", job_id: jobId, go: false }, 503);
  }
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(runControlledPilotJob(env, jobId));
  return json({
    ok: true,
    accepted: true,
    identity: CONTROLLED_PILOT_IDENTITY,
    job_id: jobId,
    status: "SUBMITTED",
    status_url: `/v1/controlled-pilot/${jobId}`,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
    mass: false,
  }, 202);
}

export async function controlledPilotStatus(
  env: Env,
  jobId: string,
  ctx?: { waitUntil(promise: Promise<unknown>): void },
): Promise<Response> {
  if (!env.STRUCTURED_BUCKET) return json({ ok: false, error: "STRUCTURED_BUCKET not bound", go: false }, 503);
  const terminal = await verifiedTerminal(env, jobId);
  if (terminal) {
    if (terminal.status !== "COMPLETED") {
      return terminalResponse(jobId, terminal.status, { error: terminal.error });
    }
    return terminalResponse(jobId, "COMPLETED", { manifest: terminal.manifest }, 200);
  }
  const environment = registries.controlledEnvironment(env);
  if (!environment) return json({ ok: false, error: "controlled environment is invalid", go: false }, 503);
  const rawState = await loadJsonObjectWithUploaded(
    env.STRUCTURED_BUCKET,
    stateKey(jobId),
    STATE_MAX_BYTES,
  );
  const state = await parseControlledPilotSubmittedState(
    rawState?.value,
    jobId,
    environment,
    rawState?.uploadedAt ?? Number.NaN,
  );
  if (!state) {
    const fragments = await Promise.all([
      env.STRUCTURED_BUCKET.head(stateKey(jobId)),
      env.STRUCTURED_BUCKET.head(pendingKey(jobId)),
      env.STRUCTURED_BUCKET.head(controlledExecutionStageKey(jobId)),
      env.STRUCTURED_BUCKET.head(failureKey(jobId)),
    ]);
    if (fragments.some(Boolean)) {
      return terminalResponse(jobId, "FAILED", { error: "controlled state failed validation" });
    }
    return json({ ok: false, error: "job_not_found", job_id: jobId, go: false }, 404);
  }
  const rawFailure = await loadJsonObject(env.STRUCTURED_BUCKET, failureKey(jobId), STATE_MAX_BYTES);
  const failureExists = rawFailure !== null || await env.STRUCTURED_BUCKET.head(failureKey(jobId)) !== null;
  if (failureExists) {
    const failure = parseControlledFailure(rawFailure, state);
    return terminalResponse(jobId, "FAILED", {
      error: failure?.error ?? "controlled failure state failed validation",
    });
  }
  const authority = await reverifyControlledSubmission(env, jobId, state.request_digest);
  if (!authority) {
    return terminalResponse(jobId, "FAILED", { error: "submission authority failed re-verification" });
  }
  const rawPending = await loadJsonObject(env.STRUCTURED_BUCKET, pendingKey(jobId), STATE_MAX_BYTES);
  const rawExecution = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    controlledExecutionStageKey(jobId),
    STATE_MAX_BYTES,
  );
  const pendingExists = rawPending !== null || await env.STRUCTURED_BUCKET.head(pendingKey(jobId)) !== null;
  const executionExists = rawExecution !== null ||
    await env.STRUCTURED_BUCKET.head(controlledExecutionStageKey(jobId)) !== null;
  const pending = parseProgress(rawPending, state, "pending");
  const execution = parseProgress(rawExecution, state, "execution");
  if ((pendingExists && !pending) || (executionExists && !execution)) {
    return terminalResponse(jobId, "FAILED", { error: "controlled progress state failed validation" });
  }
  const status = pending || execution ? "FINALIZE_RETRY" : "SUBMITTED";
  if (ctx && typeof ctx.waitUntil === "function") {
    ctx.waitUntil(scheduleControlledResume(env, jobId, jobId));
  }
  return json({
    ok: true,
    accepted: true,
    identity: CONTROLLED_PILOT_IDENTITY,
    job_id: jobId,
    status,
    pending: pending ?? undefined,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
  }, 202);
}

async function persistCandidateAndStage(
  bucket: R2Bucket,
  jobId: string,
  digest: string,
  executionId: string,
  manifest: Record<string, unknown>,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const candidate = await putCreateOnly(bucket, controlledCandidateManifestKey(jobId), manifest);
  if (candidate.conflict) return { ok: false, error: "candidate manifest conflict" };
  const stage = await putCreateOnly(bucket, controlledExecutionStageKey(jobId), {
    identity: CONTROLLED_PILOT_IDENTITY,
    stage: "CONTAINER_COMPLETED",
    job_id: jobId,
    request_digest: digest,
    execution_id: executionId,
    go: false,
  });
  if (stage.conflict) return { ok: false, error: "execution stage conflict" };
  return { ok: true };
}

async function scheduleControlledResume(env: Env, idempotencyKey: string, jobId: string): Promise<boolean> {
  if (!env.PERSONAL_RESEARCH_CONTAINER) return false;
  const name = await controlledPilotContainerName(idempotencyKey);
  const stub = env.PERSONAL_RESEARCH_CONTAINER.getByName(name) as {
    scheduleControlledPilot?: (id: string) => Promise<void>;
  };
  if (typeof stub.scheduleControlledPilot !== "function") return false;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await stub.scheduleControlledPilot(jobId);
      return true;
    } catch {
      // One immediate retry covers a transient DO RPC failure; the caller remains retryable.
    }
  }
  return false;
}

async function failControlledPilotState(
  env: Env,
  state: ControlledPilotSubmittedState,
  error: string,
  releaseCapabilities = true,
): Promise<void> {
  if (!env.STRUCTURED_BUCKET) return;
  if (env.AI_GATEWAY) {
    try {
      await invokeBudget(env.AI_GATEWAY as GatewayRpc, "cancelControlledPaper", {
        idempotency_key: state.request.idempotency_key,
        request_digest: state.request_digest,
      });
    } catch {
      // The bounded reservation expires independently; failure evidence must still close the job.
    }
  }
  await writeControlledFailure(env.STRUCTURED_BUCKET, state, error);
  if (releaseCapabilities) {
    try {
      await releaseControlledOutbound(env, state.job_id);
    } catch {
      // The Container scheduler retries capability cleanup for terminal jobs.
    }
  }
}

export async function expireControlledPilotJob(
  env: Env,
  jobId: string,
  releaseCapabilities = true,
): Promise<void> {
  if (!env.STRUCTURED_BUCKET) return;
  const environment = registries.controlledEnvironment(env);
  if (!environment) return;
  const loadedState = await loadJsonObjectWithUploaded(
    env.STRUCTURED_BUCKET,
    stateKey(jobId),
    STATE_MAX_BYTES,
  );
  const state = await parseControlledPilotSubmittedState(
    loadedState?.value,
    jobId,
    environment,
    loadedState?.uploadedAt ?? Number.NaN,
  );
  if (!state) return;
  await failControlledPilotState(
    env,
    state,
    "controlled execution deadline exceeded",
    releaseCapabilities,
  );
}

export async function runControlledPilotJob(
  env: Env,
  jobId: string,
  releaseCapabilities = true,
): Promise<void> {
  if (!env.STRUCTURED_BUCKET || !env.AI_GATEWAY) return;
  const authority = await reverifyControlledSubmission(env, jobId);
  if (!authority) return;
  const verified = await verifiedTerminal(env, jobId, authority.state.request_digest, authority);
  if (verified) {
    if (releaseCapabilities) await releaseControlledOutbound(env, jobId);
    return;
  }
  const state = authority.state;
  if (await env.STRUCTURED_BUCKET.head(failureKey(jobId))) return;
  const { spec, request, ready, request_digest: digest } = state;
  const fail = (error: string) => failControlledPilotState(env, state, error, releaseCapabilities);
  const gateway = env.AI_GATEWAY as GatewayRpc;
  const budgetInput = { idempotency_key: request.idempotency_key, request_digest: digest };
  const rawExecution = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    controlledExecutionStageKey(jobId),
    STATE_MAX_BYTES,
  );
  const executionExists = rawExecution !== null ||
    await env.STRUCTURED_BUCKET.head(controlledExecutionStageKey(jobId)) !== null;
  const execution = parseProgress(rawExecution, state, "execution");
  if (executionExists && !execution) {
    await fail("controlled execution state failed validation");
    return;
  }
  const containerCompleted = execution !== null;
  const acceptedKey = `${controlledJobPrefix(jobId)}/container-accepted.json`;
  const rawAccepted = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    acceptedKey,
    STATE_MAX_BYTES,
  );
  const acceptedExists = rawAccepted !== null || await env.STRUCTURED_BUCKET.head(acceptedKey) !== null;
  const containerAccepted = parseProgress(rawAccepted, state, "accepted");
  if (acceptedExists && !containerAccepted) {
    await fail("controlled admission state failed validation");
    return;
  }
  let leaseId = "";
  const storedReservation = await loadJsonObject(env.STRUCTURED_BUCKET, reservationKey(jobId), STATE_MAX_BYTES);
  let queried: Awaited<ReturnType<typeof invokeBudget>>;
  try {
    queried = await invokeBudget(gateway, "queryControlledPaper", budgetInput);
  } catch {
    return;
  }
  if (budgetAccepted(queried)) {
    leaseId = String(gatewayBody(queried).lease_id || storedReservation?.lease_id || "");
  } else if (!budgetRetryable(queried) &&
      String(gatewayBody(queried).error || "") === "reservation_not_found") {
    if (containerCompleted) {
      leaseId = String(storedReservation?.lease_id || "");
      if (!leaseId) return;
    } else {
      let reserved: Awaited<ReturnType<typeof invokeBudget>>;
      try {
        reserved = await invokeBudget(gateway, "reserveControlledPaper", budgetInput);
      } catch {
        return;
      }
      if (!budgetAccepted(reserved)) {
        if (!budgetRetryable(reserved)) await fail(budgetFailure(reserved, "reserve"));
        return;
      }
      leaseId = String(gatewayBody(reserved).lease_id || "");
      await putCreateOnly(env.STRUCTURED_BUCKET, reservationKey(jobId), {
        lease_id: leaseId,
        request_digest: digest,
        job_id: jobId,
        execution_id: spec.execution_id,
      });
    }
  } else if (budgetRetryable(queried)) {
    return;
  } else {
    await fail(budgetFailure(queried, "query"));
    return;
  }
  if (!leaseId && storedReservation) leaseId = String(storedReservation.lease_id || "");
  if (!leaseId) return;

  let persistedManifest: Record<string, unknown> | null = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    controlledCandidateManifestKey(jobId),
  );
  if (containerCompleted && !persistedManifest) {
    await fail("controlled candidate manifest is missing");
    return;
  }
  if (!containerCompleted) {
    let heartbeat: Awaited<ReturnType<typeof invokeBudget>>;
    try {
      heartbeat = await invokeBudget(gateway, "heartbeatControlledPaper", {
        ...budgetInput,
        lease_id: leaseId,
      });
    } catch {
      return;
    }
    if (!budgetAccepted(heartbeat)) {
      if (!budgetRetryable(heartbeat)) await fail(budgetFailure(heartbeat, "heartbeat"));
      return;
    }
    const containerName = await controlledPilotContainerName(request.idempotency_key);
    try {
      await bindPhysicalOutbound(env, containerName, ready.physical, {
        job_id: jobId,
        request_digest: digest,
      });
      let executed: Awaited<ReturnType<typeof callContainer>>;
      if (!containerAccepted) {
        executed = await callContainer(env, spec, containerName);
        if (executed.accepted) {
          await putCreateOnly(env.STRUCTURED_BUCKET, acceptedKey, {
            identity: CONTROLLED_PILOT_IDENTITY,
            stage: "CONTAINER_ACCEPTED",
            job_id: jobId,
            request_digest: digest,
            execution_id: spec.execution_id,
            runner_version: spec.runner_version,
            go: false,
          });
        }
      } else {
        executed = await callContainer(env, spec, containerName, { skipPost: true });
      }
      if (!executed.ok && "pending" in executed && executed.pending) {
        return;
      }
      if (!executed.ok) {
        await fail(executed.error);
        return;
      }
      // The Container has published its terminal and is now quiescent.
      // Subsequent persistence/finalize retries do not need its R2 capabilities.
      if (releaseCapabilities) await releaseControlledOutbound(env, jobId);
      const persisted = await persistBoundChildren(
        env.STRUCTURED_BUCKET,
        request,
        ready,
        spec.authorization_digest,
        executed.value,
        digest,
      );
      if (!persisted.ok) {
        await fail(persisted.error ?? "controlled artifact persistence failed");
        return;
      }
      persistedManifest = persisted.manifest;
      const staged = await persistCandidateAndStage(
        env.STRUCTURED_BUCKET,
        jobId,
        digest,
        spec.execution_id,
        persisted.manifest,
      );
      if (!staged.ok) {
        await fail(staged.error);
        return;
      }
    } catch {
      return;
    }
  }
  if (!persistedManifest) return;
  let finalized: Awaited<ReturnType<typeof invokeBudget>>;
  try {
    finalized = await invokeBudget(gateway, "finalizeControlledPaper", {
      ...budgetInput,
      lease_id: leaseId,
    });
  } catch {
    return;
  }
  if (!budgetAccepted(finalized)) {
    if (!budgetRetryable(finalized)) {
      await fail(budgetFailure(finalized, "finalize"));
      return;
    }
    await putCreateOnly(env.STRUCTURED_BUCKET, pendingKey(jobId), {
      identity: CONTROLLED_PILOT_IDENTITY,
      status: "FINALIZE_RETRY",
      job_id: jobId,
      request_digest: digest,
      lease_id: leaseId,
      execution_id: spec.execution_id,
      go: false,
    });
    return;
  }
  const commit = await putChildrenThenManifest(env.STRUCTURED_BUCKET, [], {
    key: manifestKey(jobId),
    data: persistedManifest,
  });
  if (!commit.ok) return;
  const ok = await reverifyManifest(env.STRUCTURED_BUCKET, jobId, digest, authority);
  if (!ok) {
    await fail("terminal manifest failed re-verification");
  }
}

export const verifyControlledReadySidecar = verifyControlledReadyEnvelope;
export const verifyTraderAuthorizationSet = verifyTraderAuthorizationBatch;
