/**
 * Phase 3.5 (P0-1) — Dataset-level `available_at` policy.
 *
 * Historical backfill used to set `available_at = ingestedAt`, which made old
 * bars invisible until ingest time — too conservative for research PIT.
 *
 * This module picks `available_at` per row using a dataset-level policy:
 *
 *   policy         | rule
 *   ---------------+---------------------------------------------------------
 *   session_close  | equities_bars_daily / am / indices / derivatives bars:
 *                  | available_at = event-date session close JST
 *                  | (15:30 from 2024-11-05; 15:00 before that).
 *   event_field    | If the row has DisclosedDate / AnnouncementDate /
 *                  | DateTime use that as the event; available_at = that
 *                  | instant (or next business open at 09:00 JST when only
 *                  | a date is present).
 *   ingest_time    | Fallback only when no better signal exists.
 *
 * The Python mirror lives in ``cf_platform/ingest_premium/availability.py``;
 * ``tests/test_phase35_availability.py`` asserts cross-language agreement.
 *
 * This module is pure (no I/O) so it is unit-testable from Python via the
 * mirror.
 */

// Datasets whose row Date IS the session — for these the session-close JST
// instant is the correct PIT-available time (the bar is knowable after the
// close). Sorted for stable reading.
export const SESSION_CLOSE_DATASETS: readonly string[] = [
  "derivatives_bars_daily_futures",
  "derivatives_bars_daily_options",
  "derivatives_bars_daily_options_225",
  "equities_bars_daily",
  "equities_bars_daily_am",
  "indices_bars_daily",
  "indices_bars_daily_topix",
];

// 2024-11-05: TSE afternoon close moved from 15:00 to 15:30 JST. Source:
// JPX timing rule change. We treat the cutoff as a date string compare.
const SESSION_CLOSE_CUTOFF_DATE = "2024-11-05";
const SESSION_CLOSE_TIME_NEW = "15:30";
const SESSION_CLOSE_TIME_OLD = "15:00";

// Event-time candidate fields in priority order. Bare dates are normalized
// to next-business-open 09:00 JST. MUST match the Python mirror's
// EVENT_FIELD_CANDIDATES tuple.
export const EVENT_FIELD_CANDIDATES: readonly string[] = [
  "DateTime",
  "DisclosedDate",
  "AnnouncementDate",
  "DiscDate",
  "Date",
];

export type AvailabilityPolicy = "session_close" | "event_field" | "ingest_time";

/** Per-dataset policy override. Datasets not listed use {@link DEFAULT_POLICY}. */
export const DATASET_POLICY: Readonly<Record<string, AvailabilityPolicy>> = Object.fromEntries(
  SESSION_CLOSE_DATASETS.map((id) => [id, "session_close" as const]),
);

export const DEFAULT_POLICY: AvailabilityPolicy = "event_field";

export function policyForDataset(datasetId: string): AvailabilityPolicy {
  return DATASET_POLICY[datasetId] ?? DEFAULT_POLICY;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Format a Date (UTC components) as YYYY-MM-DD using UTC getters. */
function utcYmd(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Return the JST session-close instant for a session date.
 *
 * 15:30 JST from 2024-11-05 onward, 15:00 JST before. Throws on malformed
 * input — callers should pre-validate the row's date field.
 */
export function sessionCloseJst(dateYyyyMmDd: string): string {
  if (!DATE_RE.test(dateYyyyMmDd)) {
    throw new Error(`sessionCloseJst: expected YYYY-MM-DD, got ${JSON.stringify(dateYyyyMmDd)}`);
  }
  const time = dateYyyyMmDd < SESSION_CLOSE_CUTOFF_DATE
    ? SESSION_CLOSE_TIME_OLD
    : SESSION_CLOSE_TIME_NEW;
  return `${dateYyyyMmDd}T${time}:00+09:00`;
}

/**
 * Advance a YYYY-MM-DD to the next JST business day if it falls on a weekend.
 * Returns ``YYYY-MM-DDT09:00:00+09:00`` (start-of-trading-day JST).
 */
export function nextBusinessOpenJst(dateYyyyMmDd: string): string {
  if (!DATE_RE.test(dateYyyyMmDd)) {
    throw new Error(`nextBusinessOpenJst: expected YYYY-MM-DD, got ${JSON.stringify(dateYyyyMmDd)}`);
  }
  const [y, m, d] = dateYyyyMmDd.split("-").map(Number);
  // UTC constructors avoid TZ drift while we walk calendar days.
  let dt = new Date(Date.UTC(y, m - 1, d));
  // 0 = Sun, 6 = Sat in both UTC and JS getters.
  while (dt.getUTCDay() === 0 || dt.getUTCDay() === 6) {
    dt = new Date(dt.getTime() + 86_400_000);
  }
  return `${utcYmd(dt)}T09:00:00+09:00`;
}

/** True when ``v`` looks like a full ISO timestamp (has a ``T`` separator). */
function hasTimeComponent(v: string): boolean {
  return v.includes("T") || v.includes(" ");
}

/** Pick the event-field instant from a row, or null if no candidate exists. */
export function pickEventFieldInstant(row: Record<string, unknown>): string | null {
  for (const k of EVENT_FIELD_CANDIDATES) {
    const v = row[k];
    if (typeof v !== "string" || v.length === 0) continue;
    if (DATE_RE.test(v)) {
      // Bare date → next business open at 09:00 JST.
      return nextBusinessOpenJst(v);
    }
    // Full timestamp (or other ISO-ish string) — trust caller formatting.
    if (hasTimeComponent(v)) return v;
    // Unexpected shape — fall through to next candidate rather than guessing.
  }
  return null;
}

/** Pick the session date from a row, used by session_close policy. */
function pickSessionDate(row: Record<string, unknown>): string | null {
  const d = row["Date"];
  if (typeof d === "string" && DATE_RE.test(d)) return d;
  return null;
}

/**
 * Compute the row's `available_at` per dataset policy.
 *
 * Resolution order:
 *   1. Explicit row-level ``available_at`` (caller's responsibility — handled
 *      in ``upsertRecords`` before this function is called).
 *   2. Policy-specific rule (session_close → session close JST;
 *      event_field → event-field instant).
 *   3. Cross-policy fallback: if a session_close row lacks ``Date``, try
 *      event_field; if event_field finds nothing, fall through to ingest_time.
 *   4. ``ingestedAt`` — the fetch instant. Last resort, PIT-safe.
 */
export function pickAvailableAt(
  row: Record<string, unknown>,
  datasetId: string,
  ingestedAt: string,
): string {
  const policy = policyForDataset(datasetId);
  if (policy === "session_close") {
    const sessionDate = pickSessionDate(row);
    if (sessionDate) return sessionCloseJst(sessionDate);
    // No row Date — try event field, else ingest time.
    const ev = pickEventFieldInstant(row);
    if (ev) return ev;
    return ingestedAt;
  }
  if (policy === "event_field") {
    const ev = pickEventFieldInstant(row);
    if (ev) return ev;
    return ingestedAt;
  }
  // ingest_time
  return ingestedAt;
}
