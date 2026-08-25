import { describe, expect, it } from "vitest";
import { runProposeThesis } from "./propose_thesis";
import type { Env } from "./types";

const frozen = {
  STRUCTURED_BUCKET: {} as Env["STRUCTURED_BUCKET"],
  MASS_RESEARCH: "NO-GO",
  PHASE7: "OFF",
  READY_DECLARED: "false",
  OPERATIONAL_GO: "false",
  CONTINUOUS_PAPER: "UNARMED",
} as Env;

const tweakOnlyRow = {
  thesis: "window",
  signal_definition: "hold_days only",
  position_rule: "hold 15",
};

const windowTweakForbidden = {
  ok: false,
  error: "window_tweak_only_forbidden",
  auto_inject: false,
  go: false,
  not_a_pass: true,
};

async function withFetchForbidden<T>(fn: () => Promise<T>): Promise<T> {
  const orig = globalThis.fetch;
  const calls: unknown[] = [];
  globalThis.fetch = (async (...args: unknown[]) => {
    calls.push(args);
    throw new Error("fetch must not run");
  }) as typeof fetch;
  try {
    const out = await fn();
    expect(calls).toEqual([]);
    return out;
  } finally {
    globalThis.fetch = orig;
  }
}

describe("runProposeThesis window_tweak_only fail-closed", () => {
  it("rejects a window-tweak-only body without calling AI_GATEWAY", async () => {
    const env = { ...frozen } as Env;
    expect("AI_GATEWAY" in env).toBe(false);
    await withFetchForbidden(async () => {
      for (const body of [
        { ...tweakOnlyRow },
        { ...tweakOnlyRow, datasets: [] as string[] },
      ]) {
        const out = await runProposeThesis(env, body);
        expect(out).toEqual(windowTweakForbidden);
      }
    });
  });

  it("rejects body.proposals[0] tweak-only row without calling AI_GATEWAY", async () => {
    const env = { ...frozen } as Env;
    expect("AI_GATEWAY" in env).toBe(false);
    await withFetchForbidden(async () => {
      const out = await runProposeThesis(env, {
        proposals: [{ ...tweakOnlyRow, datasets: [] as string[] }],
      });
      expect(out).toEqual(windowTweakForbidden);
    });
  });

  it("does not treat a non-tweak body as window_tweak_only when AI_GATEWAY is unbound", async () => {
    const env = { ...frozen } as Env;
    expect("AI_GATEWAY" in env).toBe(false);
    await withFetchForbidden(async () => {
      for (const body of [
        {
          thesis: "liquidity-conditioned EqAR after disclosure",
          signal_definition: "AND(liq_high, eq_ar_high) PIT",
          position_rule: "event-hold surprise sign",
        },
        {
          thesis: "window factor",
          signal_definition: "hold_days only",
          position_rule: "hold 15",
        },
      ]) {
        const out = await runProposeThesis(env, body);
        expect(out.error).not.toBe("window_tweak_only_forbidden");
        expect(out.ok).toBe(false);
        expect(out.go).toBe(false);
        expect(out.not_a_pass).toBe(true);
        expect(out.auto_inject).toBe(false);
        expect(out.error).toBe("llm_failed");
        expect(String(out.llm_fallback_reason)).toMatch(/unbound|ai_gateway/i);
      }
    });
  });
});
