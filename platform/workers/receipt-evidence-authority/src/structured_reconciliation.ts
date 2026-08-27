import {
  canonicalDigest,
  canonicalJson,
  resolveGovernedRequest,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type { JquantsAcquisitionRequestV2 } from "../../ingestion-secrets/src/jquants_acquisition_types";
import { pickAvailableAt } from "../../ingestion-premium/src/availability";
import type { DatasetSpec } from "../../ingestion-premium/src/catalog";
import {
  naturalKey,
  pickEventTime,
  stableJson,
} from "../../ingestion-premium/src/identity";
import { parseStrictRawPage } from "./pagination_proof";
import {
  loadRawPage,
  type Capture,
} from "./raw_capture";
import {
  compareUtf8Text,
  materializeProduct,
  type CanonicalStructuredRow,
} from "./product_materialization";
import type {
  ReceiptAuthorityEnv,
  ReceiptIssueRequestV1,
} from "./types";

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
  raw_page_count: number | null;
  raw_row_count: number | null;
  raw_bytes: number | null;
  structured_manifest_key: string | null;
  structured_digest: string | null;
  receipt_digest: string | null;
  checked_at: string;
  updated_at: string;
};

export async function initializeD1Operation(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    requestDigest: string;
    request: ReceiptIssueRequestV1;
    initial: JquantsAcquisitionRequestV2;
    capture: Capture;
    checkedAt: string;
  },
): Promise<{ runId: number; checkedAt: string }> {
  const runDetail = canonicalJson({
    schema_version: "receipt-authority-ingestion-run/v1",
    operation_id: input.operationId,
    request_digest: input.requestDigest,
    environment: input.request.environment,
    dataset: input.request.dataset_id,
    segment_id: input.request.segment_id,
    raw_manifest_key: input.capture.rawManifestKey,
    raw_manifest_digest: input.capture.rawManifestDigest,
  });
  await env.DB.prepare(
    `INSERT OR IGNORE INTO ingestion_run_log
     (ran_at,source,runtime,status,detail,authority_operation_id)
     VALUES (?,'jquants','receipt-evidence-authority','RUNNING',?,?)`,
  ).bind(input.checkedAt, runDetail, input.operationId).run();
  const run = await env.DB.prepare(
    `SELECT id,ran_at,source,runtime,status,detail,authority_operation_id
       FROM ingestion_run_log WHERE authority_operation_id=?`,
  ).bind(input.operationId).first<{
    id: number;
    ran_at: string;
    source: string;
    runtime: string;
    status: string;
    detail: string;
    authority_operation_id: string;
  }>();
  if (
    run === null || !Number.isSafeInteger(run.id) || run.id <= 0 ||
    run.source !== "jquants" || run.runtime !== "receipt-evidence-authority" ||
    run.status !== "RUNNING" || run.detail !== runDetail ||
    run.authority_operation_id !== input.operationId ||
    !Number.isFinite(Date.parse(run.ran_at))
  ) throw new Error("ingestion run allocation differs from authority request");
  const rawPageCount = input.capture.pages.length;
  const rawRowCount = input.capture.pages.reduce(
    (total, page) => total + page.rowCount,
    0,
  );
  const rawBytes = input.capture.pages.reduce(
    (total, page) => total + page.size,
    0,
  );
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_operations
     (operation_id,request_digest,run_id,environment,dataset,segment_id,
      segment_start,segment_end,state,raw_manifest_key,raw_manifest_digest,
      raw_page_count,raw_row_count,raw_bytes,checked_at,updated_at)
     VALUES (?,?,?,?,?,?,?,?,'COLLECTING',?,?,?,?,?,?,?)`,
  ).bind(
    input.operationId,
    input.requestDigest,
    run.id,
    input.request.environment,
    input.request.dataset_id,
    input.request.segment_id,
    input.initial.segment_start,
    input.initial.segment_end,
    input.capture.rawManifestKey,
    input.capture.rawManifestDigest,
    rawPageCount,
    rawRowCount,
    rawBytes,
    run.ran_at,
    run.ran_at,
  ).run();
  const row = await env.DB.prepare(
    "SELECT * FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(input.operationId).first<D1Operation>();
  if (
    row === null || row.request_digest !== input.requestDigest ||
    row.run_id !== run.id || row.environment !== input.request.environment ||
    row.dataset !== input.request.dataset_id || row.segment_id !== input.request.segment_id ||
    row.segment_start !== input.initial.segment_start ||
    row.segment_end !== input.initial.segment_end ||
    row.raw_manifest_key !== input.capture.rawManifestKey ||
    row.raw_manifest_digest !== input.capture.rawManifestDigest ||
    row.raw_page_count !== rawPageCount || row.raw_row_count !== rawRowCount ||
    row.raw_bytes !== rawBytes ||
    row.checked_at !== run.ran_at
  ) throw new Error("D1 receipt operation replay differs from authority measurement");
  return { runId: run.id, checkedAt: run.ran_at };
}

async function normalizeRows(
  rows: Record<string, unknown>[],
  spec: DatasetSpec,
  checkedAt: string,
): Promise<CanonicalStructuredRow[]> {
  const result: CanonicalStructuredRow[] = [];
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
  rows: CanonicalStructuredRow[],
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
): Promise<CanonicalStructuredRow[]> {
  const rows: CanonicalStructuredRow[] = [];
  let after = "";
  while (true) {
    const page = await env.DB.prepare(
      `SELECT natural_key,source,dataset,event_time,available_at,ingested_at,
              payload,raw_payload,row_digest
       FROM receipt_authority_structured_rows
       WHERE operation_id=? AND natural_key>?
       ORDER BY natural_key LIMIT 200`,
    ).bind(operationId, after).all<CanonicalStructuredRow>();
    const batch = page.results ?? [];
    rows.push(...batch);
    if (batch.length < 200) break;
    after = batch.at(-1)!.natural_key;
  }
  return rows;
}

export async function reconcileStructured(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    runId: number;
    capture: Capture;
    spec: DatasetSpec;
    checkedAt: string;
  },
): Promise<{ count: number; digest: string; manifestKey: string }> {
  if (!input.capture.paginationExhausted || !input.capture.discoveryExhausted) {
    throw new Error("structured reconciliation requires exhausted raw evidence");
  }
  let rawCount = 0;
  const expectedRows: CanonicalStructuredRow[] = [];
  const resolved = await resolveGovernedRequest(
    input.capture.initialRequest,
    input.capture.initialRequest.environment,
    new Date(input.checkedAt),
  );
  for (const page of input.capture.pages) {
    const bytes = await loadRawPage(env.AUTHORITY_EVIDENCE_BUCKET, page);
    const rawEvidence = parseStrictRawPage(bytes, resolved.route);
    if (rawEvidence.providerState !== page.metadata.provider_pagination_state) {
      throw new Error("persisted provider pagination differs from raw bytes");
    }
    const rawRows = rawEvidence.rows;
    if (rawRows.length !== page.rowCount) {
      throw new Error("persisted raw row count differs from live capture");
    }
    rawCount += rawRows.length;
    const normalized = await normalizeRows(rawRows, input.spec, input.checkedAt);
    expectedRows.push(...normalized);
    await persistStructuredRows(env, input.operationId, normalized);
  }
  if (rawCount === 0) throw new Error("zero-row collection cannot mint SUCCESS");
  const stored = await readStructuredRows(env, input.operationId);
  if (stored.length !== rawCount) {
    throw new Error("structured natural-key readback does not reconcile raw rows");
  }
  expectedRows.sort((left, right) =>
    compareUtf8Text(left.natural_key, right.natural_key)
  );
  if (canonicalJson(stored) !== canonicalJson(expectedRows)) {
    throw new Error(
      "persisted structured fields differ from canonical raw normalization",
    );
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
  const product = await materializeProduct(env, {
    operationId: input.operationId,
    runId: input.runId,
    capture: input.capture,
    rows: stored,
    checkedAt: input.checkedAt,
  });
  await env.DB.prepare(
    `UPDATE receipt_authority_operations
     SET state='STRUCTURED_COMMITTED',structured_manifest_key=?,
         structured_digest=?,updated_at=?
     WHERE operation_id=? AND state IN ('COLLECTING','STRUCTURED_COMMITTED')`,
  ).bind(
    product.manifestKey,
    product.digest,
    input.checkedAt,
    input.operationId,
  ).run();
  const operation = await env.DB.prepare(
    "SELECT * FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(input.operationId).first<D1Operation>();
  if (
    operation === null || operation.state !== "STRUCTURED_COMMITTED" ||
    operation.structured_manifest_key !== product.manifestKey ||
    operation.structured_digest !== product.digest
  ) throw new Error("structured D1 commit state failed");
  return {
    count: product.count,
    digest: product.digest,
    manifestKey: product.manifestKey,
  };
}
