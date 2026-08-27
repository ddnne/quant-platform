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
import type {
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
  initialRequest: JquantsAcquisitionRequestV2;
  pages: CapturedPage[];
  rawManifestKey: string;
  rawManifestDigest: string;
  rawDigest: string;
  manifestFileDigest: string;
  collectionDigest: string;
  terminalChainDigest: string;
  acquisitionExpiresAt: string;
  officialCalendarEvidence: CapturedOfficialCalendar | null;
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

function captureStateKey(capture: Capture): string {
  if (!capture.rawManifestKey.endsWith("/manifest.json")) {
    throw new Error("capture manifest key is invalid");
  }
  return `${capture.rawManifestKey.slice(0, -"manifest.json".length)}capture-state.json`;
}

export async function persistCaptureState(
  bucket: R2Bucket,
  operationId: string,
  captureAttemptId: string,
  capture: Capture,
): Promise<{ key: string; digest: string }> {
  if (
    !capture.rawManifestKey.includes(
      `/${operationId.slice(7)}/attempt-${captureAttemptId}/`,
    )
  ) throw new Error("capture state identity is invalid");
  const body = canonicalJson(capture);
  const digest = await sha256Digest(body);
  const key = captureStateKey(capture);
  await putCreateOnly(bucket, key, body, {
    authority: "receipt",
    operation_id: operationId,
    capture_attempt_id: captureAttemptId,
    schema: "receipt-authority-capture-state/v1",
  });
  return { key, digest };
}

export async function loadCaptureState(
  bucket: R2Bucket,
  key: string,
  expectedDigest: string,
): Promise<Capture> {
  const object = await bucket.get(key);
  if (object === null) throw new Error("durable capture state disappeared");
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (await sha256Digest(bytes) !== expectedDigest) {
    throw new Error("durable capture state digest differs");
  }
  const text = new TextDecoder("utf-8", {
    fatal: true,
    ignoreBOM: false,
  }).decode(bytes);
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("durable capture state is not JSON");
  }
  if (
    typeof value !== "object" || value === null || Array.isArray(value) ||
    canonicalJson(value) !== text
  ) throw new Error("durable capture state is not canonical");
  const capture = value as Partial<Capture>;
  if (
    typeof capture.rawManifestKey !== "string" ||
    typeof capture.rawManifestDigest !== "string" ||
    typeof capture.rawDigest !== "string" ||
    typeof capture.manifestFileDigest !== "string" ||
    typeof capture.collectionDigest !== "string" ||
    typeof capture.terminalChainDigest !== "string" ||
    typeof capture.acquisitionExpiresAt !== "string" ||
    !Array.isArray(capture.pages) || capture.pages.length === 0 ||
    typeof capture.initialRequest !== "object" || capture.initialRequest === null ||
    !(capture.officialCalendarEvidence === null ||
      (typeof capture.officialCalendarEvidence === "object" &&
        capture.officialCalendarEvidence !== null))
  ) throw new Error("durable capture state fields are invalid");
  const restored = capture as Capture;
  const initial = restored.initialRequest;
  if (initial.dataset_id === "equities_master") {
    const evidence = restored.officialCalendarEvidence;
    const expectedCalendarKey = restored.rawManifestKey.endsWith("/manifest.json")
      ? `${restored.rawManifestKey.slice(0, -"manifest.json".length)}official-calendar.json`
      : "";
    if (
      evidence === null || evidence.path !== "/v2/markets/calendar" ||
      typeof evidence.key !== "string" ||
      evidence.key !== expectedCalendarKey ||
      !Number.isSafeInteger(evidence.size) || evidence.size < 1 ||
      typeof evidence.digest !== "string" ||
      typeof evidence.calendarQueryDigest !== "string" ||
      typeof evidence.businessDatesDigest !== "string" ||
      typeof evidence.bindingDigest !== "string" ||
      !Array.isArray(evidence.businessDates)
    ) throw new Error("durable official calendar capture fields are invalid");
    await loadOfficialCalendarEvidence(bucket, evidence, initial);
  } else if (restored.officialCalendarEvidence !== null) {
    throw new Error("non-master durable capture carried official calendar evidence");
  }
  return restored;
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
      const calendarKey =
        `raw/receipt-authority/${request.environment}/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/attempt-${captureAttemptId}/official-calendar.json`;
      await putCreateOnly(
        env.AUTHORITY_EVIDENCE_BUCKET,
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
        env.AUTHORITY_EVIDENCE_BUCKET,
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
    const key = `raw/receipt-authority/${request.environment}/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/attempt-${captureAttemptId}/page-${String(index).padStart(6, "0")}.json`;
    await putCreateOnly(env.AUTHORITY_EVIDENCE_BUCKET, key, body, {
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
    official_calendar_evidence: capturedOfficialCalendarDescriptor(
      officialCalendarEvidence,
    ),
    pages: capturePages,
  };
  const collectionDigest = await canonicalDigest(captureBody);
  const captureDocument = { ...captureBody, collection_digest: collectionDigest };
  const manifestJson = canonicalJson(captureDocument);
  const rawManifestKey = `raw/receipt-authority/${request.environment}/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/attempt-${captureAttemptId}/manifest.json`;
  await putCreateOnly(env.AUTHORITY_EVIDENCE_BUCKET, rawManifestKey, manifestJson, {
    authority: "receipt",
    operation_id: operationId,
    capture_attempt_id: captureAttemptId,
    dataset: request.dataset_id,
    segment_id: request.segment_id,
  });
  const pageManifest = pages.map((page) => ({
    index: page.index,
    digest: page.digest,
    size: page.size,
  }));
  const rawManifest = {
    pages: pageManifest,
    official_calendar_evidence: capturedOfficialCalendarDescriptor(
      officialCalendarEvidence,
    ),
  };
  return {
    initialRequest,
    pages,
    rawManifestKey,
    rawManifestDigest: await canonicalDigest(rawManifest),
    rawDigest: pages.length === 1
      ? pages[0]!.digest
      : await canonicalDigest({ pages: pageManifest }),
    manifestFileDigest: await sha256Digest(manifestJson),
    collectionDigest,
    terminalChainDigest: terminal.metadata.chain_digest,
    acquisitionExpiresAt: terminal.metadata.acquisition_expires_at,
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
