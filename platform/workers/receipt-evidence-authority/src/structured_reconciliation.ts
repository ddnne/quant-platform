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
  putCreateOnly,
  type Capture,
} from "./raw_capture";
import type {
  ReceiptAuthorityEnv,
  ReceiptIssueRequestV1,
} from "./types";

type StructuredRow = {
  natural_key: string;
  source: "jquants";
  dataset: string;
  event_time: string;
  available_at: string;
  ingested_at: string;
  payload: string;
  raw_payload: string;
  row_digest: string;
};

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
    runId: number;
    request: ReceiptIssueRequestV1;
    initial: JquantsAcquisitionRequestV2;
    capture: Capture;
    checkedAt: string;
  },
): Promise<void> {
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_operations
     (operation_id,request_digest,run_id,environment,dataset,segment_id,
      segment_start,segment_end,state,raw_manifest_key,raw_manifest_digest,
      checked_at,updated_at)
     VALUES (?,?,?,?,?,?,?,?,'COLLECTING',?,?,?,?)`,
  ).bind(
    input.operationId,
    input.requestDigest,
    input.runId,
    input.request.environment,
    input.request.dataset_id,
    input.request.segment_id,
    input.initial.segment_start,
    input.initial.segment_end,
    input.capture.rawManifestKey,
    input.capture.rawManifestDigest,
    input.checkedAt,
    input.checkedAt,
  ).run();
  const row = await env.DB.prepare(
    "SELECT * FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(input.operationId).first<D1Operation>();
  if (
    row === null || row.request_digest !== input.requestDigest ||
    row.run_id !== input.runId || row.environment !== input.request.environment ||
    row.dataset !== input.request.dataset_id || row.segment_id !== input.request.segment_id ||
    row.segment_start !== input.initial.segment_start ||
    row.segment_end !== input.initial.segment_end ||
    row.raw_manifest_key !== input.capture.rawManifestKey ||
    row.raw_manifest_digest !== input.capture.rawManifestDigest ||
    row.checked_at !== input.checkedAt
  ) throw new Error("D1 receipt operation replay differs from authority measurement");
}

async function normalizeRows(
  rows: Record<string, unknown>[],
  spec: DatasetSpec,
  checkedAt: string,
): Promise<StructuredRow[]> {
  const result: StructuredRow[] = [];
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
  rows: StructuredRow[],
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
): Promise<StructuredRow[]> {
  const rows: StructuredRow[] = [];
  let after = "";
  while (true) {
    const page = await env.DB.prepare(
      `SELECT natural_key,source,dataset,event_time,available_at,ingested_at,
              payload,raw_payload,row_digest
       FROM receipt_authority_structured_rows
       WHERE operation_id=? AND natural_key>?
       ORDER BY natural_key LIMIT 200`,
    ).bind(operationId, after).all<StructuredRow>();
    const batch = page.results ?? [];
    rows.push(...batch);
    if (batch.length < 200) break;
    after = batch.at(-1)!.natural_key;
  }
  return rows;
}

async function structuredDigest(rows: StructuredRow[]): Promise<{
  digest: string;
  chunks: string[];
}> {
  const chunks: string[] = [];
  for (let index = 0; index < rows.length; index += 200) {
    chunks.push(await canonicalDigest(rows.slice(index, index + 200)));
  }
  return {
    digest: await canonicalDigest({
      schema_version: "receipt-structured-digest/v1",
      row_count: rows.length,
      chunk_size: 200,
      chunks,
    }),
    chunks,
  };
}

export async function reconcileStructured(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    capture: Capture;
    spec: DatasetSpec;
    checkedAt: string;
  },
): Promise<{ count: number; digest: string; manifestKey: string }> {
  let rawCount = 0;
  for (const page of input.capture.pages) {
    const bytes = await loadRawPage(env.RAW_BUCKET, page);
    const resolved = await resolveGovernedRequest(
      input.capture.initialRequest,
      input.capture.initialRequest.environment,
      new Date(input.checkedAt),
    );
    const rawRows = parseStrictRawPage(bytes, resolved.route).rows;
    if (rawRows.length !== page.rowCount) {
      throw new Error("persisted raw row count differs from live capture");
    }
    rawCount += rawRows.length;
    await persistStructuredRows(
      env,
      input.operationId,
      await normalizeRows(rawRows, input.spec, input.checkedAt),
    );
  }
  if (rawCount === 0) throw new Error("zero-row collection cannot mint SUCCESS");
  const stored = await readStructuredRows(env, input.operationId);
  if (stored.length !== rawCount) {
    throw new Error("structured natural-key readback does not reconcile raw rows");
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
  const measured = await structuredDigest(stored);
  const manifest = {
    schema_version: "receipt-structured-manifest/v1",
    operation_id: input.operationId,
    source: "jquants" as const,
    dataset: input.spec.id,
    row_count: stored.length,
    digest_algorithm: "receipt-structured-digest/v1",
    chunk_size: 200,
    chunk_digests: measured.chunks,
    structured_digest: measured.digest,
  };
  const manifestJson = canonicalJson(manifest);
  const manifestKey = `structured/receipt-authority/${input.capture.initialRequest.environment}/${input.spec.id}/${input.capture.initialRequest.segment_id}/${input.operationId.slice(7)}/manifest.json`;
  await putCreateOnly(env.STRUCTURED_BUCKET, manifestKey, manifestJson, {
    authority: "receipt",
    operation_id: input.operationId,
    dataset: input.spec.id,
    segment_id: input.capture.initialRequest.segment_id,
  });
  const reread = await env.STRUCTURED_BUCKET.get(manifestKey);
  if (reread === null || await reread.text() !== manifestJson) {
    throw new Error("structured immutable manifest readback failed");
  }
  await env.DB.prepare(
    `UPDATE receipt_authority_operations
     SET state='STRUCTURED_COMMITTED',structured_manifest_key=?,
         structured_digest=?,updated_at=?
     WHERE operation_id=? AND state IN ('COLLECTING','STRUCTURED_COMMITTED')`,
  ).bind(manifestKey, measured.digest, input.checkedAt, input.operationId).run();
  const operation = await env.DB.prepare(
    "SELECT * FROM receipt_authority_operations WHERE operation_id=?",
  ).bind(input.operationId).first<D1Operation>();
  if (
    operation === null || operation.state !== "STRUCTURED_COMMITTED" ||
    operation.structured_manifest_key !== manifestKey ||
    operation.structured_digest !== measured.digest
  ) throw new Error("structured D1 commit state failed");
  return { count: stored.length, digest: measured.digest, manifestKey };
}
