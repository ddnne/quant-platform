/**
 * J-Quants Premium fetch/retry: vendor HTTP, pagination, 429/5xx backoff.
 * ingestOne / runIngestion façade and HTTP handlers stay in index.ts.
 */

import type { DatasetSpec } from "./catalog";
import { daysAgoJst, isYyyyMmDd, todayJst } from "./identity";
import type { RateLimiter } from "./rate_limit";
import {
  exponentialBackoffFullJitterMs,
  exponentialBackoffHalfToFullJitterMs,
  sleepMs,
} from "./retry_jitter";

export interface FetchEnv {
  JQUANTS_API_KEY: string;
}

export interface FetchOptions {
  from?: string;
  to?: string;
  today?: string;
  /** Internal Cron timestamp; never a caller-controlled acquisition timestamp. */
  scheduledAt?: number;
}

const JQ_BASE = "https://api.jquants.com";

// Per-HTTP-request retries on 429/5xx (matches Python ingestion/common/retry).
const RETRY_COUNT = 3;
const RETRY_BASE_DELAY_MS = 500;
const RETRY_MAX_DELAY_MS = 8_000;
// 429: short backoff only, then resume near-ceiling via RateLimiter.notifyOk.
const RETRY_429_BASE_DELAY_MS = 1_000;
const RETRY_429_MAX_DELAY_MS = 3_000;

/** Last completed JST day — "today" before close often yields empty `data`. */
function defaultMarketDayJst(): string {
  return daysAgoJst(1);
}

/** Hourly Cron's acquisition plan, not a claim that the vendor finished updating.
 * Publication and a later catchup replace all-dataset hourly refetches. 07:15
 * revisits yesterday; older corrections require an explicit bounded collection.
 * No weekday shortcut: derivatives publish the following day, and weekly
 * investor statistics shift on holidays. Source: /ja/spec/data-update.
 */
function scheduledQueries(spec: DatasetSpec, scheduledAt: number): Record<string, string>[] {
  const jst = new Date(scheduledAt + 9 * 3_600_000);
  const hour = jst.getUTCHours();
  const day = (offset = 0) => new Date(jst.getTime() + offset * 86_400_000)
    .toISOString().slice(0, 10);
  const financial = spec.id === "fins_summary" || spec.id === "fins_details";
  const derivative = spec.path.startsWith("/v2/derivatives/");
  let hours: readonly number[];
  if (financial) hours = [hour]; // Premium disclosures remain hourly.
  else if (spec.group === "edinet") hours = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18];
  else if (derivative) hours = [3, 4, 7];
  else switch (spec.id) {
    case "equities_master": hours = [8, 9, 18, 20]; break;
    case "equities_bars_daily_am": hours = [12, 13]; break;
    case "fins_dividend": hours = [7, 12, 13, 14, 15, 16, 17, 18, 19, 20]; break;
    case "fins_earnings_date": hours = [7, 10, 11, 20]; break;
    case "equities_earnings_calendar": hours = [19, 20]; break;
    case "markets_calendar": hours = [20]; break;
    case "markets_margin_interest": hours = [7, 16, 17, 20]; break;
    case "markets_short_sale_report":
    case "markets_breakdown": hours = [7, 18, 20]; break;
    default: hours = [7, 17, 20];
  }
  if (!hours.includes(hour)) return [];
  // 24:30 final financial data and 27:00 derivatives belong to yesterday.
  const target = day(hour === 7 || derivative || (financial && hour <= 1) ? -1 : 0);
  if (spec.id === "equities_master") {
    // CURRENT/SCD2 records observations, not tomorrow's effective membership.
    return [{ date: day() }];
  }
  if (spec.id === "markets_margin_interest" && target >= "2026-09-28") {
    return [{ published_date: target }];
  }
  return requestQueries(spec, spec.dateMode === "range"
    ? { from: day(-5), to: day() }
    : { today: target });
}

function inclusiveDates(from: string, to: string): string[] {
  if (!isYyyyMmDd(from) || !isYyyyMmDd(to)) {
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

export function requestQueries(
  spec: DatasetSpec,
  opts: FetchOptions,
): Record<string, string>[] {
  if (opts.scheduledAt !== undefined && !opts.from && !opts.to && !opts.today) {
    return scheduledQueries(spec, opts.scheduledAt);
  }
  // Vendor snapshot: AM is code+pagination_key; earnings is pagination_key. No date/from/to.
  if (spec.id === "equities_bars_daily_am" || spec.id === "equities_earnings_calendar") {
    return [{}];
  }
  if (spec.dateMode === "none") return [{}];

  // Incremental collection uses publication day; explicit historical requests
  // keep application-date semantics (legacy rows have no PubDate).
  if (spec.id === "markets_margin_interest" && !opts.from && !opts.to && !opts.today
      && todayJst() >= "2026-09-28") {
    return [{ published_date: todayJst() }];
  }

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
  opts: FetchOptions,
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
      if (!Array.isArray(parsed?.data)) {
        out.error = "missing data array";
        return out;
      }
      const rows = parsed.data;
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
