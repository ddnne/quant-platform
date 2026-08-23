import { describe, expect, it } from "vitest";
import { authorized } from "./authorized";

const TOKEN = "secret";

function req(
  headers: HeadersInit = {},
  url = "https://example.test/v1/mass-eval",
): Request {
  return new Request(url, { method: "POST", headers });
}

describe("authorized", () => {
  it("unbound expected is false", async () => {
    expect(
      await authorized(req({ "X-Mass-Eval-Token": TOKEN }), undefined),
    ).toBe(false);
    expect(await authorized(req({ "X-Mass-Eval-Token": TOKEN }), "")).toBe(
      false,
    );
  });

  it("matching X-Mass-Eval-Token is true", async () => {
    expect(
      await authorized(req({ "X-Mass-Eval-Token": TOKEN }), TOKEN),
    ).toBe(true);
  });

  it("matching X-Ingestion-Token is true", async () => {
    expect(
      await authorized(req({ "X-Ingestion-Token": TOKEN }), TOKEN),
    ).toBe(true);
  });

  it("query token only is false", async () => {
    const request = req(
      {},
      `https://example.test/v1/mass-eval?token=${encodeURIComponent(TOKEN)}`,
    );
    expect(await authorized(request, TOKEN)).toBe(false);
  });

  it("wrong header is false", async () => {
    expect(
      await authorized(req({ "X-Mass-Eval-Token": "wrong-token" }), TOKEN),
    ).toBe(false);
  });
});
