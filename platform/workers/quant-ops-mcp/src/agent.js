/**
 * Quant Ops McpAgent — registers the same Ops-read tools as domain.js.
 * Auth is enforced by workers-oauth-provider before traffic reaches the DO.
 */
import { McpAgent } from "agents/mcp";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import { OPS_TOOLS, callOpsTool } from "./domain.js";
import { DurableDailyQuota, quotaCost, QuotaExceeded } from "./quota.js";
import { acceptedOpsToolSchemaDigest } from "./tool_schema_digest.js";

export const OPS_TOOL_SCHEMA_META_KEY = "quant-platform/tool-schema-digest";
export const BINDING_MANIFEST_SCHEMA_VERSION =
  "cloudflare-active-worker-bindings/v8";
export const BINDING_MANIFEST_DIGEST =
  "sha256:6ba1ee2ccf0c5723a77f4a0461a3683fca57fdf566d77a7fd4a4489780f020a9";

/** @param {Record<string, unknown>} schema */
function zodFromJsonSchema(schema) {
  if (schema.type !== "object" || schema.additionalProperties !== false) {
    throw new TypeError("Quant Ops MCP tools require a closed object schema");
  }
  return z.fromJSONSchema(schema);
}

/**
 * Construct the exact server used by QuantOpsMcpAgent. This is also the narrow
 * behavioral-test seam; production environment bindings are closed over here.
 *
 * @param {{OPS_PROJECTION_DB:D1Database,QUOTA_DB:D1Database,DAILY_ROW_QUOTA:string|number}} env
 * @param {{login?:unknown}|undefined} props
 */
export async function buildOpsMcpServer(env, props) {
  const schemaDigest = await acceptedOpsToolSchemaDigest(OPS_TOOLS);
  const schemaMeta = Object.freeze({ [OPS_TOOL_SCHEMA_META_KEY]: schemaDigest });
  const publishedTools = OPS_TOOLS.map((tool) => ({
    ...tool,
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: schemaMeta,
  }));
  const server = new McpServer(
    { name: "quant-ops-read", version: "0.2.0" },
    {
      instructions:
        "Read-only Quant Ops status (coverage, validation, READY metadata). " +
        "No research rows, SQL, ingestion triggers, or admin tools. " +
        "GitHub OAuth; single allowed login only.",
    },
  );

  for (const tool of publishedTools) {
    server.registerTool(
      tool.name,
      {
        description: tool.description,
        inputSchema: zodFromJsonSchema(tool.inputSchema),
        outputSchema: zodFromJsonSchema(tool.outputSchema),
        annotations: tool.annotations,
        _meta: tool._meta,
      },
      async (args) => {
        try {
          const value = await callOpsTool(env.OPS_PROJECTION_DB, tool.name, args);
          const login = typeof props?.login === "string" && props.login
            ? props.login
            : "unknown";
          const quota = new DurableDailyQuota(env.QUOTA_DB, env.DAILY_ROW_QUOTA);
          const charged = await quota.charge(
            { subject: `human:${login}`, clientId: login },
            quotaCost(value),
          );
          return {
            content: [{ type: "text", text: JSON.stringify(value) }],
            structuredContent: value,
            _meta: { quota: charged },
          };
        } catch (err) {
          const message = err instanceof Error ? err.message : "Internal error";
          const isQuota = err instanceof QuotaExceeded;
          return {
            content: [{ type: "text", text: message }],
            isError: true,
            _meta: isQuota ? { quota: "exceeded" } : undefined,
          };
        }
      },
    );
  }

  // The SDK derives JSON Schema from Zod for validation. Publish the reviewed
  // canonical source schemas verbatim so the live HTTP surface and acceptance
  // manifest have one byte-stable digest rather than converter-dependent drift.
  server.server.setRequestHandler(ListToolsRequestSchema, () => ({
    tools: publishedTools,
    _meta: schemaMeta,
  }));
  return server;
}

export class QuantOpsMcpAgent extends McpAgent {
  // These static fields are shipped in the Worker module without becoming DO
  // RPC methods. Exact-byte live module acceptance therefore binds the active
  // bundle to the reviewed binding-manifest version and digest.
  static bindingManifestSchemaVersion = BINDING_MANIFEST_SCHEMA_VERSION;
  static bindingManifestDigest = BINDING_MANIFEST_DIGEST;

  server = new McpServer({
    name: "quant-ops-read",
    version: "0.2.0",
  });

  async init() {
    this.server = await buildOpsMcpServer(this.env, this.props);
  }
}
