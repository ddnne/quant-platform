import { describe, expect, it } from "vitest";
import { parseAmounts, zeroCounters } from "./budget_do";

/**
 * parseAmounts pin. Missing or empty amounts are zero counters.
 * That is not budget consumption, not GO, and not Edge occupancy.
 */

const INTEGER_COUNTERS = [
  "experiment_plans",
  "generations",
  "model_calls",
  "input_tokens",
  "output_tokens",
  "paper_runs",
] as const;

describe("parseAmounts", () => {
  it("missing or empty amounts is zero counters, not a consume", () => {
    for (const raw of [undefined, null, {}]) {
      const got = parseAmounts(raw);
      expect(got.ok).toBe(true);
      if (got.ok) expect(got.amounts).toEqual(zeroCounters());
    }
  });

  it.each([
    { raw: [] as unknown, kind: "array" },
    { raw: "1", kind: "string" },
    { raw: 1, kind: "number" },
  ])("$kind is amounts must be an object", ({ raw }) => {
    const got = parseAmounts(raw);
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.error).toBe("amounts must be an object");
  });

  it("unknown key is fail-closed", () => {
    const got = parseAmounts({ tokens: 1 });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.error).toBe("unknown amount: tokens");
  });

  it("negative integer counters fail closed", () => {
    for (const name of INTEGER_COUNTERS) {
      const got = parseAmounts({ [name]: -1 });
      expect(got.ok).toBe(false);
      if (!got.ok) expect(got.error).toBe(`${name} must be a finite number >= 0`);
    }
  });

  it("non-integer counters fail closed", () => {
    for (const name of INTEGER_COUNTERS) {
      const got = parseAmounts({ [name]: 1.5 });
      expect(got.ok).toBe(false);
      if (!got.ok) expect(got.error).toBe(`${name} must be an integer >= 0`);
    }
  });

  it("negative cost_usd fails closed", () => {
    const got = parseAmounts({ cost_usd: -0.01 });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.error).toBe("cost_usd must be a finite number >= 0");
  });

  it("non-integer cost_usd is allowed", () => {
    const got = parseAmounts({ cost_usd: 0.01 });
    expect(got.ok).toBe(true);
    if (got.ok) {
      expect(got.amounts.cost_usd).toBe(0.01);
      expect(got.amounts).toEqual({ ...zeroCounters(), cost_usd: 0.01 });
    }
  });
});
