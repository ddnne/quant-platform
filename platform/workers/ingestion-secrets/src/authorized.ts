/**
 * Header-only ingestion token compare. Query `token` is not read.
 * SHA-256 digest both sides, then WebCrypto timingSafeEqual.
 */

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

export async function authorized(
  request: Request,
  expected?: string,
): Promise<boolean> {
  if (!expected) return false;
  const got = request.headers.get("X-Ingestion-Token") || "";
  return tokenMatches(got, expected);
}
