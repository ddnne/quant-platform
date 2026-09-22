import { WorkerEntrypoint } from "cloudflare:workers";
import { canonicalDigest } from "./canonical";
import { issueIdentity, requireReceiptRequest } from "./receipt_request_identity";
import { STRUCTURED_SLICE_INCOMPLETE } from "./structured_reconciliation";
import type {
  ReceiptAuthorityEnv,
  ReceiptAuthorityServiceRpc,
  ReceiptAuditRecoveryBeginResultV1,
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuditRecoveryCanaryResultV1,
  ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueRequestV1,
  ReceiptIssueResultV1,
  ReceiptPublicKeyRegistrationV1,
  ReceiptRecoveryRequestV1,
  ReceiptRequestV1,
  ReceiptServiceResultV1,
} from "./types";

export { ReceiptEvidenceAuthority } from "./authority_do";
export type { ReceiptEvidenceAuthorityRpc } from "./types";

function receiptAuthorityStub(
  env: ReceiptAuthorityEnv,
): ReceiptEvidenceAuthorityRpc {
  const namespace = env.RECEIPT_EVIDENCE_AUTHORITY_DO;
  return namespace.getByName(`receipt:${env.ENVIRONMENT}`);
}

async function serviceResult(
  result: Promise<ReceiptIssueResultV1>,
  request: ReceiptRequestV1,
): Promise<ReceiptServiceResultV1> {
  try {
    return await result;
  } catch (error) {
    // A saved bounded slice is normal progress, not a failed service RPC.
    // Preserve every other exception, including runtime cancellation.
    if (!(error instanceof Error) || error.message !== STRUCTURED_SLICE_INCOMPLETE) {
      throw error;
    }
    return {
      schema_version: "receipt-evidence-continuation/v1",
      operation_id: await canonicalDigest(issueIdentity(requireReceiptRequest(request))),
      state: "CONTINUATION_REQUIRED",
    };
  }
}

export class ReceiptAuthorityService
  extends WorkerEntrypoint<ReceiptAuthorityEnv>
  implements ReceiptAuthorityServiceRpc {
  override fetch(request: Request): Promise<Response> {
    void request;
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
  ): Promise<ReceiptServiceResultV1> {
    if (this.env.AUTHORITY_MODE !== "ACTIVE") {
      return Promise.reject(
        new Error("receipt evidence authority is PENDING activation"),
      );
    }
    const authority = receiptAuthorityStub(this.env);
    return serviceResult(authority.issue_for_segment(request), request);
  }

  recover_issue(
    request: ReceiptRecoveryRequestV1,
  ): Promise<ReceiptServiceResultV1> {
    if (this.env.AUTHORITY_MODE !== "ACTIVE") {
      return Promise.reject(
        new Error("receipt evidence authority is PENDING activation"),
      );
    }
    const authority = receiptAuthorityStub(this.env);
    return serviceResult(authority.recover_issue(request), request);
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
