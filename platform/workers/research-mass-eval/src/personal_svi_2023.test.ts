import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  buildPersonalSviInputManifest,
  submitPersonalSvi2023,
} from "./personal_svi_2023";
import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_MAX_INPUT_MANIFEST_BYTES,
  PERSONAL_SVI_2023_MAX_SESSIONS,
  PERSONAL_SVI_2023_OPTIONS_ROOT,
  PERSONAL_SVI_2023_PANEL_KEY,
  PERSONAL_SVI_2023_STRATEGY_ID,
  parsePersonalSvi2023Request,
  personalSviInputManifestKey,
  personalSviTerminalManifestKey,
} from "./personal_svi_2023_contract";
import { personalSviR2Outbound } from "./personal_svi_r2";
import type { Env } from "./types";

function days(count = 32): string[] {
  const out: string[] = [];
  let time = Date.parse("2023-01-04T00:00:00Z");
  while (out.length < count) {
    const date = new Date(time);
    if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) {
      out.push(date.toISOString().slice(0, 10));
    }
    time += 86_400_000;
  }
  return out;
}

function calendarDays(count: number): string[] {
  return Array.from({ length: count }, (_, offset) =>
    new Date(Date.parse("2023-01-04T00:00:00Z") + offset * 86_400_000)
      .toISOString()
      .slice(0, 10),
  );
}

function panel(
  dates: string[],
  equityMissingDay?: string,
): Record<string, unknown> {
  return {
    period_id: "y2023_full",
    year: 2023,
    period_start: "2023-01-04",
    period_end: "2023-10-13",
    index_proxy: {
      dataset: "indices_bars_daily_topix",
      label: "TOPIX",
    },
    bars: {
      ...Object.fromEntries(
        ["A", "B", "C", "D"].map((code, codeIndex) => [
          code,
          dates
            .filter((date) => date !== equityMissingDay)
            .map((date, index) => [date, 100 + codeIndex * 10 + index]),
        ]),
      ),
      __NKY_PROXY__: dates.map((date, index) => [date, 2_000 + index]),
    },
  };
}

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata?: Record<string, string>;
};

class AdmissionR2 {
  readonly listedPrefixes: string[] = [];
  readonly puts = new Map<string, Stored>();
  readonly dates: string[];
  readonly panelBytes: Uint8Array;
  readonly objectsPerDay: number;

  constructor(
    dates: string[],
    equityMissingDay?: string,
    objectsPerDay = 1,
  ) {
    this.dates = dates;
    this.objectsPerDay = objectsPerDay;
    this.panelBytes = new TextEncoder().encode(
      JSON.stringify(panel(dates, equityMissingDay)),
    );
  }

  async head(key: string) {
    if (key === PERSONAL_SVI_2023_PANEL_KEY) {
      return {
        key,
        size: this.panelBytes.byteLength,
        etag: "fixed-panel-etag",
        customMetadata: {},
      } as R2Object;
    }
    const stored = this.puts.get(key);
    return stored
      ? ({ key, size: stored.bytes.byteLength, etag: stored.etag } as R2Object)
      : null;
  }

  async get(key: string) {
    if (key === PERSONAL_SVI_2023_PANEL_KEY) {
      return {
        key,
        size: this.panelBytes.byteLength,
        etag: "fixed-panel-etag",
        arrayBuffer: async () => this.panelBytes.slice().buffer,
      } as R2ObjectBody;
    }
    const stored = this.puts.get(key);
    if (!stored) return null;
    return {
      key,
      size: stored.bytes.byteLength,
      etag: stored.etag,
      arrayBuffer: async () => stored.bytes.slice().buffer,
      json: async () => JSON.parse(new TextDecoder().decode(stored.bytes)),
    } as R2ObjectBody;
  }

  async list(options?: R2ListOptions): Promise<R2Objects> {
    const prefix = options?.prefix ?? "";
    this.listedPrefixes.push(prefix);
    const match = /\/dt=(2023-\d{2}-\d{2})\/$/.exec(prefix);
    const date = match?.[1] ?? "";
    if (!this.dates.includes(date)) return { objects: [], delimitedPrefixes: [], truncated: false };
    return {
      objects: Array.from({ length: this.objectsPerDay }, (_, index) =>
        ({
          key: `${PERSONAL_SVI_2023_OPTIONS_ROOT}/dt=${date}/run-${date}-${index}.jsonl`,
          size: 2048,
          etag: `etag-${date}-${index}`,
          customMetadata: { sha256: "a".repeat(64) },
        }) as R2Object,
      ),
      delimitedPrefixes: [],
      truncated: false,
    };
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    if (options?.onlyIf && "etagDoesNotMatch" in options.onlyIf) {
      if (options.onlyIf.etagDoesNotMatch === "*" && this.puts.has(key)) return null;
    }
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : ArrayBuffer.isView(value)
          ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
          : new Uint8Array(value).slice();
    const stored = { bytes, etag: `put-${key}`, customMetadata: options?.customMetadata };
    this.puts.set(key, stored);
    return { key, size: bytes.byteLength, etag: stored.etag } as R2Object;
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

describe("fixed personal SVI 2023 admission", () => {
  it("keeps the request closed to one DRAFT cohort", () => {
    expect(parsePersonalSvi2023Request({ job_id: "svi-2023-one" })).toEqual({
      ok: true,
      value: {
        job_id: "svi-2023-one",
        cohort_id: PERSONAL_SVI_2023_COHORT_ID,
      },
    });
    expect(
      parsePersonalSvi2023Request({ job_id: "svi-2023-one", threshold: 0 }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
    expect(
      parsePersonalSvi2023Request({
        job_id: "svi-2023-one",
        cohort_id: "mass-caller-selected",
      }),
    ).toMatchObject({ ok: false });
  });

  it("lists only exact fixed-panel dates and freezes exact object keys", async () => {
    const fixedDates = days();
    const mem = new AdmissionR2(fixedDates);
    const manifest = await buildPersonalSviInputManifest(mem.asBucket(), {
      job_id: "svi-list-bound",
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    });

    expect(mem.listedPrefixes).toEqual(
      fixedDates.map(
        (date) => `${PERSONAL_SVI_2023_OPTIONS_ROOT}/dt=${date}/`,
      ),
    );
    expect(manifest.options.days).toHaveLength(fixedDates.length);
    expect(manifest.options.object_count).toBe(fixedDates.length);
    expect(manifest.sessions.warmup_sessions).toBe(10);
    expect(manifest.sessions.evaluation_dates).toEqual(fixedDates.slice(10));
    expect(manifest.strategy).toMatchObject({
      feature: "svi_atm_short_over_next_minus_one",
      signal_lag_sessions: 1,
      hold_sessions: 10,
      one_way_cost: 0.001,
    });
    expect(manifest.equity_universe).toMatchObject({
      scope_id: "legacy-liq-large-adv100-2019-v1",
      daily_pit_reconstitution: false,
      comparable_to_personal_topix_factor_runs: false,
    });
    expect(manifest.temporal_contract).toMatchObject({
      source_decision_cutoff_jst: "15:00:00+09:00",
      signal_lag_sessions: 1,
      fill_timing: "next_close",
    });
    expect(manifest.authority).toEqual({
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
    });
  });

  it("uses the identified TOPIX proxy calendar when all equities miss a session", async () => {
    const fixedDates = days();
    const missingDay = fixedDates[15];
    const mem = new AdmissionR2(fixedDates, missingDay);

    const manifest = await buildPersonalSviInputManifest(mem.asBucket(), {
      job_id: "svi-proxy-calendar",
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    });

    expect(mem.listedPrefixes).toContain(
      `${PERSONAL_SVI_2023_OPTIONS_ROOT}/dt=${missingDay}/`,
    );
    expect([
      ...manifest.sessions.warmup_dates,
      ...manifest.sessions.evaluation_dates,
    ]).toEqual(fixedDates);
  });

  it("persists and serves the 193-session identity-bound TOPIX calendar", async () => {
    const fixedDates = days(193);
    const mem = new AdmissionR2(fixedDates);
    const containerFetch = vi.fn(
      async () => new Response('{"accepted":true}', { status: 202 }),
    );
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: {
        getByName: vi.fn(() => ({ fetch: containerFetch })),
      },
    } as unknown as Env;

    const response = await submitPersonalSvi2023(env, {
      job_id: "svi-full-proxy-calendar",
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    });

    expect(response.status).toBe(202);
    expect(PERSONAL_SVI_2023_MAX_SESSIONS).toBe(220);
    const inputKey = personalSviInputManifestKey("svi-full-proxy-calendar");
    const stored = mem.puts.get(inputKey);
    expect(stored).toBeDefined();
    expect(stored!.bytes.byteLength).toBeLessThanOrEqual(
      PERSONAL_SVI_2023_MAX_INPUT_MANIFEST_BYTES,
    );
    const forwarded = containerFetch.mock.calls[0]?.[0] as Request;
    const dispatched = (await forwarded.json()) as {
      input_manifest_digest: string;
    };
    const served = await personalSviR2Outbound(
      new Request(`http://research.r2/${inputKey}`, {
        headers: {
          "x-svi-job-id": "svi-full-proxy-calendar",
          "x-svi-input-manifest-key": inputKey,
          "x-svi-input-manifest-digest": dispatched.input_manifest_digest,
        },
      }),
      { STRUCTURED_BUCKET: mem.asBucket() },
      inputKey,
    );
    expect(served.status).toBe(200);
    const manifest = (await served.json()) as {
      options: { days: unknown[] };
      sessions: { warmup_dates: string[]; evaluation_dates: string[] };
    };
    expect(manifest.options.days).toHaveLength(193);
    expect([
      ...manifest.sessions.warmup_dates,
      ...manifest.sessions.evaluation_dates,
    ]).toEqual(fixedDates);
  });

  it("rejects an oversized serialized input manifest before write or dispatch", async () => {
    const mem = new AdmissionR2(calendarDays(220), undefined, 8);
    const containerFetch = vi.fn(
      async () => new Response('{"accepted":true}', { status: 202 }),
    );
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: {
        getByName: vi.fn(() => ({ fetch: containerFetch })),
      },
    } as unknown as Env;

    const response = await submitPersonalSvi2023(env, {
      job_id: "svi-oversized-manifest",
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    });

    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({
      error: "personal_svi_input_manifest_byte_bound_exceeded",
      go: false,
    });
    expect(
      mem.puts.has(personalSviInputManifestKey("svi-oversized-manifest")),
    ).toBe(false);
    expect(containerFetch).not.toHaveBeenCalled();
  });

  it("writes the create-only input manifest before dispatching the existing Container", async () => {
    const fixedDates = days();
    const mem = new AdmissionR2(fixedDates);
    const containerFetch = vi.fn(
      async () => new Response('{"accepted":true}', { status: 202 }),
    );
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: {
        getByName: vi.fn(() => ({ fetch: containerFetch })),
      },
    } as unknown as Env;
    const response = await submitPersonalSvi2023(env, {
      job_id: "svi-container-bound",
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    });

    expect(response.status).toBe(202);
    const inputKey =
      "research/personal/svi-2023/job=svi-container-bound/input-manifest.json";
    expect(mem.puts.has(inputKey)).toBe(true);
    const forwarded = containerFetch.mock.calls[0]?.[0] as Request;
    expect(await forwarded.json()).toMatchObject({
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
      input_manifest_key: inputKey,
      runner_version: "personal-svi-cloud-runner/v4",
      strategy_id: "svi-atm-term-ratio-momentum-switch",
    });
  });

  it("returns a durable terminal result before relisting 139 input days", async () => {
    const fixedDates = days();
    const mem = new AdmissionR2(fixedDates);
    const jobId = "svi-idempotent";
    await mem.put(
      personalSviTerminalManifestKey(jobId),
      JSON.stringify({
        status: "COMPLETED",
        job_id: jobId,
        cohort_id: PERSONAL_SVI_2023_COHORT_ID,
        strategy_id: PERSONAL_SVI_2023_STRATEGY_ID,
      }),
    );
    const response = await submitPersonalSvi2023(
      { STRUCTURED_BUCKET: mem.asBucket() } as Env,
      { job_id: jobId, cohort_id: PERSONAL_SVI_2023_COHORT_ID },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ ok: true, idempotent: true });
    expect(mem.listedPrefixes).toEqual([]);
  });
});

const noMass = async () => {
  throw new Error("mass path must not run");
};

describe("POST /v1/personal-svi-2023", () => {
  it("authenticates before parsing or dispatch", async () => {
    const submit = vi.fn();
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-svi-2023", {
        method: "POST",
        body: JSON.stringify({ job_id: "closed-svi" }),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
        PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"],
      } as Env,
      {
        runMassEval: noMass,
        runDailyPath: noMass,
        submitPersonalSvi2023: submit,
      },
    );

    expect(response.status).toBe(401);
    expect(submit).not.toHaveBeenCalled();
  });

  it("dispatches a fixed DRAFT request without Mass or READY capability gates", async () => {
    const submit = vi.fn(async () => new Response("accepted", { status: 202 }));
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-svi-2023", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-mass-eval-token": "secret",
        },
        body: JSON.stringify({ job_id: "closed-svi" }),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
        PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"],
        MASS_RESEARCH: "NO-GO",
        READY_DECLARED: "false",
      } as Env,
      {
        runMassEval: noMass,
        runDailyPath: noMass,
        submitPersonalSvi2023: submit,
      },
    );

    expect(response.status).toBe(202);
    expect(submit).toHaveBeenCalledWith(expect.anything(), {
      job_id: "closed-svi",
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    });
  });
});
