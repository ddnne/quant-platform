/**
 * Entrypoint: GitHub OAuth (workers-oauth-provider) + QuantOpsMcpAgent /mcp.
 * Same pattern as news-crawler workers/mcp.
 */
import OAuthProvider from "@cloudflare/workers-oauth-provider";
import { QuantOpsMcpAgent } from "./agent.js";
import { githubHandler } from "./github-handler.js";

export { QuantOpsMcpAgent };

const oauthProvider = new OAuthProvider({
  apiHandlers: {
    "/mcp": QuantOpsMcpAgent.serve("/mcp"),
    // SSE transport for clients that still initialize over SSE.
    "/sse": QuantOpsMcpAgent.serveSSE("/sse"),
  },
  defaultHandler: githubHandler,
  authorizeEndpoint: "/authorize",
  tokenEndpoint: "/token",
  clientRegistrationEndpoint: "/register",
});

/** Unauthenticated liveness for monitoring. */
async function handleHealthz(request) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response(null, { status: 405, headers: { Allow: "GET, HEAD" } });
  }
  const body = {
    ok: true,
    service: "quant-ops-read-mcp",
    auth: "github-oauth",
  };
  const headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  };
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });
  return new Response(JSON.stringify(body), { status: 200, headers });
}

export default {
  /**
   * @param {Request} request
   * @param {Record<string, unknown>} env
   * @param {ExecutionContext} ctx
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/healthz" || url.pathname === "/health") {
      return handleHealthz(request);
    }
    // Protected-resource metadata: authorization server is this Worker.
    if (url.pathname === "/.well-known/oauth-protected-resource" ||
        url.pathname === "/.well-known/oauth-protected-resource/mcp") {
      return Response.json(
        {
          resource: `${url.origin}/mcp`,
          authorization_servers: [url.origin],
          scopes_supported: ["quant.read.ops"],
          bearer_methods_supported: ["header"],
        },
        { headers: { "Cache-Control": "public, max-age=300" } },
      );
    }
    return oauthProvider.fetch(request, env, ctx);
  },
};
