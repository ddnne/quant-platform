import { WorkerEntrypoint } from "cloudflare:workers";

import {
  CREATE_ONLY_COMPARE_MAX_BYTES,
  putJsonCreateOnly,
  serializedJsonBytes,
} from "../../research-mass-eval/src/http";
import { keyUsableAt, loadPinnedReadyKeys } from "../../research-mass-eval/src/controlled_pilot_registries";
import {
  pinReceiptNativeSource,
  verifyControlledPilotBinding,
  verifyReceiptNativePeriod,
  verifyReceiptNativeReadyPublication,
  verifyReceiptNativeSnapshotQuality,
} from "../../research-mass-eval/src/receipt_native_ready_publication";
import {
  CONTROLLED_FILL_CONTRACT_DIGEST,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_READY_ENVELOPE_FORMAT,
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
  controlledPhysicalSnapshotKey,
  controlledReadyKey,
} from "../../research-mass-eval/src/controlled_pilot_contract";
import {
  canonicalJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
} from "../../research-mass-eval/src/controlled_pilot_json";
import {
  READY_MANIFEST_V2_FORMAT,
  receiptNativeManifestBodyDigest,
  receiptNativeSnapshotId,
  receiptNativeV2WireError,
} from "../../research-mass-eval/src/ready_manifest_v2";
import { PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES } from "../../research-mass-eval/src/personal_research_contract";
import {
  deriveReceiptNativeSessionScope,
  verifyOpsProjectionReady,
  type ControlledSessionScope,
} from "../../research-mass-eval/src/ops_projection_ready";
import {
  personalReceiptCandidateManifestKey,
  personalReceiptCandidatePhysicalKey,
} from "../../research-mass-eval/src/personal_receipt_candidate_contract";
import type { Env } from "./index";

export const READY_ED25519_SECRET_NAME = "READY_ED25519_PRIVATE_KEY" as const;
export const READY_ED25519_KEY_ID_VAR = "READY_ED25519_KEY_ID" as const;
export const READINESS_ATTESTATION_FORMAT = "verified-readiness-attestation/v1";
export const READY_MANIFEST_FORMAT = "ready-manifest/v1";
export { READY_MANIFEST_V2_FORMAT };
const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const READY_MANIFEST_FIELDS = new Set([
  "format", "snapshot_id", "publication_scope", "profile_id", "profile_version", "profile_digest",
  "plan_ids", "plan_set_digest", "dependency_closure_digest", "universe_rule_digest",
  "resolved_universe_digest", "dataset_ids", "dataset_membership_digest", "coverage_policy_version",
  "coverage_policy_digest", "coverage_proof_digest", "raw_proof_digest", "receipt_proof_digest",
  "validation_proof_digest", "b0_proof_digest", "b4_proof_digest", "source_generation",
  "applied_sync_generation", "export_cursor", "applied_cursor", "pit_contract_digests",
  "feature_generation", "catalog_generation", "created_at", "published_at", "identity",
  "fill_contract_digest", "observed_through", "manifest_digest",
]);

export type ReadyPublicationResult =
  | {
      ok: true;
      status: "VERIFIED_PILOT_READINESS";
      ready_declared: false;
      operational_go: false;
      mass_research: "NO-GO";
      automatic_promotion: false;
      live_orders_enabled: false;
      attestation_id: string;
      snapshot_id: string;
      immutable_db_digest: string;
      envelope_key: string;
      attestation_key: string;
    }
  | {
      ok: false;
      status: "PENDING" | "HOLD" | "REJECTED";
      error: string;
      ready_declared: false;
      operational_go: false;
    };

export type ReceiptCandidatePublicationPointer = {
  job_id: string;
  environment: "production" | "staging";
};

export type ReadyPublicationCandidate = {
  environment: "production" | "staging";
  snapshot_id: string;
  physical: { key: string; digest: string; size: number };
  ready_manifest: Record<string, unknown>;
  dependency_scope_evidence: Record<string, unknown>;
  signed_projection_document: Record<string, unknown>;
};

export type ReadyPublicationEnv = Pick<
  Env,
  "STRUCTURED_BUCKET" | "OPS_PROJECTION_ENVIRONMENT" | "READY_DECLARED"
> & {
  READY_ED25519_PRIVATE_KEY?: string;
  READY_ED25519_KEY_ID?: string;
};

function authorityInstanceId(environment: string): string {
  return `ready-authority/${environment}/v1`;
}

async function digestOf(value: unknown): Promise<string> {
  return sha256Digest(canonicalJson(value));
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_RE.test(value);
}

function hexDigest(bytes: Uint8Array): string {
  return `sha256:${[...bytes]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;
}

export function providerVerifiedR2Digest(object: R2Object): string | null {
  const sha256 = object.checksums?.sha256;
  if (!(sha256 instanceof ArrayBuffer) || sha256.byteLength !== 32) return null;
  return hexDigest(new Uint8Array(sha256));
}

function verifyReadyManifestV2(manifest: Record<string, unknown>): string | null {
  const wireError = receiptNativeV2WireError(manifest);
  if (wireError) return wireError;
  const bindingError = verifyControlledPilotBinding(manifest);
  if (bindingError) return bindingError;
  if (!isRecord(manifest.source)) return "receipt-native source is missing";
  return pinReceiptNativeSource(manifest.source, String(manifest.source.environment));
}

function verifyReadyManifest(
  manifest: Record<string, unknown>,
  snapshotId: string,
): string | null {
  const keys = Object.keys(manifest);
  if (keys.length !== READY_MANIFEST_FIELDS.size ||
      keys.some((key) => !READY_MANIFEST_FIELDS.has(key))) {
    return "ReadyManifest fields are not closed";
  }
  if (manifest.format !== READY_MANIFEST_FORMAT) return "ReadyManifest format is invalid";
  const bindingError = verifyControlledPilotBinding(manifest);
  if (bindingError) return bindingError;
  if (manifest.snapshot_id !== snapshotId) return "ReadyManifest snapshot_id mismatch";
  const required = [
    "coverage_proof_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "validation_proof_digest",
    "b0_proof_digest",
    "b4_proof_digest",
    "resolved_universe_digest",
    "export_cursor",
    "applied_cursor",
    "source_generation",
    "applied_sync_generation",
    "observed_through",
  ];
  for (const field of required) {
    if (manifest[field] == null || manifest[field] === "") {
      return `missing evidence ${field}`;
    }
  }
  const digestFields = [
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
  ];
  for (const field of digestFields) {
    if (!isSha256(manifest[field])) return `malformed evidence ${field}`;
  }
  if (!isRecord(manifest.pit_contract_digests) ||
      !isSha256(manifest.pit_contract_digests.dependency_scope)) {
    return "ReadyManifest signed PIT dependency scope is missing";
  }
  return null;
}

async function importReadySigningKey(secret: string): Promise<CryptoKey> {
  const padded = secret.replace(/-/g, "+").replace(/_/g, "/");
  const binary = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
  if (binary.byteLength === 32) {
    return crypto.subtle.importKey("raw", binary, { name: "Ed25519" }, false, ["sign"]);
  }
  return crypto.subtle.importKey("pkcs8", binary, { name: "Ed25519" }, false, ["sign"]);
}

function pending(error: string): ReadyPublicationResult {
  return {
    ok: false,
    status: "PENDING",
    error,
    ready_declared: false,
    operational_go: false,
  };
}

function rejected(error: string): ReadyPublicationResult {
  return {
    ok: false,
    status: "REJECTED",
    error,
    ready_declared: false,
    operational_go: false,
  };
}

function nativePublicationVerifierFailure(error: string): ReadyPublicationResult {
  if (
    error === "CONTROLLED_AUTHORITY_UNPROVISIONED" ||
    error.includes("expired") ||
    error.includes("time-incoherent") ||
    error.includes("key window")
  ) {
    return pending(error);
  }
  return rejected(error);
}

function readyPublicationSuccess(
  attestationId: string,
  snapshotId: string,
  physicalDigest: string,
  envelopeKey: string,
  attestationKey: string,
): ReadyPublicationResult {
  return {
    ok: true,
    status: "VERIFIED_PILOT_READINESS",
    ready_declared: false,
    operational_go: false,
    mass_research: "NO-GO",
    automatic_promotion: false,
    live_orders_enabled: false,
    attestation_id: attestationId,
    snapshot_id: snapshotId,
    immutable_db_digest: physicalDigest,
    envelope_key: envelopeKey,
    attestation_key: attestationKey,
  };
}

async function signReadyAttestation(
  secret: string,
  body: Record<string, unknown>,
): Promise<string | null> {
  try {
    const key = await importReadySigningKey(secret);
    const signed = await crypto.subtle.sign(
      { name: "Ed25519" },
      key,
      new TextEncoder().encode(canonicalJson(body)),
    );
    const bytes = new Uint8Array(signed);
    let binary = "";
    for (const value of bytes) binary += String.fromCharCode(value);
    return `ed25519:${btoa(binary)}`;
  } catch {
    return null;
  }
}

function isoUtc(ms: number): string {
  return new Date(ms).toISOString().replace(/\.000Z$/, "Z");
}

function snapshotQualityBindError(
  terminal: Record<string, unknown>,
  native: Record<string, unknown>,
  physicalDigest: string,
): string | null {
  if (terminal.snapshot_quality_kind !== "receipt-candidate-snapshot-quality/v1") {
    return "snapshot quality kind is invalid";
  }
  if (!isRecord(native.source) || !isRecord(terminal.snapshot_quality)) {
    return "snapshot quality payload is missing";
  }
  return verifyReceiptNativeSnapshotQuality(
    terminal.snapshot_quality,
    native,
    physicalDigest,
  );
}

export async function publishPilotReady(
  env: ReadyPublicationEnv,
  candidate: ReadyPublicationCandidate,
): Promise<ReadyPublicationResult> {
  const secret = env.READY_ED25519_PRIVATE_KEY;
  const keyId = env.READY_ED25519_KEY_ID;
  if (typeof secret !== "string" || !secret.trim()) {
    return pending("READY_ED25519_PRIVATE_KEY unprovisioned");
  }
  if (typeof keyId !== "string" || !keyId.trim()) {
    return pending("READY_ED25519_KEY_ID unprovisioned");
  }
  if (String(env.READY_DECLARED) !== "false") {
    return pending("READY_DECLARED remains false; publication cannot arm GO");
  }
  if (!isRecord(candidate) || !isRecord(candidate.physical) ||
      !isRecord(candidate.ready_manifest) ||
      !isRecord(candidate.dependency_scope_evidence) ||
      !isRecord(candidate.signed_projection_document)) {
    return rejected("READY candidate is malformed");
  }
  if (candidate.ready_manifest.format === READY_MANIFEST_V2_FORMAT) {
    const v2Error = verifyReadyManifestV2(candidate.ready_manifest);
    if (v2Error) return rejected(v2Error);
    const declared = candidate.ready_manifest.manifest_digest;
    const digest = await receiptNativeManifestBodyDigest(candidate.ready_manifest);
    if (declared !== digest) {
      return rejected("ReadyManifest manifest_digest mismatch");
    }
    return pending(
      "receipt-native ready-manifest/v2 is not supported for attestation",
    );
  }
  if (candidate.environment !== "production" && candidate.environment !== "staging") {
    return rejected("READY environment is invalid");
  }
  if (env.OPS_PROJECTION_ENVIRONMENT !== candidate.environment) {
    return rejected("READY environment does not match OPS_PROJECTION_ENVIRONMENT");
  }
  const physical = candidate.physical;
  if (
    !isSha256(candidate.snapshot_id) ||
    !isSha256(physical.digest) ||
    physical.digest === candidate.snapshot_id ||
    typeof physical.key !== "string" ||
    typeof physical.size !== "number" ||
    !Number.isSafeInteger(physical.size) ||
    physical.size < 1 ||
    physical.size > PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES ||
    physical.key !== controlledPhysicalSnapshotKey(physical.digest)
  ) {
    return rejected("READY physical snapshot identity is invalid");
  }
  const manifestError = verifyReadyManifest(
    candidate.ready_manifest,
    candidate.snapshot_id,
  );
  if (manifestError) return rejected(manifestError);

  const projection = await verifyOpsProjectionReady(
    candidate.signed_projection_document,
    candidate.dependency_scope_evidence,
    candidate.ready_manifest,
    candidate.environment,
  );
  if (!projection.ok) {
    return projection.status === "PENDING"
      ? pending(projection.error)
      : rejected(projection.error);
  }
  if (projection.value.session_scope.physical_db_digest !== physical.digest) {
    return rejected("signed Ops Projection physical snapshot digest mismatch");
  }

  const object = await env.STRUCTURED_BUCKET.head(physical.key);
  if (!object) return rejected("READY snapshot object is missing");
  if (object.size !== physical.size) return rejected("READY snapshot size mismatch");
  const providerDigest = providerVerifiedR2Digest(object);
  if (!providerDigest) return rejected("READY snapshot provider SHA-256 checksum is missing");
  if (providerDigest !== physical.digest) return rejected("caller digest mismatch");

  const manifestBody = { ...candidate.ready_manifest };
  delete manifestBody.manifest_digest;
  const readyManifestDigest = await digestOf(manifestBody);
  if (!isSha256(candidate.ready_manifest.manifest_digest) ||
      candidate.ready_manifest.manifest_digest !== readyManifestDigest) {
    return rejected("ReadyManifest digest mismatch");
  }
  const evidenceDigest = await digestOf({
    manifest: candidate.ready_manifest,
    immutable_db_digest: physical.digest,
  });
  const authorityResourceDigest = await digestOf({
    format: "ready-authority-resource/v1",
    environment: candidate.environment,
    authority_instance_id: authorityInstanceId(candidate.environment),
    snapshot_id: candidate.snapshot_id,
    immutable_db_digest: physical.digest,
    ready_manifest_digest: readyManifestDigest,
    signed_projection_document_digest: projection.value.document_digest,
  });
  const verifiedAt = String(candidate.ready_manifest.published_at || "");
  const verifiedAtMs = parseCanonicalUtc(verifiedAt);
  if (!Number.isFinite(verifiedAtMs) || verifiedAtMs > Date.now() + 5 * 60_000) {
    return rejected("ReadyManifest publication time is invalid");
  }
  const expiresAtMs = verifiedAtMs + 3600_000;
  if (Date.now() > expiresAtMs) {
    return pending("ReadyManifest publication window expired");
  }
  const expiresAt = new Date(expiresAtMs).toISOString().replace(/\.000Z$/, "Z");
  const attestationId = `ready-${authorityResourceDigest.slice("sha256:".length)}`;
  const body: Record<string, unknown> = {
    format: READINESS_ATTESTATION_FORMAT,
    attestation_id: attestationId,
    environment: candidate.environment,
    authority_instance_id: authorityInstanceId(candidate.environment),
    authority_resource_digest: authorityResourceDigest,
    signed_projection_document_digest: projection.value.document_digest,
    readiness_scope: "PILOT",
    identity: CONTROLLED_PILOT_IDENTITY,
    snapshot_id: candidate.snapshot_id,
    profile_id: EXACT_FOUR_PROFILE_ID,
    profile_version: EXACT_FOUR_PROFILE_VERSION,
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    plan_ids: [...EXACT_FOUR_PLAN_IDS],
    plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    universe_rule_digest: EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    resolved_universe_digest: candidate.ready_manifest.resolved_universe_digest,
    dataset_ids: [...EXACT_FOUR_DATASET_IDS],
    ready_state: "READY",
    ready_manifest_digest: readyManifestDigest,
    immutable_db_digest: physical.digest,
    coverage_policy_version: EXACT_FOUR_COVERAGE_POLICY_VERSION,
    coverage_policy_digest: EXACT_FOUR_COVERAGE_POLICY_DIGEST,
    coverage_proof_digest: candidate.ready_manifest.coverage_proof_digest,
    governed_membership_digest: EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST,
    raw_proof_digest: candidate.ready_manifest.raw_proof_digest,
    receipt_proof_digest: candidate.ready_manifest.receipt_proof_digest,
    validation_proof_digest: candidate.ready_manifest.validation_proof_digest,
    b0_quality_proof_digest: candidate.ready_manifest.b0_proof_digest,
    b4_quality_proof_digest: candidate.ready_manifest.b4_proof_digest,
    source_generation: candidate.ready_manifest.source_generation,
    export_cursor: candidate.ready_manifest.export_cursor,
    applied_cursor: candidate.ready_manifest.applied_cursor,
    verified_at: verifiedAt,
    expires_at: expiresAt,
    evidence_digest: evidenceDigest,
    key_id: keyId.trim(),
    issuer: "ReadyPublicationService/v3",
    fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
  };
  const signature = await signReadyAttestation(secret.trim(), body);
  if (!signature) return pending("READY_ED25519_PRIVATE_KEY unusable");
  const attestation = { ...body, signature };
  const envelope = {
    format: CONTROLLED_READY_ENVELOPE_FORMAT,
    identity: CONTROLLED_PILOT_IDENTITY,
    environment: candidate.environment,
    attestation,
    ready_manifest: candidate.ready_manifest,
    dependency_scope_evidence: candidate.dependency_scope_evidence,
    signed_projection_document: candidate.signed_projection_document,
    controlled_session_scope: projection.value.session_scope satisfies ControlledSessionScope,
    physical: {
      key: physical.key,
      digest: physical.digest,
      size: physical.size,
    },
  };
  const envelopeKey = controlledReadyKey(attestationId);
  const attestationKey = `${envelopeKey}.attestation.json`;
  const attestationPut = await putJsonCreateOnly(
    env.STRUCTURED_BUCKET,
    attestationKey,
    attestation,
  );
  if (attestationPut.conflict) return rejected("conflicting READY attestation");
  const envelopePut = await putJsonCreateOnly(
    env.STRUCTURED_BUCKET,
    envelopeKey,
    envelope,
  );
  if (envelopePut.conflict) return rejected("conflicting READY envelope");
  return readyPublicationSuccess(
    attestationId,
    candidate.snapshot_id,
    physical.digest,
    envelopeKey,
    attestationKey,
  );
}

export class PilotReadyPublicationService extends WorkerEntrypoint<Env> {
  override fetch(): Promise<Response> {
    return Promise.resolve(
      new Response(JSON.stringify({ error: "not_found", ready_declared: false }), {
        status: 404,
        headers: { "content-type": "application/json; charset=utf-8" },
      }),
    );
  }

  publishPilotReady(candidate: ReadyPublicationCandidate): Promise<ReadyPublicationResult> {
    return publishPilotReady(this.env, candidate);
  }

  publishAdmittedReceiptCandidate(
    pointer: ReceiptCandidatePublicationPointer,
  ): Promise<ReadyPublicationResult> {
    return publishAdmittedReceiptCandidate(this.env, pointer);
  }
}

async function qualityProofDigest(
  quality: Record<string, unknown>,
  field: "b0" | "b4",
): Promise<string> {
  return digestOf({
    physical_digest: quality.physical_digest,
    profile_digest: quality.profile_digest,
    plan_set_digest: quality.plan_set_digest,
    dependency_closure_digest: quality.dependency_closure_digest,
    receipt_runset_digest: quality.receipt_runset_digest,
    period_start: quality.period_start,
    period_end: quality.period_end,
    observation_policy: quality.observation_policy,
    observed_through: quality.observed_through,
    [field]: quality[field],
  });
}

const RECEIPT_CANDIDATE_TERMINAL_MAX_BYTES = 64 * 1024;

async function readBoundedJson(
  object: { size: number; arrayBuffer(): Promise<ArrayBuffer> },
  maximum: number,
): Promise<Record<string, unknown> | null> {
  if (!Number.isSafeInteger(object.size) || object.size < 1 || object.size > maximum) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(
      new TextDecoder().decode(await object.arrayBuffer()),
    );
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

async function recoverNativeEnvelope(
  env: ReadyPublicationEnv,
  stored: Record<string, unknown>,
  expected: {
    jobId: string;
    environment: "production" | "staging";
    snapshotId: string;
    physicalDigest: string;
    admittedNativeDigest: string;
    envelopeKey: string;
    attestationKey: string;
  },
): Promise<ReadyPublicationResult> {
  const verified = await verifyReceiptNativeReadyPublication(
    stored,
    expected.snapshotId,
    expected.environment,
  );
  if (!verified.ok) return nativePublicationVerifierFailure(verified.error);
  if (
    verified.publication.job_id !== expected.jobId ||
    verified.publication.admitted_native_digest !== expected.admittedNativeDigest ||
    verified.publication.immutable_db_digest !== expected.physicalDigest
  ) {
    return rejected("existing READY envelope does not match this job/source");
  }
  if (!isRecord(stored.attestation)) {
    return rejected("existing READY envelope attestation is missing");
  }
  const sidecar = await putJsonCreateOnly(
    env.STRUCTURED_BUCKET,
    expected.attestationKey,
    stored.attestation,
  );
  if (sidecar.conflict) return rejected("conflicting READY attestation");
  return readyPublicationSuccess(
    verified.publication.attestation_id,
    expected.snapshotId,
    expected.physicalDigest,
    expected.envelopeKey,
    expected.attestationKey,
  );
}

export async function publishAdmittedReceiptCandidate(
  env: ReadyPublicationEnv,
  pointer: ReceiptCandidatePublicationPointer,
): Promise<ReadyPublicationResult> {
  const secret = env.READY_ED25519_PRIVATE_KEY;
  const keyId = env.READY_ED25519_KEY_ID;
  if (typeof secret !== "string" || !secret.trim()) {
    return pending("READY_ED25519_PRIVATE_KEY unprovisioned");
  }
  if (typeof keyId !== "string" || !keyId.trim()) {
    return pending("READY_ED25519_KEY_ID unprovisioned");
  }
  if (String(env.READY_DECLARED) !== "false") {
    return pending("READY_DECLARED remains false; publication cannot arm GO");
  }
  if (
    !isRecord(pointer) ||
    typeof pointer.job_id !== "string" ||
    (pointer.environment !== "production" && pointer.environment !== "staging")
  ) {
    return rejected("READY pointer is malformed");
  }
  if (env.OPS_PROJECTION_ENVIRONMENT !== pointer.environment) {
    return rejected("READY environment does not match OPS_PROJECTION_ENVIRONMENT");
  }
  let terminalKey: string;
  try {
    terminalKey = personalReceiptCandidateManifestKey(pointer.job_id);
  } catch {
    return rejected("READY pointer job_id is invalid");
  }
  const terminalObject = await env.STRUCTURED_BUCKET.get(terminalKey);
  if (!terminalObject) return rejected("admitted receipt candidate terminal is missing");
  const terminal = await readBoundedJson(
    terminalObject,
    RECEIPT_CANDIDATE_TERMINAL_MAX_BYTES,
  );
  if (!terminal) return rejected("admitted receipt candidate terminal is not JSON");
  if (
    terminal.status !== "COMPLETED" ||
    terminal.compiled_scope_status !== "PASS" ||
    terminal.job_id !== pointer.job_id ||
    !isRecord(terminal.receipt_native_manifest)
  ) {
    return rejected("admitted receipt candidate is not a compiled PASS native terminal");
  }
  const native = { ...terminal.receipt_native_manifest };
  const wire = verifyReadyManifestV2(native);
  if (wire) return rejected(wire);
  if (!isRecord(native.source)) return rejected("receipt-native source is missing");
  if (native.source.environment !== pointer.environment) {
    return rejected("receipt-native source environment does not match publication environment");
  }
  const storedDigest = await receiptNativeManifestBodyDigest(native);
  if (
    native.manifest_digest !== storedDigest ||
    terminal.receipt_native_manifest_digest !== storedDigest
  ) {
    return rejected("receipt-native manifest_digest mismatch");
  }
  const snapshotId = await receiptNativeSnapshotId(native.source);
  if (native.snapshot_id !== snapshotId) {
    return rejected("receipt-native snapshot_id does not match source");
  }
  const physicalDigest = native.source.physical_digest;
  if (typeof physicalDigest !== "string" || !isSha256(physicalDigest)) {
    return rejected("receipt-native physical_digest is invalid");
  }
  if (physicalDigest === snapshotId) {
    return rejected("receipt-native physical digest collides with snapshot_id");
  }
  const rawHex = physicalDigest.slice("sha256:".length);
  const physicalKey =
    typeof terminal.physical_key === "string" ? terminal.physical_key : "";
  if (physicalKey !== personalReceiptCandidatePhysicalKey(rawHex)) {
    return rejected("admitted physical_key does not match source.physical_digest");
  }
  if (
    terminal.raw_sha256 !== physicalDigest ||
    terminal.compiled_scope_physical_digest !== physicalDigest
  ) {
    return rejected("admitted physical digest correlation failed");
  }
  const physicalObject = await env.STRUCTURED_BUCKET.head(physicalKey);
  if (!physicalObject) return rejected("READY physical object is missing");
  const providerDigest = providerVerifiedR2Digest(physicalObject);
  if (!providerDigest) return rejected("READY physical provider SHA-256 checksum is missing");
  if (providerDigest !== physicalDigest) {
    return rejected("READY physical provider SHA-256 mismatch");
  }
  if (
    !Number.isSafeInteger(physicalObject.size) ||
    physicalObject.size < 1 ||
    physicalObject.size > PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES
  ) {
    return rejected("READY physical size is invalid");
  }
  const qualityBind = snapshotQualityBindError(terminal, native, physicalDigest);
  if (qualityBind) return rejected(qualityBind);
  const quality = terminal.snapshot_quality as Record<string, unknown>;
  const qualityDigest = await digestOf(quality);
  if (
    terminal.snapshot_quality_digest !== qualityDigest ||
    terminal.validation_proof_digest !== qualityDigest ||
    native.validation_proof_digest !== qualityDigest
  ) {
    return rejected("snapshot_quality_digest does not match measured quality payload");
  }
  const expectedB0 = await qualityProofDigest(quality, "b0");
  const expectedB4 = await qualityProofDigest(quality, "b4");
  if (
    native.b0_proof_digest !== expectedB0 ||
    native.b4_proof_digest !== expectedB4 ||
    terminal.b0_proof_digest !== expectedB0 ||
    terminal.b4_proof_digest !== expectedB4
  ) {
    return rejected("B0/B4 proof digest does not match PASS quality payload");
  }
  const proofDigest = terminal.compiled_scope_proof_digest;
  const scopeKey =
    typeof terminal.dependency_scope_key === "string" ? terminal.dependency_scope_key : "";
  if (typeof proofDigest !== "string" || !isSha256(proofDigest) || !scopeKey) {
    return rejected("admitted dependency-scope sidecar is missing");
  }
  if (native.source.compiled_scope_proof_digest !== proofDigest) {
    return rejected("compiled_scope_proof_digest does not bind native source");
  }
  if (
    !isRecord(native.pit_contract_digests) ||
    native.pit_contract_digests.dependency_scope !== proofDigest
  ) {
    return pending("receipt-native pit dependency_scope is not a measured digest");
  }
  for (const field of [
    "coverage_proof_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "resolved_universe_digest",
    "feature_generation",
    "catalog_generation",
  ] as const) {
    if (!isSha256(native[field])) {
      return pending(`receipt-native ${field} is not a measured digest`);
    }
  }
  const scopeObject = await env.STRUCTURED_BUCKET.get(scopeKey);
  if (!scopeObject) return rejected("dependency-scope sidecar is missing");
  const scopeProvider = providerVerifiedR2Digest(scopeObject);
  if (scopeProvider !== proofDigest) {
    return rejected("dependency-scope provider SHA-256 mismatch");
  }
  const unsignedScope = await readBoundedJson(
    scopeObject,
    CREATE_ONLY_COMPARE_MAX_BYTES,
  );
  if (!unsignedScope || "proof_digest" in unsignedScope) {
    return rejected("dependency-scope sidecar is not an unsigned JSON body");
  }
  const evidence: Record<string, unknown> = {
    ...unsignedScope,
    proof_digest: proofDigest,
  };
  if (
    evidence.profile_digest !== EXACT_FOUR_PROFILE_DIGEST ||
    evidence.plan_set_digest !== EXACT_FOUR_PLAN_SET_DIGEST ||
    evidence.dependency_closure_digest !== EXACT_FOUR_CLOSURE_DIGEST ||
    evidence.universe_rule_digest !== EXACT_FOUR_UNIVERSE_RULE_DIGEST ||
    evidence.resolved_universe_digest !== native.resolved_universe_digest
  ) {
    return rejected("dependency-scope does not bind exact-four profile/plans/closure");
  }
  const scopePeriodError = verifyReceiptNativePeriod(
    evidence.period_start,
    evidence.period_end,
  );
  if (scopePeriodError) {
    return rejected(`dependency-scope ${scopePeriodError}`);
  }
  if (native.source.compiled_scope_proof_digest !== proofDigest) {
    return rejected("compiled_scope_proof_digest does not bind native source");
  }
  const observedThrough = String(native.source.observed_through);
  const session = await deriveReceiptNativeSessionScope(
    evidence,
    physicalDigest,
    observedThrough,
  );
  if (!session) return rejected("dependency-scope evidence is not exact-four PASS");
  const admittedNativeDigest = storedDigest;
  const authorityResourceDigest = await digestOf({
    format: "ready-authority-resource/receipt-native/v1",
    environment: pointer.environment,
    authority_instance_id: authorityInstanceId(pointer.environment),
    job_id: pointer.job_id,
    snapshot_id: snapshotId,
    immutable_db_digest: physicalDigest,
    unsigned_native_digest: admittedNativeDigest,
    compiled_scope_proof_digest: proofDigest,
  });
  const attestationId = `ready-${authorityResourceDigest.slice("sha256:".length)}`;
  const envelopeKey = controlledReadyKey(attestationId);
  const attestationKey = `${envelopeKey}.attestation.json`;
  const expectedWinner = {
    jobId: pointer.job_id,
    environment: pointer.environment,
    snapshotId,
    physicalDigest,
    admittedNativeDigest,
    envelopeKey,
    attestationKey,
  };
  const existing = await env.STRUCTURED_BUCKET.get(envelopeKey);
  if (existing) {
    const parsed = await readBoundedJson(existing, CREATE_ONLY_COMPARE_MAX_BYTES);
    if (!parsed) return rejected("existing READY envelope is not JSON");
    return recoverNativeEnvelope(env, parsed, expectedWinner);
  }
  const keys = await loadPinnedReadyKeys(pointer.environment);
  if (keys.length === 0) {
    return pending("CONTROLLED_AUTHORITY_UNPROVISIONED");
  }
  const active = keys.filter((key) => key.status === "active");
  if (active.length !== 1) {
    return pending("CONTROLLED_AUTHORITY_UNPROVISIONED");
  }
  const registryKey = active[0]!;
  if (registryKey.key_id !== keyId.trim()) {
    return rejected("READY attestation issuer is not trusted");
  }
  const verifiedAtMs = Date.now();
  if (!keyUsableAt(registryKey, verifiedAtMs)) {
    return pending("READY key window denied");
  }
  const verifiedAt = isoUtc(verifiedAtMs);
  const expiresAt = isoUtc(verifiedAtMs + 3600_000);
  const publicationManifest: Record<string, unknown> = {
    ...native,
    created_at: verifiedAt,
    published_at: verifiedAt,
  };
  delete publicationManifest.manifest_digest;
  publicationManifest.manifest_digest = await digestOf(publicationManifest);
  const evidenceDigest = await digestOf({
    manifest: publicationManifest,
    immutable_db_digest: physicalDigest,
  });
  const body: Record<string, unknown> = {
    format: READINESS_ATTESTATION_FORMAT,
    attestation_id: attestationId,
    environment: pointer.environment,
    authority_instance_id: authorityInstanceId(pointer.environment),
    authority_resource_digest: authorityResourceDigest,
    readiness_scope: "PILOT",
    identity: CONTROLLED_PILOT_IDENTITY,
    snapshot_id: snapshotId,
    profile_id: EXACT_FOUR_PROFILE_ID,
    profile_version: EXACT_FOUR_PROFILE_VERSION,
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    plan_ids: [...EXACT_FOUR_PLAN_IDS],
    plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    universe_rule_digest: EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    resolved_universe_digest: publicationManifest.resolved_universe_digest,
    dataset_ids: [...EXACT_FOUR_DATASET_IDS],
    ready_state: "READY",
    ready_manifest_digest: publicationManifest.manifest_digest,
    immutable_db_digest: physicalDigest,
    coverage_policy_version: EXACT_FOUR_COVERAGE_POLICY_VERSION,
    coverage_policy_digest: EXACT_FOUR_COVERAGE_POLICY_DIGEST,
    coverage_proof_digest: publicationManifest.coverage_proof_digest,
    governed_membership_digest: EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST,
    raw_proof_digest: publicationManifest.raw_proof_digest,
    receipt_proof_digest: publicationManifest.receipt_proof_digest,
    validation_proof_digest: publicationManifest.validation_proof_digest,
    b0_quality_proof_digest: publicationManifest.b0_proof_digest,
    b4_quality_proof_digest: publicationManifest.b4_proof_digest,
    verified_at: verifiedAt,
    expires_at: expiresAt,
    evidence_digest: evidenceDigest,
    key_id: keyId.trim(),
    issuer: "ReadyPublicationService/v3",
    fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
  };
  const signature = await signReadyAttestation(secret.trim(), body);
  if (!signature) return pending("READY_ED25519_PRIVATE_KEY unusable");
  const attestation = { ...body, signature };
  const envelope = {
    format: CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT,
    identity: CONTROLLED_PILOT_IDENTITY,
    environment: pointer.environment,
    job_id: pointer.job_id,
    admitted_native_digest: admittedNativeDigest,
    attestation,
    ready_manifest: publicationManifest,
    dependency_scope_evidence: evidence,
    controlled_session_scope: session,
    physical: {
      key: physicalKey,
      digest: physicalDigest,
      size: physicalObject.size,
    },
  };
  if (serializedJsonBytes(envelope).byteLength > CREATE_ONLY_COMPARE_MAX_BYTES) {
    return rejected("READY envelope exceeds create-only JSON cap");
  }
  const verified = await verifyReceiptNativeReadyPublication(
    envelope,
    snapshotId,
    pointer.environment,
  );
  if (!verified.ok) return nativePublicationVerifierFailure(verified.error);
  const envelopePut = await putJsonCreateOnly(
    env.STRUCTURED_BUCKET,
    envelopeKey,
    envelope,
  );
  if (envelopePut.conflict) {
    const raced = await env.STRUCTURED_BUCKET.get(envelopeKey);
    if (!raced) return rejected("conflicting READY envelope");
    const parsed = await readBoundedJson(raced, CREATE_ONLY_COMPARE_MAX_BYTES);
    if (!parsed) return rejected("conflicting READY envelope");
    return recoverNativeEnvelope(env, parsed, expectedWinner);
  }
  const sidecar = await putJsonCreateOnly(
    env.STRUCTURED_BUCKET,
    attestationKey,
    attestation,
  );
  if (sidecar.conflict) return rejected("conflicting READY attestation");
  return readyPublicationSuccess(
    verified.publication.attestation_id,
    snapshotId,
    physicalDigest,
    envelopeKey,
    attestationKey,
  );
}
