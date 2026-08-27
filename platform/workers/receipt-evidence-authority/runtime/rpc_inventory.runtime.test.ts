import { describe, expect, it } from "vitest";
import bindingManifest from "../../../../specs/cloudflare/active_worker_bindings.json";
import { ReceiptEvidenceAuthority } from "../src/authority_do";
import { ReceiptAuthorityService } from "../src/index";

describe("Receipt authority manifest-bound RPC inventory", () => {
  it("matches the Service special fetch and exact Durable Object methods", () => {
    const surface = bindingManifest.workers["receipt-evidence-authority"].staging;
    const service = surface.worker_entrypoints.find(
      (row) => row.name === "ReceiptAuthorityService",
    );
    const durable = surface.durable_object_class_handlers.find(
      (row) => row.name === "ReceiptEvidenceAuthority",
    );
    if (service === undefined || durable === undefined) {
      throw new Error("Receipt RPC inventory is absent from binding manifest");
    }
    const serviceMethods = Reflect.ownKeys(ReceiptAuthorityService.prototype)
      .map(String)
      .filter((name) => name !== "constructor");
    expect(service.fetch_reserved_special).toBe(true);
    expect(serviceMethods.includes("fetch")).toBe(true);
    expect(serviceMethods.filter((name) => name !== "fetch").sort()).toEqual(
      [...service.rpc_methods].sort(),
    );
    expect(
      Reflect.ownKeys(ReceiptEvidenceAuthority.prototype)
        .map(String)
        .filter((name) => name !== "constructor")
        .sort(),
    ).toEqual([...durable.rpc_methods].sort());
  });
});
