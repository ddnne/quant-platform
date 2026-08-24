import { describe, expect, it } from "vitest";
import worker, { type Env } from "./index";

const API_KEY = "jq-test-api-key-not-for-live";
const PROXY_TOKEN = "jq-test-proxy-token-not-for-live";

const env: Env = {
  JQUANTS_API_KEY: API_KEY,
  JQUANTS_PROXY_TOKEN: PROXY_TOKEN,
};

function proxyRequest(headers: HeadersInit = {}): Request {
  return new Request("https://ingestion-secrets.test/v1/proxy/jquants", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify({ path: "/v1/listed/info", query: {} }),
  });
}

describe("ingestion-secrets boundary", () => {
  it("denies unauthenticated proxy requests", async () => {
    const res = await worker.fetch(proxyRequest(), env);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "unauthorized" });
  });

  it("does not leak secret values in responses", async () => {
    const responses = await Promise.all([
      worker.fetch(proxyRequest(), env),
      worker.fetch(proxyRequest({ "X-Ingestion-Token": "wrong-token" }), env),
      worker.fetch(new Request("https://ingestion-secrets.test/health"), env),
      worker.fetch(new Request("https://ingestion-secrets.test/missing"), env),
    ]);

    expect(responses.map((res) => res.status)).toEqual([401, 401, 200, 404]);

    for (const res of responses) {
      const body = await res.text();
      expect(body).not.toContain(API_KEY);
      expect(body).not.toContain(PROXY_TOKEN);
    }
  });
});
