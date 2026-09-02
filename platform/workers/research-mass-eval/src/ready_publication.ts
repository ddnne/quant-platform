import { WorkerEntrypoint } from "cloudflare:workers";

import { putJsonCreateOnly } from "./http";
import {
  CONTROLLED_FILL_CONTRACT_DIGEST,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_READY_ENVELOPE_FORMAT,
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
} from "./controlled_pilot_contract";
import {
  canonicalJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
} from "./controlled_pilot_json";
import { PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES } from "./personal_research_contract";
import {
  verifyOpsProjectionReady,
  type ControlledSessionScope,
} from "./ops_projection_ready";
import type { Env } from "./types";

export const READY_ED25519_SECRET_NAME = "READY_ED25519_PRIVATE_KEY" as const;
export const READY_ED25519_KEY_ID_VAR = "READY_ED25519_KEY_ID" as const;
export const READINESS_ATTESTATION_FORMAT = "verified-readiness-attestation/v1";
export const READY_MANIFEST_FORMAT = "ready-manifest/v1";
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

export type ReadyPublicationCandidate = {
  environment: "production" | "staging";
  snapshot_id: string;
  physical: { key: string; digest: string; size: number };
  ready_manifest: Record<string, unknown>;
  dependency_scope_evidence: Record<string, unknown>;
  signed_projection_document: Record<string, unknown>;
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

function equalStringArrays(left: unknown, right: readonly string[]): boolean {
  return (
    Array.isArray(left) &&
    left.length === right.length &&
    left.every((item, index) => item === right[index])
  );
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
  if (manifest.identity !== CONTROLLED_PILOT_IDENTITY) {
    return "ReadyManifest identity is invalid";
  }
  if (manifest.publication_scope !== "PILOT") return "ReadyManifest scope is not PILOT";
  if (manifest.snapshot_id !== snapshotId) return "ReadyManifest snapshot_id mismatch";
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

export async function publishPilotReady(
  env: Env & {
    READY_ED25519_PRIVATE_KEY?: string;
    READY_ED25519_KEY_ID?: string;
  },
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
  if (candidate.environment !== "production" && candidate.environment !== "staging") {
    return rejected("READY environment is invalid");
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
  let signature: string;
  try {
    const key = await importReadySigningKey(secret.trim());
    const signed = await crypto.subtle.sign(
      { name: "Ed25519" },
      key,
      new TextEncoder().encode(canonicalJson(body)),
    );
    const bytes = new Uint8Array(signed);
    let binary = "";
    for (const value of bytes) binary += String.fromCharCode(value);
    signature = `ed25519:${btoa(binary)}`;
  } catch {
    return pending("READY_ED25519_PRIVATE_KEY unusable");
  }
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
  return {
    ok: true,
    status: "VERIFIED_PILOT_READINESS",
    ready_declared: false,
    operational_go: false,
    mass_research: "NO-GO",
    automatic_promotion: false,
    live_orders_enabled: false,
    attestation_id: attestationId,
    snapshot_id: candidate.snapshot_id,
    immutable_db_digest: physical.digest,
    envelope_key: envelopeKey,
    attestation_key: attestationKey,
  };
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
}
