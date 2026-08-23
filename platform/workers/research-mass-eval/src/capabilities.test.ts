import { describe, expect, it } from "vitest";
import {
  netsOnlyGate,
  researchCapabilities,
  requireCapability,
} from "./capabilities";
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

describe("netsOnlyGate fail-closed", () => {
  it("does not apply to other modes", () => {
    expect(netsOnlyGate("synthetic", {}, true).allowed).toBe(true);
    expect(netsOnlyGate("r2_panels", { NETS_ONLY: "deny" }, true).allowed).toBe(
      true,
    );
  });

  it("denies nets_only by default even with capability", () => {
    expect(netsOnlyGate("nets_only", {}, true).allowed).toBe(false);
    expect(netsOnlyGate("nets_only", { NETS_ONLY: "deny" }, true).allowed).toBe(
      false,
    );
    expect(netsOnlyGate("nets_only", { NETS_ONLY: "ALLOW" }, true).allowed).toBe(
      false,
    );
    expect(netsOnlyGate("nets_only", { NETS_ONLY: "true" }, true).allowed).toBe(
      false,
    );
    expect(netsOnlyGate("nets_only", {}, true).reasons).toContain(
      "nets_only_env_deny",
    );
  });

  it("denies nets_only when env allows but capability is missing", () => {
    const gate = netsOnlyGate("nets_only", { NETS_ONLY: "allow" }, false);
    expect(gate.allowed).toBe(false);
    expect(gate.reasons).toContain("mass_screen_capability_missing");
  });

  it("allows nets_only only with explicit allow AND capability", () => {
    expect(netsOnlyGate("nets_only", { NETS_ONLY: "allow" }, true).allowed).toBe(
      true,
    );
  });
});
