import { putBytesCreateOnly } from "./http";
import {
  PERSONAL_VOL_AM_PM_COMMON_VALID_SCHEMA,
  PERSONAL_VOL_AM_PM_EVALUATION_PERIODS,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_MASK_BYTES,
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
  personalVolAmPmStablePanelKey,
  type PersonalVolAmPmEvaluationPeriodId,
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

function listedKeys(manifest: PersonalVolAmPmPanelWriterInputManifest): Set<string> {
  const keys = new Set<string>([
    manifest.selection.manifest.key,
    manifest.selection.snapshot.key,
  ]);
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    const locked = manifest.periods[period.period_id];
    const sidecar = manifest.option_sidecars[period.period_id];
    keys.add(locked.manifest.key);
    keys.add(locked.snapshot.key);
    keys.add(sidecar.source_key);
  }
  return keys;
}

function inputShape(
  parsed: unknown,
  expected: Identity,
): parsed is PersonalVolAmPmPanelWriterInputManifest {
  if (!isObject(parsed) || !isObject(parsed.authority) || !isObject(parsed.selection)) {
    return false;
  }
  const authority = parsed.authority;
  return (
    parsed.schema_version === PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA &&
    parsed.producer_id === PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID &&
    parsed.job_id === expected.jobId &&
    parsed.cohort_id === PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID &&
    parsed.runner_version === PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION &&
    parsed.panel_schema === PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION &&
    authority.draft_only === true &&
    authority.screening_only === true &&
    authority.ready === false &&
    authority.mass === false &&
    authority.promotion === false &&
    authority.live_orders === false &&
    authority.go === false &&
    authority.single_stock_option_iv === "FORBIDDEN" &&
    authority.cash_index_executable_fill === false &&
    authority.adjc_fallback === false &&
    authority.ffill === false &&
    authority.synthetic_calendar === false &&
    authority.caller_provenance === false &&
    isObject(parsed.periods) &&
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
  const digest = `sha256:${await sha256Hex(bytes)}`;
  if (digest !== expected.inputDigest) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  return inputShape(parsed, expected) ? { manifest: parsed, bytes } : null;
}

function listedRef(
  manifest: PersonalVolAmPmPanelWriterInputManifest,
  key: string,
): { etag: string; size: number } | null {
  if (key === manifest.selection.snapshot.key) {
    return manifest.selection.snapshot;
  }
  if (key === manifest.selection.manifest.key) {
    return manifest.selection.manifest;
  }
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    const locked = manifest.periods[period.period_id];
    const sidecar = manifest.option_sidecars[period.period_id];
    if (key === locked.snapshot.key) return locked.snapshot;
    if (key === locked.manifest.key) return locked.manifest;
    if (key === sidecar.source_key) {
      return { etag: sidecar.etag, size: sidecar.size };
    }
  }
  return null;
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
  if (!listedKeys(loaded.manifest).has(key)) {
    return json({ error: "vol panel input key not listed" }, 403);
  }
  const reference = listedRef(loaded.manifest, key);
  if (!reference) return json({ error: "vol panel input key not listed" }, 403);
  const maximum = isPersonalResearchSnapshotKey(key)
    ? 4 * 1024 * 1024 * 1024
    : PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES;
  if (request.method === "HEAD") {
    const object = await env.STRUCTURED_BUCKET.head(key);
    if (!object) return json({ error: "vol panel input missing" }, 404);
    if (object.etag !== reference.etag || object.size !== reference.size) {
      return json({ error: "vol panel input changed after admission" }, 409);
    }
    if (object.size > maximum) return json({ error: "vol panel input size denied" }, 403);
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        etag: object.httpEtag,
      },
    });
  }
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object) return json({ error: "vol panel input missing" }, 404);
  if (object.etag !== reference.etag || object.size !== reference.size) {
    return json({ error: "vol panel input changed after admission" }, 409);
  }
  if (object.size > maximum) return json({ error: "vol panel input size denied" }, 403);
  const headers = new Headers({
    "content-length": String(object.size),
    etag: object.httpEtag,
  });
  object.writeHttpMetadata(headers);
  return new Response(object.body, { status: 200, headers });
}

function outputKind(
  key: string,
  jobId: string,
  digest: string,
): "object" | "stable-panel" | "manifest" | null {
  if (key === personalVolAmPmPanelBuildTerminalKey(jobId)) return "manifest";
  if (key === personalVolAmPmPanelObjectKey(digest)) return "object";
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    if (key === personalVolAmPmStablePanelKey(period.period_id)) return "stable-panel";
  }
  return null;
}

function authority(document: Record<string, unknown>): boolean {
  return (
    document.producer_id === PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID &&
    document.cohort_id === PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID &&
    document.draft_only === true &&
    document.screening_only === true &&
    document.ready === false &&
    document.mass === false &&
    document.promotion === false &&
    document.live_orders === false &&
    document.go === false &&
    document.not_a_pass === true
  );
}

async function existingMatches(
  bucket: R2Bucket,
  key: string,
  digest: string,
  maximum: number,
): Promise<boolean> {
  const object = await bucket.get(key);
  if (!object || object.size > maximum) return false;
  if (object.customMetadata?.sha256 && object.customMetadata.sha256 !== digest) {
    return false;
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  return `sha256:${await sha256Hex(bytes)}` === digest;
}

async function completedChildrenMatch(
  env: R2Env,
  parsed: Record<string, unknown>,
): Promise<boolean> {
  if (!isObject(parsed.periods) || !isObject(parsed.membership)) return false;
  const membershipDigest = parsed.membership.digest;
  if (
    typeof membershipDigest !== "string" ||
    !isPersonalVolAmPmPanelDigest(membershipDigest)
  ) {
    return false;
  }
  if (
    !(await existingMatches(
      env.STRUCTURED_BUCKET,
      personalVolAmPmPanelObjectKey(membershipDigest),
      membershipDigest,
      PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_MASK_BYTES,
    ))
  ) {
    return false;
  }
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    const row = parsed.periods[period.period_id];
    if (!isObject(row)) return false;
    const panelDigest = row.panel_sha256;
    const maskDigest = row.common_valid_sha256;
    if (
      typeof panelDigest !== "string" ||
      typeof maskDigest !== "string" ||
      !isPersonalVolAmPmPanelDigest(panelDigest) ||
      !isPersonalVolAmPmPanelDigest(maskDigest) ||
      row.panel_key !== personalVolAmPmPanelObjectKey(panelDigest) ||
      row.common_valid_key !== personalVolAmPmPanelObjectKey(maskDigest) ||
      row.stable_key !== personalVolAmPmStablePanelKey(period.period_id)
    ) {
      return false;
    }
    const [panelOk, stableOk, maskOk] = await Promise.all([
      existingMatches(
        env.STRUCTURED_BUCKET,
        personalVolAmPmPanelObjectKey(panelDigest),
        panelDigest,
        PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES,
      ),
      existingMatches(
        env.STRUCTURED_BUCKET,
        personalVolAmPmStablePanelKey(period.period_id),
        panelDigest,
        PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES,
      ),
      existingMatches(
        env.STRUCTURED_BUCKET,
        personalVolAmPmPanelObjectKey(maskDigest),
        maskDigest,
        PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_MASK_BYTES,
      ),
    ]);
    if (!panelOk || !stableOk || !maskOk) return false;
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
      : kind === "object" && key.includes(digest)
        ? PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES
        : PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES;
  const length = contentLength(request, maximum);
  if (length === null || request.body === null) {
    return json({ error: "vol panel output length denied" }, 400);
  }
  const input = await readInput(env, expected);
  if (!input) return json({ error: "vol panel input manifest denied" }, 403);
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength !== length || `sha256:${await sha256Hex(bytes)}` !== digest) {
    return json({ error: "vol panel output bytes mismatch" }, 400);
  }
  if (kind === "object" && key !== personalVolAmPmPanelObjectKey(digest)) {
    return json({ error: "vol panel object key digest mismatch" }, 400);
  }
  if (kind === "manifest" || kind === "stable-panel" || kind === "object") {
    let parsed: unknown;
    try {
      parsed = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return json({ error: "vol panel output must be JSON" }, 400);
    }
    if (!isObject(parsed)) return json({ error: "vol panel output must be JSON" }, 400);
    if (kind === "manifest") {
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
    }
    if (kind === "stable-panel") {
      if (
        parsed.schema_version !== PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION ||
        typeof parsed.period_id !== "string"
      ) {
        return json({ error: "vol panel stable body denied" }, 400);
      }
      const expectedKey = personalVolAmPmStablePanelKey(
        parsed.period_id as PersonalVolAmPmEvaluationPeriodId,
      );
      if (expectedKey !== key) {
        return json({ error: "vol panel stable key mismatch" }, 400);
      }
    }
    if (kind === "object" && parsed.schema_version === PERSONAL_VOL_AM_PM_COMMON_VALID_SCHEMA) {
      if (bytes.byteLength > PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_MASK_BYTES) {
        return json({ error: "vol panel mask size denied" }, 400);
      }
    }
  }
  if (await existingMatches(env.STRUCTURED_BUCKET, key, digest, maximum)) {
    return json({ ok: true, created: false, key });
  }
  if (await env.STRUCTURED_BUCKET.head(key)) {
    return json({ error: "immutable vol panel output conflict" }, 409);
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
