/**
 * HTTP presentation for /v1/export/d1 and /v1/export/changes.
 * DATA_EXPORT_TOKEN via X-Ingestion-Token; not ingest.
 */

import { json } from "./http_json";
import { ingestionTokenMatches } from "./ingestion_token";
import { requireNaturalKeysV2Ready } from "./natural_key_migration";

export type ExportEnv = Pick<Cloudflare.Env, "DB"> & {
  DATA_EXPORT_TOKEN?: string;
};

export async function handleExportD1(
  env: ExportEnv, request: Request,
): Promise<Response> {
  if (request.method !== "GET") {
    return json({ error: "GET required" }, 405);
  }
  if (!(await ingestionTokenMatches(request, env.DATA_EXPORT_TOKEN))) {
    return json({ error: "unauthorized" }, 401);
  }
  const url = new URL(request.url);
  const table = url.searchParams.get("table") || "jquants_records";
  const allowed = new Set([
    "jquants_records", "jquants_listed_info", "jquants_daily_bars",
    "jquants_market_calendar",
    "jquants_records_revisions", "jquants_listed_info_revisions",
    "jquants_daily_bars_revisions", "jquants_market_calendar_revisions",
    "ingestion_validation", "ingestion_run_log", "ingestion_watermarks",
    "raw_retention_manifests", "coverage_segments", "collection_receipts",
  ]);
  if (!allowed.has(table)) {
    return json({ error: "table not exportable" }, 400);
  }
  const limitRaw = Number(url.searchParams.get("limit") || "500");
  const cursorRaw = Number(url.searchParams.get("cursor") || "0");
  if (!Number.isInteger(limitRaw) || limitRaw < 1 || limitRaw > 1000) {
    return json({ error: "limit must be an integer between 1 and 1000" }, 400);
  }
  if (!Number.isInteger(cursorRaw) || cursorRaw < 0) {
    return json({ error: "cursor must be a non-negative integer" }, 400);
  }
  await requireNaturalKeysV2Ready(env.DB);

  const r = await env.DB.prepare(
    `SELECT rowid AS __export_cursor, * FROM ${table}
     WHERE rowid > ? ORDER BY rowid LIMIT ?`,
  ).bind(cursorRaw, limitRaw + 1).all();
  const fetched = (r.results ?? []) as Record<string, unknown>[];
  const hasMore = fetched.length > limitRaw;
  const page = fetched.slice(0, limitRaw);
  const nextCursor = page.length > 0
    ? Number(page[page.length - 1].__export_cursor)
    : null;
  const rows = page.map((row) => {
    const clean = { ...row };
    delete clean.__export_cursor;
    return clean;
  });
  return json({
    table,
    rows,
    cursor: cursorRaw,
    next_cursor: hasMore ? nextCursor : null,
    has_more: hasMore,
    limit: limitRaw,
  });
}

export async function handleExportChanges(
  env: ExportEnv, request: Request,
): Promise<Response> {
  if (request.method !== "GET") {
    return json({ error: "GET required" }, 405);
  }
  if (!(await ingestionTokenMatches(request, env.DATA_EXPORT_TOKEN))) {
    return json({ error: "unauthorized" }, 401);
  }
  const url = new URL(request.url);
  const afterSeq = Number(url.searchParams.get("after_seq") || "0");
  const limit = Number(url.searchParams.get("limit") || "500");
  if (!Number.isSafeInteger(afterSeq) || afterSeq < 0) {
    return json({ error: "after_seq must be a non-negative safe integer" }, 400);
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 1000) {
    return json({ error: "limit must be an integer between 1 and 1000" }, 400);
  }
  await requireNaturalKeysV2Ready(env.DB);

  const result = await env.DB.prepare(
    `SELECT change_seq, table_name, source, dataset, natural_key, event_time,
            available_at, ingested_at, payload, raw_payload
     FROM ingestion_change_log
     WHERE change_seq > ?
     ORDER BY change_seq
     LIMIT ?`,
  ).bind(afterSeq, limit + 1).all();
  const fetched = (result.results ?? []) as Record<string, unknown>[];
  const hasMore = fetched.length > limit;
  const rows = fetched.slice(0, limit);
  const nextSeq = rows.length > 0
    ? Number(rows[rows.length - 1].change_seq)
    : afterSeq;
  return json({
    format: "jquants-change-feed/v1",
    after_seq: afterSeq,
    rows,
    next_seq: nextSeq,
    has_more: hasMore,
    limit,
  });
}

/** /v1/export/* dispatch. Unknown export paths return null. */
export async function handleExportPaths(
  request: Request,
  env: ExportEnv,
): Promise<Response | null> {
  const url = new URL(request.url);
  if (url.pathname === "/v1/export/d1") return handleExportD1(env, request);
  if (url.pathname === "/v1/export/changes") {
    return handleExportChanges(env, request);
  }
  return null;
}
