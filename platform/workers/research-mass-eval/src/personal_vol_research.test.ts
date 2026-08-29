import { describe, expect, it } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  PERSONAL_VOL_COHORT_ID,
  PERSONAL_VOL_PANELS_PREFIX,
  PERSONAL_VOL_PERIODS,
  PERSONAL_VOL_STRATEGIES,
  evaluatePersonalVolWindow,
  parsePersonalVolResearchRequest,
  personalVolDailyPath,
  ratioSeriesForStrategy,
  runPersonalVolResearch,
} from "./personal_vol_research";
import type { Env, PeriodPanel } from "./types";

function datesFrom(start: string, count = 18): string[] {
  const startMs = Date.parse(`${start}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) =>
    new Date(startMs + index * 86_400_000).toISOString().slice(0, 10),
  );
}

function panel(periodId = "y2017_q4", start = "2017-09-01"): PeriodPanel {
  const dates = datesFrom(start);
  const short = Object.fromEntries(dates.map((date) => [date, 2]));
  const long = Object.fromEntries(dates.map((date) => [date, 1]));
  const absolute = Object.fromEntries(dates.map((date) => [date, 99]));
  const cmRatio = Object.fromEntries(dates.map((date) => [date, 0.2]));
  return {
    period_id: periodId,
    year: Number(start.slice(0, 4)),
    period_start: dates[0],
    period_end: dates.at(-1)!,
    status: "ok",
    source: "test-r2-panel",
    bars: {
      A: dates.map((date, index) => [date, 100 + index]),
      B: dates.map((date, index) => [date, 120 - index]),
    },
    opt225_regime: {
      basevol: {
        rv_abs_by_date: absolute,
        rv_short_by_date: short,
        rv_long_by_date: long,
      },
      atm_iv: {
        rv_abs_by_date: absolute,
        rv_short_by_date: short,
        rv_long_by_date: long,
      },
      skew: {
        rv_abs_by_date: absolute,
        rv_short_by_date: short,
        rv_long_by_date: long,
      },
      cm_term_ratio: { rv_abs_by_date: cmRatio },
    },
    base_vol_series: absolute,
    atm_iv_series: absolute,
    skew_series: absolute,
    cm_term_series: absolute,
    cm_term_ratio_series: cmRatio,
  };
}

describe("closed personal vol request", () => {
  it("accepts only job_id and the one fixed cohort", () => {
    expect(parsePersonalVolResearchRequest({ job_id: "vol-ratio-1" })).toEqual({
      ok: true,
      value: { job_id: "vol-ratio-1", cohort_id: PERSONAL_VOL_COHORT_ID },
    });
    expect(
      parsePersonalVolResearchRequest({
        job_id: "vol-ratio-1",
        cohort_id: "caller-selected",
      }),
    ).toMatchObject({ ok: false });
    expect(
      parsePersonalVolResearchRequest({
        job_id: "vol-ratio-1",
        threshold: 0,
      }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
    expect(parsePersonalVolResearchRequest({ job_id: "../escape" })).toEqual({
      ok: false,
      error: "job_id is invalid",
    });
  });

  it("freezes exactly four ratio strategies and six R2 periods", () => {
    expect(PERSONAL_VOL_STRATEGIES).toHaveLength(4);
    expect(new Set(PERSONAL_VOL_STRATEGIES.map((row) => row.strategy_id))).toEqual(
      new Set([
        "basevol_short_long_ratio",
        "atm_iv_short_long_ratio",
        "skew_short_long_ratio",
        "near_next_cm_atm_iv_ratio",
      ]),
    );
    expect(PERSONAL_VOL_STRATEGIES.every((row) => row.thesis && row.works_when)).toBe(
      true,
    );
    expect(PERSONAL_VOL_PERIODS).toHaveLength(6);
    expect(PERSONAL_VOL_PANELS_PREFIX).toContain("527c1065afe14601");
  });
});

describe("ratio-only series routing", () => {
  it("selects short/long rolling maps, not the absolute sidecar", () => {
    const selected = ratioSeriesForStrategy(
      "basevol_short_long_ratio",
      panel(),
    );

    expect(selected.kind).toBe("rolling_short_long");
    expect(selected.series?.rv_short_by_date?.["2017-09-01"]).toBe(2);
    expect(selected.series?.rv_long_by_date?.["2017-09-01"]).toBe(1);
    expect(selected.series?.rv_abs_by_date).toBeUndefined();
  });

  it("selects near/next ratio and never the near-minus-next level", () => {
    const selected = ratioSeriesForStrategy(
      "near_next_cm_atm_iv_ratio",
      panel(),
    );

    expect(selected.kind).toBe("near_next_zero_centered");
    expect(selected.series?.rv_abs_by_date?.["2017-09-01"]).toBe(0.2);
    expect(Object.values(selected.series?.rv_abs_by_date || {})).not.toContain(99);
  });

  it("fails the near/next candidate when only an absolute term sidecar exists", () => {
    const missingRatio = panel();
    missingRatio.cm_term_ratio_series = null;
    if (missingRatio.opt225_regime) {
      missingRatio.opt225_regime.cm_term_ratio = null;
    }
    const selected = ratioSeriesForStrategy(
      "near_next_cm_atm_iv_ratio",
      missingRatio,
    );
    const definition = PERSONAL_VOL_STRATEGIES.find(
      (row) => row.strategy_id === "near_next_cm_atm_iv_ratio",
    )!;
    const result = evaluatePersonalVolWindow(definition, missingRatio);

    expect(selected.series).toBeNull();
    expect(result).toMatchObject({
      status: "data_missing",
      reason: "required_ratio_series_missing",
      ratio_observations: 0,
    });
  });

  it("uses the separate bar-native DRAFT evaluator with fixed hold and cost", () => {
    const definition = PERSONAL_VOL_STRATEGIES[0];
    const result = evaluatePersonalVolWindow(definition, panel());

    expect(result.status).toBe("ok");
    expect(result.eval_path).toContain("personal_draft:nky_vol:nky_vol_term_ratio");
    expect(result.active_sessions).toBeGreaterThan(0);
    expect(Array.isArray(result.daily_path)).toBe(true);
    expect((result.metrics as { cagr: number | null }).cagr).not.toBeNull();
  });

  it("lags close-observed signals one session and excludes warm-up P&L", () => {
    const dates = datesFrom("2024-01-01", 5);
    const scoped = panel("lag-test", dates[0]);
    scoped.period_start = dates[2];
    scoped.period_end = dates[4];
    scoped.bars = {
      A: [
        [dates[0], 100],
        [dates[1], 100],
        [dates[2], 110],
        [dates[3], 99],
        [dates[4], 99],
      ],
    };
    const path = personalVolDailyPath(
      { A: { [dates[0]]: 1, [dates[1]]: -1 } },
      scoped,
    );

    expect(path.points.map((point) => point.date)).toEqual([
      dates[2],
      dates[3],
      dates[4],
    ]);
    expect(path.points[0].net_return).toBeCloseTo(0.1 - 0.0002);
    expect(path.points[1].net_return).toBeCloseTo(0.1 - 0.0002);
    expect(path.points[2].net_return).toBe(0);
    expect(path.active_sessions).toBe(2);
  });
});

const noopMass = async () => {
  throw new Error("mass evaluator must not run");
};

describe("POST /v1/personal-vol-research", () => {
  it("authenticates before dispatch", async () => {
    let calls = 0;
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-vol-research", {
        method: "POST",
        body: JSON.stringify({ job_id: "closed-vol" }),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
      } as Env,
      {
        runMassEval: noopMass,
        runDailyPath: noopMass,
        runPersonalVolResearch: async () => {
          calls += 1;
          return {};
        },
      },
    );

    expect(response.status).toBe(401);
    expect(calls).toBe(0);
  });

  it("runs independently of disabled Mass/READY capability variables", async () => {
    let received: unknown;
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-vol-research", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-mass-eval-token": "secret",
        },
        body: JSON.stringify({ job_id: "closed-vol" }),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
        MASS_RESEARCH: "NO-GO",
        PHASE7: "OFF",
        READY_DECLARED: "false",
        OPERATIONAL_GO: "false",
        CONTINUOUS_PAPER: "UNARMED",
      } as Env,
      {
        runMassEval: noopMass,
        runDailyPath: noopMass,
        runPersonalVolResearch: async (_env, request) => {
          received = request;
          return {
            research_mode: "personal_draft_screening",
            exact_four: true,
            go: false,
          };
        },
      },
    );

    expect(response.status).toBe(200);
    expect(received).toEqual({
      job_id: "closed-vol",
      cohort_id: PERSONAL_VOL_COHORT_ID,
    });
    expect(await response.json()).toMatchObject({
      ok: true,
      research_mode: "personal_draft_screening",
      go: false,
    });
  });
});

type Stored = { body: Uint8Array };

class MemR2 {
  readonly order: string[] = [];
  private readonly objects = new Map<string, Stored>();

  seed(key: string, data: unknown): void {
    this.objects.set(key, { body: new TextEncoder().encode(JSON.stringify(data)) });
  }

  async head(key: string) {
    const stored = this.objects.get(key);
    return stored ? { key, size: stored.body.byteLength, etag: `etag-${key}` } : null;
  }

  async get(key: string) {
    const stored = this.objects.get(key);
    if (!stored) return null;
    const text = async () => new TextDecoder().decode(stored.body);
    return {
      key,
      size: stored.body.byteLength,
      text,
      json: async () => JSON.parse(await text()),
      arrayBuffer: async () => stored.body.slice().buffer,
    };
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    if (options?.onlyIf && "etagDoesNotMatch" in options.onlyIf) {
      if (options.onlyIf.etagDoesNotMatch === "*" && this.objects.has(key)) return null;
    }
    const body =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : ArrayBuffer.isView(value)
          ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
          : new Uint8Array(value).slice();
    this.objects.set(key, { body });
    this.order.push(key);
    return { key, size: body.byteLength, etag: `etag-${key}` };
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

describe("personal vol immutable artifact", () => {
  it("writes report child before manifest and keeps the result DRAFT-only", async () => {
    const mem = new MemR2();
    for (const period of PERSONAL_VOL_PERIODS) {
      const start =
        Number(period.year) < 2016 ? "2015-09-01" : `${period.year}-09-01`;
      mem.seed(
        `${PERSONAL_VOL_PANELS_PREFIX}/${period.period_id}.json`,
        panel(period.period_id, start),
      );
    }
    const result = await runPersonalVolResearch(
      {
        STRUCTURED_BUCKET: mem.asBucket(),
        MASS_EVAL_VERSION: "research-mass-eval/test",
        MASS_RESEARCH: "NO-GO",
        READY_DECLARED: "false",
      } as Env,
      { job_id: "immutable-vol", cohort_id: PERSONAL_VOL_COHORT_ID },
    );
    const prefix = "research/personal/vol-ratio/job=immutable-vol";

    expect(result.go).toBe(false);
    expect(result.automatic_promotion).toBe(false);
    expect(result.live_orders).toBe(false);
    expect(result.result_authority).toMatchObject({
      screening_only: true,
      usable_as_pilot_readiness: false,
      usable_as_mass_readiness: false,
    });
    expect((result.strategies as unknown[])).toHaveLength(4);
    expect(result.execution_contract).toMatchObject({
      exact_four: true,
      exact_four_evaluation_complete: true,
    });
    expect(mem.order.indexOf(`${prefix}/report.json`)).toBeGreaterThanOrEqual(0);
    expect(mem.order.indexOf(`${prefix}/manifest.json`)).toBeGreaterThan(
      mem.order.indexOf(`${prefix}/report.json`),
    );
    expect(await mem.get(`${prefix}/report.json`)).not.toBeNull();
    expect(await mem.get(`${prefix}/manifest.json`)).not.toBeNull();
  });
});
