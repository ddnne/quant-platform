/**
 * Entrypoint: GitHub OAuth (workers-oauth-provider) + QuantOpsMcpAgent /mcp.
 * Same pattern as news-crawler workers/mcp.
 */
import OAuthProvider from "@cloudflare/workers-oauth-provider";
import { QuantOpsMcpAgent } from "./agent.js";
import { githubHandler } from "./github-handler.js";
import { handleHealthRequest } from "./health.js";

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

export default {
  /**
   * @param {Request} request
   * @param {Env} env
   * @param {ExecutionContext} ctx
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const health = handleHealthRequest(request);
    if (health) return health;
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
