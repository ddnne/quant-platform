import { sha256Hex } from "./sha256";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
} from "./personal_research_contract";

export const D1_BACKUP_ENCRYPT_FORMAT = "d1-backup-encrypt/v1";
export const D1_BACKUP_ENCRYPT_MAX_REQUEST_BYTES = 8 * 1024;
/** QPDBENC2 MAGIC + length + max header + GCM tag. Not dump size. */
export const QPDBENC2_MAX_FRAMING_BYTES = 8 + 4 + 64 * 1024 + 16;
/** SQL dump stream cap. D1 file_size is not dump size. */
export const D1_BACKUP_MAX_SQL_BYTES = 4 * 1024 * 1024 * 1024;
/** Max accepted restored sqlite after restore. Postcondition, not a disk cap. */
export const D1_BACKUP_MAX_RESTORED_SQLITE_BYTES = 5 * 1024 * 1024 * 1024;
export const D1_BACKUP_MAX_CIPHERTEXT_BYTES =
  D1_BACKUP_MAX_SQL_BYTES + QPDBENC2_MAX_FRAMING_BYTES;
export const D1_BACKUP_ENVIRONMENTS = ["staging", "production"] as const;
export type D1BackupEnvironment = (typeof D1_BACKUP_ENVIRONMENTS)[number];

export const D1_EXPORT_BUNDLE_SCHEMA = "d1-export-bundle/v1";
export const GOVERNED_INGEST_DATABASE = {
  staging: {
    name: "quant-ingest-staging",
    id: "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
  },
  production: {
    name: "quant-ingest",
    id: "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
  },
} as const;
const UTC_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;
const HOST_RE =
  /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/;
const DB_ID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

export type D1ExportBundle = {
  schema_version: typeof D1_EXPORT_BUNDLE_SCHEMA;
  environment: D1BackupEnvironment;
  database_name: string;
  database_id: string;
  at_bookmark: string;
  export_completed_at: string;
  download_host: string;
  signed_url: string;
};

function blockedHost(host: string): boolean {
  if (host === "localhost" || host.endsWith(".local")) return true;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) return true;
  if (host.includes(":")) return true;
  return !HOST_RE.test(host);
}

export function d1ExportDownloadUrlDenied(raw: string, allowedHost: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return true;
  }
  if (parsed.protocol !== "https:") return true;
  if (parsed.username !== "" || parsed.password !== "") return true;
  const host = parsed.hostname.toLowerCase();
  return host !== allowedHost.toLowerCase() || blockedHost(host);
}

export async function d1ExportUrlSha256(signedUrl: string): Promise<string> {
  return `sha256:${await sha256Hex(new TextEncoder().encode(signedUrl))}`;
}

export async function parseD1ExportBundle(
  raw: unknown,
): Promise<{ ok: true; value: D1ExportBundle } | { ok: false; error: string }> {
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return { ok: false, error: "export_not_authorized" };
    }
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { ok: false, error: "export_not_authorized" };
  }
  const body = raw as Record<string, unknown>;
  const environment = body.environment;
  if (environment !== "staging" && environment !== "production") {
    return { ok: false, error: "export_not_authorized" };
  }
  const signed = typeof body.signed_url === "string" ? body.signed_url : "";
  const host = typeof body.download_host === "string" ? body.download_host.toLowerCase() : "";
  const databaseId = typeof body.database_id === "string" ? body.database_id : "";
  const databaseName = typeof body.database_name === "string" ? body.database_name : "";
  const bookmark = typeof body.at_bookmark === "string" ? body.at_bookmark.trim() : "";
  const completed = typeof body.export_completed_at === "string" ? body.export_completed_at : "";
  if (
    body.schema_version !== D1_EXPORT_BUNDLE_SCHEMA ||
    !databaseName ||
    !DB_ID_RE.test(databaseId) ||
    !bookmark ||
    !UTC_RE.test(completed) ||
    blockedHost(host) ||
    d1ExportDownloadUrlDenied(signed, host)
  ) {
    return { ok: false, error: "export_not_authorized" };
  }
  return {
    ok: true,
    value: {
      schema_version: D1_EXPORT_BUNDLE_SCHEMA,
      environment,
      database_name: databaseName,
      database_id: databaseId,
      at_bookmark: bookmark,
      export_completed_at: completed,
      download_host: host,
      signed_url: signed,
    },
  };
}

export async function d1BackupEncryptRequestDigest(
  request: D1BackupEncryptRequest,
  bundle: D1ExportBundle,
): Promise<string> {
  const canonical = JSON.stringify({
    at_bookmark: bundle.at_bookmark,
    database_id: bundle.database_id,
    environment: request.environment,
    export_completed_at: bundle.export_completed_at,
    format: D1_BACKUP_ENCRYPT_FORMAT,
    job_id: request.job_id,
    max_sql_bytes: D1_BACKUP_MAX_SQL_BYTES,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    signed_url_sha256: await d1ExportUrlSha256(bundle.signed_url),
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}
