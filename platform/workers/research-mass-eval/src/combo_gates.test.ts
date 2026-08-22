import { describe, expect, it } from "vitest";
import { comboCsGateOk, comboEventGateOk } from "./daily_path";
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
});
