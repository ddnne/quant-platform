import { exactKeys, isPlainObject, isSha256 } from "./canonical";
import type { UnsignedReceiptClaimsV3 } from "./types";

const UNSIGNED_CLAIM_KEYS = [
  "environment",
  "authority_instance_digest",
  "coverage_policy_version",
  "source",
  "dataset",
  "segment_id",
  "segment_start",
  "segment_end",
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
] as const;

/** Validate only DO-derived claims immediately before signing. */
export function requireDerivedClaims(value: unknown): UnsignedReceiptClaimsV3 {
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
  if (
    (value.environment !== "production" && value.environment !== "staging") ||
    !isSha256(value.authority_instance_digest) ||
    value.coverage_policy_version !== "collection-coverage/v3" ||
    value.source !== "jquants" ||
    typeof value.dataset !== "string" || value.dataset.length === 0 ||
    typeof value.segment_id !== "string" ||
    !/^\d{4}-\d{2}$/.test(value.segment_id) ||
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
    !isSha256(value.source_request_digest) ||
    !isSha256(value.raw_manifest_digest) || !isSha256(value.raw_digest) ||
    !isSha256(value.structured_digest) || !isSha256(value.scope_digest) ||
    !isSha256(value.observation_digest) ||
    typeof value.checked_at !== "string" ||
    !Number.isFinite(Date.parse(value.checked_at)) ||
    extraDigests === null ||
    !exactKeys(extraDigests, REQUIRED_ACQUISITION_DIGESTS) ||
    REQUIRED_ACQUISITION_DIGESTS.some(
      (field) => !isSha256(extraDigests[field]),
    )
  ) {
    throw new TypeError("receipt authority claims failed invariant validation");
  }
  return value as UnsignedReceiptClaimsV3;
}
