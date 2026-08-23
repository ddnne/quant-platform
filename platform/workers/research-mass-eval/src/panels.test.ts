import { describe, expect, it } from "vitest";
import { buildSyntheticPanels, defaultPeriodsFromRequest } from "./panels";

const DEFAULT_YEARS = [2015, 2017, 2019, 2021, 2023, 2025];

describe("defaultPeriodsFromRequest", () => {
  it("returns provided non-empty periods with matching ids, years, and bounds", () => {
    const periods = [
      {
        period_id: "custom_a",
        year: 2016,
        period_start: "2016-10-01",
        period_end: "2016-12-15",
      },
      {
        period_id: "custom_b",
        year: 2018,
        period_start: "2018-10-03",
        period_end: "2018-12-14",
      },
    ];
    const out = defaultPeriodsFromRequest(periods, 1);
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual({
      period_id: "custom_a",
      year: 2016,
      period_start: "2016-10-01",
      period_end: "2016-12-15",
    });
    expect(out[1]).toEqual({
      period_id: "custom_b",
      year: 2018,
      period_start: "2018-10-03",
      period_end: "2018-12-14",
    });
    for (const p of out) {
      expect(typeof p.year).toBe("number");
    }
  });

  it("fills missing period_id as p${i} and missing year from the default table", () => {
    const out = defaultPeriodsFromRequest(
      [
        { period_id: "", period_start: "2015-10-01", period_end: "2015-12-15" },
        { period_id: "kept", year: 2018 },
        { period_id: "" },
      ],
      99,
    );
    expect(out[0].period_id).toBe("p0");
    expect(out[0].year).toBe(DEFAULT_YEARS[0]);
    expect(out[0].period_start).toBe("2015-10-01");
    expect(out[0].period_end).toBe("2015-12-15");
    expect(out[1].period_id).toBe("kept");
    expect(out[1].year).toBe(2018);
    expect(out[2].period_id).toBe("p2");
    expect(out[2].year).toBe(DEFAULT_YEARS[2]);
    for (const p of out) {
      expect(typeof p.year).toBe("number");
    }
  });

  it("defaults to six shuffled Q4-lite periods when periods is empty", () => {
    const expected = new Set(DEFAULT_YEARS);
    for (const periods of [undefined, [] as []]) {
      const out = defaultPeriodsFromRequest(periods, 42);
      expect(out).toHaveLength(6);
      expect(new Set(out.map((p) => p.year))).toEqual(expected);
      for (const p of out) {
        expect(p.year).toEqual(expect.any(Number));
        expect(p.period_id).toBe(`y${p.year}_q4_lite`);
      }
    }
  });

  it("is deterministic for the same seed", () => {
    const a = defaultPeriodsFromRequest(undefined, 42);
    const b = defaultPeriodsFromRequest(undefined, 42);
    expect(a).toEqual(b);
    expect(a.map((p) => p.year)).toEqual([2017, 2015, 2023, 2025, 2019, 2021]);
    expect(a.map((p) => p.period_id)).toEqual([
      "y2017_q4_lite",
      "y2015_q4_lite",
      "y2023_q4_lite",
      "y2025_q4_lite",
      "y2019_q4_lite",
      "y2021_q4_lite",
    ]);
  });
});

describe("buildSyntheticPanels", () => {
  it("emits bars for each default period without COMPLETE", () => {
    const periods = defaultPeriodsFromRequest(undefined, 1);
    const panels = buildSyntheticPanels(periods, 1, 3, 5);
    expect(panels).toHaveLength(6);
    for (const panel of panels) {
      expect(Object.keys(panel.bars).length).toBeGreaterThan(0);
      expect(JSON.stringify(panel)).not.toMatch(/COMPLETE/);
    }
  });
});
