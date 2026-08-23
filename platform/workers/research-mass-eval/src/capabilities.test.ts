import { describe, expect, it } from "vitest";
import { researchCapabilities, requireCapability } from "./capabilities";
import type { Env } from "./types";

const base = {
  STRUCTURED_BUCKET: {} as Env["STRUCTURED_BUCKET"],
  MASS_RESEARCH: "NO-GO",
  PHASE7: "OFF",
  READY_DECLARED: "false",
  OPERATIONAL_GO: "false",
  CONTINUOUS_PAPER: "UNARMED",
} as Env;

describe("researchCapabilities deny-by-default", () => {
  it("grants nothing without verified readiness", () => {
    const caps = researchCapabilities(base);
    expect(caps.mass_screen).toBe(false);
    expect(caps.generation).toBe(false);
    expect(caps.data_ready).toBe(false);
    expect(caps.promotion).toBe(false);
    expect(caps.paper_execution).toBe(false);
    expect(caps.reasons).toContain("mass_research_no_go");
    expect(caps.reasons).toContain("verified_readiness_missing");
    expect(requireCapability("mass_screen", caps).allowed).toBe(false);
  });
});
