import { putJsonCreateOnly, serializedJsonBytes } from "./http";
import { personalJobContainerName } from "./personal_research_contract";
import {
  PERSONAL_JOB_TTL_MS,
  durablePersonalJobStatus,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import {
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_DATASET,
  PERSONAL_OPTION_SIDECAR_DUPLICATE_RESOLUTION,
  PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_ROWS,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_OBJECT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_PERIOD_OBJECTS,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_OBJECTS,
  PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OBJECT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OBJECTS_PER_DAY,
  PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_OBJECTS,
  PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_ROWS,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  PERSONAL_OPTION_SIDECAR_SOURCE_VERSION,
  PERSONAL_OPTION_SIDECAR_TERMINAL_MAX_BYTES,
  PERSONAL_OPTION_SIDECAR_TIMEOUT_GRACE_MS,
  PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
  calendarDatesDigest,
  calendarDayFromKey,
  calendarRootPrefix,
  canonicalSha256,
  isoDaysInclusive,
  optionsDayFromKey,
  optionsDayPrefix,
  personalOptionSidecarInputKey,
  personalOptionSidecarRequestDigest,
  personalOptionSidecarTerminalKey,
  splitFrozenSessions,
  type OptionSidecarPeriodLock,
  type PersonalOptionSidecarInputManifest,
  type PersonalOptionSidecarPeriod,
  type PersonalOptionSidecarProduceRequest,
  type StructuredDayLock,
  type StructuredObjectRef,
} from "./personal_option_sidecar_producer_contract";
import {
  optionSidecarCompletedChildrenValid,
  optionSidecarTerminalIdentityMatches,
} from "./personal_option_sidecar_r2";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function metadataRef(
  object: R2Object,
  expected: { dataset: string; date: string; maximumBytes: number },
): StructuredObjectRef {
  const meta = object.customMetadata ?? {};
  const sha = meta.sha256 ?? "";
  const count = Number(meta.count);
  const bytes = Number(meta.bytes);
  if (!SHA256_HEX_RE.test(sha)) fail("option_sidecar_source_sha256_missing");
  if (
    object.size < 1 ||
    object.size > expected.maximumBytes ||
    meta.dataset !== expected.dataset ||
    meta.date !== expected.date ||
    !meta.run_id ||
    meta.schema !== PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA ||
    !Number.isInteger(count) ||
    count < 1 ||
    bytes !== object.size
  ) {
    fail("option_sidecar_source_metadata_invalid");
  }
  return {
    key: object.key,
    etag: object.etag,
    size: object.size,
    sha256: `sha256:${sha}`,
    dataset: expected.dataset,
    run_id: meta.run_id,
    date: expected.date,
    schema: PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA,
    count,
    bytes,
  };
}

function parseNaturalKey(value: unknown): Record<string, unknown> | null {
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  return isObject(value) ? value : null;
}

function isIsoDay(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isIsoInstant(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
      value,
    )
  ) {
    return false;
  }
  return Number.isFinite(Date.parse(value));
}

function lexicographicMax(
  left: readonly [string, string, number],
  right: readonly [string, string, number],
): boolean {
  if (left[0] !== right[0]) return left[0] > right[0];
  if (left[1] !== right[1]) return left[1] > right[1];
  return left[2] > right[2];
}

type CalendarWinner = {
  holiday: string;
  rank: readonly [string, string, number];
  objectKey: string;
};

type ScannedCalendar = {
  objects: StructuredObjectRef[];
  winnerByDate: Map<string, CalendarWinner>;
  datesByObject: Map<string, string[]>;
};

function parseCalendarRow(
  parsed: unknown,
  reference: StructuredObjectRef,
  lineIndex: number,
): { date: string; holiday: string; rank: readonly [string, string, number] } {
  if (!isObject(parsed)) fail("option_sidecar_calendar_row_invalid");
  if (parsed.dataset !== PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY.dataset) {
    fail("option_sidecar_calendar_row_invalid");
  }
  const naturalKey = parseNaturalKey(parsed.natural_key);
  const payload = parsed.payload;
  if (!naturalKey || !isObject(payload)) fail("option_sidecar_calendar_row_invalid");
  const keys = Object.keys(naturalKey).sort();
  const date = payload.Date;
  const holiday = payload.HolidayDivision;
  if (
    keys.length !== 1 ||
    keys[0] !== "Date" ||
    !isIsoDay(date) ||
    naturalKey.Date !== date ||
    typeof holiday !== "string" ||
    !/^[0-3]$/.test(holiday) ||
    !isIsoInstant(parsed.event_time) ||
    !isIsoInstant(parsed.available_at) ||
    !isIsoInstant(parsed.ingested_at) ||
    parsed.event_time.slice(0, 10) !== date
  ) {
    fail("option_sidecar_calendar_row_invalid");
  }
  return {
    date,
    holiday,
    rank: [parsed.ingested_at, reference.key, lineIndex],
  };
}

async function scanOfficialCalendar(bucket: R2Bucket): Promise<ScannedCalendar> {
  const listed: R2Object[] = [];
  let cursor: string | undefined;
  let scannedBytes = 0;
  do {
    const page = await bucket.list({
      prefix: calendarRootPrefix(),
      limit: 1000,
      ...(cursor ? { cursor } : {}),
      include: ["customMetadata"],
    });
    listed.push(...page.objects);
    scannedBytes += page.objects.reduce((sum, object) => sum + object.size, 0);
    if (
      listed.length > PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_OBJECTS ||
      scannedBytes > PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_BYTES
    ) {
      fail("option_sidecar_calendar_scan_bound_exceeded");
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  if (listed.length === 0) fail("option_sidecar_source_missing");
  const objects: StructuredObjectRef[] = [];
  const winnerByDate = new Map<string, CalendarWinner>();
  const datesByObject = new Map<string, string[]>();
  for (const object of listed) {
    const keyDate = calendarDayFromKey(object.key);
    if (!keyDate) fail("option_sidecar_source_key_denied");
    const reference = metadataRef(object, {
      dataset: PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY.dataset,
      date: keyDate,
      maximumBytes: PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_OBJECT_BYTES,
    });
    const body = await bucket.get(reference.key);
    if (!body || body.etag !== reference.etag || body.size !== reference.size) {
      fail("option_sidecar_source_changed_during_admission");
    }
    const bytes = new Uint8Array(await body.arrayBuffer());
    if (`sha256:${await sha256Hex(bytes)}` !== reference.sha256) {
      fail("option_sidecar_source_sha256_mismatch");
    }
    const text = new TextDecoder().decode(bytes);
    const lines = text.split("\n");
    let nonblank = 0;
    const covered: string[] = [];
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      const line = lines[lineIndex]!;
      if (!line.trim()) continue;
      nonblank += 1;
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        fail("option_sidecar_calendar_invalid_jsonl");
      }
      const row = parseCalendarRow(parsed, reference, lineIndex);
      covered.push(row.date);
      const current = winnerByDate.get(row.date);
      if (!current || lexicographicMax(row.rank, current.rank)) {
        winnerByDate.set(row.date, {
          holiday: row.holiday,
          rank: row.rank,
          objectKey: reference.key,
        });
      }
    }
    if (nonblank !== reference.count) fail("option_sidecar_calendar_count_mismatch");
    objects.push(reference);
    datesByObject.set(reference.key, covered);
  }
  objects.sort((left, right) => left.key.localeCompare(right.key));
  return { objects, winnerByDate, datesByObject };
}

async function listOptionsDay(
  bucket: R2Bucket,
  day: string,
): Promise<StructuredDayLock> {
  const objects: R2Object[] = [];
  let cursor: string | undefined;
  do {
    const page = await bucket.list({
      prefix: optionsDayPrefix(day),
      limit: 1000,
      ...(cursor ? { cursor } : {}),
      include: ["customMetadata"],
    });
    objects.push(...page.objects);
    if (objects.length > PERSONAL_OPTION_SIDECAR_MAX_OBJECTS_PER_DAY) {
      fail("option_sidecar_daily_object_bound_exceeded");
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  if (objects.length === 0) fail("option_sidecar_source_missing");
  const references = objects
    .map((object) => {
      if (optionsDayFromKey(object.key) !== day) fail("option_sidecar_source_key_denied");
      return metadataRef(object, {
        dataset: PERSONAL_OPTION_SIDECAR_DATASET,
        date: day,
        maximumBytes: PERSONAL_OPTION_SIDECAR_MAX_OBJECT_BYTES,
      });
    })
    .sort((left, right) => left.key.localeCompare(right.key));
  return { date: day, objects: references };
}

function periodCalendarRefs(
  scanned: ScannedCalendar,
  period: PersonalOptionSidecarPeriod,
): StructuredObjectRef[] {
  return scanned.objects.filter((object) => {
    const dates = scanned.datesByObject.get(object.key) ?? [];
    return dates.some((day) => day >= period.raw_start && day <= period.period_end);
  });
}

async function lockPeriod(
  bucket: R2Bucket,
  period: PersonalOptionSidecarPeriod,
  scanned: ScannedCalendar,
  totals: { objects: number; rows: number; bytes: number },
): Promise<OptionSidecarPeriodLock> {
  const requiredDays = isoDaysInclusive(period.raw_start, period.period_end);
  const trading: string[] = [];
  for (const day of requiredDays) {
    const winner = scanned.winnerByDate.get(day);
    if (!winner) fail("option_sidecar_calendar_day_missing");
    if (winner.holiday === "1") trading.push(day);
  }
  const split = splitFrozenSessions(period, trading);
  if (!split.ok) fail(split.error);
  const calendar = periodCalendarRefs(scanned, period);
  if (
    calendar.length < 1 ||
    calendar.length > PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_PERIOD_OBJECTS
  ) {
    fail("option_sidecar_calendar_object_bound_exceeded");
  }
  const options: StructuredDayLock[] = [];
  for (const day of [...split.warmup, ...split.evaluation]) {
    const locked = await listOptionsDay(bucket, day);
    totals.objects += locked.objects.length;
    for (const object of locked.objects) {
      totals.rows += object.count;
      totals.bytes += object.bytes;
    }
    if (
      totals.objects > PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_OBJECTS ||
      totals.rows > PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_ROWS ||
      totals.bytes > PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_BYTES
    ) {
      fail("option_sidecar_options_total_bound_exceeded");
    }
    options.push(locked);
  }
  const calendar_digest = await calendarDatesDigest([
    ...split.warmup,
    ...split.evaluation,
  ]);
  const raw_input_digest = await canonicalSha256({
    calendar: calendar.map((object) => ({
      etag: object.etag,
      key: object.key,
      sha256: object.sha256,
      size: object.size,
    })),
    calendar_digest,
    duplicate_resolution: PERSONAL_OPTION_SIDECAR_DUPLICATE_RESOLUTION,
    options: options.map((day) => ({
      date: day.date,
      objects: day.objects.map((object) => ({
        etag: object.etag,
        key: object.key,
        sha256: object.sha256,
        size: object.size,
      })),
    })),
    period_id: period.period_id,
  });
  return {
    period_id: period.period_id,
    year: period.year,
    raw_start: period.raw_start,
    period_start: period.period_start,
    period_end: period.period_end,
    warmup_sessions: split.warmup.length,
    evaluation_sessions: split.evaluation.length,
    warmup_dates: split.warmup,
    evaluation_dates: split.evaluation,
    calendar_digest,
    raw_input_digest,
    calendar,
    options,
  };
}

export async function buildPersonalOptionSidecarInputManifest(
  bucket: R2Bucket,
  request: PersonalOptionSidecarProduceRequest,
): Promise<PersonalOptionSidecarInputManifest> {
  const scanned = await scanOfficialCalendar(bucket);
  const requiredDays = PERSONAL_OPTION_SIDECAR_PERIODS.flatMap((period) =>
    isoDaysInclusive(period.raw_start, period.period_end),
  );
  if (requiredDays.length !== PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_ROWS) {
    fail("option_sidecar_calendar_canonical_window_mismatch");
  }
  for (const day of requiredDays) {
    if (!scanned.winnerByDate.has(day)) fail("option_sidecar_calendar_day_missing");
  }
  const periods = {} as PersonalOptionSidecarInputManifest["periods"];
  const totals = { objects: 0, rows: 0, bytes: 0 };
  for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
    periods[period.period_id] = await lockPeriod(bucket, period, scanned, totals);
  }
  return {
    schema_version: PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA,
    producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
    job_id: request.job_id,
    cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
    runner_version: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
    dataset: PERSONAL_OPTION_SIDECAR_DATASET,
    source_version: PERSONAL_OPTION_SIDECAR_SOURCE_VERSION,
    duplicate_resolution: PERSONAL_OPTION_SIDECAR_DUPLICATE_RESOLUTION,
    session_calendar: PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
    periods,
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
    personalOptionSidecarTerminalKey(jobId),
  );
  if (!object || object.size > PERSONAL_OPTION_SIDECAR_TERMINAL_MAX_BYTES) {
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

async function existingTerminalAcceptable(
  bucket: R2Bucket,
  terminal: StoredTerminal,
  request: PersonalOptionSidecarProduceRequest,
  locked: { manifest: PersonalOptionSidecarInputManifest; digest: string },
): Promise<boolean> {
  const requestDigest = await personalOptionSidecarRequestDigest(
    request,
    locked.digest,
  );
  if (
    !optionSidecarTerminalIdentityMatches(terminal, {
      jobId: request.job_id,
      inputKey: personalOptionSidecarInputKey(request.job_id),
      inputDigest: locked.digest,
      requestDigest,
    })
  ) {
    return false;
  }
  if (terminal.status !== "COMPLETED") return terminal.status === "FAILED";
  return optionSidecarCompletedChildrenValid(bucket, terminal, locked.manifest);
}

function inputMatchesRequest(
  parsed: unknown,
  request: PersonalOptionSidecarProduceRequest,
): parsed is PersonalOptionSidecarInputManifest {
  return (
    isObject(parsed) &&
    parsed.schema_version === PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA &&
    parsed.producer_id === PERSONAL_OPTION_SIDECAR_PRODUCER_ID &&
    parsed.job_id === request.job_id &&
    parsed.cohort_id === PERSONAL_OPTION_SIDECAR_COHORT_ID &&
    parsed.runner_version === PERSONAL_OPTION_SIDECAR_RUNNER_VERSION &&
    isObject(parsed.periods)
  );
}

async function loadLockedInput(
  bucket: R2Bucket,
  request: PersonalOptionSidecarProduceRequest,
): Promise<{ manifest: PersonalOptionSidecarInputManifest; digest: string } | null> {
  const object = await bucket.get(personalOptionSidecarInputKey(request.job_id));
  if (
    !object ||
    object.size < 1 ||
    object.size > PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES
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
  if (!inputMatchesRequest(parsed, request)) return null;
  return {
    manifest: parsed,
    digest: `sha256:${await sha256Hex(bytes)}`,
  };
}

async function dispatchContainer(
  env: Env,
  request: PersonalOptionSidecarProduceRequest,
  inputKey: string,
  inputDigest: string,
  requestDigest: string,
): Promise<Response> {
  try {
    const target = await verifiedPersonalResearchContainer(
      env,
      await personalJobContainerName(PERSONAL_OPTION_SIDECAR_KIND, request.job_id),
    );
    return await target.fetch(
      new Request("http://container/v1/produce-option-sidecar", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
          input_manifest_digest: inputDigest,
          input_manifest_key: inputKey,
          job_id: request.job_id,
          manifest_key: personalOptionSidecarTerminalKey(request.job_id),
          producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
          request_digest: requestDigest,
          runner_version: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      {
        ok: false,
        error: "personal_option_sidecar_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function submitPersonalOptionSidecarProduce(
  env: Env,
  request: PersonalOptionSidecarProduceRequest,
): Promise<Response> {
  const terminalBeforeAdmission = await storedTerminal(env, request.job_id);
  if (terminalBeforeAdmission) {
    const locked = await loadLockedInput(env.STRUCTURED_BUCKET, request);
    if (
      !locked ||
      !(await existingTerminalAcceptable(
        env.STRUCTURED_BUCKET,
        terminalBeforeAdmission,
        request,
        locked,
      ))
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
  const inputKey = personalOptionSidecarInputKey(request.job_id);
  let inputDigest: string;
  const existingInput = await loadLockedInput(env.STRUCTURED_BUCKET, request);
  if (existingInput) {
    inputDigest = existingInput.digest;
  } else {
    let input: PersonalOptionSidecarInputManifest;
    try {
      input = await buildPersonalOptionSidecarInputManifest(
        env.STRUCTURED_BUCKET,
        request,
      );
    } catch (error) {
      const code =
        (error as { code?: string }).code ?? "option_sidecar_admission_failed";
      return responseJson(
        { ok: false, error: code, job_id: request.job_id, go: false },
        409,
      );
    }
    if (serializedJsonBytes(input).byteLength > PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES) {
      return responseJson(
        {
          ok: false,
          error: "option_sidecar_input_manifest_byte_bound_exceeded",
          job_id: request.job_id,
          go: false,
        },
        409,
      );
    }
    const inputPut = await putJsonCreateOnly(env.STRUCTURED_BUCKET, inputKey, input);
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
    const lockedForExisting = await loadLockedInput(
      env.STRUCTURED_BUCKET,
      request,
    );
    if (
      !lockedForExisting ||
      lockedForExisting.digest !== inputDigest ||
      !(await existingTerminalAcceptable(
        env.STRUCTURED_BUCKET,
        existing,
        request,
        lockedForExisting,
      ))
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
  const requestDigest = await personalOptionSidecarRequestDigest(
    request,
    inputDigest,
  );
  const conflict = await writeSubmittedState(
    env,
    submittedStateDocument({
      jobId: request.job_id,
      requestDigest,
      kind: PERSONAL_OPTION_SIDECAR_KIND,
      deploymentId: env.CF_VERSION_METADATA?.id ?? "unknown",
      runnerVersion: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
      ttlMs: PERSONAL_JOB_TTL_MS + PERSONAL_OPTION_SIDECAR_TIMEOUT_GRACE_MS,
    }),
  );
  if (conflict) return conflict;
  return dispatchContainer(env, request, inputKey, inputDigest, requestDigest);
}

export async function personalOptionSidecarProduceStatus(
  env: Env,
  jobId: string,
): Promise<Response> {
  return durablePersonalJobStatus(env, PERSONAL_OPTION_SIDECAR_KIND, jobId);
}
