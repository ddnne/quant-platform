import { describe, expect, it } from "vitest";
import { authorized } from "./authorized";

const TOKEN = "jq-test-proxy-token-not-for-live";

function req(
  headers: HeadersInit = {},
  url = "https://ingestion-secrets.test/v1/proxy/jquants",
): Request {
  return new Request(url, { headers });
}

describe("authorized", () => {
  it("unbound expected is false", async () => {
    expect(
      await authorized(req({ "X-Ingestion-Token": TOKEN }), undefined),
    ).toBe(false);
    expect(await authorized(req({ "X-Ingestion-Token": TOKEN }), "")).toBe(
      false,
    );
  });

  it("matching header is true", async () => {
    expect(
      await authorized(req({ "X-Ingestion-Token": TOKEN }), TOKEN),
    ).toBe(true);
  });

  it("query token only is false", async () => {
    const request = req(
      {},
      `https://ingestion-secrets.test/v1/proxy/jquants?token=${encodeURIComponent(TOKEN)}`,
    );
    expect(await authorized(request, TOKEN)).toBe(false);
  });

  it("wrong header is false", async () => {
    expect(
      await authorized(req({ "X-Ingestion-Token": "wrong-token" }), TOKEN),
    ).toBe(false);
  });
});
