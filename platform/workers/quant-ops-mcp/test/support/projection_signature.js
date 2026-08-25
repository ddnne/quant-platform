/** Tests-only ephemeral Ops Projection verifier. Never imported by src/. */

import { canonicalProjectionBytes } from "../../src/projection_signature.js";

const SIGNED_DOCUMENT_SCHEMA = "ops-projection-signed-envelope/v1";
const ENVELOPE_SCHEMA = "ops-projection-envelope/v1";

/** @param {string} value */
function decodeBase64(value) {
  try {
    const binary = atob(value);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

/** @param {Record<string, unknown>} envelope */
function validateEnvelope(envelope) {
  if (envelope.schema_version !== ENVELOPE_SCHEMA) return "unsupported envelope schema";
  const required = [
    "generation_id", "content_digest", "source_db_digest", "generated_at",
    "producer_commit_sha", "contract_digest", "registry_digest",
    "coverage_policy_version", "coverage_policy_digest", "projection_status",
    "source_generation", "source_snapshot_generation", "source_cursor",
    "export_cursor", "applied_cursor", "coverage_status_digest", "b0_status",
    "b0_evidence_digest", "b4_status", "b4_evidence_digest",
    "dataset_coverage", "evidence_digests", "content_manifest", "row_counts",
  ];
  if (required.some((field) => !Object.hasOwn(envelope, field))) {
    return "envelope fields are incomplete";
  }
  return null;
}

/**
 * @param {Record<string, unknown>} generation
 * @param {Record<string, unknown>} registry
 */
export async function verifyTestProjectionGeneration(generation, registry) {
  if (registry.purpose !== "ops_projection_verification" ||
      registry.authority_status !== "ACTIVE" || !Array.isArray(registry.keys)) {
    return { ok: false, reason: "test registry is invalid", envelope: null };
  }
  if (typeof generation.signed_envelope_json !== "string" ||
      typeof generation.issuer_key_id !== "string" ||
      typeof generation.signature !== "string") {
    return { ok: false, reason: "active Ops Projection generation is unsigned", envelope: null };
  }
  let rawDocument;
  try {
    rawDocument = JSON.parse(generation.signed_envelope_json);
  } catch {
    return { ok: false, reason: "signed Ops Projection envelope is invalid JSON", envelope: null };
  }
  if (!rawDocument || typeof rawDocument !== "object" || Array.isArray(rawDocument)) {
    return { ok: false, reason: "signed Ops Projection envelope is malformed", envelope: null };
  }
  const document = /** @type {Record<string, unknown>} */ (rawDocument);
  if (document.schema_version !== SIGNED_DOCUMENT_SCHEMA ||
      document.algorithm !== "Ed25519" ||
      document.issuer_key_id !== generation.issuer_key_id ||
      document.signature !== generation.signature ||
      !document.envelope || typeof document.envelope !== "object" ||
      Array.isArray(document.envelope)) {
    return { ok: false, reason: "signed Ops Projection document shape is invalid", envelope: null };
  }
  const envelope = /** @type {Record<string, unknown>} */ (document.envelope);
  const envelopeError = validateEnvelope(envelope);
  if (envelopeError) return { ok: false, reason: envelopeError, envelope: null };
  if (envelope.generation_id !== generation.generation_id ||
      envelope.content_digest !== generation.content_digest ||
      envelope.source_db_digest !== generation.source_db_digest ||
      envelope.producer_commit_sha !== generation.producer_commit_sha ||
      envelope.contract_digest !== generation.contract_digest ||
      envelope.registry_digest !== generation.registry_digest ||
      envelope.coverage_policy_version !== generation.coverage_policy_version) {
    return { ok: false, reason: "signed envelope does not bind the selected generation", envelope: null };
  }
  const keyRow = registry.keys.find((candidate) => candidate &&
    typeof candidate === "object" && !Array.isArray(candidate) &&
    candidate.key_id === generation.issuer_key_id &&
    candidate.algorithm === "Ed25519" && candidate.status === "active");
  if (!keyRow || typeof keyRow !== "object" || Array.isArray(keyRow)) {
    return { ok: false, reason: "Ops Projection issuer is not trusted", envelope: null };
  }
  const publicKey = decodeBase64(String(keyRow.public_key_base64 || ""));
  const signatureValue = String(generation.signature);
  const signature = signatureValue.startsWith("ed25519:")
    ? decodeBase64(signatureValue.slice("ed25519:".length))
    : null;
  if (!publicKey || publicKey.byteLength !== 32 || !signature) {
    return { ok: false, reason: "Ops Projection signature material is malformed", envelope: null };
  }
  const body = {
    schema_version: SIGNED_DOCUMENT_SCHEMA,
    algorithm: "Ed25519",
    issuer_key_id: generation.issuer_key_id,
    envelope,
  };
  try {
    const key = await crypto.subtle.importKey(
      "raw", publicKey, { name: "Ed25519" }, false, ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "Ed25519" }, key, signature, canonicalProjectionBytes(body),
    );
    return valid
      ? { ok: true, reason: null, envelope }
      : { ok: false, reason: "Ops Projection signature is invalid", envelope: null };
  } catch {
    return { ok: false, reason: "Ops Projection signature verification failed", envelope: null };
  }
}

/** @param {Record<string, unknown>} registry */
export function makeTestProjectionVerifier(registry) {
  return (generation) => verifyTestProjectionGeneration(generation, registry);
}
