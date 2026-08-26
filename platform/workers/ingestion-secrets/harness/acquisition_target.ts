import { WorkerEntrypoint } from "cloudflare:workers";
import {
  fetchGovernedPage,
  type AcquisitionEnv,
} from "../src/jquants_acquisition";
import type {
  JquantsAcquisitionRequestV2,
  JquantsAcquisitionRpc,
} from "../src/jquants_acquisition_types";

const BODY = new Uint8Array([0x00, 0xff, 0x80, 0x0a, 0x4a, 0x51]);

/** Test-only separate-isolate target using the production RPC implementation. */
export default class AcquisitionTarget
  extends WorkerEntrypoint<Record<string, never>>
  implements JquantsAcquisitionRpc {
  async fetch_governed_page(request: JquantsAcquisitionRequestV2): Promise<Response> {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response(BODY, {
      status: 200,
      headers: {
        "content-type": "application/octet-stream",
        "set-cookie": "upstream=must-not-cross",
        "server": "upstream-must-not-cross",
      },
    })) as typeof fetch;
    const targetEnv = {
      ENVIRONMENT: "production",
      JQUANTS_API_KEY: "harness-api-key-not-for-live",
      JQUANTS_RPC_CURSOR_HMAC_KEY:
        "harness-cursor-hmac-key-not-for-live-00000000000000000000000000000000",
      PROXY_RATE_LIMITER: {
        limit: async () => ({ success: true }),
      } as unknown as RateLimit,
    } as unknown as AcquisitionEnv;
    try {
      return await fetchGovernedPage(
        request,
        targetEnv,
        new Date("2026-08-26T00:00:00.000Z"),
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  }
}
