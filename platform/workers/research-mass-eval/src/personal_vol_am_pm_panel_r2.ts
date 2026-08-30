import { putBytesCreateOnly } from "./http";
import {
  PERSONAL_VOL_AM_PM_EVALUATION_PERIODS,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_TERMINAL_MAX_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
  isPersonalVolAmPmPanelDigest,
  personalVolAmPmPanelBuildInputKey,
  personalVolAmPmPanelBuildTerminalKey,
  personalVolAmPmPanelObjectKey,
  type PersonalVolAmPmPanelWriterInputManifest,
} from "./personal_vol_am_pm_panel_writer_contract";
import { PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION } from "./personal_vol_am_pm_panel";
import {
  isPersonalResearchJobId,
  isPersonalResearchSnapshotKey,
} from "./personal_research_contract";
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
  const jobId = request.headers.get("x-vol-panel-job-id") ?? "";
  const inputKey = request.headers.get("x-vol-panel-input-manifest-key") ?? "";
  const inputDigest = request.headers.get("x-vol-panel-input-manifest-digest") ?? "";
  if (
    !isPersonalResearchJobId(jobId) ||
    inputKey !== personalVolAmPmPanelBuildInputKey(jobId) ||
    !isPersonalVolAmPmPanelDigest(inputDigest)
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
  manifest: PersonalVolAmPmPanelWriterInputManifest,
  key: string,
): { etag: string; size: number } | null {
  if (key.startsWith("research/mass_eval/panels_cache/")) return null;
  if (key === manifest.selection.snapshot.key) return manifest.selection.snapshot;
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    const locked = manifest.periods[period.period_id];
    const sidecar = manifest.option_sidecars[period.period_id];
    if (key === locked.snapshot.key) return locked.snapshot;
    if (key === sidecar.source_key) return { etag: sidecar.etag, size: sidecar.size };
  }
  return null;
}

function inputShape(
  parsed: unknown,
  expected: Identity,
): parsed is PersonalVolAmPmPanelWriterInputManifest {
  return (
    isObject(parsed) &&
    parsed.schema_version === PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA &&
    parsed.producer_id === PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID &&
    parsed.job_id === expected.jobId &&
    parsed.cohort_id === PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID &&
    parsed.runner_version === PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION &&
    parsed.panel_schema === PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION &&
    isObject(parsed.selection) &&
    isObject(parsed.periods) &&
    isObject(parsed.sidecar_producer) &&
    isObject(parsed.option_sidecars)
  );
}

async function readInput(
  env: R2Env,
  expected: Identity,
): Promise<{ manifest: PersonalVolAmPmPanelWriterInputManifest; bytes: Uint8Array } | null> {
  const object = await env.STRUCTURED_BUCKET.get(expected.inputKey);
  if (
    !object ||
    object.size < 1 ||
    object.size > PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES
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
  if (!loaded) return json({ error: "vol panel input manifest denied" }, 403);
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
  if (!reference) return json({ error: "vol panel input key not listed" }, 403);
  const maximum = isPersonalResearchSnapshotKey(key)
    ? 4 * 1024 * 1024 * 1024
    : PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES;
  const object =
    request.method === "HEAD"
      ? await env.STRUCTURED_BUCKET.head(key)
      : await env.STRUCTURED_BUCKET.get(key);
  if (!object) return json({ error: "vol panel input missing" }, 404);
  if (object.etag !== reference.etag || object.size !== reference.size) {
    return json({ error: "vol panel input changed after admission" }, 409);
  }
  if (object.size > maximum) return json({ error: "vol panel input size denied" }, 403);
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
  });
  object.writeHttpMetadata(headers);
  return new Response((object as R2ObjectBody).body, { status: 200, headers });
}

function outputKind(
  key: string,
  jobId: string,
  digest: string,
): "object" | "manifest" | null {
  if (key === personalVolAmPmPanelBuildTerminalKey(jobId)) return "manifest";
  if (key === personalVolAmPmPanelObjectKey(digest)) return "object";
  return null;
}

function authority(document: Record<string, unknown>): boolean {
  return (
    document.producer_id === PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID &&
    document.cohort_id === PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID &&
    document.go === false
  );
}

async function completedChildrenMatch(
  env: R2Env,
  parsed: Record<string, unknown>,
): Promise<boolean> {
  if (!isObject(parsed.periods) || !isObject(parsed.membership)) return false;
  const codes = parsed.membership.codes;
  if (!Array.isArray(codes) || codes.length < 1) return false;
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    const row = parsed.periods[period.period_id];
    if (!isObject(row)) return false;
    const panelDigest = row.panel_sha256;
    const panelSize = row.panel_size;
    if (
      typeof panelDigest !== "string" ||
      !isPersonalVolAmPmPanelDigest(panelDigest) ||
      typeof panelSize !== "number" ||
      !Number.isInteger(panelSize) ||
      panelSize < 1 ||
      row.panel_key !== personalVolAmPmPanelObjectKey(panelDigest)
    ) {
      return false;
    }
    const head = await env.STRUCTURED_BUCKET.head(
      personalVolAmPmPanelObjectKey(panelDigest),
    );
    if (!head || !headMatches(head, panelDigest, panelSize)) return false;
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
  if (!isPersonalVolAmPmPanelDigest(digest)) {
    return json({ error: "vol panel output digest denied" }, 403);
  }
  const kind = outputKind(key, expected.jobId, digest);
  if (!kind) return json({ error: "vol panel output key denied" }, 403);
  const maximum =
    kind === "manifest"
      ? PERSONAL_VOL_AM_PM_PANEL_BUILD_TERMINAL_MAX_BYTES
      : PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES;
  const length = contentLength(request, maximum);
  if (length === null || request.body === null) {
    return json({ error: "vol panel output length denied" }, 400);
  }
  const input = await readInput(env, expected);
  if (!input) return json({ error: "vol panel input manifest denied" }, 403);
  const terminalKey = personalVolAmPmPanelBuildTerminalKey(expected.jobId);
  if (kind !== "manifest") {
    if (await env.STRUCTURED_BUCKET.head(terminalKey)) {
      return json({ error: "vol panel child after terminal" }, 409);
    }
  }
  if (kind === "manifest") {
    const bytes = new Uint8Array(await request.arrayBuffer());
    if (bytes.byteLength !== length || `sha256:${await sha256Hex(bytes)}` !== digest) {
      return json({ error: "vol panel output bytes mismatch" }, 400);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return json({ error: "vol panel output must be JSON" }, 400);
    }
    if (!isObject(parsed)) return json({ error: "vol panel output must be JSON" }, 400);
    if (
      parsed.schema_version !== PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA ||
      parsed.job_id !== expected.jobId ||
      parsed.input_manifest_digest !== expected.inputDigest ||
      parsed.kind !== PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND ||
      parsed.runner_version !== PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION ||
      !authority(parsed) ||
      (parsed.status !== "COMPLETED" && parsed.status !== "FAILED")
    ) {
      return json({ error: "vol panel manifest contract mismatch" }, 400);
    }
    if (
      parsed.status === "COMPLETED" &&
      !(await completedChildrenMatch(env, parsed))
    ) {
      return json({ error: "vol panel manifest children mismatch" }, 409);
    }
    const existing = await env.STRUCTURED_BUCKET.head(key);
    if (existing) {
      return headMatches(existing, digest, length)
        ? json({ ok: true, created: false, key })
        : json({ error: "immutable vol panel output conflict" }, 409);
    }
    const stored = await putBytesCreateOnly(env.STRUCTURED_BUCKET, key, bytes, {
      digest,
      contentType: "application/json; charset=utf-8",
      customMetadata: {
        plane: "personal_vol_am_pm_panel_writer",
        kind,
        job_id: expected.jobId,
        input_manifest_digest: expected.inputDigest,
      },
    });
    return stored.conflict
      ? json({ error: "immutable vol panel output conflict" }, 409)
      : json({ ok: true, created: stored.created, key }, stored.created ? 201 : 200);
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return headMatches(existing, digest, length)
      ? json({ ok: true, created: false, key })
      : json({ error: "immutable vol panel output conflict" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, request.body, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: {
        plane: "personal_vol_am_pm_panel_writer",
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
    return json({ error: "vol panel output checksum rejected" }, 400);
  }
  if (put !== null) {
    // Cheap diagnostic only: do not delete the shared content-addressed
    // object. A FAILED terminal racing this PUT can leave an unreferenced
    // orphan; consumers read only COMPLETED terminal child refs.
    if (await env.STRUCTURED_BUCKET.head(terminalKey)) {
      return json({ error: "vol panel child after terminal" }, 409);
    }
    return json({ ok: true, created: true, key }, 201);
  }
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && headMatches(raced, digest, length)
    ? json({ ok: true, created: false, key })
    : json({ error: "immutable vol panel output conflict" }, 409);
}

export function isPersonalVolAmPmPanelOutboundRequest(
  request: Request,
  key: string,
): boolean {
  return (
    request.headers.has("x-vol-panel-job-id") ||
    key.startsWith("research/personal/vol-ratio-am-pm-v1/panel-builds/") ||
    key.startsWith("research/personal/vol-ratio-am-pm-v1/objects/")
  );
}

export async function personalVolAmPmPanelR2Outbound(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const expected = identity(request);
  if (!expected) return json({ error: "vol panel R2 identity denied" }, 403);
  if (request.method === "GET" || request.method === "HEAD") {
    return getInput(request, env, key, expected);
  }
  if (request.method === "PUT") {
    return putOutput(request, env, key, expected);
  }
  return json({ error: "vol panel R2 method denied" }, 403);
}
