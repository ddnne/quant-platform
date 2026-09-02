/** Public-key-only verification for signed Ops Projection generation rows. */

import pinnedRegistryDocument from "../../../../specs/ops_projection/verify_public_keys.json" with { type: "json" };
import pinnedStagingRegistryDocument from "../../../../specs/ops_projection/verify_public_keys.staging.json" with { type: "json" };

const SIGNED_DOCUMENT_SCHEMA = "ops-projection-signed-envelope/v1";
const ENVELOPE_SCHEMA = "ops-projection-envelope/v1";
const REGISTRY_PURPOSE = "ops_projection_verification";
export const PINNED_OPS_PROJECTION_REGISTRY_GENERATION = 3;
export const PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST =
  "sha256:bb1dc1ae823784db8b53147891d425b027c02cbf022023a74affa2ce46909abe";
export const PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST =
  "sha256:32bd179616eb9e848a47d56c38c2e12b243249b05321a0999fed53d22cd47362";
export const PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST =
  "sha256:5bebf8906b263fd9a2edf295a4e1e64e0a5a7e52bb3160123c455ebc3d39dadb";
export const PINNED_STAGING_OPS_PROJECTION_REGISTRY_GENERATION = 2;
export const PINNED_STAGING_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST = null;
export const PINNED_STAGING_OPS_PROJECTION_REGISTRY_BODY_DIGEST =
  "sha256:c97a025ecf3525e8405cac95ffae73393e687ecba5111165a8a71d4ebc99af1e";
export const PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST =
  "sha256:093fb04a3530cb094b4c4eaf2bbd92f9813706c12a885aa70931fbc4d605b7b9";

const CANONICAL_UTC = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;

/** @param {unknown} value */
function requireCanonicalUtc(value) {
  if (typeof value !== "string" || CANONICAL_UTC.test(value) === false) return null;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return null;
  const canonical = new Date(parsed).toISOString().replace(/\.\d{3}Z$/, "Z");
  return canonical === value ? value : null;
}

/** @param {unknown} value @returns {unknown} */
function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(/** @type {Record<string, unknown>} */ (value))
        .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

/** @param {unknown} value */
export function canonicalProjectionJson(value) {
  return JSON.stringify(canonicalize(value));
}

/** @param {unknown} value */
export function canonicalProjectionBytes(value) {
  return new TextEncoder().encode(canonicalProjectionJson(value));
}

/** @param {unknown} value */
export async function projectionSha256(value) {
  const raw = await crypto.subtle.digest("SHA-256", canonicalProjectionBytes(value));
  return "sha256:" + Array.from(new Uint8Array(raw))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/** @param {string} value */
function decodeBase64(value) {
  try {
    const binary = atob(value);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

/** @param {unknown} value */
function parsePinnedProjectionKeyRegistry(value, environment = "production") {
  let document = value;
  if (typeof value === "string") {
    try {
      document = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!document || typeof document !== "object" || Array.isArray(document)) return null;
  const registry = /** @type {Record<string, unknown>} */ (document);
  const expectedGeneration = environment === "staging"
    ? PINNED_STAGING_OPS_PROJECTION_REGISTRY_GENERATION
    : PINNED_OPS_PROJECTION_REGISTRY_GENERATION;
  const expectedPrior = environment === "staging"
    ? PINNED_STAGING_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST
    : PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST;
  if (Object.keys(registry).sort().join("\0") !==
      "authority_instance\0authority_status\0generation\0keys\0prior_registry_digest\0purpose\0registry_digest\0schema_version" ||
      registry.schema_version !== 3 || registry.purpose !== REGISTRY_PURPOSE ||
      registry.generation !== expectedGeneration ||
      registry.authority_instance !== "ops-projection-cloud" ||
      !["ACTIVE", "PENDING"].includes(String(registry.authority_status)) ||
      registry.prior_registry_digest !== expectedPrior ||
      !/^sha256:[0-9a-f]{64}$/.test(String(registry.registry_digest || "")) ||
      (registry.prior_registry_digest !== null &&
       !/^sha256:[0-9a-f]{64}$/.test(String(registry.prior_registry_digest))) ||
      !Array.isArray(registry.keys) || registry.keys.length > 16) return null;
  const keyIds = new Set();
  let active = 0;
  for (const candidate of registry.keys) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
    const row = /** @type {Record<string, unknown>} */ (candidate);
    if (Object.keys(row).sort().join("\0") !==
        "algorithm\0environment\0key_id\0not_after\0not_before\0public_key_base64\0revoked_at\0status" ||
        typeof row.key_id !== "string" || !row.key_id ||
        row.algorithm !== "Ed25519" ||
        !["production", "staging"].includes(String(row.environment)) ||
        !["active", "pending", "revoked"].includes(String(row.status)) ||
        typeof row.not_before !== "string" || typeof row.not_after !== "string" ||
        (row.status === "revoked" && (row.revoked_at == null || row.revoked_at === "")) ||
        (row.status !== "revoked" && row.revoked_at != null)) return null;
    const publicKey = decodeBase64(String(row.public_key_base64 || ""));
    if (!publicKey || publicKey.byteLength !== 32 || keyIds.has(row.key_id)) return null;
    keyIds.add(row.key_id);
    if (row.status === "active") {
      if (row.environment !== environment) return null;
      active += 1;
    }
  }
  const expectedActive = registry.authority_status === "ACTIVE" ? 1 : 0;
  if (active !== expectedActive) return null;
  return registry;
}

/** Load the compile-time verification root for one environment. */
async function loadPinnedProjectionKeyRegistry(environment = "production") {
  const selected = environment === "staging"
    ? {
      document: pinnedStagingRegistryDocument,
      body: PINNED_STAGING_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
      documentDigest: PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    }
    : {
      document: pinnedRegistryDocument,
      body: PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
      documentDigest: PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    };
  const registry = parsePinnedProjectionKeyRegistry(selected.document, environment);
  if (!registry ||
      await projectionSha256(registry) !== selected.documentDigest) {
    throw new Error("pinned Ops Projection public-key registry is invalid");
  }
  const registryBody = Object.fromEntries(
    Object.entries(registry).filter(([key]) => key !== "registry_digest"),
  );
  if (registry.registry_digest !== selected.body ||
      await projectionSha256(registryBody) !== selected.body) {
    throw new Error("pinned Ops Projection public-key registry is invalid");
  }
  return structuredClone(registry);
}

/** @param {Record<string, unknown>} generation */
export async function verifyPinnedProjectionGeneration(generation) {
  return verifyProjectionGenerationWithPinnedRegistry(
    generation,
    await loadPinnedProjectionKeyRegistry(),
  );
}

/** @param {unknown} value */
function placeholderKey(value) {
  const compact = String(value || "").replace(/=+$/g, "");
  return compact.length > 0 && /^A+$/.test(compact);
}

/** @param {string} spkiB64 */
function spkiRaw32(spkiB64) {
  const der = decodeBase64(spkiB64);
  if (!der || der.byteLength !== 44) return null;
  const prefix = [0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00];
  for (let index = 0; index < prefix.length; index += 1) {
    if (der[index] !== prefix[index]) return null;
  }
  return der.slice(12);
}

/** @param {Uint8Array|null} left @param {Uint8Array|null} right */
function bytesEqual(left, right) {
  if (!left || !right || left.byteLength !== right.byteLength) return false;
  for (let index = 0; index < left.byteLength; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}

/**
 * Live MCP verification uses the env SPKI/key-id. Tests without a staging/prod
 * environment keep the pinned registry path.
 *
 * @param {Record<string, unknown>} generation
 * @param {Record<string, unknown>|undefined} env
 */
export async function verifyActiveOpsProjection(generation, env) {
  const environment = env?.OPS_PROJECTION_ENVIRONMENT;
  const spki = typeof env?.OPS_PROJECTION_VERIFY_SPKI_B64 === "string"
    ? env.OPS_PROJECTION_VERIFY_SPKI_B64
    : "";
  const keyId = typeof env?.OPS_PROJECTION_VERIFY_KEY_ID === "string"
    ? env.OPS_PROJECTION_VERIFY_KEY_ID
    : "";
  const live = environment === "staging" || environment === "production";
  if (!live) return verifyPinnedProjectionGeneration(generation);
  if (!spki || placeholderKey(spki) || !keyId || placeholderKey(keyId)) {
    return { ok: false, reason: "Ops Projection verify SPKI is unprovisioned", envelope: null };
  }
  const registry = await loadPinnedProjectionKeyRegistry(String(environment));
  const named = /** @type {unknown[]} */ (registry.keys).some((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
    const row = /** @type {Record<string, unknown>} */ (candidate);
    return row.key_id === keyId;
  });
  if (!named) {
    return { ok: false, reason: "Ops Projection issuer is not a registry member", envelope: null };
  }
  if (String(registry.authority_status) !== "ACTIVE") {
    return { ok: false, reason: "pinned Ops Projection registry is not ACTIVE", envelope: null };
  }
  const rows = /** @type {unknown[]} */ (registry.keys);
  const keyRow = rows.find((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
    const row = /** @type {Record<string, unknown>} */ (candidate);
    return row.key_id === keyId && row.algorithm === "Ed25519" && row.status === "active" &&
      row.environment === environment;
  });
  if (!keyRow || typeof keyRow !== "object" || Array.isArray(keyRow)) {
    return { ok: false, reason: "Ops Projection issuer is not an ACTIVE registry member", envelope: null };
  }
  const pinnedRaw = decodeBase64(String(
    /** @type {Record<string, unknown>} */ (keyRow).public_key_base64 || "",
  ));
  const configuredRaw = spkiRaw32(spki);
  if (!bytesEqual(pinnedRaw, configuredRaw)) {
    return {
      ok: false,
      reason: "configured environment+key ID+SPKI does not match an ACTIVE registry entry",
      envelope: null,
    };
  }
  return verifyProjectionGenerationWithPinnedRegistry(generation, registry);
}

/**
 * @param {Record<string, unknown>} generation
 * @param {string} spkiB64
 * @param {string} keyId
 * @param {string} environment
 */
export async function verifyProjectionGenerationWithSpki(generation, spkiB64, keyId, environment) {
  const pinned = await verifyProjectionGenerationShape(generation);
  if (!pinned.ok || !pinned.envelope) return pinned;
  const envelope = pinned.envelope;
  if (generation.issuer_key_id !== keyId || envelope.environment !== environment) {
    return { ok: false, reason: "Ops Projection issuer/environment is not trusted", envelope: null };
  }
  const signatureValue = String(generation.signature);
  const signature = signatureValue.startsWith("ed25519:")
    ? decodeBase64(signatureValue.slice("ed25519:".length))
    : null;
  const spki = decodeBase64(spkiB64);
  if (!signature || !spki) {
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
      "spki",
      spki,
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "Ed25519" },
      key,
      signature,
      canonicalProjectionBytes(body),
    );
    return valid
      ? { ok: true, reason: null, envelope }
      : { ok: false, reason: "Ops Projection signature is invalid", envelope: null };
  } catch {
    return { ok: false, reason: "Ops Projection signature verification failed", envelope: null };
  }
}

/** @param {Record<string, unknown>} generation */
async function verifyProjectionGenerationShape(generation) {
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
  const expectedKeys = ["algorithm", "envelope", "issuer_key_id", "schema_version", "signature"];
  if (Object.keys(document).sort().join("\0") !== expectedKeys.join("\0") ||
      document.schema_version !== SIGNED_DOCUMENT_SCHEMA ||
      document.algorithm !== "Ed25519" ||
      document.issuer_key_id !== generation.issuer_key_id ||
      document.signature !== generation.signature) {
    return { ok: false, reason: "signed Ops Projection document shape is invalid", envelope: null };
  }
  if (!document.envelope || typeof document.envelope !== "object" ||
      Array.isArray(document.envelope)) {
    return { ok: false, reason: "signed Ops Projection envelope is missing", envelope: null };
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
  return { ok: true, reason: null, envelope };
}

/** @param {Record<string, unknown>} envelope */
function validateEnvelope(envelope) {
  if (envelope.schema_version !== ENVELOPE_SCHEMA) return "unsupported envelope schema";
  const required = [
    "generation_id", "content_digest", "source_db_digest", "generated_at",
    "producer_commit_sha", "worker_version_id", "contract_digest", "registry_digest",
    "coverage_policy_version", "coverage_policy_digest", "projection_status",
    "source_generation",
    "source_snapshot_generation", "source_cursor",
    "export_cursor", "applied_cursor", "coverage_status_digest", "b0_status",
    "b0_evidence_digest", "b4_status", "b4_evidence_digest",
    "dataset_coverage", "evidence_digests", "content_manifest", "row_counts",
  ];
  if (required.some((field) => !Object.hasOwn(envelope, field))) {
    return "envelope fields are incomplete";
  }
  for (const field of [
    "content_digest", "source_db_digest", "contract_digest", "registry_digest",
    "coverage_status_digest", "coverage_policy_digest", "b0_evidence_digest",
    "b4_evidence_digest",
  ]) {
    if (!/^sha256:[0-9a-f]{64}$/.test(String(envelope[field] || ""))) {
      return `invalid ${field}`;
    }
  }
  if (!["PASS", "FAIL", "UNKNOWN"].includes(String(envelope.b0_status))) {
    return "invalid b0_status";
  }
  if (!["PASS", "FAIL", "UNKNOWN"].includes(String(envelope.b4_status))) {
    return "invalid b4_status";
  }
  if (!["FRESH", "STALE", "FAILED", "UNKNOWN"].includes(String(envelope.projection_status))) {
    return "invalid projection_status";
  }
  if (!envelope.dataset_coverage || typeof envelope.dataset_coverage !== "object" ||
      Array.isArray(envelope.dataset_coverage)) return "dataset_coverage must be an object";
  for (const [dataset, raw] of Object.entries(
    /** @type {Record<string, unknown>} */ (envelope.dataset_coverage),
  )) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return `dataset_coverage row is malformed for ${dataset}`;
    }
    const row = /** @type {Record<string, unknown>} */ (raw);
    if (row.policy_id !== dataset || typeof row.policy_version !== "string" ||
        !row.policy_version ||
        !/^sha256:[0-9a-f]{64}$/.test(String(row.policy_digest || ""))) {
      return `dataset_coverage policy binding is invalid for ${dataset}`;
    }
  }
  if (!envelope.content_manifest || typeof envelope.content_manifest !== "object" ||
      Array.isArray(envelope.content_manifest)) return "content_manifest must be an object";
  if (!envelope.row_counts || typeof envelope.row_counts !== "object" ||
      Array.isArray(envelope.row_counts)) return "row_counts must be an object";
  for (const field of ["source_generation", "source_cursor", "export_cursor", "applied_cursor"]) {
    const cursor = envelope[field];
    if (cursor !== null && (!Number.isInteger(cursor) || Number(cursor) < 0)) {
      return `invalid ${field}`;
    }
  }
  return null;
}

/** @param {Record<string, unknown>} registry */
function environmentForRegistry(registry) {
  const rows = Array.isArray(registry.keys) ? registry.keys : [];
  const active = rows.find((row) => row && row.status === "active");
  return active && active.environment === "staging" ? "staging" : "production";
}

/**
 * @param {Record<string, unknown>} generation
 * @param {Record<string, unknown>} registry
 * @returns {Promise<{ok:boolean, reason:string|null, envelope:Record<string, unknown>|null}>}
 */
async function verifyProjectionGenerationWithPinnedRegistry(generation, registry) {
  const shaped = await verifyProjectionGenerationShape(generation);
  if (!shaped.ok || !shaped.envelope) return shaped;
  const envelope = shaped.envelope;
  const rows = /** @type {unknown[]} */ (registry.keys);
  const keyRow = rows.find((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
    const row = /** @type {Record<string, unknown>} */ (candidate);
    return row.key_id === generation.issuer_key_id &&
      row.algorithm === "Ed25519" && row.status === "active";
  });
  if (!keyRow || typeof keyRow !== "object" || Array.isArray(keyRow)) {
    return { ok: false, reason: "Ops Projection issuer is not trusted", envelope: null };
  }
  const pinnedDigest = environmentForRegistry(registry) === "staging"
    ? PINNED_STAGING_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST
    : PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST;
  if (envelope.registry_digest !== registry.registry_digest &&
      envelope.registry_digest !== pinnedDigest) {
    return { ok: false, reason: "envelope registry_digest does not match validated registry", envelope: null };
  }
  const generatedAt = requireCanonicalUtc(envelope.generated_at);
  const keyMeta = /** @type {Record<string, unknown>} */ (keyRow);
  const notBefore = requireCanonicalUtc(keyMeta.not_before);
  const notAfter = requireCanonicalUtc(keyMeta.not_after);
  if (!generatedAt || !notBefore || !notAfter || generatedAt < notBefore || generatedAt > notAfter) {
    return { ok: false, reason: "Ops Projection issuer is outside its validity window", envelope: null };
  }
  if (keyMeta.revoked_at) {
    const revoked = requireCanonicalUtc(keyMeta.revoked_at);
    if (!revoked || generatedAt >= revoked) {
      return { ok: false, reason: "Ops Projection issuer is revoked", envelope: null };
    }
  }
  const publicKey = decodeBase64(String(
    /** @type {Record<string, unknown>} */ (keyRow).public_key_base64 || "",
  ));
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
