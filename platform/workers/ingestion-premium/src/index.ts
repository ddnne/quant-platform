/// <reference types="@cloudflare/workers-types" />
/**
 * Phase 3.5 — J-Quants Premium core ingestion on Cloudflare.
 *
 * Secrets on CF; INGESTION_RUN_TOKEN / DATA_EXPORT_TOKEN gate write/export.
 * R2 raw + D1 structured. Incremental primary; date params on `/v1/run`.
 * Per-dataset pass/fail (failures are not success). Local PIT via
 * `/v1/export/d1` and `/v1/export/changes`. Required set: `catalog.ts`.
 *
 * Endpoints:
 *   GET  /health
 *   POST /v1/run[?dataset=..&from=..&to=..]
 *   GET  /v1/export/d1?table=..&cursor=..&limit=..
 *   GET  /v1/export/changes?after_seq=..&limit=..
 */

import { PREMIUM_CORE_DATASETS, isPremiumCore, datasetById, type DatasetSpec } from "./catalog";
import {
  naturalKeyMigrationStatus,
  rebuildNaturalKeysV2,
  requireNaturalKeysV2Ready,
} from "./natural_key_migration";
import { RateLimiter } from "./rate_limit";
import { handleArchiveCold } from "./ops_cold_archive";
import { handlePruneChangelog } from "./ops_prune_changelog";
import { handleParquetManifest } from "./ops_parquet_manifest";
import { handleArtifactsJoinPlan } from "./ops_artifacts_plan";
import { handleExportPaths } from "./http_export";
import {
  writeCollectionReceipt,
  writeRequiredCoverageSegment,
  type CollectionSegment,
} from "./collection_receipts";
import { upsertRecords, upsertWatermark } from "./persist_records";
import { fetchDataset } from "./fetch_jq";
import { todayJst, toJstIso } from "./identity";
import { sha256HexFromString } from "./sha256";

export interface Env {
  JQUANTS_API_KEY: string;
  INGESTION_RUN_TOKEN?: string;
  DATA_EXPORT_TOKEN?: string;
  /** Optional concurrency cap (1–8). Default 6 (near Premium ceiling). */
  INGEST_CONCURRENCY?: string;
  /** When "1", equities_master structured skips full-history D1 (R2 only). */
  MASTER_SCD2_ONLY?: string;
  RAW_BUCKET: R2Bucket;
  STRUCTURED_BUCKET: R2Bucket;
  DB: D1Database;
}

// P0-4 parallel ingest knobs — drive near Premium ~500/min ceiling.
const DEFAULT_CONCURRENCY = 6;
const MAX_CONCURRENCY = 8;
// Premium budget ~500 req/min → 120 ms floor = exactly 500/min theoretical max.
const RATE_LIMIT_INTERVAL_MS = 120;

// R2 raw: raw/{dataset}/{run_id}/page-NNNNNN.json + manifest.json

function rawRunPrefix(dataset: string, runId: number | null, when: Date): string {
  const fallback = `uncommitted-${when.toISOString().replace(/[-:.TZ]/g, "")}`;
  return `raw/${dataset}/${runId === null ? fallback : String(runId)}`;
}

async function sha256(value: string): Promise<string> {
  return `sha256:${await sha256HexFromString(value)}`;
}

function latestEventDate(rows: Record<string, unknown>[]): string | null {
  let best: string | null = null;
  const candidates = ["DateTime", "Date", "DisclosedDate", "AnnouncementDate", "DiscDate"];
  for (const row of rows) {
    for (const k of candidates) {
      const v = row[k];
      if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) {
        const day = v.slice(0, 10);
        if (best === null || day > best) best = day;
        break;
      }
    }
  }
  return best;
}

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

function monthEnd(day: string): string {
  const [year, month] = day.slice(0, 7).split("-").map(Number);
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

function collectionSegment(
  spec: DatasetSpec,
  queries: Record<string, string>[],
): CollectionSegment {
  const dates: string[] = [];
  for (const query of queries) {
    if (query.from) dates.push(query.from);
    if (query.to) dates.push(query.to);
    const dayKey = spec.dayParam || "date";
    if (query[dayKey]) dates.push(query[dayKey]);
  }
  if (dates.length === 0) {
    // Vendor snapshot has no date/from/to query; collection window is ingest JST day.
    if (spec.id === "equities_bars_daily_am" || spec.id === "equities_earnings_calendar") {
      dates.push(todayJst());
    } else {
      throw new Error(`collection window unavailable for ${spec.id}`);
    }
  }
  const start = [...dates].sort()[0];
  const end = [...dates].sort().at(-1)!;
  const id = start.slice(0, 7) === end.slice(0, 7)
    ? start.slice(0, 7)
    : `${start}_${end}`;
  const month = start.slice(0, 7);
  const historyStart = spec.coverage.history_target_start;
  const requiredStart = historyStart.slice(0, 7) === month
    ? historyStart
    : `${month}-01`;
  const currentDay = todayJst();
  const requiredEnd = currentDay.slice(0, 7) === month
    ? currentDay
    : monthEnd(start);
  const canonicalMonth = id === month
    && month <= currentDay.slice(0, 7)
    && start === requiredStart
    && end === requiredEnd;
  return {
    id,
    start,
    end,
    expectedScope: {
      coverage_mode: spec.coverage.coverage_mode,
      expected_frequency: spec.coverage.expected_frequency,
      expected_item_unit: spec.coverage.expected_frequency === "event_driven"
        ? "source_event"
        : "source_query",
      segment_end: end,
      segment_start: start,
      universe_rule: spec.coverage.universe_rule,
    },
    expectedItems: spec.coverage.expected_frequency === "event_driven"
      ? null
      : queries.length,
    canonicalMonth,
  };
}

// Fetch/upsert stay together as the ingestion façade.
async function ingestOne(
  env: Env,
  spec: DatasetSpec,
  opts: { from?: string; to?: string; today?: string },
  fetchImpl: typeof fetch,
  runId: number | null,
  limiter: RateLimiter,
): Promise<DatasetResult> {
  const startedAt = toJstIso(new Date());
  const when = new Date();
  const streamD1 = /options/i.test(spec.id);
  let insertedTotal = 0;
  let revisionsTotal = 0;
  let structuredRowCount = 0;
  let lastEvent: string | null = null;
  const rawPrefix = rawRunPrefix(spec.id, runId, when);
  const rawPages: {
    key: string;
    page: number;
    rows: number;
    bytes: number;
    digest: string;
    http_status: number;
  }[] = [];

  const onPage = async (
    pageRows: Record<string, unknown>[],
    page: { number: number; raw: string; httpStatus: number },
  ) => {
      const key = `${rawPrefix}/page-${String(page.number).padStart(6, "0")}.json`;
      const digest = await sha256(page.raw);
      await env.RAW_BUCKET.put(key, page.raw, {
        customMetadata: { digest, dataset: spec.id, run_id: String(runId ?? "") },
      });
      rawPages.push({
        key,
        page: page.number,
        rows: pageRows.length,
        bytes: new TextEncoder().encode(page.raw).byteLength,
        digest,
        http_status: page.httpStatus,
      });
      if (streamD1 && pageRows.length > 0) {
        const r = await upsertRecords(env, spec, pageRows, when);
        insertedTotal += r.inserted;
        revisionsTotal += r.revisions;
        structuredRowCount += pageRows.length;
        const ev = latestEventDate(pageRows);
        if (ev && (lastEvent === null || ev > lastEvent)) lastEvent = ev;
      }
    };

  let segment: CollectionSegment | null = null;
  const onPlan = async (queries: Record<string, string>[]) => {
    segment = collectionSegment(spec, queries);
    if (segment.canonicalMonth) {
      await writeRequiredCoverageSegment(env, spec, segment);
    }
  };

  const outcome = await fetchDataset(
    env, spec, opts, fetchImpl, limiter, onPage, !streamD1, onPlan,
  );

  const rawKey = `${rawPrefix}/manifest.json`;
  const complete = !outcome.error && outcome.paginationErrors === 0;
  // Raw fetch only — never Coverage COMPLETE.
  const rawAcquisition = complete ? "ACQUIRED" : "FAILED";
  const dataDigest = await sha256(rawPages.map((page) => page.digest).join("\n"));
  const rawManifest = {
    format: "jquants-raw-manifest/v1",
    dataset: spec.id,
    run_id: runId,
    fetched_at: toJstIso(when),
    path: spec.bulk === "bulk" && spec.bulkPath ? spec.bulkPath : spec.path,
    params: opts,
    page_count: rawPages.length,
    row_count: outcome.rowsSeen,
    raw_bytes: rawPages.reduce((total, page) => total + page.bytes, 0),
    data_digest: dataDigest,
    raw_acquisition: rawAcquisition,
    complete,
    error: outcome.error || null,
    pages: rawPages,
  };
  await env.RAW_BUCKET.put(rawKey, JSON.stringify(rawManifest), {
    customMetadata: {
      dataset: spec.id,
      run_id: String(runId ?? ""),
      raw_acquisition: rawAcquisition,
    },
  });
  if (runId === null) {
    throw new Error("raw retention manifest requires a durable ingestion run id");
  }
  await env.DB.prepare(
    `INSERT INTO raw_retention_manifests
       (dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
        data_digest, completeness, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(dataset, run_id) DO UPDATE SET
       manifest_key=excluded.manifest_key,
       page_count=excluded.page_count,
       row_count=excluded.row_count,
       raw_bytes=excluded.raw_bytes,
       data_digest=excluded.data_digest,
       completeness=excluded.completeness,
       created_at=excluded.created_at`,
  ).bind(
    spec.id, runId, rawKey, rawManifest.page_count, rawManifest.row_count,
    rawManifest.raw_bytes, rawManifest.data_digest, rawManifest.raw_acquisition,
    rawManifest.fetched_at,
  ).run();

  if (outcome.error) {
    if (segment !== null) {
      await writeCollectionReceipt(env, spec, runId, segment, {
        observedItems: spec.coverage.expected_frequency === "event_driven"
          ? outcome.rowsSeen
          : outcome.queries.length,
        rawPageCount: rawPages.length,
        rawRowCount: outcome.rowsSeen,
        structuredRowCount,
        paginationExhausted: false,
        rawDigest: dataDigest,
        manifestKey: rawKey,
        status: "FAILED",
        error: outcome.error,
      });
    }
    const finishedAt = toJstIso(new Date());
    const res: DatasetResult = {
      dataset: spec.id, status: "fail",
      startedAt, finishedAt,
      rowsSeen: outcome.rowsSeen, rowsInserted: insertedTotal, rowsRevisions: revisionsTotal,
      availableAtMin: null, availableAtMax: null,
      detail: outcome.error, rawKey, rawBytes: outcome.rawBytes,
    };
    if (runId !== null) {
      await writeValidation(env, runId, res);
    }
    return res;
  }

  if (!streamD1) {
    const inserted = await upsertRecords(env, spec, outcome.rows, when);
    insertedTotal = inserted.inserted;
    revisionsTotal = inserted.revisions;
    structuredRowCount = outcome.rows.length;
    lastEvent = latestEventDate(outcome.rows);
  }

  if (segment === null) {
    throw new Error(`successful collection has no segment for ${spec.id}`);
  }
  await writeCollectionReceipt(env, spec, runId, segment, {
    observedItems: spec.coverage.expected_frequency === "event_driven"
      ? outcome.rowsSeen
      : outcome.queries.length,
    rawPageCount: rawPages.length,
    rawRowCount: outcome.rowsSeen,
    structuredRowCount,
    paginationExhausted: outcome.paginationErrors === 0,
    rawDigest: dataDigest,
    manifestKey: rawKey,
    status: "SUCCESS",
    error: null,
  });

  const availableBounds = await selectAvailableBounds(env, spec.id);

  const ingestedAt = toJstIso(when);
  let watermarkDetail = "";
  try {
    await upsertWatermark(env, spec.id, lastEvent, ingestedAt);
  } catch (watermarkError) {
    watermarkDetail = `; watermark upsert failed: ${(watermarkError as Error).message}`;
  }

  const finishedAt = toJstIso(new Date());
  const res: DatasetResult = {
    dataset: spec.id,
    status: "pass",
    startedAt, finishedAt,
    rowsSeen: outcome.rowsSeen,
    rowsInserted: insertedTotal,
    rowsRevisions: revisionsTotal,
    availableAtMin: availableBounds.min,
    availableAtMax: availableBounds.max,
    detail: `raw=${rawKey}${watermarkDetail}${streamD1 ? "; stream_d1=1" : ""}`,
    rawKey,
    rawBytes: outcome.rawBytes,
  };
  if (runId !== null) {
    await writeValidation(env, runId, res);
  }
  return res;
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
  /** Effective concurrency cap actually used for this run (P0-4). */
  concurrency: number;
  /** Shared limiter minimum interval in ms (P0-4). */
  rateLimitMs: number;
  failures: { dataset: string; detail: string }[];
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


async function runIngestion(
  env: Env,
  opts: { from?: string; to?: string; today?: string; dataset?: string },
  triggeredBy: "cron" | "manual",
  fetchImpl: typeof fetch,
): Promise<RunSummary> {
  const startedAt = toJstIso(new Date());

  await requireNaturalKeysV2Ready(env.DB);

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

  const limiter = new RateLimiter(RATE_LIMIT_INTERVAL_MS);
  const concurrency = clampConcurrency(env.INGEST_CONCURRENCY);

  const orderedResults: DatasetResult[] = new Array(specs.length);
  await runWithConcurrency(specs, concurrency, async (spec, index) => {
    const datasetStartedAt = toJstIso(new Date());
    let res: DatasetResult;
    try {
      res = await ingestOne(env, spec, opts, fetchImpl, runId, limiter);
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
    orderedResults[index] = res;
  });

  for (const res of orderedResults) {
    if (!res) continue;
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
    concurrency,
    rateLimitMs: RATE_LIMIT_INTERVAL_MS,
    failures,
  };

  if (runId !== null) {
    await env.DB.prepare(
      `UPDATE ingestion_run_log SET status = ?, detail = ? WHERE id = ?`,
    ).bind(status, JSON.stringify(summary).slice(0, 8000), runId).run();
  }

  return summary;
}

/** Read INGEST_CONCURRENCY from env, clamp to [1, MAX_CONCURRENCY]. */
function clampConcurrency(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_CONCURRENCY;
  return Math.min(MAX_CONCURRENCY, parsed);
}

async function runWithConcurrency<T>(
  items: readonly T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<void>,
): Promise<void> {
  if (items.length === 0) return;
  const effective = Math.max(1, Math.min(concurrency, items.length));
  let cursor = 0;
  async function runner(): Promise<void> {
    while (cursor < items.length) {
      const myIndex = cursor++;
      try {
        await worker(items[myIndex], myIndex);
      } catch {
        /* worker records its own failure */
      }
    }
  }
  const runners: Promise<void>[] = [];
  for (let i = 0; i < effective; i++) runners.push(runner());
  await Promise.all(runners);
}


function authorized(request: Request, expected: string | undefined): boolean {
  if (!expected) return false;
  const got = request.headers.get("X-Ingestion-Token") || "";
  return got === expected;
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

async function handleHealth(env: Env): Promise<Response> {
  const last = await lastRunSummary(env);
  const hasKey = Boolean(env.JQUANTS_API_KEY);
  let naturalKeyMigration: unknown;
  let naturalKeyReady = false;
  try {
    const status = await naturalKeyMigrationStatus(env.DB);
    naturalKeyMigration = status;
    naturalKeyReady = status.state === "READY";
  } catch (error) {
    naturalKeyMigration = { state: "NOT_INSTALLED", detail: (error as Error).message };
  }
  return json({
    ok: hasKey && naturalKeyReady,
    has_jquants_key: hasKey,
    datasets: PREMIUM_CORE_DATASETS.length,
    natural_key_migration: naturalKeyMigration,
    last_run: last,
  });
}

async function handleNaturalKeyRebuild(env: Env, request: Request): Promise<Response> {
  if (request.method !== "POST") {
    return json({ error: "POST required" }, 405);
  }
  if (!authorized(request, env.INGESTION_RUN_TOKEN)) {
    return json({ error: "unauthorized" }, 401);
  }
  try {
    const status = await rebuildNaturalKeysV2(env.DB);
    return json({ ok: status.state === "READY", status });
  } catch (error) {
    const status = await naturalKeyMigrationStatus(env.DB).catch(() => null);
    return json({ error: (error as Error).message, status }, 409);
  }
}

async function handleRun(
  env: Env, request: Request, fetchImpl: typeof fetch,
): Promise<Response> {
  if (request.method !== "POST") {
    return json({ error: "POST required" }, 405);
  }
  if (!authorized(request, env.INGESTION_RUN_TOKEN)) {
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      if (request.method !== "GET") return json({ error: "GET required" }, 405);
      return handleHealth(env);
    }
    if (url.pathname === "/v1/admin/rebuild-natural-keys-v2") {
      return handleNaturalKeyRebuild(env, request);
    }
    if (url.pathname === "/v1/run") return handleRun(env, request, fetch);
    const exportResponse = await handleExportPaths(request, env);
    if (exportResponse) return exportResponse;
    if (url.pathname === "/v1/ops/archive-cold") {
      return handleArchiveCold(request, env);
    }
    if (url.pathname === "/v1/ops/prune-changelog") {
      return handlePruneChangelog(request, env);
    }
    if (url.pathname === "/v1/ops/jsonl-to-parquet-meta") {
      return handleParquetManifest(request, env);
    }
    if (url.pathname === "/v1/ops/artifacts-join-plan") {
      return handleArtifactsJoinPlan(request, env);
    }
    return json({ error: "not found" }, 404);
  },

  async scheduled(
    _event: ScheduledEvent, env: Env, ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(runIngestion(env, {}, "cron", fetch));
  },
};
