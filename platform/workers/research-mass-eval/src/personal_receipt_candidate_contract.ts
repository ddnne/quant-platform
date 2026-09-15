import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES,
  isPersonalResearchJobId,
} from "./personal_research_contract";
import {
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  EXACT_FOUR_PROFILE_ID,
} from "./controlled_pilot_contract";
import { sha256Hex } from "./sha256";

export const RECEIPT_CANDIDATE_FORMAT = "receipt-candidate/v1";
export const RECEIPT_CANDIDATE_MAX_SEGMENTS = 512;
export const RECEIPT_CANDIDATE_MAX_REQUEST_BYTES = 64 * 1024;
export const RECEIPT_CANDIDATE_DESCRIBE_BATCH_SEGMENTS = 128;
export const RECEIPT_CANDIDATE_MAX_DATABASE_BYTES =
  PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES;

const CALLER_KEYS = ["job_id"] as const;

export type ReceiptCandidateRequest = {
  job_id: string;
};

export type ReceiptCandidateParseResult =
  | { ok: true; value: ReceiptCandidateRequest }
  | { ok: false; error: string };

function closedKeys(value: object, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return JSON.stringify(keys) === JSON.stringify(wanted);
}

export function parseReceiptCandidateRequest(
  body: unknown,
): ReceiptCandidateParseResult {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  if (!closedKeys(raw, CALLER_KEYS)) {
    return { ok: false, error: "receipt candidate request fields are closed" };
  }
  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  if (!isPersonalResearchJobId(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  return { ok: true, value: { job_id: jobId } };
}

export function personalReceiptCandidateManifestKey(jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid receipt candidate job id");
  }
  return `research/receipt-candidates/job=${jobId}/manifest.json`;
}

export function personalReceiptCandidatePublicationKey(jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid receipt candidate job id");
  }
  return `research/receipt-candidates/job=${jobId}/publication.json`;
}

export function personalReceiptCandidateObjectKey(rawSha256Hex: string): string {
  if (!/^[0-9a-f]{64}$/.test(rawSha256Hex)) {
    throw new Error("invalid receipt candidate digest");
  }
  return `research/receipt-candidates/sha256=${rawSha256Hex}.sqlite.gz`;
}

export function personalReceiptCandidatePhysicalKey(rawSha256Hex: string): string {
  if (!/^[0-9a-f]{64}$/.test(rawSha256Hex)) {
    throw new Error("invalid receipt candidate digest");
  }
  return `research/receipt-candidates/sha256=${rawSha256Hex}.sqlite`;
}

export function isReceiptCandidateManifestKey(key: string): boolean {
  return /^research\/receipt-candidates\/job=[a-z0-9][a-z0-9._-]{0,63}\/manifest\.json$/.test(
    key,
  );
}

export function isReceiptCandidateObjectKey(key: string): boolean {
  return /^research\/receipt-candidates\/sha256=[0-9a-f]{64}\.sqlite\.gz$/.test(
    key,
  );
}

export function isReceiptCandidatePhysicalKey(key: string): boolean {
  return /^research\/receipt-candidates\/sha256=[0-9a-f]{64}\.sqlite$/.test(key);
}

export function personalReceiptCandidateScopeKey(contentSha256Hex: string): string {
  if (!/^[0-9a-f]{64}$/.test(contentSha256Hex)) {
    throw new Error("invalid receipt candidate digest");
  }
  return `research/receipt-candidates/sha256=${contentSha256Hex}.pit-dependency-scope.json`;
}

export function isReceiptCandidateScopeKey(key: string): boolean {
  return /^research\/receipt-candidates\/sha256=[0-9a-f]{64}\.pit-dependency-scope\.json$/.test(
    key,
  );
}

export function receiptCandidateJobIdFromPath(pathname: string): string | null {
  const prefix = "/v1/receipt-candidate/";
  if (!pathname.startsWith(prefix)) return null;
  const value = pathname.slice(prefix.length);
  return isPersonalResearchJobId(value) ? value : null;
}

export async function receiptCandidateRequestDigest(
  request: ReceiptCandidateRequest,
): Promise<string> {
  const canonical = JSON.stringify({
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    format: RECEIPT_CANDIDATE_FORMAT,
    job_id: request.job_id,
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    profile_id: EXACT_FOUR_PROFILE_ID,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}
