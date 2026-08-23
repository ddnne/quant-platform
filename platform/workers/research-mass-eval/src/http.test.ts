import { describe, expect, it } from "vitest";
import { authorized } from "./http";

function req(headers: Record<string, string>): Request {
  return new Request("https://example.test/v1/daily-path", { method: "POST", headers });
}

describe("authorized fail-closed", () => {
  it("denies when expected token is missing", async () => {
    expect(await authorized(req({ "X-Mass-Eval-Token": "x" }), undefined)).toBe(
      false,
    );
    expect(await authorized(req({}), "")).toBe(false);
  });

  it("denies when header missing", async () => {
    expect(await authorized(req({}), "secret")).toBe(false);
  });

  it("accepts matching token", async () => {
    expect(await authorized(req({ "X-Mass-Eval-Token": "secret" }), "secret")).toBe(
      true,
    );
  });

  it("rejects mismatched token", async () => {
    expect(await authorized(req({ "X-Mass-Eval-Token": "nope" }), "secret")).toBe(
      false,
    );
  });
});

import { sha256Hex } from "./http";

describe("sha256Hex", () => {
  it("is stable for the same bytes", async () => {
    const enc = new TextEncoder();
    const a = await sha256Hex(enc.encode("abc"));
    const b = await sha256Hex(enc.encode("abc"));
    expect(a).toBe(b);
    expect(a).toHaveLength(64);
  });
});
