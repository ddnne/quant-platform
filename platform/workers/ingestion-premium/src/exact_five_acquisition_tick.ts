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
 *
 * Fetch abort cancels vendor HTTP only. The tick waits for the ingest
 * callback to settle and commits that outcome even after the claim lease
 * expires. The claim lease is longer than the fetch abort so overlapping
 * minute Cron ticks do not recapture an in-flight month. Elapsed lease is
 * not proof the prior owner stopped: reconcile a SUCCESS collection receipt
 * for the pending job before any replay.
 * A Durable Object/DB `running` row is not proof an isolate still executes.
 * Official Cron Trigger wall-clock duration is 15 minutes; a `running` row
 * older than that wall, with no PREPARED request and no receipt, is an
 * abandoned started marker. Continue the same operation/attempt (same owner,
 * no attempt increment) so late work can finish. Do not overlap a live or
 * possibly-live isolate, and do not hold later jobs forever on a stale row.
 * PENDING no-operation skip still treats unsigned SUCCESS as already collected
 * for that audit path. ACTIVE no-operation skip requires a trusted signed
 * full-segment collection receipt for the exact window. Operation-bound
 * observation still finishes the initiating claim from that operation's rows.
 * Coverage presence is not liveness. A fail validation or FAILED receipt
 * for this operation and exact window is terminal only when no matching
 * PREPARED request remains. A matching PREPARED keeps the initiating
 * operation so recoverPreparedReceipts can finish before a new claim.
 * Cursor is progress inside this object; receipts also skip already-acquired
 * months after a control replace.
 */

import { datasetById } from "./catalog";
import {
  casPutJson,
  CONTROL_MAX_BYTES,
  parseControlLease,
  type ControlLease,
} from "./control_cas";
import { todayJst, validDate } from "./identity";
import {
  COMPILED_CLOSURE_DIGEST,
  COMPILED_EXACT_FIVE_DATASET_IDS,
  COMPILED_EXACT_FOUR_PERIOD,
  COMPILED_PROFILE_DIGEST,
  COMPILED_PROFILE_ID,
} from "./receipt_product_input";
import {
  pinnedReceiptRegistryForEnvironment,
  trustedSignedCollectionReceipt,
  type ReceiptVerifyRegistry,
} from "./ops_projection_policy";
import { sha256HexFromString } from "./sha256";

export const EXACT_FIVE_ACQUISITION_KEY =
  "control/exact_five_compiled_acquisition.json";

const SCHEMA = "exact-five-compiled-acquisition/v1";
const MAX_JOBS = 24;
const MAX_ATTEMPTS = 3;
const EXACT_FIVE_FETCH_TIMEOUT_MS = 180_000;
const EXACT_FIVE_LEASE_MS = 240_000;
/** Official Cron Trigger duration limit (developers.cloudflare.com/workers/platform/limits). */
const CRON_TRIGGER_WALL_MS = 15 * 60 * 1000;
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
  opts: { dataset: string; from: string; to: string; operation?: string },
  signal: AbortSignal,
) => Promise<{ status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number }>;

 export type ExactFiveObservation = {
   status: "pass" | "failed" | "started" | "absent";
   rowsInserted: number;
 };

export type ExactFiveObserve = (
  job: ExactFiveJob,
  window: { from: string; to: string },
  operation?: string,
) => Promise<ExactFiveObservation>;

export type ExactFiveTickOptions = {
  clock?: () => Date;
  fetchTimeoutMs?: number;
  observe?: ExactFiveObserve;
};

export type ExactFiveObserveOptions = {
  operationMode?: "PENDING" | "ACTIVE";
  environment?: "staging" | "production";
  registry?: ReceiptVerifyRegistry | null;
  clock?: () => Date;
};

/** Durable job completion is a collection receipt for this window, not the ingest promise. */
export async function observeExactFiveReceipt(
  db: D1Database,
  job: ExactFiveJob,
  window: { from: string; to: string },
  operation?: string,
  options: ExactFiveObserveOptions = {},
): Promise<ExactFiveObservation> {
   if (operation) {
     const bound = await observeBoundExactFive(
       db, job, window, operation, options.clock ?? (() => new Date()),
     );
     if (bound) return bound;
   }
  const operationMode = options.operationMode ?? "PENDING";
  const environment = options.environment ?? "staging";
   const success = await db.prepare(
     `SELECT source, dataset, segment_id, segment_start, segment_end, status, error,
             pagination_exhausted, structured_row_count, observed_items, expected_items,
             expected_scope, raw_page_count, raw_row_count, run_id, checked_at, digests_json
       FROM collection_receipts
      WHERE source = 'jquants' AND dataset = ? AND segment_id = ?
        AND segment_start = ? AND segment_end = ? AND status = 'SUCCESS'
      ORDER BY checked_at DESC, run_id DESC
      LIMIT 1`,
    ).bind(job.dataset, job.segment_id, window.from, window.to).first<Record<string, unknown>>();
    if (success && !operation) {
      if (operationMode === "ACTIVE") {
        const registry = options.registry !== undefined
          ? options.registry
          : await pinnedReceiptRegistryForEnvironment(environment);
        const claims = await trustedSignedCollectionReceipt(
          success,
          environment,
          registry,
        );
        if (
          claims &&
          claims.segment_start === window.from &&
          claims.segment_end === window.to
        ) {
          const rowsInserted = Number.isSafeInteger(success.structured_row_count) &&
            (success.structured_row_count as number) >= 0
            ? (success.structured_row_count as number)
            : 0;
          return { status: "pass", rowsInserted };
        }
      } else {
        const rowsInserted = Number.isSafeInteger(success.structured_row_count) &&
          (success.structured_row_count as number) >= 0
          ? (success.structured_row_count as number)
          : 0;
        return { status: "pass", rowsInserted };
      }
    }
   if (!operation && await preparedExactFiveRequest(db, job)) {
     return { status: "started", rowsInserted: 0 };
   }
   return { status: "absent", rowsInserted: 0 };
 }

 function premiumOperationSql(alias: string): string {
   return `${alias}.source = 'jquants' AND ${alias}.runtime = 'cloudflare'
     AND json_extract(${alias}.detail, '$.opts.operation') = ?
     AND json_extract(${alias}.detail, '$.opts.dataset') = ?
     AND json_extract(${alias}.detail, '$.opts.from') = ?
     AND json_extract(${alias}.detail, '$.opts.to') = ?`;
 }

 async function preparedExactFiveRequest(
   db: D1Database,
   job: ExactFiveJob,
   nonce?: string,
 ): Promise<boolean> {
   if (nonce) {
     const row = await db.prepare(
       `SELECT 1 AS present
          FROM receipt_authority_requests
         WHERE state = 'PREPARED' AND source = 'jquants'
           AND dataset = ? AND segment_id = ? AND request_nonce = ?
         LIMIT 1`,
     ).bind(job.dataset, job.segment_id, nonce).first();
     return row !== null;
   }
   const row = await db.prepare(
     `SELECT 1 AS present
        FROM receipt_authority_requests
       WHERE state = 'PREPARED' AND source = 'jquants'
         AND dataset = ? AND segment_id = ?
       LIMIT 1`,
   ).bind(job.dataset, job.segment_id).first();
   return row !== null;
 }

async function observeBoundExactFive(
  db: D1Database,
  job: ExactFiveJob,
  window: { from: string; to: string },
  operation: string,
  clock: () => Date,
): Promise<ExactFiveObservation | null> {
   const nonce = await sha256HexFromString(operation);
   const success = await db.prepare(
     `SELECT receipt.structured_row_count AS structured_row_count
        FROM collection_receipts AS receipt
        JOIN ingestion_run_log AS run ON run.id = receipt.run_id
       WHERE receipt.source = 'jquants' AND receipt.dataset = ?
         AND receipt.segment_id = ?
         AND receipt.segment_start = ? AND receipt.segment_end = ?
         AND receipt.status = 'SUCCESS'
         AND (
           (
             run.source = 'jquants' AND run.runtime = 'cloudflare'
             AND json_extract(run.detail, '$.opts.operation') = ?
             AND json_extract(run.detail, '$.opts.dataset') = ?
             AND json_extract(run.detail, '$.opts.from') = ?
             AND json_extract(run.detail, '$.opts.to') = ?
           ) OR (
             run.source = 'jquants' AND run.runtime = 'receipt-evidence-authority'
             AND EXISTS (
               SELECT 1
                 FROM receipt_authority_requests AS request
                 JOIN receipt_authority_operations AS authority
                   ON authority.operation_id = request.operation_id
                WHERE request.request_nonce = ?
                  AND request.state = 'FINALIZED'
                  AND authority.run_id = run.id
                  AND authority.operation_id = run.authority_operation_id
                  AND authority.state = 'RECEIPT_COMMITTED'
                  AND authority.dataset = receipt.dataset
                  AND authority.segment_id = receipt.segment_id
                  AND authority.segment_start = receipt.segment_start
                  AND authority.segment_end = receipt.segment_end
                  AND EXISTS (
                    SELECT 1 FROM ingestion_run_log AS premium
                     WHERE ${premiumOperationSql("premium")}
                  )
             )
           )
         )
       ORDER BY receipt.checked_at DESC, receipt.run_id DESC
       LIMIT 1`,
   ).bind(
     job.dataset, job.segment_id, window.from, window.to,
     operation, job.dataset, window.from, window.to,
     nonce,
     operation, job.dataset, window.from, window.to,
   ).first<{
     structured_row_count: number;
   }>();
     if (success) {
       const rowsInserted = Number.isSafeInteger(success.structured_row_count) &&
           success.structured_row_count >= 0
         ? success.structured_row_count
         : 0;
       return { status: "pass", rowsInserted };
     }
     if (await preparedExactFiveRequest(db, job, nonce)) {
       return { status: "started", rowsInserted: 0 };
     }
     const failed = await db.prepare(
       `SELECT 1 AS present
          FROM collection_receipts AS receipt
          JOIN ingestion_run_log AS run ON run.id = receipt.run_id
         WHERE receipt.source = 'jquants' AND receipt.dataset = ?
           AND receipt.segment_id = ?
           AND receipt.segment_start = ? AND receipt.segment_end = ?
           AND receipt.status = 'FAILED'
           AND run.source = 'jquants' AND run.runtime = 'cloudflare'
           AND json_extract(run.detail, '$.opts.operation') = ?
           AND json_extract(run.detail, '$.opts.dataset') = ?
           AND json_extract(run.detail, '$.opts.from') = ?
           AND json_extract(run.detail, '$.opts.to') = ?
         LIMIT 1`,
     ).bind(
       job.dataset, job.segment_id, window.from, window.to,
       operation, job.dataset, window.from, window.to,
     ).first();
     if (failed) return { status: "failed", rowsInserted: 0 };
   const validationFailed = await db.prepare(
     `SELECT 1 AS present
        FROM ingestion_run_log AS run
       JOIN ingestion_validation AS validation ON validation.run_id = run.id
       WHERE ${premiumOperationSql("run")}
         AND validation.dataset = ?
         AND validation.status = 'fail'
       LIMIT 1`,
   ).bind(operation, job.dataset, window.from, window.to, job.dataset).first();
   if (validationFailed) return { status: "failed", rowsInserted: 0 };
   const failedRun = await db.prepare(
     `SELECT 1 AS present
       FROM ingestion_run_log
       WHERE ${premiumOperationSql("ingestion_run_log")}
         AND status IN ('fail', 'failed')
       LIMIT 1`,
   ).bind(operation, job.dataset, window.from, window.to).first();
  if (failedRun) return { status: "failed", rowsInserted: 0 };
  const run = await db.prepare(
     `SELECT ran_at, status
       FROM ingestion_run_log
       WHERE ${premiumOperationSql("ingestion_run_log")}
       LIMIT 1`,
   ).bind(operation, job.dataset, window.from, window.to).first<{
     ran_at: string;
     status: string;
   }>();
   if (
     run &&
     (run.status === "running" || run.status === "partial") &&
     isolateMayStillRunFromStart(run.ran_at, clock)
   ) {
     return { status: "started", rowsInserted: 0 };
   }
   return null;
 }

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isolateMayStillRunFromStart(ranAt: string, clock: () => Date): boolean {
  const startedAt = Date.parse(ranAt);
  if (!Number.isFinite(startedAt)) return true;
  return clock().getTime() - startedAt < CRON_TRIGGER_WALL_MS;
}

function isolateMayStillRunFromLease(lease: ControlLease, now: Date): boolean {
  if (!lease) return false;
  if (lease.until > now.toISOString()) return true;
  const untilMs = Date.parse(lease.until);
  if (!Number.isFinite(untilMs)) return true;
  return now.getTime() - (untilMs - EXACT_FIVE_LEASE_MS) < CRON_TRIGGER_WALL_MS;
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
  if (!validDate(`${segmentId}-01`)) return null;
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

function jobsEqual(left: ExactFiveJob[], right: ExactFiveJob[]): boolean {
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i++) {
    if (left[i]!.dataset !== right[i]!.dataset) return false;
    if (left[i]!.segment_id !== right[i]!.segment_id) return false;
  }
  return true;
}

function lastForJob(
  last: AcquisitionLast,
  job: ExactFiveJob,
  window: { from: string; to: string },
): boolean {
  return last !== null &&
    last.dataset === job.dataset &&
    last.segment_id === job.segment_id &&
    last.from === window.from &&
    last.to === window.to;
}

function jobRecordedPass(
  control: AcquisitionControl,
  job: ExactFiveJob,
  window: { from: string; to: string },
  jobIndex: number,
): boolean {
  if (control.cursor > jobIndex) return true;
  return lastForJob(control.last, job, window) && control.last!.status === "pass";
}

function jobLast(
  job: ExactFiveJob,
  window: { from: string; to: string },
  rowsInserted: number,
  status: string,
): NonNullable<AcquisitionLast> {
  return {
    dataset: job.dataset,
    segment_id: job.segment_id,
    from: window.from,
    to: window.to,
    rowsInserted,
    status,
  };
}

async function finishPass(
  bucket: R2Bucket,
  control: AcquisitionControl,
  etag: string,
  job: ExactFiveJob,
  window: { from: string; to: string },
  jobIndex: number,
  rowsInserted: number,
  fetched: boolean,
): Promise<ExactFiveTickResult> {
  control.cursor = jobIndex + 1;
  control.attempts = 0;
  control.lease = null;
  control.last = jobLast(job, window, rowsInserted, "pass");
  const durable = await commitControl(bucket, control, etag);
  const jobs = fetched ? 1 : 0;
  if (!durable) return { status: "lost", fetched, jobs, reason: "cas" };
  return tickFromDurable(
    durable,
    job,
    window,
    jobIndex,
    fetched,
    { status: "lost", fetched, jobs, reason: "cas" },
  );
}

async function finishFail(
  bucket: R2Bucket,
  control: AcquisitionControl,
  etag: string,
  job: ExactFiveJob,
  window: { from: string; to: string },
  jobIndex: number,
  rowsInserted: number,
  fetched: boolean,
  reason: "timeout" | "ingestion_failed",
  keepLease: boolean,
): Promise<ExactFiveTickResult> {
  if (!keepLease) control.lease = null;
  control.last = jobLast(job, window, rowsInserted, reason);
  const durable = await commitControl(bucket, control, etag);
  const jobs = fetched ? 1 : 0;
  if (!durable) return { status: "lost", fetched, jobs, reason: "cas" };
  return tickFromDurable(
    durable,
    job,
    window,
    jobIndex,
    fetched,
   { status: "fail", fetched, jobs, reason },
 );
}

async function holdInitiating(
  bucket: R2Bucket,
  control: AcquisitionControl,
  etag: string,
  job: ExactFiveJob,
  window: { from: string; to: string },
  jobIndex: number,
  fetched: boolean,
): Promise<ExactFiveTickResult> {
  const owner = control.lease?.owner;
  control.last = jobLast(job, window, 0, "unresolved");
  if (!owner) control.lease = null;
  const durable = await commitControl(bucket, control, etag);
  const jobs = fetched ? 1 : 0;
  if (!durable) return { status: "lost", fetched, jobs, reason: "cas" };
  if (jobRecordedPass(durable, job, window, jobIndex)) {
    return { status: "pass", fetched, jobs, reason: "ok" };
  }
  return { status: "idle", fetched, jobs, reason: "unresolved" };
}

/**
 * Abort cancels vendor HTTP only. Always wait for ingest() — D1/R2/Receipt
 * may still finish after the fetch signal. Calendar-month equities bars
 * paginate past a day-tick abort; the claim lease must outlast the fetch
 * abort.
 */
async function ingestJob(
  ingest: ExactFiveIngest,
  job: ExactFiveJob,
  window: { from: string; to: string },
  fetchTimeoutMs: number,
  operation: string,
): Promise<{ status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number }> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), fetchTimeoutMs);
  try {
    return await ingest(
      { dataset: job.dataset, from: window.from, to: window.to, operation },
      ac.signal,
    );
  } catch (error) {
    if (ac.signal.aborted) {
      throw new Error("exact-five job fetch timeout");
    }
    throw error;
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

async function readControl(
  bucket: R2Bucket,
): Promise<{ control: AcquisitionControl; etag: string } | null> {
  const object = await bucket.get(EXACT_FIVE_ACQUISITION_KEY);
  if (!object?.etag) return null;
  const control = parseControl(await object.text());
  if (!control) return null;
  return { control, etag: object.etag };
}

/**
 * Persist desired. A durable pass retries once against the latest etag so a
 * late CAS miss does not drop accounting. Failure writes do not clobber a
 * later cursor or recorded pass.
 */
async function commitControl(
  bucket: R2Bucket,
  desired: AcquisitionControl,
  etag: string,
): Promise<AcquisitionControl | null> {
  const written = await casPut(bucket, desired, etag);
  if (written !== null && written.etag) return desired;
  const latest = await readControl(bucket);
  if (!latest || !jobsEqual(latest.control.jobs, desired.jobs)) return null;
  if (latest.control.cursor > desired.cursor) return latest.control;
  if (desired.last?.status === "pass" && latest.control.cursor < desired.cursor) {
    const retry = await casPut(bucket, desired, latest.etag);
    if (retry !== null && retry.etag) return desired;
    const again = await readControl(bucket);
    if (!again || !jobsEqual(again.control.jobs, desired.jobs)) return null;
    return again.control;
  }
  return latest.control;
}

function tickFromDurable(
  durable: AcquisitionControl,
  job: ExactFiveJob,
  window: { from: string; to: string },
  jobIndex: number,
  fetched: boolean,
  fallback: ExactFiveTickResult,
): ExactFiveTickResult {
  if (jobRecordedPass(durable, job, window, jobIndex)) {
    return { status: "pass", fetched, jobs: fetched ? 1 : 0, reason: "ok" };
  }
  return fallback;
}

export async function runExactFiveAcquisitionTick(
  bucket: R2Bucket,
  ingest: ExactFiveIngest,
  options: ExactFiveTickOptions = {},
): Promise<ExactFiveTickResult> {
  const clock = options.clock ?? (() => new Date());
  const fetchTimeoutMs = options.fetchTimeoutMs ?? EXACT_FIVE_FETCH_TIMEOUT_MS;
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
  const job = control.jobs[control.cursor]!;
  const window = compiledCollectionWindow(job.dataset, job.segment_id);
  if (!window) {
    return { status: "stop", fetched: false, jobs: 0, reason: "invalid" };
  }
  let etag = object.etag;
  const jobIndex = control.cursor;
  const lastStatus = lastForJob(control.last, job, window) ? control.last!.status : null;
  const pendingOperation = lastStatus === "running" || lastStatus === "unresolved" ||
      lastStatus === "timeout"
    ? control.lease?.owner
    : undefined;
  const observed = options.observe
    ? await options.observe(job, window, pendingOperation)
    : null;
  if (observed?.status === "pass") {
    return finishPass(
      bucket, control, etag, job, window, jobIndex, observed.rowsInserted, false,
    );
  }
  if (observed?.status === "failed") {
    return finishFail(
      bucket, control, etag, job, window, jobIndex, 0, false, "ingestion_failed", false,
    );
  }

  if (lastForJob(control.last, job, window) && control.last!.status === "pass") {
    return finishPass(
      bucket, control, etag, job, window, jobIndex, control.last!.rowsInserted, false,
    );
  }

  const now = clock();
  if (control.lease && control.lease.until > now.toISOString()) {
    return { status: "idle", fetched: false, jobs: 0, reason: "leased" };
  }

  if (observed?.status === "started") {
    return holdInitiating(bucket, control, etag, job, window, jobIndex, false);
  }

  const maybeLiveLate = isolateMayStillRunFromLease(control.lease, now);
  const needsFence = (lastStatus === "running" || lastStatus === "timeout") &&
    maybeLiveLate;
  if (needsFence) {
    const owner = control.lease?.owner;
    if (!owner) {
      return holdInitiating(bucket, control, etag, job, window, jobIndex, false);
    }
    control.lease = {
      owner,
      until: new Date(now.getTime() + EXACT_FIVE_LEASE_MS).toISOString(),
    };
    control.last = jobLast(job, window, 0, "unresolved");
    const durable = await commitControl(bucket, control, etag);
    if (!durable) return { status: "lost", fetched: false, jobs: 0, reason: "cas" };
    if (jobRecordedPass(durable, job, window, jobIndex)) {
      return { status: "pass", fetched: false, jobs: 0, reason: "ok" };
    }
    return { status: "idle", fetched: false, jobs: 0, reason: "unresolved" };
  }

  const continueOwner = pendingOperation;
  if (!continueOwner && control.attempts >= MAX_ATTEMPTS) {
    return { status: "stop", fetched: false, jobs: 0, reason: "exhausted" };
  }

  const owner = continueOwner ?? crypto.randomUUID();
  const until = new Date(now.getTime() + EXACT_FIVE_LEASE_MS).toISOString();
  if (!continueOwner) control.attempts += 1;
  control.lease = { owner, until };
  control.last = jobLast(job, window, 0, "running");
  const claimed = await casPut(bucket, control, etag);
  if (claimed === null || !claimed.etag) {
    const latest = await readControl(bucket);
    if (latest && jobRecordedPass(latest.control, job, window, jobIndex)) {
      return { status: "pass", fetched: false, jobs: 0, reason: "ok" };
    }
    return { status: "lost", fetched: false, jobs: 0, reason: "cas" };
  }
  etag = claimed.etag;

  let summary: { status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number };
  try {
    summary = await ingestJob(ingest, job, window, fetchTimeoutMs, owner);
  } catch (error) {
    if (options.observe) {
      const late = await options.observe(job, window, owner);
      if (late.status === "pass") {
        return finishPass(
          bucket, control, etag, job, window, jobIndex, late.rowsInserted, true,
        );
      }
      if (late.status === "started") {
        return holdInitiating(bucket, control, etag, job, window, jobIndex, true);
      }
    }
    const timedOut = error instanceof Error &&
      error.message === "exact-five job fetch timeout";
    return finishFail(
      bucket,
      control,
      etag,
      job,
      window,
      jobIndex,
      0,
      true,
      timedOut ? "timeout" : "ingestion_failed",
      timedOut,
    );
  }

  const rowsInserted = Number.isSafeInteger(summary.rowsInserted) &&
      summary.rowsInserted >= 0
    ? summary.rowsInserted
    : 0;
  if (summary.status === "partial") {
    control.lease = { owner, until: clock().toISOString() };
    return holdInitiating(bucket, control, etag, job, window, jobIndex, true);
  }
  if (!summaryAccepted(summary)) {
    if (options.observe) {
      const late = await options.observe(job, window, owner);
      if (late.status === "pass") {
        return finishPass(
          bucket, control, etag, job, window, jobIndex, late.rowsInserted, true,
        );
      }
      if (late.status === "started") {
        return holdInitiating(bucket, control, etag, job, window, jobIndex, true);
      }
    }
    return finishFail(
      bucket, control, etag, job, window, jobIndex, rowsInserted, true, "ingestion_failed", false,
    );
  }

  return finishPass(
    bucket, control, etag, job, window, jobIndex, summary.rowsInserted, true,
  );
}
