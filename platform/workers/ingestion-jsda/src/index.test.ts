import { afterEach, describe, expect, it } from "vitest";
import worker from "./index";

const RUN_TOKEN = "jsda-test-run-token-do-not-leak";

function touchingEnv(
  token: string | undefined = RUN_TOKEN,
): {
  env: {
    RAW_BUCKET: never;
    DB: never;
    INGESTION_RUN_TOKEN?: string;
  };
  sql: string[];
  r2Ops: string[];
} {
  const sql: string[] = [];
  const r2Ops: string[] = [];
  return {
    env: {
      RAW_BUCKET: {
        put: async () => {
          r2Ops.push("put");
          throw new Error("unexpected R2 write");
        },
      } as never,
      DB: {
        prepare: (query: string) => {
          sql.push(query);
          throw new Error(`unexpected D1: ${query}`);
        },
      } as never,
      INGESTION_RUN_TOKEN: token,
    },
    sql,
    r2Ops,
  };
}

describe("ingestion-jsda HTTP boundary", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function rejectOutboundFetch(): { count: () => number } {
    let count = 0;
    globalThis.fetch = (async () => {
      count += 1;
      throw new Error("HTTP boundary test must not acquire JSDA data");
    }) as typeof fetch;
    return { count: () => count };
  }

  it("exposes fetch, cron, and Queue handlers", () => {
    expect(typeof worker.fetch).toBe("function");
    expect(typeof worker.scheduled).toBe("function");
    expect(typeof worker.queue).toBe("function");
  });

  it("health reports liveness without misclaiming product readiness", async () => {
    const { env } = touchingEnv();
    const response = await worker.fetch(
      new Request("https://ingestion-jsda.test/health"),
      env,
    );
    expect(response.status).toBe(200);
    const body = await response.text();
    expect(body).not.toContain(RUN_TOKEN);
    expect(body).not.toContain("COMPLETE");
    expect(JSON.parse(body)).toMatchObject({
      ok: true,
      liveness: true,
      product_ready: false,
      cutover: "UNKNOWN",
      worker: "ingestion-jsda",
      queue_contract: "jsda-acquisition-job/v2",
      hierarchy: ["discover_root", "discover_year", "fetch_file"],
    });
  });

  it("rejects a formally valid hand-written v3_active self-claim", async () => {
    const r2Ops: string[] = [];
    const env = {
      RAW_BUCKET: {
        put: async () => {
          r2Ops.push("put");
        },
      } as never,
      DB: {
        prepare: () => ({
          first: async () => ({
            phase: "v3_active",
            activated_at: "2026-08-27T00:00:00Z",
            activated_source_sha: "a".repeat(40),
            drain_evidence_digest: `sha256:${"b".repeat(64)}`,
          }),
        }),
      } as never,
      INGESTION_RUN_TOKEN: RUN_TOKEN,
    };
    const ready = await worker.fetch(
      new Request("https://ingestion-jsda.test/health/ready"),
      env,
    );
    expect(ready.status).toBe(503);
    await expect(ready.json()).resolves.toMatchObject({
      ok: false,
      product_ready: false,
      cutover: "AUTHORITY_DISABLED",
    });
    const run = await worker.fetch(
      new Request("https://ingestion-jsda.test/v1/run", {
        method: "POST",
        headers: { "X-Ingestion-Token": RUN_TOKEN },
      }),
      env,
    );
    expect(run.status).toBe(503);
    expect(r2Ops).toEqual([]);
  });

  it("fails closed before D1, R2, Queue, or outbound fetch on bad methods and auth", async () => {
    const outbound = rejectOutboundFetch();
    const cases = [
      {
        request: new Request("https://ingestion-jsda.test/health", {
          method: "POST",
        }),
        status: 405,
      },
      {
        request: new Request("https://ingestion-jsda.test/health/ready", {
          method: "POST",
        }),
        status: 405,
      },
      {
        request: new Request("https://ingestion-jsda.test/v1/run", {
          method: "GET",
          headers: { "X-Ingestion-Token": RUN_TOKEN },
        }),
        status: 405,
      },
      {
        request: new Request("https://ingestion-jsda.test/v1/run", {
          method: "POST",
        }),
        status: 401,
      },
      {
        request: new Request(
          `https://ingestion-jsda.test/v1/run?token=${encodeURIComponent(RUN_TOKEN)}`,
          { method: "POST" },
        ),
        status: 401,
      },
    ];
    for (const testCase of cases) {
      const { env, sql, r2Ops } = touchingEnv();
      const response = await worker.fetch(testCase.request, env);
      expect(response.status).toBe(testCase.status);
      expect(await response.text()).not.toContain(RUN_TOKEN);
      expect(sql).toEqual([]);
      expect(r2Ops).toEqual([]);
    }
    expect(outbound.count()).toBe(0);
  });

  it("rejects a non-closed dataset before persistence or acquisition", async () => {
    const outbound = rejectOutboundFetch();
    const { env, sql, r2Ops } = touchingEnv();
    const response = await worker.fetch(
      new Request(
        "https://ingestion-jsda.test/v1/run?dataset=https%3A%2F%2Fevil.test%2Fpayload",
        {
          method: "POST",
          headers: { "X-Ingestion-Token": RUN_TOKEN },
        },
      ),
      env,
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "invalid dataset" });
    expect(sql).toEqual([]);
    expect(r2Ops).toEqual([]);
    expect(outbound.count()).toBe(0);
  });
});
