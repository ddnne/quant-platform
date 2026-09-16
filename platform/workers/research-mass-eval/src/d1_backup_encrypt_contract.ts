import { sha256Hex } from "./sha256";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
} from "./personal_research_contract";

export const D1_BACKUP_ENCRYPT_FORMAT = "d1-backup-encrypt/v1";
export const D1_BACKUP_ENCRYPT_MAX_REQUEST_BYTES = 8 * 1024;
/** QPDBENC2 MAGIC + length + max header + GCM tag. Not dump size. */
export const QPDBENC2_MAX_FRAMING_BYTES = 8 + 4 + 64 * 1024 + 16;
/** SQL dump cap on Container scratch. D1 file_size is not dump size. */
export const D1_BACKUP_MAX_SQL_BYTES = 4 * 1024 * 1024 * 1024;
/** Restored sqlite during integrity_check; independent of dump bytes. */
export const D1_BACKUP_MAX_RESTORED_SQLITE_BYTES = 5 * 1024 * 1024 * 1024;
export const D1_BACKUP_MAX_CIPHERTEXT_BYTES =
  D1_BACKUP_MAX_SQL_BYTES + QPDBENC2_MAX_FRAMING_BYTES;
/** Peak scratch is dump + restored sqlite before ciphertext publication. */
export const D1_BACKUP_MAX_SCRATCH_BYTES =
  D1_BACKUP_MAX_SQL_BYTES + D1_BACKUP_MAX_RESTORED_SQLITE_BYTES;
export const D1_BACKUP_ENVIRONMENTS = ["staging", "production"] as const;
export type D1BackupEnvironment = (typeof D1_BACKUP_ENVIRONMENTS)[number];

const CALLER_KEYS = ["environment", "job_id"] as const;

export type D1BackupEncryptRequest = {
  job_id: string;
  environment: D1BackupEnvironment;
};

export type D1BackupEncryptParseResult =
  | { ok: true; value: D1BackupEncryptRequest }
  | { ok: false; error: string };

function closedKeys(value: object, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return JSON.stringify(keys) === JSON.stringify(wanted);
}

export function parseD1BackupEncryptRequest(
  body: unknown,
): D1BackupEncryptParseResult {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  if (!closedKeys(raw, CALLER_KEYS)) {
    return { ok: false, error: "d1 backup encrypt request fields are closed" };
  }
  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  if (!isPersonalResearchJobId(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  const environment = raw.environment;
  if (environment !== "staging" && environment !== "production") {
    return { ok: false, error: "environment is invalid" };
  }
  return { ok: true, value: { job_id: jobId, environment } };
}

export function d1BackupEncryptManifestKey(jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid d1 backup job id");
  }
  return `research/d1-backups/job=${jobId}/manifest.json`;
}

export function d1BackupEncryptCiphertextKey(contentSha256Hex: string): string {
  if (!/^[0-9a-f]{64}$/.test(contentSha256Hex)) {
    throw new Error("invalid d1 backup digest");
  }
  return `research/d1-backups/sha256=${contentSha256Hex}.sql.enc`;
}

export function isD1BackupEncryptManifestKey(key: string): boolean {
  return /^research\/d1-backups\/job=[a-z0-9][a-z0-9._-]{0,63}\/manifest\.json$/.test(
    key,
  );
}

export function isD1BackupEncryptCiphertextKey(key: string): boolean {
  return /^research\/d1-backups\/sha256=[0-9a-f]{64}\.sql\.enc$/.test(key);
}

export function d1BackupEncryptJobIdFromPath(pathname: string): string | null {
  const prefix = "/v1/d1-backup-encrypt/";
  if (!pathname.startsWith(prefix)) return null;
  const value = pathname.slice(prefix.length);
  return isPersonalResearchJobId(value) ? value : null;
}

export async function d1BackupEncryptRequestDigest(
  request: D1BackupEncryptRequest,
): Promise<string> {
  const canonical = JSON.stringify({
    environment: request.environment,
    format: D1_BACKUP_ENCRYPT_FORMAT,
    job_id: request.job_id,
    max_sql_bytes: D1_BACKUP_MAX_SQL_BYTES,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}
