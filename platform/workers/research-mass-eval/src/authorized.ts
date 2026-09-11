/**
 * Header-only mass-eval token compare. Query `token` is not read.
 * SHA-256 digest both sides, then WebCrypto timingSafeEqual.
 */

import { tokenMatches } from "../../../worker_support/header_token";

export async function authorized(
  request: Request,
  expected?: string,
): Promise<boolean> {
  const got =
    request.headers.get("X-Mass-Eval-Token") ||
    request.headers.get("X-Ingestion-Token") ||
    "";
  return tokenMatches(got, expected);
}
