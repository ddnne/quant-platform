/**
 * Holds JQUANTS_API_KEY on Cloudflare and optionally proxies J-Quants HTTP
 * so local runners never need a local copy of the key.
 *
 * Auth: request header X-Ingestion-Token must match INGESTION_PROXY_TOKEN secret
 * when proxying. Health checks need no auth. The upstream capability is
 * intentionally narrow: GET requests to exact shared-contract paths.
 */
import premiumContract from "../../../../data_contracts/jquants_premium_core.json";
import addonProxyContract from "../../../../data_contracts/jquants_proxy_addons.json";

export interface Env {
  JQUANTS_API_KEY: string;
  INGESTION_PROXY_TOKEN?: string;
}

const JQ_BASE = "https://api.jquants.com";
const JQUANTS_PROXY_PATHS: ReadonlySet<string> = new Set(
  [...premiumContract.datasets, ...addonProxyContract.datasets].map(
    (dataset) => dataset.path,
  ),
);

type ProxyBody = {
  path: string;
  method: "GET";
  query: Record<string, string>;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseProxyBody(value: unknown): ProxyBody | null {
  if (!isObject(value) || typeof value.path !== "string") return null;
  if (value.method !== undefined && value.method !== "GET") return null;
  if (value.query !== undefined && !isObject(value.query)) return null;

  const query: Record<string, string> = {};
  for (const [key, item] of Object.entries(value.query || {})) {
    if (typeof item !== "string") return null;
    if (item !== "") query[key] = item;
  }
  return { path: value.path, method: "GET", query };
}

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      if (request.method !== "GET") {
        return Response.json({ error: "GET required" }, { status: 405 });
      }
      return Response.json({
        ok: true,
        has_jquants_key: Boolean(env.JQUANTS_API_KEY),
      });
    }

    if (url.pathname === "/v1/proxy/jquants") {
      const token = request.headers.get("X-Ingestion-Token") || "";
      if (
        !env.INGESTION_PROXY_TOKEN ||
        !(await tokenMatches(token, env.INGESTION_PROXY_TOKEN))
      ) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      if (!env.JQUANTS_API_KEY) {
        return Response.json({ error: "JQUANTS_API_KEY not bound" }, { status: 500 });
      }
      if (request.method !== "POST") {
        return Response.json({ error: "POST required" }, { status: 405 });
      }
      let rawBody: unknown;
      try {
        rawBody = await request.json();
      } catch {
        return Response.json({ error: "invalid json" }, { status: 400 });
      }
      const body = parseProxyBody(rawBody);
      if (body === null) {
        return Response.json(
          { error: "body requires path, optional method=GET, and string query values" },
          { status: 400 },
        );
      }
      if (!JQUANTS_PROXY_PATHS.has(body.path)) {
        return Response.json(
          { error: "path is not allowed by the J-Quants proxy contracts" },
          { status: 403 },
        );
      }
      const target = new URL(JQ_BASE + body.path);
      for (const [key, value] of Object.entries(body.query)) {
        target.searchParams.set(key, value);
      }
      const upstream = await fetch(target.toString(), {
        method: "GET",
        headers: { "x-api-key": env.JQUANTS_API_KEY },
        redirect: "manual",
      });
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: {
          "content-type": upstream.headers.get("content-type") || "application/json",
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        },
      });
    }

    return Response.json({ error: "not found" }, { status: 404 });
  },
} satisfies ExportedHandler<Env>;
