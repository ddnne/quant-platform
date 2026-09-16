/**
 * Small R2 control CAS/lease helpers shared by idle-by-default Cron ticks.
 */

export const CONTROL_MAX_BYTES = 8 * 1024;
export const CONTROL_LEASE_MS = 90_000;

export type ControlLease =
  | { owner: string; until: string; started?: string }
  | null;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseControlLease(value: unknown): ControlLease | undefined {
  if (value === null) return null;
  if (!isPlainObject(value)) return undefined;
  const keys = Object.keys(value);
  if (keys.length !== 2 && keys.length !== 3) return undefined;
  if (typeof value.owner !== "string" || value.owner.length === 0) return undefined;
  if (typeof value.until !== "string") return undefined;
  const until = new Date(value.until);
  if (Number.isNaN(until.getTime()) || until.toISOString() !== value.until) {
    return undefined;
  }
  if (keys.length === 2) {
    if (!("owner" in value) || !("until" in value)) return undefined;
    return { owner: value.owner, until: value.until };
  }
  if (typeof value.started !== "string") return undefined;
  const started = new Date(value.started);
  if (Number.isNaN(started.getTime()) || started.toISOString() !== value.started) {
    return undefined;
  }
  return { owner: value.owner, until: value.until, started: value.started };
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
