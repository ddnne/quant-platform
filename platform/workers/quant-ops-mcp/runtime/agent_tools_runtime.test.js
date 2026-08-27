import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import acceptance from "../../../../specs/ops_projection/mcp_tool_schema_acceptance.json" with { type: "json" };

import {
  buildOpsMcpServer,
  OPS_TOOL_SCHEMA_META_KEY,
} from "../src/agent.js";
import { OPS_TOOLS } from "../src/domain.js";
import { ACCEPTED_OPS_TOOL_SCHEMA_DIGEST } from "../src/tool_schema_digest.js";

describe("live QuantOpsMcpAgent schema registration", () => {
  it("publishes the accepted 17-tool input/output schema surface", async () => {
    const server = await buildOpsMcpServer(
      {
        OPS_PROJECTION_DB: {},
        QUOTA_DB: {},
        DAILY_ROW_QUOTA: "25000",
      },
      { login: "harness-user" },
    );
    const client = new Client(
      { name: "quant-ops-agent-schema-test", version: "1.0.0" },
      { capabilities: {} },
    );
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await server.connect(serverTransport);
    await client.connect(clientTransport);
    try {
      const listed = await client.listTools();
      expect(listed.tools).toHaveLength(17);
      expect(listed.tools.map((tool) => tool.name)).toEqual(acceptance.tool_names);
      expect(listed._meta?.[OPS_TOOL_SCHEMA_META_KEY]).toBe(
        ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
      );
      expect(acceptance.schema_digest).toBe(ACCEPTED_OPS_TOOL_SCHEMA_DIGEST);
      for (const [index, liveTool] of listed.tools.entries()) {
        const sourceTool = OPS_TOOLS[index];
        expect(liveTool.name).toBe(sourceTool.name);
        expect(liveTool.inputSchema).toEqual(sourceTool.inputSchema);
        expect(liveTool.outputSchema).toEqual(sourceTool.outputSchema);
        expect(liveTool._meta?.[OPS_TOOL_SCHEMA_META_KEY]).toBe(
          ACCEPTED_OPS_TOOL_SCHEMA_DIGEST,
        );
        expect(liveTool.annotations?.readOnlyHint).toBe(true);
        expect(liveTool.annotations?.destructiveHint).toBe(false);
      }
    } finally {
      await client.close();
      await server.close();
    }
  });
});
