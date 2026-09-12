/**
 * Identity-bound original R2 byte read. Binding possession is the caller
 * authority. Product 200 only starts an unhashed stream; DataPlane owns PASS.
 */
import {
  canonicalDigest,
  exactKeys,
  isPlainObject,
  isSha256,
  sha256Digest,
} from "../../receipt-evidence-authority/src/canonical";
import { json } from "./http_json";
import {
  describeReceiptProductInput,
  holdBody,
  parseReceiptProductInputRequest,
  RECEIPT_PRODUCT_INPUT_REQUEST,
  RECEIPT_PRODUCT_MAX_RESPONSE_BYTES,
  type ReceiptProductInputEnv,
} from "./receipt_product_input";
import {
  pinnedReceiptRegistryForEnvironment,
  verifySignedReceiptEnvelope,
} from "./ops_projection_policy";

export const RECEIPT_PRODUCT_BYTE_REQUEST =
  "receipt-product-byte-request/v1" as const;
export const OFFICIAL_CALENDAR_MAX_BYTES = 65_536;

const BYTE_REQUEST_KEYS = [
  "schema_version",
  "profile_id",
  "profile_digest",
  "dependency_closure_digest",
  "dataset",
  "segment_id",
  "operation_id",
  "receipt_digest",
  "resource",
] as const;
const COLLECTION_KEYS = [
  "schema_version",
  "capture_mode",
  "initial_request",
  "official_calendar_evidence",
  "pages",
  "collection_digest",
] as const;
const COLLECTION_PAGE_KEYS = [
  "raw_path",
  "raw_size",
  "raw_digest",
  "response_status",
  "headers",
  "metadata",
] as const;
const CALENDAR_EVIDENCE_KEYS = [
  "raw_path",
  "source_path",
  "raw_size",
  "raw_digest",
  "calendar_query_digest",
  "business_dates_digest",
  "binding_digest",
  "business_dates",
] as const;

export type ReceiptProductByteEnv = ReceiptProductInputEnv &
  Pick<Cloudflare.Env, "RAW_BUCKET" | "STRUCTURED_BUCKET">;

export type ReceiptProductByteResource =
  | "product_artifact"
  | "raw_collection_manifest"
  | "official_calendar_raw";

type ClosedByteRequest = {
  dataset: string;
  segment_id: string;
  operation_id: string;
  receipt_digest: string;
  resource: ReceiptProductByteResource;
  describe: {
    segments: Array<{ dataset: string; segment_id: string }>;
  };
};

function parseByteRequest(
  value: unknown,
): { ok: true; request: ClosedByteRequest } | { ok: false; error: string } {
  if (!isPlainObject(value)) return { ok: false, error: "invalid request" };
  if (!exactKeys(value, BYTE_REQUEST_KEYS)) {
    return { ok: false, error: "unknown field" };
  }
  if (value.schema_version !== RECEIPT_PRODUCT_BYTE_REQUEST) {
    return { ok: false, error: "invalid request" };
  }
  const resource = value.resource;
  if (
    resource !== "product_artifact" &&
    resource !== "raw_collection_manifest" &&
    resource !== "official_calendar_raw"
  ) {
    return { ok: false, error: "invalid request" };
  }
  if (
    typeof value.dataset !== "string" ||
    typeof value.segment_id !== "string" ||
    typeof value.operation_id !== "string" ||
    value.operation_id.length === 0 ||
    !isSha256(value.receipt_digest)
  ) {
    return { ok: false, error: "invalid request" };
  }
  const closed = parseReceiptProductInputRequest({
    schema_version: RECEIPT_PRODUCT_INPUT_REQUEST,
    profile_id: value.profile_id,
    profile_digest: value.profile_digest,
    dependency_closure_digest: value.dependency_closure_digest,
    segments: [{ dataset: value.dataset, segment_id: value.segment_id }],
  });
  if (!closed.ok) return { ok: false, error: closed.error };
  return {
    ok: true,
    request: {
      dataset: value.dataset,
      segment_id: value.segment_id,
      operation_id: value.operation_id,
      receipt_digest: value.receipt_digest,
      resource,
      describe: closed.request,
    },
  };
}

function hold(
  env: ReceiptProductInputEnv,
  reason: Parameters<typeof holdBody>[1],
  selector: { dataset: string; segment_id: string },
  registryDigest: string | null = null,
): Response {
  return json(holdBody(env, reason, registryDigest, selector), 409);
}

function identityHeaders(
  request: ClosedByteRequest,
): Record<string, string> {
  return {
    "content-type": "application/octet-stream",
    "x-quant-operation-id": request.operation_id,
    "x-quant-receipt-digest": request.receipt_digest,
    "x-quant-resource": request.resource,
  };
}

function officialCalendarPath(
  rawManifestKey: string,
  rawPath: string,
): boolean {
  return rawManifestKey.endsWith("manifest.json") &&
    rawPath ===
      `${rawManifestKey.slice(0, -"manifest.json".length)}official-calendar.json`;
}

async function discardObjectBody(
  object: { body?: ReadableStream | null },
): Promise<void> {
  try {
    await object.body?.cancel();
  } catch {
    /* already closed */
  }
}

async function readExactBytes(
  bucket: R2Bucket,
  key: string,
  expectedSize: number,
  maxSize: number,
): Promise<Uint8Array | "missing" | "mismatch" | "budget"> {
  if (!Number.isSafeInteger(expectedSize) || expectedSize < 1) {
    return "mismatch";
  }
  if (expectedSize > maxSize) return "budget";
  const object = await bucket.get(key);
  if (object === null) return "missing";
  if (object.size > maxSize) {
    await discardObjectBody(object);
    return "budget";
  }
  if (object.size !== expectedSize) {
    await discardObjectBody(object);
    return "mismatch";
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (bytes.byteLength !== expectedSize) return "mismatch";
  return bytes;
}

function calendarEvidence(
  value: unknown,
): Record<string, unknown> | null {
  if (!isPlainObject(value) || !exactKeys(value, CALENDAR_EVIDENCE_KEYS)) {
    return null;
  }
  if (
    typeof value.raw_path !== "string" || value.raw_path.length === 0 ||
    value.source_path !== "/v2/markets/calendar" ||
    !Number.isSafeInteger(value.raw_size) ||
    Number(value.raw_size) < 1 ||
    Number(value.raw_size) > OFFICIAL_CALENDAR_MAX_BYTES ||
    !isSha256(value.raw_digest) ||
    !isSha256(value.calendar_query_digest) ||
    !isSha256(value.business_dates_digest) ||
    !isSha256(value.binding_digest) ||
    !Array.isArray(value.business_dates) ||
    value.business_dates.length < 1 ||
    !value.business_dates.every((date) => typeof date === "string")
  ) {
    return null;
  }
  return value;
}

async function semanticRawManifestDigest(
  collection: Record<string, unknown>,
): Promise<string | null> {
  if (
    collection.schema_version !== "jquants-acquisition-collection/v2" ||
    collection.capture_mode !== "LIVE_SERVICE_BINDING_RESPONSE" ||
    !isPlainObject(collection.initial_request) ||
    !Array.isArray(collection.pages) ||
    collection.pages.length < 1 ||
    !isSha256(collection.collection_digest)
  ) {
    return null;
  }
  const pages: Array<{ index: number; digest: string; size: number }> = [];
  for (let index = 0; index < collection.pages.length; index += 1) {
    const page = collection.pages[index];
    if (
      !isPlainObject(page) || !exactKeys(page, COLLECTION_PAGE_KEYS) ||
      typeof page.raw_path !== "string" ||
      !Number.isSafeInteger(page.raw_size) || Number(page.raw_size) < 1 ||
      !isSha256(page.raw_digest)
    ) {
      return null;
    }
    pages.push({
      index,
      digest: page.raw_digest,
      size: Number(page.raw_size),
    });
  }
  return canonicalDigest({
    pages,
    official_calendar_evidence: collection.official_calendar_evidence,
  });
}

export async function readReceiptProductBytes(
  env: ReceiptProductByteEnv,
  value: unknown,
): Promise<Response> {
  const parsed = parseByteRequest(value);
  if (!parsed.ok) return json({ error: parsed.error }, 400);
  const request = parsed.request;
  if (
    request.resource === "official_calendar_raw" &&
    request.dataset !== "equities_master"
  ) {
    return json({ error: "official calendar is master-only" }, 400);
  }
  const selector = { dataset: request.dataset, segment_id: request.segment_id };
  const described = await describeReceiptProductInput(env, request.describe);
  if (described.httpStatus !== 200) {
    return json(described.body, described.httpStatus);
  }
  const segments = described.body.segments;
  if (!Array.isArray(segments) || segments.length !== 1) {
    return hold(env, "UNTRUSTED_CHAIN", selector);
  }
  const segment = segments[0];
  if (
    !isPlainObject(segment) ||
    segment.dataset !== request.dataset ||
    segment.segment_id !== request.segment_id ||
    segment.operation_id !== request.operation_id ||
    segment.receipt_digest !== request.receipt_digest ||
    !isPlainObject(segment.product) ||
    !isPlainObject(segment.signed_receipt)
  ) {
    return hold(env, "UNTRUSTED_CHAIN", selector);
  }
  const environment = env.OPS_PROJECTION_ENVIRONMENT;
  if (environment !== "staging" && environment !== "production") {
    return hold(env, "READ_FAILURE", selector);
  }
  const registry = await pinnedReceiptRegistryForEnvironment(environment);
  if (!registry) return hold(env, "PENDING_REGISTRY", selector);
  const claims = await verifySignedReceiptEnvelope(
    segment.signed_receipt,
    registry,
    environment,
  );
  if (
    claims === null ||
    claims.dataset !== request.dataset ||
    claims.segment_id !== request.segment_id ||
    claims.artifact_key !== segment.product.artifact_key ||
    claims.manifest_key !== segment.product.manifest_key ||
    claims.raw_manifest_key !== segment.product.raw_manifest_key ||
    claims.artifact_byte_count !== segment.product.byte_count ||
    claims.raw_manifest_digest !== segment.product.raw_manifest_digest
  ) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  const extras = claims.extra_digests;
  const headers = identityHeaders(request);

  if (request.resource === "product_artifact") {
    const key = claims.artifact_key;
    const expectedSize = claims.artifact_byte_count;
    const object = await env.STRUCTURED_BUCKET.get(key);
    if (object === null) {
      return hold(env, "READ_FAILURE", selector, registry.registry_digest);
    }
    if (object.size !== expectedSize || object.body === null) {
      await discardObjectBody(object);
      return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
    }
    return new Response(object.body, {
      status: 200,
      headers: {
        ...headers,
        "content-length": String(expectedSize),
      },
    });
  }

  const fileDigest = extras.acquisition_collection_manifest_file_digest;
  if (!isSha256(fileDigest)) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  const manifestBytes = await readExactBytes(
    env.RAW_BUCKET,
    claims.raw_manifest_key,
    claims.raw_manifest_byte_count,
    RECEIPT_PRODUCT_MAX_RESPONSE_BYTES,
  );
  if (manifestBytes === "missing") {
    return hold(env, "READ_FAILURE", selector, registry.registry_digest);
  }
  if (manifestBytes === "budget") {
    return hold(env, "READ_BUDGET", selector, registry.registry_digest);
  }
  if (manifestBytes === "mismatch") {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  if (await sha256Digest(manifestBytes) !== fileDigest) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  let collection: unknown;
  try {
    collection = JSON.parse(
      new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(
        manifestBytes,
      ),
    );
  } catch {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  if (!isPlainObject(collection) || !exactKeys(collection, COLLECTION_KEYS)) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  const semantic = await semanticRawManifestDigest(collection);
  if (
    semantic === null ||
    semantic !== claims.raw_manifest_digest ||
    collection.collection_digest !== extras.acquisition_collection_digest
  ) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }

  if (request.resource === "raw_collection_manifest") {
    return new Response(manifestBytes, {
      status: 200,
      headers: {
        ...headers,
        "content-length": String(manifestBytes.byteLength),
      },
    });
  }

  const evidence = calendarEvidence(collection.official_calendar_evidence);
  if (
    evidence === null ||
    typeof evidence.raw_path !== "string" ||
    !officialCalendarPath(claims.raw_manifest_key, evidence.raw_path)
  ) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  if (
    extras.official_calendar_evidence_digest !==
      await canonicalDigest(evidence) ||
    extras.official_calendar_raw_body_digest !== evidence.raw_digest ||
    extras.official_calendar_query_digest !== evidence.calendar_query_digest ||
    extras.official_business_dates_digest !== evidence.business_dates_digest ||
    extras.official_calendar_binding_digest !== evidence.binding_digest
  ) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  const calendarBytes = await readExactBytes(
    env.RAW_BUCKET,
    evidence.raw_path,
    Number(evidence.raw_size),
    OFFICIAL_CALENDAR_MAX_BYTES,
  );
  if (calendarBytes === "missing") {
    return hold(env, "READ_FAILURE", selector, registry.registry_digest);
  }
  if (calendarBytes === "budget") {
    return hold(env, "READ_BUDGET", selector, registry.registry_digest);
  }
  if (calendarBytes === "mismatch") {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  if (await sha256Digest(calendarBytes) !== evidence.raw_digest) {
    return hold(env, "UNTRUSTED_CHAIN", selector, registry.registry_digest);
  }
  return new Response(calendarBytes, {
    status: 200,
    headers: {
      ...headers,
      "content-length": String(calendarBytes.byteLength),
    },
  });
}
