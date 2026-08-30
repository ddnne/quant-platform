import { describe, expect, it, vi } from "vitest";

import {
  PERSONAL_ACQUISITION_CACHE_FORMAT,
  PERSONAL_ACQUISITION_CACHE_GZIP_MAX_BYTES,
  PERSONAL_ACQUISITION_CACHE_PLANE,
  acquisitionCacheMonthIsClosed,
  isPersonalAcquisitionCacheOutboundRequest,
  parsePersonalAcquisitionCacheKey,
  personalAcquisitionCacheObjectKey,
  personalAcquisitionCacheR2Outbound,
} from "./personal_acquisition_cache_r2";
import { personalResearchR2Outbound } from "./personal_research_r2";

vi.stubGlobal(
  "FixedLengthStream",
  class extends TransformStream<Uint8Array, Uint8Array> {
    expectedLength: number;
    constructor(expectedLength: number | bigint) {
      const expected = Number(expectedLength);
      let seen = 0;
      super({
        transform(chunk, controller) {
          seen += chunk.byteLength;
          if (seen > expected) {
            controller.error(new Error("FixedLengthStream overflow"));
            return;
          }
          controller.enqueue(chunk);
        },
        flush(controller) {
          if (seen !== expected) {
            controller.error(new Error("FixedLengthStream length mismatch"));
          }
        },
      });
      this.expectedLength = expected;
    }
  },
);

const THREE_BYTE_SHA256 =
  "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81";
const RAW_DIGEST = `sha256:${"d".repeat(64)}`;
const CONTENT_DIGEST = `sha256:${THREE_BYTE_SHA256}`;
const IDENTITY = "a".repeat(64);
const KEY = personalAcquisitionCacheObjectKey({
  environment: "production",
  dataset: "markets_calendar",
  month: "2024-03",
  identity: IDENTITY,
});

function hex(bytes: ArrayBuffer | ArrayBufferView): string {
  const view = ArrayBuffer.isView(bytes)
    ? new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    : new Uint8Array(bytes);
  return [...view].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function checksumBuffer(): ArrayBuffer {
  const bytes = new Uint8Array(32);
  for (let index = 0; index < 32; index += 1) {
    bytes[index] = Number.parseInt(THREE_BYTE_SHA256.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes.buffer;
}

function getHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    accept: "application/gzip",
    "accept-encoding": "identity",
    connection: "close",
    host: "research.r2",
    "user-agent": "quant-personal-history/v13",
    ...extra,
  };
}

function putHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    ...getHeaders(),
    "content-type": "application/gzip",
    "content-length": "3",
    "x-content-sha256": CONTENT_DIGEST,
    "x-acquisition-cache-raw-sha256": RAW_DIGEST,
    ...extra,
  };
}

function metadata(overrides: Record<string, string> = {}): Record<string, string> {
  return {
    plane: PERSONAL_ACQUISITION_CACHE_PLANE,
    format: PERSONAL_ACQUISITION_CACHE_FORMAT,
    environment: "production",
    dataset: "markets_calendar",
    month: "2024-03",
    identity: IDENTITY,
    sha256: CONTENT_DIGEST,
    raw_sha256: RAW_DIGEST,
    immutable: "true",
    ...overrides,
  };
}

function r2Object(
  key: string,
  bytes: Uint8Array,
  customMetadata: Record<string, string> = metadata(),
): R2ObjectBody {
  return {
    key,
    version: "v1",
    size: bytes.byteLength,
    etag: "etag",
    httpEtag: '"etag"',
    uploaded: new Date(0),
    checksums: { sha256: checksumBuffer() } as R2Checksums,
    customMetadata,
    httpMetadata: { contentType: "application/gzip" },
    range: undefined,
    storageClass: "Standard",
    ssecKeyMd5: undefined,
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    }),
    bodyUsed: false,
    arrayBuffer: async () => bytes.buffer,
    text: async () => new TextDecoder().decode(bytes),
    json: async () => JSON.parse(new TextDecoder().decode(bytes)),
    blob: async () => new Blob([bytes]),
    writeHttpMetadata(headers: Headers) {
      headers.set("content-type", "application/gzip");
    },
  } as unknown as R2ObjectBody;
}

describe("personal acquisition cache R2", () => {
  it("parses only the canonical closed-month key", () => {
    expect(parsePersonalAcquisitionCacheKey(KEY)).toEqual({
      environment: "production",
      dataset: "markets_calendar",
      month: "2024-03",
      identity: IDENTITY,
      key: KEY,
    });
    expect(
      parsePersonalAcquisitionCacheKey(KEY.replace("2024-03", "2024-13")),
    ).toBeNull();
    expect(isPersonalAcquisitionCacheOutboundRequest(new Request("http://research.r2/x"), KEY)).toBe(
      true,
    );
  });

  it("GET/HEAD allowlist and 404 miss", async () => {
    const object = r2Object(KEY, new Uint8Array([1, 2, 3]));
    const bucket = {
      get: vi.fn(async (got: string) => (got === KEY ? object : null)),
      head: vi.fn(async (got: string) => (got === KEY ? object : null)),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const env = { STRUCTURED_BUCKET: bucket };
    const got = await personalResearchR2Outbound(
      new Request(`http://research.r2/${KEY}`, { headers: getHeaders() }),
      env,
    );
    expect(got.status).toBe(200);
    expect(got.headers.get("content-type")).toBe("application/gzip");
    expect(got.headers.get("x-content-sha256")).toBe(CONTENT_DIGEST);
    const head = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, { method: "HEAD", headers: getHeaders() }),
      env,
      KEY,
    );
    expect(head.status).toBe(200);
    expect(head.headers.get("content-length")).toBe("3");

    const missingBucket = {
      get: vi.fn(async () => null),
      head: vi.fn(async () => null),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const missing = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, { headers: getHeaders() }),
      { STRUCTURED_BUCKET: missingBucket },
      KEY,
    );
    expect(missing.status).toBe(404);

    const extraHeader = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        headers: getHeaders({ "x-personal-job-id": "job-1" }),
      }),
      env,
      KEY,
    );
    expect(extraHeader.status).toBe(403);
  });

  it("rejects credential-like GET/PUT headers", async () => {
    const bucket = { get: vi.fn(), head: vi.fn(), put: vi.fn() } as unknown as R2Bucket;
    const env = { STRUCTURED_BUCKET: bucket };
    for (const name of ["authorization", "cookie", "x-api-key", "x-jquants-api-key"]) {
      const getDenied = await personalAcquisitionCacheR2Outbound(
        new Request(`http://research.r2/${KEY}`, {
          headers: getHeaders({ [name]: "secret-value" }),
        }),
        env,
        KEY,
      );
      expect(getDenied.status).toBe(403);
      const putDenied = await personalAcquisitionCacheR2Outbound(
        new Request(`http://research.r2/${KEY}`, {
          method: "PUT",
          headers: putHeaders({ [name]: "secret-value" }),
          body: new Uint8Array([1, 2, 3]),
        }),
        env,
        KEY,
      );
      expect(putDenied.status).toBe(403);
    }
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("PUT is create-only, identical is idempotent, different content conflicts", async () => {
    let observedOptions: R2PutOptions | undefined;
    const bucket = {
      head: vi.fn(async () => null),
      put: vi.fn(async (_key: string, body: unknown, options: R2PutOptions) => {
        observedOptions = options;
        const bytes = new Uint8Array(await new Response(body as BodyInit).arrayBuffer());
        return { key: _key, size: bytes.byteLength };
      }),
    } as unknown as R2Bucket;
    const created = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders(),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: bucket },
      KEY,
    );
    expect(created.status).toBe(201);
    expect(observedOptions?.onlyIf).toEqual({ etagDoesNotMatch: "*" });
    expect(hex(observedOptions!.sha256!)).toBe(THREE_BYTE_SHA256);
    expect(observedOptions?.customMetadata).toEqual(metadata());
    expect(JSON.stringify(observedOptions?.customMetadata).toLowerCase()).not.toContain(
      "authorization",
    );
    expect(JSON.stringify(observedOptions?.customMetadata).toLowerCase()).not.toContain("cookie");
    expect(JSON.stringify(observedOptions?.customMetadata).toLowerCase()).not.toContain("api_key");
    expect(JSON.stringify(observedOptions?.customMetadata).toLowerCase()).not.toContain("password");

    const existing = r2Object(KEY, new Uint8Array([1, 2, 3]));
    const reuseBucket = {
      head: vi.fn(async () => existing),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const reused = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders(),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: reuseBucket },
      KEY,
    );
    expect(reused.status).toBe(200);
    expect(await reused.json()).toEqual({ ok: true, created: false, key: KEY });
    expect(reuseBucket.put).not.toHaveBeenCalled();

    const conflict = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders({
          "x-content-sha256": `sha256:${"e".repeat(64)}`,
        }),
        body: new Uint8Array([9, 9, 9]),
      }),
      { STRUCTURED_BUCKET: reuseBucket },
      KEY,
    );
    expect(conflict.status).toBe(409);
  });

  it("rejects a path/identity mismatch and oversize PUT", async () => {
    const bucket = {
      head: vi.fn(async () => null),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const malformed = KEY.replace("2024-03", "2024-13");
    const mismatch = await personalResearchR2Outbound(
      new Request(`http://research.r2/${malformed}`, {
        method: "PUT",
        headers: putHeaders(),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(mismatch.status).toBe(403);

    const oversize = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders({
          "content-length": String(PERSONAL_ACQUISITION_CACHE_GZIP_MAX_BYTES + 1),
        }),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: bucket },
      KEY,
    );
    expect(oversize.status).toBe(400);
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("rejects current and future UTC month keys", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2024-03-15T12:00:00.000Z"));
      expect(acquisitionCacheMonthIsClosed("2024-03")).toBe(false);
      expect(acquisitionCacheMonthIsClosed("2024-04")).toBe(false);
      expect(acquisitionCacheMonthIsClosed("2024-02")).toBe(true);
      expect(parsePersonalAcquisitionCacheKey(KEY)).toBeNull();
      expect(
        parsePersonalAcquisitionCacheKey(KEY.replace("2024-03", "2024-04")),
      ).toBeNull();
      expect(
        parsePersonalAcquisitionCacheKey(KEY.replace("2024-03", "2024-02")),
      ).not.toBeNull();
      expect(isPersonalAcquisitionCacheOutboundRequest(new Request("http://research.r2/x"), KEY)).toBe(
        false,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("PUT declared length must match the streamed body and returned object size", async () => {
    const consumePut = {
      head: vi.fn(async () => null),
      put: vi.fn(async (_key: string, body: unknown) => {
        const bytes = new Uint8Array(await new Response(body as BodyInit).arrayBuffer());
        return { key: _key, size: bytes.byteLength };
      }),
    } as unknown as R2Bucket;
    const shorter = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders({ "content-length": "4" }),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: consumePut },
      KEY,
    );
    expect(shorter.status).toBe(502);
    const longer = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders({ "content-length": "2" }),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: consumePut },
      KEY,
    );
    expect(longer.status).toBe(502);

    const sizeMismatch = {
      head: vi.fn(async () => null),
      put: vi.fn(async (_key: string) => ({ key: _key, size: 99 })),
    } as unknown as R2Bucket;
    const mismatched = await personalAcquisitionCacheR2Outbound(
      new Request(`http://research.r2/${KEY}`, {
        method: "PUT",
        headers: putHeaders(),
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: sizeMismatch },
      KEY,
    );
    expect(mismatched.status).toBe(400);
    expect(await mismatched.json()).toEqual({ error: "acquisition cache length mismatch" });
  });
});
