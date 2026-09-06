import { describe, expect, it } from "vitest";
import {
  cellsFromPeriodPacks,
  equityPathDrawdown,
  evalLogicDailyPathOnPanel,
} from "./daily_path";
import type { PeriodPanel } from "./types";

function isoDays(n: number): string[] {
  const start = Date.parse("2026-01-05T00:00:00Z");
  return Array.from({ length: n }, (_, index) =>
    new Date(start + index * 86_400_000).toISOString().slice(0, 10),
  );
}

function panel(options: { adv?: boolean; events?: boolean } = {}): PeriodPanel {
  const dates = isoDays(24);
  const bars = {
    "13010": dates.map((date, index) => [date, 100 + index] as [string, number]),
    "72030": dates.map((date, index) => [date, 120 - index * 0.4] as [string, number]),
    "99840": dates.map((date, index) => [date, 80 + index * 0.2] as [string, number]),
  };
  return {
    period_id: "p1",
    year: 2026,
    period_start: dates[0],
    period_end: dates.at(-1)!,
    status: "ok",
    source: "test",
    bars,
    adv_by_code:
      options.adv === false
        ? undefined
        : { "13010": 2e9, "72030": 5e8, "99840": 2e8 },
    fund_regime:
      options.events === false
        ? undefined
        : {
            events_by_code: {
              "13010": [
                {
                  disc_date: dates[2],
                  disc_time: "15:30:00",
                  eps: 12,
                  prior_eps: 10,
                  bps: 100,
                },
              ],
              "72030": [
                {
                  disc_date: dates[1],
                  disc_time: "12:00:00",
                  eps: 8,
                  prior_eps: 9,
                  bps: 90,
                },
              ],
              "99840": [
                {
                  disc_date: dates[0],
                  disc_time: null,
                  eps: 5,
                  prior_eps: 5,
                  bps: 75,
                },
              ],
            },
          },
  };
}

describe("controlled daily path", () => {
  it("evaluates each controlled-pilot structural path without a catalog id table", () => {
    const cases = [
      {
        logic_id: "paper_mdh_hold10_momentum_topk",
        family_id: "multi_day_hold",
        params: { hold_days: 10, momentum_n: 10 },
        path: "controlled:mdh",
      },
      {
        logic_id: "cross_section_hold_10",
        family_id: "cross_section_relative",
        params: { hold_days: 10, momentum_n: 5, long_frac: 0.3, short_frac: 0.3 },
        path: "controlled:cross_section",
      },
      {
        logic_id: "paper_event_post_hold5_disclosure_proxy",
        family_id: "event_post",
        params: { post_hold_days: 5 },
        path: "controlled:event_post",
      },
      {
        logic_id: "fundamentals_hold_10",
        family_id: "fundamentals_price",
        params: { hold_days: 10, momentum_n: 10, mode: "value_momentum_agree" },
        path: "controlled:fundamentals",
      },
    ];
    for (const testCase of cases) {
      const result = evalLogicDailyPathOnPanel(testCase, panel(), 0.001);
      expect(result.status, testCase.logic_id).toBe("ok");
      expect(String(result.eval_path), testCase.logic_id).toContain(testCase.path);
      expect(result.path_fallback, testCase.logic_id).toBeNull();
      expect(result.daily_path_complete, testCase.logic_id).toBe(true);
      expect(result.go).toBe(false);
      expect(result.promote_as_main).toBe(false);
    }
  });

  it("rejects a retired catalog row before evaluating a panel", () => {
    const result = evalLogicDailyPathOnPanel(
      {
        logic_id: "event_cheap_iv_cheap_pb",
        family_id: "event_post",
        params: { gates: ["cheap_iv", "cheap_pb"] },
      },
      panel(),
      0.001,
    );
    expect(result.status).toBe("unsupported_strategy");
    expect(result.skip_reason).toBe("unsupported_strategy");
    expect(result.daily_path_complete).toBe(false);
    expect(result.path_fallback).toBe("path_broken_unsupported_strategy");
  });

  it("fails closed when cost or event evidence is missing", () => {
    const noAdv = evalLogicDailyPathOnPanel(
      { logic_id: "paper_mdh_hold10_momentum_topk" },
      panel({ adv: false }),
      0.001,
    );
    expect(noAdv.cost_adv_incomplete).toBe(true);
    expect(noAdv.daily_path_complete).toBe(false);
    expect(noAdv.path_fallback).toBe("path_broken_missing_adv");

    const noEvents = evalLogicDailyPathOnPanel(
      { logic_id: "paper_event_post_hold5_disclosure_proxy" },
      panel({ events: false }),
      0.001,
    );
    expect(noEvents.daily_path_complete).toBe(false);
    expect(noEvents.path_fallback).toBe("path_broken_missing_disclosure_events");
  });

  it("preserves an incomplete path as broken in cell projection", () => {
    const cells = cellsFromPeriodPacks("retired", [
      {
        period_id: "p1",
        status: "unsupported_strategy",
        skip_reason: "unsupported_strategy",
        eval_path: "controlled_exact_four",
        path_fallback: "path_broken_unsupported_strategy",
      },
    ]);
    expect(cells).toHaveLength(1);
    expect(cells[0]).toMatchObject({
      daily_path_complete: false,
      incomplete_reason: "unsupported_strategy",
      path_fallback: "path_broken_unsupported_strategy",
      go: false,
    });
  });
});

describe("equityPathDrawdown", () => {
  it("returns null evidence for a length mismatch", () => {
    expect(equityPathDrawdown([1, 0.9], ["2026-01-05"])).toMatchObject({
      max_dd: null,
      recovered: null,
      n: 0,
    });
  });

  it("measures drawdown and recovery from the daily equity path", () => {
    const result = equityPathDrawdown(
      [1, 1.1, 0.88, 1.1],
      ["d0", "d1", "d2", "d3"],
    );
    expect(result.max_dd).toBeCloseTo(-0.2);
    expect(result.dd_duration_days).toBe(1);
    expect(result.recovered).toBe(true);
    expect(result.recovery_days).toBe(1);
  });
});
