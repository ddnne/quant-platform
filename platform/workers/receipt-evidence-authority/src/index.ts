import { WorkerEntrypoint } from "cloudflare:workers";
import { executeReceiptRequest } from "./reconcile";
import type {
  ReceiptAuthorityEnv,
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueRequestV1,
  ReceiptIssueResultV1,
  ReceiptPublicKeyRegistrationV1,
  ReceiptRecoveryRequestV1,
} from "./types";

export { ReceiptEvidenceAuthority } from "./authority_do";
export type { ReceiptEvidenceAuthorityRpc } from "./types";

export class ReceiptAuthorityService
  extends WorkerEntrypoint<ReceiptAuthorityEnv>
  implements ReceiptEvidenceAuthorityRpc {
  override fetch(_request: Request): Promise<Response> {
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
    return executeReceiptRequest(this.env, request);
  }

  recover_issue(
    request: ReceiptRecoveryRequestV1,
  ): Promise<ReceiptIssueResultV1> {
    return executeReceiptRequest(this.env, request);
  }

  async public_key_registration(): Promise<ReceiptPublicKeyRegistrationV1> {
    const authority = this.env.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      `receipt:${this.env.ENVIRONMENT}`,
    );
    return authority.public_key_registration();
  }
}

export default ReceiptAuthorityService;
