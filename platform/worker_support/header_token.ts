/**
 * SHA-256 digest both sides, then WebCrypto timingSafeEqual.
 * Missing or empty expected or provided is false.
 */

export async function tokenMatches(
  provided: string | null | undefined,
  expected?: string,
): Promise<boolean> {
  if (!expected || !provided) return false;
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}
