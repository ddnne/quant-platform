import { exactKeys, isPlainObject } from "./canonical";
import {
  governedReceiptIdentity,
  type SegmentGrain,
} from "../../ingestion-premium/src/catalog";
import type {
  GovernedSource,
  ReceiptIssueRequestV1,
  ReceiptRequestV1,
} from "./types";

export const RECEIPT_REQUEST_KEYS = [
  "schema_version",
  "operation",
  "environment",
  "source",
  "contract_id",
  "dataset_id",
  "segment_grain",
  "segment_id",
  "expected_key_start",
  "expected_key_end",
  "request_nonce",
] as const;

export const JSDA_RECEIPT_REQUEST_KEYS = [
  ...RECEIPT_REQUEST_KEYS,
  "work_key",
  "expected_contract_digest",
  "raw_object_key",
] as const;

const MONTH = /^(\d{4})-(\d{2})$/;
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

function lastDayOfMonth(year: number, month: number): string {
  const date = new Date(Date.UTC(year, month, 0));
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${day}`;
}

export function segmentMatchesGrain(
  source: GovernedSource,
  grain: SegmentGrain,
  segmentId: string,
  keyStart: string,
  keyEnd: string,
): boolean {
  if (typeof keyStart !== "string" || typeof keyEnd !== "string" || keyStart > keyEnd) {
    return false;
  }
  if (source === "jquants") {
    if (grain === "same_trading_day_am_snapshot" || grain === "collection_cutoff_snapshot") {
      return DAY.test(segmentId) && keyStart === segmentId && keyEnd === segmentId;
    }
    const month = MONTH.exec(segmentId);
    if (grain !== "calendar_month" || month === null) return false;
    const year = Number(month[1]);
    const monthNumber = Number(month[2]);
    if (monthNumber < 1 || monthNumber > 12) return false;
    return keyStart === `${month[1]}-${month[2]}-01` &&
      keyEnd === lastDayOfMonth(year, monthNumber);
  }
  if (grain === "official_archive_index_day") {
    const bound =
      /^(\d{4}-\d{2}-\d{2})$/.exec(segmentId)?.[1] ??
      /^archive-(\d{4}-\d{2}-\d{2})$/.exec(segmentId)?.[1] ??
      /^index_root_(\d{4}-\d{2}-\d{2})$/.exec(segmentId)?.[1];
    if (bound === undefined) return false;
    return keyStart === bound && keyEnd === bound;
  }
  if (grain === "official_archive_year") {
    const year = /^archive_year_(\d{4})_[A-Za-z0-9._-]{1,64}$/.exec(segmentId);
    if (year === null) return false;
    return keyStart === `${year[1]}-01-01` && keyEnd === `${year[1]}-12-31`;
  }
  if (grain === "source_time_series_file") {
    const fileDay = /^file_(\d{4}-\d{2}-\d{2})(?:_[A-Za-z0-9._-]{1,140})?$/.exec(segmentId);
    if (fileDay !== null) {
      return keyStart === fileDay[1] && keyEnd === fileDay[1];
    }
    return /^file_[A-Za-z0-9._-]{1,160}$/.test(segmentId) &&
      DAY.test(keyStart) && keyStart === keyEnd;
  }
  return false;
}

export function jsdaSegmentGrain(
  segmentId: string,
): SegmentGrain | null {
  if (
    /^\d{4}-\d{2}-\d{2}$/.test(segmentId) ||
    /^archive-\d{4}-\d{2}-\d{2}$/.test(segmentId) ||
    /^index_root_\d{4}-\d{2}-\d{2}$/.test(segmentId)
  ) {
    return "official_archive_index_day";
  }
  if (/^archive_year_\d{4}_[A-Za-z0-9._-]{1,64}$/.test(segmentId)) {
    return "official_archive_year";
  }
  if (/^file_[A-Za-z0-9._-]{1,160}$/.test(segmentId)) {
    return "source_time_series_file";
  }
  return null;
}

export function requireReceiptRequest(value: unknown): ReceiptRequestV1 {
  if (!isPlainObject(value)) {
    throw new TypeError("receipt request is not closed");
  }
  const jsda = value.source === "jsda";
  if (!exactKeys(value, jsda ? JSDA_RECEIPT_REQUEST_KEYS : RECEIPT_REQUEST_KEYS)) {
    throw new TypeError("receipt request is not closed");
  }
  if (
    value.schema_version !== "receipt-evidence-issue-request/v1" ||
    (value.operation !== "issue_for_segment" && value.operation !== "recover_issue") ||
    (value.environment !== "staging" && value.environment !== "production") ||
    (value.source !== "jquants" && value.source !== "jsda") ||
    typeof value.contract_id !== "string" ||
    typeof value.dataset_id !== "string" ||
    !/^[a-z][a-z0-9_]{2,127}$/.test(value.dataset_id) ||
    typeof value.segment_grain !== "string" ||
    typeof value.segment_id !== "string" ||
    typeof value.expected_key_start !== "string" ||
    typeof value.expected_key_end !== "string" ||
    typeof value.request_nonce !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.request_nonce)
  ) {
    throw new TypeError("receipt request fields are invalid");
  }
  if (jsda) {
    if (
      typeof value.work_key !== "string" ||
      value.work_key.length < 16 ||
      value.work_key.length > 240 ||
      !/^jsda:v2:[A-Za-z0-9:._-]+$/.test(value.work_key) ||
      typeof value.expected_contract_digest !== "string" ||
      !/^sha256:[0-9a-f]{64}$/.test(value.expected_contract_digest) ||
      typeof value.raw_object_key !== "string" ||
      !/^raw\/jsda\/[A-Za-z0-9._\/-]{1,500}$/.test(value.raw_object_key)
    ) {
      throw new TypeError("receipt request fields are invalid");
    }
  }
  const identity = governedReceiptIdentity(value.dataset_id);
  if (
    identity === undefined ||
    identity.source !== value.source ||
    identity.contract_id !== value.contract_id
  ) {
    throw new TypeError("receipt request identity is not in the governed inventory");
  }
  const grain = jsda
    ? jsdaSegmentGrain(value.segment_id)
    : identity.segment_grain;
  if (
    grain === null ||
    grain !== value.segment_grain ||
    (!jsda && identity.segment_grain !== value.segment_grain)
  ) {
    throw new TypeError("receipt request identity is not in the governed inventory");
  }
  if (
    !segmentMatchesGrain(
      value.source,
      grain,
      value.segment_id,
      value.expected_key_start,
      value.expected_key_end,
    )
  ) {
    throw new TypeError("receipt request segment grain is invalid");
  }
  if (
    grain === "source_time_series_file" &&
    !/^file_\d{4}-\d{2}-\d{2}(?:_[A-Za-z0-9._-]{1,140})?$/.test(value.segment_id) &&
    (value.expected_key_start !== identity.coverage.history_target_start ||
      value.expected_key_end !== identity.coverage.history_target_start)
  ) {
    throw new TypeError("receipt request segment grain is invalid");
  }
  return value as ReceiptRequestV1;
}

export function issueIdentity(request: ReceiptRequestV1): ReceiptIssueRequestV1 {
  const base = {
    schema_version: "receipt-evidence-issue-request/v1" as const,
    operation: "issue_for_segment" as const,
    environment: request.environment,
    contract_id: request.contract_id,
    dataset_id: request.dataset_id,
    segment_grain: request.segment_grain,
    segment_id: request.segment_id,
    expected_key_start: request.expected_key_start,
    expected_key_end: request.expected_key_end,
    request_nonce: request.request_nonce,
  };
  if (request.source === "jsda") {
    return {
      ...base,
      source: "jsda",
      work_key: request.work_key,
      expected_contract_digest: request.expected_contract_digest,
      raw_object_key: request.raw_object_key,
    };
  }
  return { ...base, source: "jquants" };
}
