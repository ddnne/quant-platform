/**
 * Quant Ops McpAgent — registers the same Ops-read tools as domain.js.
 * Auth is enforced by workers-oauth-provider before traffic reaches the DO.
 */
import { McpAgent } from "agents/mcp";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { OPS_TOOLS, callOpsTool } from "./domain.js";
import { DurableDailyQuota, quotaCost, QuotaExceeded } from "./quota.js";

/**
 * Build a loose zod object from the MCP JSON Schema properties map.
 * Ops tools only use string / integer / enum; unknown keys are rejected by domain.
 * @param {Record<string, unknown>} properties
 * @param {string[]} required
 */
function zodFromSchema(properties = {}, required = []) {
  /** @type {Record<string, z.ZodTypeAny>} */
  const shape = {};
  for (const [key, raw] of Object.entries(properties)) {
    const prop = /** @type {Record<string, unknown>} */ (raw || {});
    let field;
    if (prop.type === "integer") {
      field = z.number().int();
      if (typeof prop.minimum === "number") field = field.min(prop.minimum);
      if (typeof prop.maximum === "number") field = field.max(prop.maximum);
    } else if (Array.isArray(prop.enum)) {
      field = z.enum(/** @type {[string, ...string[]]} */ (prop.enum.map(String)));
    } else {
      field = z.string();
      if (typeof prop.minLength === "number") field = field.min(prop.minLength);
      if (typeof prop.maxLength === "number") field = field.max(prop.maxLength);
    }
    shape[key] = required.includes(key) ? field : field.optional();
  }
  return z.object(shape);
}

export class QuantOpsMcpAgent extends McpAgent {
  server = new McpServer({
    name: "quant-ops-read",
    version: "0.2.0",
  });

  async init() {
    this.server = new McpServer(
      { name: "quant-ops-read", version: "0.2.0" },
      {
        instructions:
          "Read-only Quant Ops status (coverage, validation, READY metadata). " +
          "No research rows, SQL, ingestion triggers, or admin tools. " +
          "GitHub OAuth; single allowed login only.",
      },
    );

    for (const tool of OPS_TOOLS) {
      const schema = tool.inputSchema || {};
      const properties = /** @type {Record<string, unknown>} */ (
        schema.properties || {}
      );
      const required = /** @type {string[]} */ (schema.required || []);
      const shape = zodFromSchema(properties, required);
      this.server.tool(
        tool.name,
        tool.description,
        shape.shape,
        async (args) => {
          try {
            const db = this.env.OPS_DB;
            const value = await callOpsTool(db, tool.name, args);
            const login = typeof this.props?.login === "string" && this.props.login
              ? this.props.login
              : "unknown";
            const quota = new DurableDailyQuota(db, this.env.DAILY_ROW_QUOTA);
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
            const message =
              err instanceof Error ? err.message : "Internal error";
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
  }
}
