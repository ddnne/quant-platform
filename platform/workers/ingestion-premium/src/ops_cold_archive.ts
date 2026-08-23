/**
 * Archive cold jquants_records rows to R2 then DELETE from D1.
 * CPU-bounded: small batches (default 200, hard max 400), cursor pagination
 * via after_rowid, single R2 put per request, raw_payload dropped from body.
 * Never touches coverage_segments / collection_receipts / raw_retention_manifests.
 *
 * Source: GLM_ARCHIVE_FIX_OK (import adjusted to named export).
 */

import { r2DatasetSegment } from "./write_path_config";

export interface ArchiveEnv {
  DB: D1Database;
  STRUCTURED_BUCKET: R2Bucket;
  INGESTION_RUN_TOKEN?: string;
}

export async function handleArchiveCold(
  request: Request,
  env: ArchiveEnv,
): Promise<Response> {
  if (request.method !== "POST") {
    return Response.json({ error: "POST required" }, { status: 405 });
  }

  const url = new URL(request.url);

  const token = request.headers.get("X-Ingestion-Token");
  if (!env.INGESTION_RUN_TOKEN || !token || token !== env.INGESTION_RUN_TOKEN) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const dataset = url.searchParams.get("dataset");
  if (!dataset) {
    return Response.json({ error: "dataset is required" }, { status: 400 });
  }

  const before = url.searchParams.get("before");
  if (!before || !/^\d{4}-\d{2}-\d{2}$/.test(before)) {
    return Response.json(
      { error: "before must be YYYY-MM-DD" },
      { status: 400 },
    );
  }

  // meta mode: skip payload (raw still on quant-raw). Allows larger batches.
  const mode = url.searchParams.get("mode") || "full";
  const metaOnly = mode === "meta";
  let limit = parseInt(
    url.searchParams.get("limit") || (metaOnly ? "2000" : "200"),
    10,
  );
  if (!Number.isFinite(limit) || limit <= 0) limit = metaOnly ? 2000 : 200;
  const hardMax = metaOnly ? 5000 : 400;
  if (limit > hardMax) limit = hardMax;

  let afterRowid = 0;
  const afterRowidRaw = url.searchParams.get("after_rowid");
  if (afterRowidRaw !== null) {
    const parsed = parseInt(afterRowidRaw, 10);
    if (Number.isFinite(parsed) && parsed >= 0) afterRowid = parsed;
  }

  let untilRowid = Number.MAX_SAFE_INTEGER;
  const untilRaw = url.searchParams.get("until_rowid");
  if (untilRaw !== null) {
    const parsed = parseInt(untilRaw, 10);
    if (Number.isFinite(parsed) && parsed > 0) untilRowid = parsed;
  }

  const runId = crypto.randomUUID();
  const seg = r2DatasetSegment(dataset);

  const selectSql = metaOnly
    ? `SELECT rowid AS rid, source, dataset, natural_key, event_time, available_at, ingested_at
         FROM jquants_records
        WHERE dataset = ?
          AND rowid > ?
          AND rowid <= ?
          AND substr(event_time, 1, 10) < ?
        ORDER BY rowid
        LIMIT ?`
    : `SELECT rowid AS rid, source, dataset, natural_key, event_time, available_at, ingested_at, payload
         FROM jquants_records
        WHERE dataset = ?
          AND rowid > ?
          AND rowid <= ?
          AND substr(event_time, 1, 10) < ?
        ORDER BY rowid
        LIMIT ?`;

  const { results } = await env.DB.prepare(selectSql)
    .bind(dataset, afterRowid, untilRowid, before, limit)
    .all();

  const r2Key =
    `archive/jquants_records/${seg}/batch/${runId}_after${afterRowid}${metaOnly ? "_meta" : ""}.ndjson`;

  if (!results || results.length === 0) {
    return Response.json({
      archived: 0,
      deleted: 0,
      next_rowid: afterRowid,
      done: true,
      r2_key: r2Key,
      sha256: null,
      run_id: runId,
      mode: metaOnly ? "meta" : "full",
    });
  }

  const rows = results as Array<{
    rid: number;
    source: string;
    dataset: string;
    natural_key: string;
    event_time: string | null;
    available_at: string | null;
    ingested_at: string | null;
    payload?: unknown;
  }>;

  const ndjson =
    rows
      .map((r) =>
        JSON.stringify(
          metaOnly
            ? {
                rid: r.rid,
                source: r.source,
                dataset: r.dataset,
                natural_key: r.natural_key,
                event_time: r.event_time,
                available_at: r.available_at,
                ingested_at: r.ingested_at,
              }
            : {
                rid: r.rid,
                source: r.source,
                dataset: r.dataset,
                natural_key: r.natural_key,
                event_time: r.event_time,
                available_at: r.available_at,
                ingested_at: r.ingested_at,
                payload: r.payload,
              },
        ),
      )
      .join("\n") + "\n";
  const ndjsonBytes = new TextEncoder().encode(ndjson);

  const digestBuf = await crypto.subtle.digest("SHA-256", ndjsonBytes);
  const digestBytes = new Uint8Array(digestBuf);
  const sha256 = Array.from(digestBytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  await env.STRUCTURED_BUCKET.put(r2Key, ndjsonBytes, {
    httpMetadata: { contentType: "application/x-ndjson" },
    customMetadata: {
      dataset,
      sha256,
      run_id: runId,
      before,
      count: String(rows.length),
      mode: metaOnly ? "meta" : "full",
    },
  });

  const rowids = rows.map((r) => r.rid);
  let deleted = 0;
  for (let i = 0; i < rowids.length; i += 100) {
    const chunk = rowids.slice(i, i + 100);
    const placeholders = chunk.map(() => "?").join(",");
    const del = await env.DB.prepare(
      `DELETE FROM jquants_records WHERE rowid IN (${placeholders})`,
    )
      .bind(...chunk)
      .run();
    deleted += (del.meta?.changes ?? 0) as number;
  }

  const lastRid = rowids[rowids.length - 1]!;
  return Response.json({
    archived: rows.length,
    deleted,
    next_rowid: lastRid,
    done: rows.length < limit,
    r2_key: r2Key,
    sha256,
    run_id: runId,
    mode: metaOnly ? "meta" : "full",
  });
}
