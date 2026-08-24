import type { Env } from "./types";

export function freezePayload(env: Env) {
  return {
    mass_research: env.MASS_RESEARCH || "NO-GO",
    phase7: env.PHASE7 || "OFF",
    ready_declared: String(env.READY_DECLARED || "false") === "true",
    operational_go: String(env.OPERATIONAL_GO || "false") === "true",
    continuous_paper: env.CONTINUOUS_PAPER || "UNARMED",
    frozen_defaults_retuned: false,
    connected_to_ready: false,
    connected_to_mass: false,
  };
}
