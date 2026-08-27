import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

const readJson = (url) => JSON.parse(readFileSync(url, "utf8"));
const manifest = readJson(
  new URL(
    "../../../../specs/cloudflare/active_worker_bindings.json",
    import.meta.url,
  ),
);
const packageJson = readJson(new URL("../package.json", import.meta.url));
const lockUrl = new URL("../package-lock.json", import.meta.url);
const lockBytes = readFileSync(lockUrl);
const lock = JSON.parse(lockBytes.toString("utf8"));
const installedAgents = readJson(
  new URL("../node_modules/agents/package.json", import.meta.url),
);

test("fresh npm ci agents dependency matches the frozen framework inventory", () => {
  const handler = manifest.workers["quant-ops-mcp"].staging
    .durable_object_class_handlers[0];
  const dependency = handler.framework_rpc_inventory.dependency;
  const resolved = lock.packages["node_modules/agents"];
  const packageLockDigest =
    `sha256:${createHash("sha256").update(lockBytes).digest("hex")}`;

  assert.equal(packageJson.dependencies.agents, "0.17.4");
  assert.equal(lock.packages[""].dependencies.agents, "0.17.4");
  assert.deepEqual(dependency, {
    package: "agents",
    requested: packageJson.dependencies.agents,
    resolved_version: resolved.version,
    resolved: resolved.resolved,
    integrity: resolved.integrity,
    package_lock: "platform/workers/quant-ops-mcp/package-lock.json",
    package_lock_digest: packageLockDigest,
  });
  assert.equal(installedAgents.version, dependency.resolved_version);
});
