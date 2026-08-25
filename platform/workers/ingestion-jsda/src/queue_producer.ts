import type { JsdaWorkerEnv } from "./env";
import {
  loadJob,
  loadPendingRunJobs,
  markJobsQueued,
  recomputeClosureAggregates,
  rejectAdoptedMembership,
  registerJobs,
  type JobRow,
} from "./job_store";
import {
  DATASET_IDS,
  JSDA_QUEUE_JOB_VERSION,
  makeRootJob,
  type DatasetId,
  type JsdaQueueJob,
  type RequestedBy,
} from "./queue_contract";
import { putQueueAuditReceipt } from "./raw_store";

function queueMessage(job: JsdaQueueJob): MessageSendRequest<JsdaQueueJob> {
  return { body: job, contentType: "json" };
}

function persistedMessage(
  row: Awaited<ReturnType<typeof registerJobs>>[number],
): JsdaQueueJob {
  return {
    version: JSDA_QUEUE_JOB_VERSION,
    work_key: row.work_key,
    run_key: row.run_key,
    job_type: row.job_type,
    dataset: row.dataset,
    target_url: row.target_url,
    segment_id: row.segment_id,
    parent_work_key: row.parent_work_key,
    cursor: row.cursor,
    attempt: row.attempt,
    requested_by: row.requested_by,
    requested_at: row.requested_at,
    contract_digest: row.contract_digest,
  };
}

export async function enqueueRegisteredJobs(
  env: JsdaWorkerEnv,
  jobs: readonly JsdaQueueJob[],
): Promise<JsdaQueueJob[]> {
  if (jobs.length === 0) return [];
  const rows = await registerJobs(env.DB, jobs);
  await validateAdoptedEvidence(env, jobs, rows);
  // Observation identity is stable under Queue redelivery. A completed
  // archive observation keeps that URL complete; a completed rolling
  // observation does not complete later runs of the same URL.
  const eligible = rows
    .filter((row) => row.state === "pending" || row.state === "failed_transient")
    .map(persistedMessage);
  if (eligible.length > 0) {
    await env.JSDA_QUEUE.sendBatch(eligible.map(queueMessage));
    await markJobsQueued(
      env.DB,
      eligible.map((job) => job.work_key),
      new Date().toISOString(),
    );
  }
  await repairIncompleteRunAggregates(env, rows);
  return eligible;
}

async function validateAdoptedEvidence(
  env: JsdaWorkerEnv,
  jobs: readonly JsdaQueueJob[],
  rows: readonly JobRow[],
): Promise<void> {
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    const job = jobs[index];
    if (row.state !== "completed" || row.run_key === job.run_key) continue;
    const completeRef =
      row.audit_receipt_key !== null &&
      row.audit_receipt_digest !== null &&
      row.raw_key !== null &&
      row.content_digest !== null;
    const [auditObject, rawObject] = completeRef
      ? await Promise.all([
          env.RAW_BUCKET.head(row.audit_receipt_key!),
          env.RAW_BUCKET.head(row.raw_key!),
        ])
      : [null, null];
    if (
      completeRef &&
      auditObject?.customMetadata?.sha256 === row.audit_receipt_digest &&
      rawObject?.customMetadata?.sha256 === row.content_digest
    ) {
      continue;
    }
    const now = new Date().toISOString();
    const detail = "adopted archive lacks immutable R2 raw/audit evidence";
    const audit = await putQueueAuditReceipt(env.RAW_BUCKET, {
      event: "rejected_job",
      work_key: row.work_key,
      run_key: job.run_key,
      dataset: row.dataset,
      job_type: row.job_type,
      segment_id: row.segment_id,
      target_url: row.target_url,
      parent_work_key: job.parent_work_key,
      contract_digest: row.contract_digest,
      attempt: row.attempt,
      cursor: row.cursor,
      frontier_size: null,
      raw_key: row.raw_key,
      content_digest: row.content_digest,
      reason_code: "adopted_evidence_missing",
      detail,
      recorded_at: now,
    });
    await rejectAdoptedMembership(
      env.DB,
      job.run_key,
      row.work_key,
      detail,
      audit,
      now,
    );
  }
}

async function repairIncompleteRunAggregates(
  env: JsdaWorkerEnv,
  rows: readonly JobRow[],
): Promise<void> {
  const now = new Date().toISOString();
  const roots = rows.filter((row) => row.job_type === "discover_root");
  for (const root of roots) {
    const current = (await loadJob(env.DB, root.work_key)) ?? root;
    await recomputeClosureAggregates(env.DB, current, now);
    const pending = await loadPendingRunJobs(env.DB, current.run_key);
    if (pending.length === 0) continue;
    await env.JSDA_QUEUE.sendBatch(pending.map((row) => queueMessage(persistedMessage(row))));
    await markJobsQueued(
      env.DB,
      pending.map((row) => row.work_key),
      now,
    );
  }
}

export async function enqueueRoots(
  env: JsdaWorkerEnv,
  requestedBy: RequestedBy,
  onlyDataset?: DatasetId,
  requestedAt = new Date().toISOString(),
): Promise<{ selected: readonly DatasetId[]; queued: JsdaQueueJob[] }> {
  const selected = onlyDataset ? [onlyDataset] : [...DATASET_IDS];
  const roots = await Promise.all(
    selected.map((dataset) => makeRootJob(dataset, requestedBy, requestedAt)),
  );
  return { selected, queued: await enqueueRegisteredJobs(env, roots) };
}

export async function sendContinuation(
  env: JsdaWorkerEnv,
  job: JsdaQueueJob,
): Promise<void> {
  await env.JSDA_QUEUE.send(job, { contentType: "json" });
}
