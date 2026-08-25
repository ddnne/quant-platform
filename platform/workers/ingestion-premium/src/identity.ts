/** Contract-driven natural key, event_time, available_at, and persist run identity. */

import type { DatasetSpec } from "./catalog";
import { sha256HexFromString } from "./sha256.ts";

/** Persist/SCD2 run identity. crypto.randomUUID, not Math.random. */
export function newRunId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function isYyyyMmDd(value: string): boolean {
  return DATE_RE.test(value);
}

function validDate(value: string): boolean {
  if (!isYyyyMmDd(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

export function toJstIso(d: Date): string {
  const ms = d.getTime() + JST_OFFSET_MS;
  const jst = new Date(ms);
  return jst.toISOString().replace(/\.(\d+)Z$/, "+09:00");
}

export function todayJst(): string {
  return toJstIso(new Date()).slice(0, 10);
}

export function daysAgoJst(n: number): string {
  const t = new Date(Date.now() - n * 24 * 60 * 60 * 1000);
  return toJstIso(t).slice(0, 10);
}

function jsonString(value: string): string {
  return JSON.stringify(value);
}

/** Python mirror: data_contracts.identity.canonical_json. */
export function stableJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item === undefined ? null : item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).filter((key) => object[key] !== undefined).sort().map(
      (key) => `${jsonString(key)}:${stableJson(object[key])}`,
    ).join(",")}}`;
  }
  throw new Error(`not an interoperable JSON value: ${typeof value}`);
}

function aliasesFor(spec: DatasetSpec, field: string): string[] {
  return [field, ...(spec.field_aliases?.[field] ?? [])];
}

function pick(row: Record<string, unknown>, spec: DatasetSpec, field: string): unknown | null {
  for (const candidate of aliasesFor(spec, field)) {
    for (const key of [candidate, candidate.toLowerCase()]) {
      const value = row[key];
      if (value !== undefined && value !== null && value !== "") return value;
    }
  }
  return null;
}

export async function naturalKey(
  row: Record<string, unknown>,
  spec: DatasetSpec,
): Promise<string> {
  const picked: Record<string, unknown> = {};
  for (const field of spec.natural_key_fields) {
    const value = pick(row, spec, field);
    if (value === null || value === "") {
      return `hash:sha256:${await sha256HexFromString(stableJson(row))}`;
    }
    picked[field] = value;
  }
  return stableJson(picked);
}

export function sessionCloseJst(dateYyyyMmDd: string, session?: string): string {
  if (!validDate(dateYyyyMmDd)) {
    throw new Error(`expected YYYY-MM-DD, got ${JSON.stringify(dateYyyyMmDd)}`);
  }
  const close = session === "morning"
    ? "11:30:00"
    : dateYyyyMmDd < "2024-11-05" ? "15:00:00" : "15:30:00";
  return `${dateYyyyMmDd}T${close}+09:00`;
}

function dateStart(value: unknown): string | null {
  return typeof value === "string" && validDate(value)
    ? `${value}T00:00:00+09:00`
    : null;
}

function validClock(value: string): boolean {
  const match = /^(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/.exec(value);
  if (!match) return false;
  return Number(match[1]) < 24 && Number(match[2]) < 60 && Number(match[3] ?? 0) < 60;
}

function timestampFromFields(
  row: Record<string, unknown>,
  spec: DatasetSpec,
  fields: string[],
): string | null {
  if (fields.length === 0) return null;
  const first = pick(row, spec, fields[0]);
  if (typeof first !== "string" || first.length === 0) return null;
  if (first.includes("T") || first.includes(" ")) return first;
  if (fields.length < 2 || !validDate(first)) return null;
  const second = pick(row, spec, fields[1]);
  if (typeof second !== "string" || !validClock(second)) return null;
  const clock = /^\d{2}:\d{2}$/.test(second) ? `${second}:00` : second;
  return `${first}T${clock}+09:00`;
}

export function pickEventTime(
  row: Record<string, unknown>,
  spec: DatasetSpec,
): string | null {
  const fields = spec.event_time_fields;
  if (fields.length === 0) return null;
  if (spec.event_time_policy === "session_close") {
    const day = pick(row, spec, fields[0]);
    return typeof day === "string" && validDate(day)
      ? sessionCloseJst(day, spec.session)
      : null;
  }
  if (spec.event_time_policy === "explicit_timestamp_field") {
    return timestampFromFields(row, spec, fields) ?? dateStart(pick(row, spec, fields[0]));
  }
  if (spec.event_time_policy === "observation_date") {
    return dateStart(pick(row, spec, fields[0]));
  }
  return null;
}

function nextCalendarStart(value: unknown): string | null {
  if (typeof value !== "string" || !validDate(value)) return null;
  const day = new Date(`${value}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return `${day.toISOString().slice(0, 10)}T00:00:00+09:00`;
}

function knownLagAvailableAt(
  row: Record<string, unknown>,
  spec: DatasetSpec,
): string | null {
  const event = pickEventTime(row, spec);
  const lag = spec.known_publication_lag;
  if (!event || !lag) return null;
  const match = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?)?$/.exec(lag);
  if (!match) return null;
  const date = new Date(event);
  if (Number.isNaN(date.getTime())) return null;
  date.setTime(date.getTime() + (Number(match[1] ?? 0) * 24 + Number(match[2] ?? 0)) * 3_600_000);
  // Preserve an explicit offset representation for SQLite lexical ordering.
  const shifted = new Date(date.getTime() + 9 * 3_600_000).toISOString().replace("Z", "+09:00");
  return shifted.replace(".000+", "+");
}

export function pickAvailableAt(
  row: Record<string, unknown>,
  spec: DatasetSpec,
  ingestedAt: string,
): string {
  const policy = spec.available_at_policy;
  if (policy === "session_close") {
    const day = pick(row, spec, spec.availability_field ?? "Date");
    if (typeof day === "string" && validDate(day)) {
      return sessionCloseJst(day, spec.session);
    }
  } else if (policy === "explicit_timestamp_field" && spec.availability_field) {
    const instant = timestampFromFields(row, spec, spec.availability_field.split("+"));
    if (instant) return instant;
  } else if (policy === "explicit_disclosure_date" && spec.availability_field) {
    const fields = spec.availability_field.split("+");
    const instant = timestampFromFields(row, spec, fields);
    if (instant) return instant;
    const conservativeDayEnd = nextCalendarStart(pick(row, spec, fields[0]));
    if (conservativeDayEnd) return conservativeDayEnd;
  } else if (policy === "known_publication_lag") {
    const lagged = knownLagAvailableAt(row, spec);
    if (lagged) return lagged;
  }
  return ingestedAt;
}
