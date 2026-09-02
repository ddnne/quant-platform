/** Coverage V3 policy and COMPLETE proof. */
import { catalogProjectionRows, datasetById } from "./catalog";

export const COVERAGE_POLICY_VERSION = "collection-coverage/v3";

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
function b64ToBytes(value: string): Uint8Array | null {
  try {
    const binary = atob(value);
    return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
  } catch {
    return null;
  }
}

function shaPrefixed(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
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

export const PINNED_RECEIPT_REGISTRY_RAW_SHA =
  "sha256:dc6095db1d09bf775f972cb428944a1ba5bc47fefa0af19e77c3f3a157ae47f5";
export const PINNED_RECEIPT_REGISTRY_RAW_SIZE = 1370;

export type ReceiptVerifyRegistry = {
  authority_status: string;
  environment: string;
  authority_instance_digest?: string;
  registry_digest?: string;
  registry_raw_sha?: string;
  registry_raw_size?: number;
  generation?: number;
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
): Promise<Record<string, unknown> | null> {
  if (registry.authority_status !== "ACTIVE") return null;
  if (
    registry.registry_raw_sha &&
    registry.registry_raw_sha !== PINNED_RECEIPT_REGISTRY_RAW_SHA
  ) {
    return null;
  }
  if (
    registry.registry_raw_size != null &&
    registry.registry_raw_size !== PINNED_RECEIPT_REGISTRY_RAW_SIZE
  ) {
    return null;
  }
  const keyId = String(envelope.issuer_key_id ?? "");
  const key = registry.keys.find(
    (row) =>
      row.key_id === keyId &&
      row.algorithm === "Ed25519" &&
      row.status === "active" &&
      (row.environment == null || row.environment === environment),
  );
  if (!key) return null;
  if (String(envelope.environment) !== environment) return null;
  if (
    typeof registry.authority_instance_digest === "string" &&
    String(envelope.authority_instance_digest) !== registry.authority_instance_digest
  ) {
    return null;
  }
  const bodyB64 = String(envelope.signed_body_b64 ?? "");
  const bodyBytes = b64ToBytes(bodyB64);
  if (!bodyBytes) return null;
  const bodyDigest = await digestBytes(bodyBytes);
  if (bodyDigest !== String(envelope.body_digest ?? "")) return null;
  const signatureValue = String(envelope.signature ?? "");
  if (!signatureValue.startsWith("ed25519:")) return null;
  const signature = b64ToBytes(signatureValue.slice("ed25519:".length));
  const publicKey = b64ToBytes(key.public_key_base64);
  if (!signature || !publicKey || publicKey.byteLength !== 32) return null;
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
  let claims: unknown;
  try {
    const decoded = new TextDecoder("utf-8").decode(bodyBytes);
    if (new TextEncoder().encode(decoded).length !== bodyBytes.byteLength) return null;
    claims = JSON.parse(decoded);
  } catch {
    return null;
  }
  if (!claims || typeof claims !== "object" || Array.isArray(claims)) return null;
  const issuedAt = requireCanonicalUtc(
    (claims as Record<string, unknown>).issued_at ??
      (claims as Record<string, unknown>).checked_at ??
      envelope.issued_at,
  );
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
  return claims as Record<string, unknown>;
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
  if (String(row.status) !== "COMPLETE") return false;
  const dataset = String(row.dataset ?? "");
  const spec = datasetById(dataset);
  const catalog = catalogProjectionRows().find((item) => item.dataset_id === dataset);
  const policyVersion = spec?.coverage.policy_version ?? catalog?.coverage.policy_version;
  const currentSource = catalog?.source;
  if (policyVersion !== COVERAGE_POLICY_VERSION) return false;
  if (String(row.policy_version) !== COVERAGE_POLICY_VERSION) return false;
  const source = String(row.source ?? "");
  if (currentSource && source !== currentSource) return false;
  const segment = String(row.segment_id ?? "");
  const receiptRun = row.receipt_run_id;
  if (receiptRun == null || String(receiptRun) === "") return false;
  const receipt = receipts.find(
    (item) =>
      String(item.source) === source &&
      String(item.dataset) === dataset &&
      String(item.segment_id) === segment &&
      String(item.status) === "SUCCESS" &&
      String(item.run_id) === String(receiptRun),
  );
  if (!receipt) return false;
  if (Number(receipt.pagination_exhausted) !== 1) return false;
  const envelope = parseDigests(receipt.digests_json ?? receipt.digests);
  if (!envelope) return false;
  if (String(envelope.eligibility ?? "TRUSTED_COLLECTION") !== "TRUSTED_COLLECTION") return false;
  if (!registry || registry.authority_status !== "ACTIVE") return false;
  const claims = await verifySignedReceiptEnvelope(envelope, registry, environment);
  if (!claims) return false;
  const same = (left: unknown, right: unknown) => String(left ?? "") === String(right ?? "");
  if (!same(claims.source, source) || !same(claims.dataset, dataset) || !same(claims.segment_id, segment)) {
    return false;
  }
  if (!same(claims.segment_start, row.segment_start) || !same(claims.segment_end, row.segment_end)) {
    return false;
  }
  if (!same(claims.segment_start, receipt.segment_start) || !same(claims.segment_end, receipt.segment_end)) {
    return false;
  }
  if (!same(claims.run_id, receipt.run_id) || !same(claims.run_id, receiptRun)) return false;
  if (claims.pagination_exhausted !== true || claims.discovery_exhausted !== true) return false;
  if (String(claims.coverage_policy_version) !== COVERAGE_POLICY_VERSION) return false;
  if (String(claims.environment) !== environment) return false;
  if (typeof claims.checked_at !== "string" || !claims.checked_at) return false;
  if (!Number.isInteger(Number(receipt.raw_page_count)) || Number(receipt.raw_page_count) <= 0) {
    return false;
  }
  if (Number(claims.raw_page_count) !== Number(receipt.raw_page_count)) return false;
  if (Number(claims.raw_count) !== Number(receipt.raw_row_count)) return false;
  if (Number(claims.structured_count) !== Number(receipt.structured_row_count ?? receipt.observed_items)) {
    return false;
  }
  const extras = parseDigests(claims.extra_digests) ?? {};
  const structured = String(claims.structured_digest ?? "");
  const rawManifest = String(claims.raw_manifest_digest ?? "");
  const rawManifestFile = String(
    extras.acquisition_collection_manifest_file_digest ?? "",
  );
  const artifact = String(extras.product_artifact_digest ?? claims.structured_digest ?? "");
  const manifest = String(extras.product_manifest_digest ?? "");
  if (
    !shaPrefixed(structured) || !shaPrefixed(rawManifest) || !shaPrefixed(rawManifestFile) ||
    !shaPrefixed(artifact) || !shaPrefixed(manifest)
  ) {
    return false;
  }
  if (artifact !== structured) return false;
  const productKey = `${source}\0${claims.run_id}\0${dataset}\0${segment}`;
  const product = products.find(
    (item) =>
      `${item.source}\0${item.run_id}\0${item.dataset}\0${item.segment_id}` === productKey,
  );
  if (!product) return false;
  if (String(product.artifact_digest) !== artifact) return false;
  if (String(product.manifest_digest) !== manifest) return false;
  if (String(product.raw_manifest_digest) !== rawManifest) return false;
  if (Number(product.row_count) !== Number(claims.structured_count)) return false;
  if (Number(product.raw_row_count) !== Number(claims.raw_count)) return false;
  if (String(product.artifact_key) !== String(claims.artifact_key ?? product.artifact_key)) return false;
  if (String(product.manifest_key) !== String(claims.manifest_key ?? product.manifest_key)) return false;
  if (String(product.raw_manifest_key) !== String(claims.raw_manifest_key ?? product.raw_manifest_key)) {
    return false;
  }
  const rawKey = String(product.raw_manifest_key ?? claims.raw_manifest_key ?? "");
  if (rawKey.includes("/v2/") || rawKey.includes("recovered") || rawKey.includes("audit-only")) {
    return false;
  }
  if (!evidence?.structured?.get || !evidence.authority?.get || !evidence.raw?.get) return false;
  const MAX_ARTIFACT_BYTES = 8 * 1024 * 1024;
  const MAX_MANIFEST_BYTES = 256 * 1024;
  const rawManifestKey = String(product.raw_manifest_key ?? claims.raw_manifest_key ?? "");
  const fetches: Array<readonly [
    { get?(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null> } | null | undefined,
    string,
    string,
    number,
    number,
  ]> = [
    [evidence.structured, String(product.artifact_key), structured, Number(claims.artifact_byte_count ?? product.byte_count), MAX_ARTIFACT_BYTES],
    [evidence.authority, String(product.manifest_key), manifest, Number(claims.manifest_byte_count ?? 0), MAX_MANIFEST_BYTES],
    [evidence.raw, rawManifestKey, rawManifestFile, Number(claims.raw_manifest_byte_count ?? 0), MAX_MANIFEST_BYTES],
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
      String(item.run_id) === String(claims.run_id) &&
      String(item.dataset) === dataset &&
      String(item.segment_id) === segment &&
      String(item.environment) === environment &&
      String(item.state) === "RECEIPT_COMMITTED" &&
      String(item.operation_id) === String(product.operation_id) &&
      (item.source == null || String(item.source) === source),
  );
  if (!operation) return false;
  if (!shaPrefixed(operation.receipt_digest) || !shaPrefixed(operation.request_digest)) return false;
  if (String(operation.structured_digest || "") !== structured) return false;
  if (String(operation.raw_manifest_digest || "") !== rawManifest) return false;
  if (operation.segment_start != null && String(operation.segment_start) !== "" &&
      !same(operation.segment_start, claims.segment_start)) return false;
  if (operation.segment_end != null && String(operation.segment_end) !== "" &&
      !same(operation.segment_end, claims.segment_end)) return false;
  const issueDigest = String(claims.receipt_issue_digest ?? "");
  if (shaPrefixed(issueDigest) && issueDigest !== String(operation.request_digest)) return false;
  if (!shaPrefixed(String(claims.source_request_digest ?? ""))) return false;
  if (String(claims.source_request_digest) === String(operation.request_digest) && issueDigest === "") {
    // acquisition digest and issue identity must not be treated as identical
    return false;
  }
  const request = requests.find(
    (item) =>
      String(item.operation_id) === String(operation.operation_id) &&
      String(item.state) === "FINALIZED" &&
      String(item.environment) === environment &&
      String(item.dataset) === dataset &&
      String(item.segment_id) === segment &&
      String(item.receipt_digest) === String(operation.receipt_digest) &&
      (item.source == null || String(item.source) === source),
  );
  if (!request) return false;
  const naturals = naturalByOp.get(String(operation.operation_id));
  if (naturals !== Number(product.row_count)) return false;
  if (Number(claims.structured_count) !== naturals) return false;
  if (claims.contract_id != null && catalog && String(claims.contract_id) !== catalog.coverage.collection_scope) {
    return false;
  }
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
