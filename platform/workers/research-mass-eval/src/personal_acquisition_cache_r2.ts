/** Cache immutable R2 checksum binds the trusted first-writer shard; this DRAFT cache does not re-prove raw body_digest or claim Receipt/READY. */

export const PERSONAL_ACQUISITION_CACHE_FORMAT =
  "personal-draft-acquisition-cache/v1";
export const PERSONAL_ACQUISITION_CACHE_PLANE = "personal_acquisition_cache";
export const PERSONAL_ACQUISITION_CACHE_GZIP_MAX_BYTES = 536_870_912;
export const PERSONAL_ACQUISITION_CACHE_SQLITE_MAX_BYTES = 1_073_741_824;

const DATASETS = [
  "markets_calendar",
  "equities_master",
  "fins_summary",
  "equities_bars_daily",
] as const;
const DATASET_SET = new Set<string>(DATASETS);
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const KEY_RE =
  /^research\/personal\/acquisition-cache\/v1\/environment=(production|staging)\/dataset=(markets_calendar|equities_master|fins_summary|equities_bars_daily)\/month=(\d{4}-\d{2})\/identity=([0-9a-f]{64})\.sqlite\.gz$/;

const FORBIDDEN_TOKENS = [
  "authorization",
  "cookie",
  "set-cookie",
  "proxy-authorization",
  "api_key",
  "api-key",
  "x-api-key",
  "jquants_api_key",
  "password",
  "secret",
  "token",
  "credential",
  "credentials",
  "raw_headers",
  "request_headers",
  "raw-request-headers",
] as const;

const GET_HEADERS = [
  "accept",
  "accept-encoding",
  "connection",
  "host",
  "user-agent",
] as const;
const PUT_HEADERS = [
  ...GET_HEADERS,
  "content-length",
  "content-type",
  "x-acquisition-cache-raw-sha256",
  "x-content-sha256",
] as const;
const GET_FIXED: Record<string, string> = {
  accept: "application/gzip",
  "accept-encoding": "identity",
  connection: "close",
  "user-agent": "quant-personal-history/v13",
};
const PUT_FIXED: Record<string, string> = {
  ...GET_FIXED,
  "content-type": "application/gzip",
};
const METADATA_KEYS = [
  "dataset",
  "environment",
  "format",
  "identity",
  "immutable",
  "month",
  "plane",
  "raw_sha256",
  "sha256",
] as const;

export type PersonalAcquisitionCacheKey = {
  environment: "production" | "staging";
  dataset: (typeof DATASETS)[number];
  month: string;
  identity: string;
  key: string;
};

type R2Env = { STRUCTURED_BUCKET: R2Bucket };

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function isCalendarMonth(value: string): boolean {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const parsed = new Date(Date.UTC(year, month - 1, 1));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}` === value
  );
}

export function acquisitionCacheMonthIsClosed(
  month: string,
  now = new Date(),
): boolean {
  if (!isCalendarMonth(month)) return false;
  const year = Number(month.slice(0, 4));
  const monthNumber = Number(month.slice(5, 7));
  const end = new Date(Date.UTC(year, monthNumber, 0));
  return end.toISOString().slice(0, 10) < now.toISOString().slice(0, 10);
}

export function parsePersonalAcquisitionCacheKey(
  key: string,
  now = new Date(),
): PersonalAcquisitionCacheKey | null {
  const match = KEY_RE.exec(key);
  if (!match) return null;
  const environment = match[1] as "production" | "staging";
  const dataset = match[2] as PersonalAcquisitionCacheKey["dataset"];
  const month = match[3]!;
  const identity = match[4]!;
  if (
    !DATASET_SET.has(dataset) ||
    !HEX64_RE.test(identity) ||
    !isCalendarMonth(month) ||
    !acquisitionCacheMonthIsClosed(month, now)
  ) {
    return null;
  }
  return { environment, dataset, month, identity, key };
}

export function personalAcquisitionCacheObjectKey(
  parsed: Omit<PersonalAcquisitionCacheKey, "key">,
): string {
  return (
    `research/personal/acquisition-cache/v1/environment=${parsed.environment}` +
    `/dataset=${parsed.dataset}/month=${parsed.month}/identity=${parsed.identity}.sqlite.gz`
  );
}

function containsForbiddenToken(value: string): boolean {
  const lowered = value.toLowerCase();
  return FORBIDDEN_TOKENS.some((token) => lowered.includes(token));
}

function headerMap(request: Request): Map<string, string> | null {
  const seen = new Map<string, string>();
  for (const [name, value] of request.headers) {
    const key = name.trim().toLowerCase();
    if (seen.has(key) || containsForbiddenToken(key) || containsForbiddenToken(value)) {
      return null;
    }
    seen.set(key, value);
  }
  return seen;
}

function headersAreClosed(request: Request, method: "GET" | "HEAD" | "PUT"): boolean {
  const seen = headerMap(request);
  if (!seen) return false;
  const allowed = method === "PUT" ? PUT_HEADERS : GET_HEADERS;
  if (seen.size !== allowed.length) return false;
  if (allowed.some((name) => !seen.has(name))) return false;
  const host = seen.get("host") ?? "";
  if (host !== "research.r2") return false;
  const fixed = method === "PUT" ? PUT_FIXED : GET_FIXED;
  for (const [name, expected] of Object.entries(fixed)) {
    if (seen.get(name) !== expected) return false;
  }
  return true;
}

function contentLength(request: Request, maximum: number): number | null {
  const raw = request.headers.get("content-length");
  if (!raw || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) return null;
  return value;
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

type PutIdentity = PersonalAcquisitionCacheKey & {
  contentDigest: string;
  rawDigest: string;
};

function putIdentity(request: Request, key: string): PutIdentity | null {
  const parsed = parsePersonalAcquisitionCacheKey(key);
  const contentDigest = request.headers.get("x-content-sha256") ?? "";
  const rawDigest = request.headers.get("x-acquisition-cache-raw-sha256") ?? "";
  if (
    !parsed ||
    key !== personalAcquisitionCacheObjectKey(parsed) ||
    !DIGEST_RE.test(contentDigest) ||
    !DIGEST_RE.test(rawDigest)
  ) {
    return null;
  }
  return { ...parsed, contentDigest, rawDigest };
}

function metadataExact(metadata: Record<string, string> | undefined, identity: PutIdentity): boolean {
  if (!metadata) return false;
  const keys = Object.keys(metadata).sort();
  if (JSON.stringify(keys) !== JSON.stringify([...METADATA_KEYS].sort())) return false;
  for (const [name, value] of Object.entries(metadata)) {
    if (containsForbiddenToken(name) || containsForbiddenToken(value)) return false;
  }
  return (
    metadata.plane === PERSONAL_ACQUISITION_CACHE_PLANE &&
    metadata.format === PERSONAL_ACQUISITION_CACHE_FORMAT &&
    metadata.environment === identity.environment &&
    metadata.dataset === identity.dataset &&
    metadata.month === identity.month &&
    metadata.identity === identity.identity &&
    metadata.sha256 === identity.contentDigest &&
    metadata.raw_sha256 === identity.rawDigest &&
    metadata.immutable === "true"
  );
}

function existingMatches(object: R2Object, identity: PutIdentity): boolean {
  return (
    metadataExact(object.customMetadata, identity) &&
    checksumMatches(object, identity.contentDigest)
  );
}

function cacheMetadata(identity: PutIdentity): Record<string, string> {
  return {
    dataset: identity.dataset,
    environment: identity.environment,
    format: PERSONAL_ACQUISITION_CACHE_FORMAT,
    identity: identity.identity,
    immutable: "true",
    month: identity.month,
    plane: PERSONAL_ACQUISITION_CACHE_PLANE,
    raw_sha256: identity.rawDigest,
    sha256: identity.contentDigest,
  };
}

async function getObject(
  request: Request,
  env: R2Env,
  parsed: PersonalAcquisitionCacheKey,
): Promise<Response> {
  if (!headersAreClosed(request, "GET")) {
    return json({ error: "acquisition cache headers denied" }, 403);
  }
  if (request.method === "HEAD") {
    const object = await env.STRUCTURED_BUCKET.head(parsed.key);
    if (!object) return json({ error: "acquisition cache not found" }, 404);
    if (object.size < 1 || object.size > PERSONAL_ACQUISITION_CACHE_GZIP_MAX_BYTES) {
      return json({ error: "acquisition cache size denied" }, 403);
    }
    const identity: PutIdentity = {
      ...parsed,
      contentDigest: object.customMetadata?.sha256 ?? "",
      rawDigest: object.customMetadata?.raw_sha256 ?? "",
    };
    if (!metadataExact(object.customMetadata, identity) || !checksumMatches(object, identity.contentDigest)) {
      return json({ error: "acquisition cache identity mismatch" }, 403);
    }
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        "content-type": "application/gzip",
        "x-acquisition-cache-raw-sha256": identity.rawDigest,
        "x-content-sha256": identity.contentDigest,
      },
    });
  }
  const object = await env.STRUCTURED_BUCKET.get(parsed.key);
  if (!object) return json({ error: "acquisition cache not found" }, 404);
  if (object.size < 1 || object.size > PERSONAL_ACQUISITION_CACHE_GZIP_MAX_BYTES) {
    return json({ error: "acquisition cache size denied" }, 403);
  }
  const identity: PutIdentity = {
    ...parsed,
    contentDigest: object.customMetadata?.sha256 ?? "",
    rawDigest: object.customMetadata?.raw_sha256 ?? "",
  };
  if (!metadataExact(object.customMetadata, identity) || !checksumMatches(object, identity.contentDigest)) {
    return json({ error: "acquisition cache identity mismatch" }, 403);
  }
  const headers = new Headers({
    "content-length": String(object.size),
    "content-type": "application/gzip",
    "x-acquisition-cache-raw-sha256": identity.rawDigest,
    "x-content-sha256": identity.contentDigest,
  });
  object.writeHttpMetadata(headers);
  headers.delete("content-encoding");
  headers.set("content-length", String(object.size));
  headers.set("content-type", "application/gzip");
  const body = object.body.pipeThrough(new FixedLengthStream(object.size));
  return new Response(body, { status: 200, headers });
}

async function putObject(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  if (!headersAreClosed(request, "PUT")) {
    return json({ error: "acquisition cache headers denied" }, 403);
  }
  const identity = putIdentity(request, key);
  if (!identity) return json({ error: "invalid acquisition cache identity" }, 400);
  const length = contentLength(request, PERSONAL_ACQUISITION_CACHE_GZIP_MAX_BYTES);
  if (length === null || request.body === null) {
    return json({ error: "invalid acquisition cache length" }, 400);
  }
  const metadata = cacheMetadata(identity);
  if (
    Object.keys(metadata).length !== METADATA_KEYS.length ||
    METADATA_KEYS.some((name) => !(name in metadata))
  ) {
    return json({ error: "acquisition cache metadata denied" }, 400);
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return existingMatches(existing, identity)
      ? json({ ok: true, created: false, key })
      : json({ error: "immutable acquisition cache conflict" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(
      key,
      request.body.pipeThrough(new FixedLengthStream(length)),
      {
        httpMetadata: { contentType: "application/gzip" },
        customMetadata: metadata,
        sha256: digestBytes(identity.contentDigest),
        onlyIf: { etagDoesNotMatch: "*" },
      },
    );
  } catch {
    return json({ error: "acquisition cache upload checksum rejected" }, 502);
  }
  if (put !== null) {
    if (put.size !== length) {
      return json({ error: "acquisition cache length mismatch" }, 400);
    }
    return json({ ok: true, created: true, key }, 201);
  }
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && existingMatches(raced, identity)
    ? json({ ok: true, created: false, key })
    : json({ error: "immutable acquisition cache conflict" }, 409);
}

export function isPersonalAcquisitionCacheOutboundRequest(
  _request: Request,
  key: string,
): boolean {
  return parsePersonalAcquisitionCacheKey(key) !== null;
}

export async function personalAcquisitionCacheR2Outbound(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const parsed = parsePersonalAcquisitionCacheKey(key);
  if (!parsed || parsed.key !== key) {
    return json({ error: "acquisition cache key denied" }, 403);
  }
  if (request.method === "GET" || request.method === "HEAD") {
    return getObject(request, env, parsed);
  }
  if (request.method === "PUT") {
    return putObject(request, env, key);
  }
  return json({ error: "acquisition cache method denied" }, 403);
}
