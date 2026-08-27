import type {
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueResultV1,
} from "../../receipt-evidence-authority/src/types";
import { canonicalDigest } from "../../receipt-evidence-authority/src/canonical";
import { datasetById } from "./catalog";

export type ReceiptAuthorityClientEnv = {
  DB: D1Database;
  RECEIPT_EVIDENCE_AUTHORITY: Pick<
    ReceiptEvidenceAuthorityRpc,
    "issue_for_segment" | "recover_issue"
  >;
};

export type ReceiptAuthorityEnvironment = "staging" | "production";

function randomNonce(): string {
  return [...crypto.getRandomValues(new Uint8Array(32))]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function requireSegment(datasetId: string, segmentId: string): void {
  const spec = datasetById(datasetId);
  if (
    spec === undefined || spec.coverage.policy_version !== "collection-coverage/v3"
  ) throw new Error("dataset is outside the governed Receipt V3 inventory");
  if (!/^\d{4}-\d{2}$/.test(segmentId)) {
    throw new TypeError("receipt segment must be a calendar month");
  }
}

type PreparedRequest = {
  operation_id: string;
  request_nonce: string;
  environment: ReceiptAuthorityEnvironment;
  dataset: string;
  segment_id: string;
  state: "PREPARED" | "FINALIZED";
  receipt_digest: string | null;
};

async function prepareRequest(
  env: ReceiptAuthorityClientEnv,
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  requestNonce: string,
): Promise<PreparedRequest> {
  const identity = {
    schema_version: "receipt-evidence-issue-request/v1" as const,
    operation: "issue_for_segment" as const,
    environment,
    dataset_id: datasetId,
    segment_id: segmentId,
    request_nonce: requestNonce,
  };
  const operationId = await canonicalDigest(identity);
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_requests
     (operation_id,request_nonce,environment,dataset,segment_id,state,
      created_at,updated_at)
     VALUES (?,?,?,?,?,'PREPARED',?,?)`,
  ).bind(
    operationId,
    requestNonce,
    environment,
    datasetId,
    segmentId,
    now,
    now,
  ).run();
  const row = await env.DB.prepare(
    `SELECT operation_id,request_nonce,environment,dataset,segment_id,state,
            receipt_digest
       FROM receipt_authority_requests WHERE operation_id=?`,
  ).bind(operationId).first<PreparedRequest>();
  if (
    row === null || row.operation_id !== operationId ||
    row.request_nonce !== requestNonce || row.environment !== environment ||
    row.dataset !== datasetId || row.segment_id !== segmentId
  ) throw new Error("Receipt request ledger replay was substituted");
  return row;
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
    dataset_id: request.dataset,
    segment_id: request.segment_id,
    request_nonce: request.request_nonce,
  };
  const result = operation === "issue_for_segment"
    ? await env.RECEIPT_EVIDENCE_AUTHORITY.issue_for_segment({
      ...base,
      operation,
    })
    : await env.RECEIPT_EVIDENCE_AUTHORITY.recover_issue({
      ...base,
      operation,
    });
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
): Promise<{ requestNonce: string; result: ReceiptIssueResultV1 }> {
  requireSegment(datasetId, segmentId);
  const requestNonce = randomNonce();
  return issueGovernedReceiptWithNonce(
    env,
    environment,
    datasetId,
    segmentId,
    requestNonce,
  );
}

async function issueGovernedReceiptWithNonce(
  env: ReceiptAuthorityClientEnv,
  environment: ReceiptAuthorityEnvironment,
  datasetId: string,
  segmentId: string,
  requestNonce: string,
): Promise<{ requestNonce: string; result: ReceiptIssueResultV1 }> {
  requireSegment(datasetId, segmentId);
  if (!/^[0-9a-f]{64}$/.test(requestNonce)) {
    throw new TypeError("receipt issue nonce is invalid");
  }
  const prepared = await prepareRequest(
    env,
    environment,
    datasetId,
    segmentId,
    requestNonce,
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
): Promise<ReceiptIssueResultV1> {
  requireSegment(datasetId, segmentId);
  if (!/^[0-9a-f]{64}$/.test(requestNonce)) {
    throw new TypeError("receipt recovery nonce is invalid");
  }
  const prepared = await prepareRequest(
    env,
    environment,
    datasetId,
    segmentId,
    requestNonce,
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
    `SELECT operation_id,request_nonce,environment,dataset,segment_id,state,
            receipt_digest
       FROM receipt_authority_requests WHERE operation_id=?`,
  ).bind(operationId).first<PreparedRequest>();
  if (prepared === null) throw new Error("Receipt request is not durably prepared");
  return callPrepared(env, prepared, "recover_issue");
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
