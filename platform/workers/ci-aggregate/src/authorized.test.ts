import { describe, expect, it } from "vitest";
import { authorized } from "./authorized";

const TOKEN = "ci-aggregate-test-lane-token-do-not-leak";

function req(
  headers: HeadersInit = {},
  url = "https://ci-aggregate.test/v1/receipts",
): Request {
  return new Request(url, { headers });
}

describe("authorized", () => {
  it("unbound CI_LANE_TOKEN is false even with header", async () => {
    expect(
      await authorized(req({ "X-CI-Lane-Token": TOKEN }), {}),
    ).toBe(false);
    expect(
      await authorized(req({ "X-CI-Lane-Token": TOKEN }), { CI_LANE_TOKEN: "" }),
    ).toBe(false);
    expect(
      await authorized(req({ "X-CI-Lane-Token": TOKEN }), { CI_LANE_TOKEN: "   " }),
    ).toBe(false);
  });

  it("matching X-CI-Lane-Token is true", async () => {
    expect(
      await authorized(req({ "X-CI-Lane-Token": TOKEN }), {
        CI_LANE_TOKEN: TOKEN,
      }),
    ).toBe(true);
  });

  it("query token only is false", async () => {
    const request = req(
      {},
      `https://ci-aggregate.test/v1/receipts?token=${encodeURIComponent(TOKEN)}`,
    );
    expect(await authorized(request, { CI_LANE_TOKEN: TOKEN })).toBe(false);
  });

  it("mismatched header is false", async () => {
    expect(
      await authorized(req({ "X-CI-Lane-Token": "wrong-token" }), {
        CI_LANE_TOKEN: TOKEN,
      }),
    ).toBe(false);
  });
});
