import { timingSafeEqual } from "node:crypto";

// Install the baseline before per-test stubs capture it. Restoring those stubs
// must not restore real HTTP access to acquisition/export/provider endpoints.
globalThis.fetch = async () => {
  throw new Error("Node unit HTTP disabled; inject or stub the transport");
};

const subtle = globalThis.crypto.subtle as SubtleCrypto & {
  timingSafeEqual?: (a: ArrayBuffer, b: ArrayBuffer) => boolean;
};

if (typeof subtle.timingSafeEqual !== "function") {
  Object.defineProperty(subtle, "timingSafeEqual", {
    value: (a: ArrayBuffer, b: ArrayBuffer): boolean => {
      if (a.byteLength !== b.byteLength) return false;
      return timingSafeEqual(new Uint8Array(a), new Uint8Array(b));
    },
  });
}
