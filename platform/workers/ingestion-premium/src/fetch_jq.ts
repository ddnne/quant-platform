/**
 * J-Quants Premium fetch/retry: vendor HTTP, pagination, 429/5xx backoff.
 * ingestOne / runIngestion façade and HTTP handlers stay in index.ts.
 */

import type { DatasetSpec } from "./catalog";
import type { RateLimiter } from "./rate_limit";
import {
  exponentialBackoffFullJitterMs,
  exponentialBackoffHalfToFullJitterMs,
  sleepMs,
} from "./retry_jitter";

export interface FetchEnv {
  JQUANTS_API_KEY: string;
}

const JQ_BASE = "https://api.jquants.com";
const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

// Per-HTTP-request retries on 429/5xx (matches Python ingestion/common/retry).
const RETRY_COUNT = 3;
const RETRY_BASE_DELAY_MS = 500;
const RETRY_MAX_DELAY_MS = 8_000;
// 429: short backoff only, then resume near-ceiling via RateLimiter.notifyOk.
const RETRY_429_BASE_DELAY_MS = 1_000;
const RETRY_429_MAX_DELAY_MS = 3_000;

function toJstIso(d: Date): string {
  const ms = d.getTime() + JST_OFFSET_MS;
  const jst = new Date(ms);
  return jst.toISOString().replace(/\.(\d+)Z$/, "+09:00");
}

function todayJst(): string {
  return toJstIso(new Date()).slice(0, 10);
}

/** Last completed JST day — "today" before close often yields empty `data`. */
function defaultMarketDayJst(): string {
  return daysAgoJst(1);
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
  // Vendor snapshot: AM is code+pagination_key; earnings is pagination_key. No date/from/to.
  if (spec.id === "equities_bars_daily_am" || spec.id === "equities_earnings_calendar") {
    return [{}];
  }
  if (spec.dateMode === "none") return [{}];

  // Single-day key: most series use `date=`; short-sale uses `disc_date=`.
  const dayKey = spec.dayParam || "date";

  if (spec.dateMode === "today") {
    if (opts.from || opts.to) {
      const from = opts.from || opts.to!;
      const to = opts.to || opts.from!;
      return inclusiveDates(from, to).map((d) => ({ [dayKey]: d }));
    }
    return [{ [dayKey]: opts.today || defaultMarketDayJst() }];
  }

  // range: calendar / topix / investor-types (bare from/to).
  const from = opts.from || (opts.to ? opts.to : daysAgoJst(5));
  const to = opts.to || todayJst();
  if (from > to) throw new Error("from must be on or before to");
  return [{ from, to }];
}

export interface FetchOutcome {
  rows: Record<string, unknown>[];
  queries: Record<string, string>[];
  rawBytes: number;
  paginationErrors: number;
  httpStatus: number;
  error: string;
  retriesUsed: number;
}

export async function fetchOnePage(
  env: FetchEnv,
  url: string,
  fetchImpl: typeof fetch,
  limiter: RateLimiter,
): Promise<{ resp: Response | null; error: string; status: number; retriesUsed: number }> {
  let attempt = 0;
  while (true) {
    await limiter.acquire();
    let resp: Response;
    try {
      resp = await fetchImpl(url, {
        method: "GET",
        headers: { "x-api-key": env.JQUANTS_API_KEY },
      });
    } catch (e) {
      attempt++;
      if (attempt > RETRY_COUNT) {
        return {
          resp: null,
          error: `transport: ${(e as Error).message}`,
          status: 0,
          retriesUsed: attempt,
        };
      }
      await sleepMs(
        exponentialBackoffFullJitterMs(
          attempt,
          RETRY_BASE_DELAY_MS,
          RETRY_MAX_DELAY_MS,
        ),
      );
      continue;
    }
    if (resp.status === 429) {
      attempt++;
      // Adaptive limiter: short cooldown + temporary 2× interval, then recover.
      limiter.notify429(1_200);
      if (attempt > RETRY_COUNT) {
        return {
          resp,
          error: `transient HTTP 429 (retries exhausted)`,
          status: 429,
          retriesUsed: attempt,
        };
      }
      try { await resp.text(); } catch { /* ignore */ }
      await sleepMs(
        exponentialBackoffHalfToFullJitterMs(
          attempt,
          RETRY_429_BASE_DELAY_MS,
          RETRY_429_MAX_DELAY_MS,
        ),
      );
      continue;
    }
    if (resp.status >= 500 && resp.status < 600) {
      attempt++;
      if (attempt > RETRY_COUNT) {
        return {
          resp,
          error: `transient HTTP ${resp.status} (retries exhausted)`,
          status: resp.status,
          retriesUsed: attempt,
        };
      }
      // Drain so the connection can be reused before sleeping.
      try { await resp.text(); } catch { /* ignore */ }
      await sleepMs(
        exponentialBackoffFullJitterMs(
          attempt,
          RETRY_BASE_DELAY_MS,
          RETRY_MAX_DELAY_MS,
        ),
      );
      continue;
    }
    // Success path: decay any 429 penalty back toward the 120 ms floor.
    if (resp.status >= 200 && resp.status < 300) {
      limiter.notifyOk();
    }
    return { resp, error: "", status: resp.status, retriesUsed: attempt };
  }
}

export async function fetchDataset(
  env: FetchEnv,
  spec: DatasetSpec,
  opts: { from?: string; to?: string; today?: string },
  fetchImpl: typeof fetch,
  limiter: RateLimiter,
  onPage?: (
    pageRows: Record<string, unknown>[],
    page: { number: number; raw: string; httpStatus: number },
  ) => Promise<void>,
  retainRows = true,
  onPlan?: (queries: Record<string, string>[]) => Promise<void>,
): Promise<FetchOutcome & { rowsSeen: number }> {
  const out: FetchOutcome & { rowsSeen: number } = {
    rows: [],
    queries: [],
    rowsSeen: 0,
    rawBytes: 0,
    paginationErrors: 0,
    httpStatus: 0,
    error: "",
    retriesUsed: 0,
  };
  let queries: Record<string, string>[];
  try {
    queries = requestQueries(spec, opts);
  } catch (e) {
    out.error = `invalid date range: ${(e as Error).message}`;
    return out;
  }
  out.queries = queries;
  if (onPlan) await onPlan(queries);
  if (!env.JQUANTS_API_KEY) {
    out.error = "JQUANTS_API_KEY not bound on worker";
    return out;
  }

  const path = spec.bulk === "bulk" && spec.bulkPath ? spec.bulkPath : spec.path;
  let pageNumber = 0;
  for (const baseQuery of queries) {
    let pagination: string | null = null;
    for (let page = 0; page < 200; page++) {
      const params = new URLSearchParams(baseQuery);
      // AM/earnings vendor snapshot: never send date/from/to; pagination_key only on later pages.
      if (spec.id === "equities_bars_daily_am" || spec.id === "equities_earnings_calendar") {
        params.delete("date");
        params.delete("from");
        params.delete("to");
      }
      if (pagination) params.set("pagination_key", pagination);
      const suffix = params.size > 0 ? `?${params.toString()}` : "";
      const url = JQ_BASE + path + suffix;

      const page0 = await fetchOnePage(env, url, fetchImpl, limiter);
      out.retriesUsed += page0.retriesUsed;
      out.httpStatus = page0.status;
      if (page0.error) {
        out.error = page0.error;
        return out;
      }
      const resp = page0.resp;
      if (!resp) {
        out.error = "transport: no response";
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
      pageNumber++;
      out.rowsSeen += rows.length;
      if (retainRows) out.rows.push(...rows);
      if (onPage) {
        await onPage(rows as Record<string, unknown>[], {
          number: pageNumber,
          raw: text,
          httpStatus: resp.status,
        });
      }
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
