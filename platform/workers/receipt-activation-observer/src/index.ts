/// <reference types="@cloudflare/workers-types" />

import {
  collectPrivateJsdaReadiness,
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
      if (ctx.access === undefined || typeof ctx.access.aud !== "string" || ctx.access.aud.length === 0) {
        return new Response(JSON.stringify({
          schema_version: "receipt-activation-observer-error/v1",
          purpose: "receipt_authority_recovery_canary",
          eligibility: "AUDIT_ONLY",
          error: "ACCESS_REQUIRED",
        }), {
          status: 403,
          headers: {
            "Cache-Control": "no-store",
            "Content-Type": "application/json; charset=utf-8",
          },
        });
      }
      if (env.ENVIRONMENT === "disabled") {
        return new Response(JSON.stringify({
          schema_version: "receipt-activation-observer-error/v1",
          purpose: "receipt_authority_recovery_canary",
          eligibility: "AUDIT_ONLY",
          error: "OBSERVER_NOT_ACTIVE",
        }), { status: 503, headers: { "Cache-Control": "no-store", "Content-Type": "application/json; charset=utf-8" } });
      }
      try {
        const observation = await collectPrivateJsdaReadiness(env);
        return new Response(JSON.stringify(observation), {
          status: 200,
          headers: {
            "Cache-Control": "no-store",
            "Content-Type": "application/json; charset=utf-8",
          },
        });
      } catch {
        return new Response(JSON.stringify({
          schema_version: "receipt-activation-observer-error/v1",
          purpose: "receipt_authority_recovery_canary",
          eligibility: "AUDIT_ONLY",
          error: "JSDA_COLLECTOR_UNAVAILABLE",
        }), { status: 503, headers: { "Cache-Control": "no-store", "Content-Type": "application/json; charset=utf-8" } });
      }
    }
    return handleReceiptActivationObserverRequest(request, env, ctx);
  },
};
