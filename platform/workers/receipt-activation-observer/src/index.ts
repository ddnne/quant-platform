/// <reference types="@cloudflare/workers-types" />

import {
  handleReceiptActivationObserverRequest,
  type ObserverEnv,
} from "./observer";

export default {
  fetch(
    request: Request,
    env: ObserverEnv,
    ctx: ExecutionContext,
  ): Promise<Response> {
    return handleReceiptActivationObserverRequest(request, env, ctx);
  },
};
