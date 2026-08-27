import {
  canonicalDigest,
  canonicalJson,
  sha256Digest,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";

export { canonicalDigest, canonicalJson, sha256Digest };

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function base64ToBytes(value: string): Uint8Array {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(value)) {
    throw new TypeError("base64 value is invalid");
  }
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

export function arrayBufferToBase64(value: ArrayBuffer): string {
  return bytesToBase64(new Uint8Array(value));
}

export function utf8Base64(value: string): string {
  return bytesToBase64(new TextEncoder().encode(value));
}

export function randomHex(bytes: number): string {
  const value = crypto.getRandomValues(new Uint8Array(bytes));
  return [...value].map((item) => item.toString(16).padStart(2, "0")).join("");
}

export function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

export function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every(
    (key, index) => key === wanted[index],
  );
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function operationRunId(operationDigest: string): number {
  if (!isSha256(operationDigest)) throw new TypeError("operation digest required");
  // Keep the authority's run-id domain away from the ordinary D1 autoincrement
  // range while staying below Number.MAX_SAFE_INTEGER.
  return 4_000_000_000_000_000 + Number.parseInt(operationDigest.slice(7, 19), 16);
}
