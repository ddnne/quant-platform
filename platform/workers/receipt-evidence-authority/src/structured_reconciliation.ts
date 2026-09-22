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
  isJsdaPersistedRequest,
  parseJsdaStructuredRows,
} from "./jsda_capture";
import {
  materializeProduct,
  persistGovernedProductSlice,
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
  source: string;
  contract_id: string;
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
    initial: Capture["initialRequest"];
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
     VALUES (?,?, 'receipt-evidence-authority','RUNNING',?,?)`,
  ).bind(input.checkedAt, input.request.source, runDetail, input.operationId).run();
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
    run.source !== input.request.source || run.runtime !== "receipt-evidence-authority" ||
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
     (operation_id,request_digest,run_id,environment,source,contract_id,dataset,segment_id,
      segment_start,segment_end,state,raw_manifest_key,raw_manifest_digest,
      raw_page_count,raw_row_count,raw_bytes,checked_at,updated_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,'COLLECTING',?,?,?,?,?,?,?)`,
  ).bind(
    input.operationId,
    input.requestDigest,
    run.id,
    input.request.environment,
    input.request.source,
    input.request.contract_id,
    input.request.dataset_id,
    input.request.segment_id,
    input.request.expected_key_start,
    input.request.expected_key_end,
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
    row.source !== input.request.source || row.contract_id !== input.request.contract_id ||
    row.dataset !== input.request.dataset_id || row.segment_id !== input.request.segment_id ||
    row.segment_start !== input.request.expected_key_start ||
    row.segment_end !== input.request.expected_key_end ||
    row.raw_manifest_key !== input.capture.rawManifestKey ||
    row.raw_manifest_digest !== input.capture.rawManifestDigest ||
    row.raw_page_count !== rawPageCount || row.raw_row_count !== rawRowCount ||
    row.raw_bytes !== rawBytes ||
    row.checked_at !== run.ran_at
  ) throw new Error("D1 receipt operation replay differs from authority measurement");
  return { runId: run.id, checkedAt: run.ran_at };
}

async function productNaturalKey(
  row: Record<string, unknown>,
  spec: DatasetSpec,
): Promise<string> {
  if (spec.id.startsWith("jsda_") && typeof row.job_type === "string") {
    const picked: Record<string, unknown> = {};
    for (const field of ["source", "job_type", "segment_id", "target_url"] as const) {
      const value = row[field];
      if (typeof value !== "string" || value.length === 0) {
        throw new Error(
          `governed natural-key field ${field} is absent; structured product is rejected`,
        );
      }
      picked[field] = value;
    }
    return stableJson(picked);
  }
  return naturalKey(row, spec);
}

async function normalizeRows(
  rows: Record<string, unknown>[],
  spec: DatasetSpec,
  checkedAt: string,
): Promise<CanonicalStructuredRow[]> {
  const result: CanonicalStructuredRow[] = [];
  for (const row of rows) {
    const key = await productNaturalKey(row, spec);
    const availableAt = pickAvailableAt(row, spec.id, checkedAt);
    const normalized = {
      natural_key: key,
      source: spec.id.startsWith("jsda_") ? "jsda" as const : "jquants" as const,
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
  for (let index = 0; index < rows.length; index += 50) {
    const expected = rows.slice(index, index + 50);
    const insert = env.DB.prepare(
      `INSERT OR IGNORE INTO receipt_authority_structured_rows
       (operation_id,natural_key,source,dataset,event_time,available_at,
        ingested_at,payload,raw_payload,row_digest)
       SELECT ?,json_extract(value,'$.natural_key'),json_extract(value,'$.source'),
              json_extract(value,'$.dataset'),json_extract(value,'$.event_time'),
              json_extract(value,'$.available_at'),json_extract(value,'$.ingested_at'),
              json_extract(value,'$.payload'),json_extract(value,'$.raw_payload'),
              json_extract(value,'$.row_digest') FROM json_each(?)`,
    ).bind(operationId, JSON.stringify(expected));
    const select = env.DB.prepare(
      `SELECT natural_key,source,dataset,event_time,available_at,ingested_at,
              payload,raw_payload,row_digest
         FROM receipt_authority_structured_rows WHERE operation_id=?
          AND natural_key IN (${expected.map(() => "?").join(",")})`,
    ).bind(operationId, ...expected.map((row) => row.natural_key));
    // Keep write/readback ordered in one bounded D1 round trip.
    const [, result] = await env.DB.batch<CanonicalStructuredRow>([insert, select]);
    if (!result) throw new Error("structured readback result is absent");
    const stored = new Map(result.results.map((row) => [row.natural_key, row]));
    for (const row of expected) {
      if (canonicalJson(stored.get(row.natural_key) ?? null) !== canonicalJson(row)) {
        throw new Error("persisted structured fields differ from canonical raw normalization");
      }
    }
  }
}

const STRUCTURED_SLICE_PAGES = 4;
// Five D1 statements per 50 rows plus bounded metadata/readback work.
const STRUCTURED_SLICE_ROWS = 6000;
export const STRUCTURED_SLICE_INCOMPLETE =
  "structured reconciliation slice is incomplete";
export const STRUCTURED_CARDINALITY_MISMATCH =
  "structured natural-key cardinality differs from raw pages";

type StructuredProgress = {
  schema_version: "receipt-authority-structured-progress/v1";
  operation_id: string;
  next_page: number;
  next_row?: number;
  raw_rows_committed: number;
};

function structuredProgressKey(rawManifestKey: string): string {
  if (!rawManifestKey.endsWith("/manifest.json")) {
    throw new Error("capture manifest key is not a governed prefix");
  }
  return `${rawManifestKey.slice(0, -"manifest.json".length)}structured-progress.json`;
}

async function loadStructuredProgress(
  env: ReceiptAuthorityEnv,
  operationId: string,
  rawManifestKey: string,
): Promise<StructuredProgress> {
  const vacant: StructuredProgress = {
    schema_version: "receipt-authority-structured-progress/v1",
    operation_id: operationId,
    next_page: 0,
    raw_rows_committed: 0,
  };
  const object = await env.AUTHORITY_EVIDENCE_BUCKET.get(
    structuredProgressKey(rawManifestKey),
  );
  if (object === null) return vacant;
  const value = JSON.parse(await object.text()) as StructuredProgress;
  if (
    value.schema_version !== "receipt-authority-structured-progress/v1" ||
    value.operation_id !== operationId ||
    !Number.isSafeInteger(value.next_page) || value.next_page < 0 ||
    (value.next_row !== undefined && (!Number.isSafeInteger(value.next_row) || value.next_row < 0)) ||
    !Number.isSafeInteger(value.raw_rows_committed) || value.raw_rows_committed < 0
  ) {
    throw new Error("structured progress identity is invalid");
  }
  return value;
}

async function saveStructuredProgress(
  env: ReceiptAuthorityEnv,
  rawManifestKey: string,
  progress: StructuredProgress,
): Promise<void> {
  await env.AUTHORITY_EVIDENCE_BUCKET.put(
    structuredProgressKey(rawManifestKey),
    canonicalJson(progress),
  );
}

async function countStructuredRows(
  env: ReceiptAuthorityEnv,
  operationId: string,
): Promise<number> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM receipt_authority_structured_rows WHERE operation_id=?`,
  ).bind(operationId).first<{ n: number }>();
  if (row === null || !Number.isSafeInteger(row.n) || row.n < 0) {
    throw new Error("structured row count is unreadable");
  }
  return row.n;
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
): Promise<{
    count: number;
    digest: string;
    artifactKey: string;
    artifactByteCount: number;
    manifestKey: string;
    manifestByteCount: number;
    manifestDigest: string;
    naturalKeyDigest: string;
  }> {
  if (!input.capture.paginationExhausted || !input.capture.discoveryExhausted) {
    throw new Error("structured reconciliation requires exhausted raw evidence");
  }
  const rawCount = input.capture.pages.reduce((total, page) => total + page.rowCount, 0);
  if (rawCount === 0) throw new Error("zero-row collection cannot mint SUCCESS");
  let progress = await loadStructuredProgress(
    env, input.operationId, input.capture.rawManifestKey,
  );
  if (progress.next_page > input.capture.pages.length) {
    throw new Error(STRUCTURED_CARDINALITY_MISMATCH);
  }
  const nextRow = progress.next_row ?? 0;
  const expectedProgress = input.capture.pages.slice(0, progress.next_page)
    .reduce((total, page) => total + page.rowCount, 0) + nextRow;
  if (progress.raw_rows_committed !== expectedProgress ||
      nextRow > (input.capture.pages[progress.next_page]?.rowCount ?? 0)) {
    throw new Error(STRUCTURED_CARDINALITY_MISMATCH);
  }
  const storedBefore = await countStructuredRows(env, input.operationId);
  if (storedBefore < progress.raw_rows_committed) {
    throw new Error(STRUCTURED_CARDINALITY_MISMATCH);
  }
  let pagesThisInvocation = 0;
  let rowsThisInvocation = 0;
  const jsda = isJsdaPersistedRequest(input.capture.initialRequest)
    ? input.capture.initialRequest
    : null;
  const resolved = jsda === null
    ? await resolveGovernedRequest(
      input.capture.initialRequest as JquantsAcquisitionRequestV2,
      input.capture.initialRequest.environment,
      new Date(input.checkedAt),
    )
    : null;
  for (let pageIndex = progress.next_page; pageIndex < input.capture.pages.length; pageIndex += 1) {
    if (pagesThisInvocation >= STRUCTURED_SLICE_PAGES || rowsThisInvocation >= STRUCTURED_SLICE_ROWS) {
      await saveStructuredProgress(env, input.capture.rawManifestKey, progress);
      throw new Error(STRUCTURED_SLICE_INCOMPLETE);
    }
    const page = input.capture.pages[pageIndex]!;
    const bytes = await loadRawPage(env.RAW_BUCKET, page);
    let rawRows: Record<string, unknown>[];
    if (jsda !== null) {
      rawRows = parseJsdaStructuredRows(bytes, jsda.job_type, jsda.frontier_json, {
        datasetId: jsda.dataset_id,
        targetUrl: jsda.target_url,
        publicationLabelDate: jsda.segment_start,
        quoteEffectiveDate: null,
      });
    } else {
      if (resolved === null) {
        throw new Error("structured reconciliation requires exhausted raw evidence");
      }
      const rawEvidence = parseStrictRawPage(bytes, resolved.route);
      if (rawEvidence.providerState !== page.metadata.provider_pagination_state) {
        throw new Error("persisted provider pagination differs from raw bytes");
      }
      rawRows = rawEvidence.rows;
    }
    if (rawRows.length !== page.rowCount) {
      throw new Error("persisted raw row count differs from live capture");
    }
    const offset = progress.next_row ?? 0;
    const slice = rawRows.slice(offset, offset + STRUCTURED_SLICE_ROWS - rowsThisInvocation);
    const normalized = await normalizeRows(slice, input.spec, input.checkedAt);
    await persistStructuredRows(env, input.operationId, normalized);
    await persistGovernedProductSlice(env, normalized);
    progress = {
      ...progress,
      next_page: offset + slice.length === rawRows.length ? pageIndex + 1 : pageIndex,
      next_row: offset + slice.length === rawRows.length ? 0 : offset + slice.length,
      raw_rows_committed: progress.raw_rows_committed + slice.length,
    };
    pagesThisInvocation += 1;
    rowsThisInvocation += slice.length;
    // D1 writes can survive a crash before the R2 checkpoint. Replay them
    // idempotently; only the exhausted collection has an exact total count.
    await saveStructuredProgress(env, input.capture.rawManifestKey, progress);
    if (progress.next_row !== 0) throw new Error(STRUCTURED_SLICE_INCOMPLETE);
  }
  await saveStructuredProgress(env, input.capture.rawManifestKey, progress);
  const storedCount = await countStructuredRows(env, input.operationId);
  if (progress.next_page !== input.capture.pages.length || storedCount !== rawCount) {
    throw new Error(STRUCTURED_CARDINALITY_MISMATCH);
  }
  // Finalization gets a fresh invocation after a large write slice.
  if (rowsThisInvocation >= 1000) throw new Error(STRUCTURED_SLICE_INCOMPLETE);
  const product = await materializeProduct(env, {
    operationId: input.operationId,
    runId: input.runId,
    capture: input.capture,
    expectedCount: rawCount,
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
    artifactKey: product.artifactKey,
    artifactByteCount: product.artifactByteCount,
    manifestKey: product.manifestKey,
    manifestByteCount: product.manifestByteCount,
    manifestDigest: product.manifestDigest,
    naturalKeyDigest: product.naturalKeyDigest,
  };
}
