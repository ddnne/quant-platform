/// <reference types="@cloudflare/workers-types" />

import type { Env } from "./types";

export function freezePayload(env: Env) {
  return {
    mass_research: env.MASS_RESEARCH || "NO-GO",
    phase7: env.PHASE7 || "OFF",
    ready_declared: String(env.READY_DECLARED || "false") === "true",
    operational_go: String(env.OPERATIONAL_GO || "false") === "true",
    continuous_paper: env.CONTINUOUS_PAPER || "UNARMED",
    frozen_defaults_retuned: false,
    connected_to_ready: false,
    connected_to_mass: false,
  };
}

function timingSafeEqualBytes(a: ArrayBuffer, b: ArrayBuffer): boolean {
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(provided)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  return timingSafeEqualBytes(a, b);
}

export async function authorized(
  request: Request,
  expected?: string,
): Promise<boolean> {
  if (!expected) return false;
  const got =
    request.headers.get("X-Mass-Eval-Token") ||
    request.headers.get("X-Ingestion-Token") ||
    "";
  if (!got) return false;
  return tokenMatches(got, expected);
}

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

export function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function putJson(
  bucket: R2Bucket,
  key: string,
  data: unknown,
): Promise<{ key: string; bytes: number; created: boolean; digest?: string }> {
  return putJsonCreateOnly(bucket, key, data);
}

export type CreateOnlyPutResult = {
  key: string;
  bytes: number;
  created: boolean;
  digest: string;
};

export async function putJsonCreateOnly(
  bucket: R2Bucket,
  key: string,
  data: unknown,
): Promise<CreateOnlyPutResult> {
  const body = JSON.stringify(data, null, 2);
  const bytes = new TextEncoder().encode(body);
  const digest = `sha256:${await sha256Hex(bytes)}`;
  const existing = await bucket.head(key);
  if (existing) {
    return { key, bytes: 0, created: false, digest };
  }
  const put = await bucket.put(key, bytes, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: {
      plane: "research_mass_eval",
      wave: "research-mass-eval",
      sha256: digest,
    },
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (put === null) {
    return { key, bytes: 0, created: false, digest };
  }
  return { key, bytes: bytes.byteLength, created: true, digest };
}

/** Content-addressed immutable JSON. Job IDs are aliases, not identity. */
export async function putImmutableJson(
  bucket: R2Bucket,
  plane: string,
  data: unknown,
): Promise<CreateOnlyPutResult> {
  const body = JSON.stringify(data);
  const bytes = new TextEncoder().encode(body);
  const hex = await sha256Hex(bytes);
  const digest = `sha256:${hex}`;
  const key = `${plane}/sha256=${hex}.json`;
  const existing = await bucket.head(key);
  if (existing) {
    return { key, bytes: existing.size, created: false, digest };
  }
  const put = await bucket.put(key, bytes, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: {
      plane,
      sha256: digest,
      immutable: "true",
    },
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (put === null) {
    return { key, bytes: 0, created: false, digest };
  }
  return { key, bytes: bytes.byteLength, created: true, digest };
}

/**
 * Manifest 409 is not ok unless the existing object names `expectedDigest`
 * and that child object is present. Incomplete aliases are not success.
 */
export async function verifyManifestChildDigest(
  bucket: R2Bucket,
  manifestKey: string,
  expectedDigest: string,
): Promise<boolean> {
  if (!expectedDigest) return false;
  const obj = await bucket.get(manifestKey);
  if (!obj) return false;
  let parsed: unknown;
  try {
    parsed = await obj.json();
  } catch {
    return false;
  }
  if (!isObject(parsed)) return false;
  const got = String(parsed.artifact_digest ?? "");
  if (got !== expectedDigest) return false;
  const childKey =
    typeof parsed.artifact_key === "string" ? parsed.artifact_key : "";
  if (!childKey) return false;
  const child = await bucket.head(childKey);
  return child != null;
}

export type ChildrenThenManifestResult = {
  children: CreateOnlyPutResult[];
  manifest: CreateOnlyPutResult;
  ok: boolean;
  conflict: boolean;
  verified: boolean;
};

/** Two-phase: content children first, then create-only job manifest. */
export async function putChildrenThenManifest(
  bucket: R2Bucket,
  children: Array<{ key: string; data: unknown }>,
  manifest: { key: string; data: unknown },
  expectedChildDigest?: string,
): Promise<ChildrenThenManifestResult> {
  const childPuts = await Promise.all(
    children.map((child) => putJsonCreateOnly(bucket, child.key, child.data)),
  );
  const manifestPut = await putJsonCreateOnly(bucket, manifest.key, manifest.data);
  if (manifestPut.created) {
    return {
      children: childPuts,
      manifest: manifestPut,
      ok: true,
      conflict: false,
      verified: true,
    };
  }
  const digest =
    expectedChildDigest ||
    (isObject(manifest.data)
      ? String(manifest.data.artifact_digest ?? "")
      : "");
  const verified = await verifyManifestChildDigest(bucket, manifest.key, digest);
  return {
    children: childPuts,
    manifest: manifestPut,
    ok: verified,
    conflict: true,
    verified,
  };
}
