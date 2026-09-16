import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  EXACT_FIVE_ACQUISITION_KEY,
  runExactFiveAcquisitionTick,
  type ExactFiveIngest,
} from "./exact_five_acquisition_tick";

class MemoryObject {
  constructor(
    readonly body: string,
    readonly etag: string,
  ) {}
  get size(): number {
    return new TextEncoder().encode(this.body).byteLength;
  }
  async text(): Promise<string> {
    return this.body;
  }
}

class MemoryBucket {
  private objects = new Map<string, MemoryObject>();

  async get(key: string): Promise<MemoryObject | null> {
    return this.objects.get(key) ?? null;
  }

  async put(
    key: string,
    value: string,
    options?: { onlyIf?: { etagMatches?: string } },
  ): Promise<MemoryObject | null> {
    const current = this.objects.get(key);
    const expected = options?.onlyIf?.etagMatches;
    if (expected !== undefined && current?.etag !== expected) return null;
    const etag = createHash("sha256").update(value).digest("hex");
    const stored = new MemoryObject(value, etag);
    this.objects.set(key, stored);
    return stored;
  }
}

function jobsDoc(overrides: Record<string, unknown> = {}) {
  return {
    schema: "exact-five-compiled-acquisition/v1",
    jobs: [
      {
        dataset: "markets_calendar",
        from: "2023-01-04",
        to: "2023-01-04",
      },
    ],
    cursor: 0,
    attempts: 0,
    lease: null,
    last: null,
    ...overrides,
  };
}

describe("exact-five compiled acquisition control tick", () => {
  it("absent control does not ingest", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    const ingest: ExactFiveIngest = async () => {
      calls += 1;
      return { status: "pass", datasetCount: 1, rowsInserted: 1 };
    };
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "idle",
      fetched: false,
      jobs: 0,
      reason: "absent",
    });
    expect(calls).toBe(0);
  });

  it("invalid dataset or oversized window has no ingest side effects", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    const ingest: ExactFiveIngest = async () => {
      calls += 1;
      return { status: "pass", datasetCount: 1, rowsInserted: 1 };
    };
    await (bucket as unknown as MemoryBucket).put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(jobsDoc({
        jobs: [{ dataset: "equities_valuation", from: "2023-01-04", to: "2023-01-04" }],
      })),
    );
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "stop",
      fetched: false,
      jobs: 0,
      reason: "invalid",
    });
    await (bucket as unknown as MemoryBucket).put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(jobsDoc({
        jobs: [{ dataset: "markets_calendar", from: "2023-01-01", to: "2023-03-01" }],
      })),
    );
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "stop",
      fetched: false,
      jobs: 0,
      reason: "invalid",
    });
    expect(calls).toBe(0);
  });

  it("dispatches one job, resumes the cursor, and does not claim COMPLETE", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    const seen: Array<{ dataset: string; from: string; to: string }> = [];
    const ingest: ExactFiveIngest = async (opts) => {
      seen.push(opts);
      return { status: "pass", datasetCount: 1, rowsInserted: 4 };
    };
    await (bucket as unknown as MemoryBucket).put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(jobsDoc({
        jobs: [
          { dataset: "markets_calendar", from: "2023-01-04", to: "2023-01-04" },
          { dataset: "equities_master", from: "2023-01-04", to: "2023-01-05" },
        ],
      })),
    );
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "pass",
      fetched: true,
      jobs: 1,
      reason: "ok",
    });
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "pass",
      fetched: true,
      jobs: 1,
      reason: "ok",
    });
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "idle",
      fetched: false,
      jobs: 0,
      reason: "complete",
    });
    expect(seen).toEqual([
      { dataset: "markets_calendar", from: "2023-01-04", to: "2023-01-04" },
      { dataset: "equities_master", from: "2023-01-04", to: "2023-01-05" },
    ]);
    const stored = JSON.parse(
      await (await bucket.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    );
    expect(stored.cursor).toBe(2);
    expect(stored.last.status).toBe("pass");
    expect(JSON.stringify(stored)).not.toMatch(/COMPLETE/);
  });

  it("retries a failed job then stops at the attempt bound", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    const ingest: ExactFiveIngest = async () => {
      calls += 1;
      throw new Error("forced crash");
    };
    await (bucket as unknown as MemoryBucket).put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(jobsDoc()),
    );
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toMatchObject({
      status: "fail",
      reason: "ingestion_failed",
    });
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toMatchObject({
      status: "fail",
      reason: "ingestion_failed",
    });
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toMatchObject({
      status: "fail",
      reason: "ingestion_failed",
    });
    expect(await runExactFiveAcquisitionTick(bucket, ingest)).toEqual({
      status: "stop",
      fetched: false,
      jobs: 0,
      reason: "exhausted",
    });
    expect(calls).toBe(3);
  });
});
