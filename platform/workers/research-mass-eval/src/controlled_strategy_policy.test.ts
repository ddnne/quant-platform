import { describe, expect, it } from "vitest";
import {
  CONTROLLED_STRATEGY_FAMILIES,
  classifyControlledStrategy,
} from "./controlled_strategy_policy";

describe("controlled strategy policy", () => {
  it("contains exactly the governed four strategy ids", () => {
    expect(Object.keys(CONTROLLED_STRATEGY_FAMILIES).sort()).toEqual(
      [
        "cross_section_hold_10",
        "fundamentals_hold_10",
        "paper_event_post_hold5_disclosure_proxy",
        "paper_mdh_hold10_momentum_topk",
      ].sort(),
    );
  });

  it("classifies the four strategies without consulting catalog membership", () => {
    expect(
      classifyControlledStrategy({ logic_id: "paper_mdh_hold10_momentum_topk" }),
    ).toMatchObject({ ok: true, kind: "mdh", family_id: "multi_day_hold" });
    expect(
      classifyControlledStrategy({ logic_id: "cross_section_hold_10" }),
    ).toMatchObject({
      ok: true,
      kind: "cross_section",
      family_id: "cross_section_relative",
    });
    expect(
      classifyControlledStrategy({
        logic_id: "paper_event_post_hold5_disclosure_proxy",
      }),
    ).toMatchObject({ ok: true, kind: "event", family_id: "event_post" });
    expect(
      classifyControlledStrategy({ logic_id: "fundamentals_hold_10" }),
    ).toMatchObject({
      ok: true,
      kind: "fundamentals",
      family_id: "fundamentals_price",
    });
  });

  it("fails closed for legacy ids, family substitution, and catalog gates", () => {
    expect(
      classifyControlledStrategy({ logic_id: "event_cheap_iv_cheap_pb" }),
    ).toEqual({ ok: false, reason: "unsupported_strategy" });
    expect(
      classifyControlledStrategy({
        logic_id: "cross_section_hold_10",
        family_id: "event_post",
      }),
    ).toEqual({ ok: false, reason: "strategy_family_mismatch" });
    expect(
      classifyControlledStrategy({
        logic_id: "fundamentals_hold_10",
        params: { gates: ["cheap_pb"] },
      }),
    ).toEqual({ ok: false, reason: "legacy_catalog_gates_forbidden" });
    expect(
      classifyControlledStrategy({
        logic_id: "cross_section_hold_10",
        params: { cs_gate: "margin_up" },
      }),
    ).toEqual({ ok: false, reason: "legacy_catalog_gates_forbidden" });
  });
});
