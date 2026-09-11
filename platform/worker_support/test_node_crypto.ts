import { timingSafeEqual } from "node:crypto";

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
