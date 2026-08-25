import type { JsdaQueueJob, JobType, DatasetId } from "./queue_contract";

export type JobState =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed_transient"
  | "rejected";

export interface JobRow {
  work_key: string;
  run_key: string;
  dataset: DatasetId;
  job_type: JobType;
  target_url: string;
  segment_id: string;
  parent_work_key: string | null;
  contract_digest: string;
  state: JobState;
  attempt: number;
  cursor: number;
  frontier_json: string | null;
  last_error: string | null;
  content_digest: string | null;
  raw_key: string | null;
  audit_receipt_key: string | null;
  audit_receipt_digest: string | null;
  requested_by: "cron" | "manual";
  requested_at: string;
  lease_until: string | null;
}

export interface AuditRef {
  key: string;
  digest: string;
}

export interface RunEvent {
  result: "continued" | "completed" | "failed_transient" | "rejected";
  reasonCode: string | null;
  detail: string;
  cursor: number;
  rawKey: string | null;
  contentDigest: string | null;
  audit: AuditRef;
  occurredAt: string;
}

function detailJson(job: Pick<JobRow, "work_key" | "run_key" | "dataset" | "job_type" | "segment_id" | "attempt">, event: RunEvent): string {
  return JSON.stringify({
    mode: "cloudflare_queue_v2",
    run_id: job.run_key,
    job_id: job.work_key,
    segment_id: job.segment_id,
    dataset: job.dataset,
    job_type: job.job_type,
    attempt: job.attempt,
    cursor: event.cursor,
    result: event.result,
    reason: event.reasonCode,
    raw_key: event.rawKey,
    content_digest: event.contentDigest,
    audit_receipt_key: event.audit.key,
    detail: event.detail.slice(0, 500),
  });
}

function insertEventStatement(
  db: D1Database,
  job: Pick<JobRow, "work_key" | "run_key" | "dataset" | "job_type" | "segment_id" | "attempt">,
  event: RunEvent,
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT INTO jsda_acquisition_events_v2
       (work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
        result, reason_code, detail, content_digest, raw_key,
        audit_receipt_key, audit_receipt_digest, occurred_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      job.work_key,
      job.run_key,
      job.dataset,
      job.job_type,
      job.segment_id,
      job.attempt,
      event.cursor,
      event.result,
      event.reasonCode,
      event.detail.slice(0, 500),
      event.contentDigest,
      event.rawKey,
      event.audit.key,
      event.audit.digest,
      event.occurredAt,
    );
}

function insertRunLogStatement(
  db: D1Database,
  job: Pick<JobRow, "work_key" | "run_key" | "dataset" | "job_type" | "segment_id" | "attempt">,
  event: RunEvent,
): D1PreparedStatement {
  const status =
    event.result === "completed"
      ? "pass"
      : event.result === "continued"
        ? "partial"
        : "fail";
  return db
    .prepare(
      `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
       VALUES (?, 'jsda', 'cloudflare_queue_v2', ?, ?)`,
    )
    .bind(event.occurredAt, status, detailJson(job, event));
}

export async function registerJob(db: D1Database, job: JsdaQueueJob): Promise<JobRow> {
  const now = new Date().toISOString();
  await db
    .prepare(
      `INSERT OR IGNORE INTO jsda_acquisition_jobs_v2
       (work_key, run_key, dataset, job_type, target_url, segment_id,
        parent_work_key, contract_digest, state, attempt, cursor,
        requested_by, requested_at, first_seen_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?, ?, ?)`,
    )
    .bind(
      job.work_key,
      job.run_key,
      job.dataset,
      job.job_type,
      job.target_url,
      job.segment_id,
      job.parent_work_key,
      job.contract_digest,
      job.requested_by,
      job.requested_at,
      now,
      now,
    )
    .run();
  const row = await loadJob(db, job.work_key);
  if (row === null) throw new Error(`registered JSDA job cannot be loaded: ${job.work_key}`);
  return row;
}

export async function registerJobs(
  db: D1Database,
  jobs: readonly JsdaQueueJob[],
): Promise<JobRow[]> {
  if (jobs.length === 0) return [];
  const now = new Date().toISOString();
  await db.batch(
    jobs.map((job) =>
      db
        .prepare(
          `INSERT OR IGNORE INTO jsda_acquisition_jobs_v2
           (work_key, run_key, dataset, job_type, target_url, segment_id,
            parent_work_key, contract_digest, state, attempt, cursor,
            requested_by, requested_at, first_seen_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?, ?, ?)`,
        )
        .bind(
          job.work_key,
          job.run_key,
          job.dataset,
          job.job_type,
          job.target_url,
          job.segment_id,
          job.parent_work_key,
          job.contract_digest,
          job.requested_by,
          job.requested_at,
          now,
          now,
        ),
    ),
  );
  const rows: JobRow[] = [];
  for (const job of jobs) {
    const row = await loadJob(db, job.work_key);
    if (row === null) throw new Error(`registered JSDA job cannot be loaded: ${job.work_key}`);
    rows.push(row);
  }
  return rows;
}

export async function loadJob(db: D1Database, workKey: string): Promise<JobRow | null> {
  return db
    .prepare(
      `SELECT work_key, run_key, dataset, job_type, target_url, segment_id,
              parent_work_key, contract_digest, state, attempt, cursor,
              frontier_json, last_error, content_digest, raw_key,
              audit_receipt_key, audit_receipt_digest,
              requested_by, requested_at, lease_until
       FROM jsda_acquisition_jobs_v2 WHERE work_key = ?`,
    )
    .bind(workKey)
    .first<JobRow>();
}

export async function markJobsQueued(
  db: D1Database,
  workKeys: readonly string[],
  queuedAt: string,
): Promise<void> {
  if (workKeys.length === 0) return;
  await db.batch(
    workKeys.map((workKey) =>
      db
        .prepare(
          `UPDATE jsda_acquisition_jobs_v2
           SET state='queued', enqueued_at=?, updated_at=?, last_error=NULL
           WHERE work_key=? AND state IN ('pending', 'failed_transient')`,
        )
        .bind(queuedAt, queuedAt, workKey),
    ),
  );
}

export async function claimJob(
  db: D1Database,
  workKey: string,
  now: string,
  leaseUntil: string,
): Promise<JobRow | null> {
  const result = await db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='running', attempt=attempt+1, started_at=?, updated_at=?,
           lease_until=?, last_error=NULL
       WHERE work_key=? AND (
         state IN ('pending', 'queued', 'failed_transient') OR
         (state='running' AND (lease_until IS NULL OR lease_until <= ?))
       )`,
    )
    .bind(now, now, leaseUntil, workKey, now)
    .run();
  if ((result.meta.changes ?? 0) < 1) return null;
  return loadJob(db, workKey);
}

export async function persistFrontier(
  db: D1Database,
  workKey: string,
  frontierJson: string,
  rawKey: string,
  contentDigest: string,
  now: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET frontier_json=?, raw_key=?, content_digest=?, updated_at=?
       WHERE work_key=? AND state='running'`,
    )
    .bind(frontierJson, rawKey, contentDigest, now, workKey)
    .run();
  if ((result.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA frontier update lost job claim: ${workKey}`);
  }
}

export async function persistFetchedArtifact(
  db: D1Database,
  workKey: string,
  rawKey: string,
  contentDigest: string,
  now: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET raw_key=?, content_digest=?, updated_at=?
       WHERE work_key=? AND state='running'`,
    )
    .bind(rawKey, contentDigest, now, workKey)
    .run();
  if ((result.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA artifact update lost job claim: ${workKey}`);
  }
}

export async function markContinuationPending(
  db: D1Database,
  row: JobRow,
  nextCursor: number,
  now: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='pending', cursor=?, lease_until=NULL, updated_at=?
       WHERE work_key=? AND state='running'`,
    )
    .bind(nextCursor, now, row.work_key)
    .run();
  if ((result.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA continuation lost job claim: ${row.work_key}`);
  }
}

export async function markContinuationQueued(
  db: D1Database,
  row: JobRow,
  nextCursor: number,
  audit: AuditRef,
  now: string,
): Promise<void> {
  const event: RunEvent = {
    result: "continued",
    reasonCode: null,
    detail: "bounded frontier continuation enqueued",
    cursor: nextCursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit,
    occurredAt: now,
  };
  const results = await db.batch([
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v2
         SET state='queued', cursor=?, enqueued_at=?, updated_at=?,
             audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='pending'`,
      )
      .bind(nextCursor, now, now, audit.key, audit.digest, row.work_key),
    insertEventStatement(db, row, event),
    insertRunLogStatement(db, row, event),
  ]);
  if ((results[0]?.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA continuation finalize lost job claim: ${row.work_key}`);
  }
}

export async function completeJob(
  db: D1Database,
  row: JobRow,
  cursor: number,
  audit: AuditRef,
  now: string,
): Promise<void> {
  const event: RunEvent = {
    result: "completed",
    reasonCode: null,
    detail: "job completed with immutable raw and audit evidence",
    cursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit,
    occurredAt: now,
  };
  const results = await db.batch([
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v2
         SET state='completed', cursor=?, lease_until=NULL, completed_at=?, updated_at=?,
             last_error=NULL, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running'`,
      )
      .bind(cursor, now, now, audit.key, audit.digest, row.work_key),
    insertEventStatement(db, row, event),
    insertRunLogStatement(db, row, event),
  ]);
  if ((results[0]?.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA completion lost job claim: ${row.work_key}`);
  }
}

export async function rejectJob(
  db: D1Database,
  row: JobRow,
  reasonCode: string,
  detail: string,
  audit: AuditRef,
  now: string,
): Promise<void> {
  const event: RunEvent = {
    result: "rejected",
    reasonCode,
    detail,
    cursor: row.cursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit,
    occurredAt: now,
  };
  const results = await db.batch([
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v2
         SET state='rejected', lease_until=NULL, completed_at=?, updated_at=?,
             last_error=?, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running'`,
      )
      .bind(now, now, detail.slice(0, 500), audit.key, audit.digest, row.work_key),
    insertEventStatement(db, row, event),
    insertRunLogStatement(db, row, event),
  ]);
  if ((results[0]?.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA rejection lost job claim: ${row.work_key}`);
  }
}

export async function recordTransientFailure(
  db: D1Database,
  row: JobRow,
  reasonCode: string,
  detail: string,
  audit: AuditRef,
  now: string,
): Promise<void> {
  const event: RunEvent = {
    result: "failed_transient",
    reasonCode,
    detail,
    cursor: row.cursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit,
    occurredAt: now,
  };
  const results = await db.batch([
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v2
         SET state='failed_transient', lease_until=NULL, updated_at=?, last_error=?,
             audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running'`,
      )
      .bind(now, detail.slice(0, 500), audit.key, audit.digest, row.work_key),
    insertEventStatement(db, row, event),
    insertRunLogStatement(db, row, event),
  ]);
  if ((results[0]?.meta.changes ?? 0) !== 1) {
    throw new Error(`JSDA transient failure lost job claim: ${row.work_key}`);
  }
}

export async function recordRejectedMessage(
  db: D1Database,
  input: {
    messageId: string;
    attempts: number;
    reasonCode: string;
    bodyJson: string;
    bodyDigest: string;
    audit: AuditRef;
    rejectedAt: string;
  },
): Promise<void> {
  await db
    .prepare(
      `INSERT OR IGNORE INTO jsda_queue_rejects_v2
       (message_id, attempt, reason_code, body_json, body_digest,
        audit_receipt_key, audit_receipt_digest, rejected_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      input.messageId,
      input.attempts,
      input.reasonCode,
      input.bodyJson.slice(0, 8_000),
      input.bodyDigest,
      input.audit.key,
      input.audit.digest,
      input.rejectedAt,
    )
    .run();
}
