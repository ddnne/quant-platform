/**
 * Holds JQUANTS_API_KEY on Cloudflare and optionally proxies J-Quants HTTP
 * so local runners never need a local copy of the key.
 *
 * Auth: request header X-Ingestion-Token must match JQUANTS_PROXY_TOKEN secret
 * when proxying. Health checks need no auth. The upstream capability is
 * intentionally narrow: GET requests to exact shared-contract paths.
 */
import premiumContract from "../../../../packages/data_plane/data_contracts/jquants_premium_core.json";
import addonProxyContract from "../../../../packages/data_plane/data_contracts/jquants_proxy_addons.json";
import { authorized } from "./authorized";
import { json } from "./http_json";

export interface Env {
  JQUANTS_API_KEY: string;
  JQUANTS_PROXY_TOKEN?: string;
  PROXY_RATE_LIMITER?: RateLimit;
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

type AuditOutcome =
  | "health"
  | "unauthorized"
  | "configuration_unavailable"
  | "method_rejected"
  | "invalid_request"
  | "path_rejected"
  | "rate_limited"
  | "rate_limit_error"
  | "upstream_response"
  | "upstream_error"
  | "not_found";

function auditedResponse(
  request: Request,
  pathname: string,
  startedAt: number,
  response: Response,
  outcome: AuditOutcome,
  datasetPath?: string,
): Response {
  // Never record authorization headers, query values, request bodies, or
  // secret-binding state. This event is safe for Workers Logs.
  console.info(
    JSON.stringify({
      event: "ingestion_secrets_request",
      request_id: request.headers.get("cf-ray") || crypto.randomUUID(),
      worker: "ingestion-secrets",
      route: pathname,
      method: request.method,
      outcome,
      status: response.status,
      duration_ms: Math.max(0, Date.now() - startedAt),
      ...(datasetPath === undefined ? {} : { dataset_path: datasetPath }),
    }),
  );
  return response;
}

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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const startedAt = Date.now();
    const reply = (
      response: Response,
      outcome: AuditOutcome,
      datasetPath?: string,
    ): Response =>
      auditedResponse(
        request,
        url.pathname,
        startedAt,
        response,
        outcome,
        datasetPath,
      );

    if (url.pathname === "/health") {
      if (request.method !== "GET") {
        return reply(json({ error: "GET required" }, 405), "method_rejected");
      }
      return reply(
        json({
          ok: true,
          worker: "ingestion-secrets",
        }),
        "health",
      );
    }

    if (url.pathname === "/v1/proxy/jquants") {
      if (!(await authorized(request, env.JQUANTS_PROXY_TOKEN))) {
        return reply(json({ error: "unauthorized" }, 401), "unauthorized");
      }
      if (!env.JQUANTS_API_KEY || !env.PROXY_RATE_LIMITER) {
        return reply(
          json({ error: "proxy unavailable" }, 503),
          "configuration_unavailable",
        );
      }
      if (request.method !== "POST") {
        return reply(json({ error: "POST required" }, 405), "method_rejected");
      }
      let rawBody: unknown;
      try {
        rawBody = await request.json();
      } catch {
        return reply(json({ error: "invalid json" }, 400), "invalid_request");
      }
      const body = parseProxyBody(rawBody);
      if (body === null) {
        return reply(
          json(
            {
              error:
                "body requires path, optional method=GET, and string query values",
            },
            400,
          ),
          "invalid_request",
        );
      }
      if (!JQUANTS_PROXY_PATHS.has(body.path)) {
        return reply(
          json(
            { error: "path is not allowed by the J-Quants proxy contracts" },
            403,
          ),
          "path_rejected",
        );
      }

      try {
        const rateLimit = await env.PROXY_RATE_LIMITER.limit({
          key: "jquants-proxy-contract",
        });
        if (!rateLimit.success) {
          const response = json({ error: "rate limit exceeded" }, 429);
          response.headers.set("retry-after", "60");
          return reply(response, "rate_limited", body.path);
        }
      } catch {
        return reply(
          json({ error: "proxy unavailable" }, 503),
          "rate_limit_error",
          body.path,
        );
      }

      const target = new URL(JQ_BASE + body.path);
      for (const [key, value] of Object.entries(body.query)) {
        target.searchParams.set(key, value);
      }
      try {
        const upstream = await fetch(target.toString(), {
          method: "GET",
          headers: { "x-api-key": env.JQUANTS_API_KEY },
          redirect: "manual",
        });
        return reply(
          new Response(upstream.body, {
            status: upstream.status,
            statusText: upstream.statusText,
            headers: {
              "content-type":
                upstream.headers.get("content-type") || "application/json",
              "cache-control": "no-store",
              "x-content-type-options": "nosniff",
            },
          }),
          "upstream_response",
          body.path,
        );
      } catch {
        return reply(
          json({ error: "upstream unavailable" }, 502),
          "upstream_error",
          body.path,
        );
      }
    }

    return reply(json({ error: "not found" }, 404), "not_found");
  },
} satisfies ExportedHandler<Env>;
