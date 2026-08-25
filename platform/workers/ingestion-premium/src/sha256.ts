/** SHA-256 lowercase hex. WebCrypto; no algorithm prefix. */

export async function sha256HexFromBytes(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export async function sha256HexFromString(text: string): Promise<string> {
  return sha256HexFromBytes(new TextEncoder().encode(text));
}
