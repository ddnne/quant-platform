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
