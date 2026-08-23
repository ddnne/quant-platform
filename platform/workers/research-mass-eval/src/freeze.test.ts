import { describe, expect, it } from "vitest";
import { freezePayload } from "./freeze";
import type { Env } from "./types";

describe("freezePayload deny-by-default", () => {
  const expected = {
    mass_research: "NO-GO",
    phase7: "OFF",
    ready_declared: false,
    operational_go: false,
    continuous_paper: "UNARMED",
    frozen_defaults_retuned: false,
    connected_to_ready: false,
    connected_to_mass: false,
  };

  it("returns frozen defaults for an empty env", () => {
    expect(freezePayload({} as Env)).toEqual(expected);
  });

  it("returns frozen defaults for deny-by-default env", () => {
    expect(
      freezePayload({
        MASS_RESEARCH: "NO-GO",
        PHASE7: "OFF",
        READY_DECLARED: "false",
        OPERATIONAL_GO: "false",
        CONTINUOUS_PAPER: "UNARMED",
      } as Env),
    ).toEqual(expected);
  });
});
