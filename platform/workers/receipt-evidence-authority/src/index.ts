import { WorkerEntrypoint } from "cloudflare:workers";
import type {
  ReceiptAuthorityEnv,
  ReceiptAuditRecoveryBeginResultV1,
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuditRecoveryCanaryResultV1,
  ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueRequestV1,
  ReceiptIssueResultV1,
  ReceiptPublicKeyRegistrationV1,
  ReceiptRecoveryRequestV1,
} from "./types";

export { ReceiptEvidenceAuthority } from "./authority_do";
export type { ReceiptEvidenceAuthorityRpc } from "./types";

function receiptAuthorityStub(
  env: ReceiptAuthorityEnv,
): ReceiptEvidenceAuthorityRpc {
  const namespace = env.RECEIPT_EVIDENCE_AUTHORITY_DO;
  return namespace.getByName(`receipt:${env.ENVIRONMENT}`);
}

export class ReceiptAuthorityService
  extends WorkerEntrypoint<ReceiptAuthorityEnv>
  implements ReceiptEvidenceAuthorityRpc {
  override fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" || url.pathname === "/health/ready") {
      if (request.method !== "GET") {
        return Promise.resolve(new Response(null, {
          status: 405,
          headers: { allow: "GET", "cache-control": "no-store" },
        }));
      }
      return Promise.resolve(Response.json(
        { ok: true, live: true, worker: "receipt-evidence-authority" },
        { headers: { "cache-control": "no-store" } },
      ));
    }
    return Promise.resolve(new Response(null, {
      status: 404,
      headers: {
        "cache-control": "no-store",
        "content-type": "text/plain; charset=utf-8",
      },
    }));
  }

  issue_for_segment(
    request: ReceiptIssueRequestV1,
  ): Promise<ReceiptIssueResultV1> {
    if (this.env.AUTHORITY_MODE !== "ACTIVE") {
      return Promise.reject(
        new Error("receipt evidence authority is PENDING activation"),
      );
    }
    const authority = receiptAuthorityStub(this.env);
    return authority.issue_for_segment(request);
  }

  recover_issue(
    request: ReceiptRecoveryRequestV1,
  ): Promise<ReceiptIssueResultV1> {
    if (this.env.AUTHORITY_MODE !== "ACTIVE") {
      return Promise.reject(
        new Error("receipt evidence authority is PENDING activation"),
      );
    }
    const authority = receiptAuthorityStub(this.env);
    return authority.recover_issue(request);
  }

  begin_audit_recovery_canary(
    request: ReceiptAuditRecoveryCanaryBeginRequestV1,
  ): Promise<ReceiptAuditRecoveryBeginResultV1> {
    if (
      this.env.ENVIRONMENT !== "staging" ||
      this.env.AUTHORITY_MODE !== "ACTIVE"
    ) {
      return Promise.reject(
        new Error("Receipt audit recovery canary is not ACTIVE staging"),
      );
    }
    return receiptAuthorityStub(this.env).begin_audit_recovery_canary(request);
  }

  recover_audit_recovery_canary(
    request: ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ): Promise<ReceiptAuditRecoveryCanaryResultV1> {
    if (
      this.env.ENVIRONMENT !== "staging" ||
      this.env.AUTHORITY_MODE !== "ACTIVE"
    ) {
      return Promise.reject(
        new Error("Receipt audit recovery canary is not ACTIVE staging"),
      );
    }
    return receiptAuthorityStub(this.env).recover_audit_recovery_canary(request);
  }

  async public_key_registration(): Promise<ReceiptPublicKeyRegistrationV1> {
    if (
      this.env.AUTHORITY_MODE !== "PENDING" ||
      this.env.ACTIVATED_KEY_ID !== undefined
    ) {
      throw new Error(
        "receipt public-key registration requires unactivated PENDING mode",
      );
    }
    const authority = receiptAuthorityStub(this.env);
    return authority.public_key_registration();
  }
}

export default ReceiptAuthorityService;
