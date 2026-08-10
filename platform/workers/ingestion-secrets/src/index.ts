/**
 * Holds JQUANTS_API_KEY on Cloudflare and optionally proxies J-Quants HTTP
 * so local runners never need a local copy of the key.
 *
 * Auth: request header X-Ingestion-Token must match INGESTION_PROXY_TOKEN secret
 * when proxying. Health checks need no auth.
 */
export interface Env {
  JQUANTS_API_KEY: string;
  INGESTION_PROXY_TOKEN?: string;
}

const JQ_BASE = "https://api.jquants.com";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({
        ok: true,
        has_jquants_key: Boolean(env.JQUANTS_API_KEY),
      });
    }

    if (url.pathname === "/v1/proxy/jquants") {
      const token = request.headers.get("X-Ingestion-Token") || "";
      if (!env.INGESTION_PROXY_TOKEN || token !== env.INGESTION_PROXY_TOKEN) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      if (!env.JQUANTS_API_KEY) {
        return Response.json({ error: "JQUANTS_API_KEY not bound" }, { status: 500 });
      }
      if (request.method !== "POST") {
        return Response.json({ error: "POST required" }, { status: 405 });
      }
      let body: { path?: string; method?: string; query?: Record<string, string> };
      try {
        body = await request.json();
      } catch {
        return Response.json({ error: "invalid json" }, { status: 400 });
      }
      const path = body.path || "";
      if (!path.startsWith("/v2/")) {
        return Response.json({ error: "path must start with /v2/" }, { status: 400 });
      }
      const target = new URL(JQ_BASE + path);
      if (body.query) {
        for (const [k, v] of Object.entries(body.query)) {
          if (v != null && v !== "") target.searchParams.set(k, String(v));
        }
      }
      const upstream = await fetch(target.toString(), {
        method: body.method || "GET",
        headers: { "x-api-key": env.JQUANTS_API_KEY },
      });
      const text = await upstream.text();
      return new Response(text, {
        status: upstream.status,
        headers: {
          "content-type": upstream.headers.get("content-type") || "application/json",
        },
      });
    }

    return Response.json({ error: "not found" }, { status: 404 });
  },
};
