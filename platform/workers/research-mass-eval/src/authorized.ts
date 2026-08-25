/**
 * Header-only mass-eval token compare. Query `token` is not read.
 * SHA-256 digest both sides, then XOR length-safe equality.
 */

function timingSafeEqualBytes(a: ArrayBuffer, b: ArrayBuffer): boolean {
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(provided)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  return timingSafeEqualBytes(a, b);
}

export async function authorized(
  request: Request,
  expected?: string,
): Promise<boolean> {
  if (!expected) return false;
  const got =
    request.headers.get("X-Mass-Eval-Token") ||
    request.headers.get("X-Ingestion-Token") ||
    "";
  if (!got) return false;
  return tokenMatches(got, expected);
}
