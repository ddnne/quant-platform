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

export type SignedReceiptClaimsV3 = {
  version: "signed-receipt-claims/v3";
  environment: AuthorityEnvironment;
  authority_instance_digest: string;
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

export type UnsignedReceiptClaimsV3 = Omit<
  SignedReceiptClaimsV3,
  "version" | "parser_normalizer_version" | "issuer_id" | "issued_at"
>;

export type SignedReceiptEnvelopeV3 = {
  eligibility: "TRUSTED_COLLECTION";
  issuer_class: "SignedReceiptAuthority";
  issuer_key_id: string;
  issuer_id: string;
  environment: AuthorityEnvironment;
  authority_instance_digest: string;
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

export type CollectionReceiptV3 = {
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
  digests: SignedReceiptEnvelopeV3;
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
  receipt: CollectionReceiptV3;
};

type ReceiptAuditRecoveryCanaryRequestBaseV1 = {
  schema_version: "receipt-audit-recovery-canary-request/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  environment: "staging";
  caller_source_sha: string;
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
  request_nonce: string;
};

export type ReceiptAuditRecoveryCanaryBeginRequestV1 =
  ReceiptAuditRecoveryCanaryRequestBaseV1 & {
    operation: "begin_audit_recovery_canary";
  };

export type ReceiptAuditRecoveryCanaryRecoverRequestV1 =
  ReceiptAuditRecoveryCanaryRequestBaseV1 & {
    operation: "recover_audit_recovery_canary";
  };

export type ReceiptAuditRecoveryInitialResultV1 = {
  schema_version: "receipt-audit-recovery-initial-result/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  environment: "staging";
  operation_id: string;
  request_nonce: string;
  state: "RECOVERY_REQUIRED";
  initial_state_digest: string;
  created_at: string;
};

export type ReceiptAuditRecoveryBeginResultV1 = {
  schema_version: "receipt-audit-recovery-begin-result/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  operation_id: string;
  initial_result_digest: string;
  initial_result: ReceiptAuditRecoveryInitialResultV1;
  rpc_replayed: boolean;
};

export type ReceiptAuditRecoveryAttestationClaimsV1 = {
  schema_version: "receipt-audit-recovery-attestation-claims/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  environment: "staging";
  authority_instance_digest: string;
  authority_source_sha: string;
  authority_worker_version_id: string;
  authority_worker_version_tag: string;
  caller_source_sha: string;
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
  operation_id: string;
  request_nonce: string;
  initial_state: "RECOVERY_REQUIRED";
  initial_state_digest: string;
  initial_result_digest: string;
  initial_created_at: string;
  recovery_event: "RECOVERY_COMPLETED";
  recovery_event_digest: string;
  recovery_event_tail_digest: string;
  recovered_at: string;
  first_recovery_state: "RECOVERED_PENDING_REPLAY";
  first_recovery_result_digest: string;
  replay_event: "REPLAY_CONFIRMED";
  replay_event_digest: string;
  replay_event_tail_digest: string;
  replay_confirmed_at: string;
  replayed: true;
  final_state: "AUDIT_FINALIZED";
  issuer_key_id: string;
  issued_at: string;
};

export type ReceiptAuditFirstRecoveryResultV1 = {
  schema_version: "receipt-audit-first-recovery-result/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  environment: "staging";
  operation_id: string;
  request_nonce: string;
  initial_state_digest: string;
  initial_result_digest: string;
  recovery_event_digest: string;
  recovery_event_tail_digest: string;
  recovered_at: string;
  state: "RECOVERED_PENDING_REPLAY";
};

export type ReceiptAuditRecoveryPendingReplayResultV1 = {
  schema_version: "receipt-audit-recovery-pending-replay-result/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  operation_id: string;
  state: "RECOVERED_PENDING_REPLAY";
  first_recovery_result_digest: string;
  first_recovery_result: ReceiptAuditFirstRecoveryResultV1;
  rpc_replayed: false;
};

export type ReceiptAuditRecoveryAttestationV1 = {
  schema_version: "receipt-audit-recovery-attestation/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  environment: "staging";
  issuer_class: "ReceiptEvidenceAuthorityAuditSigner";
  issuer_key_id: string;
  authority_instance_digest: string;
  signed_claims_base64: string;
  signed_claims_digest: string;
  signature: string;
  issued_at: string;
};

export type ReceiptAuditRecoveryResultV1 = {
  schema_version: "receipt-audit-recovery-result/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  operation_id: string;
  final_state: "AUDIT_FINALIZED";
  signed_attestation_digest: string;
  signed_attestation: ReceiptAuditRecoveryAttestationV1;
  rpc_replayed: true;
};

export type ReceiptAuditRecoveryCanaryResultV1 =
  | ReceiptAuditRecoveryPendingReplayResultV1
  | ReceiptAuditRecoveryResultV1;

export type ReceiptAuthorityOperationState =
  | "COLLECTING"
  | "ISSUED_PENDING_FINALIZE"
  | "FINALIZED";

/**
 * Internal durable snapshot.  This is deliberately absent from both RPC
 * interfaces below: callers can request a governed dataset/segment operation,
 * but cannot supply or recover a signable claims DTO.
 */
export type ReceiptAuthorityOperationSnapshot = {
  operation_id: string;
  request_digest: string;
  capture_attempt_id: string;
  capture_attempt_ordinal: number;
  acquisition_nonce: string;
  collection_started_at: string;
  capture_key: string | null;
  capture_digest: string | null;
  state: ReceiptAuthorityOperationState;
  claims: UnsignedReceiptClaimsV3 | null;
  envelope: SignedReceiptEnvelopeV3 | null;
  envelope_digest: string | null;
  receipt_digest: string | null;
  result: ReceiptIssueResultV1 | null;
};

export type ReceiptAuthorityIssuedRecord = {
  claims: UnsignedReceiptClaimsV3;
  envelope: SignedReceiptEnvelopeV3;
  envelope_digest: string;
};

export type ReceiptPublicKeyRegistrationV1 = {
  schema_version: "receipt-public-key-registration/v1";
  purpose: "receipt_verification";
  environment: AuthorityEnvironment;
  authority_instance_digest: string;
  authority_resource_digest: string;
  authority_status: "PENDING";
  action: "public_key_registration";
  deployment_source_sha: string;
  authority_worker_version_id: string;
  authority_worker_version_tag: string;
  operation_binding_digest: string;
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
  begin_audit_recovery_canary(
    request: ReceiptAuditRecoveryCanaryBeginRequestV1,
  ): Promise<ReceiptAuditRecoveryBeginResultV1>;
  recover_audit_recovery_canary(
    request: ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ): Promise<ReceiptAuditRecoveryCanaryResultV1>;
  public_key_registration(): Promise<ReceiptPublicKeyRegistrationV1>;
}

export type ReceiptAuthorityEnv = Omit<
  Cloudflare.Env,
  | "ENVIRONMENT"
  | "AUTHORITY_MODE"
  | "JQUANTS_ACQUISITION"
  | "AUTHORITY_EVIDENCE_BUCKET"
  | "RECEIPT_EVIDENCE_AUTHORITY_DO"
> & {
  ENVIRONMENT: AuthorityEnvironment;
  AUTHORITY_MODE: AuthorityMode;
  ACTIVATED_KEY_ID?: string;
  RECEIPT_KEY_WRAP_KEY: string;
  RECEIPT_KEY_GENERATION: string;
  AUTHORITY_EVIDENCE_BUCKET: R2Bucket;
  // Keep the generated binding surface while narrowing the recursive class
  // stub to the only RPC methods this entrypoint is allowed to invoke.
  RECEIPT_EVIDENCE_AUTHORITY_DO: {
    getByName(name: string): ReceiptEvidenceAuthorityRpc;
  };
  JQUANTS_ACQUISITION: Service<IngestionSecretsWorker>;
};
