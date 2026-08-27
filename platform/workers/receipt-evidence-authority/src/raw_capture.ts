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
  validateAcquisitionPage,
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
};

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
    const verified = await validateAcquisitionPage({
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
    await putCreateOnly(env.AUTHORITY_EVIDENCE_BUCKET, key, body, {
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
  await putCreateOnly(env.AUTHORITY_EVIDENCE_BUCKET, rawManifestKey, manifestJson, {
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
