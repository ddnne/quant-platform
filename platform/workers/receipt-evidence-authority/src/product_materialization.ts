import { canonicalJson, sha256Digest } from "./canonical";
import {
  capturedOfficialCalendarDescriptor,
  putCreateOnly,
  type Capture,
} from "./raw_capture";
import type { ReceiptAuthorityEnv } from "./types";
import type { ReconciliationScratch } from "./reconciliation_scratch";

export type CanonicalStructuredRow = {
  natural_key: string;
  source: "jquants" | "jsda";
  dataset: string;
  event_time: string;
  available_at: string;
  ingested_at: string;
  payload: string;
  raw_payload: string;
  row_digest: string;
};

type GovernedProductRow = Omit<CanonicalStructuredRow, "row_digest">;

function productSource(dataset: string): "jquants" | "jsda" {
  return dataset.startsWith("jsda_") ? "jsda" : "jquants";
}

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

export async function persistGovernedProductSlice(
  env: ReceiptAuthorityEnv,
  rows: CanonicalStructuredRow[],
): Promise<void> {
  if (rows.length === 0) return;
  const productRows: GovernedProductRow[] = [];
  for (let index = 0; index < rows.length; index += 50) {
    const expected = rows.slice(index, index + 50);
    const insert = env.DB.prepare(
      `INSERT OR IGNORE INTO jquants_records
       (source,dataset,natural_key,event_time,available_at,ingested_at,payload,raw_payload)
       SELECT json_extract(value,'$.source'),json_extract(value,'$.dataset'),
              json_extract(value,'$.natural_key'),json_extract(value,'$.event_time'),
              json_extract(value,'$.available_at'),json_extract(value,'$.ingested_at'),
              json_extract(value,'$.payload'),json_extract(value,'$.raw_payload')
         FROM json_each(?)`,
    ).bind(JSON.stringify(expected));
    const select = env.DB.prepare(
      `SELECT source,dataset,natural_key,event_time,available_at,ingested_at,payload,raw_payload
         FROM jquants_records WHERE source=? AND dataset=?
          AND natural_key IN (${expected.map(() => "?").join(",")})`,
    ).bind(expected[0]!.source, expected[0]!.dataset,
      ...expected.map((row) => row.natural_key));
    const [, result] = await env.DB.batch<GovernedProductRow>([insert, select]);
    if (!result) throw new Error("governed product readback result is absent");
    const stored = new Map(result.results.map((row) => [row.natural_key, row]));
    for (const row of expected) {
      const actual = stored.get(row.natural_key);
      if (!actual || canonicalJson(governedBusinessFields(actual)) !==
          canonicalJson(governedBusinessFields(row)) ||
          !Number.isFinite(Date.parse(actual.ingested_at)) ||
          !Number.isFinite(Date.parse(actual.available_at)) ||
          Date.parse(actual.ingested_at) < Date.parse(actual.available_at) ||
          Date.parse(actual.ingested_at) > Date.parse(row.ingested_at)) {
        throw new Error("governed jquants_records fields differ from canonical raw normalization");
      }
      productRows.push(actual);
    }
  }
  for (let index = 0; index < productRows.length; index += 50) {
    await env.DB.prepare(
      `INSERT OR IGNORE INTO ingestion_change_log
       (table_name,source,dataset,natural_key,event_time,available_at,ingested_at,
        payload,raw_payload,changed_at)
       SELECT 'jquants_records',json_extract(value,'$.source'),json_extract(value,'$.dataset'),
              json_extract(value,'$.natural_key'),json_extract(value,'$.event_time'),
              json_extract(value,'$.available_at'),json_extract(value,'$.ingested_at'),
              json_extract(value,'$.payload'),json_extract(value,'$.raw_payload'),
              json_extract(value,'$.ingested_at') FROM json_each(?)`,
    ).bind(JSON.stringify(productRows.slice(index, index + 50))).run();
  }
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

export async function requireProductObject(
  bucket: R2Bucket, key: string, byteCount: number, digest: string,
): Promise<void> {
  const object = await bucket.get(key);
  if (object === null) throw new Error("product materialization disappeared");
  const hash = new crypto.DigestStream("SHA-256");
  const result = hash.digest.then(digestHex);
  await Promise.all([object.body.pipeTo(hash), result]);
  if (Number(hash.bytesWritten) !== byteCount || await result !== digest) {
    throw new Error("product materialization readback differs from signed bytes");
  }
}

function digestHex(buffer: ArrayBuffer): string {
  return `sha256:${[...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

/**
 * Materialize the actual `jquants_records/v1` product artifact.  The returned
 * digest is the SHA-256 of the exact bytes placed in the authority-owned
 * immutable product prefix; it is not a digest of the reconciliation shadow
 * table.
 */
async function* productPages(
  env: ReceiptAuthorityEnv,
  operationId: string,
): AsyncGenerator<CanonicalStructuredRow[]> {
  let after = "";
  while (true) {
    const page = await env.DB.prepare(
      `SELECT r.natural_key,r.source,r.dataset,r.event_time,r.available_at,
              r.ingested_at,r.payload,r.raw_payload
         FROM receipt_authority_structured_rows s
         JOIN jquants_records r ON r.source=s.source AND r.dataset=s.dataset
          AND r.natural_key=s.natural_key AND r.event_time=s.event_time
          AND r.available_at=s.available_at AND r.payload=s.payload
          AND r.raw_payload=s.raw_payload
        WHERE s.operation_id=? AND s.natural_key>?
          AND EXISTS (
            SELECT 1 FROM ingestion_change_log c
             WHERE c.table_name='jquants_records' AND c.source=r.source
              AND c.dataset=r.dataset AND c.natural_key=r.natural_key
              AND c.event_time=r.event_time AND c.available_at=r.available_at
              AND c.ingested_at=r.ingested_at AND c.payload=r.payload
              AND c.raw_payload=r.raw_payload AND c.changed_at=r.ingested_at
              AND c.change_seq>0
          )
        ORDER BY s.natural_key LIMIT 1000`,
    ).bind(operationId, after).all<CanonicalStructuredRow>();
    const batch = page.results ?? [];
    if (batch.length === 0) break;
    yield batch;
    if (batch.length < 1000) break;
    after = batch.at(-1)!.natural_key;
  }
}

function pageBytes(rows: CanonicalStructuredRow[]): Uint8Array {
  return new TextEncoder().encode(`${rows.map(productLine).join("\n")}\n`);
}

type ProductPages = () => AsyncIterable<CanonicalStructuredRow[]> | Iterable<CanonicalStructuredRow[]>;

async function measureProduct(pages: ProductPages, operationId: string) {
  const hash = new crypto.DigestStream("SHA-256");
  const keys = new crypto.DigestStream("SHA-256");
  const bodyWriter = hash.getWriter();
  const keyWriter = keys.getWriter();
  const encoder = new TextEncoder();
  await keyWriter.write(encoder.encode('{"natural_keys":['));
  let count = 0;
  let byteCount = 0;
  for await (const page of pages()) {
    const bytes = pageBytes(page);
    await bodyWriter.write(bytes);
    byteCount += bytes.byteLength;
    await keyWriter.write(encoder.encode((count ? "," : "") + page.map((row) => JSON.stringify(row.natural_key)).join(",")));
    count += page.length;
  }
  await keyWriter.write(encoder.encode(`],"operation_id":${JSON.stringify(operationId)}}`));
  await Promise.all([bodyWriter.close(), keyWriter.close()]);
  return { count, byteCount, digest: digestHex(await hash.digest),
    naturalKeyDigest: digestHex(await keys.digest) };
}

async function writeProduct(
  env: ReceiptAuthorityEnv, pages: ProductPages, key: string,
  measured: Awaited<ReturnType<typeof measureProduct>>,
  metadata: Record<string, string>,
): Promise<void> {
  // A retry verifies the existing immutable object without rebuilding it.
  if (await env.STRUCTURED_BUCKET.head(key) === null) {
    const stream = new FixedLengthStream(measured.byteCount);
    const writer = stream.writable.getWriter();
    const producing = (async () => {
      try {
        for await (const page of pages()) {
          await writer.write(pageBytes(page));
        }
        await writer.close();
      } catch (error) {
        await writer.abort(error).catch(() => {});
        throw error;
      }
    })();
    // Observe producer failures immediately; R2 errors/conditional conflicts
    // must also unblock a producer waiting on stream backpressure.
    const produced = producing.then(() => null, (error: unknown) => error);
    try {
      const stored = await env.STRUCTURED_BUCKET.put(key, stream.readable, {
        onlyIf: { etagDoesNotMatch: "*" },
        customMetadata: { ...metadata, digest: measured.digest },
      });
      if (stored === null) await writer.abort("immutable object already exists").catch(() => {});
      const error = await produced;
      if (stored !== null && error !== null) throw error;
    } catch (error) {
      await writer.abort(error).catch(() => {});
      await produced;
      throw error;
    }
  }
  await requireProductObject(env.STRUCTURED_BUCKET, key, measured.byteCount, measured.digest);
}

export async function materializeProduct(
  env: ReceiptAuthorityEnv,
  input: {
    operationId: string;
    runId: number;
    capture: Capture;
    expectedCount: number;
    checkedAt: string;
  },
  scratch?: ReconciliationScratch,
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
  if (!Number.isSafeInteger(input.expectedCount) || input.expectedCount < 1) {
    throw new Error("empty product materialization cannot be signed");
  }
  const pages: ProductPages = scratch === undefined
    ? () => productPages(env, input.operationId)
    : () => scratch.pages(input.operationId);
  const assembled = await measureProduct(pages, input.operationId);
  if (assembled.count !== input.expectedCount) {
    throw new Error("product materialization row count differs from raw evidence");
  }
  const artifactDigest = assembled.digest;
  const dataset = input.capture.initialRequest.dataset_id;
  const segmentId = input.capture.initialRequest.segment_id;
  const prefix =
    `product/receipt-authority/${env.ENVIRONMENT}/${dataset}/${segmentId}/run-${input.runId}`;
  const artifactKey = `${prefix}-${input.operationId.slice(7, 23)}.jsonl`;
  await writeProduct(
    env,
    pages,
    artifactKey,
    assembled,
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

  const rawPageCount = input.capture.pages.length;
  const rawRowCount = input.capture.pages.reduce(
    (total, page) => total + page.rowCount,
    0,
  );
  const rawBytes = input.capture.pages.reduce(
    (total, page) => total + page.size,
    0,
  );
  // A pre-upgrade operation may have committed its v1 index before signing.
  // Preserve that immutable manifest rather than trying to replace it with v2.
  const prior = await env.DB.prepare(
    "SELECT * FROM receipt_product_materializations WHERE operation_id=?",
  ).bind(input.operationId).first<ProductMaterializationRow>();
  if (prior !== null) {
    if (prior.run_id !== input.runId || prior.source !== productSource(dataset) ||
        prior.dataset !== dataset || prior.segment_id !== segmentId ||
        prior.artifact_key !== artifactKey || prior.artifact_digest !== artifactDigest ||
        prior.row_count !== assembled.count || prior.byte_count !== assembled.byteCount ||
        prior.raw_manifest_key !== input.capture.rawManifestKey ||
        prior.raw_manifest_digest !== input.capture.rawManifestDigest ||
        prior.raw_page_count !== rawPageCount || prior.raw_row_count !== rawRowCount ||
        prior.raw_bytes !== rawBytes || prior.committed_at !== input.checkedAt ||
        (prior.artifact_body !== "" && await sha256Digest(prior.artifact_body) !== artifactDigest)) {
      throw new Error("product materialization index differs from verified artifact");
    }
    const priorManifest = await env.AUTHORITY_EVIDENCE_BUCKET.head(prior.manifest_key);
    if (priorManifest === null) throw new Error("product materialization disappeared");
    await requireProductObject(env.AUTHORITY_EVIDENCE_BUCKET, prior.manifest_key,
      priorManifest.size, prior.manifest_digest);
    return {
      count: assembled.count, digest: artifactDigest, artifactKey,
      artifactByteCount: assembled.byteCount, manifestKey: prior.manifest_key,
      manifestByteCount: priorManifest.size, manifestDigest: prior.manifest_digest,
      naturalKeyDigest: assembled.naturalKeyDigest,
    };
  }
  const manifest = {
    schema_version: "receipt-product-materialization/v2",
    product_schema: "jquants_records/v1",
    operation_id: input.operationId,
    run_id: input.runId,
    source: productSource(dataset),
    dataset,
    segment_id: segmentId,
    artifact_key: artifactKey,
    artifact_digest: artifactDigest,
    structured_digest: artifactDigest,
    row_count: assembled.count,
    byte_count: assembled.byteCount,
    raw_manifest_key: input.capture.rawManifestKey,
    raw_manifest_digest: input.capture.rawManifestDigest,
    raw_page_count: rawPageCount,
    raw_row_count: rawRowCount,
    raw_bytes: rawBytes,
    official_calendar_evidence: capturedOfficialCalendarDescriptor(
      input.capture.officialCalendarEvidence,
    ),
    committed_at: input.checkedAt,
  };
  const manifestJson = canonicalJson(manifest);
  const manifestBytes = new TextEncoder().encode(manifestJson);
  const manifestDigest = await sha256Digest(manifestBytes);
  const manifestKey = `${prefix}-${input.operationId.slice(7, 23)}.manifest.v2.json`;
  await putCreateOnly(
    env.AUTHORITY_EVIDENCE_BUCKET,
    manifestKey,
    manifestBytes,
    {
      schema: "receipt-product-materialization/v2",
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
    source: productSource(dataset),
    dataset,
    segment_id: segmentId,
    artifact_key: artifactKey,
    artifact_digest: artifactDigest,
    artifact_body: "",
    row_count: assembled.count,
    byte_count: assembled.byteCount,
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
    count: assembled.count,
    digest: artifactDigest,
    artifactKey,
    artifactByteCount: assembled.byteCount,
    manifestKey,
    manifestByteCount: manifestBytes.byteLength,
    manifestDigest,
    naturalKeyDigest: assembled.naturalKeyDigest,
  };
}
