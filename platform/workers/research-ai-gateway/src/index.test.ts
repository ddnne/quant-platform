import { describe, expect, it } from "vitest";
import { authorized, type GatewayEnv } from "./index";

describe("authorized token separation", () => {
  const env: GatewayEnv = {
    GATEWAY_TOKEN: "gateway-secret",
    MASS_EVAL_TOKEN: "mass-secret",
  };

  it("accepts X-Gateway-Token matching GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": "gateway-secret" },
    });
    expect(await authorized(req, env)).toBe(true);
  });

  it("does not accept X-Mass-Eval-Token as GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Mass-Eval-Token": "gateway-secret" },
    });
    expect(await authorized(req, env)).toBe(false);
  });

  it("does not treat MASS_EVAL_TOKEN as GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": "mass-secret" },
    });
    expect(await authorized(req, env)).toBe(false);
  });

  it("denies unbound GATEWAY_TOKEN", async () => {
    const req = new Request("https://gw.test/v1/complete", {
      headers: { "X-Gateway-Token": "gateway-secret" },
    });
    expect(await authorized(req, { MASS_EVAL_TOKEN: "mass-secret" })).toBe(false);
  });
});
