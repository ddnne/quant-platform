import type { JsdaWorkerEnv } from "./env";
import { markJobsQueued, registerJobs } from "./job_store";
import {
  DATASET_IDS,
  JSDA_QUEUE_JOB_VERSION,
  makeRootJob,
  type DatasetId,
  type JsdaQueueJob,
  type RequestedBy,
} from "./queue_contract";

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
  // Reuse the persisted identity on recovery. A later root may rediscover the
  // same URL under a different parent; only the first governed identity may be
  // retried for that stable work key.
  const eligible = rows
    .filter((row) => row.state === "pending" || row.state === "failed_transient")
    .map(persistedMessage);
  if (eligible.length === 0) return [];
  await env.JSDA_QUEUE.sendBatch(eligible.map(queueMessage));
  await markJobsQueued(
    env.DB,
    eligible.map((job) => job.work_key),
    new Date().toISOString(),
  );
  return eligible;
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
