import {
  closedJsdaReceiptEligibility,
  issueGovernedReceipt,
  recoverGovernedReceipt,
  requireClosedJsdaCallerLedger,
  type JsdaReceiptLocator,
  type ReceiptAuthorityClientEnv,
  type ReceiptAuthorityEnvironment,
} from "../../ingestion-premium/src/receipt_authority_client";
import { governedReceiptIdentity } from "../../ingestion-premium/src/catalog";
import type { JobRow } from "./job_store";
import type { JsdaWorkerEnv } from "./env";
import { TransientAcquisitionError } from "./source_http";
import type { ReceiptIssueResultV1 } from "../../receipt-evidence-authority/src/types";

export class JsdaReceiptIssueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "JsdaReceiptIssueError";
  }
}

export type JsdaReceiptClosureState =
  | "RECEIPT_PENDING"
  | "RECEIPT_REPAIR"
  | "ISSUED";

function receiptModeConfigured(
  env: JsdaWorkerEnv,
): env is JsdaWorkerEnv & {
  RECEIPT_AUTHORITY_OPERATION_MODE: "PENDING" | "ACTIVE";
} {
  return (
    env.RECEIPT_AUTHORITY_OPERATION_MODE === "PENDING" ||
    env.RECEIPT_AUTHORITY_OPERATION_MODE === "ACTIVE"
  );
}

function receiptEnv(env: JsdaWorkerEnv): ReceiptAuthorityClientEnv | null {
  if (!env.RECEIPT_EVIDENCE_AUTHORITY) return null;
  return {
    DB: env.DB,
    RECEIPT_EVIDENCE_AUTHORITY: env.RECEIPT_EVIDENCE_AUTHORITY,
  };
}

function receiptEnvironment(env: JsdaWorkerEnv): ReceiptAuthorityEnvironment {
  if (
    env.RECEIPT_AUTHORITY_ENVIRONMENT !== "staging" &&
    env.RECEIPT_AUTHORITY_ENVIRONMENT !== "production"
  ) {
    throw new JsdaReceiptIssueError("JSDA receipt authority environment is absent or invalid");
  }
  return env.RECEIPT_AUTHORITY_ENVIRONMENT;
}

function locatorFor(row: JobRow): JsdaReceiptLocator {
  if (row.raw_key === null) {
    throw new JsdaReceiptIssueError("JSDA raw object identity is missing");
  }
  return {
    work_key: row.work_key,
    expected_contract_digest: row.contract_digest,
    raw_object_key: row.raw_key,
  };
}

function matchesContentDigest(actual: string, expected: string | null): boolean {
  if (expected === null || actual.length === 0) return false;
  const hex = actual.startsWith("sha256:") ? actual.slice("sha256:".length) : actual;
  return expected === actual || expected === hex || expected === `sha256:${hex}`;
}

export function jsdaReceiptSegmentReady(row: JobRow): boolean {
  if (row.state === "failed_transient") return false;
  if (row.state === "rejected") return false;
  if (row.job_type === "fetch_file") {
    return row.state === "completed" && row.raw_key !== null && row.content_digest !== null;
  }
  return (
    row.state === "completed" &&
    row.frontier_json !== null &&
    row.raw_key !== null &&
    row.content_digest !== null
  );
}

export async function persistJsdaReceiptRepairState(
  db: D1Database,
  workKey: string,
  state: "RECEIPT_PENDING" | "RECEIPT_REPAIR",
  detail: string,
): Promise<void> {
  const lastError = `${state}:${detail}`.slice(0, 500);
  await db.prepare(
    `UPDATE jsda_acquisition_jobs_v3
        SET last_error=?, updated_at=?
      WHERE work_key=? AND state='completed'`,
  )
    .bind(lastError, new Date().toISOString(), workKey)
    .run();
}

export async function clearJsdaReceiptRepairState(
  db: D1Database,
  workKey: string,
): Promise<void> {
  await db.prepare(
    `UPDATE jsda_acquisition_jobs_v3
        SET last_error=NULL, updated_at=?
      WHERE work_key=? AND state='completed'
        AND last_error IS NOT NULL
        AND (last_error LIKE 'RECEIPT_PENDING:%' OR last_error LIKE 'RECEIPT_REPAIR:%')`,
  )
    .bind(new Date().toISOString(), workKey)
    .run();
}

async function requireMatchingJsdaIssue(
  client: ReceiptAuthorityClientEnv,
  row: JobRow,
  result: ReceiptIssueResultV1,
  locator: JsdaReceiptLocator,
): Promise<void> {
  if (result.schema_version !== "receipt-evidence-issue-result/v1" || result.state !== "FINALIZED") {
    throw new JsdaReceiptIssueError("JSDA receipt result is not finalized");
  }
  if (
    result.receipt.source !== "jsda" || result.receipt.dataset !== row.dataset ||
    result.receipt.segment_id !== row.segment_id
  ) {
    throw new JsdaReceiptIssueError("JSDA receipt identity does not match the current job");
  }
  const eligibility = closedJsdaReceiptEligibility(result.receipt);
  if (eligibility !== "TRUSTED_COLLECTION") {
    throw new JsdaReceiptIssueError("JSDA governed receipt eligibility is not trusted");
  }
  const rawDigest = String(result.receipt.digests.raw ?? "");
  if (!matchesContentDigest(rawDigest, row.content_digest)) {
    throw new JsdaReceiptIssueError("JSDA receipt raw digest does not match the current object");
  }
  await requireClosedJsdaCallerLedger(client, result.operation_id, locator);
}

export async function issueGovernedJsdaReceipt(
  env: JsdaWorkerEnv,
  row: JobRow,
  options: { recoveryNonce?: string | null; parseZero?: boolean } = {},
): Promise<"ISSUED" | "SKIPPED" | "RECOVERED_RAW_ONLY"> {
  if (env.RECEIPT_AUTHORITY_OPERATION_MODE !== "ACTIVE") return "SKIPPED";
  const client = receiptEnv(env);
  if (!client) {
    throw new JsdaReceiptIssueError("JSDA receipt authority binding is missing");
  }
  if (options.parseZero === true) {
    throw new JsdaReceiptIssueError("JSDA parse-zero cannot issue a governed receipt");
  }
  if (!jsdaReceiptSegmentReady(row)) {
    throw new JsdaReceiptIssueError("JSDA grain is not exhausted for governed receipt issuance");
  }
  const identity = governedReceiptIdentity(row.dataset);
  if (identity === undefined || identity.source !== "jsda") {
    throw new JsdaReceiptIssueError("JSDA dataset is outside the governed Receipt V3 inventory");
  }
  const locator = locatorFor(row);
  if (options.recoveryNonce) {
    const recovered = await recoverGovernedReceipt(
      client,
      receiptEnvironment(env),
      row.dataset,
      row.segment_id,
      options.recoveryNonce,
      locator,
    );
    const eligibility = closedJsdaReceiptEligibility(recovered.receipt);
    if (eligibility === "RECOVERED_RAW_ONLY") return "RECOVERED_RAW_ONLY";
    throw new JsdaReceiptIssueError("JSDA recovery is not a normal governed receipt");
  }
  const issued = await issueGovernedReceipt(
    client,
    receiptEnvironment(env),
    row.dataset,
    row.segment_id,
    locator,
  );
  const eligibility = closedJsdaReceiptEligibility(issued.result.receipt);
  if (eligibility === "RECOVERED_RAW_ONLY") {
    throw new JsdaReceiptIssueError("JSDA recovery receipt cannot substitute normal issuance");
  }
  if (eligibility !== "TRUSTED_COLLECTION") {
    throw new JsdaReceiptIssueError("JSDA governed receipt eligibility is not trusted");
  }
  await requireMatchingJsdaIssue(client, row, issued.result, locator);
  await clearJsdaReceiptRepairState(env.DB, row.work_key);
  return "ISSUED";
}

async function failClosedCompleted(
  env: JsdaWorkerEnv,
  row: JobRow,
  state: "RECEIPT_PENDING" | "RECEIPT_REPAIR",
  detail: string,
  retryCode: "receipt_pending" | "receipt_repair",
): Promise<never> {
  try {
    await persistJsdaReceiptRepairState(env.DB, row.work_key, state, detail);
  } catch {
    // Persistence is best-effort; the queue must still retry.
  }
  throw new TransientAcquisitionError(
    retryCode,
    `${state}: ${detail}`,
  );
}

export async function requireTrustedJsdaReceipt(
  env: JsdaWorkerEnv,
  row: JobRow,
): Promise<void> {
  if (row.state === "rejected" || row.state === "waiting_children") return;
  if (row.state !== "completed") return;
  if (!receiptModeConfigured(env)) {
    await failClosedCompleted(
      env,
      row,
      "RECEIPT_PENDING",
      "RECEIPT_AUTHORITY_OPERATION_MODE is absent or invalid",
      "receipt_pending",
    );
  }
  try {
    receiptEnvironment(env);
  } catch (error) {
    await failClosedCompleted(
      env,
      row,
      "RECEIPT_PENDING",
      error instanceof Error ? error.message : "receipt environment is invalid",
      "receipt_pending",
    );
  }
  if (!receiptEnv(env)) {
    await failClosedCompleted(
      env,
      row,
      "RECEIPT_PENDING",
      "RECEIPT_EVIDENCE_AUTHORITY binding is missing",
      "receipt_pending",
    );
  }
  if (env.RECEIPT_AUTHORITY_OPERATION_MODE !== "ACTIVE") {
    await failClosedCompleted(
      env,
      row,
      "RECEIPT_PENDING",
      "trusted receipt absent while receipt authority is PENDING",
      "receipt_pending",
    );
  }
  try {
    const result = await issueGovernedJsdaReceipt(env, row);
    if (result === "ISSUED") return;
    await failClosedCompleted(
      env,
      row,
      result === "SKIPPED" ? "RECEIPT_PENDING" : "RECEIPT_REPAIR",
      result === "SKIPPED"
        ? "PENDING/SKIPPED is not successful closure"
        : "RECOVERED_RAW_ONLY cannot mint COMPLETE",
      result === "SKIPPED" ? "receipt_pending" : "receipt_repair",
    );
  } catch (error) {
    if (error instanceof TransientAcquisitionError) throw error;
    await persistJsdaReceiptRepairState(
      env.DB,
      row.work_key,
      "RECEIPT_REPAIR",
      error instanceof Error ? error.message : "receipt issuance failed",
    );
    throw new TransientAcquisitionError(
      "receipt_repair",
      `RECEIPT_REPAIR: ${error instanceof Error ? error.message : "trusted JSDA receipt is missing after terminal completion"}`,
    );
  }
}
