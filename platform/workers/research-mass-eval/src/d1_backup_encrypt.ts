import { json } from "./http";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
} from "./personal_research_contract";
import {
  D1_BACKUP_ENCRYPT_FORMAT,
  D1_BACKUP_MAX_SQL_BYTES,
  GOVERNED_INGEST_DATABASE,
  d1BackupEncryptManifestKey,
  d1BackupEncryptRequestDigest,
  d1ExportUrlSha256,
  parseD1ExportBundle,
  type D1BackupEncryptRequest,
} from "./d1_backup_encrypt_contract";
import {
  personalJobStateKey,
  readSmallJson,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";

const TERMINAL_MAX_BYTES = 64 * 1024;
const STATE_MAX_BYTES = 8 * 1024;
const SOURCE_SHA = /^[0-9a-f]{40}$/;

function releaseSourceSha(env: Env): string | null {
  const tag = env.CF_VERSION_METADATA?.tag ?? "";
  return SOURCE_SHA.test(tag) ? tag : null;
}

function backupKeyPresent(raw: string | undefined): boolean {
  if (!raw) return false;
  const utf8 = new TextEncoder().encode(raw);
  if (utf8.byteLength === 32) return true;
  try {
    return atob(raw.trim()).length === 32;
  } catch {
    return false;
  }
}

export async function submitD1BackupEncrypt(
  env: Env,
  request: D1BackupEncryptRequest,
): Promise<Response> {
  const parsed = await parseD1ExportBundle(env.D1_BACKUP_EXPORT_BUNDLE);
  if (!parsed.ok) {
    return json(
      { ok: false, error: "export_not_authorized", job_id: request.job_id, go: false },
      409,
    );
  }
  const bundle = parsed.value;
  if (
    bundle.environment !== request.environment ||
    bundle.database_id !== GOVERNED_INGEST_DATABASE[request.environment].id ||
    bundle.database_name !== GOVERNED_INGEST_DATABASE[request.environment].name
  ) {
    return json(
      { ok: false, error: "export_identity_mismatch", job_id: request.job_id, go: false },
      409,
    );
  }
  if (!backupKeyPresent(env.D1_BACKUP_KEY)) {
    return json(
      { ok: false, error: "backup_key_unavailable", job_id: request.job_id, go: false },
      409,
    );
  }
  const signedUrlSha256 = await d1ExportUrlSha256(bundle.signed_url);
  const requestDigest = await d1BackupEncryptRequestDigest(request, bundle);
  const existing = await readSmallJson(
    env.STRUCTURED_BUCKET,
    d1BackupEncryptManifestKey(request.job_id),
    TERMINAL_MAX_BYTES,
  );
  if (existing) {
    if (existing.request_digest !== requestDigest) {
      return json(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return json({
      ok: existing.status === "COMPLETED",
      idempotent: true,
      job: existing,
      go: false,
    });
  }
  const sourceSha = releaseSourceSha(env);
  if (!sourceSha) {
    return json(
      {
        ok: false,
        error: "d1_backup_release_sha_unavailable",
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
  const submitted = submittedStateDocument({
    jobId: request.job_id,
    requestDigest,
    kind: "d1-backup",
    deploymentId: env.CF_VERSION_METADATA?.id ?? "unknown",
  });
  const conflict = await writeSubmittedState(env, submitted);
  if (conflict) return conflict;
  try {
    const target = await verifiedPersonalResearchContainer(
      env,
      PERSONAL_SNAPSHOT_CONTAINER_NAME,
    );
    return await target.fetch(
      new Request("http://container/v1/encrypt-d1-backup", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          deployment_id: env.CF_VERSION_METADATA?.id ?? "unknown",
          at_bookmark: bundle.at_bookmark,
          database_id: bundle.database_id,
          database_name: bundle.database_name,
          download_host: bundle.download_host,
          environment: request.environment,
          export_completed_at: bundle.export_completed_at,
          format: D1_BACKUP_ENCRYPT_FORMAT,
          job_id: request.job_id,
          manifest_key: d1BackupEncryptManifestKey(request.job_id),
          max_sql_bytes: D1_BACKUP_MAX_SQL_BYTES,
          release_source_sha: sourceSha,
          request_digest: requestDigest,
          runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
          signed_url_sha256: signedUrlSha256,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return json(
      {
        ok: false,
        error: "d1_backup_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function d1BackupEncryptStatus(
  env: Env,
  jobId: string,
  now = new Date(),
): Promise<Response> {
  const terminal = await readSmallJson(
    env.STRUCTURED_BUCKET,
    d1BackupEncryptManifestKey(jobId),
    TERMINAL_MAX_BYTES,
  );
  if (terminal) {
    return json({
      ok: terminal.status === "COMPLETED",
      durable: true,
      job: terminal,
      go: false,
    });
  }
  const state = await readSmallJson(
    env.STRUCTURED_BUCKET,
    personalJobStateKey("d1-backup", jobId),
    STATE_MAX_BYTES,
  );
  if (state && state.status === "SUBMITTED") {
    const expiresAt = Date.parse(String(state.expires_at ?? ""));
    if (Number.isFinite(expiresAt) && expiresAt <= now.getTime()) {
      return json({
        ok: false,
        durable: false,
        observation_only: true,
        job: { ...state, status: "SUBMITTED" },
        expired: true,
        expires_at: state.expires_at,
        go: false,
      });
    }
    return json({
      ok: false,
      durable: false,
      job: state,
      go: false,
    });
  }
  return json({ ok: false, error: "job_not_found", job_id: jobId, go: false }, 404);
}
