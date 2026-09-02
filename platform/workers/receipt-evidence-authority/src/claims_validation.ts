import {
  canonicalDigest,
  exactKeys,
  isPlainObject,
  isSha256,
} from "./canonical";
import {
  issueIdentity,
  requireReceiptRequest,
  segmentMatchesGrain,
} from "./receipt_request_identity";
import type {
  ReceiptIssueRequestV1,
  UnsignedReceiptClaimsV3,
} from "./types";

const UNSIGNED_CLAIM_KEYS = [
  "environment",
  "authority_instance_digest",
  "coverage_policy_version",
  "source",
  "contract_id",
  "dataset",
  "segment_id",
  "segment_start",
  "segment_end",
  "receipt_issue_digest",
  "artifact_key",
  "artifact_byte_count",
  "manifest_key",
  "manifest_byte_count",
  "raw_manifest_key",
  "raw_manifest_byte_count",
  "raw_byte_count",
  "natural_key_digest",
  "expected_scope",
  "expected_items",
  "observed_items",
  "raw_page_count",
  "raw_count",
  "structured_count",
  "status",
  "error",
  "pagination_exhausted",
  "discovery_exhausted",
  "source_request_digest",
  "raw_manifest_digest",
  "raw_digest",
  "structured_digest",
  "structured_generation",
  "scope_digest",
  "observation_digest",
  "run_id",
  "checked_at",
  "extra_digests",
] as const;

const REQUIRED_ACQUISITION_DIGESTS = [
  "acquisition_collection_manifest_file_digest",
  "acquisition_collection_digest",
  "acquisition_terminal_chain_digest",
  "product_artifact_digest",
  "product_manifest_digest",
] as const;
const REQUIRED_MASTER_CALENDAR_DIGESTS = [
  "official_calendar_evidence_digest",
  "official_calendar_raw_body_digest",
  "official_calendar_query_digest",
  "official_business_dates_digest",
  "official_calendar_binding_digest",
] as const;

/** Validate only DO-derived claims immediately before signing. */
function requireDerivedClaims(
  value: unknown,
  persistedRequest: ReceiptIssueRequestV1,
): UnsignedReceiptClaimsV3 {
  if (!isPlainObject(value) || !exactKeys(value, UNSIGNED_CLAIM_KEYS)) {
    throw new TypeError("receipt authority claims are not closed");
  }
  const extraDigests = isPlainObject(value.extra_digests)
    ? value.extra_digests
    : null;
  const integerFields = [
    "observed_items",
    "raw_page_count",
    "raw_count",
    "structured_count",
    "structured_generation",
    "run_id",
  ] as const;
  const requiredExtraDigests = value.dataset === "equities_master"
    ? [...REQUIRED_ACQUISITION_DIGESTS, ...REQUIRED_MASTER_CALENDAR_DIGESTS]
    : [...REQUIRED_ACQUISITION_DIGESTS];
  const requestIdentityMatches =
    value.environment === persistedRequest.environment &&
    value.source === persistedRequest.source &&
    value.contract_id === persistedRequest.contract_id &&
    value.dataset === persistedRequest.dataset_id &&
    value.segment_id === persistedRequest.segment_id &&
    value.segment_start === persistedRequest.expected_key_start &&
    value.segment_end === persistedRequest.expected_key_end &&
    segmentMatchesGrain(
      persistedRequest.source,
      persistedRequest.segment_grain,
      persistedRequest.segment_id,
      persistedRequest.expected_key_start,
      persistedRequest.expected_key_end,
    );
  if (
    (value.environment !== "production" && value.environment !== "staging") ||
    !isSha256(value.authority_instance_digest) ||
    value.coverage_policy_version !== "collection-coverage/v3" ||
    (value.source !== "jquants" && value.source !== "jsda") ||
    typeof value.contract_id !== "string" || value.contract_id.length === 0 ||
    typeof value.dataset !== "string" || value.dataset.length === 0 ||
    typeof value.segment_id !== "string" ||
    !requestIdentityMatches ||
    typeof value.segment_start !== "string" ||
    typeof value.segment_end !== "string" ||
    !isPlainObject(value.expected_scope) ||
    !(value.expected_items === null ||
      (Number.isSafeInteger(value.expected_items) &&
        Number(value.expected_items) >= 0)) ||
    integerFields.some((field) =>
      !Number.isSafeInteger(value[field]) || Number(value[field]) < 0
    ) ||
    value.status !== "SUCCESS" || value.error !== null ||
    value.pagination_exhausted !== true || value.discovery_exhausted !== true ||
    !isSha256(value.receipt_issue_digest) ||
    !isSha256(value.source_request_digest) ||
    !isSha256(value.natural_key_digest) ||
    typeof value.artifact_key !== "string" || value.artifact_key.length === 0 ||
    typeof value.manifest_key !== "string" || value.manifest_key.length === 0 ||
    typeof value.raw_manifest_key !== "string" || value.raw_manifest_key.length === 0 ||
    !Number.isSafeInteger(value.artifact_byte_count) || Number(value.artifact_byte_count) <= 0 ||
    !Number.isSafeInteger(value.manifest_byte_count) || Number(value.manifest_byte_count) <= 0 ||
    !Number.isSafeInteger(value.raw_manifest_byte_count) || Number(value.raw_manifest_byte_count) <= 0 ||
    !Number.isSafeInteger(value.raw_byte_count) || Number(value.raw_byte_count) <= 0 ||
    !isSha256(value.raw_manifest_digest) || !isSha256(value.raw_digest) ||
    !isSha256(value.structured_digest) || !isSha256(value.scope_digest) ||
    !isSha256(value.observation_digest) ||
    typeof value.checked_at !== "string" ||
    !Number.isFinite(Date.parse(value.checked_at)) ||
    extraDigests === null ||
    !exactKeys(extraDigests, requiredExtraDigests) ||
    requiredExtraDigests.some(
      (field) => !isSha256(extraDigests[field]),
    )
  ) {
    throw new TypeError("receipt authority claims failed invariant validation");
  }
  return value as UnsignedReceiptClaimsV3;
}

/** Recover the canonical request preimage and bind it to the DO-persisted digest. */
export async function requirePersistedDerivedClaims(
  value: unknown,
  rawRequest: ReceiptIssueRequestV1,
  persistedRequestDigest: string,
): Promise<UnsignedReceiptClaimsV3> {
  const persistedRequest = issueIdentity(requireReceiptRequest(rawRequest));
  if (
    !isSha256(persistedRequestDigest) ||
    await canonicalDigest(persistedRequest) !== persistedRequestDigest
  ) {
    throw new Error("receipt authority request preimage differs from persisted digest");
  }
  return requireDerivedClaims(value, persistedRequest);
}
