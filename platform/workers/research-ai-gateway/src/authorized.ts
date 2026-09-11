/** Optional closed HTTP defense: GATEWAY_TOKEN vs X-Gateway-Token only. */

import { tokenMatches } from "../../../worker_support/header_token";

export async function authorized(
  request: Request,
  env: { GATEWAY_TOKEN?: string },
): Promise<boolean> {
  const got = request.headers.get("X-Gateway-Token") || "";
  return tokenMatches(got, env.GATEWAY_TOKEN);
}
