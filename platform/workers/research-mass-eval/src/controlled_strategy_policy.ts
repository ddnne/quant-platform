import type { LogicSpec } from "./types";

/**
 * Closed daily-path policy for the four governed Pilot StrategySpecs.
 *
 * This intentionally does not contain the retired 2,254-row catalog or infer
 * legacy catalog membership from prefixes.  A caller must name one of the
 * exact governed strategies; a conflicting family or catalog-style gates fail
 * closed before any panel is evaluated.
 */
export const CONTROLLED_STRATEGY_FAMILIES = {
  paper_mdh_hold10_momentum_topk: "multi_day_hold",
  cross_section_hold_10: "cross_section_relative",
  paper_event_post_hold5_disclosure_proxy: "event_post",
  fundamentals_hold_10: "fundamentals_price",
} as const;

export type ControlledStrategyId = keyof typeof CONTROLLED_STRATEGY_FAMILIES;
export type ControlledStrategyFamily =
  (typeof CONTROLLED_STRATEGY_FAMILIES)[ControlledStrategyId];
export type ControlledStrategyKind = "mdh" | "cross_section" | "event" | "fundamentals";

export type ControlledStrategyClassification =
  | {
      ok: true;
      logic_id: ControlledStrategyId;
      family_id: ControlledStrategyFamily;
      kind: ControlledStrategyKind;
    }
  | {
      ok: false;
      reason:
        | "unsupported_strategy"
        | "strategy_family_mismatch"
        | "legacy_catalog_gates_forbidden";
    };

function hasLegacyCatalogGates(params: Record<string, unknown>): boolean {
  const gates = params.gates;
  if (Array.isArray(gates) && gates.some((gate) => String(gate).trim())) return true;
  if (typeof gates === "string" && gates.trim() && gates.trim() !== "None") return true;
  const csGate = params.cs_gate;
  return (
    csGate !== undefined &&
    csGate !== null &&
    String(csGate).trim() !== "" &&
    String(csGate).trim() !== "None"
  );
}

function kindForFamily(family: ControlledStrategyFamily): ControlledStrategyKind {
  if (family === "multi_day_hold") return "mdh";
  if (family === "cross_section_relative") return "cross_section";
  if (family === "event_post") return "event";
  return "fundamentals";
}

export function classifyControlledStrategy(
  logic: LogicSpec,
): ControlledStrategyClassification {
  const logicId = String(logic.logic_id || "").trim();
  if (!Object.prototype.hasOwnProperty.call(CONTROLLED_STRATEGY_FAMILIES, logicId)) {
    return { ok: false, reason: "unsupported_strategy" };
  }
  const id = logicId as ControlledStrategyId;
  const expectedFamily = CONTROLLED_STRATEGY_FAMILIES[id];
  const suppliedFamily = String(logic.family_id || "").trim();
  if (suppliedFamily && suppliedFamily !== expectedFamily) {
    return { ok: false, reason: "strategy_family_mismatch" };
  }
  if (hasLegacyCatalogGates(logic.params || {})) {
    return { ok: false, reason: "legacy_catalog_gates_forbidden" };
  }
  return {
    ok: true,
    logic_id: id,
    family_id: expectedFamily,
    kind: kindForFamily(expectedFamily),
  };
}
