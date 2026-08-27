import { describe, expect, it } from "vitest";
import { completeViaGateway, hasAiGateway } from "./ai_gateway_client";
import type { Env } from "./types";

const body = {
  model: "test-model",
  messages: [{ role: "user", content: "ping" }],
  max_tokens: 8,
};

const frozen = {
  STRUCTURED_BUCKET: {} as Env["STRUCTURED_BUCKET"],
  MASS_RESEARCH: "NO-GO",
  PHASE7: "OFF",
  READY_DECLARED: "false",
  OPERATIONAL_GO: "false",
  CONTINUOUS_PAPER: "UNARMED",
} as Env;

type ClientEnv = Env;

function mockGateway(
  json: unknown,
  calls: unknown[],
): NonNullable<Env["AI_GATEWAY"]> {
  return {
    complete: async (input: unknown, options?: { idempotency_key?: string }) => {
      calls.push({ input, options });
      return { http_status: 200, body: json };
    },
  } as NonNullable<Env["AI_GATEWAY"]>;
}

describe("completeViaGateway unbound fail-closed", () => {
  it("returns ai_gateway_unbound when AI_GATEWAY is missing or undefined", async () => {
    const globalCalls: unknown[] = [];
    const orig = globalThis.fetch;
    globalThis.fetch = (async (...args: unknown[]) => {
      globalCalls.push(args);
      throw new Error("global fetch must not run");
    }) as typeof fetch;
    try {
      for (const env of [
        { ...frozen } as ClientEnv,
        { ...frozen, AI_GATEWAY: undefined } as ClientEnv,
      ]) {
        const out = await completeViaGateway(env, body);
        expect(out).toEqual({ ok: false, reason: "ai_gateway_unbound" });
      }
      expect(globalCalls).toEqual([]);
    } finally {
      globalThis.fetch = orig;
    }
  });

});

describe("completeViaGateway response contract", () => {
  it("rejects raw text even when ok:true", async () => {
    const calls: unknown[] = [];
    const env: ClientEnv = {
      ...frozen,
      AI_GATEWAY: mockGateway({ ok: true, text: "raw" }, calls),
    };
    const out = await completeViaGateway(env, body);
    expect(out).toEqual({ ok: false, reason: "gateway_raw_text_rejected" });
    expect(calls).toHaveLength(1);
  });

  it("echoes budget_id string without treating it as occupancy authority", async () => {
    const calls: unknown[] = [];
    const env: ClientEnv = {
      ...frozen,
      AI_GATEWAY: mockGateway(
        {
          ok: true,
          artifact: { kind: "thesis" },
          schema: "research_thesis",
          schema_version: "1",
          budget_id: "echo-not-a-reserve",
        },
        calls,
      ),
    };
    const out = await completeViaGateway(env, body);
    expect(out.ok).toBe(true);
    if (!out.ok) throw new Error("expected ok");
    expect(out.artifact).toEqual({ kind: "thesis" });
    expect(out.schema_name).toBe("research_thesis");
    expect(out.schema_version).toBe("1");
    // Echo only. A budget_id string is not occupancy / reserve authority.
    expect(out.budget_id).toBe("echo-not-a-reserve");
    expect(calls).toHaveLength(1);
  });

  it("returns gateway_budget_id_missing when budget_id is missing or empty", async () => {
    const basePayload = {
      ok: true as const,
      artifact: { kind: "thesis" },
      schema: "research_thesis",
      schema_version: "1",
    };
    for (const payload of [
      { ...basePayload },
      { ...basePayload, budget_id: "" },
    ]) {
      const calls: unknown[] = [];
      const env: ClientEnv = {
        ...frozen,
        AI_GATEWAY: mockGateway(payload, calls),
      };
      const out = await completeViaGateway(env, body);
      expect(out).toEqual({ ok: false, reason: "gateway_budget_id_missing" });
      expect(calls).toHaveLength(1);
    }
  });
});

describe("hasAiGateway", () => {
  it("is false when AI_GATEWAY is unbound and true when the object is present", () => {
    expect(hasAiGateway({ ...frozen })).toBe(false);
    expect(hasAiGateway({ ...frozen, AI_GATEWAY: undefined })).toBe(false);
    expect(
      hasAiGateway({
        ...frozen,
        AI_GATEWAY: mockGateway({ ok: true }, []),
      }),
    ).toBe(true);
  });
});
