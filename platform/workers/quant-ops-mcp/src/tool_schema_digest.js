/** Frozen acceptance digest for the public MCP tool schema surface. */

import acceptance from "../../../../specs/ops_projection/mcp_tool_schema_acceptance.json" with { type: "json" };

import { projectionSha256 } from "./projection_signature.js";

export const OPS_MCP_SERVER_NAME = "quant-ops-read";
export const OPS_MCP_SERVER_VERSION = "0.2.0";
export const OPS_MCP_PROTOCOL_VERSION = "2025-06-18";
export const OPS_TOOL_SCHEMA_DOCUMENT_VERSION = "quant-ops-mcp-tool-schemas/v2";

// Derived from the generated acceptance manifest. Do not hand-copy the hash.
export const ACCEPTED_OPS_TOOL_SCHEMA_DIGEST = acceptance.schema_digest;

/**
 * @param {ReadonlyArray<{name:string,description:string,inputSchema:Record<string,unknown>,outputSchema:Record<string,unknown>}>} tools
 * @param {{name?:string,version?:string,protocolVersion?:string}} [surface]
 */
export async function opsToolSchemaDigest(tools, surface = {}) {
  return projectionSha256({
    schema_version: OPS_TOOL_SCHEMA_DOCUMENT_VERSION,
    mcp_server: {
      name: surface.name ?? OPS_MCP_SERVER_NAME,
      version: surface.version ?? OPS_MCP_SERVER_VERSION,
    },
    protocol_version: surface.protocolVersion ?? OPS_MCP_PROTOCOL_VERSION,
    tools: tools.map(({ name, description, inputSchema, outputSchema }) => ({
      name,
      description,
      inputSchema,
      outputSchema,
    })),
  });
}

/**
 * @param {ReadonlyArray<{name:string,description:string,inputSchema:Record<string,unknown>,outputSchema:Record<string,unknown>}>} tools
 */
export async function acceptedOpsToolSchemaDigest(tools) {
  const observed = await opsToolSchemaDigest(tools);
  if (observed !== ACCEPTED_OPS_TOOL_SCHEMA_DIGEST) {
    throw new Error(
      `Quant Ops MCP schema drift: expected ${ACCEPTED_OPS_TOOL_SCHEMA_DIGEST}, observed ${observed}`,
    );
  }
  return observed;
}
