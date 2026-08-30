import { putJsonCreateOnly, serializedJsonBytes } from "./http";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  personalJobContainerName,
} from "./personal_research_contract";
import {
  PERSONAL_JOB_TTL_MS,
  durablePersonalJobStatus,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import { personalSnapshotManifestKey } from "./personal_snapshot_contract";
import {
  PERSONAL_VOL_AM_PM_EVALUATION_PERIODS,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_SNAPSHOT_MANIFEST_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_TERMINAL_MAX_BYTES,
  PERSONAL_VOL_AM_PM_PANEL_TIMEOUT_GRACE_MS,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
  PERSONAL_VOL_AM_PM_REQUIRED_LOOKBACK_SESSIONS,
  PERSONAL_VOL_AM_PM_SELECTION_PERIOD,
  inputManifestMatchesRequest,
  personalVolAmPmLegacyOptionPanelKey,
  personalVolAmPmPanelBuildInputKey,
  personalVolAmPmPanelBuildRequestDigest,
  personalVolAmPmPanelBuildTerminalKey,
  type ImmutableObjectRef,
  type OptionSidecarLock,
  type PersonalVolAmPmEvaluationPeriodId,
  type PersonalVolAmPmPanelBuildRequest,
  type PersonalVolAmPmPanelWriterInputManifest,
  type SnapshotInputLock,
} from "./personal_vol_am_pm_panel_writer_contract";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const SNAPSHOT_KEY_RE =
  /^research\/personal\/snapshots\/sha256=([0-9a-f]{64})\.sqlite\.gz$/;

type JsonObject = Record<string, unknown>;

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fail(code: string): never {
  throw Object.assign(new Error(code), { code });
}

function isDigest(value: unknown): value is `sha256:${string}` {
  return typeof value === "string" && DIGEST_RE.test(value);
}

function hexSha256(bytes: ArrayBuffer): `sha256:${string}` {
  return `sha256:${[...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("")}`;
}

function headDigest(object: R2Object): string | null {
  if (isDigest(object.customMetadata?.sha256)) return object.customMetadata.sha256;
  const checksum = object.checksums?.sha256;
  return checksum ? hexSha256(checksum) : null;
}

async function boundedManifest(
  bucket: R2Bucket,
  key: string,
  maximumBytes: number,
): Promise<{ object: R2ObjectBody; bytes: Uint8Array; digest: string }> {
  const head = await bucket.head(key);
  if (!head) fail("vol_am_pm_panel_source_missing");
  if (head.size < 1 || head.size > maximumBytes) {
    fail("vol_am_pm_panel_source_size_denied");
  }
  const body = await bucket.get(key);
  if (!body || body.etag !== head.etag || body.size !== head.size) {
    fail("vol_am_pm_panel_source_changed_during_admission");
  }
  const bytes = new Uint8Array(await body.arrayBuffer());
  if (bytes.byteLength !== head.size) fail("vol_am_pm_panel_source_length_mismatch");
  return {
    object: body,
    bytes,
    digest: `sha256:${await sha256Hex(bytes)}`,
  };
}

function snapshotObjectRef(
  object: R2Object,
  expectedKey: string,
  rawSha256: string,
  gzipSha256: string,
): SnapshotInputLock["snapshot"] {
  if (
    object.key !== expectedKey ||
    object.size < 1 ||
    !isDigest(rawSha256) ||
    !isDigest(gzipSha256) ||
    object.customMetadata?.format !== "personal-draft-history/v4" ||
    object.customMetadata?.raw_sha256 !== rawSha256 ||
    object.customMetadata?.sha256 !== gzipSha256
  ) {
    fail("vol_am_pm_panel_snapshot_reference_invalid");
  }
  const match = SNAPSHOT_KEY_RE.exec(expectedKey);
  if (!match || `sha256:${match[1]}` !== rawSha256) {
    fail("vol_am_pm_panel_snapshot_key_digest_mismatch");
  }
  return {
    key: expectedKey,
    etag: object.etag,
    size: object.size,
    sha256: gzipSha256,
    raw_sha256: rawSha256,
    gzip_sha256: gzipSha256,
  };
}

async function lockSnapshot(
  bucket: R2Bucket,
  jobId: string,
  role: SnapshotInputLock["role"],
  expected: {
    period_id: string;
    period_start: string;
    period_end: string;
    minimum_lookback: number;
  },
): Promise<SnapshotInputLock> {
  const manifestKey = personalSnapshotManifestKey(jobId);
  const loaded = await boundedManifest(
    bucket,
    manifestKey,
    PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_SNAPSHOT_MANIFEST_BYTES,
  );
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(loaded.bytes));
  } catch {
    fail("vol_am_pm_panel_snapshot_manifest_invalid_json");
  }
  if (!isObject(parsed)) fail("vol_am_pm_panel_snapshot_manifest_invalid");
  const lookback = parsed.lookback_sessions;
  if (
    parsed.status !== "COMPLETED" ||
    parsed.job_id !== jobId ||
    parsed.format !== "personal-draft-history/v4" ||
    parsed.runner_version !== PERSONAL_RESEARCH_RUNNER_VERSION ||
    parsed.period_start !== expected.period_start ||
    parsed.period_end !== expected.period_end ||
    typeof lookback !== "number" ||
    !Number.isInteger(lookback) ||
    lookback < expected.minimum_lookback ||
    !isDigest(parsed.raw_sha256) ||
    !isDigest(parsed.gzip_sha256) ||
    typeof parsed.snapshot_key !== "string"
  ) {
    fail("vol_am_pm_panel_snapshot_identity_mismatch");
  }
  const snapshotHead = await bucket.head(parsed.snapshot_key);
  if (!snapshotHead) fail("vol_am_pm_panel_snapshot_object_missing");
  const snapshot = snapshotObjectRef(
    snapshotHead,
    parsed.snapshot_key,
    parsed.raw_sha256,
    parsed.gzip_sha256,
  );
  const manifest: ImmutableObjectRef = {
    key: manifestKey,
    etag: loaded.object.etag,
    size: loaded.object.size,
    sha256: loaded.digest,
  };
  return {
    job_id: jobId,
    role,
    period_id: expected.period_id,
    period_start: expected.period_start,
    period_end: expected.period_end,
    lookback_sessions: lookback,
    format: "personal-draft-history/v4",
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    manifest,
    snapshot,
  };
}

async function lockOptionSidecar(
  bucket: R2Bucket,
  periodId: PersonalVolAmPmEvaluationPeriodId,
): Promise<OptionSidecarLock> {
  const key = personalVolAmPmLegacyOptionPanelKey(periodId);
  const head = await bucket.head(key);
  if (!head) fail("vol_am_pm_panel_source_missing");
  if (
    head.size < 1 ||
    head.size > PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES
  ) {
    fail("vol_am_pm_panel_source_size_denied");
  }
  const digest = headDigest(head);
  if (!digest) fail("vol_am_pm_panel_option_sidecar_checksum_missing");
  return {
    period_id: periodId,
    source_key: key,
    etag: head.etag,
    size: head.size,
    sha256: digest,
  };
}

export async function buildPersonalVolAmPmPanelInputManifest(
  bucket: R2Bucket,
  request: PersonalVolAmPmPanelBuildRequest,
): Promise<PersonalVolAmPmPanelWriterInputManifest> {
  const selection = await lockSnapshot(
    bucket,
    request.selection_snapshot_job_id,
    "selection_2019",
    {
      period_id: PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_id,
      period_start: PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_start,
      period_end: PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_end,
      minimum_lookback: 0,
    },
  );
  const periods = {} as PersonalVolAmPmPanelWriterInputManifest["periods"];
  const option_sidecars =
    {} as PersonalVolAmPmPanelWriterInputManifest["option_sidecars"];
  for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
    const start = period.period_start || "";
    const end = period.period_end || "";
    if (!start || !end) fail("vol_am_pm_panel_frozen_period_missing");
    periods[period.period_id] = await lockSnapshot(
      bucket,
      request.period_snapshot_job_ids[period.period_id],
      "evaluation_period",
      {
        period_id: period.period_id,
        period_start: start,
        period_end: end,
        minimum_lookback: PERSONAL_VOL_AM_PM_REQUIRED_LOOKBACK_SESSIONS,
      },
    );
    option_sidecars[period.period_id] = await lockOptionSidecar(
      bucket,
      period.period_id,
    );
  }
  return {
    schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA,
    producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
    job_id: request.job_id,
    cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
    runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
    panel_schema: "personal-vol-ratio-am-pm-panel/v1",
    required_lookback_sessions: PERSONAL_VOL_AM_PM_REQUIRED_LOOKBACK_SESSIONS,
    selection,
    periods,
    option_sidecars,
  };
}

type StoredTerminal = Record<string, unknown> & {
  input_manifest_digest?: unknown;
  job_id?: unknown;
  producer_id?: unknown;
  status?: unknown;
};

async function storedTerminal(
  env: Env,
  jobId: string,
): Promise<StoredTerminal | null> {
  const object = await env.STRUCTURED_BUCKET.get(
    personalVolAmPmPanelBuildTerminalKey(jobId),
  );
  if (!object || object.size > PERSONAL_VOL_AM_PM_PANEL_BUILD_TERMINAL_MAX_BYTES) {
    return null;
  }
  try {
    const parsed = await object.json<unknown>();
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as StoredTerminal)
      : null;
  } catch {
    return null;
  }
}

function sameClosedIdentity(
  terminal: StoredTerminal,
  request: PersonalVolAmPmPanelBuildRequest,
): boolean {
  return (
    terminal.job_id === request.job_id &&
    terminal.producer_id === PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID &&
    terminal.cohort_id === PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID
  );
}

async function loadLockedInput(
  bucket: R2Bucket,
  request: PersonalVolAmPmPanelBuildRequest,
): Promise<{ manifest: PersonalVolAmPmPanelWriterInputManifest; digest: string } | null> {
  const object = await bucket.get(personalVolAmPmPanelBuildInputKey(request.job_id));
  if (
    !object ||
    object.size < 1 ||
    object.size > PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES
  ) {
    return null;
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
  if (!inputManifestMatchesRequest(parsed, request)) return null;
  return {
    manifest: parsed,
    digest: `sha256:${await sha256Hex(bytes)}`,
  };
}

async function dispatchContainer(
  env: Env,
  request: PersonalVolAmPmPanelBuildRequest,
  inputKey: string,
  inputDigest: string,
  requestDigest: string,
): Promise<Response> {
  try {
    const target = await verifiedPersonalResearchContainer(
      env,
      await personalJobContainerName(
        PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
        request.job_id,
      ),
    );
    return await target.fetch(
      new Request("http://container/v1/build-personal-vol-am-pm-panel", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
          input_manifest_digest: inputDigest,
          input_manifest_key: inputKey,
          job_id: request.job_id,
          manifest_key: personalVolAmPmPanelBuildTerminalKey(request.job_id),
          producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
          request_digest: requestDigest,
          runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      {
        ok: false,
        error: "personal_vol_am_pm_panel_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function submitPersonalVolAmPmPanelBuild(
  env: Env,
  request: PersonalVolAmPmPanelBuildRequest,
): Promise<Response> {
  const terminalBeforeAdmission = await storedTerminal(env, request.job_id);
  if (terminalBeforeAdmission) {
    if (
      !sameClosedIdentity(terminalBeforeAdmission, request) ||
      !(await loadLockedInput(env.STRUCTURED_BUCKET, request))
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
  const inputKey = personalVolAmPmPanelBuildInputKey(request.job_id);
  let inputDigest: string;
  const existingInput = await loadLockedInput(env.STRUCTURED_BUCKET, request);
  if (existingInput) {
    inputDigest = existingInput.digest;
  } else {
    let input: PersonalVolAmPmPanelWriterInputManifest;
    try {
      input = await buildPersonalVolAmPmPanelInputManifest(
        env.STRUCTURED_BUCKET,
        request,
      );
    } catch (error) {
      const code =
        (error as { code?: string }).code ?? "vol_am_pm_panel_admission_failed";
      return responseJson(
        { ok: false, error: code, job_id: request.job_id, go: false },
        409,
      );
    }
    if (
      serializedJsonBytes(input).byteLength >
      PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES
    ) {
      return responseJson(
        {
          ok: false,
          error: "vol_am_pm_panel_input_manifest_byte_bound_exceeded",
          job_id: request.job_id,
          go: false,
        },
        409,
      );
    }
    const inputPut = await putJsonCreateOnly(
      env.STRUCTURED_BUCKET,
      inputKey,
      input,
    );
    if (inputPut.conflict) {
      const raced = await loadLockedInput(env.STRUCTURED_BUCKET, request);
      if (!raced) {
        return responseJson(
          {
            ok: false,
            error: "input_manifest_conflict",
            job_id: request.job_id,
            go: false,
          },
          409,
        );
      }
      inputDigest = raced.digest;
    } else {
      inputDigest = inputPut.digest;
    }
  }
  const existing = await storedTerminal(env, request.job_id);
  if (existing) {
    if (
      !sameClosedIdentity(existing, request) ||
      existing.input_manifest_digest !== inputDigest
    ) {
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
  const requestDigest = await personalVolAmPmPanelBuildRequestDigest(
    request,
    inputDigest,
  );
  const conflict = await writeSubmittedState(
    env,
    submittedStateDocument({
      jobId: request.job_id,
      requestDigest,
      kind: PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
      deploymentId: env.CF_VERSION_METADATA?.id ?? "unknown",
      runnerVersion: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
      ttlMs: PERSONAL_JOB_TTL_MS + PERSONAL_VOL_AM_PM_PANEL_TIMEOUT_GRACE_MS,
    }),
  );
  if (conflict) return conflict;
  return dispatchContainer(env, request, inputKey, inputDigest, requestDigest);
}

export async function personalVolAmPmPanelBuildStatus(
  env: Env,
  jobId: string,
): Promise<Response> {
  return durablePersonalJobStatus(env, PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND, jobId);
}
