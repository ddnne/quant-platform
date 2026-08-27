import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  PremiumReceiptAuditEvidenceService,
  PremiumReceiptOperatorService,
} from "./index";

type BindingManifest = {
  workers: {
    "ingestion-premium": {
      staging: {
        worker_entrypoints: Array<{
          name: string;
          fetch_reserved_special: boolean;
          rpc_methods: string[];
        }>;
      };
    };
  };
};

describe("Premium Receipt operator manifest-bound RPC inventory", () => {
  it("matches the exact no-fetch named entrypoint surface", () => {
    const manifest = JSON.parse(readFileSync(new URL(
      "../../../../specs/cloudflare/active_worker_bindings.json",
      import.meta.url,
    ), "utf8")) as BindingManifest;
    const rows = manifest.workers["ingestion-premium"].staging.worker_entrypoints;
    expect(rows).toHaveLength(2);
    const operatorInventory = rows.find(
      (row) => row.name === "PremiumReceiptOperatorService",
    );
    const auditInventory = rows.find(
      (row) => row.name === "PremiumReceiptAuditEvidenceService",
    );
    expect(operatorInventory).toMatchObject({
      fetch_reserved_special: false,
      rpc_methods: ["pending_public_key_registration"],
    });
    expect(auditInventory).toMatchObject({
      fetch_reserved_special: false,
      rpc_methods: ["staging_recovery_audit_evidence"],
    });
    expect(
      Reflect.ownKeys(PremiumReceiptOperatorService.prototype)
        .map(String)
        .filter((name) => name !== "constructor")
        .sort(),
    ).toEqual([...(operatorInventory?.rpc_methods ?? [])].sort());
    expect(
      Reflect.ownKeys(PremiumReceiptAuditEvidenceService.prototype)
        .map(String)
        .filter((name) => name !== "constructor")
        .sort(),
    ).toEqual([...(auditInventory?.rpc_methods ?? [])].sort());
  });
});
