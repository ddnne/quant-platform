import { canonicalJson, sha256Digest } from "./canonical";
import { putCreateOnly, type Capture } from "./raw_capture";
import type { ReceiptAuthorityEnv } from "./types";

export type CanonicalStructuredRow = {
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

type GovernedProductRow = Omit<CanonicalStructuredRow, "row_digest">;

type ProductMaterializationRow = {
  operation_id: string;
  run_id: number;
  source: string;
  dataset: string;
  segment_id: string;
  artifact_key: string;
  artifact_digest: string;
  artifact_body: string;
  row_count: number;
  byte_count: number;
  manifest_key: string;
  manifest_digest: string;
  raw_manifest_key: string;
  raw_manifest_digest: string;
  raw_page_count: number;
  raw_row_count: number;
  raw_bytes: number;
  committed_at: string;
};

function productLine(row: CanonicalStructuredRow): string {
  return canonicalJson({
    source: row.source,
    dataset: row.dataset,
    natural_key: row.natural_key,
    event_time: row.event_time,
    available_at: row.available_at,
    ingested_at: row.ingested_at,
    payload: row.payload,
    raw_payload: row.raw_payload,
  });
}

export function compareUtf8Text(left: string, right: string): number {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  const length = Math.min(leftBytes.length, rightBytes.length);
  for (let index = 0; index < length; index += 1) {
    if (leftBytes[index] !== rightBytes[index]) {
      return leftBytes[index]! - rightBytes[index]!;
    }
  }
  return leftBytes.length - rightBytes.length;
}

export function canonicalProductBody(rows: CanonicalStructuredRow[]): string {
  const ordered = [...rows].sort((left, right) =>
    compareUtf8Text(left.source, right.source) ||
    compareUtf8Text(left.dataset, right.dataset) ||
    compareUtf8Text(left.natural_key, right.natural_key)
  );
  return `${ordered.map(productLine).join("\n")}\n`;
}

function governedProductFields(row: CanonicalStructuredRow): GovernedProductRow {
  return {
    source: row.source,
    dataset: row.dataset,
    natural_key: row.natural_key,
    event_time: row.event_time,
    available_at: row.available_at,
    ingested_at: row.ingested_at,
    payload: row.payload,
    raw_payload: row.raw_payload,
  };
}

function governedBusinessFields(row: GovernedProductRow): Omit<
  GovernedProductRow,
  "ingested_at"
> {
  return {
    source: row.source,
    dataset: row.dataset,
    natural_key: row.natural_key,
    event_time: row.event_time,
    available_at: row.available_at,
    payload: row.payload,
    raw_payload: row.raw_payload,
  };
}

async function persistGovernedProduct(
  env: ReceiptAuthorityEnv,
  rows: CanonicalStructuredRow[],
): Promise<CanonicalStructuredRow[]> {
  const primary = rows.map((row) => env.DB.prepare(
    `INSERT OR IGNORE INTO jquants_records
     (source,dataset,natural_key,event_time,available_at,ingested_at,payload,raw_payload)
     VALUES (?,?,?,?,?,?,?,?)`,
  ).bind(
    row.source,
    row.dataset,
    row.natural_key,
    row.event_time,
    row.available_at,
    row.ingested_at,
    row.payload,
    row.raw_payload,
  ));
  for (let index = 0; index < primary.length; index += 50) {
    await env.DB.batch(primary.slice(index, index + 50));
  }

  const stored: GovernedProductRow[] = [];
  for (let index = 0; index < rows.length; index += 50) {
    const expected = rows.slice(index, index + 50);
    const placeholders = expected.map(() => "?").join(",");
    const result = await env.DB.prepare(
      `SELECT source,dataset,natural_key,event_time,available_at,ingested_at,
              payload,raw_payload
         FROM jquants_records
        WHERE source='jquants' AND dataset=?
          AND natural_key IN (${placeholders})
        ORDER BY natural_key`,
    ).bind(
      expected[0]!.dataset,
      ...expected.map((row) => row.natural_key),
    ).all<GovernedProductRow>();
    stored.push(...(result.results ?? []));
  }

  const byNaturalKey = new Map<string, GovernedProductRow>();
  for (const row of stored) {
    if (byNaturalKey.has(row.natural_key)) {
      throw new Error("governed jquants_records contains duplicate natural keys");
    }
    byNaturalKey.set(row.natural_key, row);
  }

  const productRows: CanonicalStructuredRow[] = [];
  for (const expected of rows) {
    const actual = byNaturalKey.get(expected.natural_key);
    const expectedFields = governedProductFields(expected);
    if (
      actual === undefined || actual.source !== "jquants" ||
      canonicalJson(governedBusinessFields(actual)) !==
        canonicalJson(governedBusinessFields(expectedFields)) ||
      !Number.isFinite(Date.parse(actual.ingested_at)) ||
      !Number.isFinite(Date.parse(actual.available_at)) ||
      Date.parse(actual.ingested_at) < Date.parse(actual.available_at) ||
      Date.parse(actual.ingested_at) > Date.parse(expected.ingested_at)
    ) {
      throw new Error(
        "governed jquants_records fields differ from canonical raw normalization",
      );
    }
    productRows.push({
      ...actual,
      row_digest: await sha256Digest(canonicalJson(actual)),
    });
  }
  if (productRows.length !== stored.length) {
    throw new Error(
      "governed jquants_records fields differ from canonical raw normalization",
    );
  }

  const changes = productRows.map((row) => env.DB.prepare(
    `INSERT OR IGNORE INTO ingestion_change_log
     (table_name,source,dataset,natural_key,event_time,available_at,ingested_at,
      payload,raw_payload,changed_at)
     VALUES ('jquants_records',?,?,?,?,?,?,?,?,?)`,
  ).bind(
    row.source,
    row.dataset,
    row.natural_key,
    row.event_time,
    row.available_at,
    row.ingested_at,
    row.payload,
    row.raw_payload,
    row.ingested_at,
  ));
  for (let index = 0; index < changes.length; index += 50) {
    await env.DB.batch(changes.slice(index, index + 50));
  }
  for (const row of productRows) {
    const change = await env.DB.prepare(
      `SELECT change_seq,table_name,source,dataset,natural_key,event_time,
              available_at,ingested_at,payload,raw_payload,changed_at
         FROM ingestion_change_log
        WHERE table_name='jquants_records' AND source=? AND dataset=?
          AND natural_key=? AND available_at=? AND ingested_at=? AND payload=?`,
    ).bind(
      row.source,
      row.dataset,
      row.natural_key,
      row.available_at,
      row.ingested_at,
      row.payload,
    ).first<Record<string, unknown>>();
    if (
      change === null || typeof change.change_seq !== "number" ||
      !Number.isSafeInteger(change.change_seq) || change.change_seq <= 0 ||
      canonicalJson({
        source: change.source,
        dataset: change.dataset,
        natural_key: change.natural_key,
        event_time: change.event_time,
        available_at: change.available_at,
        ingested_at: change.ingested_at,
        payload: change.payload,
        raw_payload: change.raw_payload,
      }) !== canonicalJson(governedProductFields(row)) ||
      change.table_name !== "jquants_records" ||
      change.changed_at !== row.ingested_at
    ) throw new Error("governed product change feed differs from signed rows");
  }
  return productRows;
}

async function requireExactObject(
  bucket: R2Bucket,
  key: string,
  expected: Uint8Array,
  expectedDigest: string,
): Promise<void> {
  const object = await bucket.get(key);
  if (object === null) throw new Error("product materialization disappeared");
  const stored = new Uint8Array(await object.arrayBuffer());
  if (
    stored.byteLength !== expected.byteLength ||
    await sha256Digest(stored) !== expectedDigest
  ) throw new Error("product materialization readback differs from signed bytes");
}

/**
 * Materialize the actual `jquants_records/v1` product artifact.  The returned
 * digest is the SHA-256 of the exact bytes placed in the authority-owned
 * immutable product prefix; it is not a digest of the reconciliation shadow
 * table.
 */
export async function materializeProduct(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    runId: number;
    capture: Capture;
    rows: CanonicalStructuredRow[];
    checkedAt: string;
  },
): Promise<{
  count: number;
  digest: string;
  artifactKey: string;
  manifestKey: string;
}> {
  if (input.rows.length === 0) {
    throw new Error("empty product materialization cannot be signed");
  }
  const productRows = await persistGovernedProduct(env, input.rows);
  const body = canonicalProductBody(productRows);
  const bytes = new TextEncoder().encode(body);
  const artifactDigest = await sha256Digest(bytes);
  const dataset = input.capture.initialRequest.dataset_id;
  const segmentId = input.capture.initialRequest.segment_id;
  const prefix =
    `product/receipt-authority/${env.ENVIRONMENT}/${dataset}/${segmentId}/run-${input.runId}`;
  const artifactKey = `${prefix}-${input.operationId.slice(7, 23)}.jsonl`;
  await putCreateOnly(
    env.AUTHORITY_EVIDENCE_BUCKET,
    artifactKey,
    bytes,
    {
      schema: "jquants_records/v1",
      authority: "receipt-evidence-authority",
      operation_id: input.operationId,
      dataset,
      segment_id: segmentId,
      run_id: String(input.runId),
      structured_digest: artifactDigest,
    },
  );
  await requireExactObject(
    env.AUTHORITY_EVIDENCE_BUCKET,
    artifactKey,
    bytes,
    artifactDigest,
  );

  const rawPageCount = input.capture.pages.length;
  const rawRowCount = input.capture.pages.reduce(
    (total, page) => total + page.rowCount,
    0,
  );
  const rawBytes = input.capture.pages.reduce(
    (total, page) => total + page.size,
    0,
  );
  const manifest = {
    schema_version: "receipt-product-materialization/v1",
    product_schema: "jquants_records/v1",
    operation_id: input.operationId,
    run_id: input.runId,
    source: "jquants" as const,
    dataset,
    segment_id: segmentId,
    artifact_key: artifactKey,
    artifact_digest: artifactDigest,
    artifact_body: body,
    structured_digest: artifactDigest,
    row_count: productRows.length,
    byte_count: bytes.byteLength,
    raw_manifest_key: input.capture.rawManifestKey,
    raw_manifest_digest: input.capture.rawManifestDigest,
    raw_page_count: rawPageCount,
    raw_row_count: rawRowCount,
    raw_bytes: rawBytes,
    committed_at: input.checkedAt,
  };
  const manifestJson = canonicalJson(manifest);
  const manifestBytes = new TextEncoder().encode(manifestJson);
  const manifestDigest = await sha256Digest(manifestBytes);
  const manifestKey = `${prefix}-${input.operationId.slice(7, 23)}.manifest.json`;
  await putCreateOnly(
    env.AUTHORITY_EVIDENCE_BUCKET,
    manifestKey,
    manifestBytes,
    {
      schema: "receipt-product-materialization/v1",
      authority: "receipt-evidence-authority",
      operation_id: input.operationId,
      artifact_digest: artifactDigest,
    },
  );
  await requireExactObject(
    env.AUTHORITY_EVIDENCE_BUCKET,
    manifestKey,
    manifestBytes,
    manifestDigest,
  );

  const expected: ProductMaterializationRow = {
    operation_id: input.operationId,
    run_id: input.runId,
    source: "jquants",
    dataset,
    segment_id: segmentId,
    artifact_key: artifactKey,
    artifact_digest: artifactDigest,
    artifact_body: body,
    row_count: productRows.length,
    byte_count: bytes.byteLength,
    manifest_key: manifestKey,
    manifest_digest: manifestDigest,
    raw_manifest_key: input.capture.rawManifestKey,
    raw_manifest_digest: input.capture.rawManifestDigest,
    raw_page_count: rawPageCount,
    raw_row_count: rawRowCount,
    raw_bytes: rawBytes,
    committed_at: input.checkedAt,
  };
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_product_materializations
     (operation_id,run_id,source,dataset,segment_id,artifact_key,
      artifact_digest,artifact_body,row_count,byte_count,manifest_key,manifest_digest,
      raw_manifest_key,raw_manifest_digest,raw_page_count,raw_row_count,
      raw_bytes,committed_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
  ).bind(...Object.values(expected)).run();
  const stored = await env.DB.prepare(
    `SELECT operation_id,run_id,source,dataset,segment_id,artifact_key,
            artifact_digest,artifact_body,row_count,byte_count,manifest_key,manifest_digest,
            raw_manifest_key,raw_manifest_digest,raw_page_count,raw_row_count,
            raw_bytes,committed_at
       FROM receipt_product_materializations WHERE operation_id=?`,
  ).bind(input.operationId).first<ProductMaterializationRow>();
  if (stored === null || canonicalJson(stored) !== canonicalJson(expected)) {
    throw new Error("product materialization index differs from verified artifact");
  }
  return {
    count: productRows.length,
    digest: artifactDigest,
    artifactKey,
    manifestKey,
  };
}
