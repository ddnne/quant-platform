import type {
  PremiumReceiptAuditEvidenceRpc,
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
    if (env.AUDIT_ONLY === undefined) {
      return new Response("audit evidence capability is missing", { status: 500 });
    }
    return new Response(
      "AUDIT_ONLY does not implement pending_public_key_registration",
      { status: 409, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  },
};
