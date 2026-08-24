import { afterEach, describe, expect, it } from "vitest";
import {
  discoveryCapSemantics,
  discoveryIsCoverageEligible,
  parseDataFileCap,
  parseYearPageCap,
} from "./discovery_caps";
import worker from "./index";

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

describe("POST /v1/run records cap-hit as not exhausted", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function acquiringEnv(): {
    env: {
      RAW_BUCKET: never;
      DB: never;
      INGESTION_RUN_TOKEN: string;
      MAX_YEAR_PAGES: string;
      MAX_DATA_FILES: string;
    };
  } {
    const stmt = {
      bind: (..._args: unknown[]) => stmt,
      run: async () => ({ success: true }),
      all: async () => ({ results: [] }),
    };
    return {
      env: {
        INGESTION_RUN_TOKEN: RUN_TOKEN,
        MAX_YEAR_PAGES: "1",
        MAX_DATA_FILES: "3",
        RAW_BUCKET: {
          head: async () => null,
          put: async () => ({}),
        } as never,
        DB: {
          prepare: () => stmt,
        } as never,
      },
    };
  }

  it("job/run success with MAX_YEAR_PAGES=1 and MAX_DATA_FILES=3 records pagination_exhausted=false", async () => {
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
    const res = await worker.fetch(
      new Request(
        "https://ingestion-jsda.test/v1/run?dataset=jsda_otc_bond_reference_prices",
        { method: "POST", headers: { "X-Ingestion-Token": RUN_TOKEN } },
      ),
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.text();
    assertNoLeakOrCoverage(body);
    const payload = JSON.parse(body) as {
      ok?: boolean;
      summary?: {
        status?: string;
        pagination_exhausted?: boolean;
        results?: Array<{
          pagination_exhausted?: boolean;
          year_page_cap_hit?: boolean;
          data_file_cap_hit?: boolean;
          status?: string;
        }>;
      };
    };
    expect(payload.ok).not.toBe(true);
    expect(payload.summary?.pagination_exhausted).toBe(false);
    expect(payload.summary?.status).toBe("partial");
    const otc = payload.summary?.results?.[0];
    expect(otc?.pagination_exhausted).toBe(false);
    expect(otc?.year_page_cap_hit).toBe(true);
    expect(otc?.data_file_cap_hit).toBe(true);
    expect(otc?.status).toBe("partial");
    expect(fetched.some((u) => /archive2024\.html/i.test(u))).toBe(true);
    expect(fetched.some((u) => /archive2023\.html/i.test(u))).toBe(false);
    expect(fetched.filter((u) => u.endsWith(".csv")).length).toBe(3);
  });
});
