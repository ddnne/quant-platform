import {
  ACQUISITION_RESPONSE_HEADER_NAMES,
} from "../../ingestion-secrets/src/jquants_acquisition";
import {
  canonicalDigest,
  canonicalJson,
  resolveGovernedRequest,
  sha256Digest,
  type GovernedRoute,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type {
  AcquisitionResponseMetadataV2,
  JquantsAcquisitionRequestV2,
} from "../../ingestion-secrets/src/jquants_acquisition_types";
import { inspectStrictJsonObject } from "../../ingestion-secrets/src/strict_json";
import { exactKeys, isPlainObject, isSha256 } from "./canonical";

const HEADER_NAMES = [...ACQUISITION_RESPONSE_HEADER_NAMES].sort();
const CURSOR_KEYS = [
  "schema_version", "environment", "dataset_id", "segment_id",
  "segment_start", "segment_end", "source_capability_digest",
  "dataset_contract_digest", "coverage_policy_digest", "query_contract_digest",
  "target_registry_digest", "request_identity_digest", "target_session_nonce",
  "acquisition_id", "cursor_key_id", "acquisition_issued_at",
  "acquisition_expires_at", "page_ordinal", "slice_date", "slice_ordinal",
  "provider_page_ordinal", "continuation_parameter", "provider_cursor",
  "previous_chain_digest", "previous_request_digest",
] as const;

export type RawPageEvidence = {
  rows: Record<string, unknown>[];
  providerState: "CONTINUATION" | "EXHAUSTED";
  continuationParameter: "pagination_key" | null;
  providerCursor: string | null;
};

export type PriorAcquisitionPage = {
  metadata: AcquisitionResponseMetadataV2;
};

function nullable(value: string): string | null {
  return value === "NONE" ? null : value;
}

function nullableInteger(value: string, name: string): number | null {
  if (value === "NONE") return null;
  if (!/^(?:0|[1-9][0-9]*)$/.test(value)) {
    throw new Error(`acquisition ${name} is not a canonical integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) throw new Error(`acquisition ${name} is unsafe`);
  return parsed;
}

function responseHeaders(response: Response): Record<string, string> {
  const names = [...response.headers.keys()].sort();
  if (
    names.length !== HEADER_NAMES.length ||
    names.some((name, index) => name !== HEADER_NAMES[index])
  ) {
    throw new Error("acquisition response header surface drifted");
  }
  const result: Record<string, string> = {};
  for (const name of HEADER_NAMES) {
    const value = response.headers.get(name);
    if (value === null) throw new Error(`acquisition response header missing: ${name}`);
    result[name] = value;
  }
  return result;
}

function metadataFromHeaders(
  headers: Record<string, string>,
): AcquisitionResponseMetadataV2 {
  return {
    schema_version: "jquants-acquisition-rpc-response-metadata/v2",
    evidence_state: headers["x-quant-acquisition-evidence-state"] as AcquisitionResponseMetadataV2["evidence_state"],
    environment: nullable(headers["x-quant-acquisition-environment"]!) as AcquisitionResponseMetadataV2["environment"],
    dataset_id: nullable(headers["x-quant-acquisition-dataset"]!),
    segment_id: nullable(headers["x-quant-acquisition-segment"]!),
    segment_start: nullable(headers["x-quant-acquisition-segment-start"]!),
    segment_end: nullable(headers["x-quant-acquisition-segment-end"]!),
    request_digest: nullable(headers["x-quant-acquisition-request-digest"]!),
    request_identity_digest: nullable(headers["x-quant-acquisition-request-identity-digest"]!),
    previous_request_digest: nullable(headers["x-quant-acquisition-previous-request-digest"]!),
    acquisition_id: nullable(headers["x-quant-acquisition-acquisition-id"]!),
    acquisition_issued_at: nullable(headers["x-quant-acquisition-acquisition-issued-at"]!),
    acquisition_expires_at: nullable(headers["x-quant-acquisition-acquisition-expires-at"]!),
    target_registry_digest: nullable(headers["x-quant-acquisition-registry-digest"]!),
    source_capability_digest: nullable(headers["x-quant-acquisition-source-capability-digest"]!),
    dataset_contract_digest: nullable(headers["x-quant-acquisition-dataset-contract-digest"]!),
    coverage_policy_digest: nullable(headers["x-quant-acquisition-coverage-policy-digest"]!),
    query_contract_digest: nullable(headers["x-quant-acquisition-query-contract-digest"]!),
    cursor_key_id: nullable(headers["x-quant-acquisition-cursor-key-id"]!),
    slice_date: nullable(headers["x-quant-acquisition-slice-date"]!),
    query_digest: nullable(headers["x-quant-acquisition-query-digest"]!),
    page_ordinal: nullableInteger(headers["x-quant-acquisition-page-ordinal"]!, "page ordinal"),
    slice_ordinal: nullableInteger(headers["x-quant-acquisition-slice-ordinal"]!, "slice ordinal"),
    provider_page_ordinal: nullableInteger(headers["x-quant-acquisition-provider-page-ordinal"]!, "provider ordinal"),
    provider_pagination_state: headers["x-quant-acquisition-provider-pagination-state"] as AcquisitionResponseMetadataV2["provider_pagination_state"],
    upstream_http_status: nullableInteger(headers["x-quant-acquisition-upstream-status"]!, "upstream status"),
    body_digest: headers["x-quant-acquisition-body-digest"]!,
    body_kind: headers["x-quant-acquisition-body-kind"] as AcquisitionResponseMetadataV2["body_kind"],
    pagination_state: headers["x-quant-acquisition-pagination-state"] as AcquisitionResponseMetadataV2["pagination_state"],
    continuation_token: nullable(headers["x-quant-acquisition-continuation"]!),
    content_type: headers["content-type"] as AcquisitionResponseMetadataV2["content_type"],
    redirect_count: Number(headers["x-quant-acquisition-redirect-count"]),
    previous_chain_digest: nullable(headers["x-quant-acquisition-previous-chain-digest"]!),
    chain_digest: nullable(headers["x-quant-acquisition-chain-digest"]!),
  };
}

function decodeBase64Url(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("continuation encoding invalid");
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") +
    "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const canonical = btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  if (canonical !== value) throw new Error("continuation encoding is not canonical");
  return bytes;
}

function continuationPayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "jqa2") {
    throw new Error("continuation token format invalid");
  }
  if (decodeBase64Url(parts[2]!).byteLength !== 32) {
    throw new Error("continuation signature shape invalid");
  }
  const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false })
    .decode(decodeBase64Url(parts[1]!));
  inspectStrictJsonObject(text);
  const value: unknown = JSON.parse(text);
  if (!isPlainObject(value) || !exactKeys(value, CURSOR_KEYS)) {
    throw new Error("continuation payload is not closed");
  }
  if (canonicalJson(value) !== text) {
    throw new Error("continuation payload is not canonical");
  }
  return value;
}

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) throw new Error("acquisition date is invalid");
  return new Date(date.getTime() + days * 86_400_000)
    .toISOString()
    .slice(0, 10);
}

function validProviderCursor(value: unknown): value is string {
  if (typeof value !== "string" || value.length < 1 || value.length > 2048) {
    return false;
  }
  const bytes = new TextEncoder().encode(value);
  return bytes.byteLength <= 2048 &&
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes) === value &&
    !/[\u0000-\u001f\u007f]/.test(value);
}

async function expectedQueryDigest(
  request: JquantsAcquisitionRequestV2,
  route: GovernedRoute,
  metadata: AcquisitionResponseMetadataV2,
): Promise<string> {
  const ordered: [string, string][] = [];
  if (route.queryMode === "calendar_month_range") {
    ordered.push(["from", request.segment_start], ["to", request.segment_end]);
  } else {
    if (metadata.slice_date === null) throw new Error("sliced acquisition omitted date");
    ordered.push(["date", metadata.slice_date]);
  }
  if (request.continuation_token !== null) {
    const payload = continuationPayload(request.continuation_token);
    if (
      payload.environment !== request.environment ||
      payload.dataset_id !== request.dataset_id ||
      payload.segment_id !== request.segment_id ||
      payload.page_ordinal !== metadata.page_ordinal ||
      payload.slice_date !== metadata.slice_date ||
      payload.slice_ordinal !== metadata.slice_ordinal ||
      payload.provider_page_ordinal !== metadata.provider_page_ordinal
    ) throw new Error("continuation payload identity drifted");
    if (payload.continuation_parameter !== null) {
      if (
        payload.continuation_parameter !== "pagination_key" ||
        typeof payload.provider_cursor !== "string" ||
        payload.provider_cursor.length === 0
      ) throw new Error("continuation provider cursor invalid");
      ordered.push(["pagination_key", payload.provider_cursor]);
    } else if (payload.provider_cursor !== null) {
      throw new Error("continuation cursor is unpaired");
    }
  }
  return canonicalDigest({
    schema_version: "jquants-acquisition-query/v2",
    path: route.path,
    ordered_query: ordered,
  });
}

async function expectedPreviousChain(
  metadata: AcquisitionResponseMetadataV2,
): Promise<string> {
  if (
    metadata.acquisition_id === null || metadata.request_identity_digest === null ||
    metadata.cursor_key_id === null || metadata.acquisition_issued_at === null ||
    metadata.acquisition_expires_at === null
  ) throw new Error("acquisition genesis identity missing");
  return canonicalDigest({
    schema_version: "jquants-acquisition-chain-genesis/v2",
    acquisition_id: metadata.acquisition_id,
    request_identity_digest: metadata.request_identity_digest,
    cursor_key_id: metadata.cursor_key_id,
    acquisition_issued_at: metadata.acquisition_issued_at,
    acquisition_expires_at: metadata.acquisition_expires_at,
  });
}

async function expectedChainDigest(
  metadata: AcquisitionResponseMetadataV2,
): Promise<string> {
  return canonicalDigest({
    schema_version: "jquants-acquisition-chain-link/v2",
    acquisition_id: metadata.acquisition_id,
    cursor_key_id: metadata.cursor_key_id,
    acquisition_issued_at: metadata.acquisition_issued_at,
    acquisition_expires_at: metadata.acquisition_expires_at,
    request_digest: metadata.request_digest,
    request_identity_digest: metadata.request_identity_digest,
    previous_request_digest: metadata.previous_request_digest,
    previous_chain_digest: metadata.previous_chain_digest,
    page_ordinal: metadata.page_ordinal,
    slice_date: metadata.slice_date,
    slice_ordinal: metadata.slice_ordinal,
    provider_page_ordinal: metadata.provider_page_ordinal,
    query_digest: metadata.query_digest,
    body_digest: metadata.body_digest,
    upstream_http_status: metadata.upstream_http_status,
    evidence_state: metadata.evidence_state,
    provider_pagination_state: metadata.provider_pagination_state,
    pagination_state: metadata.pagination_state,
  });
}

export function parseStrictRawPage(
  bytes: Uint8Array,
  route: GovernedRoute,
): RawPageEvidence {
  const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes);
  const shape = inspectStrictJsonObject(text);
  if (shape.get("data")?.kind !== "array") throw new Error("raw data envelope missing");
  const allowed = new Set([
    "data",
    ...route.paginationParameters.keys(),
    ...route.allowedIgnoredResponseFields,
  ]);
  for (const key of shape.keys()) {
    if (!allowed.has(key)) throw new Error("raw data envelope field drifted");
  }
  const parsed: unknown = JSON.parse(text);
  if (!isPlainObject(parsed) || !Array.isArray(parsed.data)) {
    throw new Error("raw data envelope invalid");
  }
  const rows: Record<string, unknown>[] = [];
  for (const row of parsed.data) {
    if (!isPlainObject(row)) throw new Error("raw data row is not an object");
    rows.push(row);
  }
  let informationalCursorPresent = false;
  for (const key of route.allowedIgnoredResponseFields) {
    if (!(key in parsed)) continue;
    const value = parsed[key];
    if (value === null) continue;
    if (!validProviderCursor(value)) {
      throw new Error("raw informational cursor is invalid");
    }
    informationalCursorPresent = true;
  }
  const recognized = [...route.paginationParameters.keys()].filter(
    (field) => field in parsed,
  );
  if (recognized.length === 0) {
    return {
      rows,
      providerState: "EXHAUSTED",
      continuationParameter: null,
      providerCursor: null,
    };
  }
  if (recognized.length !== 1) {
    throw new Error("raw pagination field is ambiguous");
  }
  const field = recognized[0]!;
  const cursor = parsed[field];
  if (cursor === null) {
    return {
      rows,
      providerState: "EXHAUSTED",
      continuationParameter: null,
      providerCursor: null,
    };
  }
  if (informationalCursorPresent || !validProviderCursor(cursor)) {
    throw new Error("raw provider continuation is not authoritative");
  }
  const parameter = route.paginationParameters.get(field);
  if (parameter !== "pagination_key") {
    throw new Error("raw provider continuation parameter drifted");
  }
  return {
    rows,
    providerState: "CONTINUATION",
    continuationParameter: "pagination_key",
    providerCursor: cursor,
  };
}

function requireCursorPayloadMatches(
  payload: Record<string, unknown>,
  expected: Record<string, unknown>,
  label: string,
): void {
  for (const [key, value] of Object.entries(expected)) {
    if (payload[key] !== value) {
      throw new Error(`${label} continuation ${key} drifted`);
    }
  }
}

function validatePaginationTransition(input: {
  request: JquantsAcquisitionRequestV2;
  route: GovernedRoute;
  metadata: AcquisitionResponseMetadataV2;
  raw: RawPageEvidence;
}): void {
  const { request, route, metadata, raw } = input;
  if (
    metadata.page_ordinal === null || metadata.slice_ordinal === null ||
    metadata.provider_page_ordinal === null ||
    metadata.acquisition_id === null || metadata.cursor_key_id === null ||
    metadata.acquisition_issued_at === null ||
    metadata.acquisition_expires_at === null ||
    metadata.request_identity_digest === null || metadata.request_digest === null ||
    metadata.chain_digest === null
  ) throw new Error("acquisition pagination identity is incomplete");
  if (metadata.provider_pagination_state !== raw.providerState) {
    throw new Error("provider pagination state differs from immutable raw bytes");
  }
  if (route.queryMode === "calendar_month_range") {
    if (metadata.slice_date !== null || metadata.slice_ordinal !== 0) {
      throw new Error("range pagination carried a slice identity");
    }
  } else {
    const expectedDate = addDays(request.segment_start, metadata.slice_ordinal);
    if (
      metadata.slice_date !== expectedDate ||
      expectedDate > request.segment_end
    ) throw new Error("sliced pagination date/ordinal drifted");
  }

  let currentPayload: Record<string, unknown> | null = null;
  if (request.continuation_token === null) {
    if (
      metadata.page_ordinal !== 0 || metadata.slice_ordinal !== 0 ||
      metadata.provider_page_ordinal !== 0 ||
      (route.queryMode === "calendar_month_sliced" &&
        metadata.slice_date !== request.segment_start)
    ) throw new Error("initial acquisition pagination identity drifted");
  } else {
    currentPayload = continuationPayload(request.continuation_token);
    requireCursorPayloadMatches(currentPayload, {
      schema_version: "jquants-acquisition-continuation/v2",
      environment: request.environment,
      dataset_id: request.dataset_id,
      segment_id: request.segment_id,
      segment_start: request.segment_start,
      segment_end: request.segment_end,
      source_capability_digest: request.source_capability_digest,
      dataset_contract_digest: request.dataset_contract_digest,
      coverage_policy_digest: request.coverage_policy_digest,
      query_contract_digest: request.query_contract_digest,
      target_registry_digest: request.target_registry_digest,
      request_identity_digest: metadata.request_identity_digest,
      acquisition_id: metadata.acquisition_id,
      cursor_key_id: metadata.cursor_key_id,
      acquisition_issued_at: metadata.acquisition_issued_at,
      acquisition_expires_at: metadata.acquisition_expires_at,
      page_ordinal: metadata.page_ordinal,
      slice_date: metadata.slice_date,
      slice_ordinal: metadata.slice_ordinal,
      provider_page_ordinal: metadata.provider_page_ordinal,
      previous_chain_digest: metadata.previous_chain_digest,
      previous_request_digest: metadata.previous_request_digest,
    }, "request");
    if (
      typeof currentPayload.target_session_nonce !== "string" ||
      !/^[0-9a-f]{64}$/.test(currentPayload.target_session_nonce)
    ) throw new Error("request continuation target session nonce is invalid");
    if (
      (metadata.provider_page_ordinal === 0 &&
        (currentPayload.continuation_parameter !== null ||
          currentPayload.provider_cursor !== null)) ||
      (metadata.provider_page_ordinal > 0 &&
        (currentPayload.continuation_parameter !== "pagination_key" ||
          !validProviderCursor(currentPayload.provider_cursor)))
    ) throw new Error("request continuation provider cursor/ordinal drifted");
  }

  let next: {
    sliceDate: string | null;
    sliceOrdinal: number;
    providerPageOrdinal: number;
    continuationParameter: "pagination_key" | null;
    providerCursor: string | null;
  } | null = null;
  if (raw.providerState === "CONTINUATION") {
    if (metadata.pagination_state !== "CONTINUATION") {
      throw new Error("provider continuation cannot terminate the segment");
    }
    next = {
      sliceDate: metadata.slice_date,
      sliceOrdinal: metadata.slice_ordinal,
      providerPageOrdinal: metadata.provider_page_ordinal + 1,
      continuationParameter: raw.continuationParameter,
      providerCursor: raw.providerCursor,
    };
  } else if (
    route.queryMode === "calendar_month_sliced" &&
    metadata.slice_date !== null && metadata.slice_date < request.segment_end
  ) {
    if (metadata.pagination_state !== "CONTINUATION") {
      throw new Error("sliced acquisition terminated before the final date");
    }
    next = {
      sliceDate: addDays(metadata.slice_date, 1),
      sliceOrdinal: metadata.slice_ordinal + 1,
      providerPageOrdinal: 0,
      continuationParameter: null,
      providerCursor: null,
    };
  } else if (metadata.pagination_state !== "EXHAUSTED") {
    throw new Error("terminal provider page did not exhaust the segment");
  }

  if (next === null) {
    if (metadata.continuation_token !== null) {
      throw new Error("terminal segment returned a continuation token");
    }
    if (
      metadata.provider_pagination_state !== "EXHAUSTED" ||
      (route.queryMode === "calendar_month_sliced" &&
        metadata.slice_date !== request.segment_end)
    ) throw new Error("segment exhaustion is not at the authoritative terminal");
    return;
  }
  if (metadata.continuation_token === null) {
    throw new Error("non-terminal segment omitted continuation token");
  }
  const responsePayload = continuationPayload(metadata.continuation_token);
  const targetSessionNonce = currentPayload?.target_session_nonce ??
    responsePayload.target_session_nonce;
  if (
    typeof targetSessionNonce !== "string" ||
    !/^[0-9a-f]{64}$/.test(targetSessionNonce)
  ) throw new Error("continuation target session nonce is invalid");
  requireCursorPayloadMatches(responsePayload, {
    schema_version: "jquants-acquisition-continuation/v2",
    environment: request.environment,
    dataset_id: request.dataset_id,
    segment_id: request.segment_id,
    segment_start: request.segment_start,
    segment_end: request.segment_end,
    source_capability_digest: request.source_capability_digest,
    dataset_contract_digest: request.dataset_contract_digest,
    coverage_policy_digest: request.coverage_policy_digest,
    query_contract_digest: request.query_contract_digest,
    target_registry_digest: request.target_registry_digest,
    request_identity_digest: metadata.request_identity_digest,
    target_session_nonce: targetSessionNonce,
    acquisition_id: metadata.acquisition_id,
    cursor_key_id: metadata.cursor_key_id,
    acquisition_issued_at: metadata.acquisition_issued_at,
    acquisition_expires_at: metadata.acquisition_expires_at,
    page_ordinal: metadata.page_ordinal + 1,
    slice_date: next.sliceDate,
    slice_ordinal: next.sliceOrdinal,
    provider_page_ordinal: next.providerPageOrdinal,
    continuation_parameter: next.continuationParameter,
    provider_cursor: next.providerCursor,
    previous_chain_digest: metadata.chain_digest,
    previous_request_digest: metadata.request_digest,
  }, "response");
}

export async function validateAcquisitionPage(input: {
  response: Response;
  body: Uint8Array;
  request: JquantsAcquisitionRequestV2;
  environment: "staging" | "production";
  index: number;
  prior: PriorAcquisitionPage | null;
  now: Date;
}): Promise<{
  headers: Record<string, string>;
  metadata: AcquisitionResponseMetadataV2;
  rows: Record<string, unknown>[];
}> {
  const headers = responseHeaders(input.response);
  const metadata = metadataFromHeaders(headers);
  const resolved = await resolveGovernedRequest(input.request, input.environment, input.now);
  if (
    input.response.status !== 200 || metadata.upstream_http_status !== 200 ||
    metadata.evidence_state !== "RAW_PAGE" ||
    metadata.body_kind !== "UPSTREAM_EXACT_BYTES" ||
    metadata.content_type !== "application/json" ||
    metadata.redirect_count !== 0 ||
    metadata.page_ordinal !== input.index ||
    metadata.environment !== input.environment ||
    metadata.dataset_id !== input.request.dataset_id ||
    metadata.segment_id !== input.request.segment_id ||
    metadata.segment_start !== resolved.segmentStart ||
    metadata.segment_end !== resolved.segmentEnd ||
    metadata.request_digest !== resolved.requestDigest ||
    metadata.request_identity_digest !== resolved.requestIdentityDigest ||
    metadata.target_registry_digest !== resolved.route.registryDigest ||
    metadata.source_capability_digest !== resolved.route.sourceCapabilityDigest ||
    metadata.dataset_contract_digest !== resolved.route.datasetContractDigest ||
    metadata.coverage_policy_digest !== resolved.route.coveragePolicyDigest ||
    metadata.query_contract_digest !== resolved.route.queryContractDigest ||
    metadata.query_digest !== await expectedQueryDigest(input.request, resolved.route, metadata) ||
    metadata.body_digest !== await sha256Digest(input.body) ||
    headers["x-quant-acquisition-metadata-digest"] !== await canonicalDigest(metadata) ||
    !isSha256(metadata.chain_digest) ||
    metadata.chain_digest !== await expectedChainDigest(metadata)
  ) throw new Error("acquisition page failed independent reconciliation");

  if (input.prior === null) {
    if (
      metadata.previous_request_digest !== null ||
      metadata.previous_chain_digest !== await expectedPreviousChain(metadata)
    ) throw new Error("acquisition genesis chain drifted");
  } else if (
    metadata.previous_request_digest !== input.prior.metadata.request_digest ||
    metadata.previous_chain_digest !== input.prior.metadata.chain_digest ||
    metadata.acquisition_id !== input.prior.metadata.acquisition_id ||
    metadata.cursor_key_id !== input.prior.metadata.cursor_key_id ||
    metadata.acquisition_issued_at !== input.prior.metadata.acquisition_issued_at ||
    metadata.acquisition_expires_at !== input.prior.metadata.acquisition_expires_at
  ) {
    throw new Error("acquisition continuation chain drifted");
  }
  if (
    (metadata.pagination_state === "CONTINUATION" && metadata.continuation_token === null) ||
    (metadata.pagination_state === "EXHAUSTED" && metadata.continuation_token !== null) ||
    !["CONTINUATION", "EXHAUSTED"].includes(metadata.pagination_state) ||
    !["CONTINUATION", "EXHAUSTED"].includes(metadata.provider_pagination_state)
  ) throw new Error("acquisition exhaustion state is not authoritative");
  const raw = parseStrictRawPage(input.body, resolved.route);
  validatePaginationTransition({
    request: input.request,
    route: resolved.route,
    metadata,
    raw,
  });
  return { headers, metadata, rows: raw.rows };
}
