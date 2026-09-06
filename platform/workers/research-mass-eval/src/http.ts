/// <reference types="@cloudflare/workers-types" />

import { sha256Hex } from "./sha256";

export { json } from "./http_json";
export { sha256Hex } from "./sha256";
export { authorized } from "./authorized";
export { freezePayload } from "./freeze";

async function cancelRequestBody(request: Request): Promise<void> {
  const body = request.body;
  if (!body) return;
  try {
    await body.cancel();
  } catch {
    // Body may already be locked or closed.
  }
}

/** Stream a request body up to `maximum` bytes. Does not trust Content-Length alone. */
export async function readBoundedRequestBytes(
  request: Request,
  maximum: number,
): Promise<
  | { ok: true; bytes: Uint8Array }
  | { ok: false; status: number; error: string }
> {
  const raw = request.headers.get("content-length");
  let declared: number | null = null;
  if (raw !== null && raw !== "") {
    if (!/^\d+$/.test(raw)) {
      await cancelRequestBody(request);
      return { ok: false, status: 400, error: "content-length required" };
    }
    const length = Number(raw);
    if (!Number.isSafeInteger(length) || length < 1) {
      await cancelRequestBody(request);
      return { ok: false, status: 400, error: "content-length required" };
    }
    if (length > maximum) {
      await cancelRequestBody(request);
      return { ok: false, status: 413, error: "request body exceeds the bound" };
    }
    declared = length;
  }
  if (request.body === null) {
    return { ok: false, status: 400, error: "request body exceeds the bound" };
  }
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  while (true) {
    let step: ReadableStreamReadResult<Uint8Array>;
    try {
      step = await reader.read();
    } catch {
      try {
        await reader.cancel("request body exceeds the bound");
      } catch {
        // ignore
      }
      return { ok: false, status: 400, error: "request body exceeds the bound" };
    }
    if (step.done) break;
    received += step.value.byteLength;
    if (received > maximum) {
      try {
        await reader.cancel("request body exceeds the bound");
      } catch {
        // ignore
      }
      return { ok: false, status: 413, error: "request body exceeds the bound" };
    }
    chunks.push(step.value);
  }
  if (received < 1) {
    return { ok: false, status: 400, error: "invalid JSON body" };
  }
  if (declared !== null && received !== declared) {
    return { ok: false, status: 400, error: "content-length mismatch" };
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, bytes };
}

export async function readBoundedJson(
  request: Request,
  maximum: number,
): Promise<
  | { ok: true; value: unknown }
  | { ok: false; status: number; error: string }
> {
  const raw = request.headers.get("content-length");
  if (!raw || !/^\d+$/.test(raw)) {
    await cancelRequestBody(request);
    return { ok: false, status: 400, error: "content-length required" };
  }
  const length = Number(raw);
  if (!Number.isSafeInteger(length) || length < 1 || length > maximum) {
    await cancelRequestBody(request);
    return { ok: false, status: 413, error: "request body exceeds the bound" };
  }
  const bounded = await readBoundedRequestBytes(request, maximum);
  if (!bounded.ok) return bounded;
  if (bounded.bytes.byteLength !== length) {
    return { ok: false, status: 400, error: "content-length mismatch" };
  }
  try {
    return { ok: true, value: JSON.parse(new TextDecoder().decode(bounded.bytes)) };
  } catch {
    return { ok: false, status: 400, error: "invalid JSON body" };
  }
}

export function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function serializedJsonBytes(data: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data, null, 2));
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
  conflict: boolean;
  status?: 409;
};

export type CreateOnlyBytesOptions = {
  digest: string;
  contentType: string;
  customMetadata?: Record<string, string>;
};

const CREATE_ONLY_COMPARE_MAX_BYTES = 256 * 1024;

async function compareExisting(
  bucket: R2Bucket,
  key: string,
  digest: string,
): Promise<CreateOnlyPutResult | null> {
  const obj = await bucket.get(key);
  if (!obj) return null;
  if (obj.size > CREATE_ONLY_COMPARE_MAX_BYTES) {
    return {
      key,
      bytes: obj.size,
      created: false,
      digest,
      conflict: true,
      status: 409,
    };
  }
  const existingBytes = new Uint8Array(await obj.arrayBuffer());
  if (existingBytes.byteLength > CREATE_ONLY_COMPARE_MAX_BYTES) {
    return {
      key,
      bytes: existingBytes.byteLength,
      created: false,
      digest,
      conflict: true,
      status: 409,
    };
  }
  const existingDigest = `sha256:${await sha256Hex(existingBytes)}`;
  if (existingDigest === digest) {
    return {
      key,
      bytes: existingBytes.byteLength,
      created: false,
      digest,
      conflict: false,
    };
  }
  return {
    key,
    bytes: existingBytes.byteLength,
    created: false,
    digest,
    conflict: true,
    status: 409,
  };
}

export async function putJsonCreateOnly(
  bucket: R2Bucket,
  key: string,
  data: unknown,
): Promise<CreateOnlyPutResult> {
  const bytes = serializedJsonBytes(data);
  const digest = `sha256:${await sha256Hex(bytes)}`;
  return putBytesCreateOnly(bucket, key, bytes, {
    digest,
    contentType: "application/json; charset=utf-8",
    customMetadata: {
      plane: "research_mass_eval",
      wave: "research-mass-eval",
    },
  });
}

/** Exact-byte create-only write shared by immutable Container output planes. */
export async function putBytesCreateOnly(
  bucket: R2Bucket,
  key: string,
  bytes: Uint8Array,
  options: CreateOnlyBytesOptions,
): Promise<CreateOnlyPutResult> {
  const digest = `sha256:${await sha256Hex(bytes)}`;
  if (digest !== options.digest) {
    return { key, bytes: 0, created: false, digest, conflict: true, status: 409 };
  }
  const existing = await compareExisting(bucket, key, digest);
  if (existing) return existing;
  const put = await bucket.put(key, bytes, {
    httpMetadata: { contentType: options.contentType },
    customMetadata: {
      ...options.customMetadata,
      sha256: digest,
      immutable: "true",
    },
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (put === null) {
    const raced = await compareExisting(bucket, key, digest);
    if (raced) return raced;
    return { key, bytes: 0, created: false, digest, conflict: true, status: 409 };
  }
  return { key, bytes: bytes.byteLength, created: true, digest, conflict: false };
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
    return { key, bytes: existing.size, created: false, digest, conflict: false };
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
    return { key, bytes: 0, created: false, digest, conflict: false };
  }
  return { key, bytes: bytes.byteLength, created: true, digest, conflict: false };
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
  if (childPuts.some((child) => child.conflict)) {
    return {
      children: childPuts,
      manifest: {
        key: manifest.key,
        bytes: 0,
        created: false,
        digest: "",
        conflict: true,
        status: 409,
      },
      ok: false,
      conflict: true,
      verified: false,
    };
  }
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
  if (manifestPut.conflict) {
    return {
      children: childPuts,
      manifest: manifestPut,
      ok: false,
      conflict: true,
      verified: false,
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
