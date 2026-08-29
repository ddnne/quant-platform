import { describe, expect, it, vi } from "vitest";

import { personalResearchR2Outbound } from "./personal_research_r2";

const THREE_BYTE_SHA256 =
  "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81";

function hex(bytes: ArrayBuffer | ArrayBufferView): string {
  const view = ArrayBuffer.isView(bytes)
    ? new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    : new Uint8Array(bytes);
  return [...view].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function r2Object(
  key: string,
  bytes: Uint8Array,
  customMetadata: Record<string, string> = {},
): R2ObjectBody {
  return {
    key,
    version: "v1",
    size: bytes.byteLength,
    etag: "etag",
    httpEtag: '"etag"',
    uploaded: new Date(0),
    checksums: {} as R2Checksums,
    customMetadata,
    httpMetadata: {},
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
    writeHttpMetadata() {},
  } as unknown as R2ObjectBody;
}

describe("personal Container R2 capability", () => {
  it("streams the one content-addressed snapshot and denies arbitrary reads", async () => {
    const sha = "a".repeat(64);
    const key = `research/personal/snapshots/sha256=${sha}.sqlite`;
    const object = r2Object(key, new Uint8Array([1, 2, 3]));
    const bucket = {
      get: vi.fn(async (got: string) => (got === key ? object : null)),
      head: vi.fn(),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const allowed = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(allowed.status).toBe(200);
    expect(new Uint8Array(await allowed.arrayBuffer())).toEqual(
      new Uint8Array([1, 2, 3]),
    );
    const denied = await personalResearchR2Outbound(
      new Request("http://research.r2/other/private.sqlite"),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(denied.status).toBe(403);
    expect(bucket.get).toHaveBeenCalledTimes(1);
  });

  it("passes result bodies to R2 as streams and freezes the output key", async () => {
    const jobId = "exact-four-1";
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const contentDigest = `sha256:${THREE_BYTE_SHA256}`;
    let observed: unknown;
    let observedOptions: R2PutOptions | undefined;
    const bucket = {
      head: vi.fn(async () => null),
      put: vi.fn(async (_key: string, body: unknown, options: R2PutOptions) => {
        observed = body;
        observedOptions = options;
        return { key: _key };
      }),
    } as unknown as R2Bucket;
    const response = await personalResearchR2Outbound(
      new Request(
        `http://research.r2/research/personal/jobs/job=${jobId}/result.tar.gz`,
        {
          method: "PUT",
          headers: {
            "content-length": "3",
            "x-personal-job-id": jobId,
            "x-personal-request-digest": requestDigest,
            "x-content-sha256": contentDigest,
          },
          body: new Uint8Array([1, 2, 3]),
        },
      ),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(response.status).toBe(201);
    expect(observed).toBeInstanceOf(ReadableStream);
    expect(hex(observedOptions!.sha256!)).toBe(THREE_BYTE_SHA256);

    const denied = await personalResearchR2Outbound(
      new Request(
        "http://research.r2/research/personal/jobs/job=another/result.tar.gz",
        {
          method: "PUT",
          headers: {
            "content-length": "3",
            "x-personal-job-id": jobId,
            "x-personal-request-digest": requestDigest,
            "x-content-sha256": contentDigest,
          },
          body: new Uint8Array([1, 2, 3]),
        },
      ),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(denied.status).toBe(400);
  });

  it("requires R2 to verify the declared result digest against the stream", async () => {
    const jobId = "exact-four-checksum";
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const bucket = {
      head: vi.fn(async () => null),
      put: vi.fn(
        async (_key: string, body: ReadableStream, options: R2PutOptions) => {
          const actual = await crypto.subtle.digest(
            "SHA-256",
            await new Response(body).arrayBuffer(),
          );
          if (hex(actual) !== hex(options.sha256!)) {
            throw new Error("R2 checksum mismatch");
          }
          return { key: _key };
        },
      ),
    } as unknown as R2Bucket;
    const response = await personalResearchR2Outbound(
      new Request(
        `http://research.r2/research/personal/jobs/job=${jobId}/result.tar.gz`,
        {
          method: "PUT",
          headers: {
            "content-length": "3",
            "x-personal-job-id": jobId,
            "x-personal-request-digest": requestDigest,
            "x-content-sha256": `sha256:${"c".repeat(64)}`,
          },
          body: new Uint8Array([1, 2, 3]),
        },
      ),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      error: "result upload checksum rejected",
    });
  });
});
