import { describe, expect, it } from "vitest";
import {
  writeJsonlToR2,
  type StructuredRecordLine,
} from "./r2_structured_writer";
import { sha256HexFromString } from "./sha256";

function memoryBucket(): {
  bucket: R2Bucket;
  puts: {
    key: string;
    body: string;
    metadata?: Record<string, string>;
    etag: string;
  }[];
} {
  const puts: {
    key: string;
    body: string;
    metadata?: Record<string, string>;
    etag: string;
  }[] = [];
  const objects = new Map<string, string>();
  const bucket = {
    async put(
      key: string,
      value: unknown,
      options?: { customMetadata?: Record<string, string> },
    ) {
      const body = typeof value === "string" ? value : "";
      const etag = `mem-${puts.length + 1}`;
      objects.set(key, body);
      puts.push({ key, body, metadata: options?.customMetadata, etag });
      return { key, etag, version: etag };
    },
  } as unknown as R2Bucket;
  return { bucket, puts };
}

function record(
  overrides: Partial<StructuredRecordLine> = {},
): StructuredRecordLine {
  return {
    naturalKey: '{"Code":"8697","Date":"2025-04-01"}',
    eventTime: "2025-04-01T15:30:00+09:00",
    availableAt: "2025-04-01T15:30:00+09:00",
    ingestedAt: "2025-04-02T09:00:00+09:00",
    payload: { Code: "8697", Date: "2025-04-01", Close: 100 },
    rawPayload: { Code: "8697", Date: "2025-04-01", Close: 100 },
    source: "jquants",
    dataset: "equities_bars_daily",
    ...overrides,
  };
}

describe("writeJsonlToR2", () => {
  it("writes JSONL with natural_key / dataset / payload, returns body sha256, and count matches records", async () => {
    const { bucket, puts } = memoryBucket();
    const records = [
      record(),
      record({
        naturalKey: '{"Code":"7203","Date":"2025-04-01"}',
        payload: { Code: "7203", Date: "2025-04-01", Close: 200 },
        rawPayload: { Code: "7203", Date: "2025-04-01", Close: 200 },
      }),
    ];
    const result = await writeJsonlToR2(
      bucket,
      "equities_bars_daily",
      "r2-equities_bars_daily-test",
      records,
      { runDate: "2025-04-01" },
    );

    expect(puts).toHaveLength(1);
    const put = puts[0]!;
    const jsonlLines = put.body.split("\n").filter((row) => row.length > 0);
    expect(jsonlLines).toHaveLength(records.length);
    expect(result.count).toBe(records.length);

    const parsed = jsonlLines.map((row) => JSON.parse(row) as Record<string, unknown>);
    for (const obj of parsed) {
      expect(obj).toHaveProperty("natural_key");
      expect(obj).toHaveProperty("dataset");
      expect(obj).toHaveProperty("payload");
      expect(obj).not.toHaveProperty("COMPLETE");
      expect(obj).not.toHaveProperty("complete");
      expect(obj).not.toHaveProperty("completeness");
    }
    expect(parsed[0]!.natural_key).toBe(records[0]!.naturalKey);
    expect(parsed[0]!.dataset).toBe("equities_bars_daily");
    expect(parsed[0]!.payload).toEqual(records[0]!.payload);
    expect(parsed[1]!.natural_key).toBe(records[1]!.naturalKey);
    expect(parsed[1]!.payload).toEqual(records[1]!.payload);
    expect(JSON.stringify(parsed)).not.toContain("COMPLETE");
    expect(JSON.stringify(put.metadata)).not.toContain("COMPLETE");
    expect(JSON.stringify(result)).not.toContain("COMPLETE");

    const expectedSha = await sha256HexFromString(put.body);
    expect(result.sha256).toBe(expectedSha);
    expect(put.metadata?.sha256).toBe(expectedSha);
    expect(put.metadata?.count).toBe(String(records.length));
    expect(result.bytes).toBe(new TextEncoder().encode(put.body).byteLength);
    expect(result.key).toBe(put.key);
    expect(put.key).toBe(
      "structured/jsonl/equities_bars_daily/dt=2025-04-01/r2-equities_bars_daily-test.jsonl",
    );
  });

  it("empty records still put empty body with count 0; does not invent extra writes", async () => {
    const { bucket, puts } = memoryBucket();
    const result = await writeJsonlToR2(
      bucket,
      "equities_bars_daily",
      "r2-empty-run",
      [],
      { runDate: "2025-04-01" },
    );

    expect(puts).toHaveLength(1);
    expect(puts[0]!.body).toBe("");
    expect(result.count).toBe(0);
    expect(result.sha256).toBe(await sha256HexFromString(""));
    expect(result.bytes).toBe(0);
    expect(puts[0]!.metadata?.count).toBe("0");
    expect(puts[0]!.metadata?.sha256).toBe(result.sha256);
    expect(JSON.stringify(puts[0]!.metadata)).not.toContain("COMPLETE");
    expect(JSON.stringify(result)).not.toContain("COMPLETE");
    expect(puts[0]!.key).toBe(
      "structured/jsonl/equities_bars_daily/dt=2025-04-01/r2-empty-run.jsonl",
    );
  });
});
