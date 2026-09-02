import {
  buildGovernedInitialRequest,
  canonicalDigest,
  canonicalJson,
  sha256Digest,
  targetRegistryLimits,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type {
  AcquisitionResponseMetadataV2,
  JquantsAcquisitionRequestV2,
} from "../../ingestion-secrets/src/jquants_acquisition_types";
import {
  deriveOfficialCalendarProof,
  validateAcquisitionPage,
  type OfficialCalendarProof,
} from "./pagination_proof";
import { exactKeys, isPlainObject, isSha256 } from "./canonical";
import type {
  JsdaPersistedRequestV1,
  ReceiptAuthorityEnv,
  ReceiptIssueRequestV1,
} from "./types";

export type CapturedPage = {
  index: number;
  key: string;
  size: number;
  digest: string;
  rowCount: number;
  responseStatus: number;
  headers: Record<string, string>;
  metadata: AcquisitionResponseMetadataV2;
};

export type Capture = {
  initialRequest: JquantsAcquisitionRequestV2 | JsdaPersistedRequestV1;
  pages: CapturedPage[];
  rawManifestKey: string;
  rawManifestDigest: string;
  rawDigest: string;
  manifestFileDigest: string;
  rawManifestByteCount: number;
  collectionDigest: string;
  terminalChainDigest: string;
  acquisitionExpiresAt: string;
  paginationExhausted: true;
  discoveryExhausted: true;
  officialCalendarEvidence: CapturedOfficialCalendar | null;
};

export type CaptureBindingContext = {
  operationId: string;
  requestDigest: string;
  captureAttemptId: string;
  acquisitionNonce: string;
  collectionStartedAt: string;
  request: ReceiptIssueRequestV1;
};

export type CaptureRecoveryContext = CaptureBindingContext & {
  key: string;
  expectedDigest: string;
};

export type CapturedOfficialCalendar = {
  key: string;
  path: "/v2/markets/calendar";
  size: number;
  digest: string;
  calendarQueryDigest: string;
  businessDatesDigest: string;
  bindingDigest: string;
  businessDates: readonly string[];
};

const CAPTURE_STATE_SCHEMA = "receipt-authority-capture-state/v2" as const;
const CAPTURE_VALIDATOR_SCHEMA = "receipt-authority-capture-validator/v1" as const;
const CAPTURE_STATE_KEYS = [
  "schema_version",
  "validator",
  "authority_binding",
  "capture",
] as const;
const CAPTURE_VALIDATOR_KEYS = [
  "schema_version",
  "capture_deployment_version",
  "digest",
] as const;
const CAPTURE_AUTHORITY_BINDING_KEYS = [
  "environment",
  "dataset_id",
  "segment_id",
  "operation_id",
  "request_digest",
  "capture_attempt_id",
  "acquisition_nonce",
  "collection_started_at",
] as const;
const CAPTURE_KEYS = [
  "initialRequest",
  "pages",
  "rawManifestKey",
  "rawManifestDigest",
  "rawDigest",
  "manifestFileDigest",
  "rawManifestByteCount",
  "collectionDigest",
  "terminalChainDigest",
  "acquisitionExpiresAt",
  "paginationExhausted",
  "discoveryExhausted",
  "officialCalendarEvidence",
] as const;
const CAPTURE_PAGE_KEYS = [
  "index",
  "key",
  "size",
  "digest",
  "rowCount",
  "responseStatus",
  "headers",
  "metadata",
] as const;
const CAPTURE_CALENDAR_KEYS = [
  "key",
  "path",
  "size",
  "digest",
  "calendarQueryDigest",
  "businessDatesDigest",
  "bindingDigest",
  "businessDates",
] as const;

type CaptureStateV2 = {
  schema_version: typeof CAPTURE_STATE_SCHEMA;
  validator: {
    schema_version: typeof CAPTURE_VALIDATOR_SCHEMA;
    capture_deployment_version: string;
    digest: string;
  };
  authority_binding: {
    environment: "staging" | "production";
    dataset_id: string;
    segment_id: string;
    operation_id: string;
    request_digest: string;
    capture_attempt_id: string;
    acquisition_nonce: string;
    collection_started_at: string;
  };
  capture: Capture;
};

type DerivedCaptureArtifacts = Pick<
  Capture,
  | "rawManifestKey"
  | "rawManifestDigest"
  | "rawDigest"
  | "manifestFileDigest"
  | "rawManifestByteCount"
  | "collectionDigest"
  | "terminalChainDigest"
  | "acquisitionExpiresAt"
  | "paginationExhausted"
  | "discoveryExhausted"
> & { manifestJson: string };

export function capturedOfficialCalendarDescriptor(
  evidence: CapturedOfficialCalendar | null,
): Record<string, unknown> | null {
  if (evidence === null) return null;
  return {
    raw_path: evidence.key,
    source_path: evidence.path,
    raw_size: evidence.size,
    raw_digest: evidence.digest,
    calendar_query_digest: evidence.calendarQueryDigest,
    business_dates_digest: evidence.businessDatesDigest,
    binding_digest: evidence.bindingDigest,
    business_dates: evidence.businessDates,
  };
}

function proofFromCapturedCalendar(
  evidence: CapturedOfficialCalendar,
): OfficialCalendarProof {
  return {
    rawBodyDigest: evidence.digest,
    calendarQueryDigest: evidence.calendarQueryDigest,
    businessDatesDigest: evidence.businessDatesDigest,
    bindingDigest: evidence.bindingDigest,
    businessDates: evidence.businessDates,
  };
}

async function loadOfficialCalendarEvidence(
  bucket: R2Bucket,
  evidence: CapturedOfficialCalendar,
  initialRequest: JquantsAcquisitionRequestV2,
): Promise<OfficialCalendarProof> {
  const object = await bucket.get(evidence.key);
  if (object === null) throw new Error("immutable official calendar disappeared");
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (
    bytes.byteLength !== evidence.size ||
    await sha256Digest(bytes) !== evidence.digest
  ) {
    throw new Error("immutable official calendar changed after capture");
  }
  const derived = await deriveOfficialCalendarProof(
    bytes, initialRequest.segment_start, initialRequest.segment_end,
  );
  if (
    canonicalJson(derived) !==
      canonicalJson(proofFromCapturedCalendar(evidence))
  ) {
    throw new Error("immutable official calendar proof differs after readback");
  }
  return derived;
}

function canonicalIso(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value;
}

function validDeploymentVersion(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 128 &&
    /^[A-Za-z0-9._:-]+$/.test(value);
}

function deploymentVersion(env: ReceiptAuthorityEnv): string {
  const version = env.CF_VERSION_METADATA?.id;
  if (!validDeploymentVersion(version)) {
    throw new Error("receipt authority deployment metadata is unavailable");
  }
  return version;
}

async function governedCaptureContext(
  context: CaptureBindingContext,
): Promise<{ initial: JquantsAcquisitionRequestV2; prefix: string }> {
  if (
    !isSha256(context.operationId) || context.requestDigest !== context.operationId ||
    !/^[0-9a-f]{64}$/.test(context.captureAttemptId) ||
    !/^[0-9a-f]{64}$/.test(context.acquisitionNonce) ||
    !canonicalIso(context.collectionStartedAt) ||
    context.request.operation !== "issue_for_segment" ||
    context.request.environment !== "staging" &&
      context.request.environment !== "production" ||
    context.request.dataset_id.length < 1 || context.request.segment_id.length < 1
  ) throw new Error("capture authority context is invalid");
  if (await canonicalDigest(context.request) !== context.requestDigest) {
    throw new Error("capture request digest differs from authority context");
  }
  const initial = await buildGovernedInitialRequest({
    environment: context.request.environment,
    datasetId: context.request.dataset_id,
    segmentId: context.request.segment_id,
    acquisitionNonce: context.acquisitionNonce,
    now: new Date(context.collectionStartedAt),
  });
  const prefix =
    `raw/receipt-authority/${context.request.environment}/${context.request.dataset_id}/${context.request.segment_id}/${context.operationId.slice(7)}/attempt-${context.captureAttemptId}/`;
  return { initial, prefix };
}

async function captureValidatorDigest(
  initial: JquantsAcquisitionRequestV2,
  captureDeploymentVersion: string,
): Promise<string> {
  const limits = targetRegistryLimits();
  return canonicalDigest({
    schema_version: CAPTURE_VALIDATOR_SCHEMA,
    capture_state_schema: CAPTURE_STATE_SCHEMA,
    capture_deployment_version: captureDeploymentVersion,
    governed_request_schema: initial.schema_version,
    governed_response_metadata_schema:
      "jquants-acquisition-rpc-response-metadata/v2",
    governed_collection_schema: "jquants-acquisition-collection/v2",
    pagination_proof_revision:
      "receipt-independent-pagination-proof/v4-calendar-raw",
    raw_parser_revision: "receipt-strict-raw-page/v2",
    target_registry_digest: initial.target_registry_digest,
    source_capability_digest: initial.source_capability_digest,
    dataset_contract_digest: initial.dataset_contract_digest,
    coverage_policy_digest: initial.coverage_policy_digest,
    query_contract_digest: initial.query_contract_digest,
    limits: {
      maximum_page_bytes: limits.maximumPageBytes,
      maximum_segment_pages: limits.maximumSegmentPages,
      maximum_provider_pages_per_slice: limits.maximumProviderPagesPerSlice,
      continuation_ttl_seconds: limits.continuationTtlSeconds,
      maximum_redirects: limits.maximumRedirects,
      official_origin: limits.officialOrigin,
    },
  });
}

function decodeCanonicalObject(bytes: Uint8Array, label: string): Record<string, unknown> {
  let text: string;
  try {
    text = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: false,
    }).decode(bytes);
  } catch {
    throw new Error(`${label} is not canonical UTF-8`);
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`${label} is not JSON`);
  }
  if (!isPlainObject(value) || canonicalJson(value) !== text) {
    throw new Error(`${label} is not canonical`);
  }
  return value;
}

async function deriveCaptureArtifacts(input: {
  initial: JquantsAcquisitionRequestV2;
  pages: readonly CapturedPage[];
  officialCalendarEvidence: CapturedOfficialCalendar | null;
  prefix: string;
}): Promise<DerivedCaptureArtifacts> {
  const terminal = input.pages.at(-1);
  if (
    terminal === undefined || terminal.metadata.pagination_state !== "EXHAUSTED" ||
    terminal.metadata.provider_pagination_state !== "EXHAUSTED" ||
    terminal.metadata.continuation_token !== null ||
    !isSha256(terminal.metadata.chain_digest) ||
    !canonicalIso(terminal.metadata.acquisition_expires_at)
  ) throw new Error("capture did not prove authoritative exhaustion");
  const capturePages = input.pages.map((page) => ({
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
    initial_request: input.initial,
    official_calendar_evidence: capturedOfficialCalendarDescriptor(
      input.officialCalendarEvidence,
    ),
    pages: capturePages,
  };
  const collectionDigest = await canonicalDigest(captureBody);
  const manifestJson = canonicalJson({
    ...captureBody,
    collection_digest: collectionDigest,
  });
  const pageManifest = input.pages.map((page) => ({
    index: page.index,
    digest: page.digest,
    size: page.size,
  }));
  const rawManifest = {
    pages: pageManifest,
    official_calendar_evidence: capturedOfficialCalendarDescriptor(
      input.officialCalendarEvidence,
    ),
  };
  return {
    rawManifestKey: `${input.prefix}manifest.json`,
    rawManifestDigest: await canonicalDigest(rawManifest),
    rawDigest: input.pages.length === 1
      ? input.pages[0]!.digest
      : await canonicalDigest({ pages: pageManifest }),
    manifestFileDigest: await sha256Digest(manifestJson),
    rawManifestByteCount: new TextEncoder().encode(manifestJson).byteLength,
    collectionDigest,
    terminalChainDigest: terminal.metadata.chain_digest,
    acquisitionExpiresAt: terminal.metadata.acquisition_expires_at,
    paginationExhausted: true,
    discoveryExhausted: true,
    manifestJson,
  };
}

function requireStoredCapture(
  value: Record<string, unknown>,
  prefix: string,
  initial: JquantsAcquisitionRequestV2,
): Capture {
  if (!exactKeys(value, CAPTURE_KEYS) || !Array.isArray(value.pages) ||
    value.pages.length < 1 || value.pages.length > targetRegistryLimits().maximumSegmentPages ||
    !isPlainObject(value.initialRequest) ||
    canonicalJson(value.initialRequest) !== canonicalJson(initial) ||
    typeof value.rawManifestKey !== "string" ||
    value.rawManifestKey !== `${prefix}manifest.json` ||
    !isSha256(value.rawManifestDigest) || !isSha256(value.rawDigest) ||
    !isSha256(value.manifestFileDigest) || !isSha256(value.collectionDigest) ||
    !Number.isSafeInteger(value.rawManifestByteCount) ||
    Number(value.rawManifestByteCount) < 1 ||
    !isSha256(value.terminalChainDigest) ||
    !canonicalIso(value.acquisitionExpiresAt) ||
    value.paginationExhausted !== true || value.discoveryExhausted !== true
  ) throw new Error("durable capture fields are invalid");
  const pages: CapturedPage[] = value.pages.map((item, index) => {
    if (
      !isPlainObject(item) || !exactKeys(item, CAPTURE_PAGE_KEYS) ||
      item.index !== index || item.key !== `${prefix}page-${String(index).padStart(6, "0")}.json` ||
      !Number.isSafeInteger(item.size) || Number(item.size) < 1 ||
      Number(item.size) > targetRegistryLimits().maximumPageBytes ||
      !isSha256(item.digest) || !Number.isSafeInteger(item.rowCount) ||
      Number(item.rowCount) < 0 || !Number.isSafeInteger(item.responseStatus) ||
      Number(item.responseStatus) < 100 || Number(item.responseStatus) > 599 ||
      !isPlainObject(item.headers) ||
      !Object.values(item.headers).every((entry) => typeof entry === "string") ||
      !isPlainObject(item.metadata)
    ) throw new Error("durable capture page fields are invalid");
    return {
      index,
      key: item.key as string,
      size: Number(item.size),
      digest: item.digest,
      rowCount: Number(item.rowCount),
      responseStatus: Number(item.responseStatus),
      headers: item.headers as Record<string, string>,
      metadata: item.metadata as AcquisitionResponseMetadataV2,
    };
  });
  let officialCalendarEvidence: CapturedOfficialCalendar | null = null;
  if (value.officialCalendarEvidence !== null) {
    const evidence = value.officialCalendarEvidence;
    if (
      !isPlainObject(evidence) || !exactKeys(evidence, CAPTURE_CALENDAR_KEYS) ||
      evidence.key !== `${prefix}official-calendar.json` ||
      evidence.path !== "/v2/markets/calendar" ||
      !Number.isSafeInteger(evidence.size) || Number(evidence.size) < 1 ||
      Number(evidence.size) > 65_536 || !isSha256(evidence.digest) ||
      !isSha256(evidence.calendarQueryDigest) ||
      !isSha256(evidence.businessDatesDigest) ||
      !isSha256(evidence.bindingDigest) ||
      !Array.isArray(evidence.businessDates) || evidence.businessDates.length < 1 ||
      !evidence.businessDates.every((date) => typeof date === "string")
    ) throw new Error("durable official calendar capture fields are invalid");
    officialCalendarEvidence = {
      key: evidence.key,
      path: evidence.path,
      size: Number(evidence.size),
      digest: evidence.digest,
      calendarQueryDigest: evidence.calendarQueryDigest,
      businessDatesDigest: evidence.businessDatesDigest,
      bindingDigest: evidence.bindingDigest,
      businessDates: evidence.businessDates as string[],
    };
  }
  if ((initial.dataset_id === "equities_master") !== (officialCalendarEvidence !== null)) {
    throw new Error("official calendar capture does not match the governed dataset");
  }
  return {
    initialRequest: initial,
    pages,
    rawManifestKey: value.rawManifestKey,
    rawManifestDigest: value.rawManifestDigest,
    rawDigest: value.rawDigest,
    manifestFileDigest: value.manifestFileDigest,
    rawManifestByteCount: Number(value.rawManifestByteCount),
    collectionDigest: value.collectionDigest,
    terminalChainDigest: value.terminalChainDigest,
    acquisitionExpiresAt: value.acquisitionExpiresAt,
    paginationExhausted: true,
    discoveryExhausted: true,
    officialCalendarEvidence,
  };
}

async function reproveCapture(
  env: ReceiptAuthorityEnv,
  stored: Capture,
  initial: JquantsAcquisitionRequestV2,
  prefix: string,
): Promise<Capture> {
  const calendarProof = stored.officialCalendarEvidence === null
    ? null
    : await loadOfficialCalendarEvidence(
      env.RAW_BUCKET,
      stored.officialCalendarEvidence,
      initial,
    );
  const pages: CapturedPage[] = [];
  let current = initial;
  const now = new Date();
  for (let index = 0; index < stored.pages.length; index += 1) {
    const claimed = stored.pages[index]!;
    const bytes = await loadRawPage(env.RAW_BUCKET, claimed);
    const response = new Response(bytes, {
      status: claimed.responseStatus,
      headers: claimed.headers,
    });
    const verified = await validateAcquisitionPage({
      response,
      body: bytes,
      request: current,
      environment: initial.environment,
      index,
      prior: pages.at(-1) ?? null,
      officialCalendar: calendarProof,
      now,
    });
    if (
      canonicalJson(verified.headers) !== canonicalJson(claimed.headers) ||
      canonicalJson(verified.metadata) !== canonicalJson(claimed.metadata) ||
      verified.rows.length !== claimed.rowCount
    ) throw new Error("durable capture page differs from independent reproof");
    if (index === 0 && stored.officialCalendarEvidence !== null) {
      const raw = verified.officialCalendarRaw;
      if (
        raw === null || raw.size !== stored.officialCalendarEvidence.size ||
        raw.digest !== stored.officialCalendarEvidence.digest ||
        canonicalJson(raw.proof) !== canonicalJson(calendarProof)
      ) throw new Error("capture page official calendar differs from immutable evidence");
    } else if (verified.officialCalendarRaw !== null) {
      throw new Error("capture replayed official calendar raw evidence");
    }
    const page: CapturedPage = {
      index,
      key: `${prefix}page-${String(index).padStart(6, "0")}.json`,
      size: bytes.byteLength,
      digest: await sha256Digest(bytes),
      rowCount: verified.rows.length,
      responseStatus: response.status,
      headers: verified.headers,
      metadata: verified.metadata,
    };
    pages.push(page);
    if (verified.metadata.pagination_state === "CONTINUATION") {
      if (index === stored.pages.length - 1 || verified.metadata.continuation_token === null) {
        throw new Error("durable capture ended with a continuation");
      }
      current = {
        ...initial,
        continuation_token: verified.metadata.continuation_token,
      };
    } else if (index !== stored.pages.length - 1) {
      throw new Error("durable capture has pages after authoritative exhaustion");
    }
  }
  const artifacts = await deriveCaptureArtifacts({
    initial,
    pages,
    officialCalendarEvidence: stored.officialCalendarEvidence,
    prefix,
  });
  const restored: Capture = {
    initialRequest: initial,
    pages,
    rawManifestKey: artifacts.rawManifestKey,
    rawManifestDigest: artifacts.rawManifestDigest,
    rawDigest: artifacts.rawDigest,
    manifestFileDigest: artifacts.manifestFileDigest,
    rawManifestByteCount: artifacts.rawManifestByteCount,
    collectionDigest: artifacts.collectionDigest,
    terminalChainDigest: artifacts.terminalChainDigest,
    acquisitionExpiresAt: artifacts.acquisitionExpiresAt,
    paginationExhausted: true,
    discoveryExhausted: true,
    officialCalendarEvidence: stored.officialCalendarEvidence,
  };
  if (canonicalJson(restored) !== canonicalJson(stored)) {
    throw new Error("durable capture summary differs from independent reproof");
  }
  const manifest = await env.RAW_BUCKET.get(artifacts.rawManifestKey);
  if (manifest === null) throw new Error("immutable capture manifest disappeared");
  const manifestBytes = new Uint8Array(await manifest.arrayBuffer());
  if (await sha256Digest(manifestBytes) !== artifacts.manifestFileDigest) {
    throw new Error("immutable capture manifest digest differs");
  }
  if (manifestBytes.byteLength !== artifacts.rawManifestByteCount) {
    throw new Error("immutable capture manifest byte count differs");
  }
  decodeCanonicalObject(manifestBytes, "immutable capture manifest");
  const manifestText = new TextDecoder("utf-8", {
    fatal: true,
    ignoreBOM: false,
  }).decode(manifestBytes);
  if (manifestText !== artifacts.manifestJson) {
    throw new Error("immutable capture manifest differs from independent reproof");
  }
  return restored;
}

export async function persistCaptureState(
  env: ReceiptAuthorityEnv,
  context: CaptureBindingContext,
  capture: Capture,
): Promise<{ key: string; digest: string }> {
  const { initial, prefix } = await governedCaptureContext(context);
  if (canonicalJson(capture.initialRequest) !== canonicalJson(initial)) {
    throw new Error("capture initial request differs from authority context");
  }
  const captureDeploymentVersion = deploymentVersion(env);
  const state: CaptureStateV2 = {
    schema_version: CAPTURE_STATE_SCHEMA,
    validator: {
      schema_version: CAPTURE_VALIDATOR_SCHEMA,
      capture_deployment_version: captureDeploymentVersion,
      digest: await captureValidatorDigest(initial, captureDeploymentVersion),
    },
    authority_binding: {
      environment: context.request.environment,
      dataset_id: context.request.dataset_id,
      segment_id: context.request.segment_id,
      operation_id: context.operationId,
      request_digest: context.requestDigest,
      capture_attempt_id: context.captureAttemptId,
      acquisition_nonce: context.acquisitionNonce,
      collection_started_at: context.collectionStartedAt,
    },
    capture,
  };
  const body = canonicalJson(state);
  const digest = await sha256Digest(body);
  const key = `${prefix}capture-state.json`;
  await putCreateOnly(env.AUTHORITY_EVIDENCE_BUCKET, key, body, {
    authority: "receipt",
    operation_id: context.operationId,
    capture_attempt_id: context.captureAttemptId,
    schema: CAPTURE_STATE_SCHEMA,
  });
  return { key, digest };
}

export async function loadCaptureState(
  env: ReceiptAuthorityEnv,
  context: CaptureRecoveryContext,
): Promise<Capture> {
  deploymentVersion(env);
  const { initial, prefix } = await governedCaptureContext(context);
  if (context.key !== `${prefix}capture-state.json` || !isSha256(context.expectedDigest)) {
    throw new Error("durable capture state authority binding differs");
  }
  const object = await env.AUTHORITY_EVIDENCE_BUCKET.get(context.key);
  if (object === null) throw new Error("durable capture state disappeared");
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (await sha256Digest(bytes) !== context.expectedDigest) {
    throw new Error("durable capture state digest differs");
  }
  const value = decodeCanonicalObject(bytes, "durable capture state");
  if (!exactKeys(value, CAPTURE_STATE_KEYS) ||
    value.schema_version !== CAPTURE_STATE_SCHEMA ||
    !isPlainObject(value.validator) ||
    !exactKeys(value.validator, CAPTURE_VALIDATOR_KEYS) ||
    value.validator.schema_version !== CAPTURE_VALIDATOR_SCHEMA ||
    !validDeploymentVersion(value.validator.capture_deployment_version) ||
    !isSha256(value.validator.digest) ||
    !isPlainObject(value.authority_binding) ||
    !exactKeys(value.authority_binding, CAPTURE_AUTHORITY_BINDING_KEYS) ||
    !isPlainObject(value.capture)
  ) throw new Error("durable capture state envelope is invalid");
  const binding = value.authority_binding;
  if (
    binding.environment !== context.request.environment ||
    binding.dataset_id !== context.request.dataset_id ||
    binding.segment_id !== context.request.segment_id ||
    binding.operation_id !== context.operationId ||
    binding.request_digest !== context.requestDigest ||
    binding.capture_attempt_id !== context.captureAttemptId ||
    binding.acquisition_nonce !== context.acquisitionNonce ||
    binding.collection_started_at !== context.collectionStartedAt
  ) throw new Error("durable capture authority binding differs");
  if (
    value.validator.digest !== await captureValidatorDigest(
      initial,
      value.validator.capture_deployment_version,
    )
  ) throw new Error("durable capture validator is not current");
  const stored = requireStoredCapture(value.capture, prefix, initial);
  return reproveCapture(env, stored, initial, prefix);
}

export async function putCreateOnly(
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
  if (
    existingBytes.byteLength !== payload.byteLength ||
    await sha256Digest(existingBytes) !== digest
  ) {
    throw new Error("immutable R2 object replay differs from existing bytes");
  }
}

export async function captureCollection(
  env: ReceiptAuthorityEnv,
  request: ReceiptIssueRequestV1,
  operationId: string,
  captureAttemptId: string,
  acquisitionNonce: string,
  collectionStartedAt: string,
): Promise<Capture> {
  const started = new Date(collectionStartedAt);
  if (!Number.isFinite(started.getTime()) || started.toISOString() !== collectionStartedAt) {
    throw new Error("receipt collection start time is invalid");
  }
  const initialRequest = await buildGovernedInitialRequest({
    environment: request.environment,
    datasetId: request.dataset_id,
    segmentId: request.segment_id,
    acquisitionNonce,
    now: started,
  });
  if (await canonicalDigest(request) !== operationId) {
    throw new Error("capture operation differs from governed request");
  }
  const prefix =
    `raw/receipt-authority/${request.environment}/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/attempt-${captureAttemptId}/`;
  const limits = targetRegistryLimits();
  const pages: CapturedPage[] = [];
  let officialCalendarEvidence: CapturedOfficialCalendar | null = null;
  let officialCalendarProof: OfficialCalendarProof | null = null;
  let current = initialRequest;
  for (let index = 0; index < limits.maximumSegmentPages; index += 1) {
    const response = await env.JQUANTS_ACQUISITION.fetch_governed_page(current);
    const body = new Uint8Array(await response.arrayBuffer());
    if (body.byteLength === 0 || body.byteLength > limits.maximumPageBytes) {
      throw new Error("acquisition page body is empty or exceeds the governed bound");
    }
    const verified = await validateAcquisitionPage({
      response,
      body,
      request: current,
      environment: request.environment,
      index,
      prior: pages.at(-1) ?? null,
      officialCalendar: officialCalendarProof,
      now: new Date(),
    });
    if (verified.officialCalendarRaw !== null) {
      if (officialCalendarEvidence !== null || index !== 0) {
        throw new Error("official calendar raw evidence was captured more than once");
      }
      const rawCalendar = verified.officialCalendarRaw;
      const calendarKey = `${prefix}official-calendar.json`;
      await putCreateOnly(
        env.RAW_BUCKET,
        calendarKey,
        rawCalendar.bytes,
        {
          authority: "receipt",
          operation_id: operationId,
          capture_attempt_id: captureAttemptId,
          dataset: request.dataset_id,
          segment_id: request.segment_id,
          schema: "jquants-official-calendar-raw/v1",
          digest: rawCalendar.digest,
        },
      );
      officialCalendarEvidence = {
        key: calendarKey,
        path: rawCalendar.path,
        size: rawCalendar.size,
        digest: rawCalendar.digest,
        calendarQueryDigest: rawCalendar.proof.calendarQueryDigest,
        businessDatesDigest: rawCalendar.proof.businessDatesDigest,
        bindingDigest: rawCalendar.proof.bindingDigest,
        businessDates: rawCalendar.proof.businessDates,
      };
      officialCalendarProof = await loadOfficialCalendarEvidence(
        env.RAW_BUCKET,
        officialCalendarEvidence,
        initialRequest,
      );
    } else if (
      verified.officialCalendar !== null &&
      officialCalendarProof !== null &&
      canonicalJson(verified.officialCalendar) !== canonicalJson(officialCalendarProof)
    ) {
      throw new Error("acquisition page calendar differs from immutable capture");
    }
    const digest = await sha256Digest(body);
    const key = `${prefix}page-${String(index).padStart(6, "0")}.json`;
    await putCreateOnly(env.RAW_BUCKET, key, body, {
      authority: "receipt",
      operation_id: operationId,
      capture_attempt_id: captureAttemptId,
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
    current = {
      ...initialRequest,
      continuation_token: verified.metadata.continuation_token,
    };
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
  if (
    (request.dataset_id === "equities_master") !==
      (officialCalendarEvidence !== null)
  ) {
    throw new Error("official calendar capture does not match the governed dataset");
  }

  const artifacts = await deriveCaptureArtifacts({
    initial: initialRequest,
    pages,
    officialCalendarEvidence,
    prefix,
  });
  await putCreateOnly(
    env.RAW_BUCKET,
    artifacts.rawManifestKey,
    artifacts.manifestJson,
    {
    authority: "receipt",
    operation_id: operationId,
    capture_attempt_id: captureAttemptId,
    dataset: request.dataset_id,
    segment_id: request.segment_id,
    },
  );
  return {
    initialRequest,
    pages,
    rawManifestKey: artifacts.rawManifestKey,
    rawManifestDigest: artifacts.rawManifestDigest,
    rawDigest: artifacts.rawDigest,
    manifestFileDigest: artifacts.manifestFileDigest,
    rawManifestByteCount: artifacts.rawManifestByteCount,
    collectionDigest: artifacts.collectionDigest,
    terminalChainDigest: artifacts.terminalChainDigest,
    acquisitionExpiresAt: artifacts.acquisitionExpiresAt,
    paginationExhausted: true,
    discoveryExhausted: true,
    officialCalendarEvidence,
  };
}

export async function loadRawPage(
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
