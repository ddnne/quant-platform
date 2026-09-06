import type { JsdaQueueJob } from "./queue_contract";
import type {
  ReceiptEvidenceAuthorityRpc,
} from "../../receipt-evidence-authority/src/types";

/** Generated bindings are the base; only secret and Queue body typing are refined. */
export type JsdaWorkerEnv = Omit<
  Cloudflare.Env,
  | "JSDA_QUEUE"
  | "RECEIPT_EVIDENCE_AUTHORITY"
  | "RECEIPT_AUTHORITY_ENVIRONMENT"
  | "RECEIPT_AUTHORITY_OPERATION_MODE"
> & {
  JSDA_QUEUE: Queue<JsdaQueueJob>;
  JSDA_DLQ_QUEUE: string;
  INGESTION_RUN_TOKEN?: string;
  RECEIPT_EVIDENCE_AUTHORITY?: Pick<
    ReceiptEvidenceAuthorityRpc,
    "issue_for_segment" | "recover_issue"
  >;
  RECEIPT_AUTHORITY_ENVIRONMENT?: "staging" | "production";
  RECEIPT_AUTHORITY_OPERATION_MODE?: "PENDING" | "ACTIVE";
};
