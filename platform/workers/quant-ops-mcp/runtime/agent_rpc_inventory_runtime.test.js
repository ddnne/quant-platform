import { env } from "cloudflare:workers";
import {
  createExecutionContext,
  reset,
  runInDurableObject,
  SELF,
} from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

import bindingManifest from "../../../../specs/cloudflare/active_worker_bindings.json" with { type: "json" };

import {
  BINDING_MANIFEST_DIGEST,
  BINDING_MANIFEST_SCHEMA_VERSION,
  QuantOpsMcpAgent,
} from "../src/agent.js";

const reservedSpecials = new Set([
  "fetch",
  "alarm",
  "webSocketMessage",
  "webSocketClose",
  "webSocketError",
]);

const preConstructionOwnMethods = Reflect.ownKeys(QuantOpsMcpAgent.prototype)
  .filter((name) => name !== "constructor")
  .filter((name) => typeof Object.getOwnPropertyDescriptor(
    QuantOpsMcpAgent.prototype,
    name,
  )?.value === "function")
  .map(String)
  .sort();

function canonicalPrototypeRows(instance) {
  const rows = [];
  let prototype = Object.getPrototypeOf(instance);
  let ownerOrder = 0;
  while (prototype && prototype !== Object.prototype) {
    const owner = prototype.constructor?.name || "<anonymous>";
    const keys = Reflect.ownKeys(prototype).sort((left, right) => {
      const leftName = String(left);
      const rightName = String(right);
      return leftName < rightName ? -1 : leftName > rightName ? 1 : 0;
    });
    for (const key of keys) {
      const name = typeof key === "symbol" ? `symbol:${String(key)}` : key;
      if (name === "constructor") continue;
      const descriptor = Object.getOwnPropertyDescriptor(prototype, key);
      if (!descriptor) continue;
      const base = {
        owner_order: ownerOrder,
        owner,
        name,
        enumerable: descriptor.enumerable === true,
        configurable: descriptor.configurable === true,
        writable: descriptor.writable === true,
      };
      if (typeof descriptor.value === "function") {
        rows.push({ ...base, kind: "method" });
      }
      if (typeof descriptor.get === "function") {
        rows.push({ ...base, kind: "getter" });
      }
      if (typeof descriptor.set === "function") {
        rows.push({ ...base, kind: "setter" });
      }
    }
    prototype = Object.getPrototypeOf(prototype);
    ownerOrder += 1;
  }
  return rows;
}

async function sqliteSnapshot(stub) {
  return runInDurableObject(stub, async (_instance, state) => {
    const tables = state.storage.sql.exec(
      "SELECT name, sql FROM sqlite_master " +
      "WHERE type='table' AND name NOT LIKE 'sqlite_%' " +
      "AND name NOT LIKE '_cf_%' ORDER BY name",
    ).toArray();
    const content = [];
    for (const table of tables) {
      const name = String(table.name);
      const quoted = `"${name.replaceAll('"', '""')}"`;
      const rows = state.storage.sql.exec(`SELECT * FROM ${quoted}`).toArray()
        .map((row) => Object.fromEntries(
          Object.keys(row).sort().map((key) => {
            const value = row[key];
            return [
              key,
              value instanceof Uint8Array
                ? { bytes: Array.from(value) }
                : typeof value === "bigint" ? value.toString() : value,
            ];
          }),
        ))
        .sort((left, right) => JSON.stringify(left).localeCompare(
          JSON.stringify(right),
        ));
      content.push({ name, sql: String(table.sql), rows });
    }
    return content;
  });
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0")).join("")}`;
}

beforeEach(async () => {
  await reset();
});

describe("QuantOpsMcpAgent inherited RPC inventory", () => {
  it("matches the exact post-construction framework inventory", async () => {
    expect(preConstructionOwnMethods).toEqual(["init"]);
    const handler = bindingManifest.workers["quant-ops-mcp"].staging
      .durable_object_class_handlers[0];
    const expected = handler.framework_rpc_inventory;
    expect(handler.name).toBe("QuantOpsMcpAgent");
    expect(BINDING_MANIFEST_SCHEMA_VERSION).toBe(bindingManifest.schema_version);
    expect(BINDING_MANIFEST_DIGEST).toBe(bindingManifest.manifest_digest);
    expect(QuantOpsMcpAgent.bindingManifestSchemaVersion).toBe(
      bindingManifest.schema_version,
    );
    expect(QuantOpsMcpAgent.bindingManifestDigest).toBe(
      bindingManifest.manifest_digest,
    );
    expect(expected.own_custom_pre_init_rpc_methods).toEqual(
      preConstructionOwnMethods,
    );

    const stub = env.MCP_OBJECT.getByName("rpc:inventory");
    const observed = await runInDurableObject(stub, async (instance) => {
      const rows = canonicalPrototypeRows(instance);
      const postConstructionOwnMethods = rows
        .filter((row) => row.owner_order === 0 && row.kind === "method")
        .map((row) => row.name);
      const unique = new Map();
      for (const row of rows) {
        if (!unique.has(`${row.kind}:${row.name}`)) {
          unique.set(`${row.kind}:${row.name}`, row);
        }
      }
      const uniqueRows = [...unique.values()];
      const specialNames = uniqueRows
        .filter((row) => row.kind === "method" && reservedSpecials.has(row.name))
        .map((row) => row.name)
        .sort();
      const ownerInventories = await Promise.all(
        [...new Set(rows.map((row) => row.owner))].map(async (owner) => {
          const ownerRows = rows.filter((row) => row.owner === owner);
          return {
            owner,
            descriptor_row_count: ownerRows.length,
            descriptor_digest: await sha256(ownerRows),
          };
        }),
      );
      const copiedMethods = postConstructionOwnMethods.filter(
        (name) => !preConstructionOwnMethods.includes(name),
      );
      return {
        constructor_prototype_copy: {
          observed: copiedMethods.length > 0,
          copied_method_count: copiedMethods.length,
          post_construction_own_method_count: postConstructionOwnMethods.length,
        },
        post_construction_prototype: {
          canonicalization: "prototype-descriptors/v1",
          descriptor_row_count: rows.length,
          descriptor_digest: await sha256(rows),
          owner_order: [...new Set(rows.map((row) => row.owner))],
          owner_inventories: ownerInventories,
          unique_method_count: uniqueRows.filter(
            (row) => row.kind === "method",
          ).length,
          unique_ordinary_method_count: uniqueRows.filter(
            (row) => row.kind === "method" && !reservedSpecials.has(row.name),
          ).length,
          unique_getter_count: uniqueRows.filter(
            (row) => row.kind === "getter",
          ).length,
          unique_setter_count: uniqueRows.filter(
            (row) => row.kind === "setter",
          ).length,
          unique_reserved_special_count: specialNames.length,
        },
        specialNames,
      };
    });
    expect(observed.constructor_prototype_copy).toEqual(
      expected.constructor_prototype_copy,
    );
    expect(observed.post_construction_prototype).toEqual(
      expected.post_construction_prototype,
    );
    expect(observed.specialNames).toEqual(
      Object.keys(expected.reserved_specials).sort(),
    );
    expect(expected.reserved_specials).toEqual({
      fetch: true,
      alarm: true,
      webSocketMessage: true,
      webSocketClose: true,
      webSocketError: true,
    });
  });

  it("does not forward inherited methods through MCP HTTP", async () => {
    const handler = QuantOpsMcpAgent.serve("/mcp");
    const initialize = await handler.fetch(
      new Request("https://ops.test/mcp", {
        method: "POST",
        headers: {
          accept: "application/json, text/event-stream",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "initialize",
          method: "initialize",
          params: {
            protocolVersion: "2025-06-18",
            capabilities: {},
            clientInfo: { name: "rpc-inventory-test", version: "1" },
          },
        }),
      }),
      env,
      createExecutionContext(),
    );
    expect(initialize.status).toBe(200);
    const sessionId = initialize.headers.get("mcp-session-id");
    expect(sessionId).toMatch(/^[0-9a-f]{64}$/);
    expect(await initialize.text()).toContain('"result"');
    const stub = env.MCP_OBJECT.getByName(`streamable-http:${sessionId}`);
    const before = await sqliteSnapshot(stub);
    for (const method of ["sql", "agent", "server"]) {
      const request = new Request("https://ops.test/mcp", {
        method: "POST",
        headers: {
          accept: "application/json, text/event-stream",
          "content-type": "application/json",
          "mcp-protocol-version": "2025-06-18",
          "mcp-session-id": sessionId,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: method, method }),
      });
      const response = await handler.fetch(
        request.clone(),
        env,
        createExecutionContext(),
      );
      expect(response.status).toBe(200);
      const body = await response.text();
      expect(body).toContain('"code":-32601');
      expect(body).toContain("Method not found");
      const publicResponse = await SELF.fetch(request);
      expect(publicResponse.status).toBe(401);
    }
    const after = await sqliteSnapshot(stub);
    expect(after).toEqual(before);
  });
});
