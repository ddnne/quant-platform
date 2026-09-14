import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it } from "vitest";
import { putStreamCreateOnly } from "../src/r2_stream_create_only";
import { sha256Hex } from "../src/sha256";

const runtimeEnv = env as { STRUCTURED_BUCKET: R2Bucket };
const JSON_TYPE = "application/json; charset=utf-8";

async function digestOf(bytes: Uint8Array): Promise<string> {
  return `sha256:${await sha256Hex(bytes)}`;
}

function startFixedLength(
  bytes: Uint8Array,
  mode: "complete" | "abort",
) {
  const stream = new FixedLengthStream(bytes.byteLength);
  const writer = stream.writable.getWriter();
  const producer = (async () => {
    try {
      if (mode === "abort") {
        await writer.write(bytes.subarray(0, 1));
        await writer.abort(new Error("test producer abort"));
        return;
      }
      await writer.write(bytes);
      await writer.close();
    } finally {
      try {
        writer.releaseLock();
      } catch {
        /* close/abort already released the lock */
      }
    }
  })();
  return {
    readable: stream.readable,
    writer,
    producer: producer.then(
      () => ({ status: "fulfilled" as const, value: undefined }),
      (reason: unknown) => ({ status: "rejected" as const, reason }),
    ),
  };
}

async function abortUnread(
  started: ReturnType<typeof startFixedLength>,
  outcome: "created" | "identical" | "conflict" | "checksum_rejected",
) {
  if (outcome === "created" || outcome === "checksum_rejected") return;
  try {
    await started.writer.abort("putStreamCreateOnly did not consume body");
  } catch {
    /* already closed, aborted, or consumed */
  }
}

async function putStream(
  key: string,
  bytes: Uint8Array,
  digest: string,
  mode: "complete" | "abort" = "complete",
) {
  const started = startFixedLength(bytes, mode);
  const outcome = await putStreamCreateOnly(
    runtimeEnv.STRUCTURED_BUCKET,
    key,
    started.readable,
    { digest, contentType: JSON_TYPE, size: bytes.byteLength },
  );
  await abortUnread(started, outcome);
  return { outcome, producer: await started.producer };
}

describe("putStreamCreateOnly workerd/R2", () => {
  afterEach(() => reset());

  it("creates once, retries identical content, and rejects a different body", async () => {
    const key = "c13/stream/idempotent";
    const firstBytes = new Uint8Array([1, 2, 3]);
    const otherBytes = new Uint8Array([4, 5, 6]);
    const firstDigest = await digestOf(firstBytes);
    const otherDigest = await digestOf(otherBytes);
    const created = await putStream(key, firstBytes, firstDigest);
    expect(created.outcome).toBe("created");
    expect(created.producer.status).toBe("fulfilled");
    const replay = await putStream(key, firstBytes, firstDigest);
    expect(replay.outcome).toBe("identical");
    const conflict = await putStream(key, otherBytes, otherDigest);
    expect(conflict.outcome).toBe("conflict");
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(key);
    expect(stored).not.toBeNull();
    expect(stored!.size).toBe(firstBytes.byteLength);
    expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(firstBytes);
    expect(stored!.customMetadata?.sha256).toBe(firstDigest);
    expect(stored!.customMetadata?.immutable).toBe("true");
  });

  it("lets only one concurrent create-only writer commit", async () => {
    const key = "c13/stream/race";
    const left = new Uint8Array([10, 11, 12]);
    const right = new Uint8Array([20, 21, 22]);
    const leftDigest = await digestOf(left);
    const rightDigest = await digestOf(right);
    const leftStarted = startFixedLength(left, "complete");
    const rightStarted = startFixedLength(right, "complete");
    const [leftOutcome, rightOutcome] = await Promise.all([
      putStreamCreateOnly(runtimeEnv.STRUCTURED_BUCKET, key, leftStarted.readable, {
        digest: leftDigest,
        contentType: JSON_TYPE,
        size: left.byteLength,
      }),
      putStreamCreateOnly(runtimeEnv.STRUCTURED_BUCKET, key, rightStarted.readable, {
        digest: rightDigest,
        contentType: JSON_TYPE,
        size: right.byteLength,
      }),
    ]);
    await abortUnread(leftStarted, leftOutcome);
    await abortUnread(rightStarted, rightOutcome);
    await Promise.all([leftStarted.producer, rightStarted.producer]);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(key);
    expect(stored).not.toBeNull();
    const body = new Uint8Array(await stored!.arrayBuffer());
    if (leftOutcome === "created") {
      expect(rightOutcome).toBe("conflict");
      expect(stored!.size).toBe(left.byteLength);
      expect(body).toEqual(left);
    } else {
      expect(leftOutcome).toBe("conflict");
      expect(rightOutcome).toBe("created");
      expect(stored!.size).toBe(right.byteLength);
      expect(body).toEqual(right);
    }
  });

  it("does not commit an aborted FixedLengthStream and retries a full stream", async () => {
    const key = "c13/stream/abort";
    const bytes = new Uint8Array([1, 2, 3]);
    const digest = await digestOf(bytes);
    const aborted = await putStream(key, bytes, digest, "abort");
    expect(aborted.outcome).toBe("checksum_rejected");
    expect(await runtimeEnv.STRUCTURED_BUCKET.head(key)).toBeNull();
    const retried = await putStream(key, bytes, digest);
    expect(retried.outcome).toBe("created");
    expect(retried.producer.status).toBe("fulfilled");
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(key);
    expect(stored).not.toBeNull();
    expect(stored!.size).toBe(bytes.byteLength);
    expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(bytes);
  });
});
