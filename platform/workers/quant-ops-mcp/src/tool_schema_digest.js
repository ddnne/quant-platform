/** Frozen acceptance digest for the public MCP tool schema surface. */

import { projectionSha256 } from "./projection_signature.js";

// Updated only after review of an intentional tools/list contract change.
export const ACCEPTED_OPS_TOOL_SCHEMA_DIGEST =
  "sha256:dad7cd29ef002e76ee1f9802b8685a179f94fcbd0bb2e6df685858e41c1778d3";

/**
 * @param {ReadonlyArray<{name:string,inputSchema:Record<string,unknown>,outputSchema:Record<string,unknown>}>} tools
 */
export async function opsToolSchemaDigest(tools) {
  return projectionSha256({
    schema_version: "quant-ops-mcp-tool-schemas/v1",
    tools: tools.map(({ name, inputSchema, outputSchema }) => ({
      name,
      inputSchema,
      outputSchema,
    })),
  });
}

/**
 * @param {ReadonlyArray<{name:string,inputSchema:Record<string,unknown>,outputSchema:Record<string,unknown>}>} tools
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
