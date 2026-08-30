import { putBytesCreateOnly } from "./http";
import {
  PERSONAL_OPTION_SIDECAR_AUTHORITY,
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_OBJECT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OBJECT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OUTPUT_BYTES,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  PERSONAL_OPTION_SIDECAR_TERMINAL_MAX_BYTES,
  calendarDayFromKey,
  isPersonalOptionSidecarDigest,
  optionsDayFromKey,
  personalOptionSidecarInputKey,
  personalOptionSidecarObjectKey,
  personalOptionSidecarRequestDigest,
  personalOptionSidecarTerminalKey,
  type PersonalOptionSidecarInputManifest,
  type StructuredObjectRef,
} from "./personal_option_sidecar_producer_contract";
import { isPersonalResearchJobId } from "./personal_research_contract";
import { sha256Hex } from "./sha256";

type R2Env = { STRUCTURED_BUCKET: R2Bucket };
type Identity = {
  jobId: string;
  inputKey: string;
  inputDigest: string;
};

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function identity(request: Request): Identity | null {
  const jobId = request.headers.get("x-option-sidecar-job-id") ?? "";
  const inputKey = request.headers.get("x-option-sidecar-input-manifest-key") ?? "";
  const inputDigest =
    request.headers.get("x-option-sidecar-input-manifest-digest") ?? "";
  if (
    !isPersonalResearchJobId(jobId) ||
    inputKey !== personalOptionSidecarInputKey(jobId) ||
    !isPersonalOptionSidecarDigest(inputDigest)
  ) {
    return null;
  }
  return { jobId, inputKey, inputDigest };
}

function contentLength(request: Request, maximum: number): number | null {
  const raw = request.headers.get("content-length") ?? "";
  if (!/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 && value <= maximum
    ? value
    : null;
}

function digestBytes(digest: string): Uint8Array {
  const hex = digest.slice("sha256:".length);
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function checksumMatches(object: R2Object, digest: string): boolean {
  const actual = object.checksums?.sha256;
  if (!actual) return object.customMetadata?.sha256 === digest;
  const expected = digestBytes(digest);
  const actualBytes = new Uint8Array(actual);
  return (
    actualBytes.byteLength === expected.byteLength &&
    actualBytes.every((value, index) => value === expected[index])
  );
}

function headMatches(object: R2Object, digest: string, size?: number): boolean {
  if (object.customMetadata?.sha256 && object.customMetadata.sha256 !== digest) {
    return false;
  }
  if (size !== undefined && object.size !== size) return false;
  return checksumMatches(object, digest);
}

function listedRef(
  manifest: PersonalOptionSidecarInputManifest,
  key: string,
): StructuredObjectRef | null {
  const optionsDay = optionsDayFromKey(key);
  for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
    const locked = manifest.periods[period.period_id];
    const calendar = locked.calendar.find((object) => object.key === key);
    if (calendar) return calendar;
    if (!optionsDay) continue;
    const entry = locked.options.find((candidate) => candidate.date === optionsDay);
    const found = entry?.objects.find((object) => object.key === key);
    if (found) return found;
  }
  return null;
}

function inputShape(
  parsed: unknown,
  expected: Identity,
): parsed is PersonalOptionSidecarInputManifest {
  return (
    isObject(parsed) &&
    parsed.schema_version === PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA &&
    parsed.producer_id === PERSONAL_OPTION_SIDECAR_PRODUCER_ID &&
    parsed.job_id === expected.jobId &&
    parsed.cohort_id === PERSONAL_OPTION_SIDECAR_COHORT_ID &&
    parsed.runner_version === PERSONAL_OPTION_SIDECAR_RUNNER_VERSION &&
    isObject(parsed.periods)
  );
}

async function readInput(
  env: R2Env,
  expected: Identity,
): Promise<{ manifest: PersonalOptionSidecarInputManifest; bytes: Uint8Array } | null> {
  const object = await env.STRUCTURED_BUCKET.get(expected.inputKey);
  if (
    !object ||
    object.size < 1 ||
    object.size > PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES
  ) {
    return null;
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (`sha256:${await sha256Hex(bytes)}` !== expected.inputDigest) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  return inputShape(parsed, expected) ? { manifest: parsed, bytes } : null;
}

async function getInput(
  request: Request,
  env: R2Env,
  key: string,
  expected: Identity,
): Promise<Response> {
  const loaded = await readInput(env, expected);
  if (!loaded) return json({ error: "option sidecar input manifest denied" }, 403);
  if (key === expected.inputKey) {
    return new Response(loaded.bytes, {
      status: 200,
      headers: {
        "content-length": String(loaded.bytes.byteLength),
        "content-type": "application/json; charset=utf-8",
        "x-content-sha256": expected.inputDigest,
      },
    });
  }
  const reference = listedRef(loaded.manifest, key);
  if (!reference) return json({ error: "option sidecar input key not listed" }, 403);
  const maximum = calendarDayFromKey(key)
    ? PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_OBJECT_BYTES
    : PERSONAL_OPTION_SIDECAR_MAX_OBJECT_BYTES;
  const object =
    request.method === "HEAD"
      ? await env.STRUCTURED_BUCKET.head(key)
      : await env.STRUCTURED_BUCKET.get(key);
  if (!object) return json({ error: "option sidecar input missing" }, 404);
  if (object.etag !== reference.etag || object.size !== reference.size) {
    return json({ error: "option sidecar input changed after admission" }, 409);
  }
  if (object.size > maximum) {
    return json({ error: "option sidecar input size denied" }, 403);
  }
  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        etag: object.httpEtag,
      },
    });
  }
  const headers = new Headers({
    "content-length": String(object.size),
    etag: object.httpEtag,
    "x-listed-sha256": reference.sha256,
  });
  object.writeHttpMetadata(headers);
  return new Response((object as R2ObjectBody).body, { status: 200, headers });
}

function outputKind(
  key: string,
  jobId: string,
  digest: string,
): "object" | "manifest" | null {
  if (key === personalOptionSidecarTerminalKey(jobId)) return "manifest";
  if (key === personalOptionSidecarObjectKey(digest)) return "object";
  return null;
}

function authority(document: Record<string, unknown>): boolean {
  return (
    document.producer_id === PERSONAL_OPTION_SIDECAR_PRODUCER_ID &&
    document.cohort_id === PERSONAL_OPTION_SIDECAR_COHORT_ID &&
    document.draft_only === PERSONAL_OPTION_SIDECAR_AUTHORITY.draft_only &&
    document.screening_only === PERSONAL_OPTION_SIDECAR_AUTHORITY.screening_only &&
    document.ready === PERSONAL_OPTION_SIDECAR_AUTHORITY.ready &&
    document.mass === PERSONAL_OPTION_SIDECAR_AUTHORITY.mass &&
    document.promotion === PERSONAL_OPTION_SIDECAR_AUTHORITY.promotion &&
    document.live_orders === PERSONAL_OPTION_SIDECAR_AUTHORITY.live_orders &&
    document.go === PERSONAL_OPTION_SIDECAR_AUTHORITY.go &&
    document.not_a_pass === PERSONAL_OPTION_SIDECAR_AUTHORITY.not_a_pass
  );
}

async function completedChildrenMatch(
  env: R2Env,
  parsed: Record<string, unknown>,
  manifest: PersonalOptionSidecarInputManifest,
): Promise<boolean> {
  if (!isObject(parsed.sidecars)) return false;
  const ids = Object.keys(parsed.sidecars).sort();
  const expected = PERSONAL_OPTION_SIDECAR_PERIODS.map((period) => period.period_id).sort();
  if (JSON.stringify(ids) !== JSON.stringify(expected)) return false;
  for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
    const row = parsed.sidecars[period.period_id];
    const locked = manifest.periods[period.period_id];
    if (!isObject(row) || !locked) return false;
    const digest = row.sha256;
    const size = row.size;
    if (
      row.period_id !== period.period_id ||
      row.year !== period.year ||
      row.period_start !== period.period_start ||
      row.period_end !== period.period_end ||
      row.raw_input_digest !== locked.raw_input_digest ||
      row.calendar_digest !== locked.calendar_digest ||
      typeof digest !== "string" ||
      !isPersonalOptionSidecarDigest(digest) ||
      typeof size !== "number" ||
      !Number.isInteger(size) ||
      size < 1 ||
      size > PERSONAL_OPTION_SIDECAR_MAX_OUTPUT_BYTES ||
      row.key !== personalOptionSidecarObjectKey(digest)
    ) {
      return false;
    }
    const head = await env.STRUCTURED_BUCKET.head(
      personalOptionSidecarObjectKey(digest),
    );
    if (!head || !headMatches(head, digest, size)) return false;
  }
  return true;
}

async function putOutput(
  request: Request,
  env: R2Env,
  key: string,
  expected: Identity,
): Promise<Response> {
  const digest = request.headers.get("x-content-sha256") ?? "";
  if (!isPersonalOptionSidecarDigest(digest)) {
    return json({ error: "option sidecar output digest denied" }, 403);
  }
  const kind = outputKind(key, expected.jobId, digest);
  if (!kind) return json({ error: "option sidecar output key denied" }, 403);
  const maximum =
    kind === "manifest"
      ? PERSONAL_OPTION_SIDECAR_TERMINAL_MAX_BYTES
      : PERSONAL_OPTION_SIDECAR_MAX_OUTPUT_BYTES;
  const length = contentLength(request, maximum);
  if (length === null || request.body === null) {
    return json({ error: "option sidecar output length denied" }, 400);
  }
  const input = await readInput(env, expected);
  if (!input) return json({ error: "option sidecar input manifest denied" }, 403);
  const terminalKey = personalOptionSidecarTerminalKey(expected.jobId);
  if (kind !== "manifest" && (await env.STRUCTURED_BUCKET.head(terminalKey))) {
    return json({ error: "option sidecar child after terminal" }, 409);
  }
  if (kind === "manifest") {
    const bytes = new Uint8Array(await request.arrayBuffer());
    if (bytes.byteLength !== length || `sha256:${await sha256Hex(bytes)}` !== digest) {
      return json({ error: "option sidecar output bytes mismatch" }, 400);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return json({ error: "option sidecar output must be JSON" }, 400);
    }
    if (!isObject(parsed)) {
      return json({ error: "option sidecar output must be JSON" }, 400);
    }
    const requestDigest = await personalOptionSidecarRequestDigest(
      { job_id: expected.jobId },
      expected.inputDigest,
    );
    if (
      parsed.schema_version !== PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA ||
      parsed.job_id !== expected.jobId ||
      parsed.input_manifest_digest !== expected.inputDigest ||
      parsed.input_manifest_key !== expected.inputKey ||
      parsed.request_digest !== requestDigest ||
      parsed.kind !== PERSONAL_OPTION_SIDECAR_KIND ||
      parsed.producer_id !== PERSONAL_OPTION_SIDECAR_PRODUCER_ID ||
      parsed.cohort_id !== PERSONAL_OPTION_SIDECAR_COHORT_ID ||
      parsed.runner_version !== PERSONAL_OPTION_SIDECAR_RUNNER_VERSION ||
      !authority(parsed) ||
      (parsed.status !== "COMPLETED" && parsed.status !== "FAILED")
    ) {
      return json({ error: "option sidecar manifest contract mismatch" }, 400);
    }
    if (
      parsed.status === "COMPLETED" &&
      !(await completedChildrenMatch(env, parsed, input.manifest))
    ) {
      return json({ error: "option sidecar manifest children mismatch" }, 409);
    }
    const existing = await env.STRUCTURED_BUCKET.head(key);
    if (existing) {
      return headMatches(existing, digest, length)
        ? json({ ok: true, created: false, key })
        : json({ error: "immutable option sidecar output conflict" }, 409);
    }
    const stored = await putBytesCreateOnly(env.STRUCTURED_BUCKET, key, bytes, {
      digest,
      contentType: "application/json; charset=utf-8",
      customMetadata: {
        plane: "personal_option_sidecar_producer",
        kind,
        job_id: expected.jobId,
        input_manifest_digest: expected.inputDigest,
      },
    });
    return stored.conflict
      ? json({ error: "immutable option sidecar output conflict" }, 409)
      : json({ ok: true, created: stored.created, key }, stored.created ? 201 : 200);
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return headMatches(existing, digest, length)
      ? json({ ok: true, created: false, key })
      : json({ error: "immutable option sidecar output conflict" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, request.body, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: {
        plane: "personal_option_sidecar_producer",
        kind,
        job_id: expected.jobId,
        input_manifest_digest: expected.inputDigest,
        sha256: digest,
        immutable: "true",
      },
      sha256: digestBytes(digest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return json({ error: "option sidecar output checksum rejected" }, 400);
  }
  if (put !== null) {
    if (await env.STRUCTURED_BUCKET.head(terminalKey)) {
      return json({ error: "option sidecar child after terminal" }, 409);
    }
    return json({ ok: true, created: true, key }, 201);
  }
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && headMatches(raced, digest, length)
    ? json({ ok: true, created: false, key })
    : json({ error: "immutable option sidecar output conflict" }, 409);
}

export function isPersonalOptionSidecarOutboundRequest(
  request: Request,
  key: string,
): boolean {
  return (
    request.headers.has("x-option-sidecar-job-id") ||
    key.startsWith("research/personal/option-sidecar/")
  );
}

export async function personalOptionSidecarR2Outbound(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const expected = identity(request);
  if (!expected) return json({ error: "option sidecar R2 identity denied" }, 403);
  if (request.method === "GET" || request.method === "HEAD") {
    return getInput(request, env, key, expected);
  }
  if (request.method === "PUT") {
    return putOutput(request, env, key, expected);
  }
  return json({ error: "option sidecar R2 method denied" }, 403);
}
