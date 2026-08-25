import { describe, expect, it } from "vitest";
import { ingestionTokenMatches } from "./ingestion_token";

const TOKEN = "premium-test-run-token-do-not-leak";

function req(
  headers: HeadersInit = {},
  url = "https://ingestion-premium.test/v1/ops",
): Request {
  return new Request(url, { headers });
}

describe("ingestionTokenMatches", () => {
  it("unbound expected is false", async () => {
    expect(
      await ingestionTokenMatches(req({ "X-Ingestion-Token": TOKEN }), undefined),
    ).toBe(false);
  });

  it("matching header is true", async () => {
    expect(
      await ingestionTokenMatches(req({ "X-Ingestion-Token": TOKEN }), TOKEN),
    ).toBe(true);
  });

  it("wrong header is false", async () => {
    expect(
      await ingestionTokenMatches(
        req({ "X-Ingestion-Token": "wrong-token" }),
        TOKEN,
      ),
    ).toBe(false);
  });

  it("query token is ignored even when it matches", async () => {
    const request = req(
      {},
      `https://ingestion-premium.test/v1/ops?token=${encodeURIComponent(TOKEN)}`,
    );
    expect(await ingestionTokenMatches(request, TOKEN)).toBe(false);
  });
});
