import { describe, expect, it } from "vitest";
import { isMdhCollapseSignal } from "./mdh_collapse";

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
