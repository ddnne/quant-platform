import {
  canonicalDigest,
  canonicalJson,
  exactKeys,
  isPlainObject,
  isSha256,
  sha256Digest,
} from "./canonical";
import {
  putCreateOnly,
  type Capture,
  type CaptureBindingContext,
  type CaptureRecoveryContext,
  type CapturedPage,
} from "./raw_capture";
import { queueContractDigest } from "../../ingestion-jsda/src/queue_contract";
import jsdaDocument from "../../../../packages/data_plane/data_contracts/jsda_governed.json";
import {
  JSDA_PARSE_ZERO,
  parseJsdaOtcFile,
} from "./jsda_otc_parse";
import type {
  JsdaPersistedRequestV1,
  JsdaReceiptIssueRequestV1,
  ReceiptAuthorityEnv,
  ReceiptIssueRequestV1,
} from "./types";

const JSDA_CAPTURE_SCHEMA = "receipt-authority-jsda-capture-state/v1" as const;
const JSDA_CAPTURE_VALIDATOR_SCHEMA =
  "receipt-authority-jsda-capture-validator/v1" as const;
const JSDA_IDENTITY_SCHEMA = "jsda-persisted-raw-identity/v1" as const;
const JSDA_PAGE_METADATA_SCHEMA = "jsda-persisted-raw-page/v1" as const;

const STATE_KEYS = ["schema_version", "validator", "authority_binding", "capture"] as const;
const VALIDATOR_KEYS = ["schema_version", "capture_deployment_version", "digest"] as const;
const BINDING_KEYS = [
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
const PAGE_KEYS = [
  "index",
  "key",
  "size",
  "digest",
  "rowCount",
  "responseStatus",
  "headers",
  "metadata",
] as const;

export function isJsdaPersistedRequest(
  value: Capture["initialRequest"],
): value is JsdaPersistedRequestV1 {
  return value.schema_version === JSDA_IDENTITY_SCHEMA;
}

function requireJsdaRequest(
  request: ReceiptIssueRequestV1,
): JsdaReceiptIssueRequestV1 {
  if (request.source !== "jsda") {
    throw new Error("JSDA capture requires source=jsda");
  }
  return request;
}

function canonicalIso(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value;
}

function deploymentVersion(env: ReceiptAuthorityEnv): string {
  const version = env.CF_VERSION_METADATA?.id;
  if (
    typeof version !== "string" ||
    version.length < 1 ||
    version.length > 128 ||
    !/^[A-Za-z0-9._:-]+$/.test(version)
  ) {
    throw new Error("receipt authority deployment metadata is unavailable");
  }
  return version;
}

function decodeCanonicalObject(
  bytes: Uint8Array,
  label: string,
): Record<string, unknown> {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes);
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

function governedFormatsFor(datasetId: string): readonly string[] {
  const row = (jsdaDocument.datasets as Array<{
    dataset_id: string;
    canonical_formats: string[];
  }>).find((entry) => entry.dataset_id === datasetId);
  return row?.canonical_formats ?? [];
}

export function parseJsdaStructuredRows(
  bytes: Uint8Array,
  jobType: JsdaPersistedRequestV1["job_type"],
  frontierJson: string | null,
  context: {
    datasetId: string;
    targetUrl: string;
    publicationLabelDate?: string | null;
    quoteEffectiveDate?: string | null;
  },
): Record<string, unknown>[] {
  if (jobType !== "fetch_file") {
    if (frontierJson === null) {
      throw new Error("JSDA discovery frontier is not exhausted");
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(frontierJson);
    } catch {
      throw new Error("JSDA discovery frontier is not exhausted");
    }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      throw new Error(JSDA_PARSE_ZERO);
    }
    return parsed.map((entry) => {
      if (!isPlainObject(entry)) {
        throw new Error("JSDA discovery frontier is not exhausted");
      }
      const job_type = entry.job_type;
      const segment_id = entry.segment_id;
      const target_url = entry.target_url;
      if (
        typeof job_type !== "string" || job_type.length === 0 ||
        typeof segment_id !== "string" || segment_id.length === 0 ||
        typeof target_url !== "string" || target_url.length === 0
      ) {
        throw new Error("JSDA discovery frontier identity is incomplete");
      }
      return {
        source: "jsda",
        job_type,
        segment_id,
        target_url,
      };
    });
  }
  const records = parseJsdaOtcFile(bytes, {
    datasetId: context.datasetId,
    targetUrl: context.targetUrl,
    governedFormats: governedFormatsFor(context.datasetId),
    publicationLabelDate: context.publicationLabelDate,
    quoteEffectiveDate: context.quoteEffectiveDate,
  });
  if (records.length === 0) {
    throw new Error(JSDA_PARSE_ZERO);
  }
  return records;
}

type TrustedJsdaJob = {
  work_key: string;
  run_key: string;
  dataset: string;
  job_type: JsdaPersistedRequestV1["job_type"];
  target_url: string;
  segment_id: string;
  contract_digest: string;
  state: string;
  cursor: number;
  frontier_json: string | null;
  content_digest: string | null;
  raw_key: string | null;
};

async function loadTrustedJsdaJob(
  env: ReceiptAuthorityEnv,
  request: JsdaReceiptIssueRequestV1,
): Promise<TrustedJsdaJob> {
  const job = await env.DB.prepare(
    `SELECT work_key, run_key, dataset, job_type, target_url, segment_id,
            contract_digest, state, cursor, frontier_json, content_digest, raw_key
       FROM jsda_acquisition_jobs_v3 WHERE work_key=?`,
  )
    .bind(request.work_key)
    .first<TrustedJsdaJob>();
  if (
    job === null ||
    job.work_key !== request.work_key ||
    job.dataset !== request.dataset_id ||
    job.segment_id !== request.segment_id ||
    job.contract_digest !== request.expected_contract_digest ||
    job.raw_key !== request.raw_object_key ||
    job.state !== "completed" ||
    job.content_digest === null ||
    job.raw_key === null
  ) {
    throw new Error("JSDA D1 terminal identity is not trusted");
  }
  const expectedContract = await queueContractDigest();
  if (job.contract_digest !== expectedContract) {
    throw new Error("JSDA expected contract digest does not match the governed contract");
  }
  if (job.job_type !== "fetch_file") {
    const closure = await env.DB.prepare(
      `SELECT frontier_exhausted FROM jsda_job_closures WHERE work_key=?`,
    )
      .bind(job.work_key)
      .first<{ frontier_exhausted: number }>();
    let frontier: unknown;
    try {
      frontier = job.frontier_json === null ? null : JSON.parse(job.frontier_json);
    } catch {
      frontier = null;
    }
    if (
      closure === null ||
      closure.frontier_exhausted !== 1 ||
      !Array.isArray(frontier) ||
      job.cursor !== frontier.length
    ) {
      throw new Error("JSDA discovery frontier is not exhausted");
    }
  }
  return job;
}

async function readExactRawObject(
  env: ReceiptAuthorityEnv,
  key: string,
  expectedHexOrPrefixed: string,
): Promise<{ bytes: Uint8Array; digest: string; size: number }> {
  const object = await env.RAW_BUCKET.get(key);
  if (object === null) {
    throw new Error("JSDA raw object is missing");
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (bytes.byteLength < 1) {
    throw new Error("JSDA raw object is missing");
  }
  const digest = await sha256Digest(bytes);
  const hex = digest.slice("sha256:".length);
  if (
    expectedHexOrPrefixed !== hex &&
    expectedHexOrPrefixed !== digest
  ) {
    throw new Error("JSDA raw object digest differs from independent measurement");
  }
  return { bytes, digest, size: bytes.byteLength };
}

async function deriveJsdaArtifacts(input: {
  initial: JsdaPersistedRequestV1;
  pages: CapturedPage[];
  prefix: string;
}): Promise<{
  rawManifestKey: string;
  rawManifestDigest: string;
  rawDigest: string;
  manifestFileDigest: string;
  rawManifestByteCount: number;
  collectionDigest: string;
  terminalChainDigest: string;
  acquisitionExpiresAt: string;
  manifestJson: string;
}> {
  const terminal = input.pages[0];
  if (terminal === undefined) {
    throw new Error("JSDA capture did not prove authoritative exhaustion");
  }
  const captureBody = {
    schema_version: "jsda-persisted-collection/v1",
    capture_mode: "PERSISTED_JSDA_RAW_OBJECT",
    initial_request: input.initial,
    official_calendar_evidence: null,
    pages: input.pages.map((page) => ({
      raw_path: page.key,
      raw_size: page.size,
      raw_digest: page.digest,
      response_status: page.responseStatus,
      headers: page.headers,
      metadata: page.metadata,
    })),
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
  const rawManifest = { pages: pageManifest, official_calendar_evidence: null };
  const metadata = terminal.metadata as {
    chain_digest: string;
    acquisition_expires_at: string;
  };
  return {
    rawManifestKey: `${input.prefix}manifest.json`,
    rawManifestDigest: await canonicalDigest(rawManifest),
    rawDigest: terminal.digest,
    manifestFileDigest: await sha256Digest(manifestJson),
    rawManifestByteCount: new TextEncoder().encode(manifestJson).byteLength,
    collectionDigest,
    terminalChainDigest: metadata.chain_digest,
    acquisitionExpiresAt: metadata.acquisition_expires_at,
    manifestJson,
  };
}

export async function captureJsdaPersistedCollection(
  env: ReceiptAuthorityEnv,
  request: ReceiptIssueRequestV1,
  operationId: string,
  captureAttemptId: string,
  acquisitionNonce: string,
  collectionStartedAt: string,
): Promise<Capture> {
  const jsda = requireJsdaRequest(request);
  if (await canonicalDigest(jsda) !== operationId) {
    throw new Error("capture operation differs from governed request");
  }
  const started = new Date(collectionStartedAt);
  if (!Number.isFinite(started.getTime()) || started.toISOString() !== collectionStartedAt) {
    throw new Error("receipt collection start time is invalid");
  }
  const job = await loadTrustedJsdaJob(env, jsda);
  const raw = await readExactRawObject(env, jsda.raw_object_key, job.content_digest!);
  const rows = parseJsdaStructuredRows(raw.bytes, job.job_type, job.frontier_json, {
    datasetId: job.dataset,
    targetUrl: job.target_url,
    publicationLabelDate: jsda.expected_key_start,
    quoteEffectiveDate: null,
  });
  const expires = new Date(started.getTime() + 15 * 60 * 1000).toISOString();
  const chainDigest = await canonicalDigest({
    schema_version: JSDA_PAGE_METADATA_SCHEMA,
    work_key: job.work_key,
    raw_object_key: jsda.raw_object_key,
    digest: raw.digest,
    size: raw.size,
  });
  const metadata = {
    schema_version: JSDA_PAGE_METADATA_SCHEMA,
    pagination_state: "EXHAUSTED" as const,
    provider_pagination_state: "EXHAUSTED" as const,
    continuation_token: null,
    chain_digest: chainDigest,
    acquisition_expires_at: expires,
    work_key: job.work_key,
    contract_digest: job.contract_digest,
    job_type: job.job_type,
  };
  const page: CapturedPage = {
    index: 0,
    key: jsda.raw_object_key,
    size: raw.size,
    digest: raw.digest,
    rowCount: rows.length,
    responseStatus: 200,
    headers: { "content-type": "application/octet-stream" },
    metadata: metadata as never,
  };
  const initial: JsdaPersistedRequestV1 = {
    schema_version: JSDA_IDENTITY_SCHEMA,
    environment: jsda.environment,
    work_key: job.work_key,
    run_key: job.run_key,
    job_type: job.job_type,
    dataset_id: job.dataset,
    segment_id: job.segment_id,
    segment_start: jsda.expected_key_start,
    segment_end: jsda.expected_key_end,
    target_url: job.target_url,
    contract_digest: job.contract_digest,
    raw_object_key: jsda.raw_object_key,
    frontier_json: job.frontier_json,
  };
  const prefix =
    `raw/receipt-authority/${jsda.environment}/${jsda.dataset_id}/${jsda.segment_id}/${operationId.slice(7)}/attempt-${captureAttemptId}/`;
  const artifacts = await deriveJsdaArtifacts({ initial, pages: [page], prefix });
  await putCreateOnly(env.RAW_BUCKET, artifacts.rawManifestKey, artifacts.manifestJson, {
    authority: "receipt",
    operation_id: operationId,
    capture_attempt_id: captureAttemptId,
    dataset: jsda.dataset_id,
    segment_id: jsda.segment_id,
    schema: "jsda-persisted-collection/v1",
  });
  return {
    initialRequest: initial,
    pages: [page],
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
    officialCalendarEvidence: null,
  };
}

async function jsdaValidatorDigest(
  initial: JsdaPersistedRequestV1,
  captureDeploymentVersion: string,
): Promise<string> {
  return canonicalDigest({
    schema_version: JSDA_CAPTURE_VALIDATOR_SCHEMA,
    capture_state_schema: JSDA_CAPTURE_SCHEMA,
    capture_deployment_version: captureDeploymentVersion,
    governed_request_schema: JSDA_IDENTITY_SCHEMA,
    capture_mode: "PERSISTED_JSDA_RAW_OBJECT",
    dataset_id: initial.dataset_id,
    work_key: initial.work_key,
    raw_object_key: initial.raw_object_key,
    contract_digest: initial.contract_digest,
  });
}

function jsdaPrefix(context: CaptureBindingContext): string {
  return `raw/receipt-authority/${context.request.environment}/${context.request.dataset_id}/${context.request.segment_id}/${context.operationId.slice(7)}/attempt-${context.captureAttemptId}/`;
}

export async function persistJsdaCaptureState(
  env: ReceiptAuthorityEnv,
  context: CaptureBindingContext,
  capture: Capture,
): Promise<{ key: string; digest: string }> {
  if (!isJsdaPersistedRequest(capture.initialRequest)) {
    throw new Error("JSDA capture initial request differs from authority context");
  }
  const captureDeploymentVersion = deploymentVersion(env);
  const state = {
    schema_version: JSDA_CAPTURE_SCHEMA,
    validator: {
      schema_version: JSDA_CAPTURE_VALIDATOR_SCHEMA,
      capture_deployment_version: captureDeploymentVersion,
      digest: await jsdaValidatorDigest(capture.initialRequest, captureDeploymentVersion),
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
  const key = `${jsdaPrefix(context)}capture-state.json`;
  await putCreateOnly(env.AUTHORITY_EVIDENCE_BUCKET, key, body, {
    authority: "receipt",
    operation_id: context.operationId,
    capture_attempt_id: context.captureAttemptId,
    schema: JSDA_CAPTURE_SCHEMA,
  });
  return { key, digest };
}

export async function loadJsdaCaptureState(
  env: ReceiptAuthorityEnv,
  context: CaptureRecoveryContext,
): Promise<Capture> {
  const version = deploymentVersion(env);
  const prefix = jsdaPrefix(context);
  if (context.key !== `${prefix}capture-state.json` || !isSha256(context.expectedDigest)) {
    throw new Error("durable capture state authority binding differs");
  }
  const object = await env.AUTHORITY_EVIDENCE_BUCKET.get(context.key);
  if (object === null) throw new Error("durable capture state disappeared");
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (await sha256Digest(bytes) !== context.expectedDigest) {
    throw new Error("durable capture state digest differs");
  }
  const value = decodeCanonicalObject(bytes, "durable JSDA capture state");
  if (
    !exactKeys(value, STATE_KEYS) ||
    value.schema_version !== JSDA_CAPTURE_SCHEMA ||
    !isPlainObject(value.validator) ||
    !exactKeys(value.validator, VALIDATOR_KEYS) ||
    value.validator.schema_version !== JSDA_CAPTURE_VALIDATOR_SCHEMA ||
    value.validator.capture_deployment_version !== version ||
    !isSha256(value.validator.digest) ||
    !isPlainObject(value.authority_binding) ||
    !exactKeys(value.authority_binding, BINDING_KEYS) ||
    !isPlainObject(value.capture)
  ) {
    throw new Error("durable capture state envelope is invalid");
  }
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
  ) {
    throw new Error("durable capture authority binding differs");
  }
  const stored = value.capture;
  if (
    !exactKeys(stored, CAPTURE_KEYS) ||
    !Array.isArray(stored.pages) ||
    stored.pages.length !== 1 ||
    stored.officialCalendarEvidence !== null ||
    stored.paginationExhausted !== true ||
    stored.discoveryExhausted !== true ||
    stored.rawManifestKey !== `${prefix}manifest.json` ||
    !isSha256(stored.rawManifestDigest) ||
    !isSha256(stored.rawDigest) ||
    !isSha256(stored.manifestFileDigest) ||
    !Number.isSafeInteger(stored.rawManifestByteCount) ||
    Number(stored.rawManifestByteCount) < 1 ||
    !isSha256(stored.collectionDigest) ||
    !isSha256(stored.terminalChainDigest) ||
    !canonicalIso(stored.acquisitionExpiresAt) ||
    !isPlainObject(stored.initialRequest)
  ) {
    throw new Error("durable capture fields are invalid");
  }
  const initial = stored.initialRequest as JsdaPersistedRequestV1;
  if (
    initial.schema_version !== JSDA_IDENTITY_SCHEMA ||
    context.request.source !== "jsda" ||
    initial.work_key !== context.request.work_key ||
    initial.raw_object_key !== context.request.raw_object_key ||
    initial.contract_digest !== context.request.expected_contract_digest ||
    initial.dataset_id !== context.request.dataset_id ||
    initial.segment_id !== context.request.segment_id
  ) {
    throw new Error("durable capture initial request differs from authority context");
  }
  if (value.validator.digest !== await jsdaValidatorDigest(initial, version)) {
    throw new Error("durable capture validator is not current");
  }
  const item = stored.pages[0];
  if (
    !isPlainObject(item) ||
    !exactKeys(item, PAGE_KEYS) ||
    item.index !== 0 ||
    item.key !== initial.raw_object_key ||
    !Number.isSafeInteger(item.size) ||
    Number(item.size) < 1 ||
    !isSha256(item.digest) ||
    !Number.isSafeInteger(item.rowCount) ||
    Number(item.rowCount) < 1
  ) {
    throw new Error("durable capture page fields are invalid");
  }
  const page: CapturedPage = {
    index: 0,
    key: String(item.key),
    size: Number(item.size),
    digest: item.digest,
    rowCount: Number(item.rowCount),
    responseStatus: Number(item.responseStatus),
    headers: item.headers as Record<string, string>,
    metadata: item.metadata as never,
  };
  const restored: Capture = {
    initialRequest: initial,
    pages: [page],
    rawManifestKey: stored.rawManifestKey,
    rawManifestDigest: stored.rawManifestDigest,
    rawDigest: stored.rawDigest,
    manifestFileDigest: stored.manifestFileDigest,
    rawManifestByteCount: Number(stored.rawManifestByteCount),
    collectionDigest: stored.collectionDigest,
    terminalChainDigest: stored.terminalChainDigest,
    acquisitionExpiresAt: stored.acquisitionExpiresAt,
    paginationExhausted: true,
    discoveryExhausted: true,
    officialCalendarEvidence: null,
  };
  const reproved = await reproveJsdaCapture(env, restored, context.request);
  if (canonicalJson(reproved) !== canonicalJson(restored)) {
    throw new Error("durable capture summary differs from independent reproof");
  }
  return restored;
}

async function reproveJsdaCapture(
  env: ReceiptAuthorityEnv,
  stored: Capture,
  request: ReceiptIssueRequestV1,
): Promise<Capture> {
  const jsda = requireJsdaRequest(request);
  if (!isJsdaPersistedRequest(stored.initialRequest)) {
    throw new Error("durable capture initial request differs from authority context");
  }
  const job = await loadTrustedJsdaJob(env, jsda);
  const raw = await readExactRawObject(
    env,
    stored.initialRequest.raw_object_key,
    job.content_digest!,
  );
  if (raw.digest !== stored.pages[0]?.digest || raw.size !== stored.pages[0]?.size) {
    throw new Error("JSDA raw object digest differs from independent measurement");
  }
  const rows = parseJsdaStructuredRows(raw.bytes, job.job_type, job.frontier_json, {
    datasetId: job.dataset,
    targetUrl: job.target_url,
    publicationLabelDate: jsda.expected_key_start,
    quoteEffectiveDate: null,
  });
  if (rows.length !== stored.pages[0]!.rowCount) {
    throw new Error("PARSE_ZERO: empty JSDA structured product cannot mint COMPLETE");
  }
  const manifest = await env.RAW_BUCKET.get(stored.rawManifestKey);
  if (manifest === null) throw new Error("immutable capture manifest disappeared");
  const manifestBytes = new Uint8Array(await manifest.arrayBuffer());
  if (await sha256Digest(manifestBytes) !== stored.manifestFileDigest) {
    throw new Error("immutable capture manifest digest differs");
  }
  if (manifestBytes.byteLength !== stored.rawManifestByteCount) {
    throw new Error("immutable capture manifest byte count differs");
  }
  return stored;
}
