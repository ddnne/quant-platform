import { describe, expect, it } from "vitest";
import { isPathBroken } from "./path_broken";

describe("isPathBroken", () => {
  it("treats generic CS/MDH fallback as broken", () => {
    expect(isPathBroken("cs_generic")).toBe(true);
    expect(isPathBroken("mdh_generic")).toBe(true);
    expect(isPathBroken("unknown")).toBe(true);
    expect(isPathBroken("eventHeld", "path_broken")).toBe(true);
    expect(isPathBroken("nky_vol:nky_vol_abs_level", "mdh_empty_sidecar")).toBe(
      true,
    );
  });

  it("does not mark a native path complete-broken", () => {
    expect(isPathBroken("nky_vol:nky_vol_abs_level")).toBe(false);
    expect(isPathBroken("eventHeld")).toBe(false);
    expect(isPathBroken("gated_cs")).toBe(false);
  });
});
