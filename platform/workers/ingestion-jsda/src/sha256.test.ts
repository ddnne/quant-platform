import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { sha256Hex } from "./sha256";

const here = dirname(fileURLToPath(import.meta.url));

// FIPS 180-2 appendix B.1 / NIST SHA-256("abc")
const SHA256_ABC =
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

describe("sha256Hex", () => {
  it("matches the known SHA-256 vector for abc and does not prefix", async () => {
    const hex = await sha256Hex(new TextEncoder().encode("abc"));
    expect(hex).toBe(SHA256_ABC);
    expect(hex).not.toMatch(/^sha256:/);
    expect(hex).not.toMatch(/^hash:/);
  });

  it("source uses WebCrypto and not Node createHash", () => {
    const src = readFileSync(join(here, "sha256.ts"), "utf8");
    expect(src).toContain("crypto.subtle.digest");
    expect(src).not.toMatch(/createHash/);
    expect(src).not.toMatch(/node:crypto/);
  });
});
