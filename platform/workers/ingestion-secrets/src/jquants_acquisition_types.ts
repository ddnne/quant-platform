export type AcquisitionEnvironment = "staging" | "production";

/**
 * Closed caller surface. URL, method, query, headers, credentials, redirects,
 * pagination values, and evidence assertions are intentionally absent.
 */
export type JquantsAcquisitionRequestV2 = {
  schema_version: "jquants-acquisition-rpc-request/v2";
  environment: AcquisitionEnvironment;
  operation: "fetch_governed_page";
  dataset_id: string;
  segment_id: string;
  segment_start: string;
  segment_end: string;
  acquisition_nonce: string;
  source_capability_digest: string;
  dataset_contract_digest: string;
  coverage_policy_digest: string;
  query_contract_digest: string;
  target_registry_digest: string;
  continuation_token: string | null;
};

/** Build-isolated caller type for a future Service Binding. */
export interface JquantsAcquisitionRpc {
  fetch_governed_page(request: JquantsAcquisitionRequestV2): Promise<Response>;
}

export type AcquisitionEvidenceState =
  | "RAW_PAGE"
  | "RAW_ONLY"
  | "REJECTED"
  | "FAILED";

export type AcquisitionPaginationState =
  | "CONTINUATION"
  | "EXHAUSTED"
  | "UNKNOWN"
  | "NOT_APPLICABLE";

export type AcquisitionBodyKind =
  | "UPSTREAM_EXACT_BYTES"
  | "TARGET_ERROR_JSON";

/**
 * Canonical metadata field set.  The metadata digest is SHA-256 over this
 * object using UTF-8, lexicographically sorted keys, and no whitespace.
 */
export type AcquisitionResponseMetadataV2 = {
  schema_version: "jquants-acquisition-rpc-response-metadata/v2";
  evidence_state: AcquisitionEvidenceState;
  environment: AcquisitionEnvironment | null;
  dataset_id: string | null;
  segment_id: string | null;
  segment_start: string | null;
  segment_end: string | null;
  request_digest: string | null;
  request_identity_digest: string | null;
  previous_request_digest: string | null;
  acquisition_id: string | null;
  acquisition_issued_at: string | null;
  acquisition_expires_at: string | null;
  target_registry_digest: string | null;
  source_capability_digest: string | null;
  dataset_contract_digest: string | null;
  coverage_policy_digest: string | null;
  query_contract_digest: string | null;
  cursor_key_id: string | null;
  slice_date: string | null;
  query_digest: string | null;
  page_ordinal: number | null;
  slice_ordinal: number | null;
  provider_page_ordinal: number | null;
  provider_pagination_state: AcquisitionPaginationState;
  upstream_http_status: number | null;
  body_digest: string;
  body_kind: AcquisitionBodyKind;
  pagination_state: AcquisitionPaginationState;
  continuation_token: string | null;
  content_type: "application/json" | "application/octet-stream";
  redirect_count: number;
  previous_chain_digest: string | null;
  chain_digest: string | null;
};

export type AcquisitionResponseMetadataWithDigestV2 =
  AcquisitionResponseMetadataV2 & { metadata_digest: string };
