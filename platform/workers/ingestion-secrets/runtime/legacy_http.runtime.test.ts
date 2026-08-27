import { afterEach, describe, expect, it, vi } from "vitest";
import {
  handleHttpRequest,
  type LegacyHttpEnv,
} from "../src/legacy_http";

const API_KEY = "legacy-runtime-api-key-not-for-live";
const PROXY_TOKEN = "jq-runtime-proxy-token-not-for-live";
const originalFetch = globalThis.fetch;

function runtimeEnv(
  limit: (() => Promise<{ success: boolean }>) | null = async () => ({ success: true }),
): LegacyHttpEnv {
  return {
    JQUANTS_API_KEY: API_KEY,
    JQUANTS_PROXY_TOKEN: PROXY_TOKEN,
    ...(limit === null ? {} : {
      PROXY_RATE_LIMITER: { limit } as unknown as RateLimit,
    }),
  } as unknown as LegacyHttpEnv;
}

function proxyRequest(
  token: string | null,
  body: Record<string, unknown> = {
    path: "/v2/equities/master",
    method: "GET",
    query: { code: "86970" },
  },
  url = "https://ingestion-secrets.test/v1/proxy/jquants",
  method = "POST",
): Request {
  const headers = new Headers({ "content-type": "application/json" });
  if (token !== null) headers.set("x-ingestion-token", token);
  return new Request(url, {
    method,
    headers,
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("time-bounded legacy HTTP proxy in Workers runtime", () => {
  it("rejects missing, wrong, and query-only tokens before upstream fetch", async () => {
    const fetchMock = vi.fn(async () => new Response("should-not-run"));
    globalThis.fetch = fetchMock as typeof fetch;
    const requests = [
      proxyRequest(null),
      proxyRequest("wrong-token"),
      proxyRequest(null, undefined, `https://ingestion-secrets.test/v1/proxy/jquants?token=${PROXY_TOKEN}`),
    ];
    for (const request of requests) {
      const response = await handleHttpRequest(request, runtimeEnv());
      expect(response.status).toBe(401);
      expect(await response.json()).toEqual({ error: "unauthorized" });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("enforces method/body/path contracts and forwards only target-owned GET auth", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response("legacy-exact-body", {
        status: 200,
        headers: {
          "content-type": "application/json",
          "set-cookie": "upstream=forbidden",
          "x-api-key": "upstream-forbidden",
        },
      }));
    globalThis.fetch = fetchMock as typeof fetch;
    expect((await handleHttpRequest(
      proxyRequest(PROXY_TOKEN, undefined, undefined, "GET"),
      runtimeEnv(),
    )).status).toBe(405);
    expect((await handleHttpRequest(
      proxyRequest(PROXY_TOKEN, { path: "/v2/equities/master", method: "POST", query: {} }),
      runtimeEnv(),
    )).status).toBe(400);
    expect((await handleHttpRequest(
      proxyRequest(PROXY_TOKEN, { path: "/v2/not-a-contract", query: {} }),
      runtimeEnv(),
    )).status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();

    const response = await handleHttpRequest(proxyRequest(PROXY_TOKEN), runtimeEnv());
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("legacy-exact-body");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("x-api-key")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.jquants.com/v2/equities/master?code=86970",
      {
        method: "GET",
        headers: { "x-api-key": API_KEY },
        redirect: "manual",
      },
    );
  });

  it("fails closed when the rate-limit capability is missing, denies, or errors", async () => {
    const fetchMock = vi.fn(async () => new Response("should-not-run"));
    globalThis.fetch = fetchMock as typeof fetch;
    const missing = await handleHttpRequest(proxyRequest(PROXY_TOKEN), runtimeEnv(null));
    expect(missing.status).toBe(503);
    const denied = await handleHttpRequest(
      proxyRequest(PROXY_TOKEN),
      runtimeEnv(async () => ({ success: false })),
    );
    expect(denied.status).toBe(429);
    const errored = await handleHttpRequest(
      proxyRequest(PROXY_TOKEN),
      runtimeEnv(async () => { throw new Error("limiter unavailable"); }),
    );
    expect(errored.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not leak credentials or upstream headers on provider failure/redirect", async () => {
    const throwing = vi.fn(async () => {
      throw new Error(`provider ${API_KEY} ${PROXY_TOKEN}`);
    });
    globalThis.fetch = throwing as typeof fetch;
    const failed = await handleHttpRequest(proxyRequest(PROXY_TOKEN), runtimeEnv());
    const rendered = `${await failed.text()} ${JSON.stringify([...failed.headers])}`;
    expect(failed.status).toBe(502);
    expect(rendered).not.toContain(API_KEY);
    expect(rendered).not.toContain(PROXY_TOKEN);

    globalThis.fetch = vi.fn(async () => new Response("redirect", {
      status: 302,
      headers: { location: `https://evil.example/?key=${API_KEY}` },
    })) as typeof fetch;
    const redirect = await handleHttpRequest(proxyRequest(PROXY_TOKEN), runtimeEnv());
    expect(redirect.status).toBe(302);
    expect(redirect.headers.get("location")).toBeNull();
    expect(JSON.stringify([...redirect.headers])).not.toContain(API_KEY);
  });
});
