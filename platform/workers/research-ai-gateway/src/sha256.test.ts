import { describe, expect, it, vi } from "vitest";
import { sha256Hex } from "./sha256";

describe("sha256Hex", () => {
  it("NIST abc is lowercase hex with no algorithm prefix via subtle.digest", async () => {
    const digest = vi.spyOn(crypto.subtle, "digest");
    const hash = await sha256Hex("abc");
    expect(digest).toHaveBeenCalledTimes(1);
    const [algorithm, data] = digest.mock.calls[0];
    expect(algorithm).toBe("SHA-256");
    expect(data).toBeInstanceOf(Uint8Array);
    digest.mockRestore();

    // FIPS 180-4 SHA-256("abc") — hex only; callers prefix sha256: themselves.
    expect(hash).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(hash.startsWith("sha256:")).toBe(false);
    expect(hash).toHaveLength(64);
  });
});
