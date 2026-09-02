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
const MIN_TTL_MS = 60_000;
const MAX_TTL_MS = 86_400_000;
const STATE_MAX_BYTES = 16 * 1024;
const TERMINAL_MAX_BYTES = 64 * 1024;
const READY_AUTH_MAX_BYTES = 64 * 1024;
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
  if (!isRecord(signedProjection) || !isRecord(document.dependency_scope_evidence) ||
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
  const dependencyScopeBody = { ...document.dependency_scope_evidence };
  const declaredDependencyScopeDigest = dependencyScopeBody.proof_digest;
  delete dependencyScopeBody.proof_digest;
  if (!isSha256(declaredDependencyScopeDigest) ||
      declaredDependencyScopeDigest !== sessionScope.dependency_scope_proof_digest ||
      (await sha256Digest(canonicalJson(dependencyScopeBody))) !== declaredDependencyScopeDigest ||
      !isRecord(manifest.pit_contract_digests) ||
      manifest.pit_contract_digests.dependency_scope !==
        sessionScope.dependency_scope_proof_digest) {
    return { ok: false, error: "READY dependency scope digest is invalid" };
  }
  const sessionDatasets: unknown[] = [];
  for (const entry of sessionScope.entries) {
    if (!isRecord(entry) || !closedShape(entry, new Set([
      "dataset_id", "natural_key_count", "natural_key_digest",
      "product_artifact_digests", "product_artifact_set_digest",
    ])) || !Number.isSafeInteger(entry.natural_key_count) || Number(entry.natural_key_count) < 1 ||
      !isSha256(entry.natural_key_digest) || !Array.isArray(entry.product_artifact_digests) ||
      entry.product_artifact_digests.length < 1 ||
      entry.product_artifact_digests.some((value) => !isSha256(value)) ||
      new Set(entry.product_artifact_digests).size !== entry.product_artifact_digests.length ||
      !isSha256(entry.product_artifact_set_digest) ||
      entry.product_artifact_set_digest !== await sha256Digest(canonicalJson(entry.product_artifact_digests))) {
      return { ok: false, error: "READY controlled session scope entry is invalid" };
    }
    sessionDatasets.push(entry.dataset_id);
  }
  if (!jsonEqual(sessionDatasets, [...EXACT_FOUR_DATASET_IDS])) {
    return { ok: false, error: "READY controlled session dataset scope is invalid" };
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
    params: ControlledPhysicalSnapshot,
  ) => Promise<void>;
  removeOutboundByHost: (hostname: string) => Promise<void>;
};

async function bindPhysicalOutbound(
  env: Env,
  containerName: string,
  physical: ControlledPhysicalSnapshot,
): Promise<BoundContainer> {
  const target = (await verifiedPersonalResearchContainer(env, containerName)) as BoundContainer;
  if (typeof target.setOutboundByHost !== "function" || typeof target.removeOutboundByHost !== "function") {
    throw new Error("controlled container outbound policy is unavailable");
  }
  await target.setOutboundByHost(CONTROLLED_R2_HOST, CONTROLLED_OUTBOUND_HANDLER, physical);
  return target;
}

async function unbindPhysicalOutbound(target: BoundContainer | null): Promise<void> {
  if (!target) return;
  await target.removeOutboundByHost(CONTROLLED_R2_HOST);
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
  const bindings = {
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

function readyFromManifest(manifest: Record<string, unknown>): VerifiedControlledReady {
  return {
    attestation_id: String(manifest.ready_attestation_id || ""),
    snapshot_id: String(manifest.snapshot_id || ""),
    immutable_db_digest: String(manifest.immutable_db_digest || ""),
    physical: {
      key: String(manifest.snapshot_key || ""),
      digest: String(manifest.immutable_db_digest || ""),
      size: Number(manifest.snapshot_size || 0),
    },
    identity: CONTROLLED_PILOT_IDENTITY,
    profile_digest: String(manifest.profile_digest || ""),
    plan_set_digest: String(manifest.plan_set_digest || ""),
    dependency_closure_digest: String(manifest.dependency_closure_digest || ""),
    ready_manifest_digest: String(manifest.ready_manifest_digest || ""),
    fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
    receipt_proof_digest: "",
    coverage_proof_digest: "",
    b0_quality_proof_digest: "",
    b4_quality_proof_digest: "",
    resolved_universe_digest: String(manifest.resolved_universe_digest || ""),
    environment: "",
    signed_projection_document_digest: String(manifest.signed_projection_document_digest || ""),
    session_scope: {
      format: "controlled-session-scope/v1",
      dependency_scope_proof_digest: "sha256:" + "0".repeat(64),
      physical_db_digest: String(manifest.immutable_db_digest || ""),
      observed_through: "1970-01-01T00:00:00Z",
      entries: [] as unknown as ControlledSessionScope["entries"],
    },
  };
}

async function reverifyManifest(
  bucket: R2Bucket,
  expectedJobId: string,
  expectedDigest: string,
): Promise<boolean> {
  try {
    const manifest = await loadJsonObject(bucket, manifestKey(expectedJobId));
    if (
      !manifest || manifest.format !== "controlled-pilot-paper-bundle/v2" ||
      manifest.request_digest !== expectedDigest || manifest.identity !== CONTROLLED_PILOT_IDENTITY ||
      manifest.idempotency_key !== expectedJobId ||
      manifest.fill_contract_digest !== CONTROLLED_FILL_CONTRACT_DIGEST ||
      manifest.generation !== CONTROLLED_PILOT_GENERATION ||
      manifest.max_parallel !== CONTROLLED_PILOT_MAX_PARALLEL ||
      manifest.automatic_promotion !== false || manifest.live_orders_enabled !== false || manifest.mass !== false
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
    const semantic = await validateContainerArtifacts(container, readyFromManifest(manifest));
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
  | { ok: true; value: ContainerArtifacts }
  | { ok: false; error: string; timeout?: boolean; pending?: boolean }
> {
  if (!env.PERSONAL_RESEARCH_CONTAINER) {
    return { ok: false, error: "controlled container unbound" };
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
      return { ok: false, error: detail, timeout: /timeout/i.test(detail) };
    }
    if (response.status !== 202) {
      return { ok: false, error: `controlled container POST must return 202, got ${response.status}` };
    }
    try {
      parsed = await response.json();
    } catch {
      return { ok: false, error: "controlled container returned invalid JSON" };
    }
  }
  const jobId = spec.job_id;
  const terminal = await waitForContainerJob(env, containerName, jobId, parsed);
  if (!terminal.ok) return terminal;
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
  return { ok: true, value };
}

async function waitForContainerJob(
  env: Env,
  containerName: string,
  jobId: string,
  submitted: unknown,
): Promise<
  | { ok: true; value: unknown }
  | { ok: false; error: string; timeout?: boolean; pending?: boolean }
> {
  if (isRecord(submitted) && Array.isArray(submitted.papers)) {
    return { ok: false, error: "controlled container must accept with 202 and publish via GET" };
  }
  const target = await verifiedPersonalResearchContainer(env, containerName);
  const status = await target.fetch(new Request(`http://container/v1/jobs/${jobId}`));
  let parsed: unknown;
  try {
    parsed = await status.json();
  } catch {
    return { ok: false, error: "controlled container status is invalid" };
  }
  const job = isRecord(parsed) && isRecord(parsed.job) ? parsed.job : parsed;
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
function manifestKey(jobId: string): string {
  return `${controlledJobPrefix(jobId)}/manifest.json`;
}

async function putCreateOnly(
  bucket: R2Bucket,
  key: string,
  data: Record<string, unknown>,
): Promise<{ conflict: boolean; created: boolean }> {
  const result = await putJsonCreateOnly(bucket, key, data);
  return { conflict: result.conflict, created: result.created };
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
  bucket: R2Bucket,
  jobId: string,
  expectedDigest?: string,
): Promise<
  | { status: "COMPLETED"; manifest: Record<string, unknown> }
  | { status: "FAILED" | "UNKNOWN"; error: string }
  | null
> {
  const manifest = await loadJsonObject(bucket, manifestKey(jobId));
  if (!manifest) return null;
  if (expectedDigest && manifest.request_digest !== expectedDigest) {
    return { status: "FAILED", error: "idempotency conflict" };
  }
  const digest = String(manifest.request_digest || expectedDigest || "");
  if (!digest || !(await reverifyManifest(bucket, jobId, digest))) {
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
  const digest = await requestDigest(request);
  const jobId = request.idempotency_key;
  const existing = await verifiedTerminal(env.STRUCTURED_BUCKET, jobId, digest);
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
  const readyBytes = await loadBytes(env.STRUCTURED_BUCKET, controlledReadyKey(request.ready_attestation_id));
  if (!readyBytes) return json({ ok: false, error: "READY envelope not found", go: false }, 404);
  const verified = await verifyControlledReadyEnvelopeBytes(
    readyBytes,
    request.snapshot_id,
    environment,
    await registries.loadPinnedReadyKeys(environment),
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
  const authorized = await verifyTraderAuthorizationBatchBytes(
    authBytes,
    request,
    verified.value,
    digest,
    await registries.loadPinnedTraderKeys(environment),
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
    submitted_at: new Date().toISOString(),
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
    const raced = await loadJsonObject(env.STRUCTURED_BUCKET, stateKey(jobId), STATE_MAX_BYTES);
    if (!raced || raced.request_digest !== digest) {
      return json({ ok: false, error: "idempotency conflict", go: false }, 409);
    }
  }
  if (ctx && typeof ctx.waitUntil === "function") {
    ctx.waitUntil(runControlledPilotJob(env, jobId));
  }
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
  const terminal = await verifiedTerminal(env.STRUCTURED_BUCKET, jobId);
  if (terminal) {
    if (terminal.status !== "COMPLETED") {
      return terminalResponse(jobId, terminal.status, { error: terminal.error });
    }
    return terminalResponse(jobId, "COMPLETED", { manifest: terminal.manifest }, 200);
  }
  const pending = await loadJsonObject(env.STRUCTURED_BUCKET, pendingKey(jobId), STATE_MAX_BYTES);
  const execution = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    controlledExecutionStageKey(jobId),
    STATE_MAX_BYTES,
  );
  const state = await loadJsonObject(env.STRUCTURED_BUCKET, stateKey(jobId), STATE_MAX_BYTES);
  if (!state && !pending && !execution) {
    return json({ ok: false, error: "job_not_found", job_id: jobId, go: false }, 404);
  }
  void ctx;
  const status = pending || execution?.stage === "CONTAINER_COMPLETED" ? "FINALIZE_RETRY" : "SUBMITTED";
  return json({
    ok: true,
    accepted: true,
    identity: CONTROLLED_PILOT_IDENTITY,
    job_id: jobId,
    status,
    pending: pending || undefined,
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

async function scheduleControlledResume(env: Env, idempotencyKey: string, jobId: string): Promise<void> {
  if (!env.PERSONAL_RESEARCH_CONTAINER) return;
  try {
    const name = await controlledPilotContainerName(idempotencyKey);
    const stub = env.PERSONAL_RESEARCH_CONTAINER.getByName(name) as {
      scheduleControlledPilot?: (id: string) => Promise<void>;
    };
    if (typeof stub.scheduleControlledPilot === "function") {
      await stub.scheduleControlledPilot(jobId);
    }
  } catch {
    return;
  }
}

export async function runControlledPilotJob(env: Env, jobId: string): Promise<void> {
  if (!env.STRUCTURED_BUCKET || !env.AI_GATEWAY) return;
  const verified = await verifiedTerminal(env.STRUCTURED_BUCKET, jobId);
  if (verified?.status === "COMPLETED") return;
  const state = await loadJsonObject(env.STRUCTURED_BUCKET, stateKey(jobId), STATE_MAX_BYTES);
  if (!state || !isRecord(state.spec) || !isRecord(state.ready) || !isRecord(state.request)) return;
  const spec = state.spec as unknown as ControlledPilotJobSpec;
  const request = state.request as unknown as ControlledPilotRequest;
  const ready = state.ready as unknown as VerifiedControlledReady;
  const digest = String(state.request_digest);
  const gateway = env.AI_GATEWAY as GatewayRpc;
  const budgetInput = { idempotency_key: request.idempotency_key, request_digest: digest };
  const execution = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    controlledExecutionStageKey(jobId),
    STATE_MAX_BYTES,
  );
  const containerCompleted = execution?.stage === "CONTAINER_COMPLETED";
  const containerAccepted = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    `${controlledJobPrefix(jobId)}/container-accepted.json`,
    STATE_MAX_BYTES,
  );
  let leaseId = "";
  const storedReservation = await loadJsonObject(env.STRUCTURED_BUCKET, reservationKey(jobId), STATE_MAX_BYTES);
  const queried = await invokeBudget(gateway, "queryControlledPaper", budgetInput);
  if (budgetAccepted(queried)) {
    leaseId = String(gatewayBody(queried).lease_id || storedReservation?.lease_id || "");
  } else if (String(gatewayBody(queried).error || "") === "reservation_not_found") {
    if (containerCompleted) {
      leaseId = String(storedReservation?.lease_id || "");
      if (!leaseId) return;
    } else {
      const reserved = await invokeBudget(gateway, "reserveControlledPaper", budgetInput);
      if (!budgetAccepted(reserved)) return;
      leaseId = String(gatewayBody(reserved).lease_id || "");
      await putCreateOnly(env.STRUCTURED_BUCKET, reservationKey(jobId), {
        lease_id: leaseId,
        request_digest: digest,
        job_id: jobId,
        execution_id: spec.execution_id,
      });
    }
  } else {
    return;
  }
  if (!leaseId && storedReservation) leaseId = String(storedReservation.lease_id || "");
  if (!leaseId) return;

  let persistedManifest: Record<string, unknown> | null = await loadJsonObject(
    env.STRUCTURED_BUCKET,
    controlledCandidateManifestKey(jobId),
  );
  if (containerCompleted && !persistedManifest) return;
  if (!containerCompleted) {
    const heartbeat = await invokeBudget(gateway, "heartbeatControlledPaper", {
      ...budgetInput,
      lease_id: leaseId,
    });
    if (!budgetAccepted(heartbeat)) return;
    const containerName = await controlledPilotContainerName(request.idempotency_key);
    let bound: BoundContainer | null = null;
    try {
      bound = await bindPhysicalOutbound(env, containerName, ready.physical);
      let executed: Awaited<ReturnType<typeof callContainer>>;
      if (!containerAccepted) {
        executed = await callContainer(env, spec, containerName);
        await putCreateOnly(env.STRUCTURED_BUCKET, `${controlledJobPrefix(jobId)}/container-accepted.json`, {
          identity: CONTROLLED_PILOT_IDENTITY,
          stage: "CONTAINER_ACCEPTED",
          job_id: jobId,
          request_digest: digest,
          execution_id: spec.execution_id,
          runner_version: spec.runner_version,
          go: false,
        });
      } else {
        executed = await callContainer(env, spec, containerName, { skipPost: true });
      }
      if (!executed.ok && "pending" in executed && executed.pending) {
        await scheduleControlledResume(env, request.idempotency_key, jobId);
        return;
      }
      if (!executed.ok) {
        await invokeBudget(gateway, "cancelControlledPaper", budgetInput);
        return;
      }
      const persisted = await persistBoundChildren(
        env.STRUCTURED_BUCKET,
        request,
        ready,
        spec.authorization_digest,
        executed.value,
        digest,
      );
      if (!persisted.ok) {
        await invokeBudget(gateway, "cancelControlledPaper", budgetInput);
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
        await invokeBudget(gateway, "cancelControlledPaper", budgetInput);
        return;
      }
    } catch {
      return;
    } finally {
      await unbindPhysicalOutbound(bound);
    }
  }
  if (!persistedManifest) return;
  const finalized = await invokeBudget(gateway, "finalizeControlledPaper", {
    ...budgetInput,
    lease_id: leaseId,
  });
  if (!budgetAccepted(finalized)) {
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
  const ok = await reverifyManifest(env.STRUCTURED_BUCKET, jobId, digest);
  if (!ok) {
    await putCreateOnly(env.STRUCTURED_BUCKET, `${CONTROLLED_JOB_KEY_PREFIX}${jobId}/failed.json`, {
      identity: CONTROLLED_PILOT_IDENTITY,
      status: "FAILED",
      job_id: jobId,
      request_digest: digest,
      error: "terminal manifest failed re-verification",
      go: false,
      automatic_promotion: false,
    });
  }
}

export const verifyControlledReadySidecar = verifyControlledReadyEnvelope;
export const verifyTraderAuthorizationSet = verifyTraderAuthorizationBatch;
