/** Strict JSON: reject duplicate keys and non-finite numbers before ordinary use. */

export class StrictJsonError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StrictJsonError";
  }
}

function isFiniteNumber(value: unknown): boolean {
  return typeof value !== "number" || Number.isFinite(value);
}

function walkFinite(value: unknown, path: string): void {
  if (!isFiniteNumber(value)) {
    throw new StrictJsonError(`${path} is not a finite JSON number`);
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => walkFinite(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      walkFinite(item, `${path}.${key}`);
    }
  }
}

function skipWs(text: string, index: number): number {
  while (index < text.length && /[ \t\n\r]/.test(text[index]!)) index += 1;
  return index;
}

function skipString(text: string, index: number): number {
  if (text[index] !== '"') throw new StrictJsonError("JSON string is invalid");
  index += 1;
  while (index < text.length) {
    const ch = text[index]!;
    if (ch === '"') return index + 1;
    if (ch === "\\") {
      index += 2;
      continue;
    }
    index += 1;
  }
  throw new StrictJsonError("JSON string is unterminated");
}

function skipValue(text: string, start: number): number {
  let index = skipWs(text, start);
  const ch = text[index];
  if (ch === '"') return skipString(text, index);
  if (ch === "{") return skipObject(text, index);
  if (ch === "[") {
    index += 1;
    index = skipWs(text, index);
    if (text[index] === "]") return index + 1;
    while (index < text.length) {
      index = skipValue(text, index);
      index = skipWs(text, index);
      if (text[index] === "]") return index + 1;
      if (text[index] !== ",") throw new StrictJsonError("JSON array is invalid");
      index += 1;
    }
    throw new StrictJsonError("JSON array is unterminated");
  }
  if (ch === "t" || ch === "f" || ch === "n" || ch === "-" || (ch !== undefined && ch >= "0" && ch <= "9")) {
    while (index < text.length && /[0-9eE+.\-truefalsn]/.test(text[index]!)) index += 1;
    return index;
  }
  throw new StrictJsonError("JSON value is invalid");
}

function skipObject(text: string, start: number): number {
  let index = skipWs(text, start);
  if (text[index] !== "{") throw new StrictJsonError("JSON object is invalid");
  index += 1;
  index = skipWs(text, index);
  const seen = new Set<string>();
  if (text[index] === "}") return index + 1;
  while (index < text.length) {
    index = skipWs(text, index);
    const keyStart = index;
    index = skipString(text, index);
    const key = JSON.parse(text.slice(keyStart, index)) as string;
    if (seen.has(key)) {
      throw new StrictJsonError(`JSON contains duplicate key ${key}`);
    }
    seen.add(key);
    index = skipWs(text, index);
    if (text[index] !== ":") throw new StrictJsonError("JSON object is invalid");
    index = skipValue(text, index + 1);
    index = skipWs(text, index);
    if (text[index] === "}") return index + 1;
    if (text[index] !== ",") throw new StrictJsonError("JSON object is invalid");
    index += 1;
  }
  throw new StrictJsonError("JSON object is unterminated");
}

export function decodeStrictJson(bytes: Uint8Array): unknown {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new StrictJsonError("JSON is not valid UTF-8");
  }
  skipValue(text, 0);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new StrictJsonError("JSON is invalid");
  }
  walkFinite(parsed, "$");
  return parsed;
}

export async function sha256Digest(bytes: Uint8Array | string): Promise<string> {
  const data = typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  const digest = await crypto.subtle.digest("SHA-256", data);
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `sha256:${hex}`;
}

function rejectUnpairedSurrogate(value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      if (index + 1 >= value.length) {
        throw new StrictJsonError("canonical JSON string contains an unpaired surrogate");
      }
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) {
        throw new StrictJsonError("canonical JSON string contains an unpaired surrogate");
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new StrictJsonError("canonical JSON string contains an unpaired surrogate");
    }
  }
}

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    rejectUnpairedSurrogate(value);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new StrictJsonError("canonical JSON number is not finite");
    }
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new StrictJsonError("canonical JSON integer is outside the safe range");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (typeof value !== "object") {
    throw new StrictJsonError("value is not canonical JSON");
  }
  const rec = value as Record<string, unknown>;
  const keys = Object.keys(rec);
  keys.forEach(rejectUnpairedSurrogate);
  return `{${keys.sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(rec[key])}`)
    .join(",")}}`;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const CANONICAL_UTC =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|\+00:00)$/;

export function parseCanonicalUtc(value: unknown): number {
  if (typeof value !== "string" || !CANONICAL_UTC.test(value)) return Number.NaN;
  const match = CANONICAL_UTC.exec(value);
  if (!match) return Number.NaN;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const ms = Date.UTC(year, month - 1, day, hour, minute, second);
  const roundTrip = new Date(ms);
  if (
    roundTrip.getUTCFullYear() !== year ||
    roundTrip.getUTCMonth() + 1 !== month ||
    roundTrip.getUTCDate() !== day ||
    roundTrip.getUTCHours() !== hour ||
    roundTrip.getUTCMinutes() !== minute ||
    roundTrip.getUTCSeconds() !== second
  ) {
    return Number.NaN;
  }
  return ms;
}
