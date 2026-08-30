import { describe, expect, it } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  PERSONAL_VOL_AM_PM_ARTIFACT_PLANE,
  PERSONAL_VOL_AM_PM_COHORT_ID,
  PERSONAL_VOL_AM_PM_CONTRACT,
  PERSONAL_VOL_AM_PM_CONTROL,
  PERSONAL_VOL_AM_PM_JOB_ROOT,
  PERSONAL_VOL_AM_PM_MANIFEST_SCHEMA,
  PERSONAL_VOL_AM_PM_REPORT_SCHEMA,
  evaluatePersonalVolAmPmWindow,
  loadPersonalVolAmPmPanelsFromBuildJob,
  parsePersonalVolAmPmResearchRequest,
  personalVolAmPmCommonValidMask,
  personalVolAmPmCommonValidity,
  personalVolAmPmContractDigest,
  personalVolAmPmDailyPath,
  personalVolAmPmEntrySigns,
  personalVolAmPmHeldBook,
  personalVolAmPmRebalanceDates,
  runPersonalVolAmPmResearch,
} from "./personal_vol_am_pm";
import {
  PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
  PERSONAL_VOL_AM_PM_PANELS_PREFIX,
  PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY,
  PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
  PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT,
  equityCodes,
  isLegacyPersonalVolPanel,
  loadPersonalVolAmPmPanels,
  parsePersonalVolAmPmPanel,
  personalVolAmPmSessionDatesDigest,
  type PersonalVolAmPmPanel,
} from "./personal_vol_am_pm_panel";
import {
  PERSONAL_VOL_COHORT_ID,
  PERSONAL_VOL_HOLD_SESSIONS,
  PERSONAL_VOL_ONE_WAY_COST,
  PERSONAL_VOL_PANELS_PREFIX,
  PERSONAL_VOL_PERIODS,
  PERSONAL_VOL_SOURCE_IDENTITY,
  PERSONAL_VOL_STRATEGIES,
  parsePersonalVolResearchRequest,
  runPersonalVolResearch,
} from "./personal_vol_research";
import {
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
  personalVolAmPmCommonValidDigest,
  personalVolAmPmMembershipDigest,
  personalVolAmPmPanelBuildTerminalKey,
  personalVolAmPmPanelObjectKey,
} from "./personal_vol_am_pm_panel_writer_contract";
import { sha256Hex } from "./sha256";
import type { Env, PeriodPanel } from "./types";

const PANEL_BUILD_JOB_ID = "panel-build-1";

function datesFrom(start: string, count = 18): string[] {
  const startMs = Date.parse(`${start}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) =>
    new Date(startMs + index * 86_400_000).toISOString().slice(0, 10),
  );
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

async function amPmPanel(
  periodId = "y2023_full",
  start = "2023-09-01",
): Promise<PersonalVolAmPmPanel> {
  const dates = datesFrom(start);
  const short = Object.fromEntries(dates.map((date) => [date, 2]));
  const long = Object.fromEntries(dates.map((date) => [date, 1]));
  const absolute = Object.fromEntries(dates.map((date) => [date, 99]));
  const cmRatio = Object.fromEntries(dates.map((date) => [date, 0.2]));
  return {
    schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
    period_id: periodId,
    year: Number(start.slice(0, 4)),
    period_start: dates[0],
    period_end: dates.at(-1)!,
    status: "ok",
    source: "test-am-pm-panel",
    temporal_contract: PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT,
    session_calendar: {
      ...PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
      dates,
      dates_digest: await personalVolAmPmSessionDatesDigest(dates),
    },
    codes: ["A", "B"],
    bars: {
      A: dates.map((date, index) => ({
        date,
        MAdjC: 100 + index,
        AAdjC: 200 + index,
      })),
      B: dates.map((date, index) => ({
        date,
        MAdjC: 120 - index,
        AAdjC: 220 - index,
      })),
    },
    opt225_regime: {
      source: PERSONAL_VOL_SOURCE_IDENTITY,
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
    tradable_hedge: null,
  };
}

function legacyClosePanel(start = "2023-09-01"): PeriodPanel {
  const dates = datesFrom(start);
  return {
    period_id: "y2023_full",
    year: 2023,
    period_start: dates[0],
    period_end: dates.at(-1)!,
    status: "ok",
    source: "test-r2-panel",
    bars: {
      A: dates.map((date, index) => [date, 100 + index]),
      B: dates.map((date, index) => [date, 120 - index]),
      __NKY_PROXY__: dates.map((date, index) => [date, 1_900 + index]),
    },
  };
}

async function panelForPeriod(
  period: (typeof PERSONAL_VOL_PERIODS)[number],
): Promise<PersonalVolAmPmPanel> {
  const periodStart = period.period_start!;
  const lookback = new Date(Date.parse(`${periodStart}T00:00:00Z`) - 86_400_000)
    .toISOString()
    .slice(0, 10);
  const staged = await amPmPanel(period.period_id, lookback);
  staged.year = period.year!;
  staged.period_start = periodStart;
  staged.period_end = period.period_end!;
  return staged;
}

class MemR2 {
  readonly order: string[] = [];
  private readonly objects = new Map<string, { body: Uint8Array }>();

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

async function seedPanelBuild(
  mem: MemR2,
  jobId: string,
  panels: PersonalVolAmPmPanel[],
  mutateTerminal?: (terminal: Record<string, unknown>) => void,
  membership = ["A", "B"],
): Promise<void> {
  const periods: Record<string, unknown> = {};
  for (const panel of panels) {
    const bytes = new TextEncoder().encode(JSON.stringify(panel));
    const digest = `sha256:${await sha256Hex(bytes)}`;
    const key = personalVolAmPmPanelObjectKey(digest);
    mem.seed(key, panel);
    const maskDigest = await personalVolAmPmCommonValidDigest(
      personalVolAmPmCommonValidMask(panel),
    );
    periods[panel.period_id] = {
      panel_key: key,
      panel_sha256: digest,
      panel_size: bytes.byteLength,
      common_valid_sha256: maskDigest,
    };
  }
  const terminal: Record<string, unknown> = {
    schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
    status: "COMPLETED",
    producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
    job_id: jobId,
    cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
    membership: {
      codes: membership,
      digest: await personalVolAmPmMembershipDigest(membership),
      count: membership.length,
    },
    periods,
  };
  mutateTerminal?.(terminal);
  mem.seed(personalVolAmPmPanelBuildTerminalKey(jobId), terminal);
}

describe("AM/PM request identity", () => {
  it("accepts only job_id, the AM/PM cohort, and panel_build_job_id", () => {
    expect(parsePersonalVolAmPmResearchRequest({ job_id: "am-pm-1" })).toMatchObject({
      ok: false,
      error: "panel_build_job_id is invalid",
    });
    expect(
      parsePersonalVolAmPmResearchRequest({
        job_id: "am-pm-1",
        panel_build_job_id: PANEL_BUILD_JOB_ID,
      }),
    ).toEqual({
      ok: true,
      value: {
        job_id: "am-pm-1",
        cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
        panel_build_job_id: PANEL_BUILD_JOB_ID,
      },
    });
    expect(
      parsePersonalVolAmPmResearchRequest({
        job_id: "am-pm-1",
        panel_build_job_id: PANEL_BUILD_JOB_ID,
        cohort_id: PERSONAL_VOL_COHORT_ID,
      }),
    ).toMatchObject({ ok: false });
    expect(
      parsePersonalVolAmPmResearchRequest({
        job_id: "am-pm-1",
        panel_build_job_id: PANEL_BUILD_JOB_ID,
        threshold: 0,
      }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
  });

  it("keeps the v2 request parser from admitting the AM/PM cohort", () => {
    expect(
      parsePersonalVolResearchRequest({
        job_id: "am-pm-1",
        cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
      }),
    ).toMatchObject({ ok: false, error: `cohort_id must be ${PERSONAL_VOL_COHORT_ID}` });
  });

  it("binds a distinct content digest, schema, and prefix", async () => {
    const digest = await personalVolAmPmContractDigest();
    expect(PERSONAL_VOL_AM_PM_COHORT_ID).toBe("personal-vol-ratio-am-pm-v1");
    expect(PERSONAL_VOL_AM_PM_REPORT_SCHEMA).toBe("personal-vol-ratio-am-pm-report/v1");
    expect(PERSONAL_VOL_AM_PM_MANIFEST_SCHEMA).toBe(
      "personal-vol-ratio-am-pm-manifest/v1",
    );
    expect(PERSONAL_VOL_AM_PM_PANELS_PREFIX).not.toBe(PERSONAL_VOL_PANELS_PREFIX);
    expect(PERSONAL_VOL_AM_PM_ARTIFACT_PLANE).toContain("vol-ratio-am-pm-v1");
    expect(digest.startsWith("sha256:")).toBe(true);
    expect(digest).toContain(await personalVolAmPmContractDigest());
    expect(PERSONAL_VOL_AM_PM_CONTRACT.no_adjc_fallback).toBe(true);
    expect(PERSONAL_VOL_AM_PM_CONTRACT.cash_index_executable_fill).toBe(false);
    expect(PERSONAL_VOL_AM_PM_CONTRACT.session_calendar).toEqual(
      PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
    );
    expect(PERSONAL_VOL_AM_PM_CONTRACT.morning_signal_ignores_AAdjC).toBe(true);
    expect(PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY.producer_id).toBe(
      "personal-vol-ratio-am-pm-panel-writer/v1",
    );
    expect(PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY.required_session_calendar).toEqual(
      PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
    );
  });
});

describe("AM/PM panel schema", () => {
  it("rejects a legacy PeriodPanel even when dates match", async () => {
    const legacy = legacyClosePanel();
    const am = await amPmPanel();
    expect(legacy.period_start).toBe(am.period_start);
    expect(legacy.period_end).toBe(am.period_end);
    expect(isLegacyPersonalVolPanel(legacy)).toBe(true);
    expect(parsePersonalVolAmPmPanel(legacy)).toMatchObject({
      ok: false,
      error: "legacy_period_panel_rejected",
      legacy: true,
    });
  });

  it("does not treat AdjC or close tuples as M/A", async () => {
    const withAdjC = {
      ...(await amPmPanel()),
      bars: {
        A: [{ date: "2023-09-01", AdjC: 100, close: 100 }],
      },
    };
    const parsed = parsePersonalVolAmPmPanel(withAdjC);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.bars.A).toEqual([]);
    expect(parsed.value.codes).toContain("A");
  });

  it("preserves a finite MAdjC when AAdjC is missing", async () => {
    const parsed = parsePersonalVolAmPmPanel({
      ...(await amPmPanel()),
      bars: {
        A: [{ date: "2023-09-01", MAdjC: 101, AAdjC: null }],
      },
    });
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.bars.A).toEqual([
      { date: "2023-09-01", MAdjC: 101, AAdjC: null },
    ]);
  });

  it("rejects a cash-index executable fill claim", async () => {
    const fixture = await amPmPanel();
    const claimed = {
      ...fixture,
      tradable_hedge: {
        etf_code: "TOPIX",
        dataset: "indices_bars_daily_topix",
        bars: fixture.bars.A,
      },
    };
    expect(parsePersonalVolAmPmPanel(claimed)).toMatchObject({
      ok: false,
      error: "cash_index_executable_fill_rejected",
    });
  });

  it("loads only the AM/PM prefix and never the legacy close panel", async () => {
    const mem = new MemR2();
    const period = PERSONAL_VOL_PERIODS[1];
    mem.seed(`${PERSONAL_VOL_PANELS_PREFIX}/${period.period_id}.json`, legacyClosePanel());
    const { panels, notes } = await loadPersonalVolAmPmPanels(mem.asBucket(), [period]);
    expect(notes.some((note) => note.startsWith("missing:"))).toBe(true);
    expect(panels[0].status).toBe("data_missing");
    expect(panels[0].source).toBe("am_pm_panel_missing");
  });

  it("rejects a legacy panel stored at the AM/PM key", async () => {
    const mem = new MemR2();
    const period = PERSONAL_VOL_PERIODS[1];
    mem.seed(
      `${PERSONAL_VOL_AM_PM_PANELS_PREFIX}/${period.period_id}.json`,
      {
        ...legacyClosePanel(),
        period_id: period.period_id,
        year: period.year,
        period_start: period.period_start,
        period_end: period.period_end,
      },
    );
    const { panels, notes } = await loadPersonalVolAmPmPanels(mem.asBucket(), [period]);
    expect(notes).toEqual(
      expect.arrayContaining([
        `legacy_period_panel_rejected:${PERSONAL_VOL_AM_PM_PANELS_PREFIX}/${period.period_id}.json`,
      ]),
    );
    expect(panels[0].source).toBe("legacy_period_panel_rejected");
  });

  it("rejects an arbitrary or unsorted session calendar", async () => {
    const fixture = await amPmPanel();
    const topix = parsePersonalVolAmPmPanel({
      ...fixture,
      session_calendar: {
        dataset: "indices_bars_daily_topix",
        label: "TOPIX",
        role: "diagnostic_session_calendar_only",
        dates: fixture.session_calendar.dates,
      },
    });
    expect(topix).toMatchObject({
      ok: false,
      error: "session_calendar_missing_or_invalid",
    });

    const unsorted = parsePersonalVolAmPmPanel({
      ...fixture,
      session_calendar: {
        ...PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
        dates: [...fixture.session_calendar.dates].reverse(),
        dates_digest: fixture.session_calendar.dates_digest,
      },
    });
    expect(unsorted).toMatchObject({
      ok: false,
      error: "session_calendar_missing_or_invalid",
    });

    const duplicate = parsePersonalVolAmPmPanel({
      ...fixture,
      session_calendar: {
        ...PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
        dates: [
          fixture.session_calendar.dates[0],
          fixture.session_calendar.dates[0],
        ],
        dates_digest: fixture.session_calendar.dates_digest,
      },
    });
    expect(duplicate).toMatchObject({
      ok: false,
      error: "session_calendar_missing_or_invalid",
    });
  });

  it("rejects a dates_digest that does not match the pinned ordered calendar", async () => {
    const fixture = await amPmPanel();
    const wrong = {
      ...fixture,
      session_calendar: {
        ...fixture.session_calendar,
        dates_digest: `sha256:${"ab".repeat(32)}`,
      },
    };
    expect(
      await evaluatePersonalVolAmPmWindow(PERSONAL_VOL_STRATEGIES[0], wrong),
    ).toMatchObject({
      status: "incomplete",
      reason: "session_calendar_digest_mismatch",
    });
  });
});

describe("AM/PM causal contract", () => {
  it("shifts the option signal to D-1 and uses D MAdjC for the rank", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const signs = personalVolAmPmEntrySigns(
      panel,
      "basevol_short_long_ratio",
      signalDate,
    );
    expect(signs.A).toBe(-1);
    expect(signs.B).toBe(1);
  });

  it("is invariant to D option values, D full close, and D AAdjC", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const baseline = personalVolAmPmEntrySigns(
      panel,
      "basevol_short_long_ratio",
      signalDate,
    );

    const optionMutated = clone(panel);
    optionMutated.opt225_regime!.basevol!.rv_short_by_date![signalDate] = 0.1;
    optionMutated.opt225_regime!.atm_iv!.rv_short_by_date![signalDate] = 0.1;
    optionMutated.opt225_regime!.skew!.rv_short_by_date![signalDate] = 0.1;
    optionMutated.opt225_regime!.cm_term_ratio!.rv_abs_by_date![signalDate] = -0.4;

    const closeMutated = clone(panel);
    Object.assign(closeMutated.bars.A.find((bar) => bar.date === signalDate)!, {
      AdjC: 9_999,
      Close: 9_999,
    });

    const afternoonMutated = clone(panel);
    afternoonMutated.bars.A.find((bar) => bar.date === signalDate)!.AAdjC = 9_999;

    expect(
      personalVolAmPmEntrySigns(optionMutated, "basevol_short_long_ratio", signalDate),
    ).toEqual(baseline);
    expect(
      personalVolAmPmEntrySigns(closeMutated, "basevol_short_long_ratio", signalDate),
    ).toEqual(baseline);
    expect(
      personalVolAmPmEntrySigns(afternoonMutated, "basevol_short_long_ratio", signalDate),
    ).toEqual(baseline);
  });

  it("changes the D signal when D-1 vol or D MAdjC changes", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const predecessor = dates[7];
    const baseline = personalVolAmPmEntrySigns(
      panel,
      "basevol_short_long_ratio",
      signalDate,
    );

    const volMutated = clone(panel);
    volMutated.opt225_regime!.basevol!.rv_short_by_date![predecessor] = 0.5;
    expect(
      personalVolAmPmEntrySigns(volMutated, "basevol_short_long_ratio", signalDate),
    ).not.toEqual(baseline);
    expect(
      personalVolAmPmEntrySigns(volMutated, "basevol_short_long_ratio", signalDate).A,
    ).toBe(1);

    const morningMutated = clone(panel);
    morningMutated.bars.A.find((bar) => bar.date === signalDate)!.MAdjC = 1;
    expect(
      personalVolAmPmEntrySigns(morningMutated, "basevol_short_long_ratio", signalDate),
    ).not.toEqual(baseline);
  });

  it("changes fill and PnL only when AAdjC changes", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const pnlDate = dates[9];
    const held = {
      A: { [signalDate]: -1 },
      B: { [signalDate]: 1 },
    };
    const baseline = personalVolAmPmDailyPath(held, panel);
    const baselinePoint = baseline.points.find((point) => point.date === pnlDate)!;

    const mutated = clone(panel);
    mutated.bars.A.find((bar) => bar.date === signalDate)!.AAdjC = 100;
    mutated.bars.A.find((bar) => bar.date === pnlDate)!.AAdjC = 150;
    expect(
      personalVolAmPmEntrySigns(mutated, "basevol_short_long_ratio", signalDate),
    ).toEqual(
      personalVolAmPmEntrySigns(panel, "basevol_short_long_ratio", signalDate),
    );
    const mutatedPoint = personalVolAmPmDailyPath(held, mutated).points.find(
      (point) => point.date === pnlDate,
    )!;
    expect(mutatedPoint.net_return).not.toBeCloseTo(baselinePoint.net_return);
  });

  it("fails closed on missing M/A or D-1 vol without AdjC fallback or ffill", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const predecessor = dates[7];

    const missingMorning = clone(panel);
    missingMorning.bars.A = missingMorning.bars.A.filter((bar) => bar.date !== signalDate);
    missingMorning.bars.A.push({
      date: signalDate,
      MAdjC: Number.NaN as unknown as number,
      AAdjC: 208,
    });
    Object.assign(missingMorning.bars.A.at(-1)!, { AdjC: 999 });
    expect(
      personalVolAmPmEntrySigns(missingMorning, "basevol_short_long_ratio", signalDate),
    ).toEqual({ A: 0, B: 0 });
    expect(
      personalVolAmPmCommonValidity(missingMorning).find((row) => row.date === signalDate)
        ?.morning_signal_valid,
    ).toBe(false);

    const missingAfternoon = clone(panel);
    missingAfternoon.bars.B.find((bar) => bar.date === signalDate)!.AAdjC =
      Number.NaN as unknown as number;
    expect(
      personalVolAmPmCommonValidity(missingAfternoon).find((row) => row.date === signalDate)
        ?.morning_signal_valid,
    ).toBe(true);
    expect(
      personalVolAmPmCommonValidity(missingAfternoon).find((row) => row.date === signalDate)
        ?.execution_valid,
    ).toBe(false);

    const missingVol = clone(panel);
    delete missingVol.opt225_regime!.basevol!.rv_short_by_date![predecessor];
    expect(
      personalVolAmPmCommonValidity(missingVol).find((row) => row.date === signalDate)
        ?.morning_signal_valid,
    ).toBe(false);
    for (const definition of PERSONAL_VOL_STRATEGIES) {
      expect(
        personalVolAmPmEntrySigns(missingVol, definition.strategy_id, signalDate),
      ).toEqual({ A: 0, B: 0 });
    }
    expect(personalVolAmPmEntrySigns(missingVol, "control", signalDate)).toEqual({
      A: 0,
      B: 0,
    });
  });

  it("keeps D-morning signs and later rebalance dates unchanged when D AAdjC is removed", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const pnlDate = dates[9];
    const strategy = "basevol_short_long_ratio" as const;
    const baselineSigns = personalVolAmPmEntrySigns(panel, strategy, signalDate);
    const baselineHeld = personalVolAmPmHeldBook(panel, strategy);
    const baselineRebalance = personalVolAmPmRebalanceDates(dates);
    const baselineWindow = await evaluatePersonalVolAmPmWindow(
      PERSONAL_VOL_STRATEGIES[0],
      panel,
    );

    const removed = clone(panel);
    const bar = removed.bars.A.find((row) => row.date === signalDate)!;
    bar.AAdjC = null;
    expect(bar.MAdjC).toBe(panel.bars.A.find((row) => row.date === signalDate)!.MAdjC);

    expect(personalVolAmPmEntrySigns(removed, strategy, signalDate)).toEqual(
      baselineSigns,
    );
    expect(personalVolAmPmHeldBook(removed, strategy)).toEqual(baselineHeld);
    expect(personalVolAmPmRebalanceDates(removed.session_calendar.dates)).toEqual(
      baselineRebalance,
    );
    const laterDates = dates.filter((date) => date > signalDate);
    for (const date of laterDates) {
      expect(personalVolAmPmEntrySigns(removed, strategy, date)).toEqual(
        personalVolAmPmEntrySigns(panel, strategy, date),
      );
    }
    const removedWindow = await evaluatePersonalVolAmPmWindow(
      PERSONAL_VOL_STRATEGIES[0],
      removed,
    );
    expect(removedWindow.status).toBe("incomplete");
    expect(removedWindow.performance_status).toBe("UNAVAILABLE");
    expect(baselineWindow.status).toBe("ok");
    const removedValidity = personalVolAmPmCommonValidity(removed).find(
      (row) => row.date === signalDate,
    )!;
    expect(removedValidity.morning_signal_valid).toBe(true);
    expect(removedValidity.execution_valid).toBe(false);
    const removedPoint = (
      removedWindow.daily_path as Array<{ date: string; net_return: number }>
    ).find((point) => point.date === pnlDate);
    expect(removedPoint?.net_return).toBe(0);
  });

  it("records the first PnL after the D PM fill using AAdjC only", async () => {
    const panel = await amPmPanel();
    const dates = panel.session_calendar.dates;
    const signalDate = dates[8];
    const pnlDate = dates[9];
    panel.bars.A.find((bar) => bar.date === signalDate)!.AAdjC = 100;
    panel.bars.A.find((bar) => bar.date === pnlDate)!.AAdjC = 130;
    panel.period_start = pnlDate;
    panel.period_end = pnlDate;
    const held = { A: { [signalDate]: 1 } };
    const path = personalVolAmPmDailyPath(held, panel);
    expect(path.points.map((point) => point.date)).toEqual([pnlDate]);
    expect(path.points[0].gross_return).toBeCloseTo(0.3);
    expect(path.points[0].net_return).toBeCloseTo(
      0.3 - (2 * PERSONAL_VOL_ONE_WAY_COST) / PERSONAL_VOL_HOLD_SESSIONS,
    );
    const morningReturn =
      panel.bars.A[9].MAdjC / panel.bars.A[8].MAdjC - 1;
    expect(Math.abs((path.points[0].gross_return || 0) - morningReturn)).toBeGreaterThan(
      0.2,
    );
    expect(path.fill_count).toBe(1);
  });

  it("keeps all four candidates and the control on one calendar and cost rule", async () => {
    const panel = await amPmPanel();
    const windows = [
      ...(await Promise.all(
        PERSONAL_VOL_STRATEGIES.map((definition) =>
          evaluatePersonalVolAmPmWindow(definition, panel),
        ),
      )),
      await evaluatePersonalVolAmPmWindow(PERSONAL_VOL_AM_PM_CONTROL, panel),
    ];
    const calendars = windows.map((window) =>
      (
        window.common_validity as Array<{
          date: string;
          morning_signal_valid: boolean;
          execution_valid: boolean;
        }>
      ).map(
        (row) =>
          `${row.date}:${row.morning_signal_valid}:${row.execution_valid}`,
      ),
    );
    for (const calendar of calendars.slice(1)) {
      expect(calendar).toEqual(calendars[0]);
    }
    const cost = (2 * PERSONAL_VOL_ONE_WAY_COST) / PERSONAL_VOL_HOLD_SESSIONS;
    for (const window of windows) {
      expect(window.status).toBe("ok");
      const points = window.daily_path as Array<{
        cost_return: number;
        net_return: number;
      }>;
      expect(
        points.every(
          (point) => point.cost_return === 0 || point.cost_return === cost,
        ),
      ).toBe(true);
      expect(window.fill_count).toBeGreaterThan(0);
      expect(
        (window.metrics as { fill_count: number | null; annualized_sharpe: number | null })
          .fill_count,
      ).toBeGreaterThan(0);
      expect(
        (window.metrics as { schema_version: string }).schema_version,
      ).toBe("personal-performance/v1");
    }
  });

  it("does not use single-stock IV and does not claim a cash-index fill", async () => {
    const singleStock = clone(await amPmPanel());
    singleStock.opt225_regime!.source = {
      dataset: "derivatives_bars_daily_single_stock_options",
      version: PERSONAL_VOL_SOURCE_IDENTITY.version,
    };
    expect(
      await evaluatePersonalVolAmPmWindow(PERSONAL_VOL_STRATEGIES[0], singleStock),
    ).toMatchObject({
      status: "incomplete",
      reason: "opt225_source_identity_missing_or_mismatch",
    });
    const ok = await evaluatePersonalVolAmPmWindow(
      PERSONAL_VOL_STRATEGIES[0],
      await amPmPanel(),
    );
    expect(ok.individual_stock_option_volatility_used).toBe(false);
    expect(ok.cash_index_executable_fill).toBe(false);
  });

  it("rejects a legacy panel at evaluation time", async () => {
    expect(
      await evaluatePersonalVolAmPmWindow(
        PERSONAL_VOL_STRATEGIES[0],
        legacyClosePanel() as unknown as PersonalVolAmPmPanel,
      ),
    ).toMatchObject({
      status: "incomplete",
      reason: "legacy_period_panel_rejected",
      metrics: null,
    });
  });
});

const noopMass = async () => {
  throw new Error("mass evaluator must not run");
};

describe("POST /v1/personal-vol-am-pm-research", () => {
  it("authenticates before dispatch and does not reuse the v2 handler", async () => {
    let amPmCalls = 0;
    let v2Calls = 0;
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-vol-am-pm-research", {
        method: "POST",
        body: JSON.stringify({ job_id: "closed-am-pm" }),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
      } as Env,
      {
        runMassEval: noopMass,
        runDailyPath: noopMass,
        runPersonalVolResearch: async () => {
          v2Calls += 1;
          return {};
        },
        runPersonalVolAmPmResearch: async () => {
          amPmCalls += 1;
          return {};
        },
      },
    );
    expect(response.status).toBe(401);
    expect(amPmCalls).toBe(0);
    expect(v2Calls).toBe(0);
  });

  it("dispatches the AM/PM cohort independently of Mass/READY flags", async () => {
    let received: unknown;
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-vol-am-pm-research", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-mass-eval-token": "secret",
        },
        body: JSON.stringify({
          job_id: "closed-am-pm",
          panel_build_job_id: PANEL_BUILD_JOB_ID,
        }),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
        MASS_RESEARCH: "NO-GO",
        PHASE7: "OFF",
        READY_DECLARED: "false",
      } as Env,
      {
        runMassEval: noopMass,
        runDailyPath: noopMass,
        runPersonalVolResearch: noopMass,
        runPersonalVolAmPmResearch: async (_env, request) => {
          received = request;
          return { research_mode: "personal_draft_screening", go: false };
        },
      },
    );
    expect(response.status).toBe(200);
    expect(received).toEqual({
      job_id: "closed-am-pm",
      cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
      panel_build_job_id: PANEL_BUILD_JOB_ID,
    });
  });
});

describe("AM/PM immutable artifact", () => {
  it("writes distinct keys and remains DRAFT-only", async () => {
    const mem = new MemR2();
    await seedPanelBuild(
      mem,
      PANEL_BUILD_JOB_ID,
      await Promise.all(PERSONAL_VOL_PERIODS.map((period) => panelForPeriod(period))),
    );
    const result = await runPersonalVolAmPmResearch(
      {
        STRUCTURED_BUCKET: mem.asBucket(),
        MASS_EVAL_VERSION: "research-mass-eval/test",
      } as Env,
      {
        job_id: "immutable-am-pm",
        cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
        panel_build_job_id: PANEL_BUILD_JOB_ID,
      },
    );
    const prefix = `${PERSONAL_VOL_AM_PM_JOB_ROOT}/job=immutable-am-pm`;
    expect(result.schema_version).toBe(PERSONAL_VOL_AM_PM_REPORT_SCHEMA);
    expect(result.cohort_id).toBe(PERSONAL_VOL_AM_PM_COHORT_ID);
    expect(result.go).toBe(false);
    expect(result.automatic_promotion).toBe(false);
    expect(result.live_orders).toBe(false);
    expect(result.am_pm_contract).toMatchObject(PERSONAL_VOL_AM_PM_CONTRACT);
    expect(result.data_contract).toMatchObject({
      panels_prefix: PERSONAL_VOL_AM_PM_PANELS_PREFIX,
      panel_schema: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
      producer_dependency: PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY,
    });
    expect(result.execution_contract).toMatchObject({
      exact_four: true,
      fill: "D_AAdjC",
      first_pnl: "D_AAdjC_to_next_AAdjC",
      cash_index_executable_fill: false,
    });
    expect((result.strategies as unknown[])).toHaveLength(4);
    expect(result.control).toMatchObject({
      control_id: PERSONAL_VOL_AM_PM_CONTROL.control_id,
      ranking_role: "DIAGNOSTIC_CONTROL_NOT_RANKED",
    });
    expect(String(result.r2_keys)).not.toContain("vol-ratio-v2");
    expect(mem.order.indexOf(`${prefix}/manifest.json`)).toBeGreaterThan(
      mem.order.indexOf(`${prefix}/report.json`),
    );
  });

  it("does not reinterpret legacy v2 panels when the AM/PM producer is absent", async () => {
    const mem = new MemR2();
    for (const period of PERSONAL_VOL_PERIODS) {
      mem.seed(`${PERSONAL_VOL_PANELS_PREFIX}/${period.period_id}.json`, {
        period_id: period.period_id,
        year: period.year,
        period_start: period.period_start,
        period_end: period.period_end,
        status: "ok",
        bars: { A: [["2023-09-01", 100]] },
      });
    }
    await expect(
      runPersonalVolAmPmResearch(
        {
          STRUCTURED_BUCKET: mem.asBucket(),
          MASS_EVAL_VERSION: "research-mass-eval/test",
        } as Env,
        {
          job_id: "missing-producer",
          cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
          panel_build_job_id: PANEL_BUILD_JOB_ID,
        },
      ),
    ).rejects.toMatchObject({ code: "panel_build_terminal_missing" });
  });

  it("resolves exact children from panel_build_job_id and rejects mask tamper", async () => {
    const mem = new MemR2();
    const panels = await Promise.all(
      PERSONAL_VOL_PERIODS.map((period) => panelForPeriod(period)),
    );
    await seedPanelBuild(mem, PANEL_BUILD_JOB_ID, panels);
    const loaded = await loadPersonalVolAmPmPanelsFromBuildJob(
      mem.asBucket(),
      PANEL_BUILD_JOB_ID,
    );
    expect(loaded.panels.map((panel) => panel.period_id)).toEqual(
      PERSONAL_VOL_PERIODS.map((period) => period.period_id),
    );
    expect(loaded.comparisonNotEvaluated).toBe(false);

    const first = PERSONAL_VOL_PERIODS[0]!;
    const tampered = loaded.commonValid.get(first.period_id)!;
    tampered[1] = { ...tampered[1]!, common_valid: !tampered[1]!.common_valid };
    const terminal = (await mem.get(
      personalVolAmPmPanelBuildTerminalKey(PANEL_BUILD_JOB_ID),
    )) as { json: () => Promise<Record<string, unknown>> };
    const document = await terminal.json();
    const periods = document.periods as Record<string, { common_valid_sha256: string }>;
    periods[first.period_id]!.common_valid_sha256 = `sha256:${"ab".repeat(32)}`;
    mem.seed(personalVolAmPmPanelBuildTerminalKey(PANEL_BUILD_JOB_ID), document);
    await expect(
      loadPersonalVolAmPmPanelsFromBuildJob(mem.asBucket(), PANEL_BUILD_JOB_ID),
    ).rejects.toMatchObject({ code: "common_valid_mask_tamper_rejected" });
  });

  it("keeps a zero-row frozen member and refuses an A-only common mask", async () => {
    const fixture = await amPmPanel();
    const parsed = parsePersonalVolAmPmPanel(
      { ...fixture, bars: { A: fixture.bars.A } },
      ["A", "B"],
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.codes).toEqual(["A", "B"]);
    expect(parsed.value.bars.B).toEqual([]);
    const fullMask = personalVolAmPmCommonValidMask(parsed.value);
    const aOnly = parsePersonalVolAmPmPanel({
      ...fixture,
      codes: ["A"],
      bars: { A: fixture.bars.A },
    });
    expect(aOnly.ok).toBe(true);
    if (!aOnly.ok) return;
    const aMask = personalVolAmPmCommonValidMask(aOnly.value);
    expect(await personalVolAmPmCommonValidDigest(fullMask)).not.toBe(
      await personalVolAmPmCommonValidDigest(aMask),
    );
    expect(fullMask.every((row) => !row.common_valid)).toBe(true);

    const mem = new MemR2();
    const panels = await Promise.all(
      PERSONAL_VOL_PERIODS.map(async (period) => {
        const panel = await panelForPeriod(period);
        panel.codes = ["A", "B"];
        panel.bars = { A: panel.bars.A, B: [] };
        return panel;
      }),
    );
    await seedPanelBuild(mem, PANEL_BUILD_JOB_ID, panels, undefined, ["A", "B"]);
    const loaded = await loadPersonalVolAmPmPanelsFromBuildJob(
      mem.asBucket(),
      PANEL_BUILD_JOB_ID,
    );
    expect(equityCodes(loaded.panels[0]!)).toEqual(["A", "B"]);
    expect(loaded.comparisonNotEvaluated).toBe(true);
    await expect(
      loadPersonalVolAmPmPanelsFromBuildJob(
        mem.asBucket(),
        PANEL_BUILD_JOB_ID,
      ).then(async (again) => {
        const aOnlyPanels = again.panels.map((panel) => ({
          ...panel,
          codes: ["A"],
          bars: { A: panel.bars.A },
        }));
        const aOnlyDigest = await personalVolAmPmCommonValidDigest(
          personalVolAmPmCommonValidMask(aOnlyPanels[0]!),
        );
        expect(aOnlyDigest).not.toBe(
          await personalVolAmPmCommonValidDigest(
            personalVolAmPmCommonValidMask(again.panels[0]!),
          ),
        );
        return again;
      }),
    ).resolves.toMatchObject({ comparisonNotEvaluated: true });
  });

  it("marks every exact-four candidate and the control unevaluated on a shared hole", async () => {
    const mem = new MemR2();
    const panels = await Promise.all(
      PERSONAL_VOL_PERIODS.map((period) => panelForPeriod(period)),
    );
    const hole = panels[0]!;
    hole.bars.A[2] = { ...hole.bars.A[2]!, AAdjC: null };
    await seedPanelBuild(mem, PANEL_BUILD_JOB_ID, panels);
    const result = await runPersonalVolAmPmResearch(
      {
        STRUCTURED_BUCKET: mem.asBucket(),
        MASS_EVAL_VERSION: "research-mass-eval/test",
      } as Env,
      {
        job_id: "shared-mask",
        cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
        panel_build_job_id: PANEL_BUILD_JOB_ID,
      },
    );
    expect(result.execution_contract).toMatchObject({
      exact_four_evaluation_complete: false,
    });
    expect(result.execution_summary).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          strategy_id: PERSONAL_VOL_STRATEGIES[0]!.strategy_id,
          candidate_status: "not_evaluated",
        }),
        expect.objectContaining({
          control_id: PERSONAL_VOL_AM_PM_CONTROL.control_id,
          candidate_status: "not_evaluated",
        }),
      ]),
    );
  });
});
