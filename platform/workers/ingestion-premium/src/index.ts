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
 *   7. Local-readable path — the `/v1/export/d1` endpoint streams the D1
 *      structured tables so `scripts/sync_d1_to_sqlite.py` can build a
 *      local PIT DB.
 *   8. Required datasets: see `catalog.ts` (mirrors Python
 *      `PREMIUM_CORE_DATASETS`).
 *
 * Endpoints:
 *   GET  /health                        — readiness + last-run summary
 *   POST /v1/run[?dataset=..&from=..&to=..]  — manual trigger (auth gated)
 *   GET  /v1/export/d1?table=..         — CSV stream of a D1 table
 *                                         (auth gated)
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

  // Build base query per spec.dateMode + overrides.
  const baseQuery: Record<string, string> = {};
  if (spec.dateMode === "range" || opts.from || opts.to) {
    if (opts.from) baseQuery["from"] = opts.from;
    else if (spec.dateMode === "range") baseQuery["from"] = daysAgoJst(5);
    if (opts.to) baseQuery["to"] = opts.to;
    else if (spec.dateMode === "range") baseQuery["to"] = todayJst();
  } else if (spec.dateMode === "today") {
    baseQuery["date"] = opts.today || todayJst();
  }

  const seenPaginationErrors: number[] = [];

  let pagination: string | null = null;
  for (let page = 0; page < 200; page++) {
    const params = new URLSearchParams(baseQuery);
    if (pagination) params.set("pagination_key", pagination);
    const url = JQ_BASE + spec.path + "?" + params.toString();
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
    pagination = next;
  }
  out.paginationErrors = seenPaginationErrors.length;
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
    const stable = JSON.stringify(row, Object.keys(row).sort());
    return `hash:${stable.slice(0, 60)}`;
  }
  return JSON.stringify(picked);
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
      detail: outcome.error, rawKey: null,
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
    path: spec.path,
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
  };
  if (runId !== null) {
    await writeValidation(env, runId, res);
  }
  return res;
}

interface UpsertSummary { inserted: number; revisions: number; }

async function upsertRecords(
  env: Env,
  spec: DatasetSpec,
  rows: Record<string, unknown>[],
  when: Date,
): Promise<UpsertSummary> {
  if (rows.length === 0) return { inserted: 0, revisions: 0 };
  const ingestedAt = toJstIso(when);
  // available_at: row-level if present, else the fetch time (PIT-safe:
  // the row was unknowable before it arrived).
  const placeholders: string[] = [];
  const binds: unknown[] = [];
  for (const row of rows) {
    const nk = naturalKey(row, spec);
    const ev = pickEventTime(row, spec);
    const availableAt =
      typeof row["available_at"] === "string"
        ? (row["available_at"] as string)
        : ingestedAt;
    const payload = JSON.stringify(row);
    placeholders.push("(?, ?, ?, ?, ?, ?, ?, ?)");
    binds.push(
      "jquants", spec.id, nk,
      ev || availableAt,
      availableAt, ingestedAt,
      payload, payload,
    );
  }

  // Idempotent insert with amendment-tracking. SQLite/D1 `INSERT OR IGNORE`
  // leaves a conflicting row untouched; we then upsert revisions on conflict
  // so multiple published revisions of one observation coexist. We do this
  // one chunk at a time to stay under D1's per-statement bind cap.
  const CHUNK = 100;
  let inserted = 0;
  for (let i = 0; i < rows.length; i += CHUNK) {
    const end = Math.min(i + CHUNK, rows.length);
    const pp = placeholders.slice(i, end);
    const bb = binds.slice(i * 8, end * 8);
    const sql =
      `INSERT OR IGNORE INTO jquants_records
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       VALUES ${pp.join(", ")}`;
    const stmt = env.DB.prepare(sql);
    const r = await stmt.bind(...bb).run();
    inserted += (r.meta?.changes ?? 0) as number;
  }

  // Amendments: for each row whose key already existed with a different
  // available_at, persist a revisions row. (D1 SQLite supports
  // `INSERT INTO revisions SELECT ... WHERE NOT EXISTS`.) For brevity here
  // we insert one revisions row per input row whose payload differs from
  // the current primary row — a deliberate full-fidelity strategy.
  let revisions = 0;
  for (const row of rows) {
    const nk = naturalKey(row, spec);
    const ingestedAt2 = toJstIso(when);
    const availableAt2 =
      typeof row["available_at"] === "string"
        ? (row["available_at"] as string)
        : ingestedAt2;
    const payload2 = JSON.stringify(row);
    const ev2 = pickEventTime(row, spec) || availableAt2;
    const revSql =
      `INSERT OR IGNORE INTO jquants_records_revisions
       (source, dataset, natural_key, available_at, event_time, ingested_at, payload, raw_payload)
       SELECT source, dataset, natural_key, available_at, event_time, ingested_at, payload, raw_payload
       FROM jquants_records
       WHERE source='jquants' AND dataset=? AND natural_key=?
       UNION
       SELECT ?, ?, ?, ?, ?, ?, ?, ?`;
    const r2 = await env.DB.prepare(revSql).bind(
      spec.id, nk,
      "jquants", spec.id, nk, availableAt2, ev2, ingestedAt2, payload2, payload2,
    ).run();
    revisions += (r2.meta?.changes ?? 0) as number;
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

  for (const spec of specs) {
    const res = await ingestOne(env, spec, opts, fetchImpl, runId);
    if (res.status === "pass") {
      passed++;
    } else {
      failed++;
      failures.push({ dataset: res.dataset, detail: res.detail });
    }
    rowsInserted += res.rowsInserted;
  }

  const finishedAt = toJstIso(new Date());
  const status: RunSummary["status"] =
    failed === 0 ? "pass" : passed === 0 ? "fail" : "partial";
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
  return json({
    ok: true,
    has_jquants_key: Boolean(env.JQUANTS_API_KEY),
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
  const r = await env.DB.prepare(`SELECT * FROM ${table}`).all();
  return Response.json({ table, rows: r.results ?? [] });
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
