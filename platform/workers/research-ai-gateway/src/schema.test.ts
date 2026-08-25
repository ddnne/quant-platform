import { describe, expect, it } from "vitest";
import pricingPolicyDocument from "../../../../specs/policy/ai_gateway_pricing_policy.json";
import {
  ALLOWED_MODELS,
  decodeGatewayRequest,
  decodeTypedArtifact,
  estimateCostUsd,
  MAX_GATEWAY_INPUT_TOKENS,
  MAX_GATEWAY_MESSAGES,
  MAX_GATEWAY_PROMPT_UTF8_BYTES,
  parseModelJson,
  providerInputBounds,
} from "./schema";
import { AI_GATEWAY_PRICING_POLICY_DIGEST } from "./pricing_policy";
import { sha256Hex } from "./sha256";

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

const base = {
  model: "@cf/meta/llama-3.1-8b-instruct-fp8",
  messages: [{ role: "user", content: "hi" }],
  max_tokens: 16,
  budget_id: "gw-budget-1",
};

describe("decodeGatewayRequest", () => {
  it("accepts a strict body", () => {
    const got = decodeGatewayRequest(base);
    expect(got.ok).toBe(true);
  });

  it("rejects unknown fields", () => {
    const got = decodeGatewayRequest({ ...base, extra: 1 });
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.error).toContain("unknown field");
  });

  it("rejects disallowed models", () => {
    const got = decodeGatewayRequest({ ...base, model: "gpt-4o" });
    expect(got.ok).toBe(false);
  });

  it("rejects oversize max_tokens", () => {
    const got = decodeGatewayRequest({ ...base, max_tokens: 9999 });
    expect(got.ok).toBe(false);
  });

  it("rejects message count, UTF-8 bytes, and token upper bounds before provider use", () => {
    const tooMany = decodeGatewayRequest({
      ...base,
      messages: Array.from({ length: MAX_GATEWAY_MESSAGES + 1 }, () => ({
        role: "user",
        content: "x",
      })),
    });
    expect(tooMany).toMatchObject({
      ok: false,
      error: expect.stringContaining("messages[] exceeds hard limit"),
    });

    const tooManyBytes = decodeGatewayRequest({
      ...base,
      messages: [{ role: "user", content: "x".repeat(MAX_GATEWAY_PROMPT_UTF8_BYTES + 1) }],
    });
    expect(tooManyBytes).toMatchObject({
      ok: false,
      error: expect.stringContaining("UTF-8 bytes exceed hard limit"),
    });

    const tokenHeavyButByteBounded = "x".repeat(
      MAX_GATEWAY_PROMPT_UTF8_BYTES - 1_000,
    );
    const bounds = providerInputBounds([{ role: "user", content: tokenHeavyButByteBounded }]);
    expect(bounds.utf8_bytes).toBeLessThanOrEqual(MAX_GATEWAY_PROMPT_UTF8_BYTES);
    expect(bounds.token_upper_bound).toBeGreaterThan(MAX_GATEWAY_INPUT_TOKENS);
    const tooManyTokens = decodeGatewayRequest({
      ...base,
      messages: [{ role: "user", content: tokenHeavyButByteBounded }],
    });
    expect(tooManyTokens).toMatchObject({
      ok: false,
      error: expect.stringContaining("token upper bound exceeds hard limit"),
    });
  });

  it("refuses missing budget_id", () => {
    const { budget_id: _drop, ...rest } = base;
    const got = decodeGatewayRequest(rest);
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.error).toContain("budget_id required");
  });

  it("validates optional experiment_id / ready_snapshot_id / expected_schema", () => {
    const ok = decodeGatewayRequest({
      ...base,
      experiment_id: "exp-1",
      ready_snapshot_id: "snap-1",
      expected_schema: "Insight",
    });
    expect(ok.ok).toBe(true);
    const badSchema = decodeGatewayRequest({ ...base, expected_schema: "RawText" });
    expect(badSchema.ok).toBe(false);
    const badReady = decodeGatewayRequest({ ...base, ready_snapshot_id: 1 });
    expect(badReady.ok).toBe(false);
    const badExp = decodeGatewayRequest({ ...base, experiment_id: "" });
    expect(badExp.ok).toBe(false);
  });
});

describe("decodeTypedArtifact", () => {
  it("decodes Insight and rejects unknown fields", () => {
    const ok = decodeTypedArtifact(
      {
        role: "quant",
        task: "t",
        summary: "x",
        schema_version: "insight/v1",
      },
      "Insight",
    );
    expect(ok.ok).toBe(true);
    if (ok.ok) {
      expect(ok.value.schema_name).toBe("Insight");
      expect(ok.value.schema_version).toBe("insight/v1");
    }
    const extra = decodeTypedArtifact(
      {
        role: "quant",
        task: "t",
        summary: "x",
        schema_version: "insight/v1",
        smuggled: true,
      },
      "Insight",
    );
    expect(extra.ok).toBe(false);
    if (!extra.ok) {
      expect(extra.error).toContain("unknown field");
      expect(extra).not.toHaveProperty("text");
      expect(extra).not.toHaveProperty("artifact");
    }
  });

  it("rejects banned code fields", () => {
    const got = decodeTypedArtifact(
      {
        role: "quant",
        task: "t",
        summary: "x",
        schema_version: "insight/v1",
        code: "print(1)",
      },
      "Insight",
    );
    expect(got.ok).toBe(false);
    if (!got.ok) expect(got.error).toContain("banned");
  });

  it("fails closed without expected_schema or versioned output", () => {
    const got = decodeTypedArtifact({ role: "quant", task: "t", summary: "x" });
    expect(got.ok).toBe(false);
  });

  it("decodes ThesisProposalList from a JSON array", () => {
    const got = decodeTypedArtifact(
      [
        {
          thesis: "PEAD when liq high",
          signal_definition: "AND(liq_high, eq_ar_high) PIT",
          position_rule: "event-hold",
          datasets: ["equities_bars_daily"],
          gates: ["liq_high", "eq_ar_high"],
        },
      ],
      "ThesisProposalList",
    );
    expect(got.ok).toBe(true);
    if (got.ok) {
      expect(got.value.schema_version).toBe("thesis-proposal/v1");
      expect(Array.isArray(got.value.artifact.proposals)).toBe(true);
    }
  });

  it("rejects StrategySpec unknown fields", () => {
    const got = decodeTypedArtifact(
      {
        version: "strategy-spec/v2",
        strategy_id: "agent_momentum_top_k",
        rebalance: "daily",
        rationale: "x",
        rule: {
          type: "top_k",
          feature: { id: "momentum_n", version: "1.0.0", params: { n: 5 } },
          k: 1,
        },
        code: "os.system('x')",
      },
      "StrategySpec",
    );
    expect(got.ok).toBe(false);
  });
});

describe("parseModelJson", () => {
  it("does not recover a JSON substring from prose", () => {
    const got = parseModelJson('sure, here: {"role":"q"} thanks');
    expect(got.ok).toBe(false);
  });

  it("accepts a whole-document fence", () => {
    const got = parseModelJson("```json\n{\"role\":\"q\"}\n```");
    expect(got.ok).toBe(true);
  });
});

describe("estimateCostUsd", () => {
  it("uses the official input/output rates independently", () => {
    expect(estimateCostUsd(ALLOWED_MODELS[0], 1_000_000, 0)).toBe(0.293);
    expect(estimateCostUsd(ALLOWED_MODELS[0], 0, 1_000_000)).toBe(2.253);
    expect(estimateCostUsd(ALLOWED_MODELS[1], 1_000_000, 0)).toBe(0.06);
    expect(estimateCostUsd(ALLOWED_MODELS[1], 0, 1_000_000)).toBe(0.4);
    expect(estimateCostUsd(ALLOWED_MODELS[2], 1_000_000, 0)).toBe(0.152);
    expect(estimateCostUsd(ALLOWED_MODELS[2], 0, 1_000_000)).toBe(0.287);
  });

  it("has one canonical price for every allowed model", () => {
    expect(pricingPolicyDocument.policy.model_rates.map(({ model }) => model).sort()).toEqual(
      [...ALLOWED_MODELS].sort(),
    );
  });

  it("is bound to the canonical policy payload digest", async () => {
    const digest = `sha256:${await sha256Hex(canonicalJson(pricingPolicyDocument.policy))}`;
    expect(digest).toBe(pricingPolicyDocument.policy_digest);
    expect(digest).toBe(AI_GATEWAY_PRICING_POLICY_DIGEST);
  });
});
