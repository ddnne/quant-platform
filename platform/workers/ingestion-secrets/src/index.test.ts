import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "./index";

const API_KEY = "jq-test-api-key-not-for-live";
const PROXY_TOKEN = "jq-test-proxy-token-not-for-live";
const UPSTREAM_BODY = "upstream-streamed-body";

const env: Env = {
  JQUANTS_API_KEY: API_KEY,
  JQUANTS_PROXY_TOKEN: PROXY_TOKEN,
};

const AUTH_HEADERS = { "X-Ingestion-Token": PROXY_TOKEN };
const PREMIUM_PATH = "/v2/equities/master";
const ADDON_PATH = "/v2/td/list";
const PREFIX_ONLY_PATH = "/v2/not-a-contract-path";

function proxyRequest(
  headers: HeadersInit = {},
  body: Record<string, unknown> = { path: "/v1/listed/info", query: {} },
): Request {
  return new Request("https://ingestion-secrets.test/v1/proxy/jquants", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

function stubUpstream() {
  const fetchImpl = vi.fn(async () => new Response(UPSTREAM_BODY, { status: 200 }));
  globalThis.fetch = fetchImpl as typeof fetch;
  return fetchImpl;
}

describe("ingestion-secrets boundary", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

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

  it("does not call upstream when the token is missing or wrong", async () => {
    const fetchImpl = stubUpstream();
    const missing = await worker.fetch(
      proxyRequest({}, { path: PREMIUM_PATH, query: {} }),
      env,
    );
    const wrong = await worker.fetch(
      proxyRequest(
        { "X-Ingestion-Token": "wrong-token" },
        { path: PREMIUM_PATH, query: {} },
      ),
      env,
    );
    expect(missing.status).toBe(401);
    expect(wrong.status).toBe(401);
    expect(await missing.json()).toEqual({ error: "unauthorized" });
    expect(await wrong.json()).toEqual({ error: "unauthorized" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("denies an authenticated path that is not on the contract whitelist", async () => {
    const fetchImpl = stubUpstream();
    const res = await worker.fetch(
      proxyRequest(AUTH_HEADERS, { path: PREFIX_ONLY_PATH, query: {} }),
      env,
    );
    expect(res.status).not.toBe(200);
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({
      error: "path is not allowed by the J-Quants proxy contracts",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects authenticated body.method POST/PUT without calling upstream", async () => {
    const fetchImpl = stubUpstream();
    for (const method of ["POST", "PUT"]) {
      const res = await worker.fetch(
        proxyRequest(AUTH_HEADERS, { path: PREMIUM_PATH, method, query: {} }),
        env,
      );
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({
        error: "body requires path, optional method=GET, and string query values",
      });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("forwards authenticated GET on contract paths as upstream GET with streamed body", async () => {
    const fetchImpl = stubUpstream();
    for (const path of [PREMIUM_PATH, ADDON_PATH]) {
      fetchImpl.mockClear();
      const res = await worker.fetch(
        proxyRequest(AUTH_HEADERS, {
          path,
          method: "GET",
          query: { code: "86970" },
        }),
        env,
      );
      expect(res.status).toBe(200);
      expect(await res.text()).toBe(UPSTREAM_BODY);
      expect(fetchImpl).toHaveBeenCalledOnce();
      expect(fetchImpl).toHaveBeenCalledWith(
        `https://api.jquants.com${path}?code=86970`,
        {
          method: "GET",
          headers: { "x-api-key": API_KEY },
          redirect: "manual",
        },
      );
    }
  });
});
