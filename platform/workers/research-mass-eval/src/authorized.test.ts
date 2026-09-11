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

  it("wrong nonempty X-Mass-Eval-Token does not fall back to X-Ingestion-Token", async () => {
    expect(
      await authorized(
        req({
          "X-Mass-Eval-Token": "wrong-token",
          "X-Ingestion-Token": TOKEN,
        }),
        TOKEN,
      ),
    ).toBe(false);
  });

  it("empty X-Mass-Eval-Token falls back to matching X-Ingestion-Token", async () => {
    expect(
      await authorized(
        req({
          "X-Mass-Eval-Token": "",
          "X-Ingestion-Token": TOKEN,
        }),
        TOKEN,
      ),
    ).toBe(true);
  });
});
