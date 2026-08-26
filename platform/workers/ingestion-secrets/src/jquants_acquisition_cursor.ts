import {
  AcquisitionRequestRejected,
  canonicalJson,
  sha256Digest,
  type ResolvedGovernedRequest,
  type TargetRegistryLimits,
} from "./jquants_acquisition_registry";
import type { AcquisitionEnvironment } from "./jquants_acquisition_types";

type CursorPayload = {
  schema_version: "jquants-acquisition-continuation/v2";
  environment: AcquisitionEnvironment;
  dataset_id: string;
  segment_id: string;
  segment_start: string;
  segment_end: string;
  source_capability_digest: string;
  dataset_contract_digest: string;
  coverage_policy_digest: string;
  query_contract_digest: string;
  target_registry_digest: string;
  request_identity_digest: string;
  target_session_nonce: string;
  acquisition_id: string;
  cursor_key_id: string;
  acquisition_issued_at: string;
  acquisition_expires_at: string;
  page_ordinal: number;
  slice_date: string | null;
  slice_ordinal: number;
  provider_page_ordinal: number;
  continuation_parameter: string | null;
  provider_cursor: string | null;
  previous_chain_digest: string;
  previous_request_digest: string;
};

export type AcquisitionSession = {
  acquisitionId: string;
  targetSessionNonce: string;
  cursorKeyId: string;
  issuedAt: string;
  expiresAt: string;
  pageOrdinal: number;
  sliceDate: string | null;
  sliceOrdinal: number;
  providerPageOrdinal: number;
  continuationParameter: string | null;
  providerCursor: string | null;
  previousChainDigest: string;
  previousRequestDigest: string | null;
};

const CURSOR_KEYS = [
  "schema_version", "environment", "dataset_id", "segment_id",
  "segment_start", "segment_end", "source_capability_digest",
  "dataset_contract_digest", "coverage_policy_digest", "query_contract_digest",
  "target_registry_digest", "request_identity_digest", "acquisition_id",
  "target_session_nonce",
  "cursor_key_id", "acquisition_issued_at", "acquisition_expires_at",
  "page_ordinal", "slice_date", "slice_ordinal", "provider_page_ordinal",
  "continuation_parameter", "provider_cursor", "previous_chain_digest",
  "previous_request_digest",
] as const;
const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const HMAC_RE = /^hmac-sha256:[0-9a-f]{64}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function validProviderCursor(value: unknown): value is string {
  if (typeof value !== "string" || value.length < 1 || value.length > 2048) return false;
  const encoded = new TextEncoder().encode(value);
  return encoded.byteLength <= 2048 &&
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(encoded) === value &&
    !/[\u0000-\u001f\u007f]/.test(value);
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlDecode(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new AcquisitionRequestRejected("continuation_encoding");
  }
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") +
    "=".repeat((4 - (value.length % 4)) % 4);
  let binary: string;
  try {
    binary = atob(padded);
  } catch {
    throw new AcquisitionRequestRejected("continuation_encoding");
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  if (base64UrlEncode(bytes) !== value) {
    throw new AcquisitionRequestRejected("continuation_encoding");
  }
  return bytes;
}

async function importHmacKey(secret: string): Promise<CryptoKey> {
  const bytes = new TextEncoder().encode(secret);
  if (bytes.byteLength < 32 || bytes.byteLength > 4096) {
    throw new AcquisitionRequestRejected("rpc_unavailable");
  }
  return crypto.subtle.importKey(
    "raw", bytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"],
  );
}

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map(
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}

async function hmacDigest(key: CryptoKey, value: string): Promise<string> {
  return `hmac-sha256:${hex(await crypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(value),
  ))}`;
}

export async function cursorKeyId(secret: string): Promise<string> {
  return hmacDigest(
    await importHmacKey(secret),
    "jquants-acquisition-cursor-key-id/v2",
  );
}

async function acquisitionId(
  key: CryptoKey,
  requestIdentityDigest: string,
  targetSessionNonce: string,
  issuedAt: string,
): Promise<string> {
  return hmacDigest(key, canonicalJson({
    schema_version: "jquants-acquisition-id/v2",
    request_identity_digest: requestIdentityDigest,
    target_session_nonce: targetSessionNonce,
    acquisition_issued_at: issuedAt,
  }));
}

export async function initialAcquisitionSession(
  secret: string,
  resolved: ResolvedGovernedRequest,
  now: Date,
  limits: TargetRegistryLimits,
): Promise<AcquisitionSession> {
  const key = await importHmacKey(secret);
  const issuedAt = now.toISOString();
  const expiresAt = new Date(now.getTime() + limits.continuationTtlSeconds * 1000).toISOString();
  const keyId = await hmacDigest(key, "jquants-acquisition-cursor-key-id/v2");
  const sessionBytes = crypto.getRandomValues(new Uint8Array(32));
  const targetSessionNonce = [...sessionBytes].map(
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
  const id = await acquisitionId(
    key, resolved.requestIdentityDigest, targetSessionNonce, issuedAt,
  );
  return {
    acquisitionId: id,
    targetSessionNonce,
    cursorKeyId: keyId,
    issuedAt,
    expiresAt,
    pageOrdinal: 0,
    sliceDate: resolved.route.queryMode === "calendar_month_sliced" ? resolved.segmentStart : null,
    sliceOrdinal: 0,
    providerPageOrdinal: 0,
    continuationParameter: null,
    providerCursor: null,
    previousChainDigest: await sha256Digest(canonicalJson({
      schema_version: "jquants-acquisition-chain-genesis/v2",
      acquisition_id: id,
      request_identity_digest: resolved.requestIdentityDigest,
      cursor_key_id: keyId,
      acquisition_issued_at: issuedAt,
      acquisition_expires_at: expiresAt,
    })),
    previousRequestDigest: null,
  };
}

function decodePayload(bytes: Uint8Array): CursorPayload {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes));
  } catch {
    throw new AcquisitionRequestRejected("continuation_payload");
  }
  if (!isObject(value) || !exactKeys(value, CURSOR_KEYS) ||
    value.schema_version !== "jquants-acquisition-continuation/v2" ||
    (value.environment !== "staging" && value.environment !== "production") ||
    typeof value.dataset_id !== "string" || typeof value.segment_id !== "string" ||
    typeof value.segment_start !== "string" || !DATE_RE.test(value.segment_start) ||
    typeof value.segment_end !== "string" || !DATE_RE.test(value.segment_end) ||
    typeof value.source_capability_digest !== "string" || !SHA256_RE.test(value.source_capability_digest) ||
    typeof value.dataset_contract_digest !== "string" || !SHA256_RE.test(value.dataset_contract_digest) ||
    typeof value.coverage_policy_digest !== "string" || !SHA256_RE.test(value.coverage_policy_digest) ||
    typeof value.query_contract_digest !== "string" || !SHA256_RE.test(value.query_contract_digest) ||
    typeof value.target_registry_digest !== "string" || !SHA256_RE.test(value.target_registry_digest) ||
    typeof value.request_identity_digest !== "string" || !SHA256_RE.test(value.request_identity_digest) ||
    typeof value.target_session_nonce !== "string" || !/^[0-9a-f]{64}$/.test(value.target_session_nonce) ||
    typeof value.acquisition_id !== "string" || !HMAC_RE.test(value.acquisition_id) ||
    typeof value.cursor_key_id !== "string" || !HMAC_RE.test(value.cursor_key_id) ||
    typeof value.acquisition_issued_at !== "string" || !ISO_RE.test(value.acquisition_issued_at) ||
    typeof value.acquisition_expires_at !== "string" || !ISO_RE.test(value.acquisition_expires_at) ||
    !Number.isSafeInteger(value.page_ordinal) || Number(value.page_ordinal) < 1 ||
    !(value.slice_date === null || (typeof value.slice_date === "string" && DATE_RE.test(value.slice_date))) ||
    !Number.isSafeInteger(value.slice_ordinal) || Number(value.slice_ordinal) < 0 ||
    !Number.isSafeInteger(value.provider_page_ordinal) || Number(value.provider_page_ordinal) < 0 ||
    !((value.continuation_parameter === null && value.provider_cursor === null) ||
      (value.continuation_parameter === "pagination_key" &&
        validProviderCursor(value.provider_cursor))) ||
    typeof value.previous_chain_digest !== "string" || !SHA256_RE.test(value.previous_chain_digest) ||
    typeof value.previous_request_digest !== "string" || !SHA256_RE.test(value.previous_request_digest)
  ) throw new AcquisitionRequestRejected("continuation_payload");
  return value as CursorPayload;
}

export async function issueContinuationToken(
  secret: string,
  payload: CursorPayload,
): Promise<string> {
  const canonical = canonicalJson(payload);
  const payloadBytes = new TextEncoder().encode(canonical);
  if (new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(payloadBytes) !== canonical) {
    throw new AcquisitionRequestRejected("continuation_payload");
  }
  decodePayload(payloadBytes);
  const encoded = base64UrlEncode(payloadBytes);
  const signature = new Uint8Array(await crypto.subtle.sign(
    "HMAC", await importHmacKey(secret), new TextEncoder().encode(encoded),
  ));
  return `jqa2.${encoded}.${base64UrlEncode(signature)}`;
}

export async function consumeContinuationToken(
  secret: string,
  token: string,
  resolved: ResolvedGovernedRequest,
  now: Date,
  limits: TargetRegistryLimits,
): Promise<AcquisitionSession> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "jqa2") {
    throw new AcquisitionRequestRejected("continuation_format");
  }
  const key = await importHmacKey(secret);
  const payloadPart = parts[1]!;
  const signature = base64UrlDecode(parts[2]!);
  if (signature.byteLength !== 32 || !await crypto.subtle.verify(
    "HMAC", key, signature, new TextEncoder().encode(payloadPart),
  )) throw new AcquisitionRequestRejected("continuation_signature");
  const payload = decodePayload(base64UrlDecode(payloadPart));
  const expectedKeyId = await hmacDigest(key, "jquants-acquisition-cursor-key-id/v2");
  const expectedAcquisitionId = await acquisitionId(
    key,
    resolved.requestIdentityDigest,
    payload.target_session_nonce,
    payload.acquisition_issued_at,
  );
  if (
    payload.environment !== resolved.request.environment ||
    payload.dataset_id !== resolved.request.dataset_id ||
    payload.segment_id !== resolved.request.segment_id ||
    payload.segment_start !== resolved.segmentStart ||
    payload.segment_end !== resolved.segmentEnd ||
    payload.source_capability_digest !== resolved.route.sourceCapabilityDigest ||
    payload.dataset_contract_digest !== resolved.route.datasetContractDigest ||
    payload.coverage_policy_digest !== resolved.route.coveragePolicyDigest ||
    payload.query_contract_digest !== resolved.route.queryContractDigest ||
    payload.target_registry_digest !== resolved.route.registryDigest ||
    payload.request_identity_digest !== resolved.requestIdentityDigest ||
    payload.cursor_key_id !== expectedKeyId || payload.acquisition_id !== expectedAcquisitionId ||
    payload.page_ordinal >= limits.maximumSegmentPages ||
    payload.provider_page_ordinal >= limits.maximumProviderPagesPerSlice ||
    (payload.continuation_parameter !== null &&
      resolved.route.paginationParameters.get(payload.continuation_parameter) !== payload.continuation_parameter)
  ) throw new AcquisitionRequestRejected("continuation_identity");
  const issued = Date.parse(payload.acquisition_issued_at);
  const expires = Date.parse(payload.acquisition_expires_at);
  if (!Number.isFinite(issued) || !Number.isFinite(expires) ||
    expires - issued !== limits.continuationTtlSeconds * 1000 ||
    now.getTime() < issued || now.getTime() >= expires) {
    throw new AcquisitionRequestRejected("continuation_expired");
  }
  return {
    acquisitionId: payload.acquisition_id,
    targetSessionNonce: payload.target_session_nonce,
    cursorKeyId: payload.cursor_key_id,
    issuedAt: payload.acquisition_issued_at,
    expiresAt: payload.acquisition_expires_at,
    pageOrdinal: payload.page_ordinal,
    sliceDate: payload.slice_date,
    sliceOrdinal: payload.slice_ordinal,
    providerPageOrdinal: payload.provider_page_ordinal,
    continuationParameter: payload.continuation_parameter,
    providerCursor: payload.provider_cursor,
    previousChainDigest: payload.previous_chain_digest,
    previousRequestDigest: payload.previous_request_digest,
  };
}

export function continuationPayload(input: {
  resolved: ResolvedGovernedRequest;
  session: AcquisitionSession;
  nextPageOrdinal: number;
  nextSliceDate: string | null;
  nextSliceOrdinal: number;
  nextProviderPageOrdinal: number;
  continuationParameter: string | null;
  providerCursor: string | null;
  previousChainDigest: string;
  previousRequestDigest: string;
}): CursorPayload {
  const { resolved, session } = input;
  return {
    schema_version: "jquants-acquisition-continuation/v2",
    environment: resolved.request.environment,
    dataset_id: resolved.request.dataset_id,
    segment_id: resolved.request.segment_id,
    segment_start: resolved.segmentStart,
    segment_end: resolved.segmentEnd,
    source_capability_digest: resolved.route.sourceCapabilityDigest,
    dataset_contract_digest: resolved.route.datasetContractDigest,
    coverage_policy_digest: resolved.route.coveragePolicyDigest,
    query_contract_digest: resolved.route.queryContractDigest,
    target_registry_digest: resolved.route.registryDigest,
    request_identity_digest: resolved.requestIdentityDigest,
    target_session_nonce: session.targetSessionNonce,
    acquisition_id: session.acquisitionId,
    cursor_key_id: session.cursorKeyId,
    acquisition_issued_at: session.issuedAt,
    acquisition_expires_at: session.expiresAt,
    page_ordinal: input.nextPageOrdinal,
    slice_date: input.nextSliceDate,
    slice_ordinal: input.nextSliceOrdinal,
    provider_page_ordinal: input.nextProviderPageOrdinal,
    continuation_parameter: input.continuationParameter,
    provider_cursor: input.providerCursor,
    previous_chain_digest: input.previousChainDigest,
    previous_request_digest: input.previousRequestDigest,
  };
}
