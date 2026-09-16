import { json } from "./http";
import { isPersonalResearchJobId } from "./personal_research_contract";
import {
  D1_BACKUP_MAX_SQL_BYTES,
  d1ExportDownloadUrlDenied,
  d1ExportUrlSha256,
  parseD1ExportBundle,
} from "./d1_backup_encrypt_contract";

export const D1_EXPORT_HOST = "d1.export";
const DOWNLOAD_PATH = "/v1/download";
const KEY_PATH = "/v1/key";
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const MAX_REDIRECTS = 3;
const DOWNLOAD_TIMEOUT_MS = 30 * 60 * 1000;
const KEY_BYTES = 32;

export type D1ExportEnv = {
  D1_BACKUP_EXPORT_BUNDLE?: string;
  D1_BACKUP_KEY?: string;
};

function backupJobIdentity(request: Request): boolean {
  const jobId = request.headers.get("x-personal-job-id") ?? "";
  const digest = request.headers.get("x-personal-request-digest") ?? "";
  const kind = request.headers.get("x-personal-job-kind") ?? "";
  return (
    kind === "d1-backup" &&
    isPersonalResearchJobId(jobId) &&
    DIGEST_RE.test(digest)
  );
}


function parseBackupKey(raw: string): Uint8Array | null {
  const utf8 = new TextEncoder().encode(raw);
  if (utf8.byteLength === KEY_BYTES) return utf8;
  try {
    const bin = atob(raw.trim());
    if (bin.length !== KEY_BYTES) return null;
    const out = new Uint8Array(KEY_BYTES);
    for (let i = 0; i < KEY_BYTES; i += 1) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

async function streamSignedExport(
  signedUrl: string,
  maxBytes: number,
  allowedHost: string,
): Promise<Response> {
  let current: URL;
  try {
    current = new URL(signedUrl);
  } catch {
    return json({ error: "d1 export url denied", go: false }, 403);
  }
  if (d1ExportDownloadUrlDenied(current.toString(), allowedHost)) {
    return json({ error: "d1 export url denied", go: false }, 403);
  }
  for (let hop = 0; hop <= MAX_REDIRECTS; hop += 1) {
    let response: Response;
    try {
      response = await fetch(current, {
        method: "GET",
        redirect: "manual",
        signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS),
      });
    } catch {
      return json({ error: "d1 export download failed", go: false }, 502);
    }
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location) {
        return json({ error: "d1 export redirect denied", go: false }, 502);
      }
      let next: URL;
      try {
        next = new URL(location, current);
      } catch {
        return json({ error: "d1 export redirect denied", go: false }, 502);
      }
      if (d1ExportDownloadUrlDenied(next.toString(), allowedHost)) {
        return json({ error: "d1 export redirect denied", go: false }, 403);
      }
      current = next;
      continue;
    }
    if (!response.ok || response.body === null) {
      return json({ error: "d1 export download failed", go: false }, 502);
    }
    const declared = response.headers.get("content-length");
    if (declared && /^\d+$/.test(declared) && Number(declared) > maxBytes) {
      return json({ error: "d1 export exceeds sql byte bound", go: false }, 413);
    }
    let seen = 0;
    const cap = new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        seen += chunk.byteLength;
        if (seen > maxBytes) {
          controller.error(new Error("bounded"));
          return;
        }
        controller.enqueue(chunk);
      },
    });
    const headers = new Headers({ "content-type": "application/sql" });
    if (declared && /^\d+$/.test(declared)) {
      headers.set("content-length", declared);
    }
    return new Response(response.body.pipeThrough(cap), { status: 200, headers });
  }
  return json({ error: "d1 export redirect denied", go: false }, 502);
}

/**
 * Container-only SQL/key proxy. Container internet stays off.
 * Operator later places one export bundle (descriptor + signed_url) and the
 * 32-byte backup key. Download requires the job's signed_url sha256 to match
 * the current bundle so a swapped same-host URL cannot be labelled as this job.
 */
export async function d1ExportSourceOutbound(
  request: Request,
  env: D1ExportEnv,
): Promise<Response> {
  const url = new URL(request.url);
  if (
    url.hostname !== D1_EXPORT_HOST ||
    url.search ||
    url.hash ||
    (url.pathname !== DOWNLOAD_PATH && url.pathname !== KEY_PATH)
  ) {
    return json({ error: "d1 export request denied" }, 403);
  }
  if (request.method !== "GET") {
    return json({ error: "GET required" }, 405);
  }
  if (!backupJobIdentity(request)) {
    return json({ error: "d1 export request denied" }, 403);
  }
  if (url.pathname === KEY_PATH) {
    const raw = env.D1_BACKUP_KEY;
    if (!raw) {
      return json({ error: "backup_key_unavailable", go: false }, 409);
    }
    const key = parseBackupKey(raw);
    if (!key) {
      return json({ error: "backup_key_unavailable", go: false }, 409);
    }
    return new Response(key, {
      status: 200,
      headers: {
        "content-type": "application/octet-stream",
        "content-length": String(KEY_BYTES),
      },
    });
  }
  const parsed = await parseD1ExportBundle(env.D1_BACKUP_EXPORT_BUNDLE);
  if (!parsed.ok) {
    return json({ error: "export_not_authorized", go: false }, 409);
  }
  const expected = await d1ExportUrlSha256(parsed.value.signed_url);
  const provided = request.headers.get("x-d1-export-url-sha256") ?? "";
  if (provided !== expected) {
    return json({ error: "export_identity_mismatch", go: false }, 409);
  }
  return streamSignedExport(
    parsed.value.signed_url,
    D1_BACKUP_MAX_SQL_BYTES,
    parsed.value.download_host,
  );
}
