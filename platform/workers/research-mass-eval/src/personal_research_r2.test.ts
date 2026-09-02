import { describe, expect, it, vi } from "vitest";

import {
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  PERSONAL_RESEARCH_RUNNER_VERSION,
} from "./personal_research_contract";
import { personalResearchR2Outbound } from "./personal_research_r2";
import { CONTROLLED_PILOT_RUNNER_VERSION } from "./controlled_pilot_contract";
import { CONTROLLED_JSON_TYPE,
  CONTROLLED_LEASE_MAX_BYTES,
  CONTROLLED_LEASE_TTL_SECONDS } from "./controlled_pilot_container_r2";

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

  it("rejects snapshot gzip PUT above the 4 GiB transport bound", async () => {
    const raw = "d".repeat(64);
    const key = `research/personal/snapshots/sha256=${raw}.sqlite.gz`;
    const bucket = {
      head: vi.fn(),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const response = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          "content-length": String(PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES + 1),
          "x-personal-job-id": "snap-1",
          "x-personal-request-digest": `sha256:${"b".repeat(64)}`,
          "x-content-sha256": `sha256:${THREE_BYTE_SHA256}`,
          "x-personal-raw-sha256": `sha256:${raw}`,
        },
        body: new Uint8Array([1, 2, 3]),
      }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "invalid snapshot length" });
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("rejects snapshot GET above the 4 GiB transport bound", async () => {
    const sha = "a".repeat(64);
    const key = `research/personal/snapshots/sha256=${sha}.sqlite.gz`;
    const object = r2Object(key, new Uint8Array([1, 2, 3]));
    object.size = PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES + 1;
    const bucket = {
      get: vi.fn(async () => object),
      head: vi.fn(async () => object),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const get = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`),
      { STRUCTURED_BUCKET: bucket },
    );
    const head = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, { method: "HEAD" }),
      { STRUCTURED_BUCKET: bucket },
    );
    expect(get.status).toBe(400);
    expect(head.status).toBe(400);
    expect(bucket.put).not.toHaveBeenCalled();
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
      observed_through: "2024-12-31T16:00:00+09:00",
      revision_window_calendar_days: 40,
      revision_coverage: "BOUNDED_WINDOW",
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
type StoredObject = {
  body: Uint8Array;
  etag: string;
  customMetadata?: Record<string, string>;
};

function casBucket(hooks?: { afterLeaseGet?: () => void }) {
  const objects = new Map<string, StoredObject>();
  let generation = 0;
  const bucket = {
    objects,
    head: async (key: string) => {
      const stored = objects.get(key);
      if (!stored) return null;
      return {
        key,
        size: stored.body.byteLength,
        etag: stored.etag,
        httpEtag: stored.etag,
        customMetadata: stored.customMetadata,
      };
    },
    get: async (key: string) => {
      const stored = objects.get(key);
      if (!stored) return null;
      const snapshot = {
        key,
        size: stored.body.byteLength,
        etag: stored.etag,
        httpEtag: stored.etag,
        customMetadata: stored.customMetadata ? { ...stored.customMetadata } : undefined,
        arrayBuffer: async () =>
          stored.body.buffer.slice(
            stored.body.byteOffset,
            stored.body.byteOffset + stored.body.byteLength,
          ),
      };
      if (key.endsWith("/container-lease.json") && hooks?.afterLeaseGet) {
        const takeover = hooks.afterLeaseGet;
        hooks.afterLeaseGet = undefined;
        takeover();
      }
      return snapshot;
    },
    put: async (
      key: string,
      value: ArrayBuffer | Uint8Array,
      options?: {
        onlyIf?: { etagDoesNotMatch?: string; etagMatches?: string };
        customMetadata?: Record<string, string>;
      },
    ) => {
      const stored = objects.get(key);
      if (options?.onlyIf?.etagDoesNotMatch === "*" && stored) return null;
      if (options?.onlyIf?.etagMatches) {
        if (!stored || stored.etag !== options.onlyIf.etagMatches) return null;
      }
      const body = value instanceof Uint8Array ? value : new Uint8Array(value as ArrayBuffer);
      generation += 1;
      const etag = `etag-${generation}`;
      objects.set(key, {
        body,
        etag,
        customMetadata: options?.customMetadata ? { ...options.customMetadata } : undefined,
      });
      return { key, etag, httpEtag: etag, size: body.byteLength };
    },
  };
  return bucket as typeof bucket & R2Bucket;
}

describe("controlled container R2 production router", () => {
  it("allows only closed stage/terminal keys with runner_version and create-only identity", async () => {
    const jobId = "controlled-job-1";
    const requestDigest = `sha256:${"ab".repeat(32)}`;
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const key = `research/controlled_pilot/v1/jobs/${jobId}/container-stage.json`;
    const bodyObj = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      status: "QUEUED",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(bodyObj));
    const digest = `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
    const headers = {
      "content-length": String(bytes.byteLength),
      "content-type": CONTROLLED_JSON_TYPE,
      "x-personal-job-id": jobId,
      "x-personal-request-digest": requestDigest,
      "x-personal-runner-version": CONTROLLED_PILOT_RUNNER_VERSION,
      "x-personal-job-kind": "controlled-pilot",
      "x-content-sha256": digest,
    };
    const created = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, { method: "PUT", headers, body: bytes }),
      env,
    );
    expect(created.status).toBe(201);
    const again = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, { method: "PUT", headers, body: bytes }),
      env,
    );
    expect(again.status).toBe(200);
    const different = new TextEncoder().encode(JSON.stringify({ ...bodyObj, execution_id: `sha256:${"cd".repeat(32)}` }));
    const differentDigest = `sha256:${hex(await crypto.subtle.digest("SHA-256", different))}`;
    const conflict = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: { ...headers, "content-length": String(different.byteLength), "x-content-sha256": differentDigest },
        body: different,
      }),
      env,
    );
    expect(conflict.status).toBe(409);
    const missingRunner = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          "content-length": String(bytes.byteLength),
          "content-type": CONTROLLED_JSON_TYPE,
          "x-personal-job-id": jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-job-kind": "controlled-pilot",
          "x-content-sha256": digest,
        },
        body: bytes,
      }),
      env,
    );
    expect(missingRunner.status).toBe(403);
    const arbitrary = await personalResearchR2Outbound(
      new Request(`http://research.r2/research/controlled_pilot/v1/jobs/${jobId}/evil.json`, {
        method: "PUT",
        headers,
        body: bytes,
      }),
      env,
    );
    expect(arbitrary.status).toBe(403);
    const leaseKey = `research/controlled_pilot/v1/jobs/${jobId}/container-lease.json`;
    const leaseObj = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      kind: "controlled-pilot",
      owner_nonce: "owner-nonce-1",
      fencing_token: 1,
      expires_at: Date.now() / 1000 + CONTROLLED_LEASE_TTL_SECONDS,
      heartbeat_at: Date.now() / 1000,
      status: "CLAIMED",
    };
    const leaseBytes = new TextEncoder().encode(JSON.stringify(leaseObj));
    const leaseDigest = `sha256:${hex(await crypto.subtle.digest("SHA-256", leaseBytes))}`;
    const createdLease = await personalResearchR2Outbound(
      new Request(`http://research.r2/${leaseKey}`, {
        method: "PUT",
        headers: {
          ...headers,
          "content-length": String(leaseBytes.byteLength),
          "x-content-sha256": leaseDigest,
          "if-none-match": "*",
        },
        body: leaseBytes,
      }),
      env,
    );
    expect(createdLease.status).toBe(201);
    const terminalKey = `research/controlled_pilot/v1/jobs/${jobId}/container-terminal.json`;
    const terminalObj = {
      ok: true,
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      status: "COMPLETED",
      owner_nonce: "owner-nonce-1",
      fencing_token: 1,
      automatic_promotion: false,
      live_orders_enabled: false,
      ephemeral_cleaned: true,
      papers: [{ k: 1 }, { k: 2 }, { k: 3 }, { k: 4 }],
      risks: [{ k: 1 }, { k: 2 }, { k: 3 }, { k: 4 }],
      selection: { decision: "HOLD" },
      knowledge: { kind: "knowledge" },
      generation: 1,
      max_parallel: 2,
    };
    const terminalBytes = new TextEncoder().encode(JSON.stringify(terminalObj));
    const terminalDigest = `sha256:${hex(await crypto.subtle.digest("SHA-256", terminalBytes))}`;
    const terminalDenied = await personalResearchR2Outbound(
      new Request(`http://research.r2/${terminalKey}`, {
        method: "PUT",
        headers: { ...headers, "content-length": String(terminalBytes.byteLength), "x-content-sha256": terminalDigest },
        body: terminalBytes,
      }),
      env,
    );
    expect(terminalDenied.status).toBe(409);
    const terminal = await personalResearchR2Outbound(
      new Request(`http://research.r2/${terminalKey}`, {
        method: "PUT",
        headers: {
          ...headers,
          "content-length": String(terminalBytes.byteLength),
          "x-content-sha256": terminalDigest,
          "x-personal-lease-owner": "owner-nonce-1",
          "x-personal-fencing-token": "1",
        },
        body: terminalBytes,
      }),
      env,
    );
    expect(terminal.status).toBe(201);
    const conflictLease = await personalResearchR2Outbound(
      new Request(`http://research.r2/${leaseKey}`, {
        method: "PUT",
        headers: {
          ...headers,
          "content-length": String(leaseBytes.byteLength),
          "x-content-sha256": leaseDigest,
          "if-none-match": "*",
        },
        body: leaseBytes,
      }),
      env,
    );
    expect(conflictLease.status).toBe(412);
    const takeoverHeartbeat = Date.now() / 1000;
    const takeoverObj = {
      ...leaseObj,
      owner_nonce: "owner-nonce-2",
      heartbeat_at: takeoverHeartbeat,
      expires_at: takeoverHeartbeat + CONTROLLED_LEASE_TTL_SECONDS,
      fencing_token: 2,
    };
    const takeoverBytes = new TextEncoder().encode(JSON.stringify(takeoverObj));
    const takeoverDigest = `sha256:${hex(await crypto.subtle.digest("SHA-256", takeoverBytes))}`;
    const takeover = await personalResearchR2Outbound(
      new Request(`http://research.r2/${leaseKey}`, {
        method: "PUT",
        headers: {
          ...headers,
          "content-length": String(takeoverBytes.byteLength),
          "x-content-sha256": takeoverDigest,
          "if-match": "etag-1",
        },
        body: takeoverBytes,
      }),
      env,
    );
    expect(takeover.status).toBe(412);
    const malformed = await personalResearchR2Outbound(
      new Request(`http://research.r2/${leaseKey}`, {
        method: "PUT",
        headers: {
          ...headers,
          "content-length": "2",
          "x-content-sha256": `sha256:${hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("{}")))}`,
          "if-none-match": "*",
        },
        body: "{}",
      }),
      env,
    );
    expect(malformed.status).toBeGreaterThanOrEqual(400);
    const lying = new TextEncoder().encode("x".repeat(64));
    const lyingDigest = `sha256:${hex(await crypto.subtle.digest("SHA-256", lying))}`;
    const falseSmall = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: { ...headers, "content-length": "4", "x-content-sha256": lyingDigest },
        body: lying,
      }),
      env,
    );
    expect([400, 413].includes(falseSmall.status)).toBe(true);
    const oversized = new Uint8Array(CONTROLLED_LEASE_MAX_BYTES + 1);
    const noHeader = await personalResearchR2Outbound(
      new Request(`http://research.r2/${leaseKey}`, {
        method: "PUT",
        headers: {
          "content-type": CONTROLLED_JSON_TYPE,
          "x-personal-job-id": jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": CONTROLLED_PILOT_RUNNER_VERSION,
          "x-personal-job-kind": "controlled-pilot",
          "x-content-sha256": `sha256:${hex(await crypto.subtle.digest("SHA-256", leaseBytes))}`,
          "if-none-match": "*",
        },
        body: leaseBytes,
      }),
      env,
    );
    expect([201, 200, 412].includes(noHeader.status)).toBe(true);
  });
});

describe("controlled terminal lease CAS fence", () => {
  const jobId = "controlled-job-2";
  const requestDigest = `sha256:${"ab".repeat(32)}`;
  const identityHeaders = {
    "content-type": CONTROLLED_JSON_TYPE,
    "x-personal-job-id": jobId,
    "x-personal-request-digest": requestDigest,
    "x-personal-runner-version": CONTROLLED_PILOT_RUNNER_VERSION,
    "x-personal-job-kind": "controlled-pilot",
  };

  function stageLike(status: string, owner: string, token: number) {
    const bind = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      status,
      owner_nonce: owner,
      fencing_token: token,
    };
    if (status === "FAILED") {
      return {
        ...bind,
        ok: false,
        error: "controlled_execution_failed",
        go: false,
        automatic_promotion: false,
        live_orders_enabled: false,
      };
    }
    return {
      ...bind,
      ok: true,
      automatic_promotion: false,
      live_orders_enabled: false,
      ephemeral_cleaned: true,
      papers: [{ k: 1 }, { k: 2 }, { k: 3 }, { k: 4 }],
      risks: [{ k: 1 }, { k: 2 }, { k: 3 }, { k: 4 }],
      selection: { decision: "HOLD" },
      knowledge: { kind: "knowledge" },
      generation: 1,
      max_parallel: 2,
    };
  }

  function leaseDoc(owner: string, token: number) {
    return {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      kind: "controlled-pilot",
      owner_nonce: owner,
      fencing_token: token,
      expires_at: Date.now() / 1000 + CONTROLLED_LEASE_TTL_SECONDS,
      heartbeat_at: Date.now() / 1000,
      status: "CLAIMED",
    };
  }

  async function putJson(
    env: { STRUCTURED_BUCKET: R2Bucket },
    key: string,
    value: unknown,
    extra: Record<string, string> = {},
  ) {
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    const digest = `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
    return personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          ...identityHeaders,
          "content-length": String(bytes.byteLength),
          "x-content-sha256": digest,
          ...extra,
        },
        body: bytes,
      }),
      env,
    );
  }

  it("rejects a stale owner after takeover between lease GET and terminal CAS", async () => {
    const hooks: { afterLeaseGet?: () => void } = {};
    const bucket = casBucket(hooks);
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = `research/controlled_pilot/v1/jobs/${jobId}/container-lease.json`;
    const terminalKey = `research/controlled_pilot/v1/jobs/${jobId}/container-terminal.json`;
    const createdLease = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(createdLease.status).toBe(201);

    hooks.afterLeaseGet = () => {
      const takeoverBytes = new TextEncoder().encode(JSON.stringify(leaseDoc("owner-nonce-2", 2)));
      bucket.objects.set(leaseKey, {
        body: takeoverBytes,
        etag: "etag-taken",
        customMetadata: { plane: "controlled_pilot", job_id: jobId },
      });
    };

    const stale = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(stale.status).toBe(409);
    expect(bucket.objects.has(terminalKey)).toBe(false);

    const current = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-2", 2), {
      "x-personal-lease-owner": "owner-nonce-2",
      "x-personal-fencing-token": "2",
    });
    expect(current.status).toBe(201);
    const got = await personalResearchR2Outbound(
      new Request(`http://research.r2/${terminalKey}`, {
        method: "GET",
        headers: identityHeaders,
      }),
      env,
    );
    expect(got.status).toBe(200);
    expect(JSON.parse(await got.text()).status).toBe("COMPLETED");

    const replay = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-2", 2), {
      "x-personal-lease-owner": "owner-nonce-2",
      "x-personal-fencing-token": "2",
    });
    expect(replay.status).toBe(200);

    const conflicting = await putJson(env, terminalKey, stageLike("FAILED", "owner-nonce-2", 2), {
      "x-personal-lease-owner": "owner-nonce-2",
      "x-personal-fencing-token": "2",
    });
    expect(conflicting.status).toBe(409);
    const storedLease = bucket.objects.get(leaseKey);
    expect(storedLease).toBeTruthy();
    expect(JSON.parse(new TextDecoder().decode(storedLease!.body)).status).toBe("TERMINAL");
    const storedTerminal = await personalResearchR2Outbound(
      new Request(`http://research.r2/${terminalKey}`, {
        method: "GET",
        headers: identityHeaders,
      }),
      env,
    );
    expect(JSON.parse(await storedTerminal.text()).status).toBe("COMPLETED");
  });
});
