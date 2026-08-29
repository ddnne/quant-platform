import { describe, expect, it } from "vitest";

import { barNativeHeldBook } from "./eval";
import type { LogicSpec, PeriodPanel } from "./types";

const DATES = [
  "2025-01-06",
  "2025-01-07",
  "2025-01-08",
  "2025-01-09",
  "2025-01-10",
  "2025-01-14",
];

function panel(ratio: number | null): PeriodPanel {
  const ratioSeries =
    ratio === null
      ? null
      : Object.fromEntries(DATES.map((day) => [day, ratio]));
  return {
    period_id: "ratio-route",
    year: 2025,
    period_start: DATES[0],
    period_end: DATES.at(-1)!,
    status: "ok",
    source: "fixture",
    bars: {
      A: DATES.map((day, index) => [day, 100 + index]),
      B: DATES.map((day, index) => [day, 105 - index]),
    },
    cm_term_ratio_series: ratioSeries,
    // A difference sidecar must never satisfy the ratio contract.
    cm_term_series: Object.fromEntries(DATES.map((day) => [day, 9.0])),
    nky_vol_series: {
      rv_abs_by_date: Object.fromEntries(DATES.map((day) => [day, 99.0])),
    },
  };
}

const LOGIC: LogicSpec = {
  logic_id: "opt225_cm_term_ratio",
  family_id: "options_vol_regime",
  params: {
    mode: "opt225_cm_term_ratio",
    series_kind: "cm_term_ratio",
    momentum_n: 2,
    hold_days: 1,
    long_frac: 0.5,
    short_frac: 0.5,
    high_threshold: 0.1,
    low_threshold: -0.1,
  },
};

describe("options calendar-maturity ratio routing", () => {
  it("uses the zero-centred level rather than a rolling term-ratio transform", () => {
    const high = barNativeHeldBook(LOGIC, panel(0.2));
    const low = barNativeHeldBook(LOGIC, panel(-0.2));
    const last = DATES.at(-1)!;

    expect(high?.path).toBe("opt225:opt225_cm_term_ratio");
    expect(low?.path).toBe("opt225:opt225_cm_term_ratio");
    expect(high?.held.A[last]).toBe(-1);
    expect(high?.held.B[last]).toBe(1);
    expect(low?.held.A[last]).toBe(1);
    expect(low?.held.B[last]).toBe(-1);
  });

  it("does not fall back to the absolute near-minus-next sidecar", () => {
    const missing = barNativeHeldBook(LOGIC, panel(null));

    expect(missing?.held).toEqual({});
    expect(missing?.fallback).toBe("path_broken_missing_sidecar");
  });

  it("omits ratio observations before the IV-field availability pin", () => {
    const prePin = panel(0.2);
    prePin.cm_term_ratio_series = { "2016-07-18": 0.2 };
    prePin.bars = {
      A: [["2016-07-18", 100]],
      B: [["2016-07-18", 99]],
    };

    const result = barNativeHeldBook(LOGIC, prePin);

    expect(result?.held).toEqual({ A: {}, B: {} });
  });

  it("can flatten a neutral regime at the next fixed rebalance", () => {
    const dates = Array.from({ length: 12 }, (_, index) =>
      new Date(Date.UTC(2025, 0, 6 + index)).toISOString().slice(0, 10),
    );
    const fixture = panel(0.2);
    fixture.period_start = dates[0];
    fixture.period_end = dates.at(-1)!;
    fixture.bars = {
      A: dates.map((day, index) => [day, 100 + index]),
      B: dates.map((day, index) => [day, 112 - index]),
    };
    fixture.cm_term_ratio_series = Object.fromEntries(
      dates.map((day, index) => [day, index < 6 ? 0.2 : 0.0]),
    );
    const result = barNativeHeldBook(
      {
        ...LOGIC,
        params: {
          ...LOGIC.params,
          hold_days: 3,
          neutral_policy: "flat_at_rebalance",
        },
      },
      fixture,
    );

    expect(result?.held.A[dates[5]]).toBe(-1);
    expect(result?.held.A[dates[6]]).toBeUndefined();
    expect(result?.held.B[dates[6]]).toBeUndefined();
  });
});
