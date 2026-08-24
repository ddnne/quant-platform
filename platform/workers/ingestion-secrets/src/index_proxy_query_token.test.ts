import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "./index";

const API_KEY = "jq-test-api-key-not-for-live";
const PROXY_TOKEN = "jq-test-proxy-token-not-for-live";
const UPSTREAM_BODY = "upstream-streamed-body";

const env: Env = {
  JQUANTS_API_KEY: API_KEY,
  JQUANTS_PROXY_TOKEN: PROXY_TOKEN,
};

function stubUpstream() {
  const fetchImpl = vi.fn(async () => new Response(UPSTREAM_BODY, { status: 200 }));
  globalThis.fetch = fetchImpl as typeof fetch;
  return fetchImpl;
}

describe("ingestion-secrets jquants proxy ignores query token", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("POST /v1/proxy/jquants with only matching query token and no header is 401 and does not call upstream", async () => {
    const fetchImpl = stubUpstream();
    const res = await worker.fetch(
      new Request(
        `https://ingestion-secrets.test/v1/proxy/jquants?token=${encodeURIComponent(PROXY_TOKEN)}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ path: "/v2/equities/master", query: {} }),
        },
      ),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain(API_KEY);
    expect(body).not.toContain(PROXY_TOKEN);
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain("READY");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
