import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  personalJobContainerName,
} from "./personal_research_contract";
import { serializedJsonBytes } from "./http";
import {
  PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT,
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_DATASET,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_BYTES,
  PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_OBJECTS,
  PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_ROWS,
  PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_BYTES,
  PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_DATES,
  PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_OBJECTS,
  PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_ROWS,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_OBJECTS,
  PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_BYTES,
  PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_OBJECTS,
  PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_ROWS,
  PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA,
  addIsoDays,
  calendarRootPrefix,
  isoDaysInclusive,
  monthStartDay,
  parsePersonalOptionSidecarProduceRequest,
  personalOptionSidecarInputKey,
  personalOptionSidecarTerminalKey,
  samplePinnedDates,
  splitFrozenSessions,
  type StructuredObjectRef,
} from "./personal_option_sidecar_producer_contract";
import {
  buildPersonalOptionSidecarInputManifest,
  submitPersonalOptionSidecarProduce,
} from "./personal_option_sidecar_producer";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata: Record<string, string>;
};

class MemoryR2 {
  readonly values = new Map<string, Stored>();
  readonly writes: string[] = [];
  readonly listed: string[] = [];

  seed(
    key: string,
    value: unknown,
    etag = `etag-${key}`,
    customMetadata: Record<string, string> = {},
  ) {
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : value instanceof Uint8Array
          ? value
          : new TextEncoder().encode(JSON.stringify(value));
    this.values.set(key, { bytes, etag, customMetadata });
  }

  object(key: string, stored: Stored) {
    return {
      key,
      size: stored.bytes.byteLength,
      etag: stored.etag,
      customMetadata: stored.customMetadata,
      json: async () => JSON.parse(new TextDecoder().decode(stored.bytes)),
      arrayBuffer: async () => stored.bytes.slice().buffer,
    };
  }

  async get(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async head(key: string) {
    return this.get(key);
  }

  async list(options?: R2ListOptions): Promise<R2Objects> {
    const prefix = options?.prefix ?? "";
    this.listed.push(prefix);
    const objects = [...this.values.entries()]
      .filter(([key]) => key.startsWith(prefix))
      .map(([key, stored]) => this.object(key, stored) as unknown as R2Object);
    return { objects, delimitedPrefixes: [], truncated: false };
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      options.onlyIf.etagDoesNotMatch === "*" &&
      this.values.has(key)
    ) {
      return null;
    }
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : ArrayBuffer.isView(value)
          ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
          : new Uint8Array(value).slice();
    this.values.set(key, {
      bytes,
      etag: `put-${this.writes.length}`,
      customMetadata: options?.customMetadata ?? {},
    });
    this.writes.push(key);
    return this.object(key, this.values.get(key)!);
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

function runnerReadyResponse(): Response {
  const body = JSON.stringify({
    ok: true,
    service: PERSONAL_RESEARCH_RUNNER_VERSION,
  });
  return new Response(body, {
    status: 200,
    headers: {
      "content-length": String(new TextEncoder().encode(body).byteLength),
      "content-type": "application/json; charset=utf-8",
    },
  });
}

function admittedContainer() {
  const destroy = vi.fn(async () => undefined);
  const fetch = vi.fn(async (request: Request) =>
    new URL(request.url).pathname === "/ready"
      ? runnerReadyResponse()
      : new Response('{"accepted":true}', { status: 202 }),
  );
  return { destroy, fetch };
}

function structuredRecord(args: {
  dataset: string;
  date: string;
  payload: Record<string, unknown>;
  naturalKey: Record<string, string>;
  ingestedAt?: string;
}) {
  return {
    source: "jquants",
    dataset: args.dataset,
    natural_key: JSON.stringify(args.naturalKey),
    event_time: `${args.date}T00:00:00+09:00`,
    available_at: `${args.date}T00:00:00+09:00`,
    ingested_at: args.ingestedAt ?? `${args.date}T15:00:00+09:00`,
    payload: args.payload,
  };
}

async function jsonlObject(
  dataset: string,
  date: string,
  records: unknown[],
  runId = "run-1",
) {
  const bytes = new TextEncoder().encode(
    `${records.map((row) => JSON.stringify(row)).join("\n")}\n`,
  );
  return {
    bytes,
    meta: {
      sha256: await sha256Hex(bytes),
      count: String(records.length),
      bytes: String(bytes.byteLength),
      dataset,
      run_id: runId,
      date,
      schema: PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA,
    },
  };
}

async function seedPeriod(
  mem: MemoryR2,
  period: (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number],
  options?: { omitOptionsDay?: string; badShaDay?: string; extraOptionsDay?: string },
) {
  const warmup = samplePinnedDates(
    period.raw_start,
    addIsoDays(period.period_start, -1),
    period.warmup_sessions,
  );
  const evaluation = samplePinnedDates(
    period.period_start,
    period.period_end,
    period.evaluation_sessions,
  );
  const trading = new Set([...warmup, ...evaluation]);
  const split = splitFrozenSessions(period, [...trading]);
  expect(split.ok).toBe(true);
  const byMonth = new Map<string, string[]>();
  for (const day of isoDaysInclusive(period.raw_start, period.period_end)) {
    const month = monthStartDay(day);
    const rows = byMonth.get(month) ?? [];
    rows.push(day);
    byMonth.set(month, rows);
  }
  for (const [month, days] of byMonth) {
    const records = days.map((day) =>
      structuredRecord({
        dataset: "markets_calendar",
        date: day,
        naturalKey: { Date: day },
        payload: { Date: day, HolidayDivision: trading.has(day) ? "1" : "0" },
      }),
    );
    const calendar = await jsonlObject("markets_calendar", month, records, `cal-${month}`);
    mem.seed(
      `${PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT}/dt=${month}/${month}.jsonl`,
      calendar.bytes,
      `cal-${month}`,
      calendar.meta,
    );
  }
  for (const day of [...warmup, ...evaluation]) {
    if (day === options?.omitOptionsDay) continue;
    const record = structuredRecord({
      dataset: PERSONAL_OPTION_SIDECAR_DATASET,
      date: day,
      naturalKey: { Date: day, Code: "130060018" },
      payload: { Date: day, Code: "130060018" },
    });
    const option = await jsonlObject(PERSONAL_OPTION_SIDECAR_DATASET, day, [record]);
    const meta =
      day === options?.badShaDay
        ? { ...option.meta, sha256: "not-a-digest" }
        : option.meta;
    mem.seed(
      `${PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT}/dt=${day}/run.jsonl`,
      option.bytes,
      `opt-${day}`,
      meta,
    );
    if (day !== options?.extraOptionsDay) continue;
    const extraRecord = structuredRecord({
      dataset: PERSONAL_OPTION_SIDECAR_DATASET,
      date: day,
      naturalKey: { Date: day, Code: "130060019" },
      payload: { Date: day, Code: "130060019" },
      ingestedAt: `${day}T16:00:00+09:00`,
    });
    const extra = await jsonlObject(
      PERSONAL_OPTION_SIDECAR_DATASET,
      day,
      [extraRecord],
      "run-2",
    );
    mem.seed(
      `${PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT}/dt=${day}/run-2.jsonl`,
      extra.bytes,
      `opt-${day}-2`,
      extra.meta,
    );
  }
}

const REQUEST = { job_id: "sidecar-one" };

describe("frozen option sidecar calendar closure", () => {
  it("pins 61 predecessor sessions and the frozen evaluation counts", () => {
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      const warmup = samplePinnedDates(
        period.raw_start,
        addIsoDays(period.period_start, -1),
        period.warmup_sessions,
      );
      const evaluation = samplePinnedDates(
        period.period_start,
        period.period_end,
        period.evaluation_sessions,
      );
      const split = splitFrozenSessions(period, [...warmup, ...evaluation]);
      expect(split).toEqual({
        ok: true,
        warmup,
        evaluation,
      });
    }
  });
});

describe("closed option sidecar produce request", () => {
  it("accepts only job_id and rejects unknown fields", () => {
    expect(parsePersonalOptionSidecarProduceRequest(REQUEST)).toEqual({
      ok: true,
      value: REQUEST,
    });
    expect(
      parsePersonalOptionSidecarProduceRequest({
        job_id: "sidecar-one",
        period_id: "y2021_full",
      }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
    expect(
      parsePersonalOptionSidecarProduceRequest({
        job_id: "sidecar-one",
        sidecar_producer_terminal_digest: `sha256:${"a".repeat(64)}`,
      }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
  });
});

describe("option sidecar admission", () => {
  it("fails closed when a required options object is missing", async () => {
    const mem = new MemoryR2();
    const period = PERSONAL_OPTION_SIDECAR_PERIODS[0];
    const evaluation = samplePinnedDates(
      period.period_start,
      period.period_end,
      period.evaluation_sessions,
    );
    for (const row of PERSONAL_OPTION_SIDECAR_PERIODS) {
      await seedPeriod(
        mem,
        row,
        row.period_id === period.period_id ? { omitOptionsDay: evaluation[0] } : undefined,
      );
    }
    await expect(
      buildPersonalOptionSidecarInputManifest(mem.asBucket(), REQUEST),
    ).rejects.toMatchObject({ code: "option_sidecar_source_missing" });
  });

  it("fails closed when sha256 metadata is not a hex digest", async () => {
    const mem = new MemoryR2();
    const period = PERSONAL_OPTION_SIDECAR_PERIODS[0];
    const evaluation = samplePinnedDates(
      period.period_start,
      period.period_end,
      period.evaluation_sessions,
    );
    for (const row of PERSONAL_OPTION_SIDECAR_PERIODS) {
      await seedPeriod(
        mem,
        row,
        row.period_id === period.period_id ? { badShaDay: evaluation[0] } : undefined,
      );
    }
    await expect(
      buildPersonalOptionSidecarInputManifest(mem.asBucket(), REQUEST),
    ).rejects.toMatchObject({ code: "option_sidecar_source_sha256_missing" });
  });

  it("locks monthly calendar range objects covering 2+ days without day×calendar refs", async () => {
    const mem = new MemoryR2();
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      await seedPeriod(mem, period);
    }
    const input = await buildPersonalOptionSidecarInputManifest(mem.asBucket(), REQUEST);
    expect(mem.listed.some((prefix) => prefix === calendarRootPrefix())).toBe(true);
    expect(
      mem.listed.some((prefix) =>
        prefix.startsWith(`${PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT}/dt=`),
      ),
    ).toBe(false);
    const first = input.periods.y2021_full;
    expect(first.calendar.length).toBeGreaterThan(1);
    expect(first.calendar.every((object) => object.schema === PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA)).toBe(
      true,
    );
    const october = first.calendar.find((object) => object.date === "2020-10-01");
    expect(october?.count).toBeGreaterThan(1);
    expect(first.options.every((day) => Array.isArray(day.objects))).toBe(true);
    expect("date" in (first.calendar[0] as StructuredObjectRef)).toBe(true);
    expect(serializedJsonBytes(input).byteLength).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES,
    );
  });

  it("keeps 2 options objects on one day inside the 2MiB input bound", async () => {
    const mem = new MemoryR2();
    const doubled = PERSONAL_OPTION_SIDECAR_PERIODS[2]!.period_start;
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      await seedPeriod(
        mem,
        period,
        period.period_id === "y2025_q4" ? { extraOptionsDay: doubled } : undefined,
      );
    }
    const input = await buildPersonalOptionSidecarInputManifest(mem.asBucket(), REQUEST);
    const day = input.periods.y2025_q4.options.find((row) => row.date === doubled);
    expect(day?.objects).toHaveLength(2);
    expect(serializedJsonBytes(input).byteLength).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES,
    );
  });

  it("admits the live staging inventory under the total caps", () => {
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_BYTES).toBe(3_419_223_324);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_ROWS).toBe(3_031_214);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_OBJECTS).toBe(651);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_DATES).toBe(650);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_OBJECTS).toBe(33);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_ROWS).toBe(960);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_BYTES).toBe(318_720);
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_BYTES).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_BYTES,
    );
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_ROWS).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_ROWS,
    );
    expect(PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_OBJECTS).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_OBJECTS,
    );
    expect(PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_OBJECTS).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_OBJECTS,
    );
    expect(PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_BYTES).toBeLessThanOrEqual(
      PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_BYTES,
    );
    const canonical = PERSONAL_OPTION_SIDECAR_PERIODS.flatMap((period) =>
      isoDaysInclusive(period.raw_start, period.period_end),
    );
    expect(canonical).toHaveLength(PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_ROWS);
  });

  it("fits a live-shaped compact input fixture in 2MiB with two objects on one day", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    const optionRef = (date: string, run: string): StructuredObjectRef => ({
      key: `${PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT}/dt=${date}/${run}.jsonl`,
      etag: `etag-${date}-${run}`,
      size: 5_250_000,
      sha256: digest,
      dataset: PERSONAL_OPTION_SIDECAR_DATASET,
      run_id: run,
      date,
      schema: PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA,
      count: 4_656,
      bytes: 5_250_000,
    });
    const periods = Object.fromEntries(
      PERSONAL_OPTION_SIDECAR_PERIODS.map((period) => {
        const sessions = [
          ...samplePinnedDates(
            period.raw_start,
            addIsoDays(period.period_start, -1),
            period.warmup_sessions,
          ),
          ...samplePinnedDates(
            period.period_start,
            period.period_end,
            period.evaluation_sessions,
          ),
        ];
        return [
          period.period_id,
          {
            ...period,
            warmup_dates: sessions.slice(0, period.warmup_sessions),
            evaluation_dates: sessions.slice(period.warmup_sessions),
            calendar_digest: digest,
            raw_input_digest: digest,
            calendar: isoDaysInclusive(period.raw_start, period.period_end)
              .filter((day) => day.endsWith("-01"))
              .map((day) => ({
                key: `${PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT}/dt=${day}/${day}.jsonl`,
                etag: `cal-${day}`,
                size: 10_000,
                sha256: digest,
                dataset: "markets_calendar",
                run_id: "cal",
                date: day,
                schema: PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA,
                count: 31,
                bytes: 10_000,
              })),
            options: sessions.map((day, index) => ({
              date: day,
              objects:
                index === 0
                  ? [optionRef(day, "run-1"), optionRef(day, "run-2")]
                  : [optionRef(day, "run-1")],
            })),
          },
        ];
      }),
    );
    const bytes = serializedJsonBytes({
      schema_version: "personal-n225-option-sidecar-input/v1",
      producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
      job_id: "sidecar-live-shape",
      cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
      periods,
    });
    expect(bytes.byteLength).toBeLessThanOrEqual(PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES);
  });

  it("locks the three frozen periods and dispatches the existing v13 Container", async () => {
    const mem = new MemoryR2();
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      await seedPeriod(mem, period);
    }
    const container = admittedContainer();
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn(() => container) },
    } as unknown as Env;
    const response = await submitPersonalOptionSidecarProduce(env, REQUEST);
    expect(response.status).toBe(202);
    expect(env.PERSONAL_RESEARCH_CONTAINER.getByName).toHaveBeenCalledWith(
      await personalJobContainerName(PERSONAL_OPTION_SIDECAR_KIND, REQUEST.job_id),
    );
    expect(mem.values.has(personalOptionSidecarInputKey(REQUEST.job_id))).toBe(true);
    const forwarded = container.fetch.mock.calls[1]![0] as Request;
    expect(await forwarded.json()).toMatchObject({
      cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
      job_id: REQUEST.job_id,
      producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
      manifest_key: personalOptionSidecarTerminalKey(REQUEST.job_id),
    });
  });

  it("is idempotent for a matching terminal", async () => {
    const mem = new MemoryR2();
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      await seedPeriod(mem, period);
    }
    const input = await buildPersonalOptionSidecarInputManifest(
      mem.asBucket(),
      REQUEST,
    );
    const inputKey = personalOptionSidecarInputKey(REQUEST.job_id);
    mem.seed(inputKey, input);
    const inputDigest = `sha256:${await sha256Hex(mem.values.get(inputKey)!.bytes)}`;
    mem.seed(personalOptionSidecarTerminalKey(REQUEST.job_id), {
      status: "COMPLETED",
      job_id: REQUEST.job_id,
      producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
      cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
      input_manifest_digest: inputDigest,
    });
    const again = await submitPersonalOptionSidecarProduce(
      { STRUCTURED_BUCKET: mem.asBucket() } as Env,
      REQUEST,
    );
    expect(again.status).toBe(200);
    expect(await again.json()).toMatchObject({ ok: true, idempotent: true });
  });
});

describe("POST /v1/personal-option-sidecar-produce", () => {
  it("authenticates before parsing or dispatch", async () => {
    const submit = vi.fn();
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-option-sidecar-produce", {
        method: "POST",
        body: JSON.stringify(REQUEST),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
        PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"],
      } as Env,
      {
        runMassEval: async () => {
          throw new Error("mass path must not run");
        },
        runDailyPath: async () => {
          throw new Error("mass path must not run");
        },
        submitPersonalOptionSidecarProduce: submit,
      },
    );
    expect(response.status).toBe(401);
    expect(submit).not.toHaveBeenCalled();
  });
});
