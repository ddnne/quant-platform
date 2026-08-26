import {
  consumeContinuationToken,
  continuationPayload,
  initialAcquisitionSession,
  issueContinuationToken,
  type AcquisitionSession,
} from "./jquants_acquisition_cursor";
import {
  AcquisitionRequestRejected,
  canonicalDigest,
  resolveGovernedRequest,
  sha256Digest,
  targetRegistryLimits,
  type GovernedRoute,
  type ResolvedGovernedRequest,
  type TargetRegistryLimits,
} from "./jquants_acquisition_registry";
import type {
  AcquisitionEnvironment,
  AcquisitionPaginationState,
  AcquisitionResponseMetadataV2,
} from "./jquants_acquisition_types";
import {
  inspectStrictJsonObject,
  type StrictJsonTopLevelValue,
} from "./strict_json";

export type AcquisitionEnv = {
  ENVIRONMENT?: string;
  JQUANTS_API_KEY?: string;
  JQUANTS_RPC_CURSOR_HMAC_KEY?: string;
  PROXY_RATE_LIMITER?: RateLimit;
};

const RESPONSE_SCHEMA = "jquants-acquisition-rpc-response/v2";
const METADATA_SCHEMA = "jquants-acquisition-rpc-response-metadata/v2";
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);

export const ACQUISITION_RESPONSE_HEADER_NAMES = [
  "cache-control",
  "content-type",
  "x-content-type-options",
  "x-quant-acquisition-acquisition-expires-at",
  "x-quant-acquisition-acquisition-id",
  "x-quant-acquisition-acquisition-issued-at",
  "x-quant-acquisition-body-digest",
  "x-quant-acquisition-body-kind",
  "x-quant-acquisition-chain-digest",
  "x-quant-acquisition-continuation",
  "x-quant-acquisition-coverage-policy-digest",
  "x-quant-acquisition-cursor-key-id",
  "x-quant-acquisition-dataset",
  "x-quant-acquisition-dataset-contract-digest",
  "x-quant-acquisition-environment",
  "x-quant-acquisition-evidence-state",
  "x-quant-acquisition-metadata-digest",
  "x-quant-acquisition-page-ordinal",
  "x-quant-acquisition-pagination-state",
  "x-quant-acquisition-previous-chain-digest",
  "x-quant-acquisition-previous-request-digest",
  "x-quant-acquisition-provider-page-ordinal",
  "x-quant-acquisition-provider-pagination-state",
  "x-quant-acquisition-query-contract-digest",
  "x-quant-acquisition-query-digest",
  "x-quant-acquisition-redirect-count",
  "x-quant-acquisition-registry-digest",
  "x-quant-acquisition-request-digest",
  "x-quant-acquisition-request-identity-digest",
  "x-quant-acquisition-schema",
  "x-quant-acquisition-segment",
  "x-quant-acquisition-segment-end",
  "x-quant-acquisition-segment-start",
  "x-quant-acquisition-slice-date",
  "x-quant-acquisition-slice-ordinal",
  "x-quant-acquisition-source-capability-digest",
  "x-quant-acquisition-upstream-status",
] as const;

type ParsedPagination =
  | { state: "EXHAUSTED" }
  | { state: "CONTINUATION"; parameter: string; cursor: string }
  | { state: "UNKNOWN" };

type PageQuery = {
  sliceDate: string | null;
  query: URLSearchParams;
  queryDigest: string;
};

function textBytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function errorBytes(code: string): Uint8Array {
  return textBytes(JSON.stringify({ error: code }));
}

function headerValue(value: string | number | null): string {
  return value === null ? "NONE" : String(value);
}

function blankMetadata(
  environment: AcquisitionEnvironment | null,
  evidenceState: "REJECTED" | "FAILED",
  bodyDigest: string,
): AcquisitionResponseMetadataV2 {
  return {
    schema_version: METADATA_SCHEMA,
    evidence_state: evidenceState,
    environment,
    dataset_id: null,
    segment_id: null,
    segment_start: null,
    segment_end: null,
    request_digest: null,
    request_identity_digest: null,
    previous_request_digest: null,
    acquisition_id: null,
    acquisition_issued_at: null,
    acquisition_expires_at: null,
    target_registry_digest: null,
    source_capability_digest: null,
    dataset_contract_digest: null,
    coverage_policy_digest: null,
    query_contract_digest: null,
    cursor_key_id: null,
    slice_date: null,
    query_digest: null,
    page_ordinal: null,
    slice_ordinal: null,
    provider_page_ordinal: null,
    provider_pagination_state: "NOT_APPLICABLE",
    upstream_http_status: null,
    body_digest: bodyDigest,
    body_kind: "TARGET_ERROR_JSON",
    pagination_state: "NOT_APPLICABLE",
    continuation_token: null,
    content_type: "application/json",
    redirect_count: 0,
    previous_chain_digest: null,
    chain_digest: null,
  };
}

function resolvedMetadata(
  resolved: ResolvedGovernedRequest,
  session: AcquisitionSession | null,
  bodyDigest: string,
  evidenceState: "REJECTED" | "FAILED",
): AcquisitionResponseMetadataV2 {
  const metadata = blankMetadata(resolved.request.environment, evidenceState, bodyDigest);
  return {
    ...metadata,
    dataset_id: resolved.request.dataset_id,
    segment_id: resolved.request.segment_id,
    segment_start: resolved.segmentStart,
    segment_end: resolved.segmentEnd,
    request_digest: resolved.requestDigest,
    request_identity_digest: resolved.requestIdentityDigest,
    previous_request_digest: session?.previousRequestDigest ?? null,
    acquisition_id: session?.acquisitionId ?? null,
    acquisition_issued_at: session?.issuedAt ?? null,
    acquisition_expires_at: session?.expiresAt ?? null,
    target_registry_digest: resolved.route.registryDigest,
    source_capability_digest: resolved.route.sourceCapabilityDigest,
    dataset_contract_digest: resolved.route.datasetContractDigest,
    coverage_policy_digest: resolved.route.coveragePolicyDigest,
    query_contract_digest: resolved.route.queryContractDigest,
    cursor_key_id: session?.cursorKeyId ?? null,
    page_ordinal: session?.pageOrdinal ?? null,
    slice_ordinal: session?.sliceOrdinal ?? null,
    provider_page_ordinal: session?.providerPageOrdinal ?? null,
    previous_chain_digest: session?.previousChainDigest ?? null,
  };
}

async function responseWithMetadata(
  body: Uint8Array,
  status: number,
  metadata: AcquisitionResponseMetadataV2,
): Promise<Response> {
  const actualBodyDigest = await sha256Digest(body);
  if (actualBodyDigest !== metadata.body_digest) throw new Error("body digest mismatch");
  const metadataDigest = await canonicalDigest(metadata);
  const headers = new Headers({
    "cache-control": "no-store",
    "content-type": metadata.content_type,
    "x-content-type-options": "nosniff",
    "x-quant-acquisition-acquisition-expires-at": headerValue(metadata.acquisition_expires_at),
    "x-quant-acquisition-acquisition-id": headerValue(metadata.acquisition_id),
    "x-quant-acquisition-acquisition-issued-at": headerValue(metadata.acquisition_issued_at),
    "x-quant-acquisition-body-digest": metadata.body_digest,
    "x-quant-acquisition-body-kind": metadata.body_kind,
    "x-quant-acquisition-chain-digest": headerValue(metadata.chain_digest),
    "x-quant-acquisition-continuation": headerValue(metadata.continuation_token),
    "x-quant-acquisition-coverage-policy-digest": headerValue(metadata.coverage_policy_digest),
    "x-quant-acquisition-cursor-key-id": headerValue(metadata.cursor_key_id),
    "x-quant-acquisition-dataset": headerValue(metadata.dataset_id),
    "x-quant-acquisition-dataset-contract-digest": headerValue(metadata.dataset_contract_digest),
    "x-quant-acquisition-environment": headerValue(metadata.environment),
    "x-quant-acquisition-evidence-state": metadata.evidence_state,
    "x-quant-acquisition-metadata-digest": metadataDigest,
    "x-quant-acquisition-page-ordinal": headerValue(metadata.page_ordinal),
    "x-quant-acquisition-pagination-state": metadata.pagination_state,
    "x-quant-acquisition-previous-chain-digest": headerValue(metadata.previous_chain_digest),
    "x-quant-acquisition-previous-request-digest": headerValue(metadata.previous_request_digest),
    "x-quant-acquisition-provider-page-ordinal": headerValue(metadata.provider_page_ordinal),
    "x-quant-acquisition-provider-pagination-state": metadata.provider_pagination_state,
    "x-quant-acquisition-query-contract-digest": headerValue(metadata.query_contract_digest),
    "x-quant-acquisition-query-digest": headerValue(metadata.query_digest),
    "x-quant-acquisition-redirect-count": String(metadata.redirect_count),
    "x-quant-acquisition-registry-digest": headerValue(metadata.target_registry_digest),
    "x-quant-acquisition-request-digest": headerValue(metadata.request_digest),
    "x-quant-acquisition-request-identity-digest": headerValue(metadata.request_identity_digest),
    "x-quant-acquisition-schema": RESPONSE_SCHEMA,
    "x-quant-acquisition-segment": headerValue(metadata.segment_id),
    "x-quant-acquisition-segment-end": headerValue(metadata.segment_end),
    "x-quant-acquisition-segment-start": headerValue(metadata.segment_start),
    "x-quant-acquisition-slice-date": headerValue(metadata.slice_date),
    "x-quant-acquisition-slice-ordinal": headerValue(metadata.slice_ordinal),
    "x-quant-acquisition-source-capability-digest": headerValue(metadata.source_capability_digest),
    "x-quant-acquisition-upstream-status": headerValue(metadata.upstream_http_status),
  });
  const noBodyStatus = status === 204 || status === 205 || status === 304;
  return new Response(noBodyStatus ? null : body, { status, headers });
}

async function errorResponse(
  code: string,
  status: number,
  environment: AcquisitionEnvironment | null,
  evidenceState: "REJECTED" | "FAILED",
  resolved: ResolvedGovernedRequest | null = null,
  session: AcquisitionSession | null = null,
  upstreamStatus: number | null = null,
): Promise<Response> {
  const body = errorBytes(code);
  const digest = await sha256Digest(body);
  const metadata = resolved
    ? resolvedMetadata(resolved, session, digest, evidenceState)
    : blankMetadata(environment, evidenceState, digest);
  metadata.upstream_http_status = upstreamStatus;
  return responseWithMetadata(body, status, metadata);
}

function targetEnvironment(env: AcquisitionEnv): AcquisitionEnvironment | null {
  return env.ENVIRONMENT === "production" || env.ENVIRONMENT === "staging"
    ? env.ENVIRONMENT
    : null;
}

function validateOfficialTarget(url: URL, expected: URL, officialOrigin: string): void {
  const official = new URL(officialOrigin);
  if (
    url.protocol !== "https:" || url.origin !== official.origin ||
    url.username !== "" || url.password !== "" || url.port !== "" ||
    url.pathname !== expected.pathname || url.search !== expected.search ||
    url.hash !== ""
  ) throw new AcquisitionRequestRejected("upstream_target_rejected");
}

async function governedFetch(
  target: URL,
  apiKey: string,
  limits: TargetRegistryLimits,
): Promise<Response> {
  validateOfficialTarget(target, target, limits.officialOrigin);
  const response = await fetch(target.toString(), {
    method: "GET",
    headers: { "x-api-key": apiKey },
    redirect: "manual",
  });
  if (REDIRECT_STATUSES.has(response.status)) {
    await response.body?.cancel();
    throw new AcquisitionRequestRejected("redirect_rejected");
  }
  if (response.url) {
    validateOfficialTarget(new URL(response.url), target, limits.officialOrigin);
  }
  return response;
}

async function readBoundedBody(response: Response, maximumBytes: number): Promise<Uint8Array> {
  if (response.body === null) return new Uint8Array();
  const declared = response.headers.get("content-length");
  if (declared !== null) {
    const value = Number(declared);
    if (!Number.isSafeInteger(value) || value < 0 || value > maximumBytes) {
      await response.body.cancel();
      throw new AcquisitionRequestRejected("upstream_body_limit");
    }
  }
  const reader = response.body.getReader();
  const declaredSize = declared === null ? null : Number(declared);
  let result = new Uint8Array(
    declaredSize ?? Math.min(maximumBytes, 64 * 1024),
  );
  let total = 0;
  try {
    while (true) {
      const item = await reader.read();
      if (item.done) break;
      const nextTotal = total + item.value.byteLength;
      if (nextTotal > maximumBytes) {
        await reader.cancel();
        throw new AcquisitionRequestRejected("upstream_body_limit");
      }
      if (nextTotal > result.byteLength) {
        let nextCapacity = Math.max(1, result.byteLength);
        while (nextCapacity < nextTotal) {
          nextCapacity = Math.min(maximumBytes, nextCapacity * 2);
        }
        const grown = new Uint8Array(nextCapacity);
        grown.set(result.subarray(0, total));
        result = grown;
      }
      result.set(item.value, total);
      total = nextTotal;
    }
  } finally {
    reader.releaseLock();
  }
  return result.subarray(0, total);
}

function normalizedContentType(response: Response): "application/json" | "application/octet-stream" {
  const mediaType = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  return mediaType === "application/json"
    ? "application/json"
    : "application/octet-stream";
}

function parsePagination(bytes: Uint8Array, route: GovernedRoute): ParsedPagination {
  let values: ReadonlyMap<string, StrictJsonTopLevelValue>;
  try {
    values = inspectStrictJsonObject(
      new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes),
    );
  } catch {
    return { state: "UNKNOWN" };
  }
  if (values.get("data")?.kind !== "array") return { state: "UNKNOWN" };
  let informationalCursorPresent = false;
  for (const [key, value] of values) {
    if (key === "data") continue;
    if (route.allowedIgnoredResponseFields.has(key)) {
      if (value.kind === "null") continue;
      if (value.kind !== "string" || !validProviderCursor(value.value)) {
        return { state: "UNKNOWN" };
      }
      informationalCursorPresent = true;
      continue;
    }
    if (!route.paginationParameters.has(key)) return { state: "UNKNOWN" };
  }
  const recognized = [...route.paginationParameters.keys()].filter(
    (field) => values.has(field),
  );
  if (recognized.length === 0) return { state: "EXHAUSTED" };
  if (recognized.length !== 1) return { state: "UNKNOWN" };
  const field = recognized[0]!;
  const cursor = values.get(field)!;
  if (cursor.kind === "null") return { state: "EXHAUSTED" };
  if (cursor.kind !== "string" || !validProviderCursor(cursor.value)) {
    return { state: "UNKNOWN" };
  }
  if (informationalCursorPresent) return { state: "UNKNOWN" };
  return {
    state: "CONTINUATION",
    parameter: route.paginationParameters.get(field)!,
    cursor: cursor.value,
  };
}

function validProviderCursor(value: unknown): value is string {
  if (typeof value !== "string" || value.length < 1 || value.length > 2048) return false;
  const encoded = new TextEncoder().encode(value);
  if (encoded.byteLength > 2048 ||
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(encoded) !== value) return false;
  return !/[\u0000-\u001f\u007f]/.test(value);
}

function addDays(value: string, days: number): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return new Date(parsed.getTime() + days * 86_400_000).toISOString().slice(0, 10);
}

function validateSession(resolved: ResolvedGovernedRequest, session: AcquisitionSession): void {
  if (resolved.route.queryMode === "calendar_month_range") {
    if (session.sliceDate !== null || session.sliceOrdinal !== 0) {
      throw new AcquisitionRequestRejected("continuation_slice");
    }
  } else {
    const expected = addDays(resolved.segmentStart, session.sliceOrdinal);
    if (session.sliceDate !== expected || expected > resolved.segmentEnd) {
      throw new AcquisitionRequestRejected("continuation_slice");
    }
  }
  if (
    (session.providerPageOrdinal === 0 &&
      (session.continuationParameter !== null || session.providerCursor !== null)) ||
    (session.providerPageOrdinal > 0 &&
      (session.continuationParameter !== "pagination_key" || session.providerCursor === null))
  ) throw new AcquisitionRequestRejected("continuation_page");
}

async function buildPageQuery(
  resolved: ResolvedGovernedRequest,
  session: AcquisitionSession,
): Promise<PageQuery> {
  validateSession(resolved, session);
  const query = new URLSearchParams();
  if (resolved.route.queryMode === "calendar_month_range") {
    query.set("from", resolved.segmentStart);
    query.set("to", resolved.segmentEnd);
  } else {
    query.set("date", session.sliceDate!);
  }
  if (session.continuationParameter !== null && session.providerCursor !== null) {
    query.set(session.continuationParameter, session.providerCursor);
  }
  const queryDigest = await canonicalDigest({
    schema_version: "jquants-acquisition-query/v2",
    path: resolved.route.path,
    ordered_query: [...query.entries()],
  });
  return { sliceDate: session.sliceDate, query, queryDigest };
}

async function pageChainDigest(input: {
  resolved: ResolvedGovernedRequest;
  session: AcquisitionSession;
  queryDigest: string;
  bodyDigest: string;
  upstreamStatus: number;
  evidenceState: "RAW_PAGE" | "RAW_ONLY";
  providerState: AcquisitionPaginationState;
  segmentState: AcquisitionPaginationState;
}): Promise<string> {
  return canonicalDigest({
    schema_version: "jquants-acquisition-chain-link/v2",
    acquisition_id: input.session.acquisitionId,
    cursor_key_id: input.session.cursorKeyId,
    acquisition_issued_at: input.session.issuedAt,
    acquisition_expires_at: input.session.expiresAt,
    request_digest: input.resolved.requestDigest,
    request_identity_digest: input.resolved.requestIdentityDigest,
    previous_request_digest: input.session.previousRequestDigest,
    previous_chain_digest: input.session.previousChainDigest,
    page_ordinal: input.session.pageOrdinal,
    slice_date: input.session.sliceDate,
    slice_ordinal: input.session.sliceOrdinal,
    provider_page_ordinal: input.session.providerPageOrdinal,
    query_digest: input.queryDigest,
    body_digest: input.bodyDigest,
    upstream_http_status: input.upstreamStatus,
    evidence_state: input.evidenceState,
    provider_pagination_state: input.providerState,
    pagination_state: input.segmentState,
  });
}

function audit(
  resolved: ResolvedGovernedRequest | null,
  acquisitionId: string | null,
  outcome: string,
  status: number,
): void {
  console.info(JSON.stringify({
    event: "jquants_acquisition_rpc",
    worker: "ingestion-secrets",
    operation: "fetch_governed_page",
    environment: resolved?.request.environment ?? null,
    dataset: resolved?.request.dataset_id ?? null,
    segment_id: resolved?.request.segment_id ?? null,
    acquisition_id: acquisitionId,
    result: outcome,
    status,
    redirect_count: 0,
  }));
}

export async function fetchGovernedPage(
  rawRequest: unknown,
  env: AcquisitionEnv,
  now = new Date(),
): Promise<Response> {
  const environment = targetEnvironment(env);
  if (environment === null || !env.JQUANTS_API_KEY || !env.JQUANTS_RPC_CURSOR_HMAC_KEY || !env.PROXY_RATE_LIMITER) {
    const response = await errorResponse("rpc_unavailable", 503, environment, "FAILED");
    audit(null, null, "FAILED", response.status);
    return response;
  }

  let resolved: ResolvedGovernedRequest;
  try {
    resolved = await resolveGovernedRequest(rawRequest, environment, now);
  } catch {
    const response = await errorResponse("request_rejected", 400, environment, "REJECTED");
    audit(null, null, "REJECTED", response.status);
    return response;
  }
  const limits = targetRegistryLimits();
  let session: AcquisitionSession;
  try {
    session = resolved.request.continuation_token === null
      ? await initialAcquisitionSession(env.JQUANTS_RPC_CURSOR_HMAC_KEY, resolved, now, limits)
      : await consumeContinuationToken(
        env.JQUANTS_RPC_CURSOR_HMAC_KEY,
        resolved.request.continuation_token,
        resolved,
        now,
        limits,
      );
    validateSession(resolved, session);
  } catch {
    const response = await errorResponse("request_rejected", 400, environment, "REJECTED", resolved);
    audit(resolved, null, "REJECTED", response.status);
    return response;
  }

  let page: PageQuery;
  try {
    page = await buildPageQuery(resolved, session);
  } catch {
    const response = await errorResponse("request_rejected", 400, environment, "REJECTED", resolved, session);
    audit(resolved, session.acquisitionId, "REJECTED", response.status);
    return response;
  }
  try {
    const rate = await env.PROXY_RATE_LIMITER.limit({ key: "jquants-acquisition-rpc-v2" });
    if (!rate.success) {
      const response = await errorResponse("rate_limited", 429, environment, "FAILED", resolved, session);
      audit(resolved, session.acquisitionId, "FAILED", response.status);
      return response;
    }
  } catch {
    const response = await errorResponse("rpc_unavailable", 503, environment, "FAILED", resolved, session);
    audit(resolved, session.acquisitionId, "FAILED", response.status);
    return response;
  }

  const target = new URL(resolved.route.path, limits.officialOrigin);
  target.search = page.query.toString();
  let upstream: Response;
  try {
    upstream = await governedFetch(target, env.JQUANTS_API_KEY, limits);
  } catch {
    const response = await errorResponse("upstream_unavailable", 502, environment, "FAILED", resolved, session);
    audit(resolved, session.acquisitionId, "FAILED", response.status);
    return response;
  }
  if (!upstream.ok) {
    const upstreamStatus = upstream.status;
    try {
      await upstream.body?.cancel();
    } catch {
      // A provider-controlled body stream cannot be allowed to suppress the
      // target-owned, fail-closed error envelope.
    }
    const response = await errorResponse("upstream_failed", 502, environment, "FAILED", resolved, session, upstreamStatus);
    audit(resolved, session.acquisitionId, "FAILED", response.status);
    return response;
  }

  let body: Uint8Array;
  try {
    body = await readBoundedBody(upstream, limits.maximumPageBytes);
  } catch {
    const response = await errorResponse("upstream_unavailable", 502, environment, "FAILED", resolved, session, upstream.status);
    audit(resolved, session.acquisitionId, "FAILED", response.status);
    return response;
  }
  const bodyDigest = await sha256Digest(body);
  let provider: ParsedPagination = upstream.status === 200 && normalizedContentType(upstream) === "application/json"
    ? parsePagination(body, resolved.route)
    : { state: "UNKNOWN" as const };
  if (provider.state === "CONTINUATION" && provider.cursor === session.providerCursor) {
    provider = { state: "UNKNOWN" };
  }
  let evidenceState: "RAW_PAGE" | "RAW_ONLY" = provider.state === "UNKNOWN" ? "RAW_ONLY" : "RAW_PAGE";
  let segmentState: AcquisitionPaginationState = provider.state;
  let next: {
    sliceDate: string | null;
    sliceOrdinal: number;
    providerPageOrdinal: number;
    parameter: string | null;
    cursor: string | null;
  } | null = null;

  if (provider.state === "CONTINUATION") {
    next = {
      sliceDate: session.sliceDate,
      sliceOrdinal: session.sliceOrdinal,
      providerPageOrdinal: session.providerPageOrdinal + 1,
      parameter: provider.parameter,
      cursor: provider.cursor,
    };
  } else if (provider.state === "EXHAUSTED" &&
    resolved.route.queryMode === "calendar_month_sliced" &&
    session.sliceDate !== null && session.sliceDate < resolved.segmentEnd) {
    segmentState = "CONTINUATION";
    next = {
      sliceDate: addDays(session.sliceDate, 1),
      sliceOrdinal: session.sliceOrdinal + 1,
      providerPageOrdinal: 0,
      parameter: null,
      cursor: null,
    };
  }
  if (next !== null &&
    (session.pageOrdinal + 1 >= limits.maximumSegmentPages ||
      next.providerPageOrdinal >= limits.maximumProviderPagesPerSlice)) {
    evidenceState = "RAW_ONLY";
    segmentState = "UNKNOWN";
    next = null;
  }

  let chainDigest = await pageChainDigest({
    resolved,
    session,
    queryDigest: page.queryDigest,
    bodyDigest,
    upstreamStatus: upstream.status,
    evidenceState,
    providerState: provider.state,
    segmentState,
  });
  let continuationToken: string | null = null;
  if (next !== null) {
    try {
      const issuedToken = await issueContinuationToken(
        env.JQUANTS_RPC_CURSOR_HMAC_KEY,
        continuationPayload({
          resolved,
          session,
          nextPageOrdinal: session.pageOrdinal + 1,
          nextSliceDate: next.sliceDate,
          nextSliceOrdinal: next.sliceOrdinal,
          nextProviderPageOrdinal: next.providerPageOrdinal,
          continuationParameter: next.parameter,
          providerCursor: next.cursor,
          previousChainDigest: chainDigest,
          previousRequestDigest: resolved.requestDigest,
        }),
      );
      if (issuedToken.length > 8192) {
        throw new AcquisitionRequestRejected("continuation_size");
      }
      continuationToken = issuedToken;
    } catch {
      evidenceState = "RAW_ONLY";
      segmentState = "UNKNOWN";
      chainDigest = await pageChainDigest({
        resolved,
        session,
        queryDigest: page.queryDigest,
        bodyDigest,
        upstreamStatus: upstream.status,
        evidenceState,
        providerState: provider.state,
        segmentState,
      });
    }
  }

  const metadata: AcquisitionResponseMetadataV2 = {
    schema_version: METADATA_SCHEMA,
    evidence_state: evidenceState,
    environment,
    dataset_id: resolved.request.dataset_id,
    segment_id: resolved.request.segment_id,
    segment_start: resolved.segmentStart,
    segment_end: resolved.segmentEnd,
    request_digest: resolved.requestDigest,
    request_identity_digest: resolved.requestIdentityDigest,
    previous_request_digest: session.previousRequestDigest,
    acquisition_id: session.acquisitionId,
    acquisition_issued_at: session.issuedAt,
    acquisition_expires_at: session.expiresAt,
    target_registry_digest: resolved.route.registryDigest,
    source_capability_digest: resolved.route.sourceCapabilityDigest,
    dataset_contract_digest: resolved.route.datasetContractDigest,
    coverage_policy_digest: resolved.route.coveragePolicyDigest,
    query_contract_digest: resolved.route.queryContractDigest,
    cursor_key_id: session.cursorKeyId,
    slice_date: page.sliceDate,
    query_digest: page.queryDigest,
    page_ordinal: session.pageOrdinal,
    slice_ordinal: session.sliceOrdinal,
    provider_page_ordinal: session.providerPageOrdinal,
    provider_pagination_state: provider.state,
    upstream_http_status: upstream.status,
    body_digest: bodyDigest,
    body_kind: "UPSTREAM_EXACT_BYTES",
    pagination_state: segmentState,
    continuation_token: continuationToken,
    content_type: normalizedContentType(upstream),
    redirect_count: 0,
    previous_chain_digest: session.previousChainDigest,
    chain_digest: chainDigest,
  };
  const response = await responseWithMetadata(body, upstream.status, metadata);
  audit(resolved, session.acquisitionId, evidenceState, response.status);
  return response;
}
