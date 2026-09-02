import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_DECISION_CUTOFF,
  PERSONAL_SVI_2023_EQUITY_UNIVERSE,
  PERSONAL_SVI_2023_MAX_INPUT_MANIFEST_BYTES,
  PERSONAL_SVI_2023_MAX_OBJECT_BYTES,
  PERSONAL_SVI_2023_MAX_PANEL_BYTES,
  PERSONAL_SVI_2023_PANEL_KEY,
  PERSONAL_SVI_2023_RUNNER_VERSION,
  isPersonalSviDigest,
  isPersonalSviJobId,
  optionsDayFromKey,
  personalSviJobRequestDigest,
  personalSviFeatureKey,
  personalSviInputManifestKey,
  personalSviReportKey,
  personalSviTerminalManifestKey,
  type PersonalSviInputManifest,
  type PersonalSviInputObject,
} from "./personal_svi_2023_contract";
import { sha256Hex } from "./sha256";

const FEATURE_MAX_BYTES = 8 * 1024 * 1024;
const REPORT_MAX_BYTES = 2 * 1024 * 1024;
const TERMINAL_MAX_BYTES = 64 * 1024;

type R2Env = { STRUCTURED_BUCKET: R2Bucket };

type SviIdentity = {
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

function identity(request: Request): SviIdentity | null {
  const jobId = request.headers.get("x-svi-job-id") ?? "";
  const inputKey = request.headers.get("x-svi-input-manifest-key") ?? "";
  const inputDigest = request.headers.get("x-svi-input-manifest-digest") ?? "";
  if (
    !isPersonalSviJobId(jobId) ||
    inputKey !== personalSviInputManifestKey(jobId) ||
    !isPersonalSviDigest(inputDigest)
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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function inputObjectShape(
  value: unknown,
  expectedDay?: string,
  maximumBytes = PERSONAL_SVI_2023_MAX_OBJECT_BYTES,
): boolean {
  if (!isObject(value)) return false;
  const key = typeof value.key === "string" ? value.key : "";
  return (
    typeof value.etag === "string" &&
    value.etag.length > 0 &&
    typeof value.size === "number" &&
    Number.isInteger(value.size) &&
    value.size > 0 &&
    value.size <= maximumBytes &&
    typeof value.sha256 === "string" &&
    isPersonalSviDigest(value.sha256) &&
    (expectedDay === undefined
      ? key === PERSONAL_SVI_2023_PANEL_KEY
      : optionsDayFromKey(key) === expectedDay)
  );
}

function inputDayShape(value: unknown): boolean {
  if (!isObject(value) || typeof value.date !== "string") return false;
  const day = value.date;
  return (
    Array.isArray(value.objects) &&
    value.objects.length > 0 &&
    value.objects.every((object) => inputObjectShape(object, day))
  );
}

function inputShape(
  parsed: unknown,
  expected: SviIdentity,
): parsed is PersonalSviInputManifest {
  if (!isObject(parsed)) return false;
  const authority = parsed.authority;
  const options = parsed.options;
  const panel = parsed.panel;
  const sessions = parsed.sessions;
  const strategy = parsed.strategy;
  const days = isObject(options) ? options.days : null;
  const equityUniverse = parsed.equity_universe;
  const temporal = parsed.temporal_contract;
  return (
    parsed.schema_version === "personal-svi-2023-input/v2" &&
    parsed.job_id === expected.jobId &&
    parsed.cohort_id === PERSONAL_SVI_2023_COHORT_ID &&
    parsed.runner_version === PERSONAL_SVI_2023_RUNNER_VERSION &&
    isObject(authority) &&
    authority.draft_only === true &&
    authority.screening_only === true &&
    authority.ready === false &&
    authority.mass === false &&
    authority.promotion === false &&
    authority.live_orders === false &&
    authority.go === false &&
    inputObjectShape(panel, undefined, PERSONAL_SVI_2023_MAX_PANEL_BYTES) &&
    isObject(equityUniverse) &&
    equityUniverse.scope_id === PERSONAL_SVI_2023_EQUITY_UNIVERSE.scope_id &&
    equityUniverse.selection_rule ===
      PERSONAL_SVI_2023_EQUITY_UNIVERSE.selection_rule &&
    equityUniverse.selection_reference_start ===
      PERSONAL_SVI_2023_EQUITY_UNIVERSE.selection_reference_start &&
    equityUniverse.selection_reference_end ===
      PERSONAL_SVI_2023_EQUITY_UNIVERSE.selection_reference_end &&
    equityUniverse.maximum_codes ===
      PERSONAL_SVI_2023_EQUITY_UNIVERSE.maximum_codes &&
    equityUniverse.membership ===
      PERSONAL_SVI_2023_EQUITY_UNIVERSE.membership &&
    equityUniverse.daily_pit_reconstitution === false &&
    equityUniverse.topix_scale_bound === false &&
    equityUniverse.comparable_to_personal_topix_factor_runs === false &&
    isObject(options) &&
    options.dataset === "derivatives_bars_daily_options_225" &&
    Array.isArray(days) &&
    days.length > 0 &&
    days.every(inputDayShape) &&
    isObject(sessions) &&
    typeof sessions.warmup_sessions === "number" &&
    Number.isInteger(sessions.warmup_sessions) &&
    sessions.warmup_sessions >= 0 &&
    sessions.warmup_sessions <= 60 &&
    Array.isArray(sessions.warmup_dates) &&
    Array.isArray(sessions.evaluation_dates) &&
    isObject(temporal) &&
    temporal.source_decision_cutoff_jst ===
      PERSONAL_SVI_2023_DECISION_CUTOFF &&
    temporal.signal_lag_sessions === 1 &&
    temporal.fill_timing === "next_close" &&
    temporal.first_pnl_interval === "fill_close_to_following_close" &&
    isObject(strategy) &&
    strategy.strategy_id === "svi-atm-term-ratio-momentum-switch" &&
    strategy.feature === "svi_atm_short_over_next_minus_one" &&
    strategy.signal_lag_sessions === 1 &&
    strategy.hold_sessions === 10 &&
    strategy.one_way_cost === 0.001
  );
}

async function readInputManifest(
  env: R2Env,
  expected: SviIdentity,
): Promise<{ manifest: PersonalSviInputManifest; bytes: Uint8Array } | null> {
  const object = await env.STRUCTURED_BUCKET.get(expected.inputKey);
  if (
    !object ||
    object.size < 1 ||
    object.size > PERSONAL_SVI_2023_MAX_INPUT_MANIFEST_BYTES
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

function allowedReference(
  manifest: PersonalSviInputManifest,
  key: string,
): PersonalSviInputObject | null {
  if (key === PERSONAL_SVI_2023_PANEL_KEY) return manifest.panel;
  const day = optionsDayFromKey(key);
  if (!day) return null;
  const entry = manifest.options.days.find((candidate) => candidate.date === day);
  return entry?.objects.find((object) => object.key === key) ?? null;
}

async function getInput(
  request: Request,
  env: R2Env,
  key: string,
  expected: SviIdentity,
): Promise<Response> {
  const loaded = await readInputManifest(env, expected);
  if (!loaded) return json({ error: "SVI input manifest denied" }, 403);
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
  const reference = allowedReference(loaded.manifest, key);
  if (!reference) return json({ error: "SVI input key not listed" }, 403);
  if (request.method === "HEAD") {
    const object = await env.STRUCTURED_BUCKET.head(key);
    if (!object) return json({ error: "SVI input missing" }, 404);
    if (object.etag !== reference.etag || object.size !== reference.size) {
      return json({ error: "SVI input changed after admission" }, 409);
    }
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        etag: object.httpEtag,
      },
    });
  }
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object) return json({ error: "SVI input missing" }, 404);
  if (object.etag !== reference.etag || object.size !== reference.size) {
    return json({ error: "SVI input changed after admission" }, 409);
  }
  const headers = new Headers({
    "content-length": String(object.size),
    etag: object.httpEtag,
    "x-listed-sha256": reference.sha256 ?? "",
  });
  object.writeHttpMetadata(headers);
  return new Response(object.body, { status: 200, headers });
}

function outputLimit(key: string, jobId: string): number | null {
  if (key === personalSviFeatureKey(jobId)) return FEATURE_MAX_BYTES;
  if (key === personalSviReportKey(jobId)) return REPORT_MAX_BYTES;
  if (key === personalSviTerminalManifestKey(jobId)) return TERMINAL_MAX_BYTES;
  return null;
}

function expectedOutputKind(key: string, jobId: string): string | null {
  if (key === personalSviFeatureKey(jobId)) return "features";
  if (key === personalSviReportKey(jobId)) return "report";
  if (key === personalSviTerminalManifestKey(jobId)) return "manifest";
  return null;
}

async function existingMatches(
  bucket: R2Bucket,
  key: string,
  digest: string,
  identityValue: SviIdentity,
): Promise<boolean> {
  const object = await bucket.get(key);
  if (!object || object.size > FEATURE_MAX_BYTES) return false;
  if (
    object.customMetadata?.input_manifest_digest !== identityValue.inputDigest ||
    object.customMetadata?.sha256 !== digest
  ) {
    return false;
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  return `sha256:${await sha256Hex(bytes)}` === digest;
}

async function completedChildrenMatch(
  env: R2Env,
  parsed: Record<string, unknown>,
  identityValue: SviIdentity,
): Promise<boolean> {
  const featureDigest = parsed.feature_sha256;
  const reportDigest = parsed.report_sha256;
  if (
    parsed.feature_key !== personalSviFeatureKey(identityValue.jobId) ||
    parsed.report_key !== personalSviReportKey(identityValue.jobId) ||
    typeof featureDigest !== "string" ||
    typeof reportDigest !== "string" ||
    !isPersonalSviDigest(featureDigest) ||
    !isPersonalSviDigest(reportDigest)
  ) {
    return false;
  }
  const [featureMatches, reportMatches] = await Promise.all([
    existingMatches(
      env.STRUCTURED_BUCKET,
      personalSviFeatureKey(identityValue.jobId),
      featureDigest,
      identityValue,
    ),
    existingMatches(
      env.STRUCTURED_BUCKET,
      personalSviReportKey(identityValue.jobId),
      reportDigest,
      identityValue,
    ),
  ]);
  return featureMatches && reportMatches;
}

async function exactTerminalExists(
  env: R2Env,
  identityValue: SviIdentity,
): Promise<boolean> {
  const object = await env.STRUCTURED_BUCKET.get(
    personalSviTerminalManifestKey(identityValue.jobId),
  );
  if (!object || object.size < 1 || object.size > TERMINAL_MAX_BYTES) return false;
  try {
    const parsed: unknown = await object.json();
    const requestDigest = await personalSviJobRequestDigest(
      { job_id: identityValue.jobId, cohort_id: PERSONAL_SVI_2023_COHORT_ID },
      identityValue.inputDigest,
    );
    return (
      isObject(parsed) &&
      parsed.job_id === identityValue.jobId &&
      parsed.cohort_id === PERSONAL_SVI_2023_COHORT_ID &&
      parsed.runner_version === PERSONAL_SVI_2023_RUNNER_VERSION &&
      parsed.input_manifest_digest === identityValue.inputDigest &&
      parsed.request_digest === requestDigest &&
      (parsed.status === "COMPLETED" || parsed.status === "FAILED")
    );
  } catch {
    return false;
  }
}

async function putOutput(
  request: Request,
  env: R2Env,
  key: string,
  identityValue: SviIdentity,
): Promise<Response> {
  const limit = outputLimit(key, identityValue.jobId);
  const kind = expectedOutputKind(key, identityValue.jobId);
  const declaredDigest = request.headers.get("x-content-sha256") ?? "";
  if (limit === null || kind === null || !isPersonalSviDigest(declaredDigest)) {
    return json({ error: "SVI output identity denied" }, 403);
  }
  const length = contentLength(request, limit);
  if (length === null || request.body === null) {
    return json({ error: "SVI output length denied" }, 400);
  }
  const input = await readInputManifest(env, identityValue);
  if (!input) return json({ error: "SVI input manifest denied" }, 403);
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength !== length) {
    return json({ error: "SVI output length mismatch" }, 400);
  }
  const actualDigest = `sha256:${await sha256Hex(bytes)}`;
  if (actualDigest !== declaredDigest) {
    return json({ error: "SVI output digest mismatch" }, 400);
  }
  if (kind === "report" || kind === "manifest") {
    let parsed: unknown;
    try {
      parsed = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return json({ error: `SVI ${kind} must be JSON` }, 400);
    }
    if (
      !isObject(parsed) ||
      parsed.job_id !== identityValue.jobId ||
      parsed.input_manifest_digest !== identityValue.inputDigest ||
      parsed.go !== false ||
      parsed.draft_only !== true ||
      parsed.screening_only !== true ||
      parsed.ready !== false ||
      parsed.mass !== false ||
      parsed.promotion !== false ||
      parsed.live_orders !== false ||
      parsed.not_a_pass !== true
    ) {
      return json({ error: `SVI ${kind} authority mismatch` }, 400);
    }
    if (
      kind === "manifest" &&
      parsed.status !== "COMPLETED" &&
      parsed.status !== "FAILED"
    ) {
      return json({ error: "SVI manifest status denied" }, 400);
    }
    if (
      kind === "manifest" &&
      parsed.status === "COMPLETED" &&
      !(await completedChildrenMatch(env, parsed, identityValue))
    ) {
      return json({ error: "SVI manifest children mismatch" }, 409);
    }
  }
  if (
    await existingMatches(
      env.STRUCTURED_BUCKET,
      key,
      declaredDigest,
      identityValue,
    )
  ) {
    return json({ ok: true, created: false, key });
  }
  if (await env.STRUCTURED_BUCKET.head(key)) {
    return json({ error: "immutable SVI output conflict" }, 409);
  }
  if (await exactTerminalExists(env, identityValue)) {
    return json({ error: "SVI terminal already exists" }, 409);
  }
  const put = await env.STRUCTURED_BUCKET.put(key, bytes, {
    httpMetadata: {
      contentType:
        kind === "features"
          ? "application/x-ndjson; charset=utf-8"
          : "application/json; charset=utf-8",
    },
    customMetadata: {
      plane: "personal_svi_2023",
      kind,
      job_id: identityValue.jobId,
      input_manifest_digest: identityValue.inputDigest,
      sha256: declaredDigest,
      immutable: "true",
    },
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (put !== null) return json({ ok: true, created: true, key }, 201);
  return (await existingMatches(
    env.STRUCTURED_BUCKET,
    key,
    declaredDigest,
    identityValue,
  ))
    ? json({ ok: true, created: false, key })
    : json({ error: "immutable SVI output conflict" }, 409);
}

export function isPersonalSviOutboundRequest(request: Request, key: string): boolean {
  return key.startsWith("research/personal/svi-2023/") ||
    request.headers.has("x-svi-job-id");
}

/** Manifest-constrained capability used only by the existing private Container. */
export async function personalSviR2Outbound(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const expected = identity(request);
  if (!expected) return json({ error: "SVI R2 identity denied" }, 403);
  if (request.method === "GET" || request.method === "HEAD") {
    return getInput(request, env, key, expected);
  }
  if (request.method === "PUT") {
    return putOutput(request, env, key, expected);
  }
  return json({ error: "SVI R2 method denied" }, 403);
}
