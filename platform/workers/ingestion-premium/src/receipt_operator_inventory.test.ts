import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { PremiumReceiptOperatorService } from "./index";

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
    expect(rows).toHaveLength(1);
    const inventory = rows[0]!;
    expect(inventory).toMatchObject({
      name: "PremiumReceiptOperatorService",
      fetch_reserved_special: false,
      rpc_methods: [
        "pending_public_key_registration",
        "staging_recovery_audit_attestation",
      ],
    });
    expect(
      Reflect.ownKeys(PremiumReceiptOperatorService.prototype)
        .map(String)
        .filter((name) => name !== "constructor")
        .sort(),
    ).toEqual([...inventory.rpc_methods].sort());
  });
});
