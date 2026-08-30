import { describe, expect, it, vi } from "vitest";

import { PERSONAL_RESEARCH_RUNNER_VERSION } from "./personal_research_contract";
import { personalResearchR2Outbound } from "./personal_research_r2";
import { PERSONAL_SNAPSHOT_FORMAT } from "./personal_snapshot_contract";

vi.stubGlobal(
  "FixedLengthStream",
  class extends TransformStream<Uint8Array, Uint8Array> {
    constructor(_expectedLength: number | bigint) {
      super();
    }
  },
);

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
  httpMetadata: R2HTTPMetadata = {},
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
    httpMetadata,
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
      if (httpMetadata.contentEncoding) {
        headers.set("content-encoding", httpMetadata.contentEncoding);
      }
      if (httpMetadata.contentType) {
        headers.set("content-type", httpMetadata.contentType);
      }
    },
  } as unknown as R2ObjectBody;
}

describe("personal Container R2 capability", () => {
  it.each([
    [".sqlite", "application/vnd.sqlite3"],
    [".sqlite.gz", "application/gzip"],
  ])("streams a content-addressed%s snapshot", async (suffix, contentType) => {
    const sha = "a".repeat(64);
    const key = `research/personal/snapshots/sha256=${sha}${suffix}`;
    const object = r2Object(key, new Uint8Array([1, 2, 3]), {}, {
      contentEncoding: "gzip",
      contentType: "application/octet-stream",
    });
    const bucket = {
      get: vi.fn(async (got: string) => (got === key ? object : null)),
      head: vi.fn(async (got: string) => (got === key ? object : null)),
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
    expect(allowed.headers.get("content-type")).toBe(contentType);
    expect(allowed.headers.get("content-encoding")).toBeNull();
    expect(allowed.headers.get("content-length")).toBe("3");
    const head = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, { method: "HEAD" }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(head.status).toBe(200);
    expect(head.headers.get("content-type")).toBe(contentType);
    expect(head.headers.get("content-length")).toBe("3");
    const denied = await personalResearchR2Outbound(
      new Request("http://research.r2/other/private.sqlite"),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(denied.status).toBe(403);
    expect(bucket.get).toHaveBeenCalledTimes(1);
    expect(bucket.head).toHaveBeenCalledTimes(1);
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

  it("uploads gzip first and rejects a successful snapshot manifest without that object", async () => {
    const raw = "d".repeat(64);
    const gzipDigest = `sha256:${THREE_BYTE_SHA256}`;
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const key = `research/personal/snapshots/sha256=${raw}.sqlite.gz`;
    const puts: string[] = [];
    const bucket = {
      head: vi.fn(async () => null),
      put: vi.fn(async (putKey: string) => {
        puts.push(putKey);
        return { key: putKey };
      }),
    } as unknown as R2Bucket;
    const gzip = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          "content-length": "3",
          "x-personal-job-id": "snap-1",
          "x-personal-request-digest": requestDigest,
          "x-content-sha256": gzipDigest,
          "x-personal-raw-sha256": `sha256:${raw}`,
        },
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(gzip.status).toBe(201);
    expect(puts).toEqual([key]);

    const manifest = {
      job_id: "snap-1",
      request_digest: requestDigest,
      status: "COMPLETED",
      research_state: "PERSONAL_DRAFT",
      completeness_claim: "NONE",
      controlled_live_eligibility: "FORBIDDEN",
      raw_sha256: `sha256:${raw}`,
      gzip_sha256: gzipDigest,
      snapshot_key: key,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(manifest));
    const digest = `sha256:${await (await import("./sha256")).sha256Hex(bytes)}`;
    const missing = await personalResearchR2Outbound(
      new Request(
        "http://research.r2/research/personal/snapshot-builds/job=snap-1/manifest.json",
        {
          method: "PUT",
          headers: {
            "content-length": String(bytes.byteLength),
            "x-personal-job-id": "snap-1",
            "x-personal-request-digest": requestDigest,
            "x-content-sha256": digest,
          },
          body: bytes,
        },
      ),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(missing.status).toBe(409);
    expect(puts).toEqual([key]);
  });

  it("reuses a content-addressed gzip object across jobs", async () => {
    const raw = "d".repeat(64);
    const gzipDigest = `sha256:${THREE_BYTE_SHA256}`;
    const key = `research/personal/snapshots/sha256=${raw}.sqlite.gz`;
    const checksum = new Uint8Array(32);
    for (let index = 0; index < 32; index += 1) {
      checksum[index] = Number.parseInt(THREE_BYTE_SHA256.slice(index * 2, index * 2 + 2), 16);
    }
    const existing = r2Object(key, new Uint8Array([1, 2, 3]), {
      sha256: gzipDigest,
      raw_sha256: `sha256:${raw}`,
      format: PERSONAL_SNAPSHOT_FORMAT,
    });
    existing.checksums = { sha256: checksum.buffer } as R2Checksums;
    const bucket = {
      head: vi.fn(async () => existing),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const reused = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          "content-length": "3",
          "x-personal-job-id": "snap-other",
          "x-personal-request-digest": `sha256:${"c".repeat(64)}`,
          "x-content-sha256": gzipDigest,
          "x-personal-raw-sha256": `sha256:${raw}`,
        },
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(reused.status).toBe(200);
    expect(await reused.json()).toEqual({ ok: true, created: false, key });
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("publishes a FAILED snapshot document without a snapshot object", async () => {
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const manifest = {
      job_id: "snap-fail",
      request_digest: requestDigest,
      status: "FAILED",
      research_state: "PERSONAL_DRAFT",
      completeness_claim: "NONE",
      controlled_live_eligibility: "FORBIDDEN",
      error: "oversized",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(manifest));
    const digest = `sha256:${await (await import("./sha256")).sha256Hex(bytes)}`;
    const bucket = {
      head: vi.fn(async () => null),
      put: vi.fn(async (key: string) => ({ key })),
    } as unknown as R2Bucket;
    const response = await personalResearchR2Outbound(
      new Request(
        "http://research.r2/research/personal/snapshot-builds/job=snap-fail/manifest.json",
        {
          method: "PUT",
          headers: {
            "content-length": String(bytes.byteLength),
            "x-personal-job-id": "snap-fail",
            "x-personal-request-digest": requestDigest,
            "x-content-sha256": digest,
          },
          body: bytes,
        },
      ),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(response.status).toBe(201);
    expect(bucket.put).toHaveBeenCalledOnce();
  });

  it("GETs an exact terminal manifest with closed identity headers", async () => {
    const jobId = "term-get-one";
    const key = `research/personal/jobs/job=${jobId}/manifest.json`;
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const manifest = {
      job_id: jobId,
      request_digest: requestDigest,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      status: "FAILED",
      cohort_id: "diverse-core-v1",
      universe_id: "topix_all",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(manifest));
    const object = r2Object(key, bytes);
    const bucket = {
      get: vi.fn(async () => object),
      head: vi.fn(),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const response = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": PERSONAL_RESEARCH_RUNNER_VERSION,
          "x-personal-job-kind": "research",
          "x-personal-cohort-id": "diverse-core-v1",
          "x-personal-universe-id": "topix_all",
        },
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(manifest);
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("GETs a vol-panel terminal with the closed job-kind headers", async () => {
    const jobId = "vol-panel-term";
    const key = `research/personal/vol-ratio-am-pm-v1/panel-builds/job=${jobId}/manifest.json`;
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const manifest = {
      job_id: jobId,
      request_digest: requestDigest,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      status: "FAILED",
      cohort_id: "personal-vol-ratio-am-pm-v1",
      kind: "vol-panel",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(manifest));
    const object = r2Object(key, bytes);
    const bucket = {
      get: vi.fn(async () => object),
      head: vi.fn(),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const response = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": PERSONAL_RESEARCH_RUNNER_VERSION,
          "x-personal-job-kind": "vol-panel",
          "x-personal-cohort-id": "personal-vol-ratio-am-pm-v1",
        },
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(manifest);
  });

  it("rejects extra identity headers, mismatched terminals, and non-terminal keys", async () => {
    const jobId = "term-deny";
    const key = `research/personal/jobs/job=${jobId}/manifest.json`;
    const requestDigest = `sha256:${"b".repeat(64)}`;
    const manifest = {
      job_id: jobId,
      request_digest: requestDigest,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      status: "FAILED",
      cohort_id: "diverse-core-v1",
      universe_id: "topix_all",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(manifest));
    const bucket = {
      get: vi.fn(async () => r2Object(key, bytes)),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const extra = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": PERSONAL_RESEARCH_RUNNER_VERSION,
          "x-personal-job-kind": "research",
          "x-personal-cohort-id": "diverse-core-v1",
          "x-personal-universe-id": "topix_all",
          "x-personal-extra": "nope",
        },
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(extra.status).toBe(403);
    const mismatch = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": jobId,
          "x-personal-request-digest": `sha256:${"c".repeat(64)}`,
          "x-personal-runner-version": PERSONAL_RESEARCH_RUNNER_VERSION,
          "x-personal-job-kind": "research",
          "x-personal-cohort-id": "diverse-core-v1",
          "x-personal-universe-id": "topix_all",
        },
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(mismatch.status).toBe(403);
    const resultKey = `research/personal/jobs/job=${jobId}/result.tar.gz`;
    const forbidden = await personalResearchR2Outbound(
      new Request(`http://research.r2/${resultKey}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": PERSONAL_RESEARCH_RUNNER_VERSION,
          "x-personal-job-kind": "research",
          "x-personal-cohort-id": "diverse-core-v1",
          "x-personal-universe-id": "topix_all",
        },
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(forbidden.status).toBe(403);
    expect(bucket.put).not.toHaveBeenCalled();
  });
});
