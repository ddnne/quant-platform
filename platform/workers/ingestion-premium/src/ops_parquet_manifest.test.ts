import { describe, expect, it } from "vitest";
import {
  handleParquetManifest,
  type ParquetManifestEnv,
} from "./ops_parquet_manifest";

const RUN_TOKEN = "premium-test-run-token-do-not-leak";

function touchingBucket(): { bucket: R2Bucket; r2Ops: string[] } {
  const r2Ops: string[] = [];
  const bucket = {
    async list() {
      r2Ops.push("list");
      throw new Error("unexpected R2 list");
    },
    async put() {
      r2Ops.push("put");
      throw new Error("unexpected R2 put");
    },
  } as unknown as R2Bucket;
  return { bucket, r2Ops };
}

function manifestRequest(headers: HeadersInit = {}): Request {
  return new Request(
    "https://ingestion-premium.test/v1/ops/jsonl-to-parquet-meta",
    { method: "POST", headers },
  );
}

function assertUnauthorized(body: string): void {
  expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toContain("READY");
}

async function postManifest(
  envToken: string | undefined,
  headers: HeadersInit = {},
): Promise<{ status: number; body: string; r2Ops: string[] }> {
  const { bucket, r2Ops } = touchingBucket();
  const env: ParquetManifestEnv = {
    STRUCTURED_BUCKET: bucket,
    INGESTION_RUN_TOKEN: envToken,
  };
  const res = await handleParquetManifest(manifestRequest(headers), env);
  return { status: res.status, body: await res.text(), r2Ops };
}

describe("handleParquetManifest auth", () => {
  it("missing INGESTION_RUN_TOKEN is 401 and does not list or put", async () => {
    const { status, body, r2Ops } = await postManifest(RUN_TOKEN);
    expect(status).toBe(401);
    assertUnauthorized(body);
    expect(r2Ops).toEqual([]);
  });

  it("wrong INGESTION_RUN_TOKEN is 401 and does not list or put", async () => {
    const { status, body, r2Ops } = await postManifest(RUN_TOKEN, {
      "X-Ingestion-Token": "wrong-token",
    });
    expect(status).toBe(401);
    assertUnauthorized(body);
    expect(r2Ops).toEqual([]);
  });

  it("unbound INGESTION_RUN_TOKEN is 401 even when a header is sent and does not list or put", async () => {
    const { status, body, r2Ops } = await postManifest(undefined, {
      "X-Ingestion-Token": RUN_TOKEN,
    });
    expect(status).toBe(401);
    assertUnauthorized(body);
    expect(r2Ops).toEqual([]);
  });

  it("POST with only matching query token and no header is 401 and does not list or put", async () => {
    const { bucket, r2Ops } = touchingBucket();
    const env: ParquetManifestEnv = {
      STRUCTURED_BUCKET: bucket,
      INGESTION_RUN_TOKEN: RUN_TOKEN,
    };
    const res = await handleParquetManifest(
      new Request(
        `https://ingestion-premium.test/v1/ops/jsonl-to-parquet-meta?token=${encodeURIComponent(RUN_TOKEN)}`,
        { method: "POST" },
      ),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    assertUnauthorized(body);
    expect(r2Ops).toEqual([]);
  });
});

describe("handleParquetManifest method", () => {
  it("GET with matching token is 405 and does not list or put", async () => {
    const matching: Request[] = [
      new Request(
        "https://ingestion-premium.test/v1/ops/jsonl-to-parquet-meta",
        {
          method: "GET",
          headers: { "X-Ingestion-Token": RUN_TOKEN },
        },
      ),
      new Request(
        `https://ingestion-premium.test/v1/ops/jsonl-to-parquet-meta?token=${encodeURIComponent(RUN_TOKEN)}`,
        { method: "GET" },
      ),
    ];
    for (const request of matching) {
      const { bucket, r2Ops } = touchingBucket();
      const env: ParquetManifestEnv = {
        STRUCTURED_BUCKET: bucket,
        INGESTION_RUN_TOKEN: RUN_TOKEN,
      };
      const res = await handleParquetManifest(request, env);
      expect(res.status).toBe(405);
      const body = await res.text();
      expect(JSON.parse(body)).toEqual({ error: "POST required" });
      expect(body).not.toContain(RUN_TOKEN);
      expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
      expect(body).not.toContain("COMPLETE");
      expect(body).not.toContain("READY");
      expect(r2Ops).toEqual([]);
    }
  });
});
