import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  personalJobContainerName,
} from "./personal_research_contract";
import {
  PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT,
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_DATASET,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  addIsoDays,
  parsePersonalOptionSidecarProduceRequest,
  personalOptionSidecarInputKey,
  personalOptionSidecarTerminalKey,
  samplePinnedDates,
  splitFrozenSessions,
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

async function structuredObject(
  dataset: string,
  date: string,
  payload: unknown,
  runId = "run-1",
) {
  const bytes = new TextEncoder().encode(`${JSON.stringify(payload)}\n`);
  return {
    bytes,
    meta: {
      sha256: await sha256Hex(bytes),
      count: "1",
      bytes: String(bytes.byteLength),
      dataset,
      run_id: runId,
      date,
      schema: "jquants-structured-jsonl/v1",
    },
  };
}

async function seedPeriod(
  mem: MemoryR2,
  period: (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number],
  options?: { omitOptionsDay?: string; badShaDay?: string },
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
  for (const day of isoWindow(period.raw_start, period.period_end)) {
    const calendar = await structuredObject("markets_calendar", day, {
      Date: day,
      HolidayDivision: trading.has(day) ? "1" : "0",
    });
    mem.seed(
      `${PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT}/dt=${day}/${day}.jsonl`,
      calendar.bytes,
      `cal-${day}`,
      calendar.meta,
    );
    if (!trading.has(day) || day === options?.omitOptionsDay) continue;
    const option = await structuredObject(PERSONAL_OPTION_SIDECAR_DATASET, day, {
      Date: day,
      Code: "130060018",
    });
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
  }
}

function isoWindow(start: string, end: string): string[] {
  const out: string[] = [];
  for (let day = start; day <= end; day = addIsoDays(day, 1)) out.push(day);
  return out;
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
  it("accepts only job_id", () => {
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
    await seedPeriod(mem, period, { omitOptionsDay: evaluation[0] });
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
    await seedPeriod(mem, period, { badShaDay: evaluation[0] });
    await expect(
      buildPersonalOptionSidecarInputManifest(mem.asBucket(), REQUEST),
    ).rejects.toMatchObject({ code: "option_sidecar_source_sha256_missing" });
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
