/**
 * Small R2 control CAS/lease helpers shared by idle-by-default Cron ticks.
 */

export const CONTROL_MAX_BYTES = 8 * 1024;
export const CONTROL_LEASE_MS = 90_000;

export type ControlLease = { owner: string; until: string } | null;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseControlLease(value: unknown): ControlLease | undefined {
  if (value === null) return null;
  if (!isPlainObject(value) || Object.keys(value).length !== 2) return undefined;
  if (typeof value.owner !== "string" || value.owner.length === 0) return undefined;
  if (typeof value.until !== "string") return undefined;
  const until = new Date(value.until);
  if (Number.isNaN(until.getTime()) || until.toISOString() !== value.until) {
    return undefined;
  }
  return { owner: value.owner, until: value.until };
}

export async function casPutJson(
  bucket: R2Bucket,
  key: string,
  value: unknown,
  etag: string,
): Promise<R2Object | null> {
  const body = JSON.stringify(value);
  if (new TextEncoder().encode(body).byteLength > CONTROL_MAX_BYTES) return null;
  return bucket.put(key, body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    onlyIf: { etagMatches: etag },
  });
}
