import { canonicalDigest } from "../../receipt-evidence-authority/src/canonical";
import type { JsdaWorkerEnv } from "../src/env";
import { loadJob } from "../src/job_store";

const SEMANTIC = `sha256:${"11".repeat(32)}`;
const STRUCTURED = `sha256:${"33".repeat(32)}`;
const RECEIPT_DIGEST = `sha256:${"22".repeat(32)}`;

export async function persistClosedJsdaLedger(
  db: D1Database,
  request: Record<string, unknown>,
  operationId: string,
): Promise<void> {
  const existing = await db.prepare(
    "SELECT state FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(operationId).first<{ state: string }>();
  if (existing?.state === "RECEIPT_COMMITTED") return;
  const now = "2026-08-25T01:32:00.000Z";
  await db.prepare(
    `INSERT INTO ingestion_run_log
     (ran_at,source,runtime,status,detail,authority_operation_id)
     VALUES (?,'jsda','receipt-evidence-authority','RUNNING',NULL,?)`,
  ).bind(now, operationId).run();
  const run = await db.prepare(
    "SELECT id FROM ingestion_run_log WHERE authority_operation_id=?",
  ).bind(operationId).first<{ id: number }>();
  if (run === null) throw new Error("run allocation failed");
  await db.prepare(
    `INSERT INTO receipt_authority_operations
     (operation_id,request_digest,run_id,environment,source,contract_id,dataset,segment_id,
      segment_start,segment_end,state,raw_manifest_key,raw_manifest_digest,
      raw_page_count,raw_row_count,raw_bytes,checked_at,updated_at)
     VALUES (?,?,?, 'production','jsda',?,?,?,?,?,'COLLECTING',?,?,1,1,16,?,?)`,
  ).bind(
    operationId,
    operationId,
    run.id,
    request.contract_id,
    request.dataset_id,
    request.segment_id,
    request.expected_key_start,
    request.expected_key_end,
    `raw/jsda/${operationId.slice(7, 23)}/manifest.json`,
    SEMANTIC,
    now,
    now,
  ).run();
  const artifactKey = `structured/jsda/${operationId.slice(7, 23)}.jsonl`;
  const manifestKey = `authority/jsda/${operationId.slice(7, 23)}.manifest.json`;
  const rawManifestKey = `raw/jsda/${operationId.slice(7, 23)}/manifest.json`;
  await db.prepare(
    `INSERT INTO receipt_product_materializations
     (operation_id,run_id,source,dataset,segment_id,artifact_key,artifact_digest,artifact_body,
      row_count,byte_count,manifest_key,manifest_digest,raw_manifest_key,raw_manifest_digest,
      raw_page_count,raw_row_count,raw_bytes,committed_at)
     VALUES (?,?, 'jsda',?,?,?,?,?,1,8,?,?,?, ?,1,1,16,?)`,
  ).bind(
    operationId,
    run.id,
    request.dataset_id,
    request.segment_id,
    artifactKey,
    STRUCTURED,
    "{}\n",
    manifestKey,
    `sha256:${"44".repeat(32)}`,
    rawManifestKey,
    SEMANTIC,
    now,
  ).run();
  await db.prepare(
    `UPDATE receipt_authority_operations
        SET state='STRUCTURED_COMMITTED', structured_manifest_key=?, structured_digest=?
      WHERE operation_id=?`,
  ).bind(manifestKey, STRUCTURED, operationId).run();
  await db.prepare(
    `INSERT INTO collection_receipts
     (source,dataset,segment_id,segment_start,segment_end,expected_scope,
      expected_items,observed_items,raw_page_count,raw_row_count,
      structured_row_count,pagination_exhausted,digests_json,run_id,status,
      error,checked_at)
     VALUES ('jsda',?,?,?,?, '{}',1,1,1,1,1,1,'{}',?,'SUCCESS',NULL,?)`,
  ).bind(
    request.dataset_id,
    request.segment_id,
    request.expected_key_start,
    request.expected_key_end,
    run.id,
    now,
  ).run();
  await db.prepare(
    `UPDATE receipt_authority_operations
        SET state='RECEIPT_COMMITTED', receipt_digest=?
      WHERE operation_id=?`,
  ).bind(RECEIPT_DIGEST, operationId).run();
}

export async function issuedClosedJsdaResult(
  db: D1Database,
  request: Record<string, unknown>,
  replayed = false,
) {
  const operationId = await canonicalDigest({
    ...request,
    operation: "issue_for_segment",
  });
  const workKey = String(request.work_key ?? "");
  const job = workKey ? await loadJob(db, workKey) : null;
  return {
    schema_version: "receipt-evidence-issue-result/v1" as const,
    operation_id: operationId,
    state: "FINALIZED" as const,
    replayed,
    receipt_digest: RECEIPT_DIGEST,
    receipt: {
      source: "jsda" as const,
      dataset: String(request.dataset_id ?? job?.dataset ?? ""),
      segment_id: String(request.segment_id ?? job?.segment_id ?? ""),
      digests: {
        eligibility: "TRUSTED_COLLECTION" as const,
        raw: job?.content_digest ?? "",
      },
      status: "SUCCESS" as const,
    },
  };
}

export function closedReceiptEnv(base: JsdaWorkerEnv): JsdaWorkerEnv {
  const seen = new Set<string>();
  return {
    ...base,
    RECEIPT_AUTHORITY_OPERATION_MODE: "ACTIVE",
    RECEIPT_AUTHORITY_ENVIRONMENT: "production",
    RECEIPT_EVIDENCE_AUTHORITY: {
      async issue_for_segment(request: Record<string, unknown>) {
        const result = await issuedClosedJsdaResult(base.DB, request, seen.has(String(request.request_nonce)));
        seen.add(String(request.request_nonce));
        await persistClosedJsdaLedger(base.DB, request, result.operation_id);
        return result;
      },
      async recover_issue(request: Record<string, unknown>) {
        const result = await issuedClosedJsdaResult(base.DB, request, true);
        await persistClosedJsdaLedger(base.DB, request, result.operation_id);
        return result;
      },
    },
  } as JsdaWorkerEnv;
}
