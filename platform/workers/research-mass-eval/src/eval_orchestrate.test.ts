import { describe, expect, it } from "vitest";
import {
  evaluateLogicAcrossPeriods,
  rankSurvivors,
} from "./eval_orchestrate";
import { tStatVsZeroDetail } from "./metrics";
import type { LogicEvalResult, LogicSpec } from "./types";

function logic(partial: Partial<LogicSpec> & Pick<LogicSpec, "logic_id">): LogicSpec {
  return { family_id: "multi_day_hold", ...partial };
}

/** Two finite positive nets; |t| is not a small-n low-variance artifact. */
const SPREAD_NETS = [0.02, 0.01];
/** W95-scale near-identical 2-period nets. */
const LOW_VAR_NETS = [0.008229283197313041, 0.008337431738535494];

function expectFreezeNoGo(result: LogicEvalResult) {
  expect(result.mass_research).toBe("NO-GO");
  expect(result.phase7).toBe("OFF");
  expect(result.ready_declared).toBe(false);
  expect(result.operational_go).toBe(false);
  expect(result.continuous_paper).toBe("UNARMED");
  expect(result.frozen_defaults_retuned).toBe(false);
}

describe("evaluateLogicAcrossPeriods period_nets", () => {
  it("spreads freezeFields and does not treat a period-net screen as a pass", () => {
    const result = evaluateLogicAcrossPeriods(
      logic({ logic_id: "spread_nets", period_nets: SPREAD_NETS }),
      [],
    );
    expect(result.t_stat_reason).not.toBe("low_variance_artifact");
    expect(result.low_variance_artifact).toBe(false);
    expectFreezeNoGo(result);
    expect(result.screen.n_survivors_are_not_a_pass).toBe(true);
    expect(result.screen.daily_path_complete).toBe(false);
    expect(result.screen.candidate_grade).toBe(false);
  });

  it("rejects a single period_net as insufficient_periods with freeze still NO-GO", () => {
    const result = evaluateLogicAcrossPeriods(
      logic({ logic_id: "one_period", period_nets: [0.02] }),
      [],
    );
    expect(result.screen.survived).toBe(false);
    expect(result.screen.reject_reasons).toContain("insufficient_periods");
    expectFreezeNoGo(result);
    expect(result.screen.n_survivors_are_not_a_pass).toBe(true);
    expect(result.screen.candidate_grade).toBe(false);
  });

  it("marks a null period_net data_missing and counts ok rows separately", () => {
    const result = evaluateLogicAcrossPeriods(
      logic({
        logic_id: "null_net",
        period_nets: [0.02, null, 0.01],
      }),
      [],
    );
    expect(result.n_periods_total).toBe(3);
    expect(result.n_periods_ok).toBe(2);
    expect(result.period_rows.map((r) => r.status)).toEqual([
      "ok",
      "data_missing",
      "ok",
    ]);
    expect(result.period_rows[1]?.net_one_way_mean_active).toBeNull();
  });

  it("rejects nearly identical small-n nets as inflated_t_low_variance", () => {
    expect(tStatVsZeroDetail(LOW_VAR_NETS).reason).toBe("low_variance_artifact");
    const result = evaluateLogicAcrossPeriods(
      logic({ logic_id: "low_var", period_nets: LOW_VAR_NETS }),
      [],
    );
    expect(result.t_stat_reason).toBe("low_variance_artifact");
    expect(result.low_variance_artifact).toBe(true);
    expect(result.screen.survived).toBe(false);
    expect(result.screen.reject_reasons).toContain("inflated_t_low_variance");
    expectFreezeNoGo(result);
  });
});

describe("rankSurvivors", () => {
  it("sorts survivors by |t_stat| and does not treat rank as a pass", () => {
    const highT = evaluateLogicAcrossPeriods(
      logic({
        logic_id: "high_t",
        strategy_id: "high_t",
        period_nets: [0.03, 0.027],
      }),
      [],
    );
    const lowT = evaluateLogicAcrossPeriods(
      logic({
        logic_id: "low_t",
        strategy_id: "low_t",
        period_nets: SPREAD_NETS,
      }),
      [],
    );
    const rejected = evaluateLogicAcrossPeriods(
      logic({ logic_id: "one_period", period_nets: [0.02] }),
      [],
    );
    expect(highT.screen.survived).toBe(true);
    expect(lowT.screen.survived).toBe(true);
    expect(rejected.screen.survived).toBe(false);
    expect(Math.abs(highT.t_stat ?? 0)).toBeGreaterThan(Math.abs(lowT.t_stat ?? 0));

    const ranked = rankSurvivors([lowT, rejected, highT]);
    expect(ranked.map((r) => r.strategy_id)).toEqual(["high_t", "low_t"]);
    expect(ranked.map((r) => r.rank)).toEqual([1, 2]);
    for (const row of ranked) {
      expect(row.n_survivors_are_not_a_pass).toBe(true);
      expect(row.candidate_grade).toBe(false);
      expect(row.daily_path_complete).toBe(false);
    }
  });
});
