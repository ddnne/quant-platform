import {
  isPersonalResearchJobId,
  isPersonalResearchSnapshotKey,
  personalResearchManifestKey,
  personalResearchResultKey,
} from "./personal_research_contract";
import {
  isPersonalSviOutboundRequest,
  personalSviR2Outbound,
} from "./personal_svi_r2";
import {
  isPersonalIndexVolOverlayOutboundRequest,
  personalIndexVolOverlayR2Outbound,
} from "./personal_index_vol_overlay_r2";
import { sha256Hex } from "./sha256";

const RESULT_MAX_BYTES = 512 * 1024 * 1024;
const MANIFEST_MAX_BYTES = 64 * 1024;
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;

type R2Env = { STRUCTURED_BUCKET: R2Bucket };

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function contentLength(request: Request, maximum: number): number | null {
  const raw = request.headers.get("content-length");
  if (!raw || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) return null;
  return value;
}

function outputIdentity(
  request: Request,
): { jobId: string; requestDigest: string; contentDigest: string } | null {
  const jobId = request.headers.get("x-personal-job-id") ?? "";
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  const contentDigest = request.headers.get("x-content-sha256") ?? "";
  if (
    !isPersonalResearchJobId(jobId) ||
    !DIGEST_RE.test(requestDigest) ||
    !DIGEST_RE.test(contentDigest)
  ) {
    return null;
  }
  return { jobId, requestDigest, contentDigest };
}

function digestBytes(digest: string): Uint8Array {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid sha256 digest");
  const hex = digest.slice("sha256:".length);
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function checksumMatches(object: R2Object, digest: string): boolean {
  const actual = object.checksums.sha256;
  if (!actual) return false;
  const expected = digestBytes(digest);
  const actualBytes = new Uint8Array(actual);
  return (
    actualBytes.byteLength === expected.byteLength &&
    actualBytes.every((value, index) => value === expected[index])
  );
}

function existingMatches(
  object: R2Object,
  identity: { requestDigest: string; contentDigest: string },
): boolean {
  return (
    object.customMetadata?.request_digest === identity.requestDigest &&
    object.customMetadata?.sha256 === identity.contentDigest &&
    checksumMatches(object, identity.contentDigest)
  );
}

async function putResult(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const identity = outputIdentity(request);
  if (!identity || key !== personalResearchResultKey(identity.jobId)) {
    return responseJson({ error: "invalid result identity" }, 400);
  }
  const length = contentLength(request, RESULT_MAX_BYTES);
  if (length === null || request.body === null) {
    return responseJson({ error: "invalid result length" }, 400);
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return existingMatches(existing, identity)
      ? responseJson({ ok: true, created: false, key })
      : responseJson({ error: "immutable result conflict" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, request.body, {
      httpMetadata: {
        contentType: "application/gzip",
        contentDisposition: `attachment; filename="${identity.jobId}.tar.gz"`,
      },
      customMetadata: {
        plane: "personal_research",
        job_id: identity.jobId,
        request_digest: identity.requestDigest,
        sha256: identity.contentDigest,
        immutable: "true",
      },
      sha256: digestBytes(identity.contentDigest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return responseJson({ error: "result upload checksum rejected" }, 502);
  }
  if (put !== null) return responseJson({ ok: true, created: true, key }, 201);
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && existingMatches(raced, identity)
    ? responseJson({ ok: true, created: false, key })
    : responseJson({ error: "immutable result conflict" }, 409);
}

async function putManifest(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const identity = outputIdentity(request);
  if (!identity || key !== personalResearchManifestKey(identity.jobId)) {
    return responseJson({ error: "invalid manifest identity" }, 400);
  }
  const length = contentLength(request, MANIFEST_MAX_BYTES);
  if (length === null) return responseJson({ error: "invalid manifest length" }, 400);
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength !== length) {
    return responseJson({ error: "manifest length mismatch" }, 400);
  }
  const actualDigest = `sha256:${await sha256Hex(bytes)}`;
  if (actualDigest !== identity.contentDigest) {
    return responseJson({ error: "manifest digest mismatch" }, 400);
  }
  let manifest: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("not object");
    }
    manifest = parsed as Record<string, unknown>;
  } catch {
    return responseJson({ error: "manifest must be JSON object" }, 400);
  }
  const status = manifest.status;
  if (
    manifest.job_id !== identity.jobId ||
    manifest.request_digest !== identity.requestDigest ||
    (status !== "COMPLETED" && status !== "FAILED")
  ) {
    return responseJson({ error: "manifest identity mismatch" }, 400);
  }
  if (status === "COMPLETED") {
    const resultDigest =
      typeof manifest.result_sha256 === "string" ? manifest.result_sha256 : "";
    const result = await env.STRUCTURED_BUCKET.head(
      personalResearchResultKey(identity.jobId),
    );
    if (
      !result ||
      !DIGEST_RE.test(resultDigest) ||
      result.customMetadata?.request_digest !== identity.requestDigest ||
      resultDigest !== result.customMetadata?.sha256 ||
      !checksumMatches(result, resultDigest)
    ) {
      return responseJson({ error: "completed manifest has no matching result" }, 409);
    }
  }

  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return existingMatches(existing, identity)
      ? responseJson({ ok: true, created: false, key })
      : responseJson({ error: "immutable manifest conflict" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, bytes, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: {
        plane: "personal_research",
        job_id: identity.jobId,
        request_digest: identity.requestDigest,
        sha256: identity.contentDigest,
        status,
        immutable: "true",
      },
      sha256: digestBytes(identity.contentDigest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return responseJson({ error: "manifest upload checksum rejected" }, 502);
  }
  if (put !== null) return responseJson({ ok: true, created: true, key }, 201);
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && existingMatches(raced, identity)
    ? responseJson({ ok: true, created: false, key })
    : responseJson({ error: "immutable manifest conflict" }, 409);
}

async function getSnapshot(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  if (!isPersonalResearchSnapshotKey(key)) {
    return responseJson({ error: "snapshot key denied" }, 403);
  }
  if (request.method === "HEAD") {
    const object = await env.STRUCTURED_BUCKET.head(key);
    if (!object) return responseJson({ error: "snapshot not found" }, 404);
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        "content-type": key.endsWith(".sqlite.gz")
          ? "application/gzip"
          : "application/vnd.sqlite3",
        etag: object.httpEtag,
      },
    });
  }
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object) return responseJson({ error: "snapshot not found" }, 404);
  const headers = new Headers({
    "content-length": String(object.size),
    etag: object.httpEtag,
  });
  object.writeHttpMetadata(headers);
  headers.delete("content-encoding");
  headers.set("content-length", String(object.size));
  headers.set(
    "content-type",
    key.endsWith(".sqlite.gz") ? "application/gzip" : "application/vnd.sqlite3",
  );
  const body = object.body.pipeThrough(new FixedLengthStream(object.size));
  return new Response(body, { status: 200, headers });
}

/** Narrow R2 capability exposed only to the private Container virtual host. */
export async function personalResearchR2Outbound(
  request: Request,
  env: R2Env,
): Promise<Response> {
  const url = new URL(request.url);
  const key = url.pathname.startsWith("/") ? url.pathname.slice(1) : url.pathname;
  if (url.hostname !== "research.r2" || url.search || url.hash || key.includes("%")) {
    return responseJson({ error: "R2 request denied" }, 403);
  }
  if (isPersonalIndexVolOverlayOutboundRequest(request, key)) {
    return personalIndexVolOverlayR2Outbound(request, env, key);
  }
  if (isPersonalSviOutboundRequest(request, key)) {
    return personalSviR2Outbound(request, env, key);
  }
  if ((request.method === "GET" || request.method === "HEAD") &&
      isPersonalResearchSnapshotKey(key)) {
    return getSnapshot(request, env, key);
  }
  if (request.method === "PUT" && /\/result\.tar\.gz$/.test(key)) {
    return putResult(request, env, key);
  }
  if (request.method === "PUT" && /\/manifest\.json$/.test(key)) {
    return putManifest(request, env, key);
  }
  return responseJson({ error: "R2 method or key denied" }, 403);
}
