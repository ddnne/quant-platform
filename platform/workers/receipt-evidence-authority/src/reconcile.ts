import {
  ACQUISITION_RESPONSE_HEADER_NAMES,
} from "../../ingestion-secrets/src/jquants_acquisition";
import {
  buildGovernedInitialRequest,
  canonicalDigest,
  canonicalJson,
  resolveGovernedRequest,
  sha256Digest,
  targetRegistryLimits,
  type GovernedRoute,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type {
  AcquisitionResponseMetadataV2,
  JquantsAcquisitionRequestV2,
} from "../../ingestion-secrets/src/jquants_acquisition_types";
import { inspectStrictJsonObject } from "../../ingestion-secrets/src/strict_json";
import { datasetById, type DatasetSpec } from "../../ingestion-premium/src/catalog";
import {
  naturalKey,
  pickEventTime,
  stableJson,
} from "../../ingestion-premium/src/identity";
import { pickAvailableAt } from "../../ingestion-premium/src/availability";
import {
  exactKeys,
  isPlainObject,
  isSha256,
  operationRunId,
} from "./canonical";
import type {
  IssuedRecord,
  OperationSnapshot,
  ReceiptEvidenceAuthority,
} from "./authority_do";
import type {
  CollectionReceiptV2,
  JsonValue,
  ReceiptAuthorityEnv,
  ReceiptIssueRequestV1,
  ReceiptIssueResultV1,
  ReceiptRecoveryRequestV1,
  ReceiptRequestV1,
  UnsignedReceiptClaimsV2,
} from "./types";

const REQUEST_KEYS = [
  "schema_version",
  "operation",
  "environment",
  "dataset_id",
  "segment_id",
  "request_nonce",
] as const;
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
const MAX_CONTEXT_AGE_MS = 15 * 60 * 1000;

type StructuredRow = {
  natural_key: string;
  source: "jquants";
  dataset: string;
  event_time: string;
  available_at: string;
  ingested_at: string;
  payload: string;
  raw_payload: string;
  row_digest: string;
};

type CapturedPage = {
  index: number;
  key: string;
  size: number;
  digest: string;
  rowCount: number;
  responseStatus: number;
  headers: Record<string, string>;
  metadata: AcquisitionResponseMetadataV2;
};

type Capture = {
  initialRequest: JquantsAcquisitionRequestV2;
  pages: CapturedPage[];
  rawManifestKey: string;
  rawManifestDigest: string;
  rawDigest: string;
  manifestFileDigest: string;
  collectionDigest: string;
  terminalChainDigest: string;
  acquisitionExpiresAt: string;
};

type D1Operation = {
  operation_id: string;
  request_digest: string;
  run_id: number;
  environment: string;
  dataset: string;
  segment_id: string;
  segment_start: string;
  segment_end: string;
  state: "COLLECTING" | "STRUCTURED_COMMITTED" | "RECEIPT_COMMITTED";
  raw_manifest_key: string | null;
  raw_manifest_digest: string | null;
  structured_manifest_key: string | null;
  structured_digest: string | null;
  receipt_digest: string | null;
  checked_at: string;
  updated_at: string;
};

type AuthorityStub = {
  begin_operation(
    operationId: string,
    requestDigest: string,
  ): Promise<OperationSnapshot>;
  recover_operation(
    operationId: string,
    requestDigest: string,
  ): Promise<OperationSnapshot>;
  append_issued(
    operationId: string,
    requestDigest: string,
    claims: UnsignedReceiptClaimsV2,
  ): Promise<IssuedRecord>;
  finalize_committed(
    operationId: string,
    requestDigest: string,
    receiptDigest: string,
    result: ReceiptIssueResultV1,
  ): Promise<ReceiptIssueResultV1>;
};

export type FaultInjection = {
  crashAfterIssueBeforeFinalize?: boolean;
};

function requireRequest(value: unknown): ReceiptRequestV1 {
  if (!isPlainObject(value) || !exactKeys(value, REQUEST_KEYS)) {
    throw new TypeError("receipt request is not closed");
  }
  if (
    value.schema_version !== "receipt-evidence-issue-request/v1" ||
    (value.operation !== "issue_for_segment" && value.operation !== "recover_issue") ||
    (value.environment !== "staging" && value.environment !== "production") ||
    typeof value.dataset_id !== "string" ||
    !/^[a-z][a-z0-9_]{2,127}$/.test(value.dataset_id) ||
    typeof value.segment_id !== "string" ||
    !/^\d{4}-\d{2}$/.test(value.segment_id) ||
    typeof value.request_nonce !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.request_nonce)
  ) {
    throw new TypeError("receipt request fields are invalid");
  }
  return value as ReceiptRequestV1;
}

function issueIdentity(request: ReceiptRequestV1): ReceiptIssueRequestV1 {
  return {
    schema_version: "receipt-evidence-issue-request/v1",
    operation: "issue_for_segment",
    environment: request.environment,
    dataset_id: request.dataset_id,
    segment_id: request.segment_id,
    request_nonce: request.request_nonce,
  };
}

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

function metadataFromHeaders(headers: Record<string, string>): AcquisitionResponseMetadataV2 {
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
  return bytes;
}

function continuationPayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "jqa2") {
    throw new Error("continuation token format invalid");
  }
  const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false })
    .decode(decodeBase64Url(parts[1]!));
  inspectStrictJsonObject(text);
  const value: unknown = JSON.parse(text);
  if (!isPlainObject(value) || !exactKeys(value, CURSOR_KEYS)) {
    throw new Error("continuation payload is not closed");
  }
  return value;
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

function strictRows(bytes: Uint8Array, route: GovernedRoute): Record<string, unknown>[] {
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
  return rows;
}

async function validatePage(input: {
  response: Response;
  body: Uint8Array;
  request: JquantsAcquisitionRequestV2;
  environment: "staging" | "production";
  index: number;
  prior: CapturedPage | null;
  now: Date;
}): Promise<{ headers: Record<string, string>; metadata: AcquisitionResponseMetadataV2; rows: Record<string, unknown>[] }> {
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
  const rows = strictRows(input.body, resolved.route);
  return { headers, metadata, rows };
}

async function putCreateOnly(
  bucket: R2Bucket,
  key: string,
  bytes: Uint8Array | string,
  metadata: Record<string, string>,
): Promise<void> {
  const payload = typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  const digest = await sha256Digest(payload);
  const stored = await bucket.put(key, payload, {
    onlyIf: { etagDoesNotMatch: "*" },
    customMetadata: { ...metadata, digest },
  });
  if (stored !== null) return;
  const existing = await bucket.get(key);
  if (existing === null) throw new Error("immutable R2 create lost a conflict");
  const existingBytes = new Uint8Array(await existing.arrayBuffer());
  if (existingBytes.byteLength !== payload.byteLength ||
    await sha256Digest(existingBytes) !== digest) {
    throw new Error("immutable R2 object replay differs from existing bytes");
  }
}

async function captureCollection(
  env: ReceiptAuthorityEnv,
  request: ReceiptIssueRequestV1,
  operationId: string,
  acquisitionNonce: string,
): Promise<Capture> {
  const started = new Date();
  const initialRequest = await buildGovernedInitialRequest({
    environment: request.environment,
    datasetId: request.dataset_id,
    segmentId: request.segment_id,
    acquisitionNonce,
    now: started,
  });
  const limits = targetRegistryLimits();
  const pages: CapturedPage[] = [];
  let current = initialRequest;
  for (let index = 0; index < limits.maximumSegmentPages; index += 1) {
    const response = await env.JQUANTS_ACQUISITION.fetch_governed_page(current);
    const body = new Uint8Array(await response.arrayBuffer());
    if (body.byteLength === 0 || body.byteLength > limits.maximumPageBytes) {
      throw new Error("acquisition page body is empty or exceeds the governed bound");
    }
    const verified = await validatePage({
      response,
      body,
      request: current,
      environment: request.environment,
      index,
      prior: pages.at(-1) ?? null,
      now: new Date(),
    });
    const digest = await sha256Digest(body);
    const key = `raw/receipt-authority/${request.environment}/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/page-${String(index).padStart(6, "0")}.json`;
    await putCreateOnly(env.RAW_BUCKET, key, body, {
      authority: "receipt",
      operation_id: operationId,
      dataset: request.dataset_id,
      segment_id: request.segment_id,
      page_ordinal: String(index),
    });
    pages.push({
      index,
      key,
      size: body.byteLength,
      digest,
      rowCount: verified.rows.length,
      responseStatus: response.status,
      headers: verified.headers,
      metadata: verified.metadata,
    });
    if (verified.metadata.pagination_state === "EXHAUSTED") break;
    current = { ...initialRequest, continuation_token: verified.metadata.continuation_token };
  }
  const terminal = pages.at(-1);
  if (
    terminal === undefined || terminal.metadata.pagination_state !== "EXHAUSTED" ||
    terminal.metadata.continuation_token !== null ||
    terminal.metadata.chain_digest === null ||
    terminal.metadata.acquisition_expires_at === null
  ) throw new Error("acquisition did not converge to authoritative exhaustion");
  if (Date.now() >= Date.parse(terminal.metadata.acquisition_expires_at)) {
    throw new Error("acquisition collection expired before persistence");
  }

  const capturePages = pages.map((page) => ({
    raw_path: page.key,
    raw_size: page.size,
    raw_digest: page.digest,
    response_status: page.responseStatus,
    headers: page.headers,
    metadata: page.metadata,
  }));
  const captureBody = {
    schema_version: "jquants-acquisition-collection/v2",
    capture_mode: "LIVE_SERVICE_BINDING_RESPONSE",
    initial_request: initialRequest,
    pages: capturePages,
  };
  const collectionDigest = await canonicalDigest(captureBody);
  const captureDocument = { ...captureBody, collection_digest: collectionDigest };
  const manifestJson = canonicalJson(captureDocument);
  const rawManifestKey = `raw/receipt-authority/${request.environment}/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/manifest.json`;
  await putCreateOnly(env.RAW_BUCKET, rawManifestKey, manifestJson, {
    authority: "receipt",
    operation_id: operationId,
    dataset: request.dataset_id,
    segment_id: request.segment_id,
  });
  const pageManifest = pages.map((page) => ({
    index: page.index,
    digest: page.digest,
    size: page.size,
  }));
  return {
    initialRequest,
    pages,
    rawManifestKey,
    rawManifestDigest: await canonicalDigest({ pages: pageManifest }),
    rawDigest: pages.length === 1
      ? pages[0]!.digest
      : await canonicalDigest({ pages: pageManifest }),
    manifestFileDigest: await sha256Digest(manifestJson),
    collectionDigest,
    terminalChainDigest: terminal.metadata.chain_digest,
    acquisitionExpiresAt: terminal.metadata.acquisition_expires_at,
  };
}

async function loadRawPage(
  bucket: R2Bucket,
  page: CapturedPage,
): Promise<Uint8Array> {
  const object = await bucket.get(page.key);
  if (object === null) throw new Error("immutable raw page disappeared");
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (bytes.byteLength !== page.size || await sha256Digest(bytes) !== page.digest) {
    throw new Error("immutable raw page changed after capture");
  }
  return bytes;
}

function expectedScope(spec: DatasetSpec, initial: JquantsAcquisitionRequestV2): {
  scope: Record<string, JsonValue>;
  expectedItems: number | null;
} {
  const eventDriven = spec.coverage.expected_frequency === "event_driven";
  return {
    scope: {
      coverage_mode: spec.coverage.coverage_mode,
      expected_frequency: spec.coverage.expected_frequency,
      expected_item_unit: eventDriven ? "source_event" : "source_query",
      segment_end: initial.segment_end,
      segment_start: initial.segment_start,
      universe_rule: spec.coverage.universe_rule,
      segment_granularity: "calendar_month",
    },
    expectedItems: eventDriven ? null : 1,
  };
}

async function initializeD1Operation(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    requestDigest: string;
    runId: number;
    request: ReceiptIssueRequestV1;
    initial: JquantsAcquisitionRequestV2;
    capture: Capture;
    checkedAt: string;
  },
): Promise<D1Operation> {
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_operations
     (operation_id,request_digest,run_id,environment,dataset,segment_id,
      segment_start,segment_end,state,raw_manifest_key,raw_manifest_digest,
      checked_at,updated_at)
     VALUES (?,?,?,?,?,?,?,?,'COLLECTING',?,?,?,?)`,
  ).bind(
    input.operationId,
    input.requestDigest,
    input.runId,
    input.request.environment,
    input.request.dataset_id,
    input.request.segment_id,
    input.initial.segment_start,
    input.initial.segment_end,
    input.capture.rawManifestKey,
    input.capture.rawManifestDigest,
    input.checkedAt,
    input.checkedAt,
  ).run();
  const row = await env.DB.prepare(
    "SELECT * FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(input.operationId).first<D1Operation>();
  if (
    row === null || row.request_digest !== input.requestDigest ||
    row.run_id !== input.runId || row.environment !== input.request.environment ||
    row.dataset !== input.request.dataset_id || row.segment_id !== input.request.segment_id ||
    row.segment_start !== input.initial.segment_start ||
    row.segment_end !== input.initial.segment_end ||
    row.raw_manifest_key !== input.capture.rawManifestKey ||
    row.raw_manifest_digest !== input.capture.rawManifestDigest ||
    row.checked_at !== input.checkedAt
  ) throw new Error("D1 receipt operation replay differs from authority measurement");
  return row;
}

async function normalizeRows(
  rows: Record<string, unknown>[],
  spec: DatasetSpec,
  checkedAt: string,
): Promise<StructuredRow[]> {
  const result: StructuredRow[] = [];
  for (const row of rows) {
    const key = await naturalKey(row, spec);
    const availableAt = pickAvailableAt(row, spec.id, checkedAt);
    const normalized = {
      natural_key: key,
      source: "jquants" as const,
      dataset: spec.id,
      event_time: pickEventTime(row, spec) ?? availableAt,
      available_at: availableAt,
      ingested_at: checkedAt,
      payload: stableJson(row),
      raw_payload: JSON.stringify(row),
    };
    result.push({
      ...normalized,
      row_digest: await canonicalDigest(normalized),
    });
  }
  return result;
}

async function persistStructuredRows(
  env: ReceiptAuthorityEnv,
  operationId: string,
  rows: StructuredRow[],
): Promise<void> {
  const statements = rows.map((row) => env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_structured_rows
     (operation_id,natural_key,source,dataset,event_time,available_at,
      ingested_at,payload,raw_payload,row_digest)
     VALUES (?,?,?,?,?,?,?,?,?,?)`,
  ).bind(
    operationId,
    row.natural_key,
    row.source,
    row.dataset,
    row.event_time,
    row.available_at,
    row.ingested_at,
    row.payload,
    row.raw_payload,
    row.row_digest,
  ));
  for (let index = 0; index < statements.length; index += 50) {
    await env.DB.batch(statements.slice(index, index + 50));
  }
}

async function readStructuredRows(
  env: ReceiptAuthorityEnv,
  operationId: string,
): Promise<StructuredRow[]> {
  const rows: StructuredRow[] = [];
  let after = "";
  while (true) {
    const page = await env.DB.prepare(
      `SELECT natural_key,source,dataset,event_time,available_at,ingested_at,
              payload,raw_payload,row_digest
       FROM receipt_authority_structured_rows
       WHERE operation_id=? AND natural_key>?
       ORDER BY natural_key LIMIT 200`,
    ).bind(operationId, after).all<StructuredRow>();
    const batch = page.results ?? [];
    rows.push(...batch);
    if (batch.length < 200) break;
    after = batch.at(-1)!.natural_key;
  }
  return rows;
}

async function structuredDigest(rows: StructuredRow[]): Promise<{
  digest: string;
  chunks: string[];
}> {
  const chunks: string[] = [];
  for (let index = 0; index < rows.length; index += 200) {
    chunks.push(await canonicalDigest(rows.slice(index, index + 200)));
  }
  return {
    digest: await canonicalDigest({
      schema_version: "receipt-structured-digest/v1",
      row_count: rows.length,
      chunk_size: 200,
      chunks,
    }),
    chunks,
  };
}

async function reconcileStructured(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    capture: Capture;
    spec: DatasetSpec;
    checkedAt: string;
  },
): Promise<{ count: number; digest: string; manifestKey: string }> {
  let rawCount = 0;
  for (const page of input.capture.pages) {
    const bytes = await loadRawPage(env.RAW_BUCKET, page);
    const resolved = await resolveGovernedRequest(
      input.capture.initialRequest,
      input.capture.initialRequest.environment,
      new Date(input.checkedAt),
    );
    const rawRows = strictRows(bytes, resolved.route);
    if (rawRows.length !== page.rowCount) {
      throw new Error("persisted raw row count differs from live capture");
    }
    rawCount += rawRows.length;
    await persistStructuredRows(
      env,
      input.operationId,
      await normalizeRows(rawRows, input.spec, input.checkedAt),
    );
  }
  if (rawCount === 0) throw new Error("zero-row collection cannot mint SUCCESS");
  const stored = await readStructuredRows(env, input.operationId);
  if (stored.length !== rawCount) {
    throw new Error("structured natural-key readback does not reconcile raw rows");
  }
  for (const row of stored) {
    const measured = await canonicalDigest({
      natural_key: row.natural_key,
      source: row.source,
      dataset: row.dataset,
      event_time: row.event_time,
      available_at: row.available_at,
      ingested_at: row.ingested_at,
      payload: row.payload,
      raw_payload: row.raw_payload,
    });
    if (
      row.source !== "jquants" || row.dataset !== input.spec.id ||
      measured !== row.row_digest
    ) throw new Error("structured D1 row changed after canonical normalization");
  }
  const measured = await structuredDigest(stored);
  const manifest = {
    schema_version: "receipt-structured-manifest/v1",
    operation_id: input.operationId,
    source: "jquants" as const,
    dataset: input.spec.id,
    row_count: stored.length,
    digest_algorithm: "receipt-structured-digest/v1",
    chunk_size: 200,
    chunk_digests: measured.chunks,
    structured_digest: measured.digest,
  };
  const manifestJson = canonicalJson(manifest);
  const manifestKey = `structured/receipt-authority/${input.capture.initialRequest.environment}/${input.spec.id}/${input.capture.initialRequest.segment_id}/${input.operationId.slice(7)}/manifest.json`;
  await putCreateOnly(env.STRUCTURED_BUCKET, manifestKey, manifestJson, {
    authority: "receipt",
    operation_id: input.operationId,
    dataset: input.spec.id,
    segment_id: input.capture.initialRequest.segment_id,
  });
  const reread = await env.STRUCTURED_BUCKET.get(manifestKey);
  if (reread === null || await reread.text() !== manifestJson) {
    throw new Error("structured immutable manifest readback failed");
  }
  await env.DB.prepare(
    `UPDATE receipt_authority_operations
     SET state='STRUCTURED_COMMITTED',structured_manifest_key=?,
         structured_digest=?,updated_at=?
     WHERE operation_id=? AND state IN ('COLLECTING','STRUCTURED_COMMITTED')`,
  ).bind(manifestKey, measured.digest, input.checkedAt, input.operationId).run();
  const operation = await env.DB.prepare(
    "SELECT * FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(input.operationId).first<D1Operation>();
  if (
    operation === null || operation.state !== "STRUCTURED_COMMITTED" ||
    operation.structured_manifest_key !== manifestKey ||
    operation.structured_digest !== measured.digest
  ) throw new Error("structured D1 commit state failed");
  return { count: stored.length, digest: measured.digest, manifestKey };
}

async function measuredClaims(input: {
  requestDigest: string;
  runId: number;
  spec: DatasetSpec;
  capture: Capture;
  structuredCount: number;
  structuredDigest: string;
  checkedAt: string;
}): Promise<UnsignedReceiptClaimsV2> {
  const { scope, expectedItems } = expectedScope(input.spec, input.capture.initialRequest);
  const rawCount = input.capture.pages.reduce((total, page) => total + page.rowCount, 0);
  if (rawCount !== input.structuredCount) {
    throw new Error("raw and structured counts do not reconcile");
  }
  if (input.spec.coverage.policy_version !== "collection-coverage/v3") {
    throw new Error("receipt authority accepts only Coverage V3");
  }
  const scopeBody = {
    coverage_policy_version: "collection-coverage/v3" as const,
    source: "jquants" as const,
    dataset: input.spec.id,
    segment_id: input.capture.initialRequest.segment_id,
    segment_start: input.capture.initialRequest.segment_start,
    segment_end: input.capture.initialRequest.segment_end,
    expected_scope: scope,
    expected_items: expectedItems,
  };
  const scopeDigest = await canonicalDigest(scopeBody);
  const unit = String(scope.expected_item_unit);
  const observation = {
    ...scopeBody,
    observed_items: unit === "source_query" ? 1 : rawCount,
    raw_page_count: input.capture.pages.length,
    raw_count: rawCount,
    structured_count: input.structuredCount,
    status: "SUCCESS" as const,
    error: null,
    pagination_exhausted: true as const,
    discovery_exhausted: true as const,
    source_request_digest: await canonicalDigest(input.capture.initialRequest),
    raw_manifest_digest: input.capture.rawManifestDigest,
    raw_digest: input.capture.rawDigest,
    structured_digest: input.structuredDigest,
    structured_generation: input.runId,
    scope_digest: scopeDigest,
    run_id: input.runId,
    checked_at: input.checkedAt,
    extra_digests: {
      acquisition_collection_manifest_file_digest: input.capture.manifestFileDigest,
      acquisition_collection_digest: input.capture.collectionDigest,
      acquisition_terminal_chain_digest: input.capture.terminalChainDigest,
    },
  };
  return {
    ...observation,
    observation_digest: await canonicalDigest(observation),
  };
}

function receiptFromIssued(issued: IssuedRecord): CollectionReceiptV2 {
  const claims = issued.claims;
  return {
    source: "jquants",
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
    digests: issued.envelope,
    run_id: claims.run_id,
    status: "SUCCESS",
    error: null,
    checked_at: claims.checked_at,
  };
}

async function commitReceipt(
  env: ReceiptAuthorityEnv,
  operationId: string,
  receipt: CollectionReceiptV2,
): Promise<string> {
  const receiptDigest = await canonicalDigest(receipt);
  await env.DB.prepare(
    `INSERT OR IGNORE INTO collection_receipts
     (source,dataset,segment_id,segment_start,segment_end,expected_scope,
      expected_items,observed_items,raw_page_count,raw_row_count,
      structured_row_count,pagination_exhausted,digests_json,run_id,status,
      error,checked_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'SUCCESS',NULL,?)`,
  ).bind(
    receipt.source,
    receipt.dataset,
    receipt.segment_id,
    receipt.segment_start,
    receipt.segment_end,
    JSON.stringify(receipt.expected_scope),
    receipt.expected_items,
    receipt.observed_items,
    receipt.raw_page_count,
    receipt.raw_row_count,
    receipt.structured_row_count,
    1,
    JSON.stringify(receipt.digests),
    receipt.run_id,
    receipt.checked_at,
  ).run();
  const row = await env.DB.prepare(
    `SELECT source,dataset,segment_id,segment_start,segment_end,expected_scope,
            expected_items,observed_items,raw_page_count,raw_row_count,
            structured_row_count,pagination_exhausted,digests_json,run_id,
            status,error,checked_at
     FROM collection_receipts
     WHERE source=? AND dataset=? AND segment_id=? AND run_id=?`,
  ).bind(
    receipt.source,
    receipt.dataset,
    receipt.segment_id,
    receipt.run_id,
  ).first<Record<string, unknown>>();
  if (row === null) throw new Error("receipt D1 insert disappeared");
  const restored: CollectionReceiptV2 = {
    source: String(row.source) as "jquants",
    dataset: String(row.dataset),
    segment_id: String(row.segment_id),
    segment_start: String(row.segment_start),
    segment_end: String(row.segment_end),
    expected_scope: JSON.parse(String(row.expected_scope)) as Record<string, JsonValue>,
    expected_items: row.expected_items === null ? null : Number(row.expected_items),
    observed_items: Number(row.observed_items),
    raw_page_count: Number(row.raw_page_count),
    raw_row_count: Number(row.raw_row_count),
    structured_row_count: Number(row.structured_row_count),
    pagination_exhausted: Boolean(row.pagination_exhausted) as true,
    digests: JSON.parse(String(row.digests_json)) as CollectionReceiptV2["digests"],
    run_id: Number(row.run_id),
    status: String(row.status) as "SUCCESS",
    error: row.error === null ? null : String(row.error) as never,
    checked_at: String(row.checked_at),
  };
  if (canonicalJson(restored) !== canonicalJson(receipt)) {
    throw new Error("persisted receipt differs from signed authority result");
  }
  await env.DB.prepare(
    `UPDATE receipt_authority_operations
     SET state='RECEIPT_COMMITTED',receipt_digest=?,updated_at=?
     WHERE operation_id=? AND state IN ('STRUCTURED_COMMITTED','RECEIPT_COMMITTED')`,
  ).bind(receiptDigest, new Date().toISOString(), operationId).run();
  return receiptDigest;
}

async function finalizeIssued(
  env: ReceiptAuthorityEnv,
  authority: AuthorityStub,
  operationId: string,
  requestDigest: string,
  issued: IssuedRecord,
  replayed: boolean,
): Promise<ReceiptIssueResultV1> {
  const receipt = receiptFromIssued(issued);
  const receiptDigest = await commitReceipt(env, operationId, receipt);
  const result: ReceiptIssueResultV1 = {
    schema_version: "receipt-evidence-issue-result/v1",
    operation_id: operationId,
    state: "FINALIZED",
    replayed: false,
    receipt_digest: receiptDigest,
    receipt,
  };
  const finalized = await authority.finalize_committed(
    operationId,
    requestDigest,
    receiptDigest,
    result,
  );
  return replayed ? { ...finalized, replayed: true } : finalized;
}

function issuedFromSnapshot(snapshot: OperationSnapshot): IssuedRecord | null {
  if (
    snapshot.claims === null || snapshot.envelope === null ||
    snapshot.envelope_digest === null
  ) return null;
  return {
    claims: snapshot.claims,
    envelope: snapshot.envelope,
    envelope_digest: snapshot.envelope_digest,
  };
}

export async function executeReceiptRequest(
  env: ReceiptAuthorityEnv,
  rawRequest: ReceiptIssueRequestV1 | ReceiptRecoveryRequestV1,
  faults: FaultInjection = {},
): Promise<ReceiptIssueResultV1> {
  const request = requireRequest(rawRequest);
  if (request.environment !== env.ENVIRONMENT) {
    throw new Error("receipt authority environment mismatch");
  }
  const identity = issueIdentity(request);
  const requestDigest = await canonicalDigest(identity);
  const operationId = requestDigest;
  const authority = env.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
    `receipt:${request.environment}`,
  ) as unknown as AuthorityStub;
  let snapshot = await authority.begin_operation(operationId, requestDigest);
  if (snapshot.state === "FINALIZED") {
    if (snapshot.result === null) throw new Error("finalized operation lost its result");
    return { ...snapshot.result, replayed: true };
  }
  const recoveredIssued = issuedFromSnapshot(snapshot);
  if (recoveredIssued !== null) {
    return finalizeIssued(
      env,
      authority,
      operationId,
      requestDigest,
      recoveredIssued,
      true,
    );
  }
  if (env.AUTHORITY_MODE !== "ACTIVE" && env.AUTHORITY_MODE !== "ACTIVE_TEST") {
    throw new Error("receipt evidence authority is PENDING activation");
  }
  if (request.operation === "recover_issue") {
    throw new Error("receipt recovery has no issued envelope to recover");
  }

  const capture = await captureCollection(
    env,
    identity,
    operationId,
    snapshot.acquisition_nonce,
  );
  const checkedAt = new Date().toISOString();
  if (Date.parse(checkedAt) >= Date.parse(capture.acquisitionExpiresAt)) {
    throw new Error("acquisition collection expired before reconciliation");
  }
  const spec = datasetById(request.dataset_id);
  if (spec === undefined || spec.coverage.policy_version !== "collection-coverage/v3") {
    throw new Error("dataset is outside the Receipt V3 authority inventory");
  }
  const runId = operationRunId(operationId);
  await initializeD1Operation(env, {
    operationId,
    requestDigest,
    runId,
    request: identity,
    initial: capture.initialRequest,
    capture,
    checkedAt,
  });
  const structured = await reconcileStructured(env, {
    operationId,
    capture,
    spec,
    checkedAt,
  });
  if (Date.now() - Date.parse(checkedAt) > MAX_CONTEXT_AGE_MS ||
    Date.now() >= Date.parse(capture.acquisitionExpiresAt)) {
    throw new Error("receipt reconciliation context expired before issuance");
  }
  const claims = await measuredClaims({
    requestDigest,
    runId,
    spec,
    capture,
    structuredCount: structured.count,
    structuredDigest: structured.digest,
    checkedAt,
  });
  const issued = await authority.append_issued(
    operationId,
    requestDigest,
    claims,
  );
  if (faults.crashAfterIssueBeforeFinalize) {
    throw new Error("injected crash after issue before finalize");
  }
  snapshot = await authority.recover_operation(operationId, requestDigest);
  const durableIssued = issuedFromSnapshot(snapshot);
  if (
    durableIssued === null || durableIssued.envelope_digest !== issued.envelope_digest ||
    canonicalJson(durableIssued.envelope) !== canonicalJson(issued.envelope)
  ) throw new Error("issued envelope was not durably appended");
  return finalizeIssued(
    env,
    authority,
    operationId,
    requestDigest,
    durableIssued,
    false,
  );
}
