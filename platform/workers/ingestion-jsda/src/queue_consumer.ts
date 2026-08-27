import type { JsdaWorkerEnv } from "./env";
import {
  claimJob,
  completeJob,
  completeWaitingAncestor,
  ensureRunTerminalLog,
  failWaitingAncestor,
  loadJob,
  loadJobClosure,
  loadAncestorChain,
  advanceContinuationCursor,
  markContinuationQueued,
  markFrontierExhausted,
  persistFetchedArtifact,
  persistFrontier,
  propagateTerminalAdoptedMemberships,
  recomputeClosureAggregates,
  recordRejectedMessage,
  recordTransientFailure,
  rejectFromDeadLetter,
  rejectJob,
  type JobClosureRow,
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
import {
  immutableObjectMatchesDigest,
  putImmutableRaw,
  putQueueAuditReceipt,
} from "./raw_store";
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

async function terminalEvidenceIsDurable(
  env: JsdaWorkerEnv,
  row: JobRow,
): Promise<boolean> {
  if (row.audit_receipt_key === null || row.audit_receipt_digest === null) {
    return false;
  }
  if (
    (row.state === "completed" || row.state === "waiting_children") &&
    (row.raw_key === null || row.content_digest === null)
  ) {
    return false;
  }
  if ((row.raw_key === null) !== (row.content_digest === null)) return false;
  const [auditMatches, rawMatches] = await Promise.all([
    immutableObjectMatchesDigest(
      env.RAW_BUCKET,
      row.audit_receipt_key,
      row.audit_receipt_digest,
    ),
    row.raw_key === null
      ? Promise.resolve(true)
      : immutableObjectMatchesDigest(
          env.RAW_BUCKET,
          row.raw_key,
          row.content_digest!,
        ),
  ]);
  return auditMatches && rawMatches;
}

async function terminalObservationIsAuthoritative(
  env: JsdaWorkerEnv,
  row: JobRow,
): Promise<boolean> {
  if (row.job_type !== "fetch_file") return true;
  if (row.source_object_id === null) return false;
  const observation = await env.DB.prepare(
    `SELECT source_object_id, state, content_digest, raw_key, observed_at
       FROM jsda_observations
      WHERE observation_key=? AND work_key=?`,
  )
    .bind(row.work_key, row.work_key)
    .first<{
      source_object_id: string;
      state: string;
      content_digest: string | null;
      raw_key: string | null;
      observed_at: string | null;
    }>();
  if (
    observation === null ||
    observation.source_object_id !== row.source_object_id ||
    observation.state !== row.state ||
    observation.observed_at === null
  ) {
    return false;
  }
  return (
    row.state !== "completed" ||
    (observation.content_digest === row.content_digest &&
      observation.raw_key === row.raw_key)
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
    | "frontier_exhausted"
    | "completed"
    | "failed_transient"
    | "rejected_job"
    | "dead_lettered",
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

  const exhaustedAt = new Date().toISOString();
  const audit = await putQueueAuditReceipt(
    env.RAW_BUCKET,
    auditInput(
      row,
      "frontier_exhausted",
      exhaustedAt,
      null,
      `discovery frontier exhausted with ${frontier.length} children`,
      end,
      frontier.length,
    ),
  );
  await markFrontierExhausted(env.DB, row, end, audit, exhaustedAt);
  const waiting = await loadJob(env.DB, row.work_key);
  if (waiting === null) {
    throw new Error(`JSDA frontier exhaustion lost job: ${row.work_key}`);
  }
  await advanceAncestorClosures(env, waiting);
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
  const completed = await loadJob(env.DB, row.work_key);
  if (completed === null) {
    throw new Error(`JSDA completion lost job: ${row.work_key}`);
  }
  await repairTerminalClosure(env, completed);
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
    const rejected = await loadJob(env.DB, row.work_key);
    if (rejected === null) {
      throw new Error(`JSDA rejection lost job: ${row.work_key}`);
    }
    await repairTerminalClosure(env, rejected);
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
  const failed = await loadJob(env.DB, row.work_key);
  if (failed === null) {
    throw new Error(`JSDA transient failure lost job: ${row.work_key}`);
  }
  await recomputeClosureAggregates(env.DB, failed, now);
  return "retry";
}

function descendantFailureDetail(closure: JobClosureRow): string {
  const identity = closure.failure_work_key ?? "unknown-descendant";
  const reason = closure.failure_detail ?? "governed descendant rejected";
  return `descendant ${identity}: ${reason}`.slice(0, 500);
}

async function advanceAncestorClosures(
  env: JsdaWorkerEnv,
  origin: JobRow,
): Promise<void> {
  const now = new Date().toISOString();
  await recomputeClosureAggregates(env.DB, origin, now);
  const chain: JobRow[] = [];
  if (origin.job_type !== "fetch_file") chain.push(origin);
  chain.push(...(await loadAncestorChain(env.DB, origin)));
  for (const ancestor of chain) {
    await recomputeClosureAggregates(env.DB, origin, now);
    const latest = await loadJob(env.DB, ancestor.work_key);
    if (latest === null) {
      throw new Error(`JSDA ancestor disappeared: ${ancestor.work_key}`);
    }
    if (latest.job_type === "fetch_file") continue;
    const closure = await loadJobClosure(env.DB, latest.work_key);
    if (closure === null) {
      throw new Error(`JSDA job closure missing: ${latest.work_key}`);
    }
    const rejectedOpen =
      (latest.state === "waiting_children" || latest.state === "completed") &&
      closure.descendant_rejected > 0;
    if (rejectedOpen) {
      const failedAt = new Date().toISOString();
      const audit = await putQueueAuditReceipt(
        env.RAW_BUCKET,
        auditInput(
          latest,
          "rejected_job",
          failedAt,
          "descendant_rejected",
          descendantFailureDetail(closure),
          latest.cursor,
          null,
        ),
      );
      const failed = await failWaitingAncestor(
        env.DB,
        latest,
        "descendant_rejected",
        descendantFailureDetail(closure),
        audit,
        failedAt,
      );
      const after = await loadJob(env.DB, latest.work_key);
      if (!failed && after?.state !== "rejected") {
        throw new Error(`JSDA ancestor fail did not converge: ${latest.work_key}`);
      }
      continue;
    }
    if (latest.state !== "waiting_children") continue;
    if (
      closure.frontier_exhausted === 1 &&
      closure.descendant_total > 0 &&
      closure.descendant_completed === closure.descendant_total &&
      closure.descendant_rejected === 0 &&
      closure.descendant_failed_transient === 0 &&
      closure.descendant_nonterminal === 0
    ) {
      if (!(await terminalEvidenceIsDurable(env, latest))) {
        throw new Error(`JSDA ancestor evidence is not durable: ${latest.work_key}`);
      }
      const closedAt = new Date().toISOString();
      const audit = await putQueueAuditReceipt(
        env.RAW_BUCKET,
        auditInput(
          latest,
          "completed",
          closedAt,
          null,
          "all governed descendants durably completed",
          latest.cursor,
          null,
        ),
      );
      const closed = await completeWaitingAncestor(env.DB, latest, audit, closedAt);
      const after = await loadJob(env.DB, latest.work_key);
      if (!closed && after?.state === "waiting_children") {
        continue;
      }
      if (!closed && after?.state !== "completed") {
        throw new Error(`JSDA ancestor close did not converge: ${latest.work_key}`);
      }
    }
  }
  await recomputeClosureAggregates(env.DB, origin, now);
  const rootKey =
    origin.job_type === "discover_root" ? origin.work_key : origin.run_key;
  const root = await loadJob(env.DB, rootKey);
  if (root !== null && root.job_type === "discover_root") {
    await ensureRunTerminalLog(env.DB, root, new Date().toISOString());
  }
}

async function repairTerminalClosure(
  env: JsdaWorkerEnv,
  row: JobRow,
): Promise<void> {
  if (!(await terminalEvidenceIsDurable(env, row))) {
    throw new Error("terminal_evidence_missing");
  }
  if (!(await terminalObservationIsAuthoritative(env, row))) {
    throw new Error("terminal_observation_missing");
  }
  const adopted = await propagateTerminalAdoptedMemberships(
    env.DB,
    row,
    new Date().toISOString(),
  );
  await advanceAncestorClosures(env, row);
  const advancedParents = new Set<string>();
  for (const membership of adopted) {
    if (advancedParents.has(membership.parent_work_key)) continue;
    advancedParents.add(membership.parent_work_key);
    const parent = await loadJob(env.DB, membership.parent_work_key);
    if (parent === null || parent.run_key !== membership.run_key) {
      throw new Error(
        `JSDA adopted membership parent missing: ${membership.run_key}/${membership.parent_work_key}`,
      );
    }
    await advanceAncestorClosures(env, parent);
  }
}

export async function consumeDlqMessage(
  message: Message<unknown>,
  env: JsdaWorkerEnv,
  queueName: string,
): Promise<void> {
  try {
    if (!isJsdaQueueJob(message.body)) {
      await persistRejectedDelivery(message, env, "dead_letter_invalid_job_schema");
      message.ack();
      return;
    }

    const job = message.body;
    const expectedContract = await queueContractDigest();
    if (job.contract_digest !== expectedContract || !hostAllowed(job.target_url)) {
      await persistRejectedDelivery(
        message,
        env,
        job.contract_digest !== expectedContract
          ? "dead_letter_contract_digest_mismatch"
          : "dead_letter_host_not_allowlisted",
      );
      message.ack();
      return;
    }

    const row = await loadJob(env.DB, job.work_key);
    if (row === null) {
      await persistRejectedDelivery(message, env, "dead_letter_unregistered_job");
      message.ack();
      return;
    }
    if (!rowMatchesMessage(row, job)) {
      await persistRejectedDelivery(message, env, "dead_letter_work_key_identity_mismatch");
      message.ack();
      return;
    }

    if (row.state === "completed" || row.state === "rejected") {
      await repairTerminalClosure(env, row);
      message.ack();
      return;
    }

    const now = new Date().toISOString();
    const detail =
      `dead-lettered on ${queueName} after ${message.attempts} attempts`.slice(0, 500);
    const audit = await putQueueAuditReceipt(
      env.RAW_BUCKET,
      auditInput(row, "dead_lettered", now, "dead_lettered", detail, row.cursor, null),
    );
    const rejected = await rejectFromDeadLetter(
      env.DB,
      row,
      "dead_lettered",
      detail,
      audit,
      now,
    );
    const latest = await loadJob(env.DB, row.work_key);
    if (latest === null) {
      throw new Error(`JSDA DLQ reject lost job: ${row.work_key}`);
    }
    if (!rejected && latest.state !== "rejected") {
      throw new Error(`JSDA DLQ did not terminalize: ${row.work_key}`);
    }
    await repairTerminalClosure(env, latest);
    message.ack();
  } catch (error) {
    logError(env, "jsda_queue_dlq_persist_failed", {
      job_id: isJsdaQueueJob(message.body) ? message.body.work_key : message.id,
      run_id: isJsdaQueueJob(message.body) ? message.body.run_key : null,
      reason: errorDetail(error),
    });
    message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
  }
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

  let row: JobRow | null;
  try {
    row = await loadJob(env.DB, job.work_key);
  } catch (error) {
    logError(env, "jsda_queue_load_failed", {
      run_id: job.run_key,
      job_id: job.work_key,
      dataset: job.dataset,
      segment_id: job.segment_id,
      reason: errorDetail(error),
    });
    message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    return;
  }

  if (row === null) {
    try {
      await persistRejectedDelivery(message, env, "unregistered_job");
      message.ack();
    } catch (error) {
      logError(env, "jsda_queue_unregistered_reject_persist_failed", {
        run_id: job.run_key,
        job_id: job.work_key,
        dataset: job.dataset,
        reason: errorDetail(error),
      });
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    }
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

  if (
    row.state === "completed" ||
    row.state === "rejected" ||
    row.state === "waiting_children"
  ) {
    try {
      await repairTerminalClosure(env, row);
      message.ack();
    } catch (error) {
      logError(env, "jsda_queue_terminal_closure_repair_failed", {
        run_id: row.run_key,
        job_id: row.work_key,
        dataset: row.dataset,
        segment_id: row.segment_id,
        result: row.state,
        reason: errorDetail(error),
      });
      message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
    }
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
        (current.state === "completed" ||
          current.state === "rejected" ||
          current.state === "waiting_children")
      ) {
        await repairTerminalClosure(env, current);
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
        current !== null &&
        (current.state === "completed" ||
          current.state === "rejected" ||
          current.state === "waiting_children")
      ) {
        logError(env, "jsda_queue_post_terminal_closure_failed", {
          run_id: claimed.run_key,
          job_id: claimed.work_key,
          dataset: claimed.dataset,
          segment_id: claimed.segment_id,
          cursor: claimed.cursor,
          result: current.state,
          reason: errorDetail(error),
        });
        message.retry({ delaySeconds: RETRY_DELAY_SECONDS });
        return;
      }
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
