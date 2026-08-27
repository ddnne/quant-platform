import { env } from "cloudflare:workers";
import { reset, SELF } from "cloudflare:test";
import { afterEach, describe, expect, it } from "vitest";
import bindingManifest from "../../../../specs/cloudflare/active_worker_bindings.json";

const runtimeEnv = env as { DB: D1Database };

async function sentinelRows(): Promise<unknown[]> {
  const result = await runtimeEnv.DB.prepare(
    "SELECT id,value FROM audit_capability_sentinel ORDER BY id",
  ).all();
  return result.results;
}

afterEach(async () => {
  await reset();
});

describe("Premium audit-only WorkerEntrypoint capability", () => {
  it("rejects registration over actual workerd RPC without a D1 side effect", async () => {
    await runtimeEnv.DB.exec(
      "CREATE TABLE audit_capability_sentinel (id INTEGER PRIMARY KEY, value TEXT NOT NULL);" +
        "INSERT INTO audit_capability_sentinel(id,value) VALUES (1,'unchanged');",
    );
    const before = await sentinelRows();

    const response = await SELF.fetch(
      new Request("https://premium.test/attempt-registration"),
    );
    expect(response.status).toBe(409);
    expect(await response.text()).toContain("does not implement");

    expect(await sentinelRows()).toEqual(before);
    const harness = bindingManifest.test_harness_surfaces["ingestion-premium"];
    expect(harness.services).toEqual([{
      binding: "AUDIT_ONLY",
      service: "quant-platform-ingestion-premium-test",
      entrypoint: "PremiumReceiptAuditEvidenceService",
    }]);
    expect(harness.secret_names).toEqual([]);
    expect(harness.worker_entrypoints).toEqual([
      {
        name: "PremiumReceiptOperatorService",
        handlers: ["class"],
        fetch_reserved_special: false,
        rpc_methods: ["pending_public_key_registration"],
      },
      {
        name: "PremiumReceiptAuditEvidenceService",
        handlers: ["class"],
        fetch_reserved_special: false,
        rpc_methods: ["staging_recovery_audit_evidence"],
      },
    ]);
  });
});
