import {
  JSDA_QUEUE_AUDIT_VERSION,
  type DatasetId,
  type JobType,
} from "./queue_contract";
import { sha256Hex } from "./sha256";

export interface ImmutableObjectRef {
  key: string;
  digest: string;
}

export interface QueueAuditInput {
  event:
    | "continued"
    | "completed"
    | "failed_transient"
    | "rejected_job"
    | "rejected_message";
  work_key: string;
  run_key: string | null;
  dataset: DatasetId | null;
  job_type: JobType | null;
  segment_id: string | null;
  target_url: string | null;
  parent_work_key: string | null;
  contract_digest: string | null;
  attempt: number;
  cursor: number;
  frontier_size: number | null;
  raw_key: string | null;
  content_digest: string | null;
  reason_code: string | null;
  detail: string | null;
  recorded_at: string;
}

async function createOnly(
  bucket: R2Bucket,
  key: string,
  body: ArrayBuffer | Uint8Array | string,
  contentType: string,
  metadata: Record<string, string>,
): Promise<void> {
  const created = await bucket.put(key, body, {
    onlyIf: { etagDoesNotMatch: "*" },
    httpMetadata: { contentType },
    customMetadata: metadata,
  });
  if (created !== null) return;
  const existing = await bucket.head(key);
  if (
    existing === null ||
    existing.customMetadata?.sha256 !== metadata.sha256
  ) {
    throw new Error(`immutable R2 collision or unverifiable object: ${key}`);
  }
}

export async function putImmutableRaw(
  bucket: R2Bucket,
  dataset: DatasetId,
  segmentId: string,
  extension: string,
  body: ArrayBuffer,
  contentType: string,
  metadata: Record<string, string>,
): Promise<ImmutableObjectRef> {
  const digest = await sha256Hex(body);
  const key = `raw/jsda/${dataset}/${segmentId}/${digest}.${extension}`;
  await createOnly(bucket, key, body, contentType, {
    ...metadata,
    source: "jsda",
    dataset,
    segment_id: segmentId,
    sha256: digest,
  });
  return { key, digest };
}

export async function putQueueAuditReceipt(
  bucket: R2Bucket,
  input: QueueAuditInput,
): Promise<ImmutableObjectRef> {
  const document = {
    version: JSDA_QUEUE_AUDIT_VERSION,
    source: "jsda",
    ...input,
  };
  const text = JSON.stringify(document);
  const digest = await sha256Hex(new TextEncoder().encode(text));
  const workDigest = await sha256Hex(new TextEncoder().encode(input.work_key));
  const key =
    `audit/jsda/queue/${workDigest.slice(0, 24)}/` +
    `${input.event}-${digest}.json`;
  await createOnly(bucket, key, text, "application/json", {
    source: "jsda",
    event: input.event,
    sha256: digest,
    work_key_digest: workDigest,
  });
  return { key, digest };
}
