import { describe, expect, it } from "vitest";
import { authorized } from "./authorized";

describe("authorized X-Gateway-Token only", () => {
  const GATEWAY_TOKEN = "gateway-secret";

  it("denies unbound GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": GATEWAY_TOKEN },
    });
    expect(await authorized(req, {})).toBe(false);
  });

  it("accepts X-Gateway-Token matching GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": GATEWAY_TOKEN },
    });
    expect(await authorized(req, { GATEWAY_TOKEN })).toBe(true);
  });

  it("does not read query token", async () => {
    const req = new Request(`https://gw.test/v1/complete?token=${GATEWAY_TOKEN}`, {
      method: "POST",
    });
    expect(await authorized(req, { GATEWAY_TOKEN })).toBe(false);
  });

  it("does not accept X-Mass-Eval-Token", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Mass-Eval-Token": GATEWAY_TOKEN },
    });
    expect(await authorized(req, { GATEWAY_TOKEN })).toBe(false);
  });
});
