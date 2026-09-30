/** Public dispatch only; actual receipt-product/D1 behavior lives in workerd tests. */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import worker, { type Env } from "./index";

const TOKEN = "premium-test-export-token-do-not-leak";

function noStorageEnv(token: string | undefined): Env {
  return new Proxy({} as Env, {
    get(_target, name) {
      if (name === "DATA_EXPORT_TOKEN") return token;
      throw new Error(`unexpected binding access: ${String(name)}`);
    },
  });
}

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("unexpected fetch"));
});
afterEach(() => vi.restoreAllMocks());

it("retired D1 exports/maintenance and unknown paths return 404 without storage or outbound IO", async () => {
  for (const path of ["export/d1", "export/changes", "export/unknown", "ops/archive-cold", "ops/prune-changelog"]) {
    const response = await worker.fetch(new Request(
      `https://ingestion-premium.test/v1/${path}`,
      { method: "POST", headers: { "X-Ingestion-Token": TOKEN } },
    ), noStorageEnv(TOKEN));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not found" });
  }
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it("receipt-product dispatch requires its header credential before storage access", async () => {
  for (const [bound, supplied] of [[TOKEN, ""], [TOKEN, "run-token"], [undefined, TOKEN]]) {
    const response = await worker.fetch(new Request(
      `https://ingestion-premium.test/v1/export/receipt-products?token=${TOKEN}`,
      { method: "POST", headers: { "X-Ingestion-Token": supplied ?? "" }, body: "{}" },
    ), noStorageEnv(bound));
    expect(response.status).toBe(401);
  }
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it("authorized receipt-product dispatch reaches the existing body decoder", async () => {
  const response = await worker.fetch(new Request(
    "https://ingestion-premium.test/v1/export/receipt-products",
    { method: "POST", headers: { "X-Ingestion-Token": TOKEN }, body: "{" },
  ), noStorageEnv(TOKEN));
  expect(response.status).toBe(400);
  expect(await response.json()).toEqual({ error: "invalid json" });
  expect(globalThis.fetch).not.toHaveBeenCalled();
});
