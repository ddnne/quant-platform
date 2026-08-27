import type IngestionSecretsWorker from "../../ingestion-secrets/src/index";

export type AuthorityEnvironment = "staging" | "production";
export type AuthorityMode = "PENDING" | "ACTIVE";

export type ReceiptIssueRequestV1 = {
  schema_version: "receipt-evidence-issue-request/v1";
  operation: "issue_for_segment";
  environment: AuthorityEnvironment;
  dataset_id: string;
  segment_id: string;
  request_nonce: string;
};

export type ReceiptRecoveryRequestV1 = Omit<
  ReceiptIssueRequestV1,
  "operation"
> & { operation: "recover_issue" };

export type ReceiptRequestV1 =
  | ReceiptIssueRequestV1
  | ReceiptRecoveryRequestV1;

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type SignedReceiptClaimsV2 = {
  version: "signed-receipt-claims/v2";
  coverage_policy_version: "collection-coverage/v3";
  source: "jquants";
  dataset: string;
  segment_id: string;
  segment_start: string;
  segment_end: string;
  expected_scope: Record<string, JsonValue>;
  expected_items: number | null;
  observed_items: number;
  raw_page_count: number;
  raw_count: number;
  structured_count: number;
  status: "SUCCESS";
  error: null;
  pagination_exhausted: true;
  discovery_exhausted: true;
  source_request_digest: string;
  raw_manifest_digest: string;
  raw_digest: string;
  structured_digest: string;
  parser_normalizer_version: "coverage-receipt/v4-ed25519-closure";
  structured_generation: number;
  scope_digest: string;
  observation_digest: string;
  run_id: number;
  issuer_id: string;
  issued_at: string;
  checked_at: string;
  extra_digests: Record<string, string>;
};

export type UnsignedReceiptClaimsV2 = Omit<
  SignedReceiptClaimsV2,
  "version" | "parser_normalizer_version" | "issuer_id" | "issued_at"
>;

export type SignedReceiptEnvelopeV2 = {
  eligibility: "TRUSTED_COLLECTION";
  issuer_class: "SignedReceiptAuthority";
  issuer_key_id: string;
  issuer_id: string;
  parser_normalizer_version: "coverage-receipt/v4-ed25519-closure";
  signed_body_b64: string;
  signature: string;
  body_digest: string;
  issued_at: string;
  checked_at: string;
  source_request_digest: string;
  raw_manifest_digest: string;
  raw: string;
  structured_generation: number;
  structured_digest: string;
  scope_digest: string;
  observation_digest: string;
  extra_digests: Record<string, string>;
  [extraDigest: string]: JsonValue;
};

export type CollectionReceiptV2 = {
  source: "jquants";
  dataset: string;
  segment_id: string;
  segment_start: string;
  segment_end: string;
  expected_scope: Record<string, JsonValue>;
  expected_items: number | null;
  observed_items: number;
  raw_page_count: number;
  raw_row_count: number;
  structured_row_count: number;
  pagination_exhausted: true;
  digests: SignedReceiptEnvelopeV2;
  run_id: number;
  status: "SUCCESS";
  error: null;
  checked_at: string;
};

export type ReceiptIssueResultV1 = {
  schema_version: "receipt-evidence-issue-result/v1";
  operation_id: string;
  state: "FINALIZED";
  replayed: boolean;
  receipt_digest: string;
  receipt: CollectionReceiptV2;
};

export type ReceiptPublicKeyRegistrationV1 = {
  schema_version: "receipt-public-key-registration/v1";
  purpose: "receipt_verification";
  environment: AuthorityEnvironment;
  authority_status: "PENDING";
  key_id: string;
  key_generation: number;
  algorithm: "Ed25519";
  public_key_base64: string;
  private_key_extractable: false;
  status: "pending";
  generated_at: string;
  registration_digest: string;
};

export interface ReceiptEvidenceAuthorityRpc {
  issue_for_segment(request: ReceiptIssueRequestV1): Promise<ReceiptIssueResultV1>;
  recover_issue(request: ReceiptRecoveryRequestV1): Promise<ReceiptIssueResultV1>;
  public_key_registration(): Promise<ReceiptPublicKeyRegistrationV1>;
}

export type ReceiptAuthorityEnv = Omit<
  Cloudflare.Env,
  "ENVIRONMENT" | "AUTHORITY_MODE" | "JQUANTS_ACQUISITION"
> & {
  ENVIRONMENT: AuthorityEnvironment;
  AUTHORITY_MODE: AuthorityMode;
  ACTIVATED_KEY_ID?: string;
  RECEIPT_KEY_WRAP_KEY: string;
  RECEIPT_KEY_GENERATION: string;
  JQUANTS_ACQUISITION: Service<IngestionSecretsWorker>;
};
