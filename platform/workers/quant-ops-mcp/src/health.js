/** Unauthenticated liveness. GET/HEAD only; ok is not READY. */

/**
 * @param {Request} request
 * @returns {Response | null}
 */
export function handleHealthRequest(request) {
  const url = new URL(request.url);
  if (url.pathname !== "/healthz" && url.pathname !== "/health") return null;
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
