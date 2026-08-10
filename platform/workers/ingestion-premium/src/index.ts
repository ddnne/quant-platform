/// <reference types="@cloudflare/workers-types" />
/**
 * Phase 3.5 — J-Quants Premium **core** ingestion closed loop on Cloudflare.
 *
 * Closed-loop contract (Phase 3.5 handoff):
 *   1. Scheduled run on CF (Workers Cron → `scheduled`).
 *   2. Secrets only on CF (same names: `JQUANTS_API_KEY`, optional
 *      `INGESTION_PROXY_TOKEN` to gate `/v1/run`). Key is never logged.
 *   3. Persist R2 raw + D1 structured (R2 + D1 bindings).
 *   4. Incremental primary; backfill separable (date params on `/v1/run`).
 *   5. Auto validation with explicit pass/fail per dataset.
 *   6. Failures not treated as success — a dataset that errors is recorded
 *      with `status='fail'` and surfaces in `/health` + the run summary.
 *   7. Local-readable path — the paginated `/v1/export/d1` endpoint exposes
 *      D1 structured tables so `scripts/sync_d1_to_sqlite.py` can build a
 *      local PIT DB.
 *   8. Required datasets: see `catalog.ts` (mirrors Python
 *      `PREMIUM_CORE_DATASETS`).
 *
 * Endpoints:
 *   GET  /health                        — readiness + last-run summary
 *   POST /v1/run[?dataset=..&from=..&to=..]  — manual trigger (auth gated)
 *   GET  /v1/export/d1?table=..&cursor=..&limit=.. — JSON page of a D1 table
 *                                                    (auth gated)
 */

import { PREMIUM_CORE_DATASETS, isPremiumCore, datasetById, type DatasetSpec } from "./catalog";

export interface Env {
  JQUANTS_API_KEY: string;
  INGESTION_PROXY_TOKEN?: string;
  RAW_BUCKET: R2Bucket;
  STRUCTURED_BUCKET: R2Bucket;
  DB: D1Database;
}

const JQ_BASE = "https://api.jquants.com";
const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

// Persistent run-state keys (KV would be cleaner, but D1 is already here).
const STATE_LAST_RUN = "last_run_summary";

// ---------------------------------------------------------------------------
// time helpers (JST = UTC+9)
// ---------------------------------------------------------------------------

function toJstIso(d: Date): string {
  const ms = d.getTime() + JST_OFFSET_MS;
  const jst = new Date(ms);
  return jst.toISOString().replace(/\.(\d+)Z$/, "+09:00");
}

function todayJst(): string {
  return toJstIso(new Date()).slice(0, 10);
}

function daysAgoJst(n: number): string {
  const t = new Date(Date.now() - n * 24 * 60 * 60 * 1000);
  return toJstIso(t).slice(0, 10);
}

function inclusiveDates(from: string, to: string): string[] {
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  if (!datePattern.test(from) || !datePattern.test(to)) {
    throw new Error("from/to must be YYYY-MM-DD");
  }
  const start = new Date(`${from}T00:00:00Z`);
  const end = new Date(`${to}T00:00:00Z`);
  if (
    Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) ||
    start.toISOString().slice(0, 10) !== from ||
    end.toISOString().slice(0, 10) !== to
  ) {
    throw new Error("from/to must be valid calendar dates");
  }
  if (start > end) throw new Error("from must be on or before to");

  const dates: string[] = [];
  for (let cursor = start; cursor <= end; cursor = new Date(cursor.getTime() + 86_400_000)) {
    dates.push(cursor.toISOString().slice(0, 10));
  }
  return dates;
}

function requestQueries(
  spec: DatasetSpec,
  opts: { from?: string; to?: string; today?: string },
): Record<string, string>[] {
  if (spec.dateMode === "none") return [{}];

  if (spec.dateMode === "today") {
    if (opts.from || opts.to) {
      const from = opts.from || opts.to!;
      const to = opts.to || opts.from!;
      return inclusiveDates(from, to).map((date) => ({ date }));
    }
    return [{ date: opts.today || todayJst() }];
  }

  const from = opts.from || (opts.to ? opts.to : daysAgoJst(5));
  const to = opts.to || todayJst();
  if (from > to) throw new Error("from must be on or before to");
  return [{ from, to }];
}

// ---------------------------------------------------------------------------
// R2 raw path layout: raw/{dataset}/{yyyy}/{mm}/{dd}/{stamp}.json
// ---------------------------------------------------------------------------

function rawR2Key(dataset: string, when: Date): string {
  const jst = new Date(when.getTime() + JST_OFFSET_MS);
  const yyyy = jst.toISOString().slice(0, 4);
  const mm = jst.toISOString().slice(5, 7);
  const dd = jst.toISOString().slice(8, 10);
  const stamp = jst.toISOString().replace(/[-:]/g, "").slice(0, 15);
  return `raw/${dataset}/${yyyy}/${mm}/${dd}/${stamp}.json`;
}

// ---------------------------------------------------------------------------
// fetch one dataset (paginated)
// ---------------------------------------------------------------------------

interface FetchOutcome {
  rows: Record<string, unknown>[];
  rawBytes: number;
  paginationErrors: number;
  httpStatus: number;
  error: string;
}

async function fetchDataset(
  env: Env,
  spec: DatasetSpec,
  opts: { from?: string; to?: string; today?: string },
  fetchImpl: typeof fetch
): Promise<FetchOutcome> {
  const out: FetchOutcome = {
    rows: [],
    rawBytes: 0,
    paginationErrors: 0,
    httpStatus: 0,
    error: "",
  };
  if (!env.JQUANTS_API_KEY) {
    out.error = "JQUANTS_API_KEY not bound on worker";
    return out;
  }

  let queries: Record<string, string>[];
  try {
    queries = requestQueries(spec, opts);
  } catch (e) {
    out.error = `invalid date range: ${(e as Error).message}`;
    return out;
  }

  const path = spec.bulk === "bulk" && spec.bulkPath ? spec.bulkPath : spec.path;
  for (const baseQuery of queries) {
    let pagination: string | null = null;
    for (let page = 0; page < 200; page++) {
      const params = new URLSearchParams(baseQuery);
      if (pagination) params.set("pagination_key", pagination);
      const suffix = params.size > 0 ? `?${params.toString()}` : "";
      const url = JQ_BASE + path + suffix;
      let resp: Response;
      try {
        resp = await fetchImpl(url, {
          method: "GET",
          headers: { "x-api-key": env.JQUANTS_API_KEY },
        });
      } catch (e) {
        out.error = `transport: ${(e as Error).message}`;
        return out;
      }
      out.httpStatus = resp.status;
      if (resp.status === 429 || resp.status >= 500) {
        out.error = `transient HTTP ${resp.status}`;
        return out;
      }
      if (!resp.ok) {
        out.error = `HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`;
        return out;
      }
      const text = await resp.text();
      out.rawBytes += text.length;
      let parsed: any;
      try {
        parsed = JSON.parse(text);
      } catch (e) {
        out.error = `invalid json: ${(e as Error).message}`;
        return out;
      }
      const rows = Array.isArray(parsed?.data) ? parsed.data : [];
      out.rows.push(...rows);
      const next = parsed?.pagination_key || parsed?.pagination_token;
      if (!next) break;
      if (page === 199) {
        out.paginationErrors++;
        out.error = "pagination exceeded 200 pages";
        return out;
      }
      pagination = String(next);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// natural key + structured insert (mirrors ingestion/jquants/normalize.py)
// ---------------------------------------------------------------------------

const KEY_FIELDS = [
  "Code", "Date", "DateTime", "Time", "DisclosedDate", "AnnouncementDate",
  "DiscDate", "DiscNo",
];

function naturalKey(row: Record<string, unknown>, spec: DatasetSpec): string {
  const picked: Record<string, unknown> = {};
  for (const k of KEY_FIELDS) {
    if (row[k] !== undefined && row[k] !== null && row[k] !== "") {
      picked[k] = row[k];
    }
  }
  if (Object.keys(picked).length === 0) {
    // Fallback: stable JSON hash of the whole row.
    const stable = stableJson(row);
    return `hash:${stable.slice(0, 60)}`;
  }
  return JSON.stringify(picked);
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  const object = value as Record<string, unknown>;
  return `{${Object.keys(object).sort().map(
    (key) => `${JSON.stringify(key)}:${stableJson(object[key])}`,
  ).join(",")}}`;
}

function pickEventTime(row: Record<string, unknown>, spec: DatasetSpec): string | null {
  // Event time candidate fields in priority order.
  const candidates = [
    "DateTime", "Date", "DisclosedDate", "AnnouncementDate", "DiscDate",
  ];
  for (const k of candidates) {
    const v = row[k];
    if (typeof v === "string" && v.length > 0) {
      // Treat bare dates as 09:00 JST event_time.
      if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return `${v}T09:00:00+09:00`;
      return v;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// persistence: R2 raw + D1 structured
// ---------------------------------------------------------------------------

interface DatasetResult {
  dataset: string;
  status: "pass" | "fail";
  startedAt: string;
  finishedAt: string;
  rowsSeen: number;
  rowsInserted: number;
  rowsRevisions: number;
  availableAtMin: string | null;
  availableAtMax: string | null;
  detail: string;
  rawKey: string | null;
  rawBytes: number;
}

async function ingestOne(
  env: Env,
  spec: DatasetSpec,
  opts: { from?: string; to?: string; today?: string },
  fetchImpl: typeof fetch,
  runId: number | null,
): Promise<DatasetResult> {
  const startedAt = toJstIso(new Date());
  const outcome = await fetchDataset(env, spec, opts, fetchImpl);

  if (outcome.error) {
    const finishedAt = toJstIso(new Date());
    const res: DatasetResult = {
      dataset: spec.id, status: "fail",
      startedAt, finishedAt,
      rowsSeen: outcome.rows.length, rowsInserted: 0, rowsRevisions: 0,
      availableAtMin: null, availableAtMax: null,
      detail: outcome.error, rawKey: null, rawBytes: outcome.rawBytes,
    };
    if (runId !== null) {
      await writeValidation(env, runId, res);
    }
    return res;
  }

  // Raw to R2 (even on empty result, so the run is auditable; only skip on
  // rows=-and-rawBytes=0 which is impossible here because we got ok HTTP).
  const when = new Date();
  const rawKey = rawR2Key(spec.id, when);
  const rawBody = JSON.stringify({
    fetched_at: toJstIso(when),
    dataset: spec.id,
    path: spec.bulk === "bulk" && spec.bulkPath ? spec.bulkPath : spec.path,
    params: opts,
    http_status: outcome.httpStatus,
    rows: outcome.rows.length,
    data: outcome.rows,
  });
  await env.RAW_BUCKET.put(rawKey, rawBody);

  // Structured to D1 (generic table for all datasets; specialized tables
  // are not used on CF — the local sync script reads the generic table).
  const inserted = await upsertRecords(env, spec, outcome.rows, when);
  const availableBounds = await selectAvailableBounds(env, spec.id);

  const finishedAt = toJstIso(new Date());
  const res: DatasetResult = {
    dataset: spec.id,
    status: "pass",
    startedAt, finishedAt,
    rowsSeen: outcome.rows.length,
    rowsInserted: inserted.inserted,
    rowsRevisions: inserted.revisions,
    availableAtMin: availableBounds.min,
    availableAtMax: availableBounds.max,
    detail: `raw=${rawKey}`,
    rawKey,
    rawBytes: outcome.rawBytes,
  };
  if (runId !== null) {
    await writeValidation(env, runId, res);
  }
  return res;
}

interface UpsertSummary { inserted: number; revisions: number; }

interface StructuredRecord {
  source: string;
  dataset: string;
  naturalKey: string;
  eventTime: string;
  availableAt: string;
  ingestedAt: string;
  payload: string;
  rawPayload: string;
}

function recordBinds(records: StructuredRecord[]): unknown[] {
  return records.flatMap((record) => [
    record.source,
    record.dataset,
    record.naturalKey,
    record.eventTime,
    record.availableAt,
    record.ingestedAt,
    record.payload,
    record.rawPayload,
  ]);
}

async function upsertRecords(
  env: Env,
  spec: DatasetSpec,
  rows: Record<string, unknown>[],
  when: Date,
): Promise<UpsertSummary> {
  if (rows.length === 0) return { inserted: 0, revisions: 0 };
  const ingestedAt = toJstIso(when);
  // De-duplicate a response by business key, retaining its last occurrence.
  // available_at is row-level if present, else fetch time (PIT-safe: the row
  // was unknowable before it arrived).
  const byKey = new Map<string, StructuredRecord>();
  for (const row of rows) {
    const nk = naturalKey(row, spec);
    const ev = pickEventTime(row, spec);
    const availableAt =
      typeof row["available_at"] === "string"
        ? (row["available_at"] as string)
        : ingestedAt;
    // Stable key ordering makes payload comparison semantic rather than
    // dependent on JSON object property order. The generated PIT timestamps
    // are separate columns, so an hourly re-fetch does not look amended.
    const payload = stableJson(row);
    byKey.set(nk, {
      source: "jquants",
      dataset: spec.id,
      naturalKey: nk,
      eventTime: ev || availableAt,
      availableAt,
      ingestedAt,
      payload,
      rawPayload: JSON.stringify(row),
    });
  }
  const records = [...byKey.values()];

  // D1 permits at most 100 bound parameters per statement. Each record has
  // eight fields, so a VALUES statement can contain at most floor(100/8)=12.
  const CHUNK = Math.floor(100 / 8);
  let inserted = 0;
  let revisions = 0;
  for (let i = 0; i < records.length; i += CHUNK) {
    const chunk = records.slice(i, i + CHUNK);
    const placeholders = chunk.map(() => "(?, ?, ?, ?, ?, ?, ?, ?)").join(", ");
    const binds = recordBinds(chunk);

    const existing = await env.DB.prepare(
      `SELECT natural_key FROM jquants_records
       WHERE source = ? AND dataset = ?
         AND natural_key IN (${chunk.map(() => "?").join(", ")})`,
    ).bind("jquants", spec.id, ...chunk.map((record) => record.naturalKey)).all();
    inserted += chunk.length - (existing.results?.length ?? 0);

    // Archive only a displaced primary whose stable source payload changed.
    // The archive + primary upsert run atomically as one D1 batch.
    const archiveSql =
      `WITH incoming
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       AS (VALUES ${placeholders})
       INSERT OR IGNORE INTO jquants_records_revisions
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       SELECT current.source, current.dataset, current.natural_key,
              current.event_time, current.available_at, current.ingested_at,
              current.payload, current.raw_payload
       FROM jquants_records AS current
       JOIN incoming
         ON current.source = incoming.source
        AND current.dataset = incoming.dataset
        AND current.natural_key = incoming.natural_key
       WHERE current.payload IS NOT incoming.payload`;
    const upsertSql =
      `INSERT INTO jquants_records
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       VALUES ${placeholders}
       ON CONFLICT(source, dataset, natural_key) DO UPDATE SET
         event_time = CASE
           WHEN jquants_records.payload IS excluded.payload THEN jquants_records.event_time
           ELSE excluded.event_time END,
         available_at = CASE
           WHEN jquants_records.payload IS excluded.payload
             THEN MIN(jquants_records.available_at, excluded.available_at)
           ELSE excluded.available_at END,
         ingested_at = excluded.ingested_at,
         payload = CASE
           WHEN jquants_records.payload IS excluded.payload THEN jquants_records.payload
           ELSE excluded.payload END,
         raw_payload = CASE
           WHEN jquants_records.payload IS excluded.payload THEN jquants_records.raw_payload
           ELSE excluded.raw_payload END`;
    const batch = await env.DB.batch([
      env.DB.prepare(archiveSql).bind(...binds),
      env.DB.prepare(upsertSql).bind(...binds),
    ]);
    revisions += (batch[0]?.meta?.changes ?? 0) as number;
  }

  return { inserted, revisions };
}

async function selectAvailableBounds(
  env: Env, dataset: string,
): Promise<{ min: string | null; max: string | null }> {
  const r = await env.DB.prepare(
    `SELECT MIN(available_at) AS mn, MAX(available_at) AS mx
     FROM jquants_records WHERE dataset = ?`,
  ).bind(dataset).first();
  return { min: (r?.mn as string) ?? null, max: (r?.mx as string) ?? null };
}

async function writeValidation(env: Env, runId: number, res: DatasetResult): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO ingestion_validation
     (run_id, dataset, started_at, finished_at, status, rows_seen, rows_inserted,
      rows_revisions, available_at_min, available_at_max, detail)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(
    runId, res.dataset, res.startedAt, res.finishedAt, res.status,
    res.rowsSeen, res.rowsInserted, res.rowsRevisions,
    res.availableAtMin, res.availableAtMax, res.detail,
  ).run();
}

// ---------------------------------------------------------------------------
// run summary persistence (last-run blob for /health)
// ---------------------------------------------------------------------------

export interface RunSummary {
  startedAt: string;
  finishedAt: string;
  status: "pass" | "fail" | "partial";
  datasetCount: number;
  passed: number;
  failed: number;
  rowsInserted: number;
  rawBytes: number;
  triggeredBy: "cron" | "manual";
  failures: { dataset: string; detail: string }[];
}

async function persistSummary(env: Env, summary: RunSummary): Promise<void> {
  // We persist by overwriting a fixed id so /health only sees the latest.
  await env.DB.prepare(
    `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
     VALUES (?, 'jquants', 'cloudflare', ?, ?)`,
  ).bind(
    summary.startedAt,
    summary.status,
    JSON.stringify(summary).slice(0, 8000),
  ).run();
}

async function lastRunSummary(env: Env): Promise<RunSummary | null> {
  const r = await env.DB.prepare(
    `SELECT detail FROM ingestion_run_log
     WHERE source='jquants' AND runtime='cloudflare'
     ORDER BY id DESC LIMIT 1`,
  ).first();
  if (!r?.detail) return null;
  try {
    return JSON.parse(r.detail as string) as RunSummary;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// run all (or one) dataset
// ---------------------------------------------------------------------------

async function runIngestion(
  env: Env,
  opts: { from?: string; to?: string; today?: string; dataset?: string },
  triggeredBy: "cron" | "manual",
  fetchImpl: typeof fetch,
): Promise<RunSummary> {
  const startedAt = toJstIso(new Date());

  // Start a run row so validation rows can FK to it.
  const ins = await env.DB.prepare(
    `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
     VALUES (?, 'jquants', 'cloudflare', 'running', ?)`,
  ).bind(startedAt, JSON.stringify({ triggeredBy, opts })).run();
  const runId = (ins.meta?.last_row_id ?? null) as number | null;

  const specs: DatasetSpec[] = opts.dataset
    ? (isPremiumCore(opts.dataset) ? [datasetById(opts.dataset)!] : [])
    : PREMIUM_CORE_DATASETS;

  const failures: { dataset: string; detail: string }[] = [];
  let passed = 0;
  let failed = 0;
  let rowsInserted = 0;
  let rawBytes = 0;

  if (specs.length === 0) {
    const finishedAt = toJstIso(new Date());
    const dataset = opts.dataset || "<none>";
    const detail = opts.dataset
      ? `unknown or out-of-scope dataset: ${opts.dataset}`
      : "no datasets selected";
    const result: DatasetResult = {
      dataset,
      status: "fail",
      startedAt,
      finishedAt,
      rowsSeen: 0,
      rowsInserted: 0,
      rowsRevisions: 0,
      availableAtMin: null,
      availableAtMax: null,
      detail,
      rawKey: null,
      rawBytes: 0,
    };
    failed = 1;
    failures.push({ dataset, detail });
    if (runId !== null) await writeValidation(env, runId, result);
  }

  for (const spec of specs) {
    const datasetStartedAt = toJstIso(new Date());
    let res: DatasetResult;
    try {
      res = await ingestOne(env, spec, opts, fetchImpl, runId);
    } catch (e) {
      const detail = `ingest exception: ${(e as Error).message || String(e)}`;
      res = {
        dataset: spec.id,
        status: "fail",
        startedAt: datasetStartedAt,
        finishedAt: toJstIso(new Date()),
        rowsSeen: 0,
        rowsInserted: 0,
        rowsRevisions: 0,
        availableAtMin: null,
        availableAtMax: null,
        detail,
        rawKey: null,
        rawBytes: 0,
      };
      if (runId !== null) {
        try {
          await writeValidation(env, runId, res);
        } catch (validationError) {
          res.detail += `; validation write failed: ${(validationError as Error).message}`;
        }
      }
    }
    if (res.status === "pass") {
      passed++;
    } else {
      failed++;
      failures.push({ dataset: res.dataset, detail: res.detail });
    }
    rowsInserted += res.rowsInserted;
    rawBytes += res.rawBytes;
  }

  const finishedAt = toJstIso(new Date());
  const status: RunSummary["status"] =
    specs.length === 0 || passed === 0 ? "fail" : failed === 0 ? "pass" : "partial";
  const summary: RunSummary = {
    startedAt, finishedAt, status,
    datasetCount: specs.length,
    passed, failed, rowsInserted, rawBytes,
    triggeredBy,
    failures,
  };

  // Update the run row with the final status.
  if (runId !== null) {
    await env.DB.prepare(
      `UPDATE ingestion_run_log SET status = ?, detail = ? WHERE id = ?`,
    ).bind(status, JSON.stringify(summary).slice(0, 8000), runId).run();
  }

  return summary;
}

// ---------------------------------------------------------------------------
// HTTP entrypoints
// ---------------------------------------------------------------------------

function authorized(request: Request, env: Env, requireToken: boolean): boolean {
  if (!requireToken) return true;
  if (!env.INGESTION_PROXY_TOKEN) return false;
  const got = request.headers.get("X-Ingestion-Token") || "";
  return got === env.INGESTION_PROXY_TOKEN;
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

async function handleHealth(env: Env): Promise<Response> {
  const last = await lastRunSummary(env);
  const hasKey = Boolean(env.JQUANTS_API_KEY);
  return json({
    ok: hasKey,
    has_jquants_key: hasKey,
    datasets: PREMIUM_CORE_DATASETS.length,
    last_run: last,
  });
}

async function handleRun(
  env: Env, request: Request, fetchImpl: typeof fetch,
): Promise<Response> {
  if (!authorized(request, env, true)) {
    return json({ error: "unauthorized" }, 401);
  }
  const url = new URL(request.url);
  const opts = {
    from: url.searchParams.get("from") || undefined,
    to: url.searchParams.get("to") || undefined,
    today: url.searchParams.get("today") || undefined,
    dataset: url.searchParams.get("dataset") || undefined,
  };
  const summary = await runIngestion(env, opts, "manual", fetchImpl);
  return json({ ok: summary.status !== "fail", summary });
}

async function handleExportD1(
  env: Env, request: Request,
): Promise<Response> {
  if (!authorized(request, env, true)) {
    return json({ error: "unauthorized" }, 401);
  }
  const url = new URL(request.url);
  const table = url.searchParams.get("table") || "jquants_records";
  // Allow only our known tables (defence in depth against SQL injection).
  const allowed = new Set([
    "jquants_records", "jquants_listed_info", "jquants_daily_bars",
    "jquants_market_calendar",
    "jquants_records_revisions", "jquants_listed_info_revisions",
    "jquants_daily_bars_revisions", "jquants_market_calendar_revisions",
    "ingestion_validation", "ingestion_run_log",
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

  // rowid is a stable, indexed cursor for every exportable D1 table. Fetch
  // one extra row so has_more is exact without an unbounded COUNT(*).
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
  return Response.json({
    table,
    rows,
    cursor: cursorRaw,
    next_cursor: hasMore ? nextCursor : null,
    has_more: hasMore,
    limit: limitRaw,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") return handleHealth(env);
    if (url.pathname === "/v1/run") return handleRun(env, request, fetch);
    if (url.pathname === "/v1/export/d1") return handleExportD1(env, request);
    return json({ error: "not found" }, 404);
  },

  async scheduled(
    _event: ScheduledEvent, env: Env, ctx: ExecutionContext,
  ): Promise<void> {
    // Cron-driven closed loop. Use the global `fetch` (Workers runtime).
    ctx.waitUntil(runIngestion(env, {}, "cron", fetch));
  },
};
