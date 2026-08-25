import type { JsdaWorkerEnv } from "./env";
import {
  claimJob,
  completeJob,
  loadJob,
  advanceContinuationCursor,
  markContinuationQueued,
  persistFetchedArtifact,
  persistFrontier,
  recordRejectedMessage,
  recordTransientFailure,
  registerJob,
  rejectJob,
  type JobRow,
} from "./job_store";
import {
  CHILD_ENQUEUE_BATCH_SIZE,
  continuationJob,
  descriptorForFile,
  descriptorForYear,
  isJsdaQueueJob,
  makeChildJob,
  queueContractDigest,
  type ChildDescriptor,
  type JsdaQueueJob,
} from "./queue_contract";
import { enqueueRegisteredJobs, sendContinuation } from "./queue_producer";
import { putImmutableRaw, putQueueAuditReceipt } from "./raw_store";
import { sha256Hex } from "./sha256";
import { logOperationalEvent } from "./operational_event";
import {
  PermanentAcquisitionError,
  TransientAcquisitionError,
  extensionOf,
  extractLinks,
  fetchAllowed,
  hostAllowed,
  isYearArchive,
  selectDatasetDataUrls,
} from "./source_http";

const USER_AGENT =
  "quant-platform-ingest/0.1 (+personal-research; JSDA bond stats)";
const LEASE_SECONDS = 15 * 60;
const RETRY_DELAY_SECONDS = 60;

function logError(
  env: JsdaWorkerEnv,
  event: string,
  fields: {
    run_id?: string | null;
    job_id?: string | null;
    segment_id?: string | null;
    dataset?: string | null;
    cursor?: number | null;
    result?: string | null;
    reason?: string | null;
  },
): void {
  logOperationalEvent(env, event, fields);
}

function canonicalBodyJson(body: unknown): string {
  try {
    const value = JSON.stringify(body);
    return value === undefined ? "null" : value;
  } catch {
    return '"unserializable_queue_body"';
  }
}

function auditBodySummary(body: unknown, canonical: string): string {
  const kind = body === null ? "null" : Array.isArray(body) ? "array" : typeof body;
  const keys =
    typeof body === "object" && body !== null && !Array.isArray(body)
      ? Object.keys(body as Record<string, unknown>).sort().slice(0, 64)
      : [];
  return JSON.stringify({ kind, keys, canonical_bytes: canonical.length });
}

function errorDetail(error: unknown): string {
  return (error instanceof Error ? error.message : String(error)).slice(0, 500);
}

function isChildDescriptor(value: unknown): value is ChildDescriptor {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  const keys = Object.keys(candidate).sort();
  return (
    JSON.stringify(keys) === JSON.stringify(["job_type", "segment_id", "target_url"]) &&
    (candidate.job_type === "discover_year" || candidate.job_type === "fetch_file") &&
    typeof candidate.target_url === "string" &&
    hostAllowed(candidate.target_url) &&
    typeof candidate.segment_id === "string" &&
    /^[A-Za-z0-9._-]{1,200}$/.test(candidate.segment_id)
  );
}

function parseFrontier(raw: string): ChildDescriptor[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new PermanentAcquisitionError(
      "frontier_corrupt",
      "persisted JSDA frontier is not JSON",
    );
  }
  if (!Array.isArray(parsed) || !parsed.every(isChildDescriptor)) {
    throw new PermanentAcquisitionError(
      "frontier_corrupt",
      "persisted JSDA frontier violates the v2 child descriptor contract",
    );
  }
  return parsed;
}

function rowMatchesMessage(row: JobRow, job: JsdaQueueJob): boolean {
  return (
    row.work_key === job.work_key &&
    row.run_key === job.run_key &&
    row.dataset === job.dataset &&
    row.job_type === job.job_type &&
    row.target_url === job.target_url &&
    row.segment_id === job.segment_id &&
    row.parent_work_key === job.parent_work_key &&
    row.contract_digest === job.contract_digest &&
    row.requested_by === job.requested_by &&
    row.requested_at === job.requested_at
  );
}

async function terminalAuditIsDurable(
  env: JsdaWorkerEnv,
  row: JobRow,
): Promise<boolean> {
  if (row.audit_receipt_key === null || row.audit_receipt_digest === null) {
    return false;
  }
  const object = await env.RAW_BUCKET.head(row.audit_receipt_key);
  return (
    object !== null &&
    object.customMetadata?.sha256 === row.audit_receipt_digest
  );
}

async function persistRejectedDelivery(
  message: Message<unknown>,
  env: JsdaWorkerEnv,
  reasonCode: string,
): Promise<void> {
  const canonical = canonicalBodyJson(message.body);
  const bodyJson = auditBodySummary(message.body, canonical);
  const bodyDigest = await sha256Hex(new TextEncoder().encode(canonical));
  const rejectedAt = message.timestamp.toISOString();
  const audit = await putQueueAuditReceipt(env.RAW_BUCKET, {
    event: "rejected_message",
    work_key: `invalid:${message.id}`,
    run_key: null,
    dataset: null,
    job_type: null,
    segment_id: null,
    target_url: null,
    parent_work_key: null,
    contract_digest: null,
    attempt: message.attempts,
    cursor: 0,
    frontier_size: null,
    raw_key: null,
    content_digest: bodyDigest,
    reason_code: reasonCode,
    detail: "queue delivery rejected before acquisition",
    recorded_at: rejectedAt,
  });
  await recordRejectedMessage(env.DB, {
    messageId: message.id,
    attempts: message.attempts,
    reasonCode,
    bodyJson,
    bodyDigest,
    audit,
    rejectedAt,
  });
}

async function discoverFrontier(
  env: JsdaWorkerEnv,
  job: JsdaQueueJob,
): Promise<{
  frontier: ChildDescriptor[];
  rawKey: string;
  contentDigest: string;
}> {
  const page = await fetchAllowed(job.target_url, env.USER_AGENT || USER_AGENT);
  const html = new TextDecoder().decode(page.bytes);
  const links = extractLinks(html, page.finalUrl);
  const descriptors: ChildDescriptor[] = [];
  if (job.job_type === "discover_root") {
    const yearLinks = links.filter(isYearArchive);
    const dataLinks = selectDatasetDataUrls(job.dataset, links);
    descriptors.push(...(await Promise.all(yearLinks.map(descriptorForYear))));
    descriptors.push(...(await Promise.all(dataLinks.map(descriptorForFile))));
  } else {
    descriptors.push(
      ...(await Promise.all(
        selectDatasetDataUrls(job.dataset, links).map(descriptorForFile),
      )),
    );
  }
  const distinct = [
    ...new Map(descriptors.map((descriptor) => [descriptor.target_url, descriptor])).values(),
  ].sort((left, right) => left.target_url.localeCompare(right.target_url));
  if (distinct.length === 0) {
    throw new TransientAcquisitionError(
      "discovery_empty",
      `JSDA discovery yielded no governed children: ${job.target_url}`,
    );
  }
  const raw = await putImmutableRaw(
    env.RAW_BUCKET,
    job.dataset,
    job.segment_id,
    "html",
    page.bytes,
    page.contentType || "text/html; charset=utf-8",
    {
      kind: job.job_type === "discover_root" ? "root_index" : "year_index",
      target_url: job.target_url,
      final_url: page.finalUrl,
      work_key: job.work_key,
      contract_digest: job.contract_digest,
    },
  );
  return { frontier: distinct, rawKey: raw.key, contentDigest: raw.digest };
}

function auditInput(
  row: JobRow,
  event:
    | "continued"
    | "completed"
    | "failed_transient"
    | "rejected_job",
  now: string,
  reasonCode: string | null,
  detail: string | null,
  cursor: number,
  frontierSize: number | null,
) {
  return {
    event,
    work_key: row.work_key,
    run_key: row.run_key,
    dataset: row.dataset,
    job_type: row.job_type,
    segment_id: row.segment_id,
    target_url: row.target_url,
    parent_work_key: row.parent_work_key,
    contract_digest: row.contract_digest,
    attempt: row.attempt,
    cursor,
    frontier_size: frontierSize,
    raw_key: row.raw_key,
    content_digest: row.content_digest,
    reason_code: reasonCode,
    detail,
    recorded_at: now,
  } as const;
}

async function processDiscovery(
  env: JsdaWorkerEnv,
  job: JsdaQueueJob,
  claimed: JobRow,
): Promise<void> {
  let row = claimed;
  let frontier: ChildDescriptor[];
  if (row.frontier_json === null) {
    const discovered = await discoverFrontier(env, job);
    const frontierJson = JSON.stringify(discovered.frontier);
    const now = new Date().toISOString();
    await persistFrontier(
      env.DB,
      row,
      frontierJson,
      discovered.rawKey,
      discovered.contentDigest,
      now,
    );
    frontier = discovered.frontier;
    row = {
      ...row,
      frontier_json: frontierJson,
      raw_key: discovered.rawKey,
      content_digest: discovered.contentDigest,
    };
  } else {
    frontier = parseFrontier(row.frontier_json);
  }

  if (row.cursor > frontier.length) {
    throw new PermanentAcquisitionError(
      "cursor_out_of_range",
      `JSDA cursor ${row.cursor} exceeds frontier ${frontier.length}`,
    );
  }
  const end = Math.min(row.cursor + CHILD_ENQUEUE_BATCH_SIZE, frontier.length);
  const descriptors = frontier.slice(row.cursor, end);
  const children = await Promise.all(
    descriptors.map((descriptor) => makeChildJob(job, descriptor)),
  );
  await enqueueRegisteredJobs(env, children);

  if (end < frontier.length) {
    const pendingAt = new Date().toISOString();
    await advanceContinuationCursor(env.DB, row, end, pendingAt);
    row = { ...row, cursor: end };
    const auditAt = new Date().toISOString();
    const audit = await putQueueAuditReceipt(
      env.RAW_BUCKET,
      auditInput(
        row,
        "continued",
        auditAt,
        null,
        `enqueued children ${end - descriptors.length}-${end - 1}`,
        end,
        frontier.length,
      ),
    );
    await sendContinuation(env, continuationJob(job, end, row.attempt));
    await markContinuationQueued(env.DB, row, end, audit, auditAt);
    return;
  }

  const completedAt = new Date().toISOString();
  const audit = await putQueueAuditReceipt(
    env.RAW_BUCKET,
    auditInput(
      row,
      "completed",
      completedAt,
      null,
      `discovery frontier exhausted with ${frontier.length} children`,
      end,
      frontier.length,
    ),
  );
  await completeJob(env.DB, row, end, audit, completedAt);
}

async function processFile(
  env: JsdaWorkerEnv,
  job: JsdaQueueJob,
  claimed: JobRow,
): Promise<void> {
  let row = claimed;
  if (row.raw_key === null || row.content_digest === null) {
    const artifact = await fetchAllowed(job.target_url, env.USER_AGENT || USER_AGENT);
    const raw = await putImmutableRaw(
      env.RAW_BUCKET,
      job.dataset,
      job.segment_id,
      extensionOf(artifact.finalUrl),
      artifact.bytes,
      artifact.contentType,
      {
        kind: "data",
        target_url: job.target_url,
        final_url: artifact.finalUrl,
        work_key: job.work_key,
        contract_digest: job.contract_digest,
      },
    );
    const persistedAt = new Date().toISOString();
    await persistFetchedArtifact(
      env.DB,
      row,
      raw.key,
      raw.digest,
      persistedAt,
    );
    row = { ...row, raw_key: raw.key, content_digest: raw.digest };
  }
  const completedAt = new Date().toISOString();
  const audit = await putQueueAuditReceipt(
    env.RAW_BUCKET,
    auditInput(
      row,
      "completed",
      completedAt,
      null,
      "official JSDA observation stored with immutable artifact",
      row.cursor,
      null,
    ),
  );
  await completeJob(env.DB, row, row.cursor, audit, completedAt);
}

async function handleFailure(
  env: JsdaWorkerEnv,
  row: JobRow,
  error: unknown,
): Promise<"ack" | "retry"> {
  const now = new Date().toISOString();
  const detail = errorDetail(error);
  if (error instanceof PermanentAcquisitionError) {
    const audit = await putQueueAuditReceipt(
      env.RAW_BUCKET,
      auditInput(row, "rejected_job", now, error.reasonCode, detail, row.cursor, null),
    );
    await rejectJob(env.DB, row, error.reasonCode, detail, audit, now);
    return "ack";
  }
  const reasonCode =
    error instanceof TransientAcquisitionError
      ? error.reasonCode
      : "consumer_exception";
  const audit = await putQueueAuditReceipt(
    env.RAW_BUCKET,
    auditInput(row, "failed_transient", now, reasonCode, detail, row.cursor, null),
  );
  await recordTransientFailure(env.DB, row, reasonCode, detail, audit, now);
  return "retry";
}

export async function consumeQueueMessage(
  message: Message<unknown>,
  env: JsdaWorkerEnv,
): Promise<void> {
  if (!isJsdaQueueJob(message.body)) {
    try {
      await persistRejectedDelivery(message, env, "invalid_job_schema");
      message.ack();
    } catch (error) {
      logError(env, "jsda_queue_reject_persist_failed", {
        job_id: message.id,
        reason: errorDetail(error),
      });
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    }
    return;
  }

  const job = message.body;
  const expectedContract = await queueContractDigest();
  if (job.contract_digest !== expectedContract || !hostAllowed(job.target_url)) {
    try {
      await persistRejectedDelivery(
        message,
        env,
        job.contract_digest !== expectedContract
          ? "contract_digest_mismatch"
          : "host_not_allowlisted",
      );
      message.ack();
    } catch (error) {
      logError(env, "jsda_queue_contract_reject_persist_failed", {
        run_id: job.run_key,
        job_id: job.work_key,
        dataset: job.dataset,
        reason: errorDetail(error),
      });
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    }
    return;
  }

  let row: JobRow;
  try {
    row = await registerJob(env.DB, job);
  } catch (error) {
    logError(env, "jsda_queue_register_failed", {
      run_id: job.run_key,
      job_id: job.work_key,
      dataset: job.dataset,
      segment_id: job.segment_id,
      reason: errorDetail(error),
    });
    message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    return;
  }

  if (!rowMatchesMessage(row, job)) {
    try {
      await persistRejectedDelivery(message, env, "work_key_identity_mismatch");
      message.ack();
    } catch (error) {
      logError(env, "jsda_queue_identity_reject_persist_failed", {
        run_id: job.run_key,
        job_id: job.work_key,
        dataset: job.dataset,
        reason: errorDetail(error),
      });
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    }
    return;
  }

  if (row.state === "completed" || row.state === "rejected") {
    let durable = false;
    try {
      durable = await terminalAuditIsDurable(env, row);
    } catch (error) {
      logError(env, "jsda_queue_terminal_audit_read_failed", {
        run_id: row.run_key,
        job_id: row.work_key,
        dataset: row.dataset,
        segment_id: row.segment_id,
        result: row.state,
        reason: errorDetail(error),
      });
    }
    if (!durable) {
      logError(env, "jsda_queue_terminal_state_without_audit", {
        run_id: row.run_key,
        job_id: row.work_key,
        dataset: row.dataset,
        segment_id: row.segment_id,
        result: row.state,
        reason: "terminal_audit_missing",
      });
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
      return;
    }
    message.ack();
    return;
  }

  const now = new Date();
  const leaseUntil = new Date(now.getTime() + LEASE_SECONDS * 1_000).toISOString();
  let claimed: JobRow | null;
  try {
    claimed = await claimJob(env.DB, row.work_key, now.toISOString(), leaseUntil);
  } catch (error) {
    logError(env, "jsda_queue_claim_failed", {
      run_id: row.run_key,
      job_id: row.work_key,
      dataset: row.dataset,
      segment_id: row.segment_id,
      reason: errorDetail(error),
    });
    message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    return;
  }
  if (claimed === null) {
    try {
      const current = await loadJob(env.DB, row.work_key);
      if (
        current !== null &&
        (current.state === "completed" || current.state === "rejected") &&
        (await terminalAuditIsDurable(env, current))
      ) {
        message.ack();
        return;
      }
    } catch (error) {
      logError(env, "jsda_queue_claim_resolution_failed", {
        run_id: row.run_key,
        job_id: row.work_key,
        dataset: row.dataset,
        reason: errorDetail(error),
      });
    }
    message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    return;
  }

  try {
    if (claimed.job_type === "fetch_file") {
      await processFile(env, job, claimed);
    } else {
      await processDiscovery(env, job, claimed);
    }
    message.ack();
  } catch (error) {
    try {
      const current = await loadJob(env.DB, claimed.work_key);
      if (
        current === null ||
        current.state !== "running" ||
        current.attempt !== claimed.attempt
      ) {
        logError(env, "jsda_queue_claim_fence_lost", {
          run_id: claimed.run_key,
          job_id: claimed.work_key,
          dataset: claimed.dataset,
          segment_id: claimed.segment_id,
          cursor: claimed.cursor,
          result: current?.state ?? null,
          reason: errorDetail(error),
        });
        message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
        return;
      }
      const outcome = await handleFailure(env, current, error);
      if (outcome === "ack") message.ack();
      else message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    } catch (persistError) {
      logError(env, "jsda_queue_failure_evidence_write_failed", {
        run_id: claimed.run_key,
        job_id: claimed.work_key,
        dataset: claimed.dataset,
        segment_id: claimed.segment_id,
        cursor: claimed.cursor,
        reason: errorDetail(persistError),
      });
      // The claim may still be leased because its failure evidence could not be
      // written. Retry only after that lease can be reclaimed.
      message.retry({ delaySeconds: LEASE_SECONDS });
    }
  }
}
