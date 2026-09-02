/** Frozen acceptance digest for the public MCP tool schema surface. */

import { projectionSha256 } from "./projection_signature.js";

export const OPS_MCP_SERVER_NAME = "quant-ops-read";
export const OPS_MCP_SERVER_VERSION = "0.2.0";
export const OPS_MCP_PROTOCOL_VERSION = "2025-06-18";
export const OPS_TOOL_SCHEMA_DOCUMENT_VERSION = "quant-ops-mcp-tool-schemas/v2";

// Updated only after review of an intentional tools/list contract change.
export const ACCEPTED_OPS_TOOL_SCHEMA_DIGEST =
  "sha256:227465ce16df9ebd496bc102b198dcb5cc5c9660a26a8820b0449f824a5b67bc";

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
