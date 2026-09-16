/**
 * Staging R2 control for a finite exact-five compiled acquisition queue.
 * Absent/idle is a no-op. Does not mint Coverage COMPLETE or READY.
 */

import { COMPILED_EXACT_FIVE_DATASET_IDS } from "./receipt_product_input";

export const EXACT_FIVE_ACQUISITION_KEY =
  "control/exact_five_compiled_acquisition.json";

const SCHEMA = "exact-five-compiled-acquisition/v1";
const CONTROL_MAX_BYTES = 8 * 1024;
const MAX_JOBS = 24;
const MAX_JOBS_PER_TICK = 1;
const MAX_ATTEMPTS = 3;
const MAX_INCLUSIVE_DAYS = 31;
const FETCH_TIMEOUT_MS = 30_000;
const LEASE_MS = 90_000;

const CONTROL_KEYS = [
  "schema",
  "jobs",
  "cursor",
  "attempts",
  "lease",
  "last",
] as const;

const JOB_KEYS = ["dataset", "from", "to"] as const;

type ControlLease = { owner: string; until: string } | null;

export type ExactFiveJob = {
  dataset: string;
  from: string;
  to: string;
};

type AcquisitionLast = {
  dataset: string;
  from: string;
  to: string;
  rowsInserted: number;
  status: string;
} | null;

type AcquisitionControl = {
  schema: typeof SCHEMA;
  jobs: ExactFiveJob[];
  cursor: number;
  attempts: number;
  lease: ControlLease;
  last: AcquisitionLast;
};

export type ExactFiveTickResult = {
  status: "idle" | "stop" | "lost" | "pass" | "fail";
  fetched: boolean;
  jobs: number;
  reason: string;
};

export type ExactFiveIngest = (
  opts: { dataset: string; from: string; to: string },
  signal: AbortSignal,
) => Promise<{ status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number }>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCalendarDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function inclusiveDays(from: string, to: string): number {
  const start = Date.parse(`${from}T00:00:00Z`);
  const end = Date.parse(`${to}T00:00:00Z`);
  return Math.floor((end - start) / 86_400_000) + 1;
}

function parseLease(value: unknown): ControlLease | undefined {
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

function parseJob(value: unknown): ExactFiveJob | null {
  if (!isPlainObject(value)) return null;
  const keys = Object.keys(value);
  if (keys.length !== JOB_KEYS.length) return null;
  const dataset = value.dataset;
  const from = value.from;
  const to = value.to;
  if (typeof dataset !== "string" || typeof from !== "string" || typeof to !== "string") {
    return null;
  }
  if (!COMPILED_EXACT_FIVE_DATASET_IDS.has(dataset)) return null;
  if (!isCalendarDay(from) || !isCalendarDay(to)) return null;
  if (from > to) return null;
  if (inclusiveDays(from, to) > MAX_INCLUSIVE_DAYS) return null;
  return { dataset, from, to };
}

function parseLast(value: unknown): AcquisitionLast | undefined {
  if (value === null) return null;
  if (!isPlainObject(value) || Object.keys(value).length !== 5) return undefined;
  const dataset = value.dataset;
  const from = value.from;
  const to = value.to;
  const status = value.status;
  if (typeof dataset !== "string" || !COMPILED_EXACT_FIVE_DATASET_IDS.has(dataset)) {
    return undefined;
  }
  if (typeof from !== "string" || typeof to !== "string") return undefined;
  if (!isCalendarDay(from) || !isCalendarDay(to)) return undefined;
  if (
    typeof value.rowsInserted !== "number" ||
    !Number.isSafeInteger(value.rowsInserted) ||
    value.rowsInserted < 0
  ) {
    return undefined;
  }
  if (typeof status !== "string" || status.length === 0) return undefined;
  return {
    dataset,
    from,
    to,
    rowsInserted: value.rowsInserted,
    status,
  };
}

function parseControl(raw: string): AcquisitionControl | null {
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
  if (parsed.schema !== SCHEMA) return null;
  if (!Array.isArray(parsed.jobs) || parsed.jobs.length < 1 || parsed.jobs.length > MAX_JOBS) {
    return null;
  }
  const jobs: ExactFiveJob[] = [];
  for (const row of parsed.jobs) {
    const job = parseJob(row);
    if (!job) return null;
    jobs.push(job);
  }
  if (
    typeof parsed.cursor !== "number" ||
    !Number.isSafeInteger(parsed.cursor) ||
    parsed.cursor < 0 ||
    parsed.cursor > jobs.length
  ) {
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
    jobs,
    cursor: parsed.cursor,
    attempts: parsed.attempts,
    lease,
    last,
  };
}

function serialize(control: AcquisitionControl): string {
  return JSON.stringify(control);
}

async function casPut(
  bucket: R2Bucket,
  control: AcquisitionControl,
  etag: string,
): Promise<R2Object | null> {
  const body = serialize(control);
  if (new TextEncoder().encode(body).byteLength > CONTROL_MAX_BYTES) return null;
  return bucket.put(EXACT_FIVE_ACQUISITION_KEY, body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    onlyIf: { etagMatches: etag },
  });
}

async function ingestJob(
  ingest: ExactFiveIngest,
  job: ExactFiveJob,
): Promise<{ status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number }> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), FETCH_TIMEOUT_MS);
  try {
    return await new Promise((resolve, reject) => {
      const onAbort = () => reject(new Error("exact-five job fetch timeout"));
      if (ac.signal.aborted) {
        onAbort();
        return;
      }
      ac.signal.addEventListener("abort", onAbort, { once: true });
      ingest(job, ac.signal).then(
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

function summaryAccepted(
  summary: { status: string; datasetCount: number; rowsInserted: number },
): boolean {
  if (summary.status !== "pass") return false;
  if (!Number.isSafeInteger(summary.datasetCount) || summary.datasetCount !== 1) {
    return false;
  }
  if (!Number.isSafeInteger(summary.rowsInserted) || summary.rowsInserted < 0) {
    return false;
  }
  return true;
}

export async function runExactFiveAcquisitionTick(
  bucket: R2Bucket,
  ingest: ExactFiveIngest,
  clock: () => Date = () => new Date(),
): Promise<ExactFiveTickResult> {
  const object = await bucket.get(EXACT_FIVE_ACQUISITION_KEY);
  if (!object) return { status: "idle", fetched: false, jobs: 0, reason: "absent" };
  if (object.size > CONTROL_MAX_BYTES) {
    return { status: "stop", fetched: false, jobs: 0, reason: "invalid" };
  }
  const control = parseControl(await object.text());
  if (!control || !object.etag) {
    return { status: "stop", fetched: false, jobs: 0, reason: "invalid" };
  }

  let etag = object.etag;
  let fetched = false;
  let ran = 0;

  for (let i = 0; i < MAX_JOBS_PER_TICK; i++) {
    if (control.cursor >= control.jobs.length) {
      return {
        status: ran > 0 ? "pass" : "idle",
        fetched,
        jobs: ran,
        reason: ran > 0 ? "ok" : "complete",
      };
    }
    if (control.attempts >= MAX_ATTEMPTS) {
      return { status: "stop", fetched, jobs: ran, reason: "exhausted" };
    }
    const now = clock();
    if (control.lease && control.lease.until > now.toISOString()) {
      return { status: "idle", fetched, jobs: ran, reason: "leased" };
    }

    const job = control.jobs[control.cursor]!;
    const owner = crypto.randomUUID();
    const until = new Date(now.getTime() + LEASE_MS).toISOString();
    control.attempts += 1;
    control.lease = { owner, until };
    const claimed = await casPut(bucket, control, etag);
    if (claimed === null || !claimed.etag) {
      return { status: "lost", fetched, jobs: ran, reason: "cas" };
    }
    etag = claimed.etag;
    fetched = true;
    ran += 1;

    let summary: { status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number };
    try {
      summary = await ingestJob(ingest, job);
    } catch (error) {
      const reportNow = clock();
      if (control.lease.until <= reportNow.toISOString()) {
        return { status: "lost", fetched, jobs: ran, reason: "expired" };
      }
      const timedOut = error instanceof Error &&
        error.message === "exact-five job fetch timeout";
      if (!timedOut) control.lease = null;
      control.last = {
        dataset: job.dataset,
        from: job.from,
        to: job.to,
        rowsInserted: 0,
        status: timedOut ? "timeout" : "ingestion_failed",
      };
      const written = await casPut(bucket, control, etag);
      if (written === null) return { status: "lost", fetched, jobs: ran, reason: "cas" };
      return {
        status: "fail",
        fetched,
        jobs: ran,
        reason: timedOut ? "timeout" : "ingestion_failed",
      };
    }

    const reportNow = clock();
    if (control.lease.until <= reportNow.toISOString()) {
      return { status: "lost", fetched, jobs: ran, reason: "expired" };
    }
    const rowsInserted = Number.isSafeInteger(summary.rowsInserted) &&
        summary.rowsInserted >= 0
      ? summary.rowsInserted
      : 0;
    if (!summaryAccepted(summary)) {
      control.lease = null;
      control.last = {
        dataset: job.dataset,
        from: job.from,
        to: job.to,
        rowsInserted,
        status: "ingestion_failed",
      };
      const written = await casPut(bucket, control, etag);
      if (written === null) return { status: "lost", fetched, jobs: ran, reason: "cas" };
      return { status: "fail", fetched, jobs: ran, reason: "ingestion_failed" };
    }

    control.cursor += 1;
    control.attempts = 0;
    control.lease = null;
    control.last = {
      dataset: job.dataset,
      from: job.from,
      to: job.to,
      rowsInserted: summary.rowsInserted,
      status: "pass",
    };
    const written = await casPut(bucket, control, etag);
    if (written === null || !written.etag) {
      return { status: "lost", fetched, jobs: ran, reason: "cas" };
    }
    etag = written.etag;
  }

  return { status: "pass", fetched, jobs: ran, reason: "ok" };
}
