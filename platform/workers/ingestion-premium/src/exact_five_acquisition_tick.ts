/**
 * Staging R2 control for a finite exact-five compiled acquisition queue.
 * Absent/idle is a no-op. Does not mint Coverage COMPLETE or READY.
 *
 * Admission checks compiled profile/closure identity and catalog month
 * bounds (official history start, no window after today, no month after the
 * compiled period end). Exact selector membership is the operator control,
 * produced by `ops.exact_five_acquisition_control` from
 * `compiled_candidate_selectors` / `declared_coverage_segments` /
 * `_missing_compiled_segments` extras. This tick does not compile warmup.
 */

import { datasetById } from "./catalog";
import {
  casPutJson,
  CONTROL_LEASE_MS,
  CONTROL_MAX_BYTES,
  parseControlLease,
  type ControlLease,
} from "./control_cas";
import { todayJst } from "./identity";
import {
  COMPILED_CLOSURE_DIGEST,
  COMPILED_EXACT_FIVE_DATASET_IDS,
  COMPILED_EXACT_FOUR_PERIOD,
  COMPILED_PROFILE_DIGEST,
  COMPILED_PROFILE_ID,
} from "./receipt_product_input";

export const EXACT_FIVE_ACQUISITION_KEY =
  "control/exact_five_compiled_acquisition.json";

const SCHEMA = "exact-five-compiled-acquisition/v1";
const MAX_JOBS = 24;
const MAX_ATTEMPTS = 3;
const FETCH_TIMEOUT_MS = 30_000;
const MONTH_ID = /^[0-9]{4}-[0-9]{2}$/;

const CONTROL_KEYS = [
  "schema",
  "profile_id",
  "profile_digest",
  "dependency_closure_digest",
  "jobs",
  "cursor",
  "attempts",
  "lease",
  "last",
] as const;

const JOB_KEYS = ["dataset", "segment_id"] as const;

export type ExactFiveJob = {
  dataset: string;
  segment_id: string;
};

type AcquisitionLast = {
  dataset: string;
  segment_id: string;
  from: string;
  to: string;
  rowsInserted: number;
  status: string;
} | null;

type AcquisitionControl = {
  schema: typeof SCHEMA;
  profile_id: string;
  profile_digest: string;
  dependency_closure_digest: string;
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

function monthEnd(month: string): string {
  const [year, monthNum] = month.split("-").map(Number);
  return new Date(Date.UTC(year, monthNum, 0)).toISOString().slice(0, 10);
}

/** Catalog canonical-month window for an explicit compiled selector. */
export function compiledCollectionWindow(
  dataset: string,
  segmentId: string,
): { from: string; to: string } | null {
  if (!COMPILED_EXACT_FIVE_DATASET_IDS.has(dataset) || !MONTH_ID.test(segmentId)) {
    return null;
  }
  const spec = datasetById(dataset);
  if (!spec || spec.coverage.segment_granularity !== "calendar_month") return null;
  const historyStart = spec.coverage.history_target_start;
  const periodEndMonth = COMPILED_EXACT_FOUR_PERIOD.end.slice(0, 7);
  const currentDay = todayJst();
  const currentMonth = currentDay.slice(0, 7);
  if (
    segmentId < historyStart.slice(0, 7) ||
    segmentId > periodEndMonth ||
    segmentId > currentMonth
  ) {
    return null;
  }
  const from = historyStart.slice(0, 7) === segmentId
    ? historyStart
    : `${segmentId}-01`;
  const to = currentMonth === segmentId ? currentDay : monthEnd(segmentId);
  if (from > to) return null;
  return { from, to };
}

function parseJob(value: unknown): ExactFiveJob | null {
  if (!isPlainObject(value)) return null;
  const keys = Object.keys(value);
  if (keys.length !== JOB_KEYS.length) return null;
  const dataset = value.dataset;
  const segmentId = value.segment_id;
  if (typeof dataset !== "string" || typeof segmentId !== "string") return null;
  if (!compiledCollectionWindow(dataset, segmentId)) return null;
  return { dataset, segment_id: segmentId };
}

function parseLast(value: unknown): AcquisitionLast | undefined {
  if (value === null) return null;
  if (!isPlainObject(value) || Object.keys(value).length !== 6) return undefined;
  const dataset = value.dataset;
  const segmentId = value.segment_id;
  const from = value.from;
  const to = value.to;
  const status = value.status;
  if (typeof dataset !== "string" || typeof segmentId !== "string") return undefined;
  const window = compiledCollectionWindow(dataset, segmentId);
  if (!window) return undefined;
  if (typeof from !== "string" || typeof to !== "string") return undefined;
  if (from !== window.from || to !== window.to) return undefined;
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
    segment_id: segmentId,
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
  if (
    parsed.profile_id !== COMPILED_PROFILE_ID ||
    parsed.profile_digest !== COMPILED_PROFILE_DIGEST ||
    parsed.dependency_closure_digest !== COMPILED_CLOSURE_DIGEST
  ) {
    return null;
  }
  if (!Array.isArray(parsed.jobs) || parsed.jobs.length < 1 || parsed.jobs.length > MAX_JOBS) {
    return null;
  }
  const jobs: ExactFiveJob[] = [];
  const seen = new Set<string>();
  for (const row of parsed.jobs) {
    const job = parseJob(row);
    if (!job) return null;
    const key = `${job.dataset}\0${job.segment_id}`;
    if (seen.has(key)) return null;
    seen.add(key);
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
  const lease = parseControlLease(parsed.lease);
  const last = parseLast(parsed.last);
  if (lease === undefined || last === undefined) return null;
  return {
    schema: SCHEMA,
    profile_id: COMPILED_PROFILE_ID,
    profile_digest: COMPILED_PROFILE_DIGEST,
    dependency_closure_digest: COMPILED_CLOSURE_DIGEST,
    jobs,
    cursor: parsed.cursor,
    attempts: parsed.attempts,
    lease,
    last,
  };
}

function casPut(
  bucket: R2Bucket,
  control: AcquisitionControl,
  etag: string,
): Promise<R2Object | null> {
  return casPutJson(bucket, EXACT_FIVE_ACQUISITION_KEY, control, etag);
}

/**
 * Abort covers the ingest callback only. It does not cancel in-flight D1/R2
 * or Receipt writes, and the 90s lease is not proof the prior owner stopped.
 */
async function ingestJob(
  ingest: ExactFiveIngest,
  job: ExactFiveJob,
  window: { from: string; to: string },
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
      ingest({ dataset: job.dataset, from: window.from, to: window.to }, ac.signal).then(
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
  if (control.cursor >= control.jobs.length) {
    return { status: "idle", fetched: false, jobs: 0, reason: "complete" };
  }
  if (control.attempts >= MAX_ATTEMPTS) {
    return { status: "stop", fetched: false, jobs: 0, reason: "exhausted" };
  }
  const now = clock();
  if (control.lease && control.lease.until > now.toISOString()) {
    return { status: "idle", fetched: false, jobs: 0, reason: "leased" };
  }

  const job = control.jobs[control.cursor]!;
  const window = compiledCollectionWindow(job.dataset, job.segment_id);
  if (!window) {
    return { status: "stop", fetched: false, jobs: 0, reason: "invalid" };
  }
  const owner = crypto.randomUUID();
  const until = new Date(now.getTime() + CONTROL_LEASE_MS).toISOString();
  control.attempts += 1;
  control.lease = { owner, until };
  const claimed = await casPut(bucket, control, object.etag);
  if (claimed === null || !claimed.etag) {
    return { status: "lost", fetched: false, jobs: 0, reason: "cas" };
  }
  const etag = claimed.etag;

  let summary: { status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number };
  try {
    summary = await ingestJob(ingest, job, window);
  } catch (error) {
    const reportNow = clock();
    if (control.lease.until <= reportNow.toISOString()) {
      return { status: "lost", fetched: true, jobs: 1, reason: "expired" };
    }
    const timedOut = error instanceof Error &&
      error.message === "exact-five job fetch timeout";
    // Abort covers fetch only; delay retries while prior storage IO may still finish.
    if (!timedOut) control.lease = null;
    control.last = {
      dataset: job.dataset,
      segment_id: job.segment_id,
      from: window.from,
      to: window.to,
      rowsInserted: 0,
      status: timedOut ? "timeout" : "ingestion_failed",
    };
    const written = await casPut(bucket, control, etag);
    if (written === null) return { status: "lost", fetched: true, jobs: 1, reason: "cas" };
    return {
      status: "fail",
      fetched: true,
      jobs: 1,
      reason: timedOut ? "timeout" : "ingestion_failed",
    };
  }

  const reportNow = clock();
  if (control.lease.until <= reportNow.toISOString()) {
    return { status: "lost", fetched: true, jobs: 1, reason: "expired" };
  }
  const rowsInserted = Number.isSafeInteger(summary.rowsInserted) &&
      summary.rowsInserted >= 0
    ? summary.rowsInserted
    : 0;
  if (!summaryAccepted(summary)) {
    control.lease = null;
    control.last = {
      dataset: job.dataset,
      segment_id: job.segment_id,
      from: window.from,
      to: window.to,
      rowsInserted,
      status: "ingestion_failed",
    };
    const written = await casPut(bucket, control, etag);
    if (written === null) return { status: "lost", fetched: true, jobs: 1, reason: "cas" };
    return { status: "fail", fetched: true, jobs: 1, reason: "ingestion_failed" };
  }

  control.cursor += 1;
  control.attempts = 0;
  control.lease = null;
  control.last = {
    dataset: job.dataset,
    segment_id: job.segment_id,
    from: window.from,
    to: window.to,
    rowsInserted: summary.rowsInserted,
    status: "pass",
  };
  const written = await casPut(bucket, control, etag);
  if (written === null) return { status: "lost", fetched: true, jobs: 1, reason: "cas" };
  return { status: "pass", fetched: true, jobs: 1, reason: "ok" };
}
