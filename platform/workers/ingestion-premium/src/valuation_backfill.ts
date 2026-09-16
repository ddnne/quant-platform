/**
 * Staging-only equities_valuation day tick. Mutable control lives at a fixed
 * STRUCTURED_BUCKET key; market objects stay immutable.
 */

export const VALUATION_BACKFILL_KEY = "control/equities_valuation/backfill.json";
const VALUATION_DATASET = "equities_valuation";

const SCHEMA = "equities-valuation-backfill/v1";
const FLOOR = "2008-07-08";
const CONTROL_MAX_BYTES = 8 * 1024;
const MAX_ATTEMPTS = 3;
const MAX_DAYS_PER_TICK = 5;
const FETCH_TIMEOUT_MS = 30_000;
const LEASE_MS = 90_000;

const CONTROL_KEYS = [
  "schema",
  "dataset",
  "job_id",
  "kind",
  "start",
  "end",
  "next",
  "attempts",
  "lease",
  "last",
] as const;

type ValuationKind = "canary" | "history";

type ValuationLease = { owner: string; until: string } | null;

type ValuationLast = {
  day: string;
  rowsInserted: number;
  status: string;
} | null;

type ValuationControl = {
  schema: typeof SCHEMA;
  dataset: typeof VALUATION_DATASET;
  job_id: string;
  kind: ValuationKind;
  start: string;
  end: string;
  next: string;
  attempts: number;
  lease: ValuationLease;
  last: ValuationLast;
};

type ValuationRunSummary = {
  status: "pass" | "fail" | "partial";
  datasetCount: number;
  rowsInserted: number;
};

export type ValuationIngest = (
  opts: { dataset: string; from: string; to: string },
  signal: AbortSignal,
) => Promise<ValuationRunSummary>;

export type ValuationTickResult = {
  status: "idle" | "stop" | "lost" | "pass" | "fail";
  fetched: boolean;
  days: number;
  reason: string;
};

/** Exact-five may run only when valuation is definitively idle, not busy/CAS/error. */
export function valuationIdleForExactFive(tick: ValuationTickResult): boolean {
  return tick.fetched === false &&
    tick.status === "idle" &&
    (tick.reason === "absent" || tick.reason === "complete");
}

function isCalendarDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function addUtcDays(day: string, delta: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + delta);
  return date.toISOString().slice(0, 10);
}

function jstDay(now: Date): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function lastCompletedJst(now: Date): string {
  return addUtcDays(jstDay(now), -1);
}

function valuationJobId(kind: string, start: string, end: string): string {
  return `${kind}:${start}:${end}`;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseLease(value: unknown): ValuationLease | undefined {
  if (value === null) return null;
  if (!isPlainObject(value) || Object.keys(value).length !== 2) return undefined;
  if (typeof value.owner !== "string" || value.owner.length === 0) return undefined;
  if (typeof value.until !== "string") return undefined;
  const until = new Date(value.until);
  if (Number.isNaN(until.getTime()) || until.toISOString() !== value.until) {
    return undefined;
  }
  return { owner: value.owner, until: value.until };
}

function parseLast(value: unknown): ValuationLast | undefined {
  if (value === null) return null;
  if (!isPlainObject(value) || Object.keys(value).length !== 3) return undefined;
  if (typeof value.day !== "string" || !isCalendarDay(value.day)) return undefined;
  if (
    typeof value.rowsInserted !== "number" ||
    !Number.isSafeInteger(value.rowsInserted) ||
    value.rowsInserted < 0
  ) {
    return undefined;
  }
  if (typeof value.status !== "string" || value.status.length === 0) return undefined;
  return {
    day: value.day,
    rowsInserted: value.rowsInserted,
    status: value.status,
  };
}

function parseControl(raw: string, now: Date): ValuationControl | null {
  if (new TextEncoder().encode(raw).byteLength > CONTROL_MAX_BYTES) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) return null;
  const keys = Object.keys(parsed);
  if (keys.length !== CONTROL_KEYS.length) return null;
  for (const key of CONTROL_KEYS) {
    if (!keys.includes(key)) return null;
  }
  if (parsed.schema !== SCHEMA || parsed.dataset !== VALUATION_DATASET) return null;
  if (parsed.kind !== "canary" && parsed.kind !== "history") return null;
  if (parsed.kind === "canary" && parsed.start !== parsed.end) return null;
  if (
    typeof parsed.start !== "string" ||
    typeof parsed.end !== "string" ||
    typeof parsed.next !== "string" ||
    typeof parsed.job_id !== "string"
  ) {
    return null;
  }
  if (
    !isCalendarDay(parsed.start) ||
    !isCalendarDay(parsed.end) ||
    !isCalendarDay(parsed.next)
  ) {
    return null;
  }
  if (parsed.start < FLOOR || parsed.start > parsed.end) return null;
  if (parsed.end > lastCompletedJst(now)) return null;
  const done = addUtcDays(parsed.end, 1);
  if (parsed.next < parsed.start || parsed.next > done) return null;
  if (parsed.job_id !== valuationJobId(parsed.kind, parsed.start, parsed.end)) {
    return null;
  }
  if (
    typeof parsed.attempts !== "number" ||
    !Number.isSafeInteger(parsed.attempts) ||
    parsed.attempts < 0
  ) {
    return null;
  }
  const lease = parseLease(parsed.lease);
  const last = parseLast(parsed.last);
  if (lease === undefined || last === undefined) return null;
  return {
    schema: SCHEMA,
    dataset: VALUATION_DATASET,
    job_id: parsed.job_id,
    kind: parsed.kind,
    start: parsed.start,
    end: parsed.end,
    next: parsed.next,
    attempts: parsed.attempts,
    lease,
    last,
  };
}

function serialize(control: ValuationControl): string {
  return JSON.stringify(control);
}

async function casPut(
  bucket: R2Bucket,
  control: ValuationControl,
  etag: string,
): Promise<R2Object | null> {
  const body = serialize(control);
  if (new TextEncoder().encode(body).byteLength > CONTROL_MAX_BYTES) return null;
  return bucket.put(VALUATION_BACKFILL_KEY, body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    onlyIf: { etagMatches: etag },
  });
}

function summaryAccepted(kind: ValuationKind, summary: ValuationRunSummary): boolean {
  if (summary.status !== "pass") return false;
  if (!Number.isSafeInteger(summary.datasetCount) || summary.datasetCount !== 1) {
    return false;
  }
  if (!Number.isSafeInteger(summary.rowsInserted) || summary.rowsInserted < 0) {
    return false;
  }
  if (kind === "canary" && summary.rowsInserted <= 0) return false;
  return true;
}

async function ingestDay(
  ingest: ValuationIngest,
  day: string,
): Promise<ValuationRunSummary> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), FETCH_TIMEOUT_MS);
  try {
    return await new Promise<ValuationRunSummary>((resolve, reject) => {
      const onAbort = () => reject(new Error("valuation day fetch timeout"));
      if (ac.signal.aborted) {
        onAbort();
        return;
      }
      ac.signal.addEventListener("abort", onAbort, { once: true });
      ingest(
        { dataset: VALUATION_DATASET, from: day, to: day },
        ac.signal,
      ).then(
        (summary) => {
          ac.signal.removeEventListener("abort", onAbort);
          resolve(summary);
        },
        (error: unknown) => {
          ac.signal.removeEventListener("abort", onAbort);
          reject(error);
        },
      );
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function runValuationBackfillTick(
  bucket: R2Bucket,
  ingest: ValuationIngest,
  clock: () => Date = () => new Date(),
): Promise<ValuationTickResult> {
  const object = await bucket.get(VALUATION_BACKFILL_KEY);
  if (!object) return { status: "idle", fetched: false, days: 0, reason: "absent" };
  if (object.size > CONTROL_MAX_BYTES) {
    return { status: "stop", fetched: false, days: 0, reason: "invalid" };
  }
  const control = parseControl(await object.text(), clock());
  if (!control || !object.etag) {
    return { status: "stop", fetched: false, days: 0, reason: "invalid" };
  }

  let etag = object.etag;
  let fetched = false;
  let days = 0;

  for (let i = 0; i < MAX_DAYS_PER_TICK; i++) {
    if (control.next > control.end) {
      return {
        status: days > 0 ? "pass" : "idle",
        fetched,
        days,
        reason: days > 0 ? "ok" : "complete",
      };
    }
    if (control.attempts >= MAX_ATTEMPTS) {
      return { status: "stop", fetched, days, reason: "exhausted" };
    }
    const now = clock();
    if (control.lease && control.lease.until > now.toISOString()) {
      return { status: "idle", fetched, days, reason: "leased" };
    }

    const owner = crypto.randomUUID();
    const until = new Date(now.getTime() + LEASE_MS).toISOString();
    const day = control.next;
    control.attempts += 1;
    control.lease = { owner, until };
    const claimed = await casPut(bucket, control, etag);
    if (claimed === null || !claimed.etag) {
      return { status: "lost", fetched, days, reason: "cas" };
    }
    etag = claimed.etag;
    fetched = true;
    days += 1;

    let summary: ValuationRunSummary;
    try {
      summary = await ingestDay(ingest, day);
    } catch (error) {
      const reportNow = clock();
      if (control.lease.until <= reportNow.toISOString()) {
        return { status: "lost", fetched, days, reason: "expired" };
      }
      const timedOut = error instanceof Error &&
        error.message === "valuation day fetch timeout";
      // Abort covers fetch only; delay retries while prior storage IO may still finish.
      if (!timedOut) control.lease = null;
      control.last = {
        day,
        rowsInserted: 0,
        status: timedOut ? "timeout" : "ingestion_failed",
      };
      const written = await casPut(bucket, control, etag);
      if (written === null) return { status: "lost", fetched, days, reason: "cas" };
      return {
        status: "fail",
        fetched,
        days,
        reason: timedOut ? "timeout" : "ingestion_failed",
      };
    }

    const reportNow = clock();
    if (control.lease.until <= reportNow.toISOString()) {
      return { status: "lost", fetched, days, reason: "expired" };
    }
    const rowsInserted = Number.isSafeInteger(summary.rowsInserted) &&
        summary.rowsInserted >= 0
      ? summary.rowsInserted
      : 0;
    if (!summaryAccepted(control.kind, summary)) {
      control.lease = null;
      control.last = { day, rowsInserted, status: "ingestion_failed" };
      const written = await casPut(bucket, control, etag);
      if (written === null) return { status: "lost", fetched, days, reason: "cas" };
      return { status: "fail", fetched, days, reason: "ingestion_failed" };
    }

    control.next = addUtcDays(day, 1);
    control.attempts = 0;
    control.lease = null;
    control.last = {
      day,
      rowsInserted: summary.rowsInserted,
      status: "pass",
    };
    const written = await casPut(bucket, control, etag);
    if (written === null || !written.etag) {
      return { status: "lost", fetched, days, reason: "cas" };
    }
    etag = written.etag;
  }

  return { status: "pass", fetched, days, reason: "ok" };
}
