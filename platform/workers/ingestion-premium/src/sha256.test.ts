import { describe, expect, it } from "vitest";
import { sha256HexFromBytes, sha256HexFromString } from "./sha256";

// FIPS 180-2 appendix B.1 / NIST SHA-256("abc")
const SHA256_ABC =
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

describe("sha256 hex helper", () => {
  it("matches the known SHA-256 vector for abc", async () => {
    const fromString = await sha256HexFromString("abc");
    const fromBytes = await sha256HexFromBytes(new TextEncoder().encode("abc"));
    expect(fromString).toBe(SHA256_ABC);
    expect(fromBytes).toBe(SHA256_ABC);
  });
});
