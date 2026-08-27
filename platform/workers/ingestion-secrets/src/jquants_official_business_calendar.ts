import {
  AcquisitionRequestRejected,
  canonicalDigest,
  sha256Digest,
} from "./jquants_acquisition_registry";
import { inspectStrictJsonObject } from "./strict_json";

export const OFFICIAL_CALENDAR_PATH = "/v2/markets/calendar";
const BUSINESS_DATES_SCHEMA = "jquants-official-business-dates/v1";
const BINDING_SCHEMA = "jquants-official-business-calendar-binding/v1";
const HOLIDAY_DIVISIONS = new Set(["0", "1", "2", "3"]);
const TSE_BUSINESS_DIVISIONS = new Set(["1", "2"]);

export type OfficialBusinessCalendarBinding = {
  rawBodyDigest: string;
  calendarQueryDigest: string;
  businessDatesDigest: string;
  bindingDigest: string;
  businessDates: readonly string[];
};

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length &&
    actual.every((key, index) => key === expected[index]);
}

function addDays(value: string, days: number): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new AcquisitionRequestRejected("official_calendar_range");
  }
  return new Date(parsed.getTime() + days * 86_400_000).toISOString().slice(0, 10);
}

function inclusiveDays(start: string, end: string): number {
  const startMs = Date.parse(`${start}T00:00:00Z`);
  const endMs = Date.parse(`${end}T00:00:00Z`);
  const days = (endMs - startMs) / 86_400_000 + 1;
  if (!Number.isSafeInteger(days) || days < 1 || days > 31) {
    throw new AcquisitionRequestRejected("official_calendar_range");
  }
  return days;
}

/**
 * Derive TSE equities-master slices solely from exact official V2 bytes.
 *
 * A strict shape scan rejects duplicate keys (including escape-equivalent
 * spellings) before JSON.parse materializes the bounded one-month document.
 * The response must enumerate every requested calendar date exactly once.
 */
export async function deriveOfficialBusinessCalendar(
  raw: Uint8Array,
  segmentStart: string,
  segmentEnd: string,
): Promise<OfficialBusinessCalendarBinding> {
  if (raw.byteLength < 1) {
    throw new AcquisitionRequestRejected("official_calendar_body");
  }
  let text: string;
  let value: unknown;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(raw);
    const top = inspectStrictJsonObject(text);
    if (top.size !== 1 || top.get("data")?.kind !== "array") {
      throw new SyntaxError("calendar envelope");
    }
    value = JSON.parse(text);
  } catch {
    throw new AcquisitionRequestRejected("official_calendar_body");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value) ||
    !exactKeys(value as Record<string, unknown>, ["data"])) {
    throw new AcquisitionRequestRejected("official_calendar_body");
  }
  const rows = (value as Record<string, unknown>).data;
  const expectedDays = inclusiveDays(segmentStart, segmentEnd);
  if (!Array.isArray(rows) || rows.length !== expectedDays) {
    throw new AcquisitionRequestRejected("official_calendar_exhaustion");
  }
  const businessDates: string[] = [];
  for (let ordinal = 0; ordinal < rows.length; ordinal += 1) {
    const row = rows[ordinal];
    if (typeof row !== "object" || row === null || Array.isArray(row) ||
      !exactKeys(row as Record<string, unknown>, ["Date", "HolDiv"])) {
      throw new AcquisitionRequestRejected("official_calendar_row");
    }
    const expectedDate = addDays(segmentStart, ordinal);
    const date = (row as Record<string, unknown>).Date;
    const division = (row as Record<string, unknown>).HolDiv;
    if (date !== expectedDate) {
      throw new AcquisitionRequestRejected("official_calendar_sequence");
    }
    if (typeof division !== "string" || !HOLIDAY_DIVISIONS.has(division)) {
      throw new AcquisitionRequestRejected("official_calendar_division");
    }
    if (TSE_BUSINESS_DIVISIONS.has(division)) businessDates.push(expectedDate);
  }
  if (businessDates.length === 0) {
    throw new AcquisitionRequestRejected("official_calendar_no_business_day");
  }

  const orderedQuery = [["from", segmentStart], ["to", segmentEnd]];
  const rawBodyDigest = await sha256Digest(raw);
  const calendarQueryDigest = await canonicalDigest({
    schema_version: "jquants-acquisition-query/v2",
    path: OFFICIAL_CALENDAR_PATH,
    ordered_query: orderedQuery,
  });
  const businessDatesDigest = await canonicalDigest({
    schema_version: BUSINESS_DATES_SCHEMA,
    segment_start: segmentStart,
    segment_end: segmentEnd,
    dates: businessDates,
  });
  const bindingDigest = await canonicalDigest({
    schema_version: BINDING_SCHEMA,
    path: OFFICIAL_CALENDAR_PATH,
    ordered_query: orderedQuery,
    raw_body_digest: rawBodyDigest,
    calendar_query_digest: calendarQueryDigest,
    business_dates_digest: businessDatesDigest,
    business_dates: businessDates,
  });
  return {
    rawBodyDigest,
    calendarQueryDigest,
    businessDatesDigest,
    bindingDigest,
    businessDates: Object.freeze([...businessDates]),
  };
}

export async function officialMasterQueryDigest(input: {
  path: string;
  sliceDate: string;
  providerCursor: string | null;
  calendar: OfficialBusinessCalendarBinding;
}): Promise<string> {
  if (input.path !== "/v2/equities/master" ||
    !input.calendar.businessDates.includes(input.sliceDate)) {
    throw new AcquisitionRequestRejected("official_calendar_slice");
  }
  const orderedQuery = [["date", input.sliceDate]];
  if (input.providerCursor !== null) {
    orderedQuery.push(["pagination_key", input.providerCursor]);
  }
  return canonicalDigest({
    schema_version: "jquants-acquisition-query/v3",
    path: input.path,
    ordered_query: orderedQuery,
    official_calendar_binding: {
      binding_digest: input.calendar.bindingDigest,
      raw_body_digest: input.calendar.rawBodyDigest,
      calendar_query_digest: input.calendar.calendarQueryDigest,
      business_dates_digest: input.calendar.businessDatesDigest,
      business_dates: input.calendar.businessDates,
    },
  });
}
