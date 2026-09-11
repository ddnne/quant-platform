import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it } from "vitest";
import { personalResearchR2Outbound } from "../src/personal_research_r2";
import { PERSONAL_SNAPSHOT_FORMAT } from "../src/personal_snapshot_contract";

const runtimeEnv = env as { STRUCTURED_BUCKET: R2Bucket };

const BYTES = new Uint8Array([1, 2, 3]);
const ACTUAL_HEX =
  "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81";
const CONTENT_DIGEST = `sha256:${ACTUAL_HEX}`;
const REQUEST_DIGEST = `sha256:${"b".repeat(64)}`;
const WRONG_DIGEST = `sha256:${"c".repeat(64)}`;
const RAW_HEX = "d".repeat(64);
const RAW_DIGEST = `sha256:${RAW_HEX}`;

type Kind = "result" | "snapshot";
type ProduceMode = "complete" | "short" | "overflow" | "abort";

function hex(data: ArrayBuffer | ArrayBufferView): string {
  const bytes =
    data instanceof ArrayBuffer
      ? new Uint8Array(data)
      : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

function objectKey(kind: Kind, jobId: string): string {
  return kind === "result"
    ? `research/personal/jobs/job=${jobId}/result.tar.gz`
    : `research/personal/snapshots/sha256=${RAW_HEX}.sqlite.gz`;
}

function manifestKey(kind: Kind, jobId: string): string {
  return kind === "result"
    ? `research/personal/jobs/job=${jobId}/manifest.json`
    : `research/personal/snapshot-builds/job=${jobId}/manifest.json`;
}

function uploadHeaders(
  kind: Kind,
  jobId: string,
  contentDigest: string,
): Record<string, string> {
  const headers: Record<string, string> = {
    "content-length": "3",
    "x-personal-job-id": jobId,
    "x-personal-request-digest": REQUEST_DIGEST,
    "x-content-sha256": contentDigest,
  };
  if (kind === "snapshot") {
    headers["x-personal-raw-sha256"] = RAW_DIGEST;
  }
  return headers;
}

function completedManifest(
  kind: Kind,
  jobId: string,
): Record<string, unknown> {
  if (kind === "result") {
    return {
      job_id: jobId,
      request_digest: REQUEST_DIGEST,
      status: "COMPLETED",
      result_sha256: CONTENT_DIGEST,
    };
  }
  return {
    job_id: jobId,
    request_digest: REQUEST_DIGEST,
    status: "COMPLETED",
    research_state: "PERSONAL_DRAFT",
    completeness_claim: "NONE",
    controlled_live_eligibility: "FORBIDDEN",
    raw_sha256: RAW_DIGEST,
    gzip_sha256: CONTENT_DIGEST,
    snapshot_key: objectKey("snapshot", jobId),
    observed_through: "2026-09-01",
    revision_window_calendar_days: 1,
    revision_coverage: "BOUNDED_WINDOW",
  };
}

async function putWithProducer(
  kind: Kind,
  jobId: string,
  mode: ProduceMode,
  contentDigest: string,
): Promise<{
  response: Response;
  producer: PromiseSettledResult<void>;
}> {
  const stream = new FixedLengthStream(3);
  const producer = (async () => {
    const writer = stream.writable.getWriter();
    try {
      if (mode === "abort") {
        await writer.write(BYTES.subarray(0, 1));
        await writer.abort(new Error("test producer abort"));
        return;
      }
      if (mode === "short") {
        await writer.write(BYTES.subarray(0, 2));
        await writer.close();
        return;
      }
      if (mode === "overflow") {
        await writer.write(new Uint8Array([1, 2, 3, 4]));
        await writer.close();
        return;
      }
      await writer.write(BYTES);
      await writer.close();
    } finally {
      try {
        writer.releaseLock();
      } catch {
        /* close/abort already released the lock */
      }
    }
  })();
  const producerSettled: Promise<PromiseSettledResult<void>> = producer.then(
    () => ({ status: "fulfilled", value: undefined }),
    (reason: unknown) => ({ status: "rejected", reason }),
  );
  const response = await personalResearchR2Outbound(
    new Request(`http://research.r2/${objectKey(kind, jobId)}`, {
      method: "PUT",
      headers: uploadHeaders(kind, jobId, contentDigest),
      body: stream.readable,
    }),
    runtimeEnv,
  );
  return { response, producer: await producerSettled };
}

async function putCompletedManifest(
  kind: Kind,
  jobId: string,
): Promise<Response> {
  const bytes = new TextEncoder().encode(
    JSON.stringify(completedManifest(kind, jobId)),
  );
  const digest = `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
  return personalResearchR2Outbound(
    new Request(`http://research.r2/${manifestKey(kind, jobId)}`, {
      method: "PUT",
      headers: {
        "content-length": String(bytes.byteLength),
        "x-personal-job-id": jobId,
        "x-personal-request-digest": REQUEST_DIGEST,
        "x-content-sha256": digest,
      },
      body: bytes,
    }),
    runtimeEnv,
  );
}

describe("personalResearchR2Outbound workerd/R2 runtime", () => {
  afterEach(() => reset());

  it.each([
    { suffix: ".sqlite", contentType: "application/vnd.sqlite3" },
    { suffix: ".sqlite.gz", contentType: "application/gzip" },
  ] as const)(
    "GET and HEAD seeded snapshot $suffix",
    async ({ suffix, contentType }) => {
      const key = `research/personal/snapshots/sha256=${ACTUAL_HEX}${suffix}`;
      await runtimeEnv.STRUCTURED_BUCKET.put(key, BYTES, {
        httpMetadata: {
          contentType: "application/octet-stream",
          contentEncoding: "gzip",
        },
      });
      const get = await personalResearchR2Outbound(
        new Request(`http://research.r2/${key}`),
        runtimeEnv,
      );
      const head = await personalResearchR2Outbound(
        new Request(`http://research.r2/${key}`, { method: "HEAD" }),
        runtimeEnv,
      );
      expect(get.status).toBe(200);
      expect(get.headers.get("content-type")).toBe(contentType);
      expect(get.headers.get("content-encoding")).toBeNull();
      expect(get.headers.get("content-length")).toBe("3");
      expect(new Uint8Array(await get.arrayBuffer())).toEqual(BYTES);
      expect(head.status).toBe(200);
      expect(head.headers.get("content-type")).toBe(contentType);
      expect(head.headers.get("content-length")).toBe("3");
      expect(head.body).toBeNull();
    },
  );

  describe.each([{ kind: "result" as const }, { kind: "snapshot" as const }])(
    "$kind writer",
    ({ kind }) => {
      it("valid FixedLengthStream upload then COMPLETED manifest", async () => {
        const jobId = `r05-${kind}-ok`;
        const { response, producer } = await putWithProducer(
          kind,
          jobId,
          "complete",
          CONTENT_DIGEST,
        );
        expect(producer.status).toBe("fulfilled");
        expect(response.status).toBe(201);
        const stored = await runtimeEnv.STRUCTURED_BUCKET.get(
          objectKey(kind, jobId),
        );
        expect(stored).not.toBeNull();
        expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(BYTES);
        expect(hex(stored!.checksums.sha256!)).toBe(ACTUAL_HEX);
        expect(stored!.customMetadata?.sha256).toBe(CONTENT_DIGEST);
        if (kind === "snapshot") {
          expect(stored!.customMetadata?.raw_sha256).toBe(RAW_DIGEST);
          expect(stored!.customMetadata?.format).toBe(PERSONAL_SNAPSHOT_FORMAT);
        }
        const manifest = await putCompletedManifest(kind, jobId);
        expect(manifest.status).toBe(201);
        expect(
          await runtimeEnv.STRUCTURED_BUCKET.head(manifestKey(kind, jobId)),
        ).not.toBeNull();
      });

      it.each([
        { mode: "short" as const, digest: CONTENT_DIGEST, label: "short" },
        { mode: "overflow" as const, digest: CONTENT_DIGEST, label: "overflow" },
        { mode: "abort" as const, digest: CONTENT_DIGEST, label: "abort" },
        {
          mode: "complete" as const,
          digest: WRONG_DIGEST,
          label: "badsha",
        },
      ])(
        "failed stream $label then COMPLETED manifest 409",
        async ({ mode, digest, label }) => {
          const jobId = `r05-${kind}-${label}`;
          const { response } = await putWithProducer(
            kind,
            jobId,
            mode,
            digest,
          );
          expect(response.status).toBe(502);
          expect(await response.json()).toEqual({
            error:
              kind === "result"
                ? "result upload checksum rejected"
                : "snapshot upload checksum rejected",
          });
          expect(
            await runtimeEnv.STRUCTURED_BUCKET.head(objectKey(kind, jobId)),
          ).toBeNull();
          const manifest = await putCompletedManifest(kind, jobId);
          expect(manifest.status).toBe(409);
          expect(await manifest.json()).toEqual({
            error:
              kind === "result"
                ? "completed manifest has no matching result"
                : "completed snapshot manifest has no matching object",
          });
          expect(
            await runtimeEnv.STRUCTURED_BUCKET.head(manifestKey(kind, jobId)),
          ).toBeNull();
        },
      );
    },
  );
});
