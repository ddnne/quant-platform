import { describe, expect, it } from "vitest";
import { sha256Hex } from "./sha256";

// FIPS 180-2 appendix B.1 / NIST SHA-256("abc")
const SHA256_ABC =
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

describe("sha256Hex", () => {
  it("matches the known SHA-256 vector for abc", async () => {
    const hex = await sha256Hex(new TextEncoder().encode("abc"));
    expect(hex).toBe(SHA256_ABC);
  });
});
