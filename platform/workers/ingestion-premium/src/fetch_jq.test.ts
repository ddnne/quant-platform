import { afterEach, describe, expect, it, vi } from "vitest";
import { datasetById } from "./catalog";
import { fetchDataset, fetchOnePage, requestQueries } from "./fetch_jq";
import { pickAvailableAt } from "./identity";
import { RateLimiter } from "./rate_limit";

const API_KEY = "premium-test-jquants-key-do-not-leak";

function limiter(): RateLimiter {
  return new RateLimiter(0);
}

describe("fetchOnePage retry", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("does not retry a 200", async () => {
    let calls = 0;
    const keys: unknown[] = [];
    const fetchImpl = (async (_url, init) => {
      calls += 1;
      keys.push((init?.headers as Record<string, string> | undefined)?.["x-api-key"]);
      return new Response(JSON.stringify({ data: [] }), { status: 200 });
    }) as typeof fetch;
    const rl = limiter();
    const page = await fetchOnePage(
      { JQUANTS_API_KEY: API_KEY },
      "https://api.jquants.com/v2/markets/calendar",
      fetchImpl,
      rl,
    );
    expect(calls).toBe(1);
    expect(page.status).toBe(200);
    expect(page.error).toBe("");
    expect(page.retriesUsed).toBe(0);
    expect(rl.rateLimitHitCount).toBe(0);
    expect(keys).toEqual([API_KEY]);
  });

  it("retries 429 then succeeds", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const fetchImpl = (async () => {
      calls += 1;
      if (calls === 1) return new Response("slow down", { status: 429 });
      return new Response(JSON.stringify({ data: [] }), { status: 200 });
    }) as typeof fetch;
    const rl = limiter();
    const pending = fetchOnePage(
      { JQUANTS_API_KEY: API_KEY },
      "https://api.jquants.com/v2/markets/calendar",
      fetchImpl,
      rl,
    );
    const page = await vi.runAllTimersAsync().then(() => pending);
    expect(calls).toBe(2);
    expect(page.status).toBe(200);
    expect(page.error).toBe("");
    expect(page.retriesUsed).toBe(1);
    expect(rl.rateLimitHitCount).toBe(1);
  });

  it("exhausts 429 retries", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const fetchImpl = (async () => {
      calls += 1;
      return new Response("slow down", { status: 429 });
    }) as typeof fetch;
    const pending = fetchOnePage(
      { JQUANTS_API_KEY: API_KEY },
      "https://api.jquants.com/v2/markets/calendar",
      fetchImpl,
      limiter(),
    );
    const page = await vi.runAllTimersAsync().then(() => pending);
    expect(calls).toBe(4);
    expect(page.status).toBe(429);
    expect(page.error).toBe("transient HTTP 429 (retries exhausted)");
    expect(page.retriesUsed).toBe(4);
  });
});

describe("fetchDataset", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("plans publication dates across midnight without changing bounded manual requests", () => {
    const scheduled = (id: string, at: string) => requestQueries(datasetById(id)!, {
      scheduledAt: Date.parse(at),
    });
    // Friday's derivatives publish on Saturday; no weekday shortcut.
    expect(scheduled("derivatives_bars_daily_options_225", "2026-10-03T03:15:00+09:00"))
      .toEqual([{ date: "2026-10-02" }]);
    expect(scheduled("fins_summary", "2026-10-01T01:15:00+09:00"))
      .toEqual([{ date: "2026-09-30" }]);
    expect(scheduled("markets_margin_interest", "2026-10-01T07:15:00+09:00"))
      .toEqual([{ published_date: "2026-09-30" }]);
    expect(scheduled("equities_master", "2026-10-02T18:15:00+09:00"))
      .toEqual([{ date: "2026-10-02" }]); // Never prefetch tomorrow into CURRENT.
    expect(requestQueries(datasetById("equities_bars_daily")!, {
      from: "2020-09-30", to: "2020-10-01", scheduledAt: Date.parse("2026-10-01T02:15:00+09:00"),
    })).toEqual([{ date: "2020-09-30" }, { date: "2020-10-01" }]);
  });

  it("collects margin publications without changing historical date queries or nullable fields", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-28T08:00:00Z"));
    const spec = datasetById("markets_margin_interest")!;
    const row = { Date: "2026-09-25", Code: "86970", PubDate: "2026-09-28",
      IssType: "2", LongVol: 225000, ShrtVol: 257400, LongVal: 450000000,
      ShrtVal: 514800000, LongNegVal: 163800000, ShrtNegVal: 485600000,
      LongStdVal: 286200000, ShrtStdVal: 29200000 };
    const legacy = { ...row, Date: "2026-09-18", PubDate: null, LongVal: null };
    const urls: string[] = [];
    const fetchImpl = (async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify({ data: [row, legacy] }));
    }) as typeof fetch;
    const result = await fetchDataset({ JQUANTS_API_KEY: API_KEY }, spec, {}, fetchImpl, limiter());
    expect(new URL(urls[0]).search).toBe("?published_date=2026-09-28");
    expect(result.rows).toEqual([row, legacy]);
    expect(requestQueries(spec, { from: "2026-09-18", to: "2026-09-18" })).toEqual([{ date: "2026-09-18" }]);
    expect(pickAvailableAt(row, spec, "2026-09-28T17:00:00+09:00")).toBe("2026-09-29T00:00:00+09:00");
    expect(pickAvailableAt(legacy, spec, "2026-09-28T17:00:00+09:00")).toBe("2026-09-28T17:00:00+09:00");
  });

  it("fails closed when JQUANTS_API_KEY is missing", async () => {
    const spec = datasetById("markets_calendar");
    expect(spec).toBeDefined();
    let calls = 0;
    const fetchImpl = (async () => {
      calls += 1;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    const out = await fetchDataset(
      { JQUANTS_API_KEY: "" },
      spec!,
      { from: "2024-06-03", to: "2024-06-03" },
      fetchImpl,
      limiter(),
    );
    expect(calls).toBe(0);
    expect(out.error).toBe("JQUANTS_API_KEY not bound on worker");
    expect(out.rowsSeen).toBe(0);
  });

  it("follows pagination_key then stops", async () => {
    const spec = datasetById("markets_calendar");
    expect(spec).toBeDefined();
    const urls: string[] = [];
    const fetchImpl = (async (input: string | URL | Request) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("pagination_key=next")) {
        return new Response(JSON.stringify({ data: [{ n: 2 }] }), { status: 200 });
      }
      return new Response(
        JSON.stringify({ data: [{ n: 1 }], pagination_key: "next" }),
        { status: 200 },
      );
    }) as typeof fetch;
    const pages: number[] = [];
    const out = await fetchDataset(
      { JQUANTS_API_KEY: API_KEY },
      spec!,
      { from: "2024-06-03", to: "2024-06-03" },
      fetchImpl,
      limiter(),
      async (rows, page) => {
        pages.push(page.number);
        expect(rows).toHaveLength(1);
      },
    );
    expect(out.error).toBe("");
    expect(out.rowsSeen).toBe(2);
    expect(out.rows.map((row) => row.n)).toEqual([1, 2]);
    expect(pages).toEqual([1, 2]);
    expect(urls).toHaveLength(2);
    expect(urls[0]).toContain("https://api.jquants.com/v2/markets/calendar");
    expect(urls[0]).not.toContain("pagination_key=");
    expect(urls[1]).toContain("pagination_key=next");
    expect(urls.join("\n")).not.toContain(API_KEY);
  });
});
