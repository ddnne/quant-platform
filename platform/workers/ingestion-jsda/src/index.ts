/// <reference types="@cloudflare/workers-types" />
/**
 * JSDA raw acquisition on Cloudflare.
 *
 * Scope (v0):
 *   - Fetch public index + data files for the 3 governed JSDA series.
 *   - Store verbatim bytes under R2: raw/jsda/{dataset}/{yyyy}/{basename}
 *   - Write a lightweight run log into D1 ingestion_run_log (source=jsda).
 *
 * Not in v0 (explicit):
 *   - XLS/XLSX structured parse (needs xlrd/openpyxl or a future WASM path).
 *   - Coverage V2 COMPLETE proof for JSDA (requires structured rows).
 *
 * Auth: INGESTION_RUN_TOKEN for /v1/run (optional for health). Cron needs none.
 */

export interface Env {
  RAW_BUCKET: R2Bucket;
  DB: D1Database;
  INGESTION_RUN_TOKEN?: string;
  USER_AGENT?: string;
}

const UA =
  "quant-platform-ingest/0.1 (+personal-research; JSDA bond stats)";

const OTC_INDEX =
  "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html";
const REPO_INDEX = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/";
const CORP_INDEX =
  "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/";

const LINK_RE = /<a\s+[^>]*href=["']([^"']+)["']/gi;
const DATA_EXT = [".csv", ".xlsx", ".xls"];

type DatasetId =
  | "jsda_otc_bond_reference_prices"
  | "jsda_tokyo_repo_rates"
  | "jsda_corporate_bond_transactions";

interface FetchItem {
  dataset: DatasetId;
  url: string;
  kind: "index" | "data";
}

function authorized(request: Request, expected?: string): boolean {
  if (!expected) return false;
  return (request.headers.get("X-Ingestion-Token") || "") === expected;
}

function absolutize(base: string, href: string): string {
  try {
    return new URL(href, base).toString();
  } catch {
    return href;
  }
}

function isDataUrl(url: string): boolean {
  const path = new URL(url).pathname.toLowerCase();
  return DATA_EXT.some((ext) => path.endsWith(ext));
}

function basename(url: string): string {
  const path = new URL(url).pathname;
  const name = path.split("/").filter(Boolean).pop() || "index.html";
  return name;
}

function extractLinks(html: string, base: string): string[] {
  const out: string[] = [];
  LINK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = LINK_RE.exec(html)) !== null) {
    const abs = absolutize(base, m[1].replace(/&amp;/g, "&").trim());
    if (abs.startsWith("http")) out.push(abs);
  }
  return [...new Set(out)];
}

async function getText(url: string, ua: string): Promise<{ status: number; text: string }> {
  const resp = await fetch(url, {
    headers: { "User-Agent": ua, Accept: "text/html,*/*" },
    redirect: "follow",
  });
  const text = await resp.text();
  return { status: resp.status, text };
}

async function getBytes(
  url: string,
  ua: string,
): Promise<{ status: number; bytes: ArrayBuffer; contentType: string }> {
  const resp = await fetch(url, {
    headers: { "User-Agent": ua, Accept: "*/*" },
    redirect: "follow",
  });
  return {
    status: resp.status,
    bytes: await resp.arrayBuffer(),
    contentType: resp.headers.get("content-type") || "application/octet-stream",
  };
}

async function putRaw(
  env: Env,
  dataset: DatasetId,
  keySuffix: string,
  body: ArrayBuffer | string,
  contentType: string,
): Promise<string> {
  const year = new Date().toISOString().slice(0, 4);
  const key = `raw/jsda/${dataset}/${year}/${keySuffix}`;
  await env.RAW_BUCKET.put(key, body, {
    httpMetadata: { contentType },
    customMetadata: { source: "jsda", dataset, storedAt: new Date().toISOString() },
  });
  return key;
}

async function collectDataset(
  env: Env,
  dataset: DatasetId,
  indexUrl: string,
  ua: string,
  opts: { maxDataFiles: number },
): Promise<{
  dataset: DatasetId;
  status: "pass" | "fail" | "partial";
  indexStatus: number;
  filesStored: number;
  keys: string[];
  detail: string;
}> {
  const keys: string[] = [];
  try {
    const index = await getText(indexUrl, ua);
    if (index.status >= 400) {
      return {
        dataset,
        status: "fail",
        indexStatus: index.status,
        filesStored: 0,
        keys,
        detail: `index HTTP ${index.status}`,
      };
    }
    const indexKey = await putRaw(
      env,
      dataset,
      `index-${new Date().toISOString().slice(0, 10)}.html`,
      index.text,
      "text/html; charset=utf-8",
    );
    keys.push(indexKey);

    const links = extractLinks(index.text, indexUrl).filter(isDataUrl);
    // Drop non-data attachments (repo appointment docs live next to rate files).
    const dataOnly = links.filter((u) => {
      const p = u.toLowerCase();
      return !["reference", "bessi", "kijun", "koubo", "youkou"].some((x) =>
        p.includes(x),
      );
    });
    // Prefer repo history xls and recent-looking names first.
    const ranked = dataOnly.sort((a, b) => {
      const score = (u: string) => {
        const p = u.toLowerCase();
        let s = 0;
        if (p.includes("trrts")) s += 100;
        if (p.includes("torihiki")) s += 40;
        if (p.endsWith(".csv")) s += 10;
        if (p.endsWith(".xls") || p.endsWith(".xlsx")) s += 5;
        const year = p.match(/20\d{2}/g);
        if (year) s += Math.max(...year.map(Number)) - 2000;
        return s;
      };
      return score(b) - score(a);
    });

    let stored = 0;
    const errors: string[] = [];
    for (const url of ranked.slice(0, opts.maxDataFiles)) {
      try {
        const file = await getBytes(url, ua);
        if (file.status >= 400) {
          errors.push(`${basename(url)}:HTTP${file.status}`);
          continue;
        }
        const key = await putRaw(
          env,
          dataset,
          basename(url),
          file.bytes,
          file.contentType,
        );
        keys.push(key);
        stored++;
        // Be polite to JSDA origin.
        await new Promise((r) => setTimeout(r, 500));
      } catch (e) {
        errors.push(`${basename(url)}:${(e as Error).message}`);
      }
    }

    const status =
      stored > 0 ? "pass" : ranked.length === 0 ? "partial" : "fail";
    return {
      dataset,
      status,
      indexStatus: index.status,
      filesStored: stored,
      keys,
      detail:
        ranked.length === 0
          ? "index ok; no data-file links discovered on root (year archives may require deeper crawl)"
          : errors.length
            ? `stored=${stored}; errors=${errors.slice(0, 5).join("|")}`
            : `stored=${stored} of ${Math.min(ranked.length, opts.maxDataFiles)}`,
    };
  } catch (e) {
    return {
      dataset,
      status: "fail",
      indexStatus: 0,
      filesStored: 0,
      keys,
      detail: (e as Error).message || String(e),
    };
  }
}

async function runAll(
  env: Env,
  triggeredBy: "cron" | "manual",
): Promise<Record<string, unknown>> {
  const ua = env.USER_AGENT || UA;
  const startedAt = new Date().toISOString();
  const plans: { dataset: DatasetId; url: string; max: number }[] = [
    { dataset: "jsda_otc_bond_reference_prices", url: OTC_INDEX, max: 3 },
    { dataset: "jsda_tokyo_repo_rates", url: REPO_INDEX, max: 3 },
    { dataset: "jsda_corporate_bond_transactions", url: CORP_INDEX, max: 3 },
  ];

  const results = [];
  for (const plan of plans) {
    results.push(await collectDataset(env, plan.dataset, plan.url, ua, {
      maxDataFiles: plan.max,
    }));
  }

  const passed = results.filter((r) => r.status === "pass").length;
  const failed = results.filter((r) => r.status === "fail").length;
  const finishedAt = new Date().toISOString();
  const summary = {
    startedAt,
    finishedAt,
    status: failed === 0 ? (passed === results.length ? "pass" : "partial") : "partial",
    triggeredBy,
    datasetCount: results.length,
    passed,
    failed,
    results,
  };

  try {
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
       VALUES (?, 'jsda', 'cloudflare', ?, ?)`,
    )
      .bind(startedAt, summary.status, JSON.stringify(summary))
      .run();
  } catch (e) {
    // D1 write is best-effort for v0 raw path.
    (summary as Record<string, unknown>).d1Error = (e as Error).message;
  }

  return summary;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({
        ok: true,
        worker: "ingestion-jsda",
        datasets: 3,
        note:
          "raw R2 acquisition only; structured XLS/XLSX parse remains Python until Workers path lands",
      });
    }
    if (url.pathname === "/v1/run") {
      if (!authorized(request, env.INGESTION_RUN_TOKEN)) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      const summary = await runAll(env, "manual");
      return Response.json({ ok: true, summary });
    }
    return Response.json({ error: "not found" }, { status: 404 });
  },

  async scheduled(
    _event: ScheduledEvent,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(runAll(env, "cron"));
  },
};
