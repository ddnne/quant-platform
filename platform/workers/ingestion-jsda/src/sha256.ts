/** SHA-256 lowercase hex. WebCrypto; no algorithm prefix. */
export async function sha256Hex(buf: BufferSource): Promise<string> {
  const dig = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(dig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
