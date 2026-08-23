import { describe, expect, it } from "vitest";
import { decodeGatewayRequest, estimateCostUsd } from "./schema";

describe("decodeGatewayRequest", () => {
  const base = {
    model: "@cf/meta/llama-3.1-8b-instruct-fp8",
    messages: [{ role: "user", content: "hi" }],
    max_tokens: 16,
  };

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
});

describe("estimateCostUsd", () => {
  it("is non-negative", () => {
    expect(estimateCostUsd("@cf/meta/llama-3.1-8b-instruct-fp8", 10, 10)).toBeGreaterThanOrEqual(
      0,
    );
  });
});
