import { describe, expect, it } from "vitest";
import { isMdhCollapseSignal, isPathCollapsedRow } from "./mdh_collapse";

describe("isMdhCollapseSignal", () => {
  it("flags unique MDH fallback and never treats it as a candidate path", () => {
    expect(isMdhCollapseSignal("c21_lite_fallback_mdh:event_calendar_gate")).toBe(
      true,
    );
    expect(isMdhCollapseSignal("c21_lite_fallback_mdh:surprise_xs_rank")).toBe(
      true,
    );
  });

  it("does not flag bar-native signal ids", () => {
    expect(isMdhCollapseSignal("c21_fund_value_mom_agree")).toBe(false);
    expect(isMdhCollapseSignal("nky_vol:nky_vol_abs_level")).toBe(false);
  });
});

describe("isPathCollapsedRow", () => {
  it("drops unique period-net collapse from survivors", () => {
    expect(
      isPathCollapsedRow({
        path_collapsed: true,
        status: "path_collapsed",
        signal_id: "c21_lite_fallback_mdh:event_calendar_gate",
        skip_reason: "unique_unsupported_on_period_net",
      }),
    ).toBe(true);
    expect(
      isPathCollapsedRow({
        signal_id: "c21_lite_fallback_mdh:surprise_xs_rank",
      }),
    ).toBe(true);
    expect(
      isPathCollapsedRow({ skip_reason: "unique_unsupported_on_period_net" }),
    ).toBe(true);
  });

  it("does not collapse a bar-native period-net row", () => {
    expect(
      isPathCollapsedRow({
        status: "ok",
        signal_id: "c21_fund_value_mom_agree",
      }),
    ).toBe(false);
    expect(
      isPathCollapsedRow({
        status: "ok",
        signal_id: "nky_vol:nky_vol_abs_level",
      }),
    ).toBe(false);
  });
});
