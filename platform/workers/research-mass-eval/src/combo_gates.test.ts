import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { clusterWindowSeries, comboCsGateOk, comboEventGateOk } from "./daily_path";
import type { PeriodPanel } from "./types";

const dummyPanel = { fund_regime: { events_by_code: {} } } as PeriodPanel;
const ev = {
  code: "13010",
  disc: "2019-01-08",
  entryDate: "2019-01-08",
  entryIdx: 2,
  sign: 1,
  abs: 1,
  after: false,
};

describe("comboEventGateOk", () => {
  it("skip_tuesday fails on Tuesday and passes other weekdays", () => {
    const tue = { ...ev, entryDate: "2019-01-08" }; // Tuesday
    const wed = { ...ev, entryDate: "2019-01-09" };
    expect(
      comboEventGateOk("skip_tuesday", tue, {}, {}, 20, dummyPanel),
    ).toBe(false);
    expect(
      comboEventGateOk("skip_tuesday", wed, {}, {}, 20, dummyPanel),
    ).toBe(true);
  });

  it("unknown gate fails closed", () => {
    expect(
      comboEventGateOk("not_a_real_gate", ev, {}, {}, 20, dummyPanel),
    ).toBe(false);
  });

  it("eq_ar_high / ta_up skip when payload fields are missing", () => {
    const missing = { ...ev, eq_ar: null, ta: null, prior_ta: null };
    expect(
      comboEventGateOk("eq_ar_high", missing, {}, {}, 8, dummyPanel),
    ).toBe(false);
    expect(
      comboEventGateOk("ta_up", missing, {}, {}, 8, dummyPanel),
    ).toBe(false);
  });

  it("ta_up keeps when TA rose versus prior_ta", () => {
    const up = { ...ev, ta: 200, prior_ta: 150 };
    const down = { ...ev, ta: 100, prior_ta: 150 };
    expect(comboEventGateOk("ta_up", up, {}, {}, 8, dummyPanel)).toBe(true);
    expect(comboEventGateOk("ta_up", down, {}, {}, 8, dummyPanel)).toBe(false);
  });

  it("cluster uses a linear window series and skips missing dates", () => {
    const dates = [
      "2019-01-04",
      "2019-01-05",
      "2019-01-07",
      "2019-01-08",
      "2019-01-09",
      "2019-01-10",
      "2019-01-11",
      "2019-01-14",
      "2019-01-15",
      "2019-01-16",
      "2019-01-17",
      "2019-01-18",
      "2019-01-21",
    ];
    const panel = {
      fund_regime: {
        events_by_code: {
          a: dates.map((d) => ({ disc_date: d })),
          b: [{ disc_date: "2019-01-21" }, { disc_date: "2019-01-21" }],
        },
      },
    } as PeriodPanel;
    const series = clusterWindowSeries(panel);
    expect(series["2019-01-04"]).toBe(0);
    expect(series["2019-01-08"]).toBeGreaterThan(0);
    expect(series["2019-01-21"]).toBeGreaterThan(series["2019-01-04"]);
    const quiet = { ...ev, disc: "2019-01-04", entryDate: "2019-01-04" };
    expect(comboEventGateOk("cluster", quiet, {}, {}, 8, panel)).toBe(false);
  });

  it("liq_high skips missing ADV and keeps above-median names", () => {
    const panel = {
      adv_by_code: { "13010": 200, "72030": 50, "67580": 40, "99840": 30 },
    } as PeriodPanel;
    expect(comboEventGateOk("liq_high", ev, {}, {}, 8, panel)).toBe(true);
    const thin = { ...ev, code: "99840" };
    expect(comboEventGateOk("liq_high", thin, {}, {}, 8, panel)).toBe(false);
    expect(comboEventGateOk("liq_high", ev, {}, {}, 8, dummyPanel)).toBe(false);
  });

  it("month_end_skip fails on and after the 28th", () => {
    const late = { ...ev, entryDate: "2019-01-28" };
    const ok = { ...ev, entryDate: "2019-01-27" };
    expect(comboEventGateOk("month_end_skip", late, {}, {}, 20, dummyPanel)).toBe(
      false,
    );
    expect(comboEventGateOk("month_end_skip", ok, {}, {}, 20, dummyPanel)).toBe(
      true,
    );
  });

  it("fy_end is late March (Mar>=15), fy_results May, fy_start April", () => {
    const mar15 = { ...ev, entryDate: "2019-03-15" };
    const mar14 = { ...ev, entryDate: "2019-03-14" };
    const apr = { ...ev, entryDate: "2019-04-01" };
    const may = { ...ev, entryDate: "2019-05-02" };
    expect(comboEventGateOk("fy_end", mar15, {}, {}, 20, dummyPanel)).toBe(true);
    expect(comboEventGateOk("fy_end", mar14, {}, {}, 20, dummyPanel)).toBe(false);
    expect(comboEventGateOk("fy_end", apr, {}, {}, 20, dummyPanel)).toBe(false);
    expect(comboEventGateOk("fy_results", may, {}, {}, 20, dummyPanel)).toBe(
      true,
    );
    expect(comboEventGateOk("fy_results", apr, {}, {}, 20, dummyPanel)).toBe(
      false,
    );
    expect(comboEventGateOk("fy_start", apr, {}, {}, 20, dummyPanel)).toBe(true);
    expect(comboEventGateOk("fy_start", may, {}, {}, 20, dummyPanel)).toBe(false);
  });

  it("overnight_tightening keeps a rise versus the prior print", () => {
    const up = { "2019-01-07": 0.1, "2019-01-08": 0.2 };
    const down = { "2019-01-07": 0.2, "2019-01-08": 0.1 };
    const flat = { "2019-01-07": 0.2, "2019-01-08": 0.2 };
    expect(comboEventGateOk("overnight_tightening", ev, up, {}, 20, dummyPanel)).toBe(
      true,
    );
    expect(
      comboEventGateOk("overnight_tightening", ev, down, {}, 20, dummyPanel),
    ).toBe(false);
    expect(
      comboEventGateOk("overnight_tightening", ev, flat, {}, 20, dummyPanel),
    ).toBe(false);
    expect(
      comboEventGateOk("overnight_tightening", ev, { "2019-01-08": 0.2 }, {}, 20, dummyPanel),
    ).toBe(false);
  });

  it("crowded_margin is the invert of uncrowded_margin (stale<=14d)", () => {
    const levels: Record<string, number> = {};
    for (let i = 1; i <= 20; i++) {
      levels[`2018-12-${String(i).padStart(2, "0")}`] = 10;
    }
    levels["2019-01-07"] = 20;
    const panel = {
      flow_regime: { margin_level_by_code: { "13010": levels } },
    } as PeriodPanel;
    expect(comboEventGateOk("crowded_margin", ev, {}, {}, 8, panel)).toBe(true);
    expect(comboEventGateOk("uncrowded_margin", ev, {}, {}, 8, panel)).toBe(
      false,
    );
    const thin = { ...levels, "2019-01-07": 5 };
    const thinPanel = {
      flow_regime: { margin_level_by_code: { "13010": thin } },
    } as PeriodPanel;
    expect(comboEventGateOk("crowded_margin", ev, {}, {}, 8, thinPanel)).toBe(
      false,
    );
    expect(comboEventGateOk("uncrowded_margin", ev, {}, {}, 8, thinPanel)).toBe(
      true,
    );
    const stale: Record<string, number> = {};
    for (let i = 1; i <= 20; i++) {
      stale[`2018-12-${String(i).padStart(2, "0")}`] = 20;
    }
    const stalePanel = {
      flow_regime: { margin_level_by_code: { "13010": stale } },
    } as PeriodPanel;
    expect(comboEventGateOk("crowded_margin", ev, {}, {}, 8, stalePanel)).toBe(
      false,
    );
    expect(comboEventGateOk("crowded_margin", ev, {}, {}, 8, dummyPanel)).toBe(
      false,
    );
  });

  it("pre_mom uses last close strictly before entry (Python lookback)", () => {
    const pairs: Array<[string, number]> = [
      ["2019-01-02", 100],
      ["2019-01-03", 101],
      ["2019-01-04", 102],
      ["2019-01-05", 103],
      ["2019-01-07", 104],
      ["2019-01-08", 80],
      ["2019-01-09", 70],
    ];
    const panel = { bars: { "13010": pairs } } as PeriodPanel;
    const agree = { ...ev, entryDate: "2019-01-09", entryIdx: 6, sign: -1 };
    const disagree = { ...agree, sign: 1 };
    const shortHist = { ...ev, entryDate: "2019-01-08", entryIdx: 5, sign: -1 };
    expect(comboEventGateOk("pre_mom", agree, {}, {}, 20, panel)).toBe(true);
    expect(comboEventGateOk("pre_mom", disagree, {}, {}, 20, panel)).toBe(false);
    expect(comboEventGateOk("pre_mom", shortHist, {}, {}, 20, panel)).toBe(
      false,
    );
    expect(comboEventGateOk("pre_mom", agree, {}, {}, 20, dummyPanel)).toBe(
      false,
    );
  });

  it("leftover pre_mom lids reuse comboEventGateOk occupancy (entryIdx-1)", () => {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "daily_path.ts"),
      "utf8",
    );
    const easy = src.slice(
      src.indexOf('if (lid === "event_pre_mom_easy_funding")'),
      src.indexOf('if (lid === "event_margin_or_funding_skip")'),
    );
    const steep = src.slice(
      src.indexOf('if (lid === "event_pre_mom_steep_curve")'),
      src.indexOf('if (lid === "event_large_surprise_afterclose")'),
    );
    expect(easy).toContain('comboEventGateOk("pre_mom"');
    expect(easy).toContain("params.side");
    expect(easy).not.toContain("momentumAt");
    expect(steep).toContain('comboEventGateOk("pre_mom"');
    expect(steep).toContain("params.side");
    expect(steep).not.toContain("momentumAt");
    expect(src).toContain(
      'lid === "surprise_xs_month_start" && ev.entryDate.slice(8, 10) > "05"',
    );
  });
});

describe("crossed CS gates fail closed without extras", () => {
  it("eq_ar_high_repo3m_down and cheap_pb_cheap_iv skip when extras missing", () => {
    const miss = comboCsGateOk(
      "eq_ar_high_repo3m_down",
      "2019-01-08",
      {},
      {},
      null,
      null,
      null,
    );
    expect(miss.keep).toBe(false);
    const iv = comboCsGateOk(
      "cheap_pb_cheap_iv",
      "2019-01-08",
      {},
      {},
      null,
      null,
      null,
      { cheapPb: true, cheapIv: false },
    );
    expect(iv.keep).toBe(false);
  });
});

describe("comboCsGateOk", () => {
  it("skip_wednesday and month_start7 are calendar-only", () => {
    const wed = comboCsGateOk("skip_wednesday", "2019-01-09", {}, {}, null, null, null);
    const tue = comboCsGateOk("skip_wednesday", "2019-01-08", {}, {}, null, null, null);
    expect(wed.keep).toBe(false);
    expect(tue.keep).toBe(true);
    const start = comboCsGateOk("month_start7", "2019-01-05", {}, {}, null, null, null);
    const late = comboCsGateOk("month_start7", "2019-01-20", {}, {}, null, null, null);
    expect(start.keep).toBe(true);
    expect(late.keep).toBe(false);
  });

  it("fy_end_invert is late March fade; fy_start is April follow", () => {
    const mar15 = comboCsGateOk("fy_end_invert", "2019-03-15", {}, {}, null, null, null);
    const mar14 = comboCsGateOk("fy_end_invert", "2019-03-14", {}, {}, null, null, null);
    const apr = comboCsGateOk("fy_start", "2019-04-02", {}, {}, null, null, null);
    const may = comboCsGateOk("fy_start", "2019-05-02", {}, {}, null, null, null);
    expect(mar15.keep).toBe(true);
    expect(mar15.invert).toBe(true);
    expect(mar14.keep).toBe(false);
    expect(apr.keep).toBe(true);
    expect(apr.invert).toBe(false);
    expect(may.keep).toBe(false);
  });

  it("unknown gate fails closed", () => {
    const miss = comboCsGateOk(
      "not_a_real_cs_gate",
      "2019-01-08",
      {},
      {},
      null,
      null,
      null,
    );
    expect(miss.keep).toBe(false);
    expect(miss.invert).toBe(false);
  });
});
