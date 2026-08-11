import { handleMcpHttp } from "./mcp.js";
import { AuthError, authenticateAccess } from "./auth.js";
import { DurableDailyQuota } from "./quota.js";

/** @typedef {{OPS_DB:D1Database, OAUTH_AUTHORIZATION_SERVER:string, ALLOWED_ORIGINS:string,
 * ACCESS_TEAM_DOMAIN:string, ACCESS_AUD:string, DAILY_ROW_QUOTA:string}} Env */

/** @param {unknown} error @param {string} resourceMetadata */
function unauthorized(error, resourceMetadata) {
  const status = error instanceof AuthError ? error.status : 401;
  return Response.json({ error: status === 403 ? "forbidden" : "unauthorized" }, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "WWW-Authenticate": `Bearer resource_metadata=\"${resourceMetadata}\"`,
    },
  });
}

/** @param {Request} request @param {string|undefined} configured */
function originAllowed(request, configured) {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  const allowed = String(configured || "").split(",").map((item) => item.trim()).filter(Boolean);
  return allowed.includes(origin);
}

/** @param {{authenticate?:typeof authenticateAccess}} dependencies */
export function createFetchHandler(dependencies = {}) {
  const authenticate = dependencies.authenticate || authenticateAccess;
  /** @param {Request} request @param {Env} env */
  return async function fetchHandler(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, service: "quant-ops-read-mcp" }, {
        headers: { "Cache-Control": "no-store" },
      });
    }
    if (url.pathname === "/.well-known/oauth-protected-resource") {
      return Response.json({
        resource: url.origin + "/mcp",
        authorization_servers: [env.OAUTH_AUTHORIZATION_SERVER],
        scopes_supported: ["quant.read.ops"],
      }, { headers: { "Cache-Control": "public, max-age=300" } });
    }
    if (url.pathname !== "/mcp") return Response.json({ error: "not found" }, { status: 404 });
    const resourceMetadata = url.origin + "/.well-known/oauth-protected-resource";
    if (!originAllowed(request, env.ALLOWED_ORIGINS)) {
      return Response.json({ error: "origin not allowed" }, { status: 403 });
    }
    let principal;
    try {
      principal = await authenticate(request, env);
    } catch (error) {
      return unauthorized(error, resourceMetadata);
    }
    const quota = new DurableDailyQuota(env.OPS_DB, env.DAILY_ROW_QUOTA);
    return handleMcpHttp(request, env.OPS_DB, { principal, quota });
  };
}

export default {
  /**
   * @param {Request} request
   * @param {Env} env
   */
  async fetch(request, env) {
    return createFetchHandler()(request, env);
  },
};
