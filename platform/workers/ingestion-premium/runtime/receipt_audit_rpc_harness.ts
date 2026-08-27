import type {
  PremiumReceiptAuditEvidenceRpc,
  PremiumReceiptOperatorRpc,
} from "../src/index";

export {
  PremiumReceiptAuditEvidenceService,
  PremiumReceiptOperatorService,
} from "../src/index";

type HarnessEnv = {
  AUDIT_ONLY: PremiumReceiptAuditEvidenceRpc;
};

export default {
  async fetch(request: Request, env: HarnessEnv): Promise<Response> {
    if (new URL(request.url).pathname !== "/attempt-registration") {
      return new Response(null, { status: 404 });
    }
    try {
      await (env.AUDIT_ONLY as unknown as PremiumReceiptOperatorRpc)
        .pending_public_key_registration();
      return new Response("unexpected registration capability", { status: 500 });
    } catch (error) {
      return new Response(error instanceof Error ? error.message : "RPC rejected", {
        status: 409,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }
  },
};
