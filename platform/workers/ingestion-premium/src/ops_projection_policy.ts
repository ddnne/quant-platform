/** Coverage V3 policy and COMPLETE proof. */
import receiptClaimsSchema from "../../../../packages/data_plane/storage/authorities/receipts/signed_receipt_claims.schema.json";
import {
  base64ToBytes,
  canonicalDigest,
  canonicalJson,
  exactKeys,
  isPlainObject,
  isSha256,
} from "../../receipt-evidence-authority/src/canonical";
import type { SignedReceiptClaimsV3 } from "../../receipt-evidence-authority/src/types";
import { catalogProjectionRows, datasetById } from "./catalog";

export const COVERAGE_POLICY_VERSION = "collection-coverage/v3";
const CLAIMS_VERSION = "signed-receipt-claims/v3";
const PARSER_NORMALIZER_VERSION = "coverage-receipt/v4-ed25519-closure";

const claimsSchema = receiptClaimsSchema as unknown as {
  required: string[];
  properties: Record<string, unknown> & {
    extra_digests: { required: string[] };
  };
  allOf: Array<{
    then: { properties: { extra_digests: { required: string[] } } };
  }>;
};
const SIGNED_CLAIM_KEYS = claimsSchema.required;
const BASE_EXTRA_DIGEST_KEYS = claimsSchema.properties.extra_digests.required;
const MASTER_EXTRA_DIGEST_KEYS = claimsSchema.allOf[0]!.then.properties.extra_digests.required;
const ENVELOPE_KEYS = [
  "eligibility",
  "issuer_class",
  "issuer_key_id",
  "issuer_id",
  "environment",
  "authority_instance_digest",
  "parser_normalizer_version",
  "signed_body_b64",
  "signature",
  "body_digest",
  "issued_at",
  "checked_at",
  "source_request_digest",
  "raw_manifest_digest",
  "raw",
  "structured_generation",
  "structured_digest",
  "scope_digest",
  "observation_digest",
  "extra_digests",
] as const;

function parseDigests(raw: unknown): Record<string, unknown> | null {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>;
  }
  if (typeof raw !== "string") return null;
  try {
    const value = JSON.parse(raw) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    return value as Record<string, unknown>;
  } catch {
    return null;
  }
}
function decodeBase64(value: unknown): Uint8Array | null {
  if (typeof value !== "string") return null;
  try {
    return base64ToBytes(value);
  } catch {
    return null;
  }
}

function exactNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function exactPositiveInteger(value: unknown): value is number {
  return exactNonNegativeInteger(value) && value > 0;
}

function sameJson(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

async function requireClosedClaims(value: unknown): Promise<SignedReceiptClaimsV3 | null> {
  if (
    !isPlainObject(value) ||
    !exactKeys(claimsSchema.properties, SIGNED_CLAIM_KEYS) ||
    !exactKeys(value, SIGNED_CLAIM_KEYS)
  ) return null;

  const extraDigests = isPlainObject(value.extra_digests)
    ? value.extra_digests
    : null;
  const expectedExtraKeys = value.source === "jquants" && value.dataset === "equities_master"
    ? [...BASE_EXTRA_DIGEST_KEYS, ...MASTER_EXTRA_DIGEST_KEYS]
    : BASE_EXTRA_DIGEST_KEYS;
  const nonNegativeIntegers = [
    value.observed_items,
    value.raw_page_count,
    value.raw_count,
    value.structured_count,
    value.structured_generation,
    value.run_id,
  ];
  const positiveIntegers = [
    value.artifact_byte_count,
    value.manifest_byte_count,
    value.raw_manifest_byte_count,
    value.raw_byte_count,
  ];
  const requiredDigests = [
    value.authority_instance_digest,
    value.receipt_issue_digest,
    value.natural_key_digest,
    value.source_request_digest,
    value.raw_manifest_digest,
    value.raw_digest,
    value.structured_digest,
    value.scope_digest,
    value.observation_digest,
  ];
  const nonEmptyStrings = [
    value.contract_id,
    value.dataset,
    value.segment_id,
    value.segment_start,
    value.segment_end,
    value.artifact_key,
    value.manifest_key,
    value.raw_manifest_key,
    value.issuer_id,
  ];
  if (
    value.version !== CLAIMS_VERSION ||
    value.parser_normalizer_version !== PARSER_NORMALIZER_VERSION ||
    value.coverage_policy_version !== COVERAGE_POLICY_VERSION ||
    (value.environment !== "production" && value.environment !== "staging") ||
    (value.source !== "jquants" && value.source !== "jsda") ||
    value.status !== "SUCCESS" || value.error !== null ||
    value.pagination_exhausted !== true || value.discovery_exhausted !== true ||
    nonEmptyStrings.some((item) => typeof item !== "string" || item.length === 0) ||
    (typeof value.segment_start === "string" &&
      typeof value.segment_end === "string" &&
      value.segment_start > value.segment_end) ||
    !isPlainObject(value.expected_scope) ||
    !(value.expected_items === null || exactNonNegativeInteger(value.expected_items)) ||
    nonNegativeIntegers.some((item) => !exactNonNegativeInteger(item)) ||
    value.structured_generation !== value.run_id ||
    positiveIntegers.some((item) => !exactPositiveInteger(item)) ||
    requiredDigests.some((item) => !isSha256(item)) ||
    requireCanonicalUtc(value.issued_at) === null ||
    requireCanonicalUtc(value.checked_at) === null ||
    extraDigests === null ||
    !exactKeys(extraDigests, expectedExtraKeys) ||
    expectedExtraKeys.some((key) => !isSha256(extraDigests[key])) ||
    extraDigests.product_artifact_digest !== value.structured_digest
  ) return null;

  const claims = value as SignedReceiptClaimsV3;
  const scope = {
    environment: claims.environment,
    authority_instance_digest: claims.authority_instance_digest,
    coverage_policy_version: claims.coverage_policy_version,
    source: claims.source,
    contract_id: claims.contract_id,
    dataset: claims.dataset,
    segment_id: claims.segment_id,
    segment_start: claims.segment_start,
    segment_end: claims.segment_end,
    expected_scope: claims.expected_scope,
    expected_items: claims.expected_items,
  };
  if (await canonicalDigest(scope) !== claims.scope_digest) return null;
  const observation = {
    ...scope,
    observed_items: claims.observed_items,
    raw_page_count: claims.raw_page_count,
    raw_count: claims.raw_count,
    structured_count: claims.structured_count,
    status: claims.status,
    error: claims.error,
    pagination_exhausted: claims.pagination_exhausted,
    discovery_exhausted: claims.discovery_exhausted,
    receipt_issue_digest: claims.receipt_issue_digest,
    artifact_key: claims.artifact_key,
    artifact_byte_count: claims.artifact_byte_count,
    manifest_key: claims.manifest_key,
    manifest_byte_count: claims.manifest_byte_count,
    raw_manifest_key: claims.raw_manifest_key,
    raw_manifest_byte_count: claims.raw_manifest_byte_count,
    raw_byte_count: claims.raw_byte_count,
    natural_key_digest: claims.natural_key_digest,
    source_request_digest: claims.source_request_digest,
    raw_manifest_digest: claims.raw_manifest_digest,
    raw_digest: claims.raw_digest,
    structured_digest: claims.structured_digest,
    structured_generation: claims.structured_generation,
    scope_digest: claims.scope_digest,
    run_id: claims.run_id,
    checked_at: claims.checked_at,
    extra_digests: claims.extra_digests,
  };
  return await canonicalDigest(observation) === claims.observation_digest
    ? claims
    : null;
}

export const CANONICAL_UTC =
  /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;

export function requireCanonicalUtc(value: unknown): string | null {
  if (typeof value !== "string" || CANONICAL_UTC.test(value) === false) return null;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return null;
  const canonical = new Date(parsed).toISOString().replace(/\.\d{3}Z$/, "Z");
  return canonical === value ? value : null;
}

export const PINNED_RECEIPT_REGISTRY_RAW = {
  production: {
    registry_raw_sha:
      "sha256:c258de1ff4a1d8c917aefe6656f0892a602f8d0de635ca21a4c8d7160d84ab33",
    registry_raw_size: 464,
  },
  staging: {
    registry_raw_sha:
      "sha256:2e5f91fd38d25ab971c674b4d979e4258748cf3db46e52eb445d5352f5dd4d19",
    registry_raw_size: 461,
  },
} as const;

export type ReceiptVerifyRegistry = {
  schema_version?: number;
  purpose?: string;
  authority_status: string;
  environment: string;
  authority_instance_digest?: string;
  registry_digest?: string;
  registry_raw_sha?: string;
  registry_raw_size?: number;
  generation?: number;
  prior_registry_digest?: string | null;
  keys: Array<{
    key_id: string;
    algorithm: string;
    public_key_base64: string;
    status: string;
    environment?: string;
    not_before?: string;
    not_after?: string;
    revoked_at?: string | null;
  }>;
};

export type ClosedObjectStores = {
  structured?: { get?(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null> } | null;
  authority?: { get?(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null> } | null;
  raw?: { get?(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null> } | null;
};

async function digestBytes(bytes: Uint8Array): Promise<string> {
  const raw = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(raw), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")}`;
}

export async function verifySignedReceiptEnvelope(
  envelope: Record<string, unknown>,
  registry: ReceiptVerifyRegistry,
  environment: string,
): Promise<SignedReceiptClaimsV3 | null> {
  if (registry.authority_status !== "ACTIVE") return null;
  if (registry.environment !== environment) return null;
  if (!isSha256(registry.authority_instance_digest)) return null;
  const rawPin = PINNED_RECEIPT_REGISTRY_RAW[environment as "production" | "staging"];
  if (!rawPin || registry.registry_raw_sha !== rawPin.registry_raw_sha ||
      registry.registry_raw_size !== rawPin.registry_raw_size) return null;
  const keyId = envelope.issuer_key_id;
  if (typeof keyId !== "string" || keyId.length === 0) return null;
  const key = registry.keys.find(
    (row) =>
      row.key_id === keyId &&
      row.algorithm === "Ed25519" &&
      row.status === "active" &&
      (row.environment == null || row.environment === environment),
  );
  if (!key) return null;
  if (envelope.environment !== environment) return null;
  if (envelope.authority_instance_digest !== registry.authority_instance_digest) return null;
  const bodyBytes = decodeBase64(envelope.signed_body_b64);
  if (!bodyBytes) return null;
  const bodyDigest = await digestBytes(bodyBytes);
  if (!isSha256(envelope.body_digest) || bodyDigest !== envelope.body_digest) return null;
  const signatureValue = envelope.signature;
  if (typeof signatureValue !== "string") return null;
  if (!signatureValue.startsWith("ed25519:")) return null;
  const signature = decodeBase64(signatureValue.slice("ed25519:".length));
  const publicKey = decodeBase64(key.public_key_base64);
  if (!signature || signature.byteLength !== 64 || !publicKey || publicKey.byteLength !== 32) {
    return null;
  }
  try {
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      publicKey,
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "Ed25519" },
      cryptoKey,
      signature,
      bodyBytes,
    );
    if (!valid) return null;
  } catch {
    return null;
  }
  let decoded = "";
  let rawClaims: unknown;
  try {
    decoded = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bodyBytes);
    if (new TextEncoder().encode(decoded).length !== bodyBytes.byteLength) return null;
    rawClaims = JSON.parse(decoded);
  } catch {
    return null;
  }
  const claims = await requireClosedClaims(rawClaims);
  if (!claims || canonicalJson(claims) !== decoded) return null;
  const expectedEnvelopeKeys = [...ENVELOPE_KEYS, ...Object.keys(claims.extra_digests)];
  if (!exactKeys(envelope, expectedEnvelopeKeys)) return null;
  if (
    envelope.eligibility !== "TRUSTED_COLLECTION" ||
    envelope.issuer_class !== "SignedReceiptAuthority" ||
    envelope.issuer_key_id !== claims.issuer_id ||
    envelope.issuer_id !== claims.issuer_id ||
    claims.issuer_id !== keyId ||
    envelope.environment !== claims.environment ||
    envelope.authority_instance_digest !== claims.authority_instance_digest ||
    envelope.parser_normalizer_version !== claims.parser_normalizer_version ||
    envelope.issued_at !== claims.issued_at ||
    envelope.checked_at !== claims.checked_at ||
    envelope.source_request_digest !== claims.source_request_digest ||
    envelope.raw_manifest_digest !== claims.raw_manifest_digest ||
    envelope.raw !== claims.raw_digest ||
    envelope.structured_generation !== claims.structured_generation ||
    envelope.structured_digest !== claims.structured_digest ||
    envelope.scope_digest !== claims.scope_digest ||
    envelope.observation_digest !== claims.observation_digest ||
    !sameJson(envelope.extra_digests, claims.extra_digests) ||
    Object.entries(claims.extra_digests).some(([name, digest]) => envelope[name] !== digest)
  ) return null;
  const issuedAt = requireCanonicalUtc(claims.issued_at);
  if (!issuedAt) return null;
  const notBefore = requireCanonicalUtc(key.not_before);
  const notAfter = requireCanonicalUtc(key.not_after);
  if (key.not_before && !notBefore) return null;
  if (key.not_after && !notAfter) return null;
  if (notBefore && issuedAt < notBefore) return null;
  if (notAfter && issuedAt > notAfter) return null;
  if (key.revoked_at) {
    const revoked = requireCanonicalUtc(key.revoked_at);
    if (!revoked || issuedAt >= revoked) return null;
  }
  return claims;
}

export async function trustedComplete(
  row: Record<string, unknown>,
  receipts: Record<string, unknown>[],
  products: Record<string, unknown>[],
  operations: Record<string, unknown>[],
  requests: Record<string, unknown>[],
  naturalByOp: Map<string, number>,
  environment: string,
  registry: ReceiptVerifyRegistry | null = null,
  evidence?: ClosedObjectStores | null,
): Promise<boolean> {
  if (row.status !== "COMPLETE") return false;
  const dataset = typeof row.dataset === "string" ? row.dataset : "";
  const catalog = catalogProjectionRows().find((item) => item.dataset_id === dataset);
  if (!datasetById(dataset) || catalog?.coverage.policy_version !== COVERAGE_POLICY_VERSION) {
    return false;
  }
  if (row.policy_version !== COVERAGE_POLICY_VERSION) return false;
  const source = typeof row.source === "string" ? row.source : "";
  if (source !== catalog.source) return false;
  const segment = typeof row.segment_id === "string" ? row.segment_id : "";
  const receiptRun = row.receipt_run_id;
  if (!exactNonNegativeInteger(receiptRun)) return false;
  const receipt = receipts.find(
    (item) =>
      item.source === source &&
      item.dataset === dataset &&
      item.segment_id === segment &&
      item.status === "SUCCESS" &&
      item.run_id === receiptRun,
  );
  if (!receipt) return false;
  if (receipt.pagination_exhausted !== 1 || receipt.error !== null) return false;
  const envelope = parseDigests(receipt.digests_json ?? receipt.digests);
  if (!envelope) return false;
  if (!registry || registry.authority_status !== "ACTIVE") return false;
  const claims = await verifySignedReceiptEnvelope(envelope, registry, environment);
  if (!claims) return false;
  if (
    claims.source !== source || claims.dataset !== dataset || claims.segment_id !== segment ||
    claims.contract_id !== catalog.coverage.collection_scope ||
    claims.environment !== environment
  ) {
    return false;
  }
  if (claims.segment_start !== row.segment_start || claims.segment_end !== row.segment_end) {
    return false;
  }
  if (claims.segment_start !== receipt.segment_start || claims.segment_end !== receipt.segment_end) {
    return false;
  }
  if (claims.run_id !== receipt.run_id || claims.run_id !== receiptRun) return false;
  const requiredScope = parseDigests(row.expected_scope);
  const receiptScope = parseDigests(receipt.expected_scope);
  if (
    !requiredScope || !receiptScope ||
    !sameJson(claims.expected_scope, requiredScope) ||
    !sameJson(claims.expected_scope, receiptScope) ||
    claims.expected_items !== row.expected_items ||
    claims.expected_items !== receipt.expected_items
  ) return false;
  if (!exactPositiveInteger(receipt.raw_page_count)) {
    return false;
  }
  if (
    claims.observed_items !== receipt.observed_items ||
    claims.raw_page_count !== receipt.raw_page_count ||
    claims.raw_count !== receipt.raw_row_count ||
    claims.structured_count !== receipt.structured_row_count ||
    claims.checked_at !== receipt.checked_at
  ) {
    return false;
  }
  const receiptDigest = await canonicalDigest({
    source: claims.source,
    dataset: claims.dataset,
    segment_id: claims.segment_id,
    segment_start: claims.segment_start,
    segment_end: claims.segment_end,
    expected_scope: claims.expected_scope,
    expected_items: claims.expected_items,
    observed_items: claims.observed_items,
    raw_page_count: claims.raw_page_count,
    raw_row_count: claims.raw_count,
    structured_row_count: claims.structured_count,
    pagination_exhausted: true,
    digests: envelope,
    run_id: claims.run_id,
    status: claims.status,
    error: claims.error,
    checked_at: claims.checked_at,
  });
  const structured = claims.structured_digest;
  const rawManifest = claims.raw_manifest_digest;
  const rawManifestFile = claims.extra_digests.acquisition_collection_manifest_file_digest!;
  const artifact = claims.extra_digests.product_artifact_digest!;
  const manifest = claims.extra_digests.product_manifest_digest!;
  const productKey = `${source}\0${claims.run_id}\0${dataset}\0${segment}`;
  const product = products.find(
    (item) =>
      `${item.source}\0${item.run_id}\0${item.dataset}\0${item.segment_id}` === productKey,
  );
  if (!product) return false;
  if (String(product.artifact_digest) !== artifact) return false;
  if (String(product.manifest_digest) !== manifest) return false;
  if (String(product.raw_manifest_digest) !== rawManifest) return false;
  if (
    product.row_count !== claims.structured_count ||
    product.raw_page_count !== claims.raw_page_count ||
    product.raw_row_count !== claims.raw_count ||
    product.raw_bytes !== claims.raw_byte_count ||
    product.byte_count !== claims.artifact_byte_count ||
    product.committed_at !== claims.checked_at
  ) return false;
  if (product.artifact_key !== claims.artifact_key) return false;
  if (product.manifest_key !== claims.manifest_key) return false;
  if (product.raw_manifest_key !== claims.raw_manifest_key) {
    return false;
  }
  const rawKey = claims.raw_manifest_key;
  if (rawKey.includes("/v2/") || rawKey.includes("recovered") || rawKey.includes("audit-only")) {
    return false;
  }
  if (!evidence?.structured?.get || !evidence.authority?.get || !evidence.raw?.get) return false;
  const MAX_ARTIFACT_BYTES = 8 * 1024 * 1024;
  const MAX_MANIFEST_BYTES = 256 * 1024;
  const fetches: Array<readonly [
    { get?(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null> } | null | undefined,
    string,
    string,
    number,
    number,
  ]> = [
    [evidence.structured, claims.artifact_key, structured, claims.artifact_byte_count, MAX_ARTIFACT_BYTES],
    [evidence.authority, claims.manifest_key, manifest, claims.manifest_byte_count, MAX_MANIFEST_BYTES],
    [evidence.raw, claims.raw_manifest_key, rawManifestFile, claims.raw_manifest_byte_count, MAX_MANIFEST_BYTES],
  ];
  for (const [store, key, expectedDigest, expectedBytes, maxBytes] of fetches) {
    if (!key || !store?.get) return false;
    if (!Number.isInteger(expectedBytes) || expectedBytes <= 0) return false;
    const object = await store.get(key);
    if (!object) return false;
    const stored = new Uint8Array(await object.arrayBuffer());
    if (stored.byteLength === 0 || stored.byteLength > maxBytes) return false;
    if (stored.byteLength !== expectedBytes) return false;
    if (await digestBytes(stored) !== expectedDigest) return false;
  }
  if (!operations.length) return false;
  const operation = operations.find(
    (item) =>
      item.run_id === claims.run_id &&
      item.dataset === dataset &&
      item.segment_id === segment &&
      item.environment === environment &&
      item.state === "RECEIPT_COMMITTED" &&
      item.operation_id === product.operation_id &&
      item.source === source,
  );
  if (!operation) return false;
  if (operation.receipt_digest !== receiptDigest || !isSha256(operation.request_digest)) {
    return false;
  }
  if (
    operation.contract_id !== claims.contract_id ||
    operation.request_digest !== claims.receipt_issue_digest ||
    operation.segment_start !== claims.segment_start ||
    operation.segment_end !== claims.segment_end ||
    operation.structured_manifest_key !== claims.manifest_key ||
    operation.structured_digest !== structured ||
    operation.raw_manifest_key !== claims.raw_manifest_key ||
    operation.raw_manifest_digest !== rawManifest ||
    operation.raw_page_count !== claims.raw_page_count ||
    operation.raw_row_count !== claims.raw_count ||
    operation.raw_bytes !== claims.raw_byte_count
  ) return false;
  const request = requests.find(
    (item) =>
      item.operation_id === operation.operation_id &&
      item.state === "FINALIZED" &&
      item.environment === environment &&
      item.source === source &&
      item.contract_id === claims.contract_id &&
      item.dataset === dataset &&
      item.segment_id === segment &&
      item.receipt_digest === operation.receipt_digest,
  );
  if (!request) return false;
  const naturals = naturalByOp.get(String(operation.operation_id));
  if (naturals !== product.row_count) return false;
  if (Number(claims.structured_count) !== naturals) return false;
  return true;
}

export async function projectedSegmentStatus(
  row: Record<string, unknown>,
  receipts: Record<string, unknown>[],
  products: Record<string, unknown>[],
  operations: Record<string, unknown>[],
  requests: Record<string, unknown>[],
  naturalByOp: Map<string, number>,
  environment: string,
  registry: ReceiptVerifyRegistry | null = null,
  evidence?: ClosedObjectStores | null,
): Promise<string> {
  if (await trustedComplete(
    row, receipts, products, operations, requests, naturalByOp, environment, registry, evidence,
  )) {
    return "COMPLETE";
  }
  if (String(row.status) === "COMPLETE") return "UNKNOWN";
  return String(row.status ?? "UNKNOWN");
}

export function aggregateDatasetStatus(statuses: string[]): string {
  const unique = [...new Set(statuses)];
  if (unique.length === 1) return unique[0] ?? "UNKNOWN";
  if (unique.includes("FAILED")) return "FAILED";
  const onlyCompletePartial = unique.every(
    (status) => status === "COMPLETE" || status === "PARTIAL",
  );
  if (onlyCompletePartial && unique.includes("PARTIAL")) return "PARTIAL";
  return "UNKNOWN";
}
