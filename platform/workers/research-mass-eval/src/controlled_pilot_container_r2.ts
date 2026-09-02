import {
  CONTROLLED_JOB_KEY_PREFIX,
  CONTROLLED_PILOT_CONTRACT,
  CONTROLLED_PILOT_GENERATION,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_PILOT_MAX_PARALLEL,
  CONTROLLED_PILOT_PLAN_COUNT,
} from "./controlled_pilot_contract";
import { decodeStrictJson, isRecord } from "./controlled_pilot_json";
import { sha256Hex } from "./sha256";

export const CONTROLLED_PILOT_RUNNER_VERSION = String(
  (CONTROLLED_PILOT_CONTRACT as { runner_version?: string }).runner_version ||
    "controlled-pilot-container/v1",
);
export const CONTROLLED_CONTAINER_KIND = "controlled-pilot";
export const CONTROLLED_STAGE_MAX_BYTES = 16 * 1024;
export const CONTROLLED_TERMINAL_MAX_BYTES = 64 * 1024;
export const CONTROLLED_LEASE_MAX_BYTES = 8 * 1024;
const TERMINAL_ENVELOPE_OVERHEAD = 2048;
// Stored lease GET cap: claim PUT is still CONTROLLED_LEASE_MAX_BYTES; terminal
// CAS embeds the logical terminal (base64) plus a closed envelope overhead.
export const CONTROLLED_LEASE_STORED_MAX_BYTES =
  CONTROLLED_LEASE_MAX_BYTES +
  Math.ceil(CONTROLLED_TERMINAL_MAX_BYTES / 3) * 4 +
  TERMINAL_ENVELOPE_OVERHEAD;
export const CONTROLLED_LEASE_TTL_SECONDS = Number(
  (CONTROLLED_PILOT_CONTRACT as { lease_ttl_seconds?: number }).lease_ttl_seconds,
);
export const CONTROLLED_LEASE_CLOCK_SKEW_SECONDS = 30;
export const CONTROLLED_JSON_TYPE = "application/json; charset=utf-8";
const BYOB_CHUNK_BYTES = 1024;
const WEAK_ETAG_PREFIX = /^[Ww]\//;

const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const JOB_RE = /^[a-z0-9][a-z0-9._-]{7,63}$/;
const STAGE_RE = new RegExp(
  `^${CONTROLLED_JOB_KEY_PREFIX.replace(/\//g, "\\/")}([a-z0-9][a-z0-9._-]{7,63})\\/container-stage\\.json$`,
);
const TERMINAL_RE = new RegExp(
  `^${CONTROLLED_JOB_KEY_PREFIX.replace(/\//g, "\\/")}([a-z0-9][a-z0-9._-]{7,63})\\/container-terminal\\.json$`,
);
const LEASE_RE = new RegExp(
  `^${CONTROLLED_JOB_KEY_PREFIX.replace(/\//g, "\\/")}([a-z0-9][a-z0-9._-]{7,63})\\/container-lease\\.json$`,
);

type R2Env = { STRUCTURED_BUCKET: R2Bucket };
type ControlledObject = "stage" | "terminal" | "lease";

const REQUIRED_HEADERS = [
  "x-personal-job-id",
  "x-personal-request-digest",
  "x-personal-runner-version",
  "x-personal-job-kind",
] as const;

export type BoundedReadTrace = {
  pulled: number;
  forwarded: number;
  cancelled: boolean;
};

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": CONTROLLED_JSON_TYPE },
  });
}

export function parseControlledContainerObject(
  key: string,
): { kind: ControlledObject; jobId: string } | null {
  const stage = STAGE_RE.exec(key);
  if (stage) return { kind: "stage", jobId: stage[1]! };
  const terminal = TERMINAL_RE.exec(key);
  if (terminal) return { kind: "terminal", jobId: terminal[1]! };
  const lease = LEASE_RE.exec(key);
  if (lease) return { kind: "lease", jobId: lease[1]! };
  return null;
}

function maxBytes(kind: ControlledObject): number {
  if (kind === "stage") return CONTROLLED_STAGE_MAX_BYTES;
  if (kind === "lease") return CONTROLLED_LEASE_MAX_BYTES;
  return CONTROLLED_TERMINAL_MAX_BYTES;
}

function storedMaxBytes(kind: ControlledObject): number {
  if (kind === "stage") return CONTROLLED_STAGE_MAX_BYTES;
  if (kind === "lease") return CONTROLLED_LEASE_STORED_MAX_BYTES;
  return CONTROLLED_TERMINAL_MAX_BYTES;
}

function identityHeaders(request: Request, jobId: string): Response | null {
  const personal: string[] = [];
  for (const [name] of request.headers) {
    const lower = name.toLowerCase();
    if (lower.startsWith("x-personal-")) personal.push(lower);
  }
  const extras = new Set([
    "x-personal-lease-owner",
    "x-personal-fencing-token",
    "x-personal-lease-etag",
  ]);
  if (
    REQUIRED_HEADERS.some((name) => !personal.includes(name)) ||
    personal.some((name) => !REQUIRED_HEADERS.includes(name as typeof REQUIRED_HEADERS[number]) && !extras.has(name))
  ) {
    return responseJson({ error: "controlled identity headers denied" }, 403);
  }
  const headerJob = request.headers.get("x-personal-job-id") ?? "";
  const digest = request.headers.get("x-personal-request-digest") ?? "";
  const runner = request.headers.get("x-personal-runner-version") ?? "";
  const kind = request.headers.get("x-personal-job-kind") ?? "";
  if (
    headerJob !== jobId ||
    !JOB_RE.test(headerJob) ||
    !DIGEST_RE.test(digest) ||
    runner !== CONTROLLED_PILOT_RUNNER_VERSION ||
    kind !== CONTROLLED_CONTAINER_KIND
  ) {
    return responseJson({ error: "controlled identity denied" }, 403);
  }
  return null;
}

function declaredLength(request: Request, maximum: number): number | null {
  const raw = request.headers.get("content-length");
  if (!raw) return null;
  if (!/^\d+$/.test(raw)) return -1;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1) return -1;
  if (value > maximum) return -2;
  return value;
}

function trustedNowSeconds(): number {
  return Date.now() / 1000;
}

function copyBytes(view: Uint8Array): Uint8Array {
  const copy = new Uint8Array(view.byteLength);
  copy.set(view);
  return copy;
}

function isUsableRawEtag(value: string): boolean {
  return (
    value.length > 0 &&
    value !== "*" &&
    !value.includes(",") &&
    !value.includes('"') &&
    !WEAK_ETAG_PREFIX.test(value) &&
    !/[\x00-\x1f\x7f ]/.test(value)
  );
}

function quoteHttpEtag(raw: string): string {
  return `"${raw}"`;
}

function parseSingleStrongEtag(value: string): string | null {
  if (
    value.length < 1 ||
    value.includes(",") ||
    value === "*" ||
    WEAK_ETAG_PREFIX.test(value)
  ) {
    return null;
  }
  if (value.startsWith('"')) {
    if (value.length < 3 || !value.endsWith('"')) return null;
    const inner = value.slice(1, -1);
    if (!isUsableRawEtag(inner)) return null;
    return inner;
  }
  if (!isUsableRawEtag(value)) return null;
  return value;
}

function callerEtagMatchesRaw(caller: string | null, raw: string): boolean {
  if (caller === null) return false;
  const parsed = parseSingleStrongEtag(caller);
  return parsed !== null && parsed === raw;
}

function rawR2Etag(object: { etag?: string }): string | null {
  const raw = object.etag;
  if (typeof raw !== "string" || !isUsableRawEtag(raw)) return null;
  return raw;
}

function httpEtagFromPut(object: { etag?: string; httpEtag?: string }): string | null {
  const raw = rawR2Etag(object);
  if (!raw) return null;
  return quoteHttpEtag(raw);
}

async function cancelReader(
  reader: ReadableStreamBYOBReader | undefined,
  stream: ReadableStream<Uint8Array> | null,
  reason: string,
): Promise<void> {
  if (reader) {
    try {
      await reader.cancel(reason);
      return;
    } catch {
      // already closed or cancelled
    }
  }
  if (stream) {
    try {
      await stream.cancel(reason);
    } catch {
      // Body may already be locked or closed.
    }
  }
}

function getByobReader(
  stream: ReadableStream<Uint8Array>,
): ReadableStreamBYOBReader | null {
  try {
    const reader = stream.getReader({ mode: "byob" });
    if (!reader || typeof reader.read !== "function") return null;
    return reader;
  } catch {
    return null;
  }
}

export async function readBoundedBody(
  request: Request,
  maximum: number,
  trace?: BoundedReadTrace,
): Promise<Uint8Array | Response> {
  if (trace) {
    trace.pulled = 0;
    trace.forwarded = 0;
    trace.cancelled = false;
  }
  const declared = declaredLength(request, maximum);
  if (declared === -1) {
    await cancelReader(undefined, request.body, "controlled object length denied");
    if (trace) trace.cancelled = true;
    return responseJson({ error: "controlled object length denied" }, 400);
  }
  if (declared === -2) {
    await cancelReader(undefined, request.body, "controlled object exceeds bound");
    if (trace) trace.cancelled = true;
    return responseJson({ error: "controlled object exceeds bound" }, 413);
  }
  if (request.body === null) {
    return responseJson({ error: "controlled object length denied" }, 400);
  }
  const stream = request.body;
  const reader = getByobReader(stream);
  if (!reader) {
    await cancelReader(undefined, stream, "controlled object length denied");
    if (trace) trace.cancelled = true;
    return responseJson({ error: "controlled object length denied" }, 400);
  }
  const hardCap = declared !== null ? Math.min(maximum, declared) : maximum;
  const chunks: Uint8Array[] = [];
  let received = 0;
  while (true) {
    const room = hardCap + 1 - received;
    if (room <= 0) {
      await cancelReader(reader, stream, "controlled object exceeds bound");
      if (trace) {
        trace.cancelled = true;
        trace.forwarded = 0;
      }
      return responseJson({ error: "controlled object exceeds bound" }, 413);
    }
    const requestBytes = Math.min(BYOB_CHUNK_BYTES, room);
    const view = new Uint8Array(requestBytes);
    let step: ReadableStreamReadResult<Uint8Array>;
    try {
      step = await reader.read(view);
    } catch {
      await cancelReader(reader, stream, "controlled object length denied");
      if (trace) {
        trace.cancelled = true;
        trace.forwarded = 0;
      }
      return responseJson({ error: "controlled object length denied" }, 400);
    }
    if (step.done) break;
    const value = step.value;
    if (!value) break;
    if (trace) trace.pulled += value.byteLength;
    if (value.byteLength > requestBytes) {
      await cancelReader(reader, stream, "controlled object exceeds bound");
      if (trace) {
        trace.cancelled = true;
        trace.forwarded = 0;
      }
      return responseJson({ error: "controlled object exceeds bound" }, 413);
    }
    const next = received + value.byteLength;
    if (next > hardCap) {
      await cancelReader(reader, stream, "controlled object exceeds bound");
      if (trace) {
        trace.cancelled = true;
        trace.forwarded = 0;
      }
      if (next > maximum) {
        return responseJson({ error: "controlled object exceeds bound" }, 413);
      }
      return responseJson({ error: "controlled object length mismatch" }, 400);
    }
    chunks.push(copyBytes(value));
    received = next;
  }
  if (received < 1) {
    if (trace) trace.forwarded = 0;
    return responseJson({ error: "controlled object length denied" }, 400);
  }
  if (declared !== null && received !== declared) {
    if (trace) trace.forwarded = 0;
    return responseJson({ error: "controlled object length mismatch" }, 400);
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  if (trace) trace.forwarded = received;
  return bytes;
}

const LEASE_FIELDS = [
  "identity",
  "job_id",
  "request_digest",
  "execution_id",
  "runner_version",
  "kind",
  "owner_nonce",
  "fencing_token",
  "expires_at",
  "heartbeat_at",
  "status",
] as const;

const TERMINAL_LEASE_FIELDS = [
  ...LEASE_FIELDS,
  "terminal_digest",
  "terminal_status",
  "terminal_payload_b64",
] as const;

const LOGICAL_TERMINAL_BIND_FIELDS = [
  "identity",
  "job_id",
  "request_digest",
  "execution_id",
  "runner_version",
  "owner_nonce",
  "fencing_token",
  "status",
] as const;

const LOGICAL_COMPLETED_FIELDS = [
  ...LOGICAL_TERMINAL_BIND_FIELDS,
  "ok",
  "automatic_promotion",
  "live_orders_enabled",
  "ephemeral_cleaned",
  "papers",
  "risks",
  "selection",
  "knowledge",
  "generation",
  "max_parallel",
] as const;

const LOGICAL_FAILED_FIELDS = [
  ...LOGICAL_TERMINAL_BIND_FIELDS,
  "ok",
  "error",
  "go",
  "automatic_promotion",
  "live_orders_enabled",
] as const;

const FAILED_ERROR_MAX_CHARS = 500;

function exactFields(
  parsed: Record<string, unknown>,
  fields: readonly string[],
): boolean {
  const keys = Object.keys(parsed);
  return (
    keys.length === fields.length &&
    keys.every((key) => fields.includes(key))
  );
}

function closedFencingToken(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 1 &&
    value <= Number.MAX_SAFE_INTEGER
  );
}

function closedOwnerNonce(value: unknown): value is string {
  return typeof value === "string" && value.length >= 8;
}

function parseFenceHeader(value: string): number | null {
  if (!/^[1-9][0-9]*$/.test(value)) return null;
  const token = Number(value);
  if (!closedFencingToken(token)) return null;
  return token;
}

function closedLeaseTimes(parsed: Record<string, unknown>): boolean {
  const ttl = CONTROLLED_LEASE_TTL_SECONDS;
  if (!Number.isSafeInteger(ttl) || ttl < 1) return false;
  return (
    typeof parsed.expires_at === "number" &&
    Number.isFinite(parsed.expires_at) &&
    typeof parsed.heartbeat_at === "number" &&
    Number.isFinite(parsed.heartbeat_at) &&
    parsed.expires_at > parsed.heartbeat_at &&
    parsed.expires_at - parsed.heartbeat_at <= ttl
  );
}

function heartbeatNotTooFarInFuture(
  parsed: Record<string, unknown>,
  nowSeconds: number,
): boolean {
  return (
    typeof parsed.heartbeat_at === "number" &&
    Number.isFinite(parsed.heartbeat_at) &&
    parsed.heartbeat_at <= nowSeconds + CONTROLLED_LEASE_CLOCK_SKEW_SECONDS
  );
}

function closedLease(parsed: Record<string, unknown>, jobId: string, requestDigest: string): boolean {
  if (!exactFields(parsed, LEASE_FIELDS)) return false;
  return (
    parsed.identity === CONTROLLED_PILOT_IDENTITY &&
    parsed.job_id === jobId &&
    parsed.request_digest === requestDigest &&
    typeof parsed.execution_id === "string" &&
    DIGEST_RE.test(parsed.execution_id) &&
    parsed.runner_version === CONTROLLED_PILOT_RUNNER_VERSION &&
    parsed.kind === CONTROLLED_CONTAINER_KIND &&
    closedOwnerNonce(parsed.owner_nonce) &&
    closedFencingToken(parsed.fencing_token) &&
    closedLeaseTimes(parsed) &&
    parsed.status === "CLAIMED"
  );
}

const LEASE_IMMUTABLE_FIELDS = [
  "identity",
  "job_id",
  "request_digest",
  "execution_id",
  "runner_version",
  "kind",
] as const;

function claimedLeaseTimesValid(
  parsed: Record<string, unknown>,
  nowSeconds: number,
): boolean {
  const ttl = CONTROLLED_LEASE_TTL_SECONDS;
  if (!Number.isSafeInteger(ttl) || ttl < 1) return false;
  const heartbeat = Number(parsed.heartbeat_at);
  const expires = Number(parsed.expires_at);
  if (!Number.isFinite(heartbeat) || !Number.isFinite(expires)) return false;
  if (Math.abs(heartbeat - nowSeconds) > CONTROLLED_LEASE_CLOCK_SKEW_SECONDS) {
    return false;
  }
  if (!(expires > heartbeat)) return false;
  if (expires - heartbeat > ttl) return false;
  if (!(expires > nowSeconds)) return false;
  return true;
}

function sameLeaseIdentity(
  current: Record<string, unknown>,
  next: Record<string, unknown>,
): boolean {
  return LEASE_IMMUTABLE_FIELDS.every((field) => current[field] === next[field]);
}

function leasePutTransition(
  current: Record<string, unknown>,
  next: Record<string, unknown>,
  nowSeconds: number,
): "renew" | "takeover" | "deny" {
  if (current.status !== "CLAIMED") return "deny";
  if (!sameLeaseIdentity(current, next)) return "deny";
  const currentExpires = Number(current.expires_at);
  const currentHeartbeat = Number(current.heartbeat_at);
  const currentToken = Number(current.fencing_token);
  const nextToken = Number(next.fencing_token);
  const nextHeartbeat = Number(next.heartbeat_at);
  const nextExpires = Number(next.expires_at);
  if (
    !Number.isFinite(currentExpires) ||
    !Number.isFinite(currentHeartbeat) ||
    !Number.isSafeInteger(currentToken) ||
    currentToken < 1
  ) {
    return "deny";
  }
  const expired = currentExpires <= nowSeconds;
  if (!expired) {
    if (current.owner_nonce !== next.owner_nonce) return "deny";
    if (currentToken !== nextToken) return "deny";
    if (!(nextHeartbeat > currentHeartbeat)) return "deny";
    if (!(nextExpires >= currentExpires)) return "deny";
    return "renew";
  }
  if (currentToken >= Number.MAX_SAFE_INTEGER) return "deny";
  const expected = currentToken + 1;
  if (!Number.isSafeInteger(expected) || nextToken !== expected) return "deny";
  return "takeover";
}

function digestBytes(digest: string): Uint8Array {
  const hex = digest.slice("sha256:".length);
  const bytes = new Uint8Array(32);
  for (let i = 0; i < 32; i += 1) {
    bytes[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function encodeBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x2000;
  for (let i = 0; i < bytes.byteLength; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function decodeBase64(value: string): Uint8Array | null {
  try {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  } catch {
    return null;
  }
}

function decodeCanonicalBase64(value: string): Uint8Array | null {
  if (
    value.length < 4 ||
    value.length % 4 !== 0 ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(value)
  ) {
    return null;
  }
  const decoded = decodeBase64(value);
  if (!decoded || decoded.byteLength < 1) return null;
  if (encodeBase64(decoded) !== value) return null;
  return decoded;
}

async function boundedExisting(
  bucket: R2Bucket,
  key: string,
  maximum: number,
): Promise<{ digest: string; size: number; etag: string } | "oversized" | null> {
  const object = await bucket.get(key);
  if (!object) return null;
  if (object.size > maximum) return "oversized";
  const stored = new Uint8Array(await object.arrayBuffer());
  if (stored.byteLength > maximum) return "oversized";
  return {
    digest: `sha256:${await sha256Hex(stored)}`,
    size: stored.byteLength,
    etag: rawR2Etag(object) ?? "",
  };
}

function documentMatches(
  parsed: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
  kind: ControlledObject,
): boolean {
  if (parsed.job_id !== jobId || parsed.request_digest !== requestDigest) return false;
  if (parsed.identity !== CONTROLLED_PILOT_IDENTITY) return false;
  if (kind === "terminal") {
    return parsed.status === "COMPLETED" || parsed.status === "FAILED";
  }
  if (kind === "stage") {
    return parsed.execution_id !== undefined;
  }
  return typeof parsed.owner_nonce === "string" && parsed.owner_nonce.length >= 8;
}

type LeaseSnapshot = {
  bytes: Uint8Array;
  doc: Record<string, unknown>;
  etag: string;
  httpEtag: string;
  sha256: string;
};

function leaseMetadata(jobId: string, sha256: string): Record<string, string> {
  return {
    plane: "controlled_pilot",
    job_id: jobId,
    sha256,
  };
}

function closedJobIdentity(
  doc: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
): boolean {
  return (
    doc.identity === CONTROLLED_PILOT_IDENTITY &&
    doc.job_id === jobId &&
    doc.request_digest === requestDigest &&
    typeof doc.execution_id === "string" &&
    DIGEST_RE.test(doc.execution_id) &&
    doc.runner_version === CONTROLLED_PILOT_RUNNER_VERSION
  );
}

function storedStageReadable(
  doc: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
): boolean {
  return closedJobIdentity(doc, jobId, requestDigest);
}

function storedClaimedLeaseValid(
  doc: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
  nowSeconds = trustedNowSeconds(),
): boolean {
  return (
    closedLease(doc, jobId, requestDigest) &&
    heartbeatNotTooFarInFuture(doc, nowSeconds)
  );
}

function fourClosedRecords(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === CONTROLLED_PILOT_PLAN_COUNT &&
    value.every((row) => isRecord(row))
  );
}

function closedLogicalTerminal(
  logical: Record<string, unknown>,
  lease: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
): boolean {
  if (logical.identity !== CONTROLLED_PILOT_IDENTITY) return false;
  if (logical.job_id !== jobId || logical.job_id !== lease.job_id) return false;
  if (logical.request_digest !== requestDigest || logical.request_digest !== lease.request_digest) {
    return false;
  }
  if (
    typeof logical.execution_id !== "string" ||
    !DIGEST_RE.test(logical.execution_id) ||
    logical.execution_id !== lease.execution_id
  ) {
    return false;
  }
  if (
    logical.runner_version !== CONTROLLED_PILOT_RUNNER_VERSION ||
    logical.runner_version !== lease.runner_version
  ) {
    return false;
  }
  if (!closedOwnerNonce(logical.owner_nonce) || logical.owner_nonce !== lease.owner_nonce) {
    return false;
  }
  if (!closedFencingToken(logical.fencing_token) || logical.fencing_token !== lease.fencing_token) {
    return false;
  }
  if (logical.status === "COMPLETED") {
    if (!exactFields(logical, LOGICAL_COMPLETED_FIELDS)) return false;
    return (
      logical.ok === true &&
      logical.automatic_promotion === false &&
      logical.live_orders_enabled === false &&
      logical.ephemeral_cleaned === true &&
      fourClosedRecords(logical.papers) &&
      fourClosedRecords(logical.risks) &&
      isRecord(logical.selection) &&
      isRecord(logical.knowledge) &&
      logical.generation === CONTROLLED_PILOT_GENERATION &&
      logical.max_parallel === CONTROLLED_PILOT_MAX_PARALLEL
    );
  }
  if (logical.status === "FAILED") {
    if (!exactFields(logical, LOGICAL_FAILED_FIELDS)) return false;
    return (
      logical.ok === false &&
      typeof logical.error === "string" &&
      logical.error.length >= 1 &&
      logical.error.length <= FAILED_ERROR_MAX_CHARS &&
      logical.go === false &&
      logical.automatic_promotion === false &&
      logical.live_orders_enabled === false
    );
  }
  return false;
}

type ClosedTerminalLease = {
  payload: Uint8Array;
  logical: Record<string, unknown>;
};

async function closedTerminalLease(
  doc: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
  nowSeconds = trustedNowSeconds(),
): Promise<ClosedTerminalLease | null> {
  if (!exactFields(doc, TERMINAL_LEASE_FIELDS)) return null;
  if (doc.identity !== CONTROLLED_PILOT_IDENTITY) return null;
  if (doc.job_id !== jobId) return null;
  if (doc.request_digest !== requestDigest) return null;
  if (typeof doc.execution_id !== "string" || !DIGEST_RE.test(doc.execution_id)) return null;
  if (doc.runner_version !== CONTROLLED_PILOT_RUNNER_VERSION) return null;
  if (doc.kind !== CONTROLLED_CONTAINER_KIND) return null;
  if (!closedOwnerNonce(doc.owner_nonce)) return null;
  if (!closedFencingToken(doc.fencing_token)) return null;
  if (!closedLeaseTimes(doc)) return null;
  if (!heartbeatNotTooFarInFuture(doc, nowSeconds)) return null;
  if (doc.status !== "TERMINAL") return null;
  if (typeof doc.terminal_digest !== "string" || !DIGEST_RE.test(doc.terminal_digest)) return null;
  if (doc.terminal_status !== "COMPLETED" && doc.terminal_status !== "FAILED") return null;
  if (typeof doc.terminal_payload_b64 !== "string") return null;
  const payload = decodeCanonicalBase64(doc.terminal_payload_b64);
  if (!payload || payload.byteLength > CONTROLLED_TERMINAL_MAX_BYTES) return null;
  const digest = `sha256:${await sha256Hex(payload)}`;
  if (digest !== doc.terminal_digest) return null;
  let parsed: unknown;
  try {
    parsed = decodeStrictJson(payload);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;
  if (parsed.status !== doc.terminal_status) return null;
  if (!closedLogicalTerminal(parsed, doc, jobId, requestDigest)) return null;
  return { payload, logical: parsed };
}

async function storedLeaseReadable(
  doc: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
): Promise<boolean> {
  if (await closedTerminalLease(doc, jobId, requestDigest)) return true;
  return storedClaimedLeaseValid(doc, jobId, requestDigest);
}

async function readLeaseSnapshot(
  bucket: R2Bucket,
  key: string,
): Promise<LeaseSnapshot | "invalid" | "oversized" | null> {
  const object = await bucket.get(key);
  if (!object) return null;
  if (object.size < 1 || object.size > CONTROLLED_LEASE_STORED_MAX_BYTES) return "oversized";
  const etag = rawR2Etag(object);
  if (!etag) return "invalid";
  const stored = new Uint8Array(await object.arrayBuffer());
  if (stored.byteLength > CONTROLLED_LEASE_STORED_MAX_BYTES) return "oversized";
  let doc: Record<string, unknown>;
  try {
    const value = decodeStrictJson(stored);
    if (!isRecord(value)) return "invalid";
    doc = value;
  } catch {
    return "invalid";
  }
  return {
    bytes: stored,
    doc,
    etag,
    httpEtag: quoteHttpEtag(etag),
    sha256: `sha256:${await sha256Hex(stored)}`,
  };
}

function leaseMatchesFence(
  leaseDoc: Record<string, unknown>,
  owner: string,
  token: number,
  nowSeconds: number,
): boolean {
  const expires = leaseDoc.expires_at;
  return (
    leaseDoc.owner_nonce === owner &&
    closedFencingToken(leaseDoc.fencing_token) &&
    leaseDoc.fencing_token === token &&
    leaseDoc.status === "CLAIMED" &&
    typeof expires === "number" &&
    Number.isFinite(expires) &&
    expires > nowSeconds
  );
}

function claimedLeaseAllowsTerminal(
  stored: Record<string, unknown>,
  terminalDoc: Record<string, unknown>,
  jobId: string,
  requestDigest: string,
  owner: string,
  token: number,
  nowSeconds: number,
): "ok" | "schema" | "identity" | "fence" {
  if (!storedClaimedLeaseValid(stored, jobId, requestDigest, nowSeconds)) {
    return "schema";
  }
  if (stored.execution_id !== terminalDoc.execution_id) return "identity";
  if (!leaseMatchesFence(stored, owner, token, nowSeconds)) return "fence";
  return "ok";
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.byteLength !== right.byteLength) return false;
  for (let i = 0; i < left.byteLength; i += 1) {
    if (left[i] !== right[i]) return false;
  }
  return true;
}

async function putCreateOnlyBytes(
  env: R2Env,
  key: string,
  bytes: Uint8Array,
  digest: string,
  jobId: string,
  requestDigest: string,
  maximum: number,
): Promise<Response> {
  const existing = await boundedExisting(env.STRUCTURED_BUCKET, key, maximum);
  if (existing === "oversized") {
    return responseJson({ error: "controlled object exceeds bound" }, 409);
  }
  if (existing) {
    return existing.digest === digest
      ? responseJson({ ok: true, created: false, key, digest }, 200)
      : responseJson({ error: "immutable controlled object conflict" }, 409);
  }
  const put = await env.STRUCTURED_BUCKET.put(key, bytes, {
    httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
    customMetadata: {
      plane: "controlled_pilot",
      job_id: jobId,
      request_digest: requestDigest,
      sha256: digest,
      immutable: "true",
    },
    sha256: digestBytes(digest),
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (put !== null) return responseJson({ ok: true, created: true, key, digest }, 201);
  const raced = await boundedExisting(env.STRUCTURED_BUCKET, key, maximum);
  if (raced && raced !== "oversized" && raced.digest === digest) {
    return responseJson({ ok: true, created: false, key, digest }, 200);
  }
  return responseJson({ error: "immutable controlled object conflict" }, 409);
}

function terminalResponseHeaders(bytes: Uint8Array, digest: string, etag: string): HeadersInit {
  return {
    "content-type": CONTROLLED_JSON_TYPE,
    "content-length": String(bytes.byteLength),
    etag,
    "x-content-sha256": digest,
  };
}

async function getTerminalFromLease(
  request: Request,
  env: R2Env,
  key: string,
  jobId: string,
): Promise<Response> {
  const denied = identityHeaders(request, jobId);
  if (denied) return denied;
  const leaseKey = key.replace(/container-terminal\.json$/, "container-lease.json");
  const lease = await readLeaseSnapshot(env.STRUCTURED_BUCKET, leaseKey);
  if (lease === "oversized" || lease === "invalid") {
    return responseJson({ error: "controlled object size denied" }, 403);
  }
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  if (!lease) {
    return responseJson({ error: "controlled object not found" }, 404);
  }
  const closed = await closedTerminalLease(lease.doc, jobId, requestDigest);
  if (!closed) {
    if (storedClaimedLeaseValid(lease.doc, jobId, requestDigest)) {
      return responseJson({ error: "controlled object not found" }, 404);
    }
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  const digest = `sha256:${await sha256Hex(closed.payload)}`;
  const headers = terminalResponseHeaders(closed.payload, digest, lease.httpEtag);
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });
  return new Response(closed.payload, { status: 200, headers });
}

function parseJsonObject(bytes: Uint8Array): Record<string, unknown> | null {
  try {
    const value = decodeStrictJson(bytes);
    return isRecord(value) ? value : null;
  } catch {
    return null;
  }
}

async function putTerminal(
  request: Request,
  env: R2Env,
  key: string,
  jobId: string,
): Promise<Response> {
  const denied = identityHeaders(request, jobId);
  if (denied) return denied;
  const digest = request.headers.get("x-content-sha256") ?? "";
  const type = request.headers.get("content-type") ?? "";
  if (!DIGEST_RE.test(digest)) {
    return responseJson({ error: "controlled object length denied" }, 400);
  }
  if (type !== CONTROLLED_JSON_TYPE && type !== "application/json") {
    return responseJson({ error: "controlled content type denied" }, 403);
  }
  const bounded = await readBoundedBody(request, CONTROLLED_TERMINAL_MAX_BYTES);
  if (bounded instanceof Response) return bounded;
  const bytes = bounded;
  const actual = `sha256:${await sha256Hex(bytes)}`;
  if (actual !== digest) return responseJson({ error: "controlled digest mismatch" }, 400);
  let parsed: Record<string, unknown>;
  try {
    const value = decodeStrictJson(bytes);
    if (!isRecord(value)) return responseJson({ error: "controlled object must be JSON" }, 400);
    parsed = value;
  } catch {
    return responseJson({ error: "controlled object must be JSON" }, 400);
  }
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  const owner = request.headers.get("x-personal-lease-owner") ?? "";
  const tokenHeader = request.headers.get("x-personal-fencing-token") ?? "";
  const token = parseFenceHeader(tokenHeader);
  if (!closedOwnerNonce(owner) || token === null) {
    return responseJson({ error: "controlled fencing token denied" }, 409);
  }
  if (parsed.owner_nonce !== owner || parsed.fencing_token !== token) {
    return responseJson({ error: "controlled fencing token denied" }, 409);
  }
  const clientEtag = request.headers.get("x-personal-lease-etag");
  const leaseKey = key.replace(/container-terminal\.json$/, "container-lease.json");
  const lease = await readLeaseSnapshot(env.STRUCTURED_BUCKET, leaseKey);
  if (lease === "oversized" || lease === "invalid") {
    return responseJson({ error: "controlled lease required" }, 409);
  }
  if (!lease) return responseJson({ error: "controlled lease required" }, 409);

  const existingClosed = await closedTerminalLease(lease.doc, jobId, requestDigest);
  if (existingClosed) {
    if (
      existingClosed.logical.owner_nonce === owner &&
      existingClosed.logical.fencing_token === token &&
      lease.doc.terminal_digest === digest &&
      bytesEqual(existingClosed.payload, bytes)
    ) {
      return responseJson({ ok: true, created: false, key, digest }, 200);
    }
    return responseJson({ error: "immutable controlled object conflict" }, 409);
  }
  if (lease.doc.status === "TERMINAL") {
    return responseJson({ error: "immutable controlled object conflict" }, 409);
  }

  const now = trustedNowSeconds();
  const allowed = claimedLeaseAllowsTerminal(
    lease.doc,
    parsed,
    jobId,
    requestDigest,
    owner,
    token,
    now,
  );
  if (allowed === "schema") {
    return responseJson({ error: "controlled lease schema denied" }, 409);
  }
  if (allowed === "identity") {
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  if (allowed !== "ok") {
    return responseJson({ error: "controlled fencing token denied" }, 409);
  }
  if (!closedLogicalTerminal(parsed, lease.doc, jobId, requestDigest)) {
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  if (clientEtag !== null && !callerEtagMatchesRaw(clientEtag, lease.etag)) {
    return responseJson({ error: "controlled fencing token denied" }, 409);
  }
  const casEtag = lease.etag;

  const terminalLease: Record<string, unknown> = {
    identity: lease.doc.identity,
    job_id: lease.doc.job_id,
    request_digest: lease.doc.request_digest,
    execution_id: lease.doc.execution_id,
    runner_version: lease.doc.runner_version,
    kind: lease.doc.kind,
    owner_nonce: lease.doc.owner_nonce,
    fencing_token: lease.doc.fencing_token,
    expires_at: lease.doc.expires_at,
    heartbeat_at: lease.doc.heartbeat_at,
    status: "TERMINAL",
    terminal_digest: digest,
    terminal_status: parsed.status,
    terminal_payload_b64: encodeBase64(bytes),
  };
  if (!(await closedTerminalLease(terminalLease, jobId, requestDigest))) {
    return responseJson({ error: "controlled lease required" }, 409);
  }
  const storedBytes = new TextEncoder().encode(JSON.stringify(terminalLease));
  if (storedBytes.byteLength > CONTROLLED_LEASE_STORED_MAX_BYTES) {
    return responseJson({ error: "controlled object exceeds bound" }, 413);
  }
  const storedSha = `sha256:${await sha256Hex(storedBytes)}`;
  const put = await env.STRUCTURED_BUCKET.put(leaseKey, storedBytes, {
    httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
    customMetadata: leaseMetadata(jobId, storedSha),
    sha256: digestBytes(storedSha),
    onlyIf: { etagMatches: casEtag },
  });
  if (put !== null) {
    return responseJson({ ok: true, created: true, key, digest }, 201);
  }
  const raced = await readLeaseSnapshot(env.STRUCTURED_BUCKET, leaseKey);
  if (raced && raced !== "oversized" && raced !== "invalid") {
    const racedClosed = await closedTerminalLease(raced.doc, jobId, requestDigest);
    if (
      racedClosed &&
      racedClosed.logical.owner_nonce === owner &&
      racedClosed.logical.fencing_token === token &&
      raced.doc.terminal_digest === digest &&
      bytesEqual(racedClosed.payload, bytes)
    ) {
      return responseJson({ ok: true, created: false, key, digest }, 200);
    }
  }
  return responseJson({ error: "immutable controlled object conflict" }, 409);
}

async function putCreateOnlyControlled(
  request: Request,
  env: R2Env,
  key: string,
  kind: ControlledObject,
  jobId: string,
): Promise<Response> {
  if (kind === "terminal") {
    return putTerminal(request, env, key, jobId);
  }
  const denied = identityHeaders(request, jobId);
  if (denied) return denied;
  const maximum = maxBytes(kind);
  const digest = request.headers.get("x-content-sha256") ?? "";
  const type = request.headers.get("content-type") ?? "";
  if (!DIGEST_RE.test(digest)) {
    return responseJson({ error: "controlled object length denied" }, 400);
  }
  if (type !== CONTROLLED_JSON_TYPE && type !== "application/json") {
    return responseJson({ error: "controlled content type denied" }, 403);
  }
  const bounded = await readBoundedBody(request, maximum);
  if (bounded instanceof Response) return bounded;
  const bytes = bounded;
  const actual = `sha256:${await sha256Hex(bytes)}`;
  if (actual !== digest) return responseJson({ error: "controlled digest mismatch" }, 400);
  const parsed = parseJsonObject(bytes);
  if (!parsed) return responseJson({ error: "controlled object must be JSON" }, 400);
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  if (!documentMatches(parsed, jobId, requestDigest, kind)) {
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  return putCreateOnlyBytes(env, key, bytes, digest, jobId, requestDigest, maximum);
}

async function putLease(
  request: Request,
  env: R2Env,
  key: string,
  jobId: string,
): Promise<Response> {
  const denied = identityHeaders(request, jobId);
  if (denied) return denied;
  const maximum = CONTROLLED_LEASE_MAX_BYTES;
  const digest = request.headers.get("x-content-sha256") ?? "";
  if (!DIGEST_RE.test(digest)) {
    return responseJson({ error: "controlled lease length denied" }, 400);
  }
  const bounded = await readBoundedBody(request, maximum);
  if (bounded instanceof Response) {
    const body = await bounded.json() as { error?: string };
    return responseJson({ error: String(body.error || "controlled lease length denied").replace("object", "lease") }, bounded.status);
  }
  const bytes = bounded;
  const actual = `sha256:${await sha256Hex(bytes)}`;
  if (actual !== digest) return responseJson({ error: "controlled digest mismatch" }, 400);
  const parsed = parseJsonObject(bytes);
  if (!parsed) return responseJson({ error: "controlled lease must be JSON" }, 400);
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  if (!closedLease(parsed, jobId, requestDigest)) {
    return responseJson({ error: "controlled lease schema denied" }, 400);
  }
  const now = trustedNowSeconds();
  const ifNone = request.headers.get("if-none-match");
  const ifMatch = request.headers.get("if-match");
  const clientLeaseEtag = request.headers.get("x-personal-lease-etag");
  const existing = await readLeaseSnapshot(env.STRUCTURED_BUCKET, key);
  if (existing === "oversized") {
    return responseJson({ error: "controlled lease cas conflict" }, 412);
  }
  if (existing === "invalid") {
    return responseJson({ error: "controlled lease schema denied" }, 409);
  }
  if (ifNone === "*") {
    if (existing) return responseJson({ error: "controlled lease exists" }, 412);
    if (parsed.fencing_token !== 1) {
      return responseJson({ error: "controlled lease schema denied" }, 400);
    }
    if (!claimedLeaseTimesValid(parsed, now)) {
      return responseJson({ error: "controlled lease freshness denied" }, 400);
    }
    const put = await env.STRUCTURED_BUCKET.put(key, bytes, {
      httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
      customMetadata: leaseMetadata(jobId, digest),
      sha256: digestBytes(digest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
    if (put === null) return responseJson({ error: "controlled lease exists" }, 412);
    const createdEtag = httpEtagFromPut(put);
    if (!createdEtag) return responseJson({ error: "controlled lease cas conflict" }, 412);
    return responseJson({ ok: true, created: true, key, etag: createdEtag }, 201);
  }
  if (ifMatch) {
    if (!existing) {
      return responseJson({ error: "controlled lease cas conflict" }, 412);
    }
    if (!callerEtagMatchesRaw(ifMatch, existing.etag)) {
      return responseJson({ error: "controlled lease cas conflict" }, 412);
    }
    if (clientLeaseEtag !== null && !callerEtagMatchesRaw(clientLeaseEtag, existing.etag)) {
      return responseJson({ error: "controlled lease cas conflict" }, 412);
    }
    if (await closedTerminalLease(existing.doc, jobId, requestDigest)) {
      return responseJson({ error: "controlled lease cas conflict" }, 412);
    }
    if (existing.doc.status === "TERMINAL") {
      return responseJson({ error: "controlled lease schema denied" }, 409);
    }
    if (!storedClaimedLeaseValid(existing.doc, jobId, requestDigest)) {
      return responseJson({ error: "controlled lease schema denied" }, 409);
    }
    if (!claimedLeaseTimesValid(parsed, now)) {
      return responseJson({ error: "controlled lease freshness denied" }, 400);
    }
    const transition = leasePutTransition(existing.doc, parsed, now);
    if (transition === "deny") {
      return responseJson({ error: "controlled lease fencing denied" }, 409);
    }
    const put = await env.STRUCTURED_BUCKET.put(key, bytes, {
      httpMetadata: { contentType: CONTROLLED_JSON_TYPE },
      customMetadata: leaseMetadata(jobId, digest),
      sha256: digestBytes(digest),
      onlyIf: { etagMatches: existing.etag },
    });
    if (put === null) return responseJson({ error: "controlled lease cas conflict" }, 412);
    const nextEtag = httpEtagFromPut(put);
    if (!nextEtag) return responseJson({ error: "controlled lease cas conflict" }, 412);
    return responseJson({ ok: true, created: false, key, etag: nextEtag }, 200);
  }
  return responseJson({ error: "controlled lease precondition required" }, 428);
}

async function getControlled(
  request: Request,
  env: R2Env,
  key: string,
  kind: ControlledObject,
  jobId: string,
): Promise<Response> {
  const denied = identityHeaders(request, jobId);
  if (denied) return denied;
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object) return responseJson({ error: "controlled object not found" }, 404);
  const maximum = storedMaxBytes(kind);
  if (object.size < 1 || object.size > maximum) {
    return responseJson({ error: "controlled object size denied" }, 403);
  }
  const stored = new Uint8Array(await object.arrayBuffer());
  if (stored.byteLength > maximum) {
    return responseJson({ error: "controlled object size denied" }, 403);
  }
  const parsed = parseJsonObject(stored);
  if (!parsed) {
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  const readable =
    kind === "lease"
      ? await storedLeaseReadable(parsed, jobId, requestDigest)
      : storedStageReadable(parsed, jobId, requestDigest);
  if (!readable) {
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  const raw = rawR2Etag(object);
  if (!raw) {
    return responseJson({ error: "controlled object identity mismatch" }, 403);
  }
  const headers = {
    "content-type": CONTROLLED_JSON_TYPE,
    "content-length": String(stored.byteLength),
    etag: quoteHttpEtag(raw),
  };
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });
  return new Response(stored, { status: 200, headers });
}

export async function controlledContainerR2Outbound(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response | null> {
  const parsed = parseControlledContainerObject(key);
  if (!parsed) return null;
  if (request.method === "GET" || request.method === "HEAD") {
    if (parsed.kind === "terminal") {
      return getTerminalFromLease(request, env, key, parsed.jobId);
    }
    return getControlled(request, env, key, parsed.kind, parsed.jobId);
  }
  if (request.method !== "PUT") {
    return responseJson({ error: "controlled method denied" }, 403);
  }
  if (parsed.kind === "lease") {
    return putLease(request, env, key, parsed.jobId);
  }
  return putCreateOnlyControlled(request, env, key, parsed.kind, parsed.jobId);
}
