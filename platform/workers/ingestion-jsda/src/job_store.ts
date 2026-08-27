import {
  classifyFetchFreshness,
  observationEpoch,
  sourceObjectId,
  type DatasetId,
  type FreshnessClass,
  type JobType,
  type JsdaQueueJob,
} from "./queue_contract";

export type JobState =
  | "pending"
  | "queued"
  | "running"
  | "waiting_children"
  | "completed"
  | "failed_transient"
  | "rejected";

export type ClosureState =
  | "open"
  | "waiting_children"
  | "completed"
  | "failed"
  | "partial";

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
  source_object_id: string | null;
  freshness: FreshnessClass | null;
  observation_epoch: string | null;
}

export interface AuditRef {
  key: string;
  digest: string;
}

export interface RunEvent {
  result:
    | "continued"
    | "frontier_exhausted"
    | "completed"
    | "failed_transient"
    | "rejected";
  reasonCode: string | null;
  detail: string;
  cursor: number;
  rawKey: string | null;
  contentDigest: string | null;
  audit: AuditRef;
  occurredAt: string;
}

export interface JobClosureRow {
  work_key: string;
  run_key: string;
  parent_work_key: string | null;
  job_type: JobType;
  closure_state: ClosureState;
  frontier_exhausted: number;
  descendant_total: number;
  descendant_completed: number;
  descendant_rejected: number;
  descendant_failed_transient: number;
  descendant_nonterminal: number;
  failure_work_key: string | null;
  failure_reason_code: string | null;
  failure_detail: string | null;
  closed_at: string | null;
  updated_at: string;
}

export interface RunClosureRow {
  run_key: string;
  root_work_key: string;
  dataset: DatasetId;
  closure_state: ClosureState;
  frontier_exhausted: number;
  descendant_total: number;
  descendant_completed: number;
  descendant_rejected: number;
  descendant_failed_transient: number;
  descendant_nonterminal: number;
  failure_work_key: string | null;
  failure_reason_code: string | null;
  failure_detail: string | null;
  closed_at: string | null;
  updated_at: string;
}

export type MembershipKind = "enqueued" | "adopted";

export interface RunMembershipRow {
  run_key: string;
  root_work_key: string;
  parent_work_key: string;
  child_work_key: string;
  membership_kind: MembershipKind;
  child_job_type: Exclude<JobType, "discover_root">;
  terminal_state: JobState;
  content_digest: string | null;
  raw_key: string | null;
  audit_receipt_key: string | null;
  audit_receipt_digest: string | null;
  failure_reason_code: string | null;
  failure_detail: string | null;
  adopted_at: string | null;
  updated_at: string;
}

const JOB_SELECT = `work_key, run_key, dataset, job_type, target_url, segment_id,
              parent_work_key, contract_digest, state, attempt, cursor,
              frontier_json, last_error, content_digest, raw_key,
              audit_receipt_key, audit_receipt_digest,
              requested_by, requested_at, lease_until,
              source_object_id, freshness, observation_epoch`;

const CLOSURE_SELECT = `work_key, run_key, parent_work_key, job_type, closure_state,
        frontier_exhausted, descendant_total, descendant_completed,
        descendant_rejected, descendant_failed_transient, descendant_nonterminal,
        failure_work_key, failure_reason_code, failure_detail, closed_at, updated_at`;

const RUN_CLOSURE_SELECT = `run_key, root_work_key, dataset, closure_state,
        frontier_exhausted, descendant_total, descendant_completed,
        descendant_rejected, descendant_failed_transient, descendant_nonterminal,
        failure_work_key, failure_reason_code, failure_detail, closed_at, updated_at`;

const MEMBERSHIP_SELECT = `run_key, root_work_key, parent_work_key, child_work_key,
        membership_kind, child_job_type, terminal_state, content_digest, raw_key,
        audit_receipt_key, audit_receipt_digest, failure_reason_code,
        failure_detail, adopted_at, updated_at`;

const MEMBERSHIP_COMPLETED = `terminal_state='completed'
         AND audit_receipt_key IS NOT NULL AND audit_receipt_digest IS NOT NULL
         AND content_digest IS NOT NULL AND raw_key IS NOT NULL`;

function detailJson(
  job: Pick<JobRow, "work_key" | "run_key" | "dataset" | "job_type" | "segment_id" | "attempt">,
  event: RunEvent,
): string {
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
    audit_receipt_digest: event.audit.digest,
    detail: event.detail.slice(0, 500),
  });
}

function insertEventStatement(
  db: D1Database,
  job: Pick<JobRow, "work_key" | "run_key" | "dataset" | "job_type" | "segment_id" | "attempt">,
  event: RunEvent,
  expectedState: JobState,
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT INTO jsda_acquisition_events_v3
       (work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
        result, reason_code, detail, content_digest, raw_key,
        audit_receipt_key, audit_receipt_digest, occurred_at)
       SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
       WHERE EXISTS (
         SELECT 1 FROM jsda_acquisition_jobs_v3
          WHERE work_key=? AND attempt=? AND state=?
            AND audit_receipt_key=? AND audit_receipt_digest=?
       )`,
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
      job.work_key,
      job.attempt,
      expectedState,
      event.audit.key,
      event.audit.digest,
    );
}

interface FileIdentity {
  sourceObjectId: string;
  freshness: FreshnessClass;
  epoch: string;
}

async function fileIdentity(job: JsdaQueueJob): Promise<FileIdentity | null> {
  if (job.job_type !== "fetch_file") return null;
  const freshness = classifyFetchFreshness(
    job.dataset,
    job.target_url,
    job.requested_at,
  );
  return {
    sourceObjectId: await sourceObjectId(job.dataset, job.target_url),
    freshness,
    epoch: observationEpoch(freshness, job.run_key),
  };
}

function insertSourceObjectStatement(
  db: D1Database,
  job: JsdaQueueJob,
  identity: FileIdentity,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT OR IGNORE INTO jsda_source_objects
       (source_object_id, dataset, canonical_url, freshness,
        next_observation_seq, first_seen_at, updated_at)
       VALUES (?, ?, ?, ?, 1, ?, ?)`,
    )
    .bind(
      identity.sourceObjectId,
      job.dataset,
      job.target_url,
      identity.freshness,
      now,
      now,
    );
}

function insertJobStatement(
  db: D1Database,
  job: JsdaQueueJob,
  identity: FileIdentity | null,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT OR IGNORE INTO jsda_acquisition_jobs_v3
       (work_key, run_key, dataset, job_type, target_url, segment_id,
        parent_work_key, contract_digest, state, attempt, cursor,
        requested_by, requested_at, first_seen_at, updated_at,
        source_object_id, freshness, observation_epoch)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?, ?, ?, ?, ?, ?)`,
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
      identity?.sourceObjectId ?? null,
      identity?.freshness ?? null,
      identity?.epoch ?? null,
    );
}

function allocateObservationStatements(
  db: D1Database,
  job: JsdaQueueJob,
  identity: FileIdentity,
  now: string,
): D1PreparedStatement[] {
  return [
    db
      .prepare(
        `UPDATE jsda_source_objects
            SET next_observation_seq = next_observation_seq + 1, updated_at=?
          WHERE source_object_id=?
            AND NOT EXISTS (
              SELECT 1 FROM jsda_observations WHERE observation_key=?
            )
            AND EXISTS (
              SELECT 1 FROM jsda_acquisition_jobs_v3
               WHERE work_key=? AND state='pending'
            )`,
      )
      .bind(now, identity.sourceObjectId, job.work_key, job.work_key),
    db
      .prepare(
        `INSERT OR IGNORE INTO jsda_observations
         (observation_key, source_object_id, work_key, run_key, dataset,
          target_url, freshness, epoch, observation_seq, state,
          first_seen_at, updated_at)
         SELECT ?, ?, ?, ?, ?, ?, ?, ?, so.next_observation_seq - 1, 'pending', ?, ?
           FROM jsda_source_objects so
          WHERE so.source_object_id=?
            AND EXISTS (
              SELECT 1 FROM jsda_acquisition_jobs_v3
               WHERE work_key=? AND state='pending'
            )`,
      )
      .bind(
        job.work_key,
        identity.sourceObjectId,
        job.work_key,
        job.run_key,
        job.dataset,
        job.target_url,
        identity.freshness,
        identity.epoch,
        now,
        now,
        identity.sourceObjectId,
        job.work_key,
      ),
  ];
}

function backfillIdentityStatement(
  db: D1Database,
  job: JsdaQueueJob,
  identity: FileIdentity,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v3
          SET source_object_id=COALESCE(source_object_id, ?),
              freshness=COALESCE(freshness, ?),
              observation_epoch=COALESCE(observation_epoch, ?),
              updated_at=?
        WHERE work_key=?`,
    )
    .bind(
      identity.sourceObjectId,
      identity.freshness,
      identity.epoch,
      now,
      job.work_key,
    );
}

function backfillCompletedObservationStatements(
  db: D1Database,
  job: JsdaQueueJob,
  identity: FileIdentity,
  now: string,
): D1PreparedStatement[] {
  return [
    db
      .prepare(
        `UPDATE jsda_source_objects
            SET next_observation_seq = next_observation_seq + 1, updated_at=?
          WHERE source_object_id=?
            AND NOT EXISTS (
              SELECT 1 FROM jsda_observations WHERE observation_key=?
            )
            AND EXISTS (
              SELECT 1 FROM jsda_acquisition_jobs_v3
               WHERE work_key=? AND state='completed'
                 AND audit_receipt_key IS NOT NULL
                 AND audit_receipt_digest IS NOT NULL
                 AND content_digest IS NOT NULL
                 AND raw_key IS NOT NULL
            )`,
      )
      .bind(now, identity.sourceObjectId, job.work_key, job.work_key),
    db
      .prepare(
        `INSERT OR IGNORE INTO jsda_observations
         (observation_key, source_object_id, work_key, run_key, dataset,
          target_url, freshness, epoch, observation_seq, state,
          content_digest, raw_key, observed_at, first_seen_at, updated_at)
         SELECT ?, ?, j.work_key, j.run_key, j.dataset, j.target_url, ?, ?,
                so.next_observation_seq - 1, 'completed',
                j.content_digest, j.raw_key, COALESCE(j.completed_at, ?), ?, ?
           FROM jsda_acquisition_jobs_v3 AS j
           JOIN jsda_source_objects AS so
             ON so.source_object_id=?
          WHERE j.work_key=?
            AND j.state='completed'
            AND j.audit_receipt_key IS NOT NULL
            AND j.audit_receipt_digest IS NOT NULL
            AND j.content_digest IS NOT NULL
            AND j.raw_key IS NOT NULL`,
      )
      .bind(
        job.work_key,
        identity.sourceObjectId,
        identity.freshness,
        identity.epoch,
        now,
        now,
        now,
        identity.sourceObjectId,
        job.work_key,
      ),
  ];
}

function insertMembershipStatement(
  db: D1Database,
  job: JsdaQueueJob,
  now: string,
): D1PreparedStatement | null {
  if (job.parent_work_key === null) return null;
  const evidence = `child.state='completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL`;
  return db
    .prepare(
      `INSERT OR IGNORE INTO jsda_run_membership
       (run_key, root_work_key, parent_work_key, child_work_key,
        membership_kind, child_job_type, terminal_state,
        content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
        failure_reason_code, failure_detail, adopted_at, updated_at)
       SELECT ?, ?, ?, child.work_key,
              CASE WHEN child.run_key=? THEN 'enqueued' ELSE 'adopted' END,
              child.job_type,
              CASE
                WHEN child.run_key=? THEN child.state
                WHEN ${evidence} THEN 'completed'
                WHEN child.state='rejected' THEN 'rejected'
                WHEN child.state='completed' THEN 'rejected'
                ELSE child.state
              END,
              CASE
                WHEN child.run_key=? THEN child.content_digest
                WHEN ${evidence} THEN child.content_digest
                ELSE NULL
              END,
              CASE
                WHEN child.run_key=? THEN child.raw_key
                WHEN ${evidence} THEN child.raw_key
                ELSE NULL
              END,
              CASE
                WHEN child.run_key=? THEN child.audit_receipt_key
                WHEN ${evidence} THEN child.audit_receipt_key
                ELSE NULL
              END,
              CASE
                WHEN child.run_key=? THEN child.audit_receipt_digest
                WHEN ${evidence} THEN child.audit_receipt_digest
                ELSE NULL
              END,
              CASE
                WHEN child.run_key=? AND child.state='rejected' THEN 'rejected'
                WHEN child.run_key!=? AND ${evidence} THEN NULL
                WHEN child.run_key!=? AND child.state='rejected' THEN 'rejected'
                WHEN child.run_key!=? AND child.state='completed'
                  THEN 'insufficient_legacy_evidence'
                ELSE NULL
              END,
              CASE
                WHEN child.run_key=? AND child.state='rejected' THEN child.last_error
                WHEN child.run_key!=? AND ${evidence} THEN NULL
                WHEN child.run_key!=? AND child.state='rejected' THEN child.last_error
                WHEN child.run_key!=? AND child.state='completed'
                  THEN 'adopted child lacks authoritative artifact/audit evidence'
                ELSE NULL
              END,
              CASE WHEN child.run_key!=? THEN ? ELSE NULL END,
              ?
         FROM jsda_acquisition_jobs_v3 AS child
        WHERE child.work_key=?`,
    )
    .bind(
      job.run_key,
      job.run_key,
      job.parent_work_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      job.run_key,
      now,
      now,
      job.work_key,
    );
}

function insertArtifactStatements(
  db: D1Database,
  row: Pick<JobRow, "content_digest" | "raw_key" | "dataset">,
  now: string,
): D1PreparedStatement[] {
  if (row.content_digest === null || row.raw_key === null) return [];
  return [
    db
      .prepare(
        `INSERT OR IGNORE INTO jsda_artifacts (content_digest, first_seen_at)
         VALUES (?, ?)`,
      )
      .bind(row.content_digest, now),
    db
      .prepare(
        `INSERT OR IGNORE INTO jsda_artifact_locations
         (raw_key, content_digest, dataset, first_seen_at)
         VALUES (?, ?, ?, ?)`,
      )
      .bind(row.raw_key, row.content_digest, row.dataset, now),
  ];
}

function insertRunClosureStatement(
  db: D1Database,
  job: JsdaQueueJob,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT OR IGNORE INTO jsda_run_closures
       (run_key, root_work_key, dataset, closure_state, updated_at)
       VALUES (?, ?, ?, 'open', ?)`,
    )
    .bind(job.run_key, job.run_key, job.dataset, now);
}

function insertJobClosureStatement(
  db: D1Database,
  job: JsdaQueueJob,
  now: string,
): D1PreparedStatement | null {
  if (job.job_type === "fetch_file") return null;
  return db
    .prepare(
      `INSERT OR IGNORE INTO jsda_job_closures
       (work_key, run_key, parent_work_key, job_type, closure_state, updated_at)
       VALUES (?, ?, ?, ?, 'open', ?)`,
    )
    .bind(job.work_key, job.run_key, job.parent_work_key, job.job_type, now);
}

function updateObservationTerminalStatement(
  db: D1Database,
  row: JobRow,
  event: RunEvent,
  expectedState: JobState,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_observations
       SET state=?, content_digest=?, raw_key=?, observed_at=?, updated_at=?
       WHERE observation_key=? AND work_key=?
         AND EXISTS (
           SELECT 1 FROM jsda_acquisition_jobs_v3
            WHERE work_key=? AND attempt=? AND state=?
              AND audit_receipt_key=? AND audit_receipt_digest=?
         )`,
    )
    .bind(
      expectedState,
      event.contentDigest,
      event.rawKey,
      event.occurredAt,
      event.occurredAt,
      row.work_key,
      row.work_key,
      row.work_key,
      row.attempt,
      expectedState,
      event.audit.key,
      event.audit.digest,
    );
}

function casCurrentSourceObjectStatement(
  db: D1Database,
  row: JobRow,
  event: RunEvent,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_source_objects
          SET current_digest = CASE
                WHEN current_observation_seq IS NULL
                  OR current_observation_seq < obs.observation_seq
                THEN obs.content_digest ELSE current_digest
              END,
              current_raw_key = CASE
                WHEN current_observation_seq IS NULL
                  OR current_observation_seq < obs.observation_seq
                THEN obs.raw_key ELSE current_raw_key
              END,
              current_observation_key = CASE
                WHEN current_observation_seq IS NULL
                  OR current_observation_seq < obs.observation_seq
                THEN obs.observation_key ELSE current_observation_key
              END,
              current_observation_seq = CASE
                WHEN current_observation_seq IS NULL
                  OR current_observation_seq < obs.observation_seq
                THEN obs.observation_seq ELSE current_observation_seq
              END,
              last_observed_at = CASE
                WHEN current_observation_seq IS NULL
                  OR current_observation_seq < obs.observation_seq
                THEN ? ELSE last_observed_at
              END,
              updated_at=?
         FROM jsda_observations AS obs
        WHERE jsda_source_objects.source_object_id = obs.source_object_id
          AND jsda_source_objects.source_object_id=?
          AND obs.observation_key=?
          AND obs.work_key=?
          AND obs.state='completed'
          AND obs.content_digest=?
          AND obs.raw_key=?
          AND EXISTS (
            SELECT 1 FROM jsda_acquisition_jobs_v3
             WHERE work_key=? AND attempt=? AND state='completed'
               AND audit_receipt_key=? AND audit_receipt_digest=?
          )
          AND (
            jsda_source_objects.current_observation_seq IS NULL
            OR jsda_source_objects.current_observation_seq < obs.observation_seq
            OR (
              jsda_source_objects.current_observation_seq = obs.observation_seq
              AND jsda_source_objects.current_digest = obs.content_digest
              AND jsda_source_objects.current_raw_key = obs.raw_key
              AND jsda_source_objects.current_observation_key = obs.observation_key
            )
            OR jsda_source_objects.current_observation_seq > obs.observation_seq
          )`,
    )
    .bind(
      event.occurredAt,
      event.occurredAt,
      row.source_object_id,
      row.work_key,
      row.work_key,
      event.contentDigest,
      event.rawKey,
      row.work_key,
      row.attempt,
      event.audit.key,
      event.audit.digest,
    );
}

function insertRunTerminalLogStatement(
  db: D1Database,
  job: Pick<JobRow, "work_key" | "run_key" | "dataset" | "job_type" | "segment_id" | "attempt">,
  event: RunEvent,
  expectedState: JobState,
): D1PreparedStatement {
  return db
    .prepare(
      `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
       SELECT ?, 'jsda', 'cloudflare_queue_v2',
              CASE rc.closure_state
                WHEN 'completed' THEN 'pass'
                WHEN 'partial' THEN 'partial'
                ELSE 'fail'
              END,
              ?
         FROM jsda_run_closures AS rc
        WHERE rc.run_key=?
          AND rc.closure_state IN ('completed', 'failed', 'partial')
          AND EXISTS (
            SELECT 1 FROM jsda_acquisition_jobs_v3
             WHERE work_key=? AND attempt=? AND state=? AND job_type='discover_root'
               AND audit_receipt_key=? AND audit_receipt_digest=?
          )
          AND (
            (rc.closure_state='completed'
             AND rc.frontier_exhausted=1
             AND rc.descendant_total > 0
             AND rc.descendant_completed = rc.descendant_total
             AND rc.descendant_rejected = 0
             AND rc.descendant_failed_transient = 0
             AND rc.descendant_nonterminal = 0)
            OR rc.descendant_rejected > 0
          )
          AND NOT EXISTS (
            SELECT 1 FROM ingestion_run_log
             WHERE source='jsda'
               AND runtime='cloudflare_queue_v2'
               AND json_extract(detail, '$.run_id') = ?
               AND json_extract(detail, '$.result') = ?
               AND json_extract(detail, '$.job_id') = ?
               AND json_extract(detail, '$.audit_receipt_digest') = ?
          )`,
    )
    .bind(
      event.occurredAt,
      detailJson(job, event),
      job.run_key,
      job.work_key,
      job.attempt,
      expectedState,
      event.audit.key,
      event.audit.digest,
      job.run_key,
      event.result,
      job.work_key,
      event.audit.digest,
    );
}

function requireBatch(results: D1Result[], message: string): void {
  // D1 includes rows written by triggers in meta.changes, so a fenced job
  // UPDATE that syncs run membership can report more than one change.
  if (results.some((result) => (result?.meta.changes ?? 0) < 1)) {
    throw new Error(message);
  }
}

function recomputeJobClosureStatement(
  db: D1Database,
  parent: Pick<JobRow, "work_key" | "run_key">,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_job_closures
          SET descendant_total=(
                SELECT COUNT(*) FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
              ),
              descendant_completed=(
                SELECT COUNT(*) FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
                   AND ${MEMBERSHIP_COMPLETED}
              ),
              descendant_rejected=(
                SELECT COUNT(*) FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
                   AND terminal_state='rejected'
              ),
              descendant_failed_transient=(
                SELECT COUNT(*) FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
                   AND terminal_state='failed_transient'
              ),
              descendant_nonterminal=(
                SELECT COUNT(*) FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
                   AND terminal_state IN ('pending','queued','running','waiting_children')
              ),
              failure_work_key=(
                SELECT child_work_key FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
                   AND terminal_state='rejected'
                 ORDER BY updated_at, child_work_key LIMIT 1
              ),
              failure_detail=(
                SELECT failure_detail FROM jsda_run_membership
                 WHERE parent_work_key=? AND run_key=?
                   AND terminal_state='rejected'
                 ORDER BY updated_at, child_work_key LIMIT 1
              ),
              failure_reason_code=CASE
                WHEN (
                  SELECT COUNT(*) FROM jsda_run_membership
                   WHERE parent_work_key=? AND run_key=?
                     AND terminal_state='rejected'
                ) > 0 THEN 'descendant_rejected'
                ELSE failure_reason_code
              END,
              updated_at=?
        WHERE work_key=?`,
    )
    .bind(
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      parent.work_key,
      parent.run_key,
      now,
      parent.work_key,
    );
}

function recomputeRunClosureStatement(
  db: D1Database,
  runKey: string,
  rootWorkKey: string,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_run_closures
          SET descendant_total=(
                SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
                 WHERE run_key=?
              ),
              descendant_completed=(
                SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
                 WHERE run_key=? AND ${MEMBERSHIP_COMPLETED}
              ),
              descendant_rejected=(
                SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
                 WHERE run_key=? AND terminal_state='rejected'
              ),
              descendant_failed_transient=(
                SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
                 WHERE run_key=? AND terminal_state='failed_transient'
              ),
              descendant_nonterminal=(
                SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
                 WHERE run_key=?
                   AND terminal_state IN ('pending','queued','running','waiting_children')
              ),
              frontier_exhausted=CASE
                WHEN (
                  SELECT state FROM jsda_acquisition_jobs_v3 WHERE work_key=?
                ) IN ('waiting_children','completed','rejected') THEN 1
                ELSE frontier_exhausted
              END,
              failure_work_key=(
                SELECT child_work_key FROM jsda_run_membership
                 WHERE run_key=? AND terminal_state='rejected'
                 ORDER BY updated_at, child_work_key LIMIT 1
              ),
              failure_detail=(
                SELECT failure_detail FROM jsda_run_membership
                 WHERE run_key=? AND terminal_state='rejected'
                 ORDER BY updated_at, child_work_key LIMIT 1
              ),
              failure_reason_code=CASE
                WHEN (
                  SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
                   WHERE run_key=? AND terminal_state='rejected'
                ) > 0 THEN 'descendant_rejected'
                ELSE failure_reason_code
              END,
              updated_at=?
        WHERE run_key=?`,
    )
    .bind(
      runKey,
      runKey,
      runKey,
      runKey,
      runKey,
      rootWorkKey,
      runKey,
      runKey,
      runKey,
      now,
      runKey,
    );
}

function applyRunClosureStateStatement(
  db: D1Database,
  runKey: string,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_run_closures
          SET closure_state=CASE
                WHEN descendant_rejected > 0 AND descendant_completed > 0 THEN 'partial'
                WHEN descendant_rejected > 0 THEN 'failed'
                WHEN closure_state IN ('failed','partial') THEN closure_state
                WHEN frontier_exhausted=1
                 AND descendant_total > 0
                 AND descendant_completed = descendant_total
                 AND descendant_rejected = 0
                 AND descendant_failed_transient = 0
                 AND descendant_nonterminal = 0 THEN 'completed'
                WHEN frontier_exhausted=1 THEN 'waiting_children'
                ELSE 'open'
              END,
              closed_at=CASE
                WHEN descendant_rejected > 0 THEN COALESCE(closed_at, ?)
                WHEN closure_state IN ('failed','partial') THEN closed_at
                WHEN frontier_exhausted=1
                 AND descendant_total > 0
                 AND descendant_completed = descendant_total
                 AND descendant_rejected = 0
                 AND descendant_failed_transient = 0
                 AND descendant_nonterminal = 0 THEN COALESCE(closed_at, ?)
                ELSE closed_at
              END,
              updated_at=?
        WHERE run_key=?`,
    )
    .bind(now, now, now, runKey);
}

function applyJobClosureStateStatement(
  db: D1Database,
  workKey: string,
  now: string,
): D1PreparedStatement {
  return db
    .prepare(
      `UPDATE jsda_job_closures
          SET closure_state=CASE
                WHEN descendant_rejected > 0 AND descendant_completed > 0 THEN 'partial'
                WHEN descendant_rejected > 0 THEN 'failed'
                WHEN closure_state IN ('failed','partial') THEN closure_state
                WHEN frontier_exhausted=1
                 AND descendant_total > 0
                 AND descendant_completed = descendant_total
                 AND descendant_rejected = 0
                 AND descendant_failed_transient = 0
                 AND descendant_nonterminal = 0 THEN 'completed'
                WHEN frontier_exhausted=1 THEN 'waiting_children'
                ELSE 'open'
              END,
              closed_at=CASE
                WHEN descendant_rejected > 0 THEN COALESCE(closed_at, ?)
                WHEN closure_state IN ('failed','partial') THEN closed_at
                WHEN frontier_exhausted=1
                 AND descendant_total > 0
                 AND descendant_completed = descendant_total
                 AND descendant_rejected = 0
                 AND descendant_failed_transient = 0
                 AND descendant_nonterminal = 0 THEN COALESCE(closed_at, ?)
                ELSE closed_at
              END,
              updated_at=?
        WHERE work_key=?`,
    )
    .bind(now, now, now, workKey);
}

export async function registerJob(db: D1Database, job: JsdaQueueJob): Promise<JobRow> {
  const rows = await registerJobs(db, [job]);
  return rows[0];
}

export async function registerJobs(
  db: D1Database,
  jobs: readonly JsdaQueueJob[],
): Promise<JobRow[]> {
  if (jobs.length === 0) return [];
  const now = new Date().toISOString();
  const identities = await Promise.all(jobs.map((job) => fileIdentity(job)));
  const statements: D1PreparedStatement[] = [];
  jobs.forEach((job, index) => {
    const identity = identities[index];
    if (identity !== null) {
      statements.push(insertSourceObjectStatement(db, job, identity, now));
    }
  });
  jobs.forEach((job, index) => {
    statements.push(insertJobStatement(db, job, identities[index], now));
  });
  jobs.forEach((job, index) => {
    const identity = identities[index];
    if (identity !== null) {
      statements.push(backfillIdentityStatement(db, job, identity, now));
      statements.push(...allocateObservationStatements(db, job, identity, now));
      statements.push(...backfillCompletedObservationStatements(db, job, identity, now));
    }
  });
  for (const job of jobs) {
    if (job.parent_work_key === null) continue;
    statements.push(
      db
        .prepare(
          `INSERT OR IGNORE INTO jsda_acquisition_discoveries_v3
           (parent_work_key, child_work_key, run_key, discovered_at)
           VALUES (?, ?, ?, ?)`,
        )
        .bind(job.parent_work_key, job.work_key, job.run_key, now),
    );
    const membership = insertMembershipStatement(db, job, now);
    if (membership !== null) statements.push(membership);
  }
  for (const job of jobs) {
    if (job.job_type === "discover_root") {
      statements.push(insertRunClosureStatement(db, job, now));
    }
    const closure = insertJobClosureStatement(db, job, now);
    if (closure !== null) statements.push(closure);
  }
  await db.batch(statements);
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
    .prepare(`SELECT ${JOB_SELECT} FROM jsda_acquisition_jobs_v3 WHERE work_key = ?`)
    .bind(workKey)
    .first<JobRow>();
}

export async function loadJobClosure(
  db: D1Database,
  workKey: string,
): Promise<JobClosureRow | null> {
  return db
    .prepare(`SELECT ${CLOSURE_SELECT} FROM jsda_job_closures WHERE work_key = ?`)
    .bind(workKey)
    .first<JobClosureRow>();
}

export async function loadRunClosure(
  db: D1Database,
  runKey: string,
): Promise<RunClosureRow | null> {
  return db
    .prepare(`SELECT ${RUN_CLOSURE_SELECT} FROM jsda_run_closures WHERE run_key = ?`)
    .bind(runKey)
    .first<RunClosureRow>();
}

export async function loadRunMembership(
  db: D1Database,
  runKey: string,
): Promise<RunMembershipRow[]> {
  const rows = await db
    .prepare(
      `SELECT ${MEMBERSHIP_SELECT}
         FROM jsda_run_membership
        WHERE run_key=?
        ORDER BY parent_work_key, child_work_key`,
    )
    .bind(runKey)
    .all<RunMembershipRow>();
  return rows.results;
}

export async function propagateTerminalAdoptedMemberships(
  db: D1Database,
  row: JobRow,
  now: string,
): Promise<RunMembershipRow[]> {
  if (row.state !== "completed" && row.state !== "rejected") return [];
  if (row.audit_receipt_key === null || row.audit_receipt_digest === null) {
    throw new Error(`JSDA terminal adoption missing audit evidence: ${row.work_key}`);
  }
  if (
    row.state === "completed" &&
    (row.content_digest === null || row.raw_key === null)
  ) {
    throw new Error(`JSDA completed adoption missing raw evidence: ${row.work_key}`);
  }

  const affected = await db
    .prepare(
      `SELECT ${MEMBERSHIP_SELECT}
         FROM jsda_run_membership
        WHERE child_work_key=? AND membership_kind='adopted'
          AND (
            terminal_state=? OR terminal_state IN
              ('pending','queued','running','waiting_children','failed_transient')
          )
        ORDER BY run_key, parent_work_key`,
    )
    .bind(row.work_key, row.state)
    .all<RunMembershipRow>();
  if (affected.results.length === 0) return [];

  await db
    .prepare(
      `UPDATE jsda_run_membership
          SET terminal_state=?,
              content_digest=?,
              raw_key=?,
              audit_receipt_key=?,
              audit_receipt_digest=?,
              failure_reason_code=?,
              failure_detail=?,
              updated_at=?
        WHERE child_work_key=? AND membership_kind='adopted'
          AND (
            terminal_state=? OR terminal_state IN
              ('pending','queued','running','waiting_children','failed_transient')
          )`,
    )
    .bind(
      row.state,
      row.content_digest,
      row.raw_key,
      row.audit_receipt_key,
      row.audit_receipt_digest,
      row.state === "rejected" ? "rejected" : null,
      row.state === "rejected" ? row.last_error : null,
      now,
      row.work_key,
      row.state,
    )
    .run();

  const expected = row.state;
  for (const membership of affected.results) {
    const current = await db
      .prepare(
        `SELECT terminal_state, content_digest, raw_key,
                audit_receipt_key, audit_receipt_digest
           FROM jsda_run_membership
          WHERE run_key=? AND parent_work_key=? AND child_work_key=?`,
      )
      .bind(
        membership.run_key,
        membership.parent_work_key,
        membership.child_work_key,
      )
      .first<
        Pick<
          RunMembershipRow,
          | "terminal_state"
          | "content_digest"
          | "raw_key"
          | "audit_receipt_key"
          | "audit_receipt_digest"
        >
      >();
    if (
      current?.terminal_state !== expected ||
      current.audit_receipt_key !== row.audit_receipt_key ||
      current.audit_receipt_digest !== row.audit_receipt_digest ||
      (expected === "completed" &&
        (current.content_digest !== row.content_digest ||
          current.raw_key !== row.raw_key))
    ) {
      throw new Error(
        `JSDA adopted membership did not converge: ${membership.run_key}/${row.work_key}`,
      );
    }
  }
  return affected.results;
}

export async function rejectAdoptedMembership(
  db: D1Database,
  runKey: string,
  childWorkKey: string,
  detail: string,
  audit: AuditRef,
  now: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE jsda_run_membership
          SET terminal_state='rejected',
              content_digest=NULL,
              raw_key=NULL,
              audit_receipt_key=?,
              audit_receipt_digest=?,
              failure_reason_code='adopted_evidence_missing',
              failure_detail=?,
              updated_at=?
        WHERE run_key=? AND child_work_key=?
          AND membership_kind='adopted'
          AND terminal_state IN ('completed','rejected')`,
    )
    .bind(
      audit.key,
      audit.digest,
      detail.slice(0, 500),
      now,
      runKey,
      childWorkKey,
    )
    .run();
  if ((result.meta.changes ?? 0) < 1) {
    const current = await db
      .prepare(
        `SELECT terminal_state, failure_reason_code
           FROM jsda_run_membership
          WHERE run_key=? AND child_work_key=? AND membership_kind='adopted'`,
      )
      .bind(runKey, childWorkKey)
      .first<{ terminal_state: string; failure_reason_code: string | null }>();
    if (
      current?.terminal_state !== "rejected" ||
      current.failure_reason_code !== "adopted_evidence_missing"
    ) {
      throw new Error(`JSDA adopted membership rejection lost: ${childWorkKey}`);
    }
  }
}

export async function loadPendingRunJobs(
  db: D1Database,
  runKey: string,
): Promise<JobRow[]> {
  const rows = await db
    .prepare(
      `SELECT ${JOB_SELECT}
         FROM jsda_acquisition_jobs_v3
        WHERE run_key=? AND state IN ('pending', 'failed_transient')
        ORDER BY work_key`,
    )
    .bind(runKey)
    .all<JobRow>();
  return rows.results;
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
          `UPDATE jsda_acquisition_jobs_v3
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
      `UPDATE jsda_acquisition_jobs_v3
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
  row: Pick<JobRow, "work_key" | "attempt">,
  frontierJson: string,
  rawKey: string,
  contentDigest: string,
  now: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v3
       SET frontier_json=?, raw_key=?, content_digest=?, updated_at=?
       WHERE work_key=? AND state='running' AND attempt=?`,
    )
    .bind(frontierJson, rawKey, contentDigest, now, row.work_key, row.attempt)
    .run();
  if ((result.meta.changes ?? 0) < 1) {
    throw new Error(`JSDA frontier update lost job claim: ${row.work_key}`);
  }
}

export async function persistFetchedArtifact(
  db: D1Database,
  row: Pick<
    JobRow,
    "work_key" | "attempt" | "dataset" | "source_object_id"
  >,
  rawKey: string,
  contentDigest: string,
  now: string,
): Promise<void> {
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET raw_key=?, content_digest=?, updated_at=?
         WHERE work_key=? AND state='running' AND attempt=?`,
      )
      .bind(rawKey, contentDigest, now, row.work_key, row.attempt),
    ...insertArtifactStatements(
      db,
      { content_digest: contentDigest, raw_key: rawKey, dataset: row.dataset },
      now,
    ),
  ];
  if (row.source_object_id !== null) {
    statements.push(
      db
        .prepare(
          `UPDATE jsda_observations
           SET content_digest=?, raw_key=?, updated_at=?
           WHERE observation_key=? AND work_key=?
             AND EXISTS (
               SELECT 1 FROM jsda_acquisition_jobs_v3
                WHERE work_key=? AND state='running' AND attempt=?
                  AND raw_key=? AND content_digest=?
             )`,
        )
        .bind(
          contentDigest,
          rawKey,
          now,
          row.work_key,
          row.work_key,
          row.work_key,
          row.attempt,
          rawKey,
          contentDigest,
        ),
    );
  }
  const results = await db.batch(statements);
  if ((results[0]?.meta.changes ?? 0) < 1) {
    throw new Error(`JSDA artifact update lost job claim: ${row.work_key}`);
  }
  if (row.source_object_id !== null && (results[results.length - 1]?.meta.changes ?? 0) < 1) {
    throw new Error(`JSDA observation artifact update lost job claim: ${row.work_key}`);
  }
}

export async function advanceContinuationCursor(
  db: D1Database,
  row: JobRow,
  nextCursor: number,
  now: string,
): Promise<void> {
  const result = await db
    .prepare(
      `UPDATE jsda_acquisition_jobs_v3
       SET cursor=?, updated_at=?
       WHERE work_key=? AND state='running' AND attempt=?`,
    )
    .bind(nextCursor, now, row.work_key, row.attempt)
    .run();
  if ((result.meta.changes ?? 0) < 1) {
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
        `UPDATE jsda_acquisition_jobs_v3
         SET state='queued', cursor=?, enqueued_at=?, updated_at=?,
             audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running' AND attempt=?`,
      )
      .bind(
        nextCursor,
        now,
        now,
        audit.key,
        audit.digest,
        row.work_key,
        row.attempt,
      ),
    insertEventStatement(db, row, event, "queued"),
  ]);
  requireBatch(results, `JSDA continuation finalize lost job claim: ${row.work_key}`);
}

export async function markFrontierExhausted(
  db: D1Database,
  row: JobRow,
  cursor: number,
  audit: AuditRef,
  now: string,
): Promise<void> {
  const event: RunEvent = {
    result: "frontier_exhausted",
    reasonCode: null,
    detail: "discovery frontier exhausted; waiting for governed descendants",
    cursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit,
    occurredAt: now,
  };
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET state='waiting_children', cursor=?, lease_until=NULL, updated_at=?,
             last_error=NULL, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running' AND attempt=?`,
      )
      .bind(cursor, now, audit.key, audit.digest, row.work_key, row.attempt),
    insertEventStatement(db, row, event, "waiting_children"),
    db
      .prepare(
        `UPDATE jsda_job_closures
            SET frontier_exhausted=1,
                closure_state='waiting_children',
                updated_at=?
          WHERE work_key=?`,
      )
      .bind(now, row.work_key),
  ];
  if (row.job_type === "discover_root") {
    statements.push(
      db
        .prepare(
          `UPDATE jsda_run_closures
              SET frontier_exhausted=1,
                  closure_state=CASE
                    WHEN closure_state IN ('completed','failed','partial') THEN closure_state
                    ELSE 'waiting_children'
                  END,
                  updated_at=?
            WHERE run_key=?`,
        )
        .bind(now, row.run_key),
    );
  }
  const results = await db.batch(statements);
  requireBatch(
    results.slice(0, 2),
    `JSDA frontier exhaustion lost job claim: ${row.work_key}`,
  );
  if ((results[2]?.meta.changes ?? 0) < 1) {
    throw new Error(`JSDA job closure missing at frontier exhaustion: ${row.work_key}`);
  }
  if (row.job_type === "discover_root" && (results[3]?.meta.changes ?? 0) < 1) {
    throw new Error(`JSDA run closure missing at frontier exhaustion: ${row.run_key}`);
  }
}

export async function completeJob(
  db: D1Database,
  row: JobRow,
  cursor: number,
  audit: AuditRef,
  now: string,
): Promise<void> {
  if (row.job_type !== "fetch_file") {
    throw new Error(`JSDA completeJob is leaf-only: ${row.work_key}`);
  }
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
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET state='completed', cursor=?, lease_until=NULL, completed_at=?, updated_at=?,
             last_error=NULL, content_digest=?, raw_key=?,
             audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running' AND attempt=?
           AND content_digest IS NOT NULL AND raw_key IS NOT NULL
           AND (
             source_object_id IS NOT NULL AND EXISTS (
               SELECT 1 FROM jsda_observations AS observation
                WHERE observation.observation_key=jsda_acquisition_jobs_v3.work_key
                  AND observation.work_key=jsda_acquisition_jobs_v3.work_key
                  AND observation.source_object_id=
                      jsda_acquisition_jobs_v3.source_object_id
             )
           )`,
      )
      .bind(
        cursor,
        now,
        now,
        row.content_digest,
        row.raw_key,
        audit.key,
        audit.digest,
        row.work_key,
        row.attempt,
      ),
    insertEventStatement(db, row, event, "completed"),
    ...insertArtifactStatements(db, row, now),
  ];
  const required = 2;
  if (row.source_object_id !== null) {
    statements.push(updateObservationTerminalStatement(db, row, event, "completed"));
    statements.push(casCurrentSourceObjectStatement(db, row, event));
  }
  const results = await db.batch(statements);
  const requiredResults = results.slice(0, required);
  const observationResults =
    row.source_object_id === null ? [] : results.slice(-2);
  if (
    [...requiredResults, ...observationResults].some(
      (result) => (result?.meta.changes ?? 0) < 1,
    )
  ) {
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
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET state='rejected', lease_until=NULL, completed_at=?, updated_at=?,
             last_error=?, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running' AND attempt=?
           AND (
             job_type != 'fetch_file' OR (
               source_object_id IS NOT NULL AND EXISTS (
                 SELECT 1 FROM jsda_observations AS observation
                  WHERE observation.observation_key=jsda_acquisition_jobs_v3.work_key
                    AND observation.work_key=jsda_acquisition_jobs_v3.work_key
                    AND observation.source_object_id=
                        jsda_acquisition_jobs_v3.source_object_id
               )
             )
           )`,
      )
      .bind(
        now,
        now,
        detail.slice(0, 500),
        audit.key,
        audit.digest,
        row.work_key,
        row.attempt,
      ),
    insertEventStatement(db, row, event, "rejected"),
  ];
  if (row.source_object_id !== null) {
    statements.push(updateObservationTerminalStatement(db, row, event, "rejected"));
  }
  const results = await db.batch(statements);
  if (results.some((result) => (result?.meta.changes ?? 0) < 1)) {
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
        `UPDATE jsda_acquisition_jobs_v3
         SET state='failed_transient', lease_until=NULL, updated_at=?, last_error=?,
             audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='running' AND attempt=?`,
      )
      .bind(
        now,
        detail.slice(0, 500),
        audit.key,
        audit.digest,
        row.work_key,
        row.attempt,
      ),
    insertEventStatement(db, row, event, "failed_transient"),
  ]);
  requireBatch(results, `JSDA transient failure lost job claim: ${row.work_key}`);
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

export async function loadAncestorChain(db: D1Database, row: JobRow): Promise<JobRow[]> {
  const chain: JobRow[] = [];
  let parentKey = row.parent_work_key;
  while (parentKey !== null) {
    const parent = await loadJob(db, parentKey);
    if (parent === null) {
      throw new Error(`JSDA ancestor missing for ${row.work_key}: ${parentKey}`);
    }
    chain.push(parent);
    parentKey = parent.parent_work_key;
  }
  return chain;
}

export async function recomputeClosureAggregates(
  db: D1Database,
  origin: JobRow,
  now: string,
): Promise<void> {
  const chain: JobRow[] = [];
  if (origin.job_type !== "fetch_file") chain.push(origin);
  chain.push(...(await loadAncestorChain(db, origin)));
  const statements: D1PreparedStatement[] = [];
  for (const ancestor of chain) {
    statements.push(recomputeJobClosureStatement(db, ancestor, now));
    statements.push(applyJobClosureStateStatement(db, ancestor.work_key, now));
  }
  statements.push(recomputeRunClosureStatement(db, origin.run_key, origin.run_key, now));
  statements.push(applyRunClosureStateStatement(db, origin.run_key, now));
  const results = await db.batch(statements);
  if (results.some((result) => (result?.meta.changes ?? 0) < 1)) {
    throw new Error(`JSDA closure aggregate update failed for ${origin.work_key}`);
  }
}

export async function completeWaitingAncestor(
  db: D1Database,
  row: JobRow,
  audit: AuditRef,
  now: string,
): Promise<boolean> {
  const event: RunEvent = {
    result: "completed",
    reasonCode: null,
    detail: "all governed descendants durably completed",
    cursor: row.cursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit,
    occurredAt: now,
  };
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET state='completed', lease_until=NULL, completed_at=?, updated_at=?,
             last_error=NULL, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state='waiting_children'
           AND EXISTS (
             SELECT 1 FROM jsda_job_closures
              WHERE work_key=?
                AND frontier_exhausted=1
                AND descendant_total > 0
                AND descendant_completed = descendant_total
                AND descendant_rejected = 0
                AND descendant_failed_transient = 0
                AND descendant_nonterminal = 0
           )`,
      )
      .bind(now, now, audit.key, audit.digest, row.work_key, row.work_key),
    insertEventStatement(db, row, event, "completed"),
    recomputeJobClosureStatement(db, row, now),
    applyJobClosureStateStatement(db, row.work_key, now),
  ];
  if (row.job_type === "discover_root") {
    statements.push(recomputeRunClosureStatement(db, row.run_key, row.run_key, now));
    statements.push(applyRunClosureStateStatement(db, row.run_key, now));
    statements.push(insertRunTerminalLogStatement(db, row, event, "completed"));
  }
  const results = await db.batch(statements);
  const closed = (results[0]?.meta.changes ?? 0) >= 1;
  if (closed) {
    requireBatch(results.slice(1, 2), `JSDA ancestor close lost evidence: ${row.work_key}`);
  }
  return closed;
}

export async function failWaitingAncestor(
  db: D1Database,
  row: JobRow,
  reasonCode: string,
  detail: string,
  audit: AuditRef,
  now: string,
): Promise<boolean> {
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
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET state='rejected', lease_until=NULL, completed_at=?, updated_at=?,
             last_error=?, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state IN ('waiting_children', 'completed')
           AND EXISTS (
             SELECT 1 FROM jsda_job_closures
              WHERE work_key=? AND descendant_rejected > 0
           )`,
      )
      .bind(
        now,
        now,
        detail.slice(0, 500),
        audit.key,
        audit.digest,
        row.work_key,
        row.work_key,
      ),
    insertEventStatement(db, row, event, "rejected"),
    recomputeJobClosureStatement(db, row, now),
    applyJobClosureStateStatement(db, row.work_key, now),
  ];
  if (row.job_type === "discover_root") {
    statements.push(recomputeRunClosureStatement(db, row.run_key, row.run_key, now));
    statements.push(applyRunClosureStateStatement(db, row.run_key, now));
    statements.push(insertRunTerminalLogStatement(db, row, event, "rejected"));
  }
  const results = await db.batch(statements);
  const failed = (results[0]?.meta.changes ?? 0) >= 1;
  if (failed) {
    requireBatch(results.slice(1, 2), `JSDA ancestor fail lost evidence: ${row.work_key}`);
  }
  return failed;
}

export async function ensureRunTerminalLog(
  db: D1Database,
  row: JobRow,
  now: string,
): Promise<void> {
  if (row.job_type !== "discover_root") return;
  if (row.state !== "completed" && row.state !== "rejected") return;
  if (row.audit_receipt_key === null || row.audit_receipt_digest === null) {
    throw new Error(`JSDA root terminal log missing audit: ${row.work_key}`);
  }
  const event: RunEvent = {
    result: row.state === "rejected" ? "rejected" : "completed",
    reasonCode: row.state === "rejected" ? "descendant_rejected" : null,
    detail:
      row.state === "rejected"
        ? (row.last_error ?? "governed run rejected")
        : "all governed descendants durably completed",
    cursor: row.cursor,
    rawKey: row.raw_key,
    contentDigest: row.content_digest,
    audit: { key: row.audit_receipt_key, digest: row.audit_receipt_digest },
    occurredAt: now,
  };
  const result = await insertRunTerminalLogStatement(db, row, event, row.state).run();
  if ((result.meta.changes ?? 0) < 0) {
    throw new Error(`JSDA run terminal log write failed: ${row.work_key}`);
  }
  const persisted = await db
    .prepare(
      `SELECT status FROM ingestion_run_log
        WHERE source='jsda' AND runtime='cloudflare_queue_v2'
          AND json_extract(detail, '$.run_id')=?
          AND json_extract(detail, '$.result')=?
          AND json_extract(detail, '$.job_id')=?
          AND json_extract(detail, '$.audit_receipt_digest')=?
        ORDER BY id DESC LIMIT 1`,
    )
    .bind(row.run_key, event.result, row.work_key, row.audit_receipt_digest)
    .first<{ status: string }>();
  if (
    persisted === null ||
    (row.state === "completed"
      ? persisted.status !== "pass"
      : persisted.status === "pass")
  ) {
    throw new Error(`JSDA run terminal log is not authoritative: ${row.work_key}`);
  }
}

export async function rejectFromDeadLetter(
  db: D1Database,
  row: JobRow,
  reasonCode: string,
  detail: string,
  audit: AuditRef,
  now: string,
): Promise<boolean> {
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
  const statements: D1PreparedStatement[] = [
    db
      .prepare(
        `UPDATE jsda_acquisition_jobs_v3
         SET state='rejected', lease_until=NULL, completed_at=?, updated_at=?,
             last_error=?, audit_receipt_key=?, audit_receipt_digest=?
         WHERE work_key=? AND state IN
           ('pending', 'queued', 'running', 'waiting_children', 'failed_transient')
           AND (
             job_type != 'fetch_file' OR (
               source_object_id IS NOT NULL AND EXISTS (
                 SELECT 1 FROM jsda_observations AS observation
                  WHERE observation.observation_key=jsda_acquisition_jobs_v3.work_key
                    AND observation.work_key=jsda_acquisition_jobs_v3.work_key
                    AND observation.source_object_id=
                        jsda_acquisition_jobs_v3.source_object_id
               )
             )
           )`,
      )
      .bind(
        now,
        now,
        detail.slice(0, 500),
        audit.key,
        audit.digest,
        row.work_key,
      ),
    insertEventStatement(db, { ...row, attempt: row.attempt }, event, "rejected"),
  ];
  if (row.source_object_id !== null) {
    statements.push(updateObservationTerminalStatement(db, { ...row, state: "rejected" }, event, "rejected"));
  }
  const results = await db.batch(statements);
  const rejected = (results[0]?.meta.changes ?? 0) >= 1;
  if (rejected && (results[1]?.meta.changes ?? 0) < 1) {
    throw new Error(`JSDA DLQ reject lost evidence: ${row.work_key}`);
  }
  if (
    rejected &&
    row.source_object_id !== null &&
    (results[2]?.meta.changes ?? 0) < 1
  ) {
    throw new Error(`JSDA DLQ reject lost observation: ${row.work_key}`);
  }
  return rejected;
}
