import type { Env } from "./types";

export type ResearchCapabilities = {
  data_ready: boolean;
  generation: boolean;
  mass_screen: boolean;
  promotion: boolean;
  paper_execution: boolean;
  reasons: string[];
  mass_research: string;
  phase7: string;
  ready_declared: boolean;
  operator_override: boolean;
  go: false;
  not_a_pass: true;
};

export function researchCapabilities(env: Env): ResearchCapabilities {
  const mass = String(env.MASS_RESEARCH || "NO-GO");
  const phase7 = String(env.PHASE7 || "OFF");
  const readyDeclared = String(env.READY_DECLARED || "false") === "true";
  const operationalGo = String(env.OPERATIONAL_GO || "false") === "true";
  const paper = String(env.CONTINUOUS_PAPER || "UNARMED");
  const tokenBound = Boolean(env.MASS_EVAL_TOKEN);
  const reasons: string[] = [];
  if (mass !== "GO") reasons.push("mass_research_no_go");
  if (!readyDeclared) reasons.push("ready_not_declared");
  reasons.push("verified_readiness_missing");
  if (!tokenBound) reasons.push("eval_token_unbound");
  if (phase7 !== "ON") reasons.push("phase7_off");
  if (!operationalGo) reasons.push("operational_go_false");
  if (paper !== "ARMED") reasons.push("paper_unarmed");
  return {
    data_ready: false,
    generation: false,
    mass_screen: false,
    promotion: false,
    paper_execution: false,
    reasons,
    mass_research: mass,
    phase7,
    ready_declared: readyDeclared,
    operator_override: false,
    go: false,
    not_a_pass: true,
  };
}

export function requireCapability(
  name: keyof Pick<
    ResearchCapabilities,
    "data_ready" | "generation" | "mass_screen" | "promotion" | "paper_execution"
  >,
  caps: ResearchCapabilities,
): { allowed: boolean; capability: string; reasons: string[] } {
  return {
    capability: name,
    allowed: Boolean(caps[name]),
    reasons: caps.reasons,
  };
}

/** nets_only needs env.NETS_ONLY=allow AND mass_screen. Default deny. */
export function netsOnlyGate(
  mode: string | undefined,
  env: { NETS_ONLY?: string },
  massScreenAllowed: boolean,
): { allowed: boolean; reasons: string[] } {
  if (mode !== "nets_only") return { allowed: true, reasons: [] };
  const reasons: string[] = [];
  if (String(env.NETS_ONLY ?? "deny") !== "allow") {
    reasons.push("nets_only_env_deny");
  }
  if (!massScreenAllowed) {
    reasons.push("mass_screen_capability_missing");
  }
  return { allowed: reasons.length === 0, reasons };
}
