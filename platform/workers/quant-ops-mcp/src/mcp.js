import { OPS_TOOLS, callOpsTool } from "./domain.js";
import { QuotaExceeded, quotaCost } from "./quota.js";
import { acceptedOpsToolSchemaDigest } from "./tool_schema_digest.js";

export const MCP_PROTOCOL_VERSION = "2025-06-18";

/** @param {unknown} id @param {unknown} result */
function response(id, result) {
  return { jsonrpc: "2.0", id, result };
}

/** @param {unknown} id @param {number} code @param {string} message */
function error(id, code, message) {
  return { jsonrpc: "2.0", id: id ?? null, error: { code, message } };
}

/**
 * @param {unknown} payload
 * @param {D1Database} db
 * @param {{quota?:{charge:(principal:{subject:string,clientId:string}, units:number)=>Promise<unknown>},
 * principal?:{subject:string,clientId:string},projectionPublicKeyRegistry?:unknown}} context
 */
export async function handleJsonRpc(payload, db, context = {}) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return error(null, -32600, "Invalid Request");
  }
  const request = /** @type {Record<string, unknown>} */ (payload);
  const id = request.id;
  // JSON-RPC responses to a server-initiated request carry no method. This
  // stateless server currently initiates none, so acknowledge without a reply.
  if (request.jsonrpc === "2.0" && typeof request.method !== "string" &&
      ("result" in request || "error" in request)) return null;
  if (request.jsonrpc !== "2.0" || typeof request.method !== "string") {
    return error(id, -32600, "Invalid Request");
  }
  if (request.method === "initialize" && id === undefined) {
    return error(null, -32600, "initialize must be a JSON-RPC request");
  }
  try {
    if (request.method === "initialize") {
      const params = request.params;
      if (!params || typeof params !== "object" || Array.isArray(params)) {
        return error(id, -32602, "initialize params are required");
      }
      const values = /** @type {Record<string, unknown>} */ (params);
      if (typeof values.protocolVersion !== "string" ||
          !values.capabilities || typeof values.capabilities !== "object" ||
          !values.clientInfo || typeof values.clientInfo !== "object") {
        return error(id, -32602, "invalid initialize params");
      }
      return response(id, {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "quant-ops-read", version: "0.1.0" },
        instructions: "Current mutable Ops status only. Research rows are not exposed by this server.",
      });
    }
    if (request.method === "ping") return response(id, {});
    if (request.method === "tools/list") {
      const schemaDigest = await acceptedOpsToolSchemaDigest(OPS_TOOLS);
      return response(id, {
        tools: OPS_TOOLS,
        _meta: { "quant-platform/tool-schema-digest": schemaDigest },
      });
    }
    if (request.method === "notifications/initialized") return null;
    if (id === undefined) return null;
    if (request.method === "tools/call") {
      const params = request.params;
      if (!params || typeof params !== "object" || Array.isArray(params)) {
        return error(id, -32602, "tools/call requires params");
      }
      const values = /** @type {Record<string, unknown>} */ (params);
      if (typeof values.name !== "string") return error(id, -32602, "tool name is required");
      const value = await callOpsTool(db, values.name, values.arguments, {
        projectionPublicKeyRegistry: context.projectionPublicKeyRegistry,
      });
      const quota = context.quota && context.principal
        ? await context.quota.charge(context.principal, quotaCost(value))
        : null;
      return response(id, {
        content: [{ type: "text", text: JSON.stringify(value) }],
        structuredContent: value,
        isError: false,
        ...(quota ? { _meta: { quota } } : {}),
      });
    }
    return error(id, -32601, "Method not found");
  } catch (cause) {
    if (cause instanceof TypeError || cause instanceof RangeError) {
      return error(id, -32602, cause.message);
    }
    if (cause instanceof QuotaExceeded) return error(id, -32029, cause.message);
    return error(id, -32603, "Internal error");
  }
}

/**
 * @param {Request} request @param {D1Database} db
 * @param {{quota?:{charge:(principal:{subject:string,clientId:string}, units:number)=>Promise<unknown>},
 * principal?:{subject:string,clientId:string},projectionPublicKeyRegistry?:unknown}} context
 */
export async function handleMcpHttp(request, db, context = {}) {
  if (request.method === "GET") {
    return Response.json({ error: "GET event stream is not offered; use Streamable HTTP POST" }, {
      status: 405, headers: { Allow: "POST", "Cache-Control": "no-store" },
    });
  }
  if (request.method !== "POST") {
    return Response.json({ error: "POST required" }, {
      status: 405, headers: { Allow: "POST", "Cache-Control": "no-store" },
    });
  }
  const contentType = request.headers.get("content-type") || "";
  const accept = request.headers.get("accept") || "";
  const requestedVersion = request.headers.get("MCP-Protocol-Version");
  if (requestedVersion && requestedVersion !== MCP_PROTOCOL_VERSION) {
    return Response.json({ error: "unsupported MCP protocol version" }, { status: 400 });
  }
  if (!contentType.toLowerCase().includes("application/json")) {
    return Response.json({ error: "application/json required" }, { status: 415 });
  }
  if (!accept.includes("application/json") || !accept.includes("text/event-stream")) {
    return Response.json({ error: "Accept must include application/json and text/event-stream" }, { status: 406 });
  }
  let payload;
  try {
    payload = await request.json();
  } catch {
    return Response.json(error(null, -32700, "Parse error"), { status: 400 });
  }
  const result = await handleJsonRpc(payload, db, context);
  if (result === null) return new Response(null, { status: 202 });
  return Response.json(result, {
    headers: {
      "Cache-Control": "no-store",
      "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
      "X-Content-Type-Options": "nosniff",
    },
  });
}
