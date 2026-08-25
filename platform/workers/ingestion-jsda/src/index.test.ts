import { afterEach, describe, expect, it, vi } from "vitest";
import {
  discoveryCapSemantics,
  discoveryIsCoverageEligible,
  parseDataFileCap,
  parseYearPageCap,
} from "./discovery_caps";
import worker, { type JsdaDatasetJob } from "./index";

const RUN_TOKEN = "jsda-test-run-token-do-not-leak";

function testEnv(): {
  RAW_BUCKET: never;
  DB: never;
  INGESTION_RUN_TOKEN: string;
} {
  return {
    RAW_BUCKET: {} as never,
    DB: {} as never,
    INGESTION_RUN_TOKEN: RUN_TOKEN,
  };
}

function touchingEnv(
  overrides: { INGESTION_RUN_TOKEN?: string } = { INGESTION_RUN_TOKEN: RUN_TOKEN },
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
        head: async () => {
          r2Ops.push("head");
          throw new Error("unexpected R2 head");
        },
        put: async () => {
          r2Ops.push("put");
          throw new Error("unexpected R2 put");
        },
      } as never,
      DB: {
        prepare: (query: string) => {
          sql.push(query);
          throw new Error(`unexpected D1: ${query}`);
        },
      } as never,
      ...overrides,
    },
    sql,
    r2Ops,
  };
}

function postRun(headers: HeadersInit = {}): Request {
  return new Request("https://ingestion-jsda.test/v1/run", {
    method: "POST",
    headers,
  });
}

function assertNoLeakOrCoverage(body: string): void {
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toContain("READY");
}

describe("ingestion-jsda handlers", () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    fetchCalls = 0;
  });

  function rejectLiveFetch(): void {
    fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls += 1;
      throw new Error("live JSDA HTML must not be fetched in unit tests");
    }) as typeof fetch;
  }

  it("exposes health fetch and scheduled cron handlers", () => {
    expect(typeof worker.fetch).toBe("function");
    expect(typeof worker.scheduled).toBe("function");
    expect(typeof worker.queue).toBe("function");
  });

  it("health and unauthorized run do not leak the run token", async () => {
    const env = testEnv();
    const health = await worker.fetch(
      new Request("https://ingestion-jsda.test/health"),
      env,
    );
    expect(health.status).toBe(200);
    const healthBody = await health.text();
    expect(healthBody).not.toContain(RUN_TOKEN);
    expect(healthBody).not.toContain("COMPLETE");
    const healthJson = JSON.parse(healthBody) as { ok?: boolean; worker?: string };
    expect(healthJson.ok).toBe(true);
    expect(healthJson.worker).toBe("ingestion-jsda");

    const run = await worker.fetch(postRun(), env);
    expect(run.status).toBe(401);
    const runBody = await run.text();
    expect(runBody).not.toContain(RUN_TOKEN);
    expect(runBody).not.toMatch(/INGESTION_RUN_TOKEN/i);
    expect(runBody).not.toContain("COMPLETE");
  });

  it("GET /v1/run with matching or missing token is 405 and does not fetch or persist", async () => {
    rejectLiveFetch();

    const matching = touchingEnv();
    const matchingRes = await worker.fetch(
      new Request("https://ingestion-jsda.test/v1/run", {
        method: "GET",
        headers: { "X-Ingestion-Token": RUN_TOKEN },
      }),
      matching.env,
    );
    expect(matchingRes.status).toBe(405);
    const matchingBody = await matchingRes.text();
    expect(JSON.parse(matchingBody)).toEqual({ error: "POST required" });
    assertNoLeakOrCoverage(matchingBody);
    expect(matching.sql).toEqual([]);
    expect(matching.r2Ops).toEqual([]);

    const missing = touchingEnv();
    const missingRes = await worker.fetch(
      new Request("https://ingestion-jsda.test/v1/run", { method: "GET" }),
      missing.env,
    );
    expect(missingRes.status).toBe(405);
    const missingBody = await missingRes.text();
    expect(JSON.parse(missingBody)).toEqual({ error: "POST required" });
    assertNoLeakOrCoverage(missingBody);
    expect(missing.sql).toEqual([]);
    expect(missing.r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });

  it("POST /health is 405 GET required and does not leak the token or fetch JSDA", async () => {
    rejectLiveFetch();
    const { env, sql, r2Ops } = touchingEnv();
    const res = await worker.fetch(
      new Request("https://ingestion-jsda.test/health", {
        method: "POST",
        headers: { "X-Ingestion-Token": RUN_TOKEN },
      }),
      env,
    );
    expect(res.status).toBe(405);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "GET required" });
    assertNoLeakOrCoverage(body);
    expect(sql).toEqual([]);
    expect(r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });

  it("GET and POST /nope are 404 and do not fetch JSDA or persist", async () => {
    rejectLiveFetch();

    const getCase = touchingEnv();
    const getRes = await worker.fetch(
      new Request("https://ingestion-jsda.test/nope", { method: "GET" }),
      getCase.env,
    );
    expect(getRes.status).toBe(404);
    const getBody = await getRes.text();
    expect(JSON.parse(getBody)).toEqual({ error: "not found" });
    assertNoLeakOrCoverage(getBody);
    expect(getCase.sql).toEqual([]);
    expect(getCase.r2Ops).toEqual([]);

    const postCase = touchingEnv();
    const postRes = await worker.fetch(
      new Request("https://ingestion-jsda.test/nope", {
        method: "POST",
        headers: { "X-Ingestion-Token": RUN_TOKEN },
      }),
      postCase.env,
    );
    expect(postRes.status).toBe(404);
    const postBody = await postRes.text();
    expect(JSON.parse(postBody)).toEqual({ error: "not found" });
    assertNoLeakOrCoverage(postBody);
    expect(postCase.sql).toEqual([]);
    expect(postCase.r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });

  it("POST /v1/run missing or wrong token is 401 and does not fetch or persist", async () => {
    rejectLiveFetch();

    const missing = touchingEnv();
    const missingRes = await worker.fetch(postRun(), missing.env);
    expect(missingRes.status).toBe(401);
    const missingBody = await missingRes.text();
    expect(JSON.parse(missingBody)).toEqual({ error: "unauthorized" });
    assertNoLeakOrCoverage(missingBody);
    expect(missing.sql).toEqual([]);
    expect(missing.r2Ops).toEqual([]);

    const wrong = touchingEnv();
    const wrongRes = await worker.fetch(
      postRun({ "X-Ingestion-Token": "wrong-token" }),
      wrong.env,
    );
    expect(wrongRes.status).toBe(401);
    const wrongBody = await wrongRes.text();
    expect(JSON.parse(wrongBody)).toEqual({ error: "unauthorized" });
    assertNoLeakOrCoverage(wrongBody);
    expect(wrong.sql).toEqual([]);
    expect(wrong.r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });

  it("POST /v1/run with unbound INGESTION_RUN_TOKEN is 401 even when a header is sent", async () => {
    rejectLiveFetch();
    const { env, sql, r2Ops } = touchingEnv({});
    const res = await worker.fetch(
      postRun({ "X-Ingestion-Token": RUN_TOKEN }),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    assertNoLeakOrCoverage(body);
    expect(sql).toEqual([]);
    expect(r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });

  it("authorized manual run enqueues one closed typed dataset job without acquiring", async () => {
    rejectLiveFetch();
    const sent: Array<{ body: unknown; contentType?: string }> = [];
    const env = {
      ...testEnv(),
      JSDA_QUEUE: {
        sendBatch: async (messages: Iterable<{ body: unknown; contentType?: string }>) => {
          sent.push(...messages);
          return { metadata: { metrics: { backlogCount: 1, backlogBytes: 1 } } };
        },
      } as never,
    };
    const res = await worker.fetch(
      new Request(
        "https://ingestion-jsda.test/v1/run?dataset=jsda_tokyo_repo_rates",
        { method: "POST", headers: { "X-Ingestion-Token": RUN_TOKEN } },
      ),
      env,
    );

    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({
      accepted: true,
      mode: "cloudflare_queue",
      queued: 1,
      datasets: ["jsda_tokyo_repo_rates"],
    });
    expect(sent).toHaveLength(1);
    expect(sent[0].contentType).toBe("json");
    expect(Object.keys(sent[0].body as object).sort()).toEqual(
      ["dataset", "job_id", "requested_at", "requested_by", "version"].sort(),
    );
    expect(sent[0].body).toMatchObject({
      version: "jsda-dataset-job/v1",
      dataset: "jsda_tokyo_repo_rates",
      requested_by: "manual",
    });
    expect(JSON.stringify(sent[0].body)).not.toMatch(/url|payload/i);
    expect(fetchCalls).toBe(0);
  });

  it("scheduled producer enqueues all three closed datasets", async () => {
    rejectLiveFetch();
    const sent: Array<{ body: JsdaDatasetJob }> = [];
    const waits: Promise<unknown>[] = [];
    const env = {
      ...testEnv(),
      JSDA_QUEUE: {
        sendBatch: async (messages: Iterable<{ body: JsdaDatasetJob }>) => {
          sent.push(...messages);
          return { metadata: { metrics: { backlogCount: 3, backlogBytes: 3 } } };
        },
      } as never,
    };
    await worker.scheduled(
      {} as ScheduledController,
      env,
      { waitUntil: (promise: Promise<unknown>) => waits.push(promise) } as ExecutionContext,
    );
    await Promise.all(waits);

    expect(sent.map(({ body }) => body.dataset).sort()).toEqual(
      [
        "jsda_corporate_bond_transactions",
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
      ].sort(),
    );
    expect(sent.every(({ body }) => body.requested_by === "cron")).toBe(true);
    expect(sent.every(({ body }) => !Object.hasOwn(body, "url"))).toBe(true);
    expect(fetchCalls).toBe(0);
  });

  it("authorized manual run rejects a non-closed dataset without enqueueing", async () => {
    rejectLiveFetch();
    let sendCalls = 0;
    const env = {
      ...testEnv(),
      JSDA_QUEUE: {
        sendBatch: async () => {
          sendCalls += 1;
        },
      } as never,
    };
    const res = await worker.fetch(
      new Request(
        "https://ingestion-jsda.test/v1/run?dataset=https%3A%2F%2Fevil.test%2Fpayload",
        { method: "POST", headers: { "X-Ingestion-Token": RUN_TOKEN } },
      ),
      env,
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "invalid dataset" });
    expect(sendCalls).toBe(0);
    expect(fetchCalls).toBe(0);
  });
});

describe("JSDA rate/safety caps are not pagination exhaustion", () => {
  it("MAX_YEAR_PAGES defaults to 1 as a rate/safety cap, not unlimited", () => {
    expect(parseYearPageCap(undefined)).toBe(1);
    expect(parseYearPageCap("1")).toBe(1);
    expect(parseYearPageCap("0")).toBe(0);
    expect(parseDataFileCap(undefined)).toBe(0);
    expect(parseDataFileCap("3")).toBe(3);
  });

  it("cap-hit is not exhausted and is not coverage-eligible", () => {
    const yearCap = discoveryCapSemantics({
      yearPagesFound: 12,
      maxYearPages: 1,
      dataFilesDiscovered: 3,
      dataFilesStored: 3,
      maxDataFiles: 3,
      fetchErrors: 0,
    });
    expect(yearCap.year_page_cap_hit).toBe(true);
    expect(yearCap.pagination_exhausted).toBe(false);
    expect(yearCap.status).toBe("partial");
    expect(discoveryIsCoverageEligible(yearCap)).toBe(false);

    const fileCap = discoveryCapSemantics({
      yearPagesFound: 1,
      maxYearPages: 1,
      dataFilesDiscovered: 40,
      dataFilesStored: 3,
      maxDataFiles: 3,
      fetchErrors: 0,
    });
    expect(fileCap.data_file_cap_hit).toBe(true);
    expect(fileCap.pagination_exhausted).toBe(false);
    expect(fileCap.status).toBe("partial");
    expect(discoveryIsCoverageEligible(fileCap)).toBe(false);
  });

  it("uncapped full fetch may exhaust; cap-truncated discovery never does", () => {
    const exhausted = discoveryCapSemantics({
      yearPagesFound: 1,
      maxYearPages: 1,
      dataFilesDiscovered: 2,
      dataFilesStored: 2,
      maxDataFiles: 0,
      fetchErrors: 0,
    });
    expect(exhausted.year_page_cap_hit).toBe(false);
    expect(exhausted.data_file_cap_hit).toBe(false);
    expect(exhausted.pagination_exhausted).toBe(true);
    expect(exhausted.status).toBe("pass");
    expect(discoveryIsCoverageEligible(exhausted)).toBe(true);

    const wranglerCaps = discoveryCapSemantics({
      yearPagesFound: 20,
      maxYearPages: parseYearPageCap("1"),
      dataFilesDiscovered: 3,
      dataFilesStored: 3,
      maxDataFiles: parseDataFileCap("3"),
      fetchErrors: 0,
    });
    expect(wranglerCaps.pagination_exhausted).toBe(false);
    expect(discoveryIsCoverageEligible(wranglerCaps)).toBe(false);
  });
});

describe("JSDA Queue consumer", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function acquiringEnv(caps: {
    years: string;
    files: string;
  } = { years: "1", files: "3" }): {
    env: {
      RAW_BUCKET: never;
      DB: never;
      INGESTION_RUN_TOKEN: string;
      MAX_YEAR_PAGES: string;
      MAX_DATA_FILES: string;
    };
    bindings: unknown[][];
  } {
    const bindings: unknown[][] = [];
    const stmt = {
      bind: (...args: unknown[]) => {
        bindings.push(args);
        return stmt;
      },
      run: async () => ({ success: true }),
      all: async () => ({ results: [] }),
    };
    return {
      env: {
        INGESTION_RUN_TOKEN: RUN_TOKEN,
        MAX_YEAR_PAGES: caps.years,
        MAX_DATA_FILES: caps.files,
        RAW_BUCKET: {
          head: async () => null,
          put: async () => ({}),
        } as never,
        DB: {
          prepare: () => stmt,
        } as never,
      },
      bindings,
    };
  }

  function job(
    overrides: Partial<JsdaDatasetJob> = {},
  ): JsdaDatasetJob {
    return {
      version: "jsda-dataset-job/v1",
      dataset: "jsda_otc_bond_reference_prices",
      requested_by: "manual",
      requested_at: "2026-08-24T00:00:00.000Z",
      job_id: "jsda:test:otc:2026-08-24",
      ...overrides,
    };
  }

  function queueDelivery(body: unknown): {
    batch: MessageBatch<unknown>;
    acked: () => number;
    retried: () => number;
  } {
    let ackCount = 0;
    let retryCount = 0;
    const message = {
      id: "queue-message-1",
      timestamp: new Date("2026-08-24T00:00:01.000Z"),
      body,
      attempts: 1,
      ack: () => {
        ackCount += 1;
      },
      retry: () => {
        retryCount += 1;
      },
    } as Message<unknown>;
    return {
      batch: {
        messages: [message],
        queue: "quant-jsda-ingestion",
        metadata: {
          metrics: { backlogCount: 1, backlogBytes: 1 },
        },
        ackAll: () => undefined,
        retryAll: () => undefined,
      },
      acked: () => ackCount,
      retried: () => retryCount,
    };
  }

  it("retries a cap-truncated partial result instead of acknowledging it", async () => {
    const fetched: string[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      fetched.push(url);
      const path = new URL(url).pathname;
      if (path.endsWith("/index.html")) {
        return new Response(
          [
            '<a href="archive2024.html">2024</a>',
            '<a href="archive2023.html">2023</a>',
            '<a href="archive2022.html">2022</a>',
          ].join("\n"),
          { status: 200, headers: { "content-type": "text/html" } },
        );
      }
      if (/archive2024\.html$/i.test(path)) {
        return new Response(
          [
            '<a href="data/otc202401.csv">jan</a>',
            '<a href="data/otc202402.csv">feb</a>',
            '<a href="data/otc202403.csv">mar</a>',
            '<a href="data/otc202404.csv">apr</a>',
          ].join("\n"),
          { status: 200, headers: { "content-type": "text/html" } },
        );
      }
      if (path.endsWith(".csv")) {
        return new Response("isin,price\nJP000,100\n", {
          status: 200,
          headers: { "content-type": "text/csv" },
        });
      }
      return new Response("not used", { status: 404 });
    }) as typeof fetch;

    const { env } = acquiringEnv();
    const delivery = queueDelivery(job());
    await worker.queue(delivery.batch, env);

    expect(delivery.acked()).toBe(0);
    expect(delivery.retried()).toBe(1);
    expect(fetched.some((u) => /archive2024\.html/i.test(u))).toBe(true);
    expect(fetched.some((u) => /archive2023\.html/i.test(u))).toBe(false);
    expect(fetched.filter((u) => u.endsWith(".csv")).length).toBe(3);
  });

  it("acknowledges only an exhausted result with at least one stored data file", async () => {
    const fetched: string[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      fetched.push(url);
      if (new URL(url).pathname.endsWith("/index.html")) {
        return new Response('<a href="data/otc-current.csv">current</a>', {
          status: 200,
          headers: { "content-type": "text/html" },
        });
      }
      return new Response("isin,price\nJP000,100\n", {
        status: 200,
        headers: { "content-type": "text/csv" },
      });
    }) as typeof fetch;

    const { env } = acquiringEnv({ years: "0", files: "0" });
    const delivery = queueDelivery(job());
    await worker.queue(delivery.batch, env);

    expect(delivery.acked()).toBe(1);
    expect(delivery.retried()).toBe(0);
    expect(fetched).toHaveLength(2);
  });

  it("retries zero-row discovery and never marks it as a pass", async () => {
    globalThis.fetch = (async () =>
      new Response("<html>no data links</html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      })) as typeof fetch;

    const { env, bindings } = acquiringEnv({ years: "0", files: "0" });
    const delivery = queueDelivery(job());
    await worker.queue(delivery.batch, env);

    expect(delivery.acked()).toBe(0);
    expect(delivery.retried()).toBe(1);
    expect(JSON.stringify(bindings)).not.toContain('"pass"');
  });

  it("acks an invalid message with a URL field without fetching or persisting", async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls += 1;
      throw new Error("invalid message must not fetch");
    }) as typeof fetch;
    const { env, sql, r2Ops } = touchingEnv();
    const delivery = queueDelivery({
      ...job(),
      url: "https://evil.test/arbitrary.csv",
    });
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await worker.queue(delivery.batch, env);
    errorLog.mockRestore();

    expect(delivery.acked()).toBe(1);
    expect(delivery.retried()).toBe(0);
    expect(fetchCalls).toBe(0);
    expect(sql).toEqual([]);
    expect(r2Ops).toEqual([]);
  });
});
