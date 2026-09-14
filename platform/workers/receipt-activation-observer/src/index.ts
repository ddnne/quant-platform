/// <reference types="@cloudflare/workers-types" />

import {
  handlePrivateJsdaHealthReady,
  handleReceiptActivationObserverRequest,
  type ObserverEnv,
} from "./observer";

export default {
  async fetch(
    request: Request,
    env: ObserverEnv,
    ctx: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/v1/private/jsda-health-ready") {
      return handlePrivateJsdaHealthReady(request, env, ctx);
    }
    return handleReceiptActivationObserverRequest(request, env, ctx);
  },
};
