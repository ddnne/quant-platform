import { putJsonCreateOnly, serializedJsonBytes } from "./http";
import { personalJobContainerName } from "./personal_research_contract";
import {
  durablePersonalJobStatus,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_DECISION_CUTOFF,
  PERSONAL_SVI_2023_EARLIEST_DAY,
  PERSONAL_SVI_2023_EQUITY_UNIVERSE,
  PERSONAL_SVI_2023_LATEST_DAY,
  PERSONAL_SVI_2023_MAX_INPUT_BYTES,
  PERSONAL_SVI_2023_MAX_INPUT_MANIFEST_BYTES,
  PERSONAL_SVI_2023_MAX_OBJECT_BYTES,
  PERSONAL_SVI_2023_MAX_OBJECTS_PER_DAY,
  PERSONAL_SVI_2023_MAX_PANEL_BYTES,
  PERSONAL_SVI_2023_MAX_SESSIONS,
  PERSONAL_SVI_2023_PANEL_KEY,
  PERSONAL_SVI_2023_RUNNER_VERSION,
  PERSONAL_SVI_2023_STRATEGY_ID,
  PERSONAL_SVI_2023_WARMUP_SESSIONS,
  optionsDayFromKey,
  optionsDayPrefix,
  personalSviFeatureKey,
  personalSviInputManifestKey,
  personalSviJobRequestDigest,
  personalSviReportKey,
  personalSviTerminalManifestKey,
  type PersonalSvi2023Request,
  type PersonalSviInputDay,
  type PersonalSviInputManifest,
  type PersonalSviInputObject,
} from "./personal_svi_2023_contract";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

const MIN_PANEL_SESSIONS = PERSONAL_SVI_2023_WARMUP_SESSIONS + 20;
const SHA256_HEX_RE = /^[0-9a-f]{64}$/;

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function fail(code: string): never {
  throw Object.assign(new Error(code), { code });
}

function metadataObjectRef(object: R2Object): PersonalSviInputObject {
  const rawSha = object.customMetadata?.sha256 ?? "";
  if (!SHA256_HEX_RE.test(rawSha)) {
    fail("personal_svi_source_sha256_missing");
  }
  return {
    key: object.key,
    etag: object.etag,
    size: object.size,
    sha256: `sha256:${rawSha}`,
  };
}

function panelDates(raw: unknown): string[] {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return [];
  }
  const record = raw as Record<string, unknown>;
  const identity = record.index_proxy;
  if (
    typeof identity !== "object" ||
    identity === null ||
    Array.isArray(identity) ||
    (identity as Record<string, unknown>).dataset !==
      "indices_bars_daily_topix" ||
    (identity as Record<string, unknown>).label !== "TOPIX"
  ) {
    return [];
  }
  const bars = record.bars;
  if (typeof bars !== "object" || bars === null || Array.isArray(bars)) {
    return [];
  }
  const proxy = (bars as Record<string, unknown>).__NKY_PROXY__;
  if (!Array.isArray(proxy)) return [];
  const dates = new Set<string>();
  for (const pair of proxy) {
    if (
      !Array.isArray(pair) ||
      typeof pair[0] !== "string" ||
      typeof pair[1] !== "number" ||
      !Number.isFinite(pair[1]) ||
      pair[1] <= 0
    ) {
      continue;
    }
    const day = pair[0].slice(0, 10);
    if (
      /^2023-\d{2}-\d{2}$/.test(day) &&
      day >= PERSONAL_SVI_2023_EARLIEST_DAY &&
      day <= PERSONAL_SVI_2023_LATEST_DAY
    ) {
      dates.add(day);
    }
  }
  return [...dates].sort();
}

async function fixedPanel(
  bucket: R2Bucket,
): Promise<{ reference: PersonalSviInputObject; dates: string[] }> {
  const head = await bucket.head(PERSONAL_SVI_2023_PANEL_KEY);
  if (!head) fail("personal_svi_fixed_panel_missing");
  if (head.size < 1 || head.size > PERSONAL_SVI_2023_MAX_PANEL_BYTES) {
    fail("personal_svi_fixed_panel_size_denied");
  }
  const body = await bucket.get(PERSONAL_SVI_2023_PANEL_KEY);
  if (!body || body.etag !== head.etag || body.size !== head.size) {
    fail("personal_svi_fixed_panel_changed_during_admission");
  }
  let parsed: unknown;
  let bytes: Uint8Array;
  try {
    bytes = new Uint8Array(await body.arrayBuffer());
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    fail("personal_svi_fixed_panel_invalid_json");
  }
  const dates = panelDates(parsed);
  if (
    dates.length < MIN_PANEL_SESSIONS ||
    dates.length > PERSONAL_SVI_2023_MAX_SESSIONS
  ) {
    fail("personal_svi_fixed_panel_session_bound_failed");
  }
  return {
    reference: {
      key: head.key,
      etag: head.etag,
      size: head.size,
      sha256: `sha256:${await sha256Hex(bytes!)}`,
    },
    dates,
  };
}

async function listOneDay(
  bucket: R2Bucket,
  day: string,
): Promise<PersonalSviInputDay> {
  const prefix = optionsDayPrefix(day);
  const objects: R2Object[] = [];
  let cursor: string | undefined;
  do {
    const page = await bucket.list({
      prefix,
      limit: 1000,
      ...(cursor ? { cursor } : {}),
      include: ["customMetadata"],
    });
    objects.push(...page.objects);
    if (objects.length > PERSONAL_SVI_2023_MAX_OBJECTS_PER_DAY) {
      fail("personal_svi_daily_object_bound_exceeded");
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  if (objects.length === 0) fail("personal_svi_options_day_missing");
  const references = objects
    .map((object) => {
      if (
        optionsDayFromKey(object.key) !== day ||
        object.size < 1 ||
        object.size > PERSONAL_SVI_2023_MAX_OBJECT_BYTES
      ) {
        fail("personal_svi_options_object_denied");
      }
      return metadataObjectRef(object);
    })
    .sort((left, right) => left.key.localeCompare(right.key));
  return { date: day, objects: references };
}

export async function buildPersonalSviInputManifest(
  bucket: R2Bucket,
  request: PersonalSvi2023Request,
): Promise<PersonalSviInputManifest> {
  const panel = await fixedPanel(bucket);
  const days: PersonalSviInputDay[] = [];
  let objectCount = 0;
  let totalBytes = 0;
  // Intentionally sequential: every list request is for one fixed panel date,
  // so no unlisted year/month prefix is exposed and admission is bounded.
  for (const day of panel.dates) {
    const listed = await listOneDay(bucket, day);
    days.push(listed);
    objectCount += listed.objects.length;
    totalBytes += listed.objects.reduce((sum, object) => sum + object.size, 0);
    if (totalBytes > PERSONAL_SVI_2023_MAX_INPUT_BYTES) {
      fail("personal_svi_input_byte_bound_exceeded");
    }
  }
  const warmupDates = panel.dates.slice(0, PERSONAL_SVI_2023_WARMUP_SESSIONS);
  const evaluationDates = panel.dates.slice(PERSONAL_SVI_2023_WARMUP_SESSIONS);
  return {
    schema_version: "personal-svi-2023-input/v2",
    job_id: request.job_id,
    cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
    strategy: {
      strategy_id: PERSONAL_SVI_2023_STRATEGY_ID,
      feature: "svi_atm_short_over_next_minus_one",
      thesis:
        "Use the fitted front/next ATM-IV ratio, not an absolute IV level: maintain equity cross-sectional momentum in contango and reverse it when front SVI ATM IV exceeds the next maturity, where near-term stress is expected to disrupt leadership.",
      signal_lag_sessions: 1,
      hold_sessions: 10,
      one_way_cost: 0.001,
    },
    panel: panel.reference,
    equity_universe: PERSONAL_SVI_2023_EQUITY_UNIVERSE,
    options: {
      dataset: "derivatives_bars_daily_options_225",
      natural_key: ["Date", "Code"],
      days,
      object_count: objectCount,
      total_bytes: totalBytes,
    },
    sessions: {
      warmup_sessions: warmupDates.length,
      warmup_dates: warmupDates,
      evaluation_dates: evaluationDates,
    },
    temporal_contract: {
      source_decision_cutoff_jst: PERSONAL_SVI_2023_DECISION_CUTOFF,
      signal_lag_sessions: 1,
      fill_timing: "next_close",
      first_pnl_interval: "fill_close_to_following_close",
    },
    authority: {
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
    },
  };
}

type StoredTerminal = Record<string, unknown> & {
  input_manifest_digest?: unknown;
  job_id?: unknown;
  status?: unknown;
};

async function storedTerminal(
  env: Env,
  jobId: string,
): Promise<StoredTerminal | null> {
  const object = await env.STRUCTURED_BUCKET.get(
    personalSviTerminalManifestKey(jobId),
  );
  if (!object || object.size > 64 * 1024) return null;
  try {
    const parsed = await object.json<unknown>();
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as StoredTerminal)
      : null;
  } catch {
    return null;
  }
}

export async function submitPersonalSvi2023(
  env: Env,
  request: PersonalSvi2023Request,
): Promise<Response> {
  const terminalBeforeAdmission = await storedTerminal(env, request.job_id);
  if (terminalBeforeAdmission) {
    if (
      terminalBeforeAdmission.job_id !== request.job_id ||
      terminalBeforeAdmission.cohort_id !== request.cohort_id ||
      terminalBeforeAdmission.strategy_id !== PERSONAL_SVI_2023_STRATEGY_ID
    ) {
      return responseJson(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return responseJson({
      ok: terminalBeforeAdmission.status === "COMPLETED",
      idempotent: true,
      job: terminalBeforeAdmission,
      draft_only: true,
      screening_only: true,
      go: false,
    });
  }
  let input: PersonalSviInputManifest;
  try {
    input = await buildPersonalSviInputManifest(env.STRUCTURED_BUCKET, request);
  } catch (error) {
    const code = (error as { code?: string }).code ?? "personal_svi_admission_failed";
    return responseJson(
      { ok: false, error: code, job_id: request.job_id, go: false },
      409,
    );
  }
  if (
    serializedJsonBytes(input).byteLength >
    PERSONAL_SVI_2023_MAX_INPUT_MANIFEST_BYTES
  ) {
    return responseJson(
      {
        ok: false,
        error: "personal_svi_input_manifest_byte_bound_exceeded",
        job_id: request.job_id,
        go: false,
      },
      409,
    );
  }
  const inputKey = personalSviInputManifestKey(request.job_id);
  const inputPut = await putJsonCreateOnly(env.STRUCTURED_BUCKET, inputKey, input);
  if (inputPut.conflict) {
    return responseJson(
      { ok: false, error: "input_manifest_conflict", job_id: request.job_id, go: false },
      409,
    );
  }
  const existing = await storedTerminal(env, request.job_id);
  if (existing) {
    if (existing.input_manifest_digest !== inputPut.digest) {
      return responseJson(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return responseJson({
      ok: existing.status === "COMPLETED",
      idempotent: true,
      job: existing,
      draft_only: true,
      screening_only: true,
      go: false,
    });
  }
  const requestDigest = await personalSviJobRequestDigest(request, inputPut.digest);
  const conflict = await writeSubmittedState(
    env,
    submittedStateDocument({
      jobId: request.job_id,
      requestDigest,
      kind: "svi",
      deploymentId: env.CF_VERSION_METADATA?.id ?? "unknown",
      runnerVersion: PERSONAL_SVI_2023_RUNNER_VERSION,
    }),
  );
  if (conflict) return conflict;
  try {
    const target = await verifiedPersonalResearchContainer(
      env,
      await personalJobContainerName("svi", request.job_id),
    );
    return await target.fetch(
      new Request("http://container/v1/run-svi-2023", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          cohort_id: request.cohort_id,
          feature_key: personalSviFeatureKey(request.job_id),
          input_manifest_digest: inputPut.digest,
          input_manifest_key: inputKey,
          job_id: request.job_id,
          manifest_key: personalSviTerminalManifestKey(request.job_id),
          report_key: personalSviReportKey(request.job_id),
          request_digest: requestDigest,
          runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
          strategy_id: PERSONAL_SVI_2023_STRATEGY_ID,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      {
        ok: false,
        error: "personal_svi_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function personalSvi2023Status(
  env: Env,
  jobId: string,
): Promise<Response> {
  return durablePersonalJobStatus(env, "svi", jobId);
}
