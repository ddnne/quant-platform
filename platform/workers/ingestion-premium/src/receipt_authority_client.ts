import type {
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueResultV1,
  SegmentGrain,
} from "../../receipt-evidence-authority/src/types";
import { canonicalDigest } from "../../receipt-evidence-authority/src/canonical";
import { governedReceiptIdentity } from "./catalog";
import {
  jsdaSegmentGrain,
  segmentMatchesGrain,
} from "../../receipt-evidence-authority/src/receipt_request_identity";

export type ReceiptAuthorityClientEnv = {
  DB: D1Database;
  RECEIPT_EVIDENCE_AUTHORITY: Pick<
    ReceiptEvidenceAuthorityRpc,
    "issue_for_segment" | "recover_issue"
  >;
};

export type ReceiptAuthorityEnvironment = "staging" | "production";

export type JsdaReceiptLocator = {
  work_key: string;
  expected_contract_digest: string;
  raw_object_key: string;
};

function randomNonce(): string {
  return [...crypto.getRandomValues(new Uint8Array(32))]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function closedIdentity(
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  requestNonce: string,
  locator?: JsdaReceiptLocator,
): {
  schema_version: "receipt-evidence-issue-request/v1";
  operation: "issue_for_segment";
  environment: ReceiptAuthorityEnvironment;
  source: "jquants" | "jsda";
  contract_id: string;
  dataset_id: string;
  segment_grain: SegmentGrain;
  segment_id: string;
  expected_key_start: string;
  expected_key_end: string;
  request_nonce: string;
  work_key?: string;
  expected_contract_digest?: string;
  raw_object_key?: string;
} {
  const identity = governedReceiptIdentity(datasetId);
  if (identity === undefined) {
    throw new Error("dataset is outside the governed Receipt V3 inventory");
  }
  const grain = identity.source === "jsda"
    ? jsdaSegmentGrain(segmentId) ?? identity.segment_grain
    : identity.segment_grain;
  const expected = expectedKeyRange({ ...identity, segment_grain: grain }, segmentId);
  if (
    !segmentMatchesGrain(
      identity.source,
      grain,
      segmentId,
      expected.start,
      expected.end,
    )
  ) {
    throw new TypeError("receipt segment grain is invalid");
  }
  if (identity.source === "jsda") {
    if (
      locator === undefined ||
      typeof locator.work_key !== "string" ||
      typeof locator.expected_contract_digest !== "string" ||
      typeof locator.raw_object_key !== "string"
    ) {
      throw new TypeError("JSDA receipt request is missing job/raw identity");
    }
    return {
      schema_version: "receipt-evidence-issue-request/v1",
      operation: "issue_for_segment",
      environment,
      source: "jsda",
      contract_id: identity.contract_id,
      dataset_id: datasetId,
      segment_grain: grain,
      segment_id: segmentId,
      expected_key_start: expected.start,
      expected_key_end: expected.end,
      request_nonce: requestNonce,
      work_key: locator.work_key,
      expected_contract_digest: locator.expected_contract_digest,
      raw_object_key: locator.raw_object_key,
    };
  }
  if (locator !== undefined) {
    throw new TypeError("J-Quants receipt request cannot carry JSDA raw identity");
  }
  return {
    schema_version: "receipt-evidence-issue-request/v1",
    operation: "issue_for_segment",
    environment,
    source: identity.source,
    contract_id: identity.contract_id,
    dataset_id: datasetId,
    segment_grain: grain,
    segment_id: segmentId,
    expected_key_start: expected.start,
    expected_key_end: expected.end,
    request_nonce: requestNonce,
  };
}

function expectedKeyRange(
  identity: { segment_grain: SegmentGrain; coverage: { history_target_start: string } },
  segmentId: string,
): { start: string; end: string } {
  const grain = identity.segment_grain;
  if (grain === "calendar_month") {
    const match = /^(\d{4})-(\d{2})$/.exec(segmentId);
    if (match === null) throw new TypeError("receipt segment must be a calendar month");
    const year = Number(match[1]);
    const month = Number(match[2]);
    const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return {
      start: `${match[1]}-${match[2]}-01`,
      end: `${match[1]}-${match[2]}-${String(last).padStart(2, "0")}`,
    };
  }
  if (grain === "same_trading_day_am_snapshot" || grain === "collection_cutoff_snapshot") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(segmentId)) {
      throw new TypeError("receipt segment must be a trading-day snapshot");
    }
    return { start: segmentId, end: segmentId };
  }
  const day =
    /^(\d{4}-\d{2}-\d{2})$/.exec(segmentId)?.[1] ??
    /^archive-(\d{4}-\d{2}-\d{2})$/.exec(segmentId)?.[1] ??
    /^index_root_(\d{4}-\d{2}-\d{2})$/.exec(segmentId)?.[1];
  if (grain === "official_archive_index_day" && day) {
    return { start: day, end: day };
  }
  if (grain === "official_archive_year") {
    const year = /^archive_year_(\d{4})_[A-Za-z0-9._-]{1,64}$/.exec(segmentId);
    if (year === null) throw new TypeError("receipt segment must be an official archive year");
    return { start: `${year[1]}-01-01`, end: `${year[1]}-12-31` };
  }
  if (grain === "source_time_series_file") {
    const fileDay = /^file_(\d{4}-\d{2}-\d{2})(?:_[A-Za-z0-9._-]{1,140})?$/.exec(segmentId);
    if (fileDay !== null) return { start: fileDay[1], end: fileDay[1] };
    if (!/^file_[A-Za-z0-9._-]{1,160}$/.test(segmentId)) {
      throw new TypeError("receipt segment must be a source time-series file");
    }
    const start = identity.coverage.history_target_start;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) {
      throw new TypeError("source time-series file key range is not authority-derived");
    }
    return { start, end: start };
  }
  throw new TypeError("receipt segment grain is invalid");
}


type PreparedRequest = {
  operation_id: string;
  request_nonce: string;
  environment: ReceiptAuthorityEnvironment;
  source: "jquants" | "jsda";
  contract_id: string;
  dataset: string;
  segment_id: string;
  segment_grain: SegmentGrain;
  expected_key_start: string;
  expected_key_end: string;
  state: "PREPARED" | "FINALIZED";
  receipt_digest: string | null;
  work_key?: string;
  expected_contract_digest?: string;
  raw_object_key?: string;
};

async function prepareRequest(
  env: ReceiptAuthorityClientEnv,
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  requestNonce: string,
  locator?: JsdaReceiptLocator,
): Promise<PreparedRequest> {
  const identity = closedIdentity(
    environment,
    datasetId,
    segmentId,
    requestNonce,
    locator,
  );
  const operationId = await canonicalDigest(identity);
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_requests
     (operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
      created_at,updated_at,work_key,expected_contract_digest,raw_object_key)
     VALUES (?,?,?,?,?,?,?,'PREPARED',?,?,?,?,?)`,
  ).bind(
    operationId,
    requestNonce,
    environment,
    identity.source,
    identity.contract_id,
    datasetId,
    segmentId,
    now,
    now,
    identity.work_key ?? null,
    identity.expected_contract_digest ?? null,
    identity.raw_object_key ?? null,
  ).run();
  const row = await env.DB.prepare(
    `SELECT operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
            receipt_digest,work_key,expected_contract_digest,raw_object_key
       FROM receipt_authority_requests WHERE operation_id=?`,
  ).bind(operationId).first<PreparedRequest>();
  const storedLocator = {
    work_key: optionalLocatorField(row?.work_key),
    expected_contract_digest: optionalLocatorField(row?.expected_contract_digest),
    raw_object_key: optionalLocatorField(row?.raw_object_key),
  };
  if (
    row === null || row.operation_id !== operationId ||
    row.request_nonce !== requestNonce || row.environment !== environment ||
    row.dataset !== datasetId || row.segment_id !== segmentId ||
    row.source !== identity.source || row.contract_id !== identity.contract_id ||
    storedLocator.work_key !== identity.work_key ||
    storedLocator.expected_contract_digest !== identity.expected_contract_digest ||
    storedLocator.raw_object_key !== identity.raw_object_key
  ) throw new Error("Receipt request ledger replay was substituted");
  return {
    ...row,
    segment_grain: identity.segment_grain,
    expected_key_start: identity.expected_key_start,
    expected_key_end: identity.expected_key_end,
    work_key: identity.work_key,
    expected_contract_digest: identity.expected_contract_digest,
    raw_object_key: identity.raw_object_key,
  };
}

function optionalLocatorField(value: string | null | undefined): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

async function finalizeRequest(
  env: ReceiptAuthorityClientEnv,
  request: PreparedRequest,
  result: ReceiptIssueResultV1,
): Promise<void> {
  if (result.operation_id !== request.operation_id) {
    throw new Error("Receipt authority returned a substituted operation");
  }
  await env.DB.prepare(
    `UPDATE receipt_authority_requests
        SET state='FINALIZED',receipt_digest=?,updated_at=?
      WHERE operation_id=?
        AND (state='PREPARED' OR (state='FINALIZED' AND receipt_digest=?))`,
  ).bind(
    result.receipt_digest,
    new Date().toISOString(),
    request.operation_id,
    result.receipt_digest,
  ).run();
  const stored = await env.DB.prepare(
    `SELECT operation_id,request_nonce,environment,dataset,segment_id,state,
            receipt_digest
       FROM receipt_authority_requests WHERE operation_id=?`,
  ).bind(request.operation_id).first<PreparedRequest>();
  if (
    stored === null || stored.state !== "FINALIZED" ||
    stored.receipt_digest !== result.receipt_digest ||
    stored.request_nonce !== request.request_nonce
  ) throw new Error("Receipt request ledger finalization failed");
}

async function callPrepared(
  env: ReceiptAuthorityClientEnv,
  request: PreparedRequest,
  operation: "issue_for_segment" | "recover_issue",
): Promise<ReceiptIssueResultV1> {
  const base = {
    schema_version: "receipt-evidence-issue-request/v1" as const,
    environment: request.environment,
    source: request.source,
    contract_id: request.contract_id,
    dataset_id: request.dataset,
    segment_grain: request.segment_grain,
    segment_id: request.segment_id,
    expected_key_start: request.expected_key_start,
    expected_key_end: request.expected_key_end,
    request_nonce: request.request_nonce,
  };
  const locator = request.source === "jsda" &&
    request.work_key &&
    request.expected_contract_digest &&
    request.raw_object_key
    ? {
      work_key: request.work_key,
      expected_contract_digest: request.expected_contract_digest,
      raw_object_key: request.raw_object_key,
    }
    : {};
  const result = operation === "issue_for_segment"
    ? await env.RECEIPT_EVIDENCE_AUTHORITY.issue_for_segment({
      ...base,
      ...locator,
      operation: "issue_for_segment",
    } as never)
    : await env.RECEIPT_EVIDENCE_AUTHORITY.recover_issue({
      ...base,
      ...locator,
      operation: "recover_issue",
    } as never);
  await finalizeRequest(env, request, result);
  return result;
}

/**
 * The caller selects only a reviewed dataset/month. Counts, digests,
 * pagination state, raw bytes, normalization, and issuance stay authority-
 * measured behind the typed Service Binding.
 */
export async function issueGovernedReceipt(
  env: ReceiptAuthorityClientEnv,
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  locator?: JsdaReceiptLocator,
): Promise<{ requestNonce: string; result: ReceiptIssueResultV1 }> {
  const requestNonce = locator === undefined
    ? randomNonce()
    : (await canonicalDigest({
      work_key: locator.work_key,
      raw_object_key: locator.raw_object_key,
      expected_contract_digest: locator.expected_contract_digest,
      dataset_id: datasetId,
      segment_id: segmentId,
    })).slice("sha256:".length);
  return issueGovernedReceiptWithNonce(
    env,
    environment,
    datasetId,
    segmentId,
    requestNonce,
    locator,
  );
}

async function issueGovernedReceiptWithNonce(
  env: ReceiptAuthorityClientEnv,
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  requestNonce: string,
  locator?: JsdaReceiptLocator,
): Promise<{ requestNonce: string; result: ReceiptIssueResultV1 }> {
  if (!/^[0-9a-f]{64}$/.test(requestNonce)) {
    throw new TypeError("receipt issue nonce is invalid");
  }
  const prepared = await prepareRequest(
    env,
    environment,
    datasetId,
    segmentId,
    requestNonce,
    locator,
  );
  const result = await callPrepared(env, prepared, "issue_for_segment");
  return { requestNonce, result };
}

export async function recoverGovernedReceipt(
  env: ReceiptAuthorityClientEnv,
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  requestNonce: string,
  locator?: JsdaReceiptLocator,
): Promise<ReceiptIssueResultV1> {
  if (!/^[0-9a-f]{64}$/.test(requestNonce)) {
    throw new TypeError("receipt recovery nonce is invalid");
  }
  const prepared = await prepareRequest(
    env,
    environment,
    datasetId,
    segmentId,
    requestNonce,
    locator,
  );
  return callPrepared(env, prepared, "recover_issue");
}

/** Recover a lost RPC response using only the durable caller operation id. */
export async function recoverPreparedReceipt(
  env: ReceiptAuthorityClientEnv,
  operationId: string,
): Promise<ReceiptIssueResultV1> {
  if (!/^sha256:[0-9a-f]{64}$/.test(operationId)) {
    throw new TypeError("receipt operation id is invalid");
  }
  const prepared = await env.DB.prepare(
    `SELECT operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
            receipt_digest,work_key,expected_contract_digest,raw_object_key
       FROM receipt_authority_requests WHERE operation_id=?`,
  ).bind(operationId).first<PreparedRequest>();
  if (prepared === null) throw new Error("Receipt request is not durably prepared");
  const locator = prepared.source === "jsda"
    ? {
      work_key: prepared.work_key,
      expected_contract_digest: prepared.expected_contract_digest,
      raw_object_key: prepared.raw_object_key,
    }
    : undefined;
  if (prepared.source === "jsda") {
    if (
      typeof locator?.work_key !== "string" ||
      typeof locator.expected_contract_digest !== "string" ||
      typeof locator.raw_object_key !== "string"
    ) {
      throw new Error("JSDA PREPARED recovery is missing closed locator identity");
    }
  }
  const identity = closedIdentity(
    prepared.environment,
    prepared.dataset,
    prepared.segment_id,
    prepared.request_nonce,
    locator as JsdaReceiptLocator | undefined,
  );
  if (await canonicalDigest(identity) !== operationId) {
    throw new Error("JSDA PREPARED recovery locator does not reconstruct the operation");
  }
  const recovered = await callPrepared(env, {
    ...prepared,
    segment_grain: identity.segment_grain,
    expected_key_start: identity.expected_key_start,
    expected_key_end: identity.expected_key_end,
    work_key: identity.work_key,
    expected_contract_digest: identity.expected_contract_digest,
    raw_object_key: identity.raw_object_key,
  }, "recover_issue");
  if (prepared.source === "jsda") {
    await requireClosedJsdaCallerLedger(env, operationId, locator as JsdaReceiptLocator);
  }
  return recovered;
}

export async function requireClosedJsdaCallerLedger(
  env: ReceiptAuthorityClientEnv,
  operationId: string,
  locator: JsdaReceiptLocator,
): Promise<void> {
  const request = await env.DB.prepare(
    `SELECT operation_id,state,receipt_digest,work_key,expected_contract_digest,raw_object_key
       FROM receipt_authority_requests WHERE operation_id=?`,
  ).bind(operationId).first<{
    operation_id: string;
    state: string;
    receipt_digest: string | null;
    work_key: string | null;
    expected_contract_digest: string | null;
    raw_object_key: string | null;
  }>();
  if (
    request === null ||
    request.operation_id !== operationId ||
    request.state !== "FINALIZED" ||
    typeof request.receipt_digest !== "string" ||
    request.work_key !== locator.work_key ||
    request.expected_contract_digest !== locator.expected_contract_digest ||
    request.raw_object_key !== locator.raw_object_key
  ) {
    throw new Error("JSDA caller request is not FINALIZED for the current locator");
  }
  const operation = await env.DB.prepare(
    `SELECT operation_id,state,raw_manifest_digest,structured_digest
       FROM receipt_authority_operations WHERE operation_id=?`,
  ).bind(operationId).first<{
    operation_id: string;
    state: string;
    raw_manifest_digest: string | null;
    structured_digest: string | null;
  }>();
  if (
    operation === null ||
    operation.operation_id !== operationId ||
    operation.state !== "RECEIPT_COMMITTED" ||
    typeof operation.raw_manifest_digest !== "string" ||
    typeof operation.structured_digest !== "string"
  ) {
    throw new Error("JSDA receipt operation is not RECEIPT_COMMITTED");
  }
  const product = await env.DB.prepare(
    `SELECT operation_id,raw_manifest_digest,artifact_digest
       FROM receipt_product_materializations WHERE operation_id=?`,
  ).bind(operationId).first<{
    operation_id: string;
    raw_manifest_digest: string;
    artifact_digest: string;
  }>();
  if (
    product === null ||
    product.operation_id !== operationId ||
    product.raw_manifest_digest !== operation.raw_manifest_digest ||
    product.artifact_digest !== operation.structured_digest
  ) {
    throw new Error("JSDA product identity does not match the committed operation");
  }
}

export function closedJsdaReceiptEligibility(
  receipt: ReceiptIssueResultV1["receipt"] | Record<string, unknown> | undefined,
): string {
  const digests = receipt && typeof receipt === "object"
    ? (receipt as { digests?: { eligibility?: unknown } }).digests
    : undefined;
  return typeof digests?.eligibility === "string" ? digests.eligibility : "";
}

export type ReceiptRecoverySweep = {
  attempted: number;
  recovered: number;
  failed: number;
};

/**
 * Cron recovery reads only caller-owned PREPARED identities. It cannot supply
 * counts, digests, pagination state, or claims to the authority.
 */
export async function recoverPreparedReceipts(
  env: ReceiptAuthorityClientEnv,
  limit = 8,
): Promise<ReceiptRecoverySweep> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 32) {
    throw new TypeError("receipt recovery limit is invalid");
  }
  const page = await env.DB.prepare(
    `SELECT operation_id
       FROM receipt_authority_requests
      WHERE state='PREPARED'
      ORDER BY created_at,operation_id
      LIMIT ?`,
  ).bind(limit).all<{ operation_id: string }>();
  const rows = page.results ?? [];
  let recovered = 0;
  let failed = 0;
  for (const row of rows) {
    try {
      await recoverPreparedReceipt(env, row.operation_id);
      recovered += 1;
    } catch (error) {
      failed += 1;
      console.error(JSON.stringify({
        event: "receipt_authority_recovery",
        operation_id: row.operation_id,
        result: "FAILED",
        reason: error instanceof Error ? error.message : "unknown",
      }));
    }
  }
  return { attempted: rows.length, recovered, failed };
}
