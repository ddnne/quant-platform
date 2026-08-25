import {
  classifyFetchFreshness,
  FILE_ROUTING_VERSION,
  observationEpoch,
  type FreshnessClass,
} from "./source_routing";
import { sha256Hex } from "./sha256";

export {
  classifyFetchFreshness,
  FILE_ROUTING_VERSION,
  observationEpoch,
  type FreshnessClass,
} from "./source_routing";

export type DatasetId =
  | "jsda_otc_bond_reference_prices"
  | "jsda_tokyo_repo_rates"
  | "jsda_corporate_bond_transactions";

export const DATASET_IDS = [
  "jsda_otc_bond_reference_prices",
  "jsda_tokyo_repo_rates",
  "jsda_corporate_bond_transactions",
] as const satisfies readonly DatasetId[];

export const DATASET_ROOTS: Readonly<Record<DatasetId, string>> = {
  jsda_otc_bond_reference_prices:
    "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html",
  jsda_tokyo_repo_rates: "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/",
  jsda_corporate_bond_transactions:
    "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/",
};

export const JSDA_QUEUE_JOB_VERSION = "jsda-acquisition-job/v2" as const;
export const JSDA_QUEUE_AUDIT_VERSION = "jsda-queue-audit/v2" as const;
export const CHILD_ENQUEUE_BATCH_SIZE = 25;

export function isJsdaDlqQueue(
  queueName: string,
  configuredDlqQueue: string,
): boolean {
  return queueName === configuredDlqQueue;
}

export type JobType = "discover_root" | "discover_year" | "fetch_file";
export type RequestedBy = "cron" | "manual";

export interface JsdaQueueJob {
  version: typeof JSDA_QUEUE_JOB_VERSION;
  work_key: string;
  run_key: string;
  job_type: JobType;
  dataset: DatasetId;
  target_url: string;
  segment_id: string;
  parent_work_key: string | null;
  cursor: number;
  attempt: number;
  requested_by: RequestedBy;
  requested_at: string;
  contract_digest: string;
}

export interface ChildDescriptor {
  job_type: Exclude<JobType, "discover_root">;
  target_url: string;
  segment_id: string;
}

const JOB_KEYS = new Set<keyof JsdaQueueJob>([
  "version",
  "work_key",
  "run_key",
  "job_type",
  "dataset",
  "target_url",
  "segment_id",
  "parent_work_key",
  "cursor",
  "attempt",
  "requested_by",
  "requested_at",
  "contract_digest",
]);

const CONTRACT_CANONICAL = JSON.stringify({
  version: JSDA_QUEUE_JOB_VERSION,
  hierarchy: ["discover_root", "discover_year", "fetch_file"],
  dataset_roots: DATASET_ROOTS,
  dataset_file_selection: FILE_ROUTING_VERSION,
  identities: ["source_object", "observation", "artifact"],
  work_key:
    "daily stable root; run-scoped discovery URL; archive fetched-file URL; rolling fetched-file URL per run epoch",
  fields: [...JOB_KEYS].sort(),
  official_hosts: ["jsda.or.jp", "market.jsda.or.jp", "www.jsda.or.jp"],
  semantics: [
    "d1-authoritative-progress",
    "bounded-child-continuations",
    "fenced-job-attempts",
    "run-scoped-discovery-refresh",
    "source-object-observation-artifact",
    "rolling-url-reobservation",
    "archive-url-immutable-identity",
    "r2-create-only-raw-and-audit",
    "completed-observation-idempotent",
    "monotonic-observation-sequence",
    "cas-current-source-pointer",
    "descendant-run-closure",
    "run-scoped-membership-adoption",
    "run-pass-from-closure-only",
    "dlq-terminal-convergence",
  ],
});

function encode(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

export async function queueContractDigest(): Promise<string> {
  return `sha256:${await sha256Hex(encode(CONTRACT_CANONICAL))}`;
}

export function isDatasetId(value: unknown): value is DatasetId {
  return (
    typeof value === "string" &&
    (DATASET_IDS as readonly string[]).includes(value)
  );
}

function isIsoInstant(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString() === value;
}

function isWorkKey(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 16 &&
    value.length <= 240 &&
    /^jsda:v2:[A-Za-z0-9:._-]+$/.test(value)
  );
}

function isSegmentId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 200 &&
    /^[A-Za-z0-9._-]+$/.test(value)
  );
}

export function isJsdaQueueJob(value: unknown): value is JsdaQueueJob {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  const keys = Object.keys(candidate);
  if (
    keys.length !== JOB_KEYS.size ||
    keys.some((key) => !JOB_KEYS.has(key as keyof JsdaQueueJob))
  ) {
    return false;
  }
  return (
    candidate.version === JSDA_QUEUE_JOB_VERSION &&
    isWorkKey(candidate.work_key) &&
    isWorkKey(candidate.run_key) &&
    (candidate.job_type === "discover_root" ||
      candidate.job_type === "discover_year" ||
      candidate.job_type === "fetch_file") &&
    isDatasetId(candidate.dataset) &&
    typeof candidate.target_url === "string" &&
    candidate.target_url.length <= 2_048 &&
    isSegmentId(candidate.segment_id) &&
    (candidate.parent_work_key === null || isWorkKey(candidate.parent_work_key)) &&
    ((candidate.job_type === "discover_root" &&
      candidate.parent_work_key === null &&
      candidate.work_key === candidate.run_key) ||
      (candidate.job_type !== "discover_root" &&
        candidate.parent_work_key !== null)) &&
    Number.isInteger(candidate.cursor) &&
    Number(candidate.cursor) >= 0 &&
    Number.isInteger(candidate.attempt) &&
    Number(candidate.attempt) >= 0 &&
    (candidate.requested_by === "cron" || candidate.requested_by === "manual") &&
    isIsoInstant(candidate.requested_at) &&
    typeof candidate.contract_digest === "string" &&
    /^sha256:[0-9a-f]{64}$/.test(candidate.contract_digest)
  );
}

export function canonicalUrl(raw: string): string {
  const url = new URL(raw);
  url.hash = "";
  return url.toString();
}

export async function urlIdentity(raw: string): Promise<string> {
  return sha256Hex(encode(canonicalUrl(raw)));
}

export async function sourceObjectId(
  dataset: DatasetId,
  raw: string,
): Promise<string> {
  return `jsda:obj:${dataset}:${await urlIdentity(raw)}`;
}

export async function runEpochToken(runKey: string): Promise<string> {
  return (await sha256Hex(encode(runKey))).slice(0, 16);
}

export async function fetchFileWorkKey(
  dataset: DatasetId,
  targetUrl: string,
  runKey: string,
  requestedAt: string,
): Promise<{ workKey: string; freshness: FreshnessClass; epoch: string }> {
  const identity = await urlIdentity(targetUrl);
  const freshness = classifyFetchFreshness(dataset, targetUrl, requestedAt);
  const epoch = observationEpoch(freshness, runKey);
  const runIdentity =
    freshness === "rolling" ? `:${await runEpochToken(runKey)}` : "";
  return {
    workKey: `jsda:v2:file:${dataset}:${identity}${runIdentity}`,
    freshness,
    epoch,
  };
}

function safeBasename(raw: string): string {
  const pathname = new URL(raw).pathname;
  const value = pathname.split("/").filter(Boolean).pop() || "artifact";
  return value.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 120);
}

export async function makeRootJob(
  dataset: DatasetId,
  requestedBy: RequestedBy,
  requestedAt: string,
): Promise<JsdaQueueJob> {
  const day = requestedAt.slice(0, 10);
  const workKey = `jsda:v2:root:${dataset}:${requestedBy}:${day}`;
  return {
    version: JSDA_QUEUE_JOB_VERSION,
    work_key: workKey,
    run_key: workKey,
    job_type: "discover_root",
    dataset,
    target_url: DATASET_ROOTS[dataset],
    segment_id: `index_root_${day}`,
    parent_work_key: null,
    cursor: 0,
    attempt: 0,
    requested_by: requestedBy,
    requested_at: requestedAt,
    contract_digest: await queueContractDigest(),
  };
}

export async function makeChildJob(
  parent: Pick<
    JsdaQueueJob,
    "dataset" | "run_key" | "work_key" | "requested_at" | "requested_by" | "contract_digest"
  >,
  descriptor: ChildDescriptor,
): Promise<JsdaQueueJob> {
  const identity = await urlIdentity(descriptor.target_url);
  let workKey: string;
  if (descriptor.job_type === "discover_year") {
    workKey = `jsda:v2:year:${parent.dataset}:${identity}:${await runEpochToken(parent.run_key)}`;
  } else {
    workKey = (
      await fetchFileWorkKey(
        parent.dataset,
        descriptor.target_url,
        parent.run_key,
        parent.requested_at,
      )
    ).workKey;
  }
  return {
    version: JSDA_QUEUE_JOB_VERSION,
    work_key: workKey,
    run_key: parent.run_key,
    job_type: descriptor.job_type,
    dataset: parent.dataset,
    target_url: canonicalUrl(descriptor.target_url),
    segment_id: descriptor.segment_id,
    parent_work_key: parent.work_key,
    cursor: 0,
    attempt: 0,
    requested_by: parent.requested_by,
    requested_at: parent.requested_at,
    contract_digest: parent.contract_digest,
  };
}

export async function descriptorForYear(url: string): Promise<ChildDescriptor> {
  const match = /archive(20\d{2})\.html/i.exec(new URL(url).pathname);
  const identity = (await urlIdentity(url)).slice(0, 12);
  return {
    job_type: "discover_year",
    target_url: canonicalUrl(url),
    segment_id: `archive_year_${match?.[1] ?? "unknown"}_${identity}`,
  };
}

export async function descriptorForFile(url: string): Promise<ChildDescriptor> {
  const identity = (await urlIdentity(url)).slice(0, 12);
  return {
    job_type: "fetch_file",
    target_url: canonicalUrl(url),
    segment_id: `file_${safeBasename(url)}_${identity}`,
  };
}

export function continuationJob(job: JsdaQueueJob, cursor: number, attempt: number): JsdaQueueJob {
  return { ...job, cursor, attempt };
}
